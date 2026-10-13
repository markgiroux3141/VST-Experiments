"""Fitting device models to digitized datasheet data.

The 6386 fit uses three digitized figures from the GE ET-T1113 sheet, plus its
tabulated operating points:
  - plate characteristics   Ip(Vp) at 15 grid voltages
  - transfer characteristics Ip(Vg) at 5 plate voltages
  - cascode transconductance gm(Vg1) on a log scale. This is the most direct
    picture of the remote-cutoff law, so the fit weights it heavily: it *is*
    the compression law. It is reproduced by solving the two-section cascode
    of the datasheet's test circuit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import least_squares

from varimu.config import DATA_DIR
from varimu.devices.triode import VariMuTriode

DATASHEETS = DATA_DIR / "datasheets"


@dataclass(frozen=True)
class Data6386:
    plate: np.ndarray  # columns vg, vp, ip
    transfer: np.ndarray  # columns vp, vg, ip
    cascode_gm: np.ndarray  # columns ecc2, vg1, gm
    published: dict


def load_6386(root: Path = DATASHEETS) -> Data6386:
    def csv(name):
        return np.loadtxt(root / name, delimiter=",", skiprows=1)

    with open(root / "published_points.yaml", encoding="utf-8") as f:
        published = yaml.safe_load(f)["6386"]
    return Data6386(
        csv("ge_6386_plate.csv"),
        csv("ge_6386_transfer.csv"),
        csv("ge_6386_cascode_gm.csv"),
        published,
    )


def cascode_current(ip, vg1, vgu, eb, iters: int = 64):
    """Plate current of the datasheet cascode (lower grid vg1, upper grid vgu, supply eb).

    Bisects the midpoint voltage X so that Ip_lower(vg1, X) = Ip_upper(vgu - X, eb - X).
    The difference is monotonic in X, so plain bisection is robust and vectorizes.
    """
    vg1, vgu, eb = np.broadcast_arrays(*(np.asarray(a, float) for a in (vg1, vgu, eb)))
    lo, hi = np.zeros_like(vg1), eb.copy()
    for _ in range(iters):
        x = 0.5 * (lo + hi)
        f = ip(vg1, x) - ip(vgu - x, eb - x)
        lo, hi = np.where(f < 0, x, lo), np.where(f < 0, hi, x)
    return ip(vg1, 0.5 * (lo + hi))


def cascode_gm(ip, vg1, ecc2, eb=250.0, dv=0.01):
    """gm of the ET-T1113 p.3 test circuit: upper grid at Ecc2/2 via 470k/470k."""
    vgu = np.asarray(ecc2, float) / 2
    vg1 = np.asarray(vg1, float)
    return (cascode_current(ip, vg1 + dv, vgu, eb) - cascode_current(ip, vg1 - dv, vgu, eb)) / (
        2 * dv
    )


def _class_a_point(pub):
    """Self-consistent cathode-bias point: Vg = -Ip * Rk."""
    a = pub["class_a1"]
    return -a["ip_a"] * a["rk_ohm"], a["vp_v"]


@dataclass(frozen=True)
class FitReport:
    plate_rms_ma: float
    plate_max_ma: float
    transfer_rms_ma: float
    transfer_max_ma: float
    gm_rms_log_pct: float  # RMS of |ln(model/data)| as a percentage
    gm_max_log_pct: float
    class_a: dict  # model vs published
    gm_100umho_vg: float  # model grid voltage where gm = 100 umho at Vp = 100 V

    def as_dict(self):
        return {
            k: (float(v) if isinstance(v, float | np.floating) else v)
            for k, v in self.__dict__.items()
        }


def evaluate_6386(model: VariMuTriode, data: Data6386) -> FitReport:
    from scipy.optimize import brentq

    from varimu.devices.triode import Triode

    t = Triode("6386", model)
    pe = (model.ip(data.plate[:, 0], data.plate[:, 1]) - data.plate[:, 2]) * 1e3
    te = (model.ip(data.transfer[:, 1], data.transfer[:, 0]) - data.transfer[:, 2]) * 1e3
    ge = (
        np.log(
            cascode_gm(model.ip, data.cascode_gm[:, 1], data.cascode_gm[:, 0])
            / data.cascode_gm[:, 2]
        )
        * 100
    )
    vg, vp = _class_a_point(data.published)
    class_a = {
        "ip_a": float(model.ip(vg, vp)),
        "gm_s": float(t.gm(vg, vp)),
        "rp_ohm": float(t.rp(vg, vp)),
    }
    class_a["mu"] = class_a["gm_s"] * class_a["rp_ohm"]
    vg100 = brentq(lambda v: t.gm(v, 100.0) - 1e-4, -60, -0.5)
    rms = lambda e: float(np.sqrt(np.mean(e**2)))  # noqa: E731
    return FitReport(
        rms(pe),
        float(np.max(np.abs(pe))),
        rms(te),
        float(np.max(np.abs(te))),
        rms(ge),
        float(np.max(np.abs(ge))),
        class_a,
        float(vg100),
    )


def _curve_slopes(x, y, groups, half_width):
    """Local slope dy/dx at each point from a linear fit over neighbours on the same curve."""
    out = np.zeros_like(x)
    for g in np.unique(groups):
        idx = np.where(groups == g)[0]
        xs, ys = x[idx], y[idx]
        for j, i in enumerate(idx):
            sel = np.abs(xs - xs[j]) <= half_width
            out[i] = np.polyfit(xs[sel], ys[sel], 1)[0] if sel.sum() >= 3 else 0.0
    return out


@dataclass(frozen=True)
class PitchDistribution:
    """Parametric distribution of the grid pitch along the cathode.

    The grid pitch is expressed as u = 1/mu, which sets each section's cutoff
    voltage of about -u * Vp. u is spread uniformly over [u_min, u_min + u_span],
    and the cathode share has log-density sum_k c_k * t^k, where t is in (0, 1)
    across that span. Discretized into n_sections parallel Koren sections. Steeply
    falling weights at coarse pitch give the near-exponential remote-cutoff tail
    seen on the datasheet's log gm plot.
    """

    u_min: float
    u_span: float
    coeffs: tuple[float, ...]
    n_sections: int = 32

    def sections(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        t = (np.arange(self.n_sections) + 0.5) / self.n_sections
        u = self.u_min + t * self.u_span
        lw = sum(c * t ** (k + 1) for k, c in enumerate(self.coeffs))
        w = np.exp(lw - np.max(lw))
        w /= w.sum()
        return tuple(float(m) for m in 1 / u), tuple(float(x) for x in w)

    def triode(self, ex, kg1, kp, kvb) -> VariMuTriode:
        mus, w = self.sections()
        return VariMuTriode(mus, w, float(ex), float(kg1), float(kp), float(kvb))


# Assumed uncertainties of the digitized curves (drawing + digitizing). Each
# residual is scaled by sqrt(sigma_y^2 + (slope * sigma_x)^2), the effective
# variance for errors in both coordinates, so steep parts of a curve aren't
# over-weighted.
SIG_I_REL, SIG_I_ABS = 0.02, 50e-6  # plate current
SIG_VP, SIG_VG = 1.5, 0.3  # V
SIG_LNGM = 0.05


def fit_6386(
    data: Data6386,
    *,
    n_sections: int = 32,
    degree: int = 3,
    gm_weight: float = 2.0,
    seed: int = 0,
    n_starts: int = 4,
    max_nfev: int = 3000,
) -> tuple[VariMuTriode, PitchDistribution]:
    """Least-squares fit of the pitch-distribution variable-mu model to all GE 6386 data.

    Each dataset is normalized by its point count. The cascode gm figure is
    weighted by `gm_weight` because it is the compression law. The class-A
    point and the "gm = 100 umho at -16 V" figure enter as soft constraints.
    """
    pub = data.published
    vg_a, vp_a = _class_a_point(pub)
    P, T, G = data.plate, data.transfer, data.cascode_gm

    sp = _curve_slopes(P[:, 1], P[:, 2], P[:, 0], 10.0)
    st = _curve_slopes(T[:, 1], T[:, 2], T[:, 0], 2.0)
    sg = _curve_slopes(G[:, 1], np.log(G[:, 2]), G[:, 0], 2.0)
    w_p = 1 / np.sqrt((SIG_I_REL * P[:, 2] + SIG_I_ABS) ** 2 + (sp * SIG_VP) ** 2) / np.sqrt(len(P))
    w_t = 1 / np.sqrt((SIG_I_REL * T[:, 2] + SIG_I_ABS) ** 2 + (st * SIG_VG) ** 2) / np.sqrt(len(T))
    w_g = gm_weight / np.sqrt(SIG_LNGM**2 + (sg * SIG_VG) ** 2) / np.sqrt(len(G))

    def unpack(x):
        dist = PitchDistribution(
            float(np.exp(x[0])),
            float(np.exp(x[1])),
            tuple(float(c) for c in x[2 : 2 + degree]),
            n_sections,
        )
        return dist.triode(*np.exp(x[2 + degree :])), dist

    def resid(x):
        m, _ = unpack(x)
        d = 1e-3
        gm_a = (m.ip(vg_a + d, vp_a) - m.ip(vg_a - d, vp_a)) / (2 * d)
        rp_a = 2 * d / (m.ip(vg_a, vp_a + d) - m.ip(vg_a, vp_a - d))
        gm16 = (m.ip(-16 + d, 100.0) - m.ip(-16 - d, 100.0)) / (2 * d)
        g = np.maximum(cascode_gm(m.ip, G[:, 1], G[:, 0]), 1e-12)
        return np.concatenate(
            [
                (m.ip(P[:, 0], P[:, 1]) - P[:, 2]) * w_p,
                (m.ip(T[:, 1], T[:, 0]) - T[:, 2]) * w_t,
                np.log(g / G[:, 2]) * w_g,
                [
                    np.log(m.ip(vg_a, vp_a) / pub["class_a1"]["ip_a"]) / 0.05,
                    np.log(gm_a / pub["class_a1"]["gm_s"]) / 0.05,
                    np.log(rp_a / pub["class_a1"]["rp_ohm"]) / 0.10,
                    np.log(gm16 / pub["gm_100umho_at"]["gm_s"]) / 0.15,
                ],
            ]
        )

    lo = np.r_[np.log([1 / 500, 1e-3]), np.full(degree, -150.0), np.log([1.0, 10.0, 1.0, 1.0])]
    hi = np.r_[np.log([1 / 2, 1.0]), np.full(degree, 150.0), np.log([2.5, 1e5, 5e3, 1e5])]
    rng = np.random.default_rng(seed)
    best = None
    for k in range(n_starts):
        jit = 0.3 if k else 0.0
        x0 = np.r_[
            np.log(1 / 40) + rng.normal(0, jit),
            np.log(1 / 3 - 1 / 40) + rng.normal(0, jit),
            np.where(np.arange(degree) == 0, -2.0, 0.0) + rng.normal(0, 3 * jit, degree),
            np.log([1.4, 1400.0, 200.0, 300.0]),
        ]
        sol = least_squares(
            resid,
            np.clip(x0, lo + 1e-6, hi - 1e-6),
            bounds=(lo, hi),
            x_scale="jac",
            max_nfev=max_nfev,
        )
        if best is None or sol.cost < best.cost:
            best = sol
    return unpack(best.x)

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


# --- Power supply devices (Phase 3) -------------------------------------------------


def load_csv(name: str, root: Path = DATASHEETS) -> np.ndarray:
    """A digitized curve (see data/datasheets/README.md) as an array, header skipped."""
    return np.loadtxt(root / name, delimiter=",", skiprows=1, ndmin=2)


@dataclass(frozen=True)
class CurveFit:
    """Fit residuals on the digitized points, in each point's estimated error (sigma)."""

    rms_sigma: float
    max_sigma: float
    rms_pct: float  # RMS of 100 * (model / data - 1)

    def as_dict(self):
        return {k: float(v) for k, v in self.__dict__.items()}


def _report(model_i, data_i, sigma) -> CurveFit:
    z = (model_i - data_i) / sigma
    return CurveFit(
        float(np.sqrt(np.mean(z**2))),
        float(np.max(np.abs(z))),
        float(100 * np.sqrt(np.mean((model_i / data_i - 1) ** 2))),
    )


def fit_koren_triode(vg, vp, ip, sigma):
    """Koren triode (mu, ex, kg1, kp, kvb) by least squares on plate-curve points
    (each weighted by its sigma). Returns (KorenTriode, CurveFit)."""
    from varimu.devices.triode import KorenTriode

    vg, vp, ip, sigma = (np.asarray(a, float) for a in (vg, vp, ip, sigma))

    def make(x):
        return KorenTriode(*np.exp(x))

    def resid(x):
        return (make(x).ip(vg, vp) - ip) / sigma

    best = None
    for x0 in ([10.0, 1.35, 1000.0, 50.0, 30.0], [10.0, 1.4, 500.0, 300.0, 300.0]):
        sol = least_squares(resid, np.log(x0), x_scale="jac", max_nfev=20000)
        if best is None or sol.cost < best.cost:
            best = sol
    m = make(best.x)
    return m, _report(m.ip(vg, vp), ip, sigma)


def fit_koren_pentode(plate, screen, plate_sigma, screen_sigma, ex: float | None = None):
    """Koren pentode (mu, ex, kg1, kg2, kp, kvb) by least squares on plate-current points
    `plate` (columns vg1, vg2, vp, ip) and screen-current points `screen` (vg1, vg2,
    ig2), jointly: mu sets both. `ex` fixed if given. Returns (KorenPentode, plate
    CurveFit, screen CurveFit)."""
    from varimu.devices.pentode import KorenPentode

    plate, screen = np.asarray(plate, float), np.asarray(screen, float)

    def make(x):
        e = np.exp(x)
        if ex is None:
            return KorenPentode(e[0], e[1], e[2], e[3], e[4], e[5])
        return KorenPentode(e[0], ex, e[1], e[2], e[3], e[4])

    def resid(x):
        m = make(x)
        rp = (m.ip(plate[:, 0], plate[:, 1], plate[:, 2]) - plate[:, 3]) / plate_sigma
        rs = (m.ig2(screen[:, 0], screen[:, 1]) - screen[:, 2]) / screen_sigma
        return np.r_[rp, rs]

    x0 = [25.0, 1.35, 3000.0, 20000.0, 100.0, 20.0]
    if ex is not None:
        x0.pop(1)
    sol = least_squares(resid, np.log(x0), x_scale="jac", max_nfev=20000)
    m = make(sol.x)
    return (
        m,
        _report(m.ip(plate[:, 0], plate[:, 1], plate[:, 2]), plate[:, 3], plate_sigma),
        _report(m.ig2(screen[:, 0], screen[:, 1]), screen[:, 2], screen_sigma),
    )


def fit_junction_diode(v, i, sigma, name: str = "fit"):
    """Shockley diode with series resistance (is, n, rs) by least squares on forward
    points. Returns (JunctionDiode, CurveFit)."""
    from varimu.devices.diode import JunctionDiode

    v, i, sigma = (np.asarray(a, float) for a in (v, i, sigma))

    def make(x):
        return JunctionDiode(name, *np.exp(x))

    def resid(x):
        return (make(x).i(v) - i) / sigma

    best = None
    for x0 in ([1e-6, 5.0, 1.0], [1e-4, 10.0, 0.5], [1e-8, 3.0, 2.0]):
        sol = least_squares(resid, np.log(x0), x_scale="jac", max_nfev=20000)
        if best is None or sol.cost < best.cost:
            best = sol
    m = make(best.x)
    return m, _report(m.i(v), i, sigma)

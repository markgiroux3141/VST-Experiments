"""A plate reverb's plate (docs/REVERB_PLAN.md, E6): the component, the decay its damper
sets, and the Python reference of its modes and impulse response (circuitsim's plate.rs
is the port; the two agree within rounding, tests/test_plate.py).

**The plate** (Ducceschi & Webb, ICA 2016, eqs. 1, 10-13; Russo, MSc thesis 2021, eqs.
3.10, 3.37-3.41): a thin steel plate under tension T0 (N/m), simply supported, its modes
Phi_m = sqrt(4 / (Lx Ly)) sin(m1 pi x / Lx) sin(m2 pi y / Ly) (unit norm) at
omega_m^2 = (T0 / (rho H)) b + (D / (rho H)) b^2, b = (m1 pi / Lx)^2 + (m2 pi / Ly)^2,
D = E H^3 / (12 (1 - nu^2)). A point force P drives each mode,
q'' + 2 s q' + omega^2 q = Phi_m(x_in) P / (rho H), and the pickup reads the
acceleration sum q_m'' Phi_m(x_out): the EMT 140's pickups are accelerometers (Russo
2021, p.3; ceramic contact pickups in the EMT 140 TS brochure, pp.3-4).

**Losses.** A mode's amplitude decays as exp(-s t), s = sigma_E(f) / 2, with sigma_E the
plate's energy decay rate at the mode's frequency (T60 = 6 ln 10 / sigma_E). sigma_E comes
from the EMT 140's measured decay curves (the 1971 brochure's reverberation time against
frequency for three damper settings, data/datasheets/emt_140ts_decay.csv): the damper is
set by the decay at 500 Hz, as the real unit's remote scale reads (Russo 2021, p.59), and
between two curves sigma_E is interpolated by where the setting falls at 500 Hz. The
loss mechanisms' formulas (thermoelastic, radiation: Russo eqs. 3.12-3.19, Arcas &
Chaigne 2010) are kept here as a cross-check (`physics_decay`); they disagree with the
brochure by ~20% in the midrange and ~2x at 10 kHz (reports/reverb/).

**The response** at rate fs: h[k] = T a(kT) for k >= 1 (impulse invariance; h[0], the
force's instantaneous share, is never used: the pickup is a distance away), each mode
summed until it has decayed by tail_db, the modes below min(f_max, 0.45 fs).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

SIX_LN10 = 6.0 * math.log(10.0)


@dataclass(frozen=True)
class PlateComponent:
    """A plate component version (config/components/<name>/<N>.yaml, kind `plate`)."""

    name: str
    lx_m: float
    ly_m: float
    thickness_m: float
    density_kg_m3: float
    youngs_pa: float
    poisson: float
    tension_n_m: float
    drive_xy: tuple[float, float]
    pickup_xy: tuple[float, float]
    exciter_re_ohm: float
    exciter_le_h: float
    exciter_bl_tm: float
    pickup_v_per_m_s2: float
    pickup_c_f: float
    f_max_hz: float
    tail_db: float
    # The measured decay curves: a frequency grid and, per curve, T60 (s) at each.
    decay_f_hz: tuple[float, ...]
    decay_curves_s: tuple[tuple[float, ...], ...]

    def t500_range(self) -> tuple[float, float]:
        """The damper's range: the curves' decay at 500 Hz, shortest and longest."""
        i = self.decay_f_hz.index(500.0)
        t = [c[i] for c in self.decay_curves_s]
        return min(t), max(t)


def plate_from_data(d: dict[str, Any], name: str) -> PlateComponent:
    p, pos, ex, pu, m, dec = (
        d["plate"],
        d["positions"],
        d["exciter"],
        d["pickup"],
        d["model"],
        d["decay"],
    )
    return PlateComponent(
        name=name,
        lx_m=float(p["lx_m"]),
        ly_m=float(p["ly_m"]),
        thickness_m=float(p["thickness_m"]),
        density_kg_m3=float(p["density_kg_m3"]),
        youngs_pa=float(p["youngs_pa"]),
        poisson=float(p["poisson"]),
        tension_n_m=float(p["tension_n_m"]),
        drive_xy=(float(pos["drive_xy"][0]), float(pos["drive_xy"][1])),
        pickup_xy=(float(pos["pickup_xy"][0]), float(pos["pickup_xy"][1])),
        exciter_re_ohm=float(ex["re_ohm"]),
        exciter_le_h=float(ex["le_h"]),
        exciter_bl_tm=float(ex["bl_tm"]),
        pickup_v_per_m_s2=float(pu["v_per_m_s2"]),
        pickup_c_f=float(pu["c_f"]),
        f_max_hz=float(m["f_max_hz"]),
        tail_db=float(m["tail_db"]),
        decay_f_hz=tuple(float(f) for f in dec["f_hz"]),
        decay_curves_s=tuple(tuple(float(t) for t in c["t60_s"]) for c in dec["curves"]),
    )


def decay_table(c: PlateComponent, t500_s: float) -> tuple[tuple[float, float], ...]:
    """The energy decay rate (Hz, 1/s) for the damper set to `t500_s` at 500 Hz: between
    the two measured curves around it, weighted by where it falls at 500 Hz (clamped to the
    curves' range). Plain arithmetic, as varimu-circuit's plate.rs does it."""
    i500 = c.decay_f_hz.index(500.0)
    rates = [[SIX_LN10 / t for t in curve] for curve in c.decay_curves_s]
    order = sorted(range(len(rates)), key=lambda k: rates[k][i500])
    lo, hi = c.t500_range()
    t = min(max(t500_s, lo), hi)
    target = SIX_LN10 / t
    a, b = order[0], order[-1]
    for j in range(len(order) - 1):
        if rates[order[j]][i500] <= target <= rates[order[j + 1]][i500]:
            a, b = order[j], order[j + 1]
            break
    ra, rb = rates[a][i500], rates[b][i500]
    w = 0.0 if rb == ra else (target - ra) / (rb - ra)
    return tuple(
        (f, (1.0 - w) * sa + w * sb)
        for f, sa, sb in zip(c.decay_f_hz, rates[a], rates[b], strict=True)
    )


def plate_impedance_ns_per_m(c: PlateComponent) -> float:
    """The plate's driving-point impedance, that of an infinite plate: 8 sqrt(D rho H)
    (Cremer & Heckl, Structure-Borne Sound; resistive, so the coil's load is a resistor)."""
    h = c.thickness_m
    # h * h * h, not h**3: the Rust builder multiplies (bit for bit, tests/agreement.rs).
    d = c.youngs_pa * (h * h * h) / (12.0 * (1.0 - c.poisson * c.poisson))
    return 8.0 * math.sqrt(d * c.density_kg_m3 * h)


# --- The reference --------------------------------------------------------------------


@dataclass(frozen=True)
class PlateSpec:
    """What the IR's Plate element carries (varimu.circuit.ir.Plate's medium fields)."""

    lx_m: float
    ly_m: float
    thickness_m: float
    density_kg_m3: float
    youngs_pa: float
    poisson: float
    tension_n_m: float
    drive_xy: tuple[float, float]
    pickup_xy: tuple[float, float]
    f_max_hz: float
    decay: tuple[tuple[float, float], ...]
    tail_db: float

    @classmethod
    def of(cls, el: Any) -> PlateSpec:
        """From an IR Plate element (or anything with its fields)."""
        return cls(
            el.lx_m,
            el.ly_m,
            el.thickness_m,
            el.density_kg_m3,
            el.youngs_pa,
            el.poisson,
            el.tension_n_m,
            tuple(el.drive_xy),
            tuple(el.pickup_xy),
            el.f_max_hz,
            tuple(tuple(d) for d in el.decay),
            el.tail_db,
        )


def energy_decay(table: tuple[tuple[float, float], ...], f_hz: np.ndarray) -> np.ndarray:
    """sigma_E at f_hz: linear in log frequency between the table's points, held at its
    ends."""
    fs = np.array([p[0] for p in table])
    ss = np.array([p[1] for p in table])
    return np.interp(np.log(f_hz), np.log(fs), ss)


def stiffness(p: PlateSpec) -> tuple[float, float]:
    """kappa^2 = D / (rho H) (m^4/s^2) and T0 / (rho H) (m^2/s^2)."""
    rho_h = p.density_kg_m3 * p.thickness_m
    d = p.youngs_pa * p.thickness_m**3 / (12.0 * (1.0 - p.poisson * p.poisson))
    return d / rho_h, p.tension_n_m / rho_h


def modes(p: PlateSpec, f_top_hz: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(omega, amplitude decay rate, weight) of the modes below f_top_hz, (m1, m2) order
    (m1 outer); weight = Phi(x_in) Phi(x_out) / (rho H)."""
    kappa2, tension = stiffness(p)
    rho_h = p.density_kg_m3 * p.thickness_m
    w2_top = (2.0 * math.pi * f_top_hz) ** 2
    m1_max = 1
    while (
        tension * (m1_max * math.pi / p.lx_m) ** 2 + kappa2 * (m1_max * math.pi / p.lx_m) ** 4
        <= w2_top
    ):
        m1_max += 1
    m2_max = 1
    while (
        tension * (m2_max * math.pi / p.ly_m) ** 2 + kappa2 * (m2_max * math.pi / p.ly_m) ** 4
        <= w2_top
    ):
        m2_max += 1
    m1 = np.arange(1, m1_max)[:, None]
    m2 = np.arange(1, m2_max)[None, :]
    kx, ky = m1 * math.pi / p.lx_m, m2 * math.pi / p.ly_m
    b = kx * kx + ky * ky
    w2 = tension * b + kappa2 * b * b
    keep = w2 <= w2_top
    sx = np.sin(m1 * math.pi * p.drive_xy[0]) * np.sin(m1 * math.pi * p.pickup_xy[0])
    sy = np.sin(m2 * math.pi * p.drive_xy[1]) * np.sin(m2 * math.pi * p.pickup_xy[1])
    weight = (4.0 / (p.lx_m * p.ly_m)) * sx * sy / rho_h
    omega = np.sqrt(w2[keep])
    decay = 0.5 * energy_decay(p.decay, omega / (2.0 * math.pi))
    return omega, decay, np.broadcast_to(weight, w2.shape)[keep]


def impulse_response(p: PlateSpec, fs: float) -> np.ndarray:
    """Force (N) to acceleration (m/s^2) at fs (see the module docs)."""
    omega, s, w = modes(p, min(p.f_max_hz, 0.45 * fs))
    ok = (w != 0) & (omega > s)
    omega, s, w = omega[ok], s[ok], w[ok]
    t = 1.0 / fs
    ln_tail = abs(p.tail_db) / 20.0 * math.log(10.0)
    lens = np.ceil(ln_tail / s * fs).astype(np.int64) + 1
    n = int(min(lens.max(), 60 * int(fs)))
    h = np.zeros(n)
    wd = np.sqrt(omega * omega - s * s)
    ca = t * w * (-2.0 * s)
    cb = t * w * (s * s - wd * wd) / wd
    chunk, group = 1 << 12, 256
    for k0 in range(0, n, chunk):
        k = np.arange(k0, min(k0 + chunk, n))
        kt = k[None, :] * t
        live = np.flatnonzero(lens > k0)
        for g0 in range(0, len(live), group):
            j = live[g0 : g0 + group]
            env = np.exp(-s[j, None] * kt)
            ph = wd[j, None] * kt
            terms = env * (ca[j, None] * np.cos(ph) + cb[j, None] * np.sin(ph))
            terms[k[None, :] >= lens[j, None]] = 0.0
            h[k0 : k0 + len(k)] += terms.sum(axis=0)
    h[0] = 0.0
    return h


def physics_decay(c: PlateComponent, f_hz: np.ndarray) -> dict[str, np.ndarray]:
    """The loss mechanisms' energy decay rates (1/s) by formula, for the cross-check:
    thermoelastic (Russo eq. 3.12, Arcas & Chaigne 2010; SAE 1010: R1 9.664e-3, C1
    0.1855e-3 m^2/s) and radiation into free air (Russo eqs. 3.15-3.19, Maidanik's form
    with g(psi) = [(1 - psi^2) ln((1 + psi) / (1 - psi)) + 2 psi] / (1 - psi^2)^(3/2), the
    standard form: Russo prints a product in the logarithm; air 1.2 kg/m^3, 343 m/s)."""
    r1, c1 = 9.664e-3, 0.1855e-3
    h = c.thickness_m
    w = 2.0 * math.pi * f_hz
    thermo = w * w * r1 * c1 / (2.0 * (w * w * h * h + c1 * c1 / (h * h)))
    rho_a, c_a = 1.2, 343.0
    kappa = math.sqrt(
        stiffness(
            PlateSpec(
                c.lx_m,
                c.ly_m,
                h,
                c.density_kg_m3,
                c.youngs_pa,
                c.poisson,
                0.0,
                c.drive_xy,
                c.pickup_xy,
                1.0,
                ((1.0, 0.0),),
                1.0,
            )
        )[0]
    )
    f_c = c_a * c_a / (2.0 * math.pi * kappa)
    psi = np.sqrt(np.minimum(f_hz / f_c, 0.999))
    g = ((1 - psi**2) * np.log((1 + psi) / (1 - psi)) + 2 * psi) / (1 - psi**2) ** 1.5
    rho_h = c.density_kg_m3 * h
    rad = (
        (1.0 / (4.0 * math.pi**2))
        * (rho_a * c_a / rho_h)
        * (2.0 * (c.lx_m + c.ly_m) / (c.lx_m * c.ly_m))
        * (c_a / f_c)
        * g
    )
    return {"thermoelastic": thermo, "radiation": rad, "total": thermo + rad}

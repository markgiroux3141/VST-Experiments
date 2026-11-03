"""Fitting the lumped thyratron (varimu.devices.thyratron) to its data sheets.

**The 2D21** is fitted in full: its sheets are the only ones found that publish the event's
physics. Targets: Sylvania's control family at shield-grid volts 0, +2, +8 (the strike, in
grid volts), the grid's pre-conduction ion current where it rises into the strike, the grid
current during conduction (as a fraction of the anode current), and RCA's tabulated drop
(8 V), ionization time (0.5 us) and deionization times (35 us at -100 V, 75 us at -10 V).
The leakage is fitted alone (the before-conduction curves' flat parts, linear in the anode
volts). Fixed: the gas's levels (NIST), the thresholds' softness and the arc's electron
temperature and grid floating potential (provisional), the background floor (numerics).

**The 884** has a control characteristic and a drop (16 V) but no times. It takes the 2D21's
fitted structure (the cathode's barrier, the supply, the ionization rate, the plasma's
scales and grid collection) with argon's levels; it fits its anode control ratio and
barrier offset to its control curve and its stepwise ionization to its drop; and its
plasma's transport (diffusion and grid collection) is the 2D21's scaled by argon's ion
mobility over xenon's (provisional: equal pressure and geometry). RCA's own sweep circuit
and its frequency table are the check (`varimu.devices.thyratron_fit.rca_sweep`), not a
target: the table is "approximate" and implies a ~2x larger sweep than the control curve.

Observables:
- the strike: the stable pre-breakdown state meeting the unstable one. `margin` is the
  least dx/dt / x over the pre-breakdown densities (negative: the grid holds the tube off);
  the strike is where it crosses 0, found by root finding (smooth in the parameters);
- the arc: anode current given, (V_a, x) where the ion balance closes;
- ionization time: RCA's test (100 V through a load for 0.5 A, a 50 V grid step from an
  assumed -10 V), until the anode has fallen 90% of the way to the drop: Va is algebraic in
  x there, so the time is a quadrature over ln x;
- deionization: the arc at 0.1 A from 125 V, the anode current stopped; the time until the
  plasma has decayed (at its loss rate, the anode at 0 V) below the separatrix of a tube with
  125 V reapplied.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
from scipy.optimize import brentq, least_squares, minimize_scalar

from varimu.devices.thyratron import AR_ION_EV, AR_META_EV, XE_ION_EV, XE_META_EV, Thyratron

DATA = Path(__file__).resolve().parents[2] / "data" / "datasheets"

# Fixed (provisional: model knowledge): the thresholds' softness (the electrons' energy
# spread at the threshold), the arc's electron temperature, the grid's floating potential
# in the arc (Sylvania's during-conduction curves cross near -0.6 V), the background
# ionization (numerics: a floor ~1e-11 of the strike's density).
W_ION_V = 0.3
W_META_V = 0.3
T_E_V = 0.3
V_FLOAT_V = -0.6
S0_PER_S = 1e-6
# Reduced mobilities of the atomic ions in their own gas at low field, cm^2 / (V s)
# (provisional: model knowledge, the standard tabulated values: Ar+ in Ar ~1.53, Xe+ in Xe
# ~0.58): the 884's plasma clears ~2.6x faster than the 2D21's at equal pressure and size.
MOBILITY_AR_XE = 1.53 / 0.58


def _w_range(t: Thyratron) -> tuple[float, float]:
    """The pre-breakdown densities (ln x): from the floor to well above the strike's
    (e_v / v_x, where the ions have lowered the barrier by its tail energy), below any arc."""
    lo = np.log(S0_PER_S * t.tau_diff_s) - 5.0
    hi = np.log(t.e_v / t.v_x_v) + 3.0
    return lo, hi


def margin(t: Thyratron, va: float, vg: float, vg2: float = 0.0) -> float:
    """The least dx/dt / x over the pre-breakdown densities: < 0 while the grid holds."""
    lo, hi = _w_range(t)

    def f(w):
        x = np.exp(w)
        return float(t.dx_dt(va, vg2, vg, x)) / x

    ws = np.linspace(lo, hi, 60)
    k = int(np.argmin([f(w) for w in ws]))
    a, b = ws[max(k - 1, 0)], ws[min(k + 1, len(ws) - 1)]
    r = minimize_scalar(f, bounds=(a, b), method="bounded", options={"xatol": 1e-9})
    return float(r.fun)


def strike_vg(t: Thyratron, va: float, vg2: float = 0.0) -> float:
    """The control-grid volts at which the tube strikes with va on its anode."""
    lo, hi = -150.0, 20.0
    if margin(t, va, lo, vg2) >= 0 or margin(t, va, hi, vg2) < 0:
        return np.nan
    return brentq(lambda vg: margin(t, va, vg, vg2), lo, hi, xtol=1e-6)


def stable_x(t: Thyratron, va: float, vg: float, vg2: float = 0.0) -> float | None:
    """The pre-breakdown density (the stable root), or None if the tube can't hold off."""
    lo, hi = _w_range(t)
    ws = np.linspace(lo, hi, 400)
    r = np.array([float(t.dx_dt(va, vg2, vg, np.exp(w))) for w in ws])
    neg = np.where(r < 0)[0]
    if len(neg) == 0:
        return None
    k = neg[0]
    if k == 0:
        return float(np.exp(ws[0]))
    g = lambda w: float(t.dx_dt(va, vg2, vg, np.exp(w)))  # noqa: E731
    return float(np.exp(brentq(g, ws[k - 1], ws[k])))


def arc(t: Thyratron, ia: float, vg: float, vg2: float = 0.0) -> tuple[float, float]:
    """(V_a, x) of a steady arc carrying ia."""

    def va_of(w):
        x = np.exp(w)
        f = lambda v: float(t.anode_a(v, vg2, vg, x)) - ia  # noqa: E731
        if f(700.0) < 0 or f(-5.0) > 0:
            return np.nan
        return brentq(f, -5.0, 700.0, xtol=1e-10)

    def g(w):
        va = va_of(w)
        return np.nan if np.isnan(va) else float(t.dx_dt(va, vg2, vg, np.exp(w)))

    ws = np.linspace(-5.0, 15.0, 200)
    gs = np.array([g(w) for w in ws])
    ok = np.isfinite(gs)
    s = np.where(ok[:-1] & ok[1:] & (np.sign(gs[:-1]) > 0) & (np.sign(gs[1:]) < 0))[0]
    if len(s) == 0:
        return np.nan, np.nan
    w = brentq(g, ws[s[-1]], ws[s[-1] + 1], xtol=1e-10)
    return va_of(w), float(np.exp(w))


def ionization_time(
    t: Thyratron, vsup=100.0, ipk=0.5, vbias=-10.0, pulse=50.0, drop=8.0, vg2=0.0
) -> float:
    """RCA's ionization-time test (vbias assumed): the time from the grid's step until the
    anode has fallen 90% of the way to the drop."""
    rl = (vsup - drop) / ipk
    vg = vbias + pulse

    def va_of(w):
        x = np.exp(min(w, 30.0))
        return brentq(lambda v: v - vsup + rl * float(t.anode_a(v, vg2, vg, x)), -100.0, vsup + 1.0)

    x0 = stable_x(t, vsup, vbias, vg2)
    if x0 is None:
        return np.nan
    target = drop + 0.1 * (vsup - drop)
    w0 = np.log(x0)
    if va_of(30.0) > target:
        return np.nan
    w1 = brentq(lambda w: va_of(w) - target, w0, 30.0)
    ws = np.linspace(w0, w1, 2000)
    r = np.array([float(t.dx_dt(va_of(w), vg2, vg, np.exp(w))) / np.exp(w) for w in ws])
    if np.any(r <= 0):
        return np.nan
    return float(np.trapezoid(1.0 / r, ws))


def deionization_time(t: Thyratron, vg: float, va=125.0, ia=0.1, vg2=0.0) -> float:
    """RCA's deionization test: the arc at ia stopped; the time until the plasma is below the
    separatrix of the tube with va reapplied (it decays at its loss rate meanwhile)."""
    _, x_arc = arc(t, ia, vg, vg2)
    ws = np.linspace(_w_range(t)[0], 12.0, 3000)
    r = np.array([float(t.dx_dt(va, vg2, vg, np.exp(w))) for w in ws])
    neg = np.where(r < 0)[0]
    if len(neg) == 0 or not np.isfinite(x_arc):
        return np.nan
    k = neg[-1]
    if k + 1 >= len(ws):
        return 0.0
    g = lambda w: float(t.dx_dt(va, vg2, vg, np.exp(w)))  # noqa: E731
    xu = np.exp(brentq(g, ws[k], ws[k + 1]))
    return float(np.log(x_arc / xu) / t.loss_per_s(vg)) if x_arc > xu else 0.0


# --- the 2D21 -----------------------------------------------------------------------


def _at(c, key, xcol, ycol, x):
    s = c[c[:, 0] == key]
    s = s[np.argsort(s[:, xcol])]
    return float(np.interp(x, s[:, xcol], s[:, ycol]))


def targets_2d21(data: Path = DATA) -> dict:
    ctl = np.loadtxt(data / "sylvania_2d21_control.csv", delimiter=",", skiprows=1)
    bef = np.loadtxt(data / "sylvania_2d21_grid_before.csv", delimiter=",", skiprows=1)
    dur = np.loadtxt(data / "sylvania_2d21_grid_during.csv", delimiter=",", skiprows=1)
    control = [
        (va, vs, _at(ctl, vs, 1, 2, va))
        for vs, vas in (
            (0.0, (650, 500, 400, 300, 200, 150, 100, 70, 55)),
            (2.0, (650, 400, 200, 100, 50)),
            (8.0, (650, 400, 200, 100, 50)),
        )
        for va in vas
    ]
    flats = []
    knee = []
    for va in (25.0, 200.0, 400.0, 600.0):
        s = bef[bef[:, 0] == va]
        s = s[np.argsort(s[:, 1])]
        base = s[(s[:, 1] < -10) & (s[:, 1] > -15), 2].mean()
        flats.append((va, base))
        if va < 100:
            continue
        ion = s[:, 2] - base
        for lvl in (-2e-9, -4e-9, -8e-9, -15e-9):
            k = np.where(ion < lvl)[0]
            if len(k):
                knee.append((va, s[k[0], 1], lvl))
    flats = np.array(flats)
    g_leak = float(np.polyfit(flats[:, 0], -flats[:, 1], 1)[0])
    during = [
        (ia, vg, _at(dur, ia, 1, 2, vg))
        for ia in (0.025, 0.05, 0.1, 0.15, 0.2)
        for vg in (-7.0, -5.0, -3.0, -2.0, -1.5)
    ]
    return {"control": control, "knee": knee, "during": during, "g_leak_s": g_leak}


# Fitted in log where positive and scale-free.
FREE_2D21 = (
    "mu_a",
    "mu_g2",
    "v0_v",
    "e_v",
    "perveance",
    "x_n",
    "v_x_v",
    "k_ion",
    "c_meta",
    "tau_diff_s",
    "k_grid",
    "p_grid",
    "q_s_c",
)
LINEAR = {"mu_a", "mu_g2", "v0_v", "e_v", "p_grid"}

# The converged fit (2026-11-02, 80 evaluations from the prototype's result: cost 339 -> 208;
# control 0.29 V rms, knee 0.91 (ln), during 0.0042 (Ig / Ia), drop 8.68 V, ionization 0.30
# us, deionization 78 / 38.6 us): the start, so `fit-devices` polishes rather than refits.
START_2D21 = dict(
    mu_a=262.69696018520983,
    mu_g2=3.218856993347048,
    v0_v=0.14764451300634288,
    e_v=0.460996829997864,
    perveance=2.9451987877851485e-05,
    x_n=38.00131096232554,
    v_x_v=2.0989978705045593,
    k_ion=357784999.040512,
    c_meta=0.21482688977622594,
    tau_diff_s=1.7863712062297545e-05,
    k_grid=20942.876987614305,
    p_grid=0.20422878717910176,
    q_s_c=1.859658673918004e-11,
)


def tube_2d21(values: dict, g_leak_s: float, caps: dict) -> Thyratron:
    return Thyratron(
        "2D21",
        mu_a=values["mu_a"],
        mu_g2=values["mu_g2"],
        v0_v=values["v0_v"],
        e_v=values["e_v"],
        perveance=values["perveance"],
        x_n=values["x_n"],
        v_x_v=values["v_x_v"],
        k_ion=values["k_ion"],
        v_ion_v=XE_ION_EV,
        w_ion_v=W_ION_V,
        c_meta=values["c_meta"],
        v_meta_v=XE_META_EV,
        w_meta_v=W_META_V,
        tau_diff_s=values["tau_diff_s"],
        k_grid=values["k_grid"],
        p_grid=values["p_grid"],
        v_float_v=V_FLOAT_V,
        t_e_v=T_E_V,
        q_s_c=values["q_s_c"],
        g_leak_s=g_leak_s,
        s0_per_s=S0_PER_S,
        c_gk=caps.get("gk", 0.0),
        c_ga=caps.get("ga", 0.0),
        c_ak=caps.get("ak", 0.0),
    )


def residuals_2d21(t: Thyratron, tg: dict) -> dict[str, np.ndarray]:
    """Each target's residuals, in units of its tolerance."""
    out = {}
    out["control"] = np.array([(strike_vg(t, va, vs) - vg) / 0.1 for va, vs, vg in tg["control"]])
    knee = []
    for va, vg, lvl in tg["knee"]:
        x = stable_x(t, va, vg)
        ion = float(t.grid1_a(va, vg, x)) - t.g_leak_s * (vg - va) if x is not None else 1.0
        knee.append(np.log(max(-ion, 1e-15) / -lvl) / 0.3)
    out["knee"] = np.array(knee)
    during = []
    for ia, vg, ig in tg["during"]:
        va, x = arc(t, ia, vg)
        during.append((float(t.grid1_a(va, vg, x)) - ig) / ia / 0.002)
    out["during"] = np.array(during)
    va, _ = arc(t, 0.1, -10.0)
    out["drop"] = np.array([(va - 8.0) / 0.3])
    out["ionization"] = np.array([np.log(max(ionization_time(t), 1e-12) / 0.5e-6) / 0.1])
    out["deionization"] = np.array(
        [
            np.log(max(deionization_time(t, -10.0), 1e-7) / 75e-6) / 0.05,
            np.log(max(deionization_time(t, -100.0), 1e-7) / 35e-6) / 0.05,
        ]
    )
    return {k: np.nan_to_num(v, nan=100.0, posinf=100.0, neginf=-100.0) for k, v in out.items()}


def fit_2d21(data: Path = DATA, max_nfev: int = 60, start: dict | None = None, verbose=0):
    """Least squares on the 2D21's sheets. Returns (tube, report)."""
    import yaml

    tg = targets_2d21(data)
    caps = yaml.safe_load((data / "published_points.yaml").read_text())["2D21"]["capacitances_f"]
    caps = {"gk": caps["input"], "ga": caps["g1a"], "ak": caps["output"]}
    start = dict(start or START_2D21)

    def unpack(th):
        v = {}
        for k, x in zip(FREE_2D21, th, strict=True):
            v[k] = x if k in LINEAR else float(np.exp(x))
        return v

    def resid(th):
        try:
            r = residuals_2d21(tube_2d21(unpack(th), tg["g_leak_s"], caps), tg)
            return np.concatenate(list(r.values()))
        except (ValueError, ZeroDivisionError, FloatingPointError):
            n = len(tg["control"]) + len(tg["knee"]) + len(tg["during"]) + 4
            return np.full(n, 100.0)

    th0 = np.array([start[k] if k in LINEAR else np.log(start[k]) for k in FREE_2D21])
    sol = least_squares(resid, th0, diff_step=1e-4, max_nfev=max_nfev, verbose=verbose)
    t = tube_2d21(unpack(sol.x), tg["g_leak_s"], caps)
    r = residuals_2d21(t, tg)
    report = {
        "nfev": int(sol.nfev),
        "cost": float(sol.cost),
        "status": sol.message,
        "control_rms_v": float(np.sqrt(np.mean((r["control"] * 0.1) ** 2))),
        "knee_rms_ln": float(np.sqrt(np.mean((r["knee"] * 0.3) ** 2))),
        "during_rms_ig_per_ia": float(np.sqrt(np.mean((r["during"] * 0.002) ** 2))),
        "drop_v": float(arc(t, 0.1, -10.0)[0]),
        "ionization_time_s": ionization_time(t),
        "deionization_time_s": {
            "-10": deionization_time(t, -10.0),
            "-100": deionization_time(t, -100.0),
        },
    }
    return t, report


# --- the 884 ------------------------------------------------------------------------


def fit_884(base: Thyratron, data: Path = DATA, mobility: float = MOBILITY_AR_XE):
    """The 884 from the 2D21's structure (see the module docstring). Returns (tube, report)."""
    import yaml

    pub = yaml.safe_load((data / "published_points.yaml").read_text())["884"]
    ctl = np.loadtxt(data / "rca_884_control.csv", delimiter=",", skiprows=1)
    vas = np.linspace(40.0, 290.0, 11)
    order = np.argsort(ctl[:, 1])
    vgs = np.interp(vas, ctl[order, 1], ctl[order, 0])
    caps = pub["capacitances_f"]
    drop = float(pub["tube_drop_v"])

    def tube(mu_a, v0, c_meta):
        return dataclasses.replace(
            base,
            name="884",
            mu_a=mu_a,
            mu_g2=None,
            v0_v=v0,
            v_ion_v=AR_ION_EV,
            v_meta_v=AR_META_EV,
            c_meta=c_meta,
            tau_diff_s=base.tau_diff_s / mobility,
            k_grid=base.k_grid * mobility,
            c_gk=caps["gk"],
            c_ga=caps["ga"],
            c_ak=caps["ak"],
        )

    def resid(th):
        t = tube(th[0], th[1], float(np.exp(th[2])))
        r = [(strike_vg(t, va) - vg) / 0.1 for va, vg in zip(vas, vgs, strict=True)]
        va, _ = arc(t, 0.1, -10.0)
        r.append((va - drop) / 0.3)
        return np.nan_to_num(np.array(r), nan=100.0)

    mu0 = -np.polyfit(vgs, vas, 1)[0]
    th0 = np.array([mu0, base.v0_v, np.log(base.c_meta)])
    sol = least_squares(resid, th0, diff_step=1e-4, max_nfev=200)
    t = tube(sol.x[0], sol.x[1], float(np.exp(sol.x[2])))
    r = resid(sol.x)
    report = {
        "nfev": int(sol.nfev),
        "control_rms_v": float(np.sqrt(np.mean((r[:-1] * 0.1) ** 2))),
        "control_max_v": float(np.max(np.abs(r[:-1] * 0.1))),
        "drop_v": float(arc(t, 0.1, -10.0)[0]),
        "mobility_ratio": mobility,
        # RCA's 2D21 tests with the grid where an 884 holds 100-125 V off (-20 V)
        "ionization_time_s": ionization_time(t, vbias=-20.0, drop=drop),
        "deionization_time_s": {
            "-20": deionization_time(t, -20.0),
            "-100": deionization_time(t, -100.0),
        },
    }
    return t, report

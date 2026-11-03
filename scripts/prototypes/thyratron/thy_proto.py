"""Prototype: a lumped thyratron (2D21) and its observables, for fitting."""

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

sp = lambda z: np.logaddexp(0.0, z)  # noqa: E731

P0 = dict(
    mu_a=250.0,  # anode control ratio
    mu_s=2.6,  # shield-grid control ratio
    v0=0.0,  # barrier offset (V)
    e_v=0.2,  # barrier tail energy (V)
    g_s=1e-3,  # electron supply perveance (A/V^1.5)
    x_n=50.0,  # density at which ions double the supply
    a=2.6e6,  # ionization rate per (V A) (1/(V A s))
    v_i=12.13,  # xenon's first ionization potential (eV)
    w_i=0.3,  # its softness (V)
    c_m=60.0,  # stepwise (metastable) ionization, relative
    v_m=8.315,  # xenon's lowest metastable level (eV)
    w_m=0.3,
    v_x=80.0,  # barrier lowering per unit density (V)
    tau_d=15e-6,  # ambipolar diffusion time (s)
    k_g0=2e4,  # grid ion collection (1/s per V^p)
    p_g=0.9,
    v_f=-0.6,  # grid floating potential (V)
    t_e=0.3,  # electron temperature (eV)
    q_s=5e-10,  # charge of the plasma at x = 1 (C)
    g_leak=4e-11,  # anode-grid leakage (S)
    s0=1e-6,  # background ionization (1/s): numerics floor
)


def control(p, va, vg, vs):
    return vg + vs / p["mu_s"] + va / p["mu_a"]


def ie(p, va, vg, vs, x):
    vc = control(p, va, vg, vs)
    ev = p["e_v"]
    d = ev * sp((va - vc) / ev)
    vx = p["v_x"] * x
    phi = vc + d * vx / (vx + d)  # screened: d * y / (1 + y), y = v_x x / d
    phi = phi - ev * sp((phi - va) / ev)  # the anode must collect them too: softmin(phi, va)
    return p["g_s"] * (1.0 + x / p["x_n"]) * (ev * sp((phi - p["v0"]) / ev)) ** 1.5


def nu(p, va, x):
    return p["w_i"] * sp((va - p["v_i"]) / p["w_i"]) + p["c_m"] * x / p["x_n"] * p["w_m"] * sp(
        (va - p["v_m"]) / p["w_m"]
    )


def kg(p, vg):
    return p["k_g0"] * (p["t_e"] * sp((p["v_f"] - vg) / p["t_e"])) ** p["p_g"]


def rate(p, va, vg, vs, x):
    """dx/dt."""
    loss = 1.0 / p["tau_d"] + kg(p, vg)
    return p["a"] * nu(p, va, x) * ie(p, va, vg, vs, x) + p["s0"] - x * loss


def ig(p, va, vg, x):
    el = kg(p, p["v_f"]) * 2.0 * np.exp(-sp((p["v_f"] - vg) / p["t_e"]))
    return p["g_leak"] * (vg - va) + p["q_s"] * x * (el - kg(p, vg))


XS = np.geomspace(1e-14, 30.0, 4000)


def holds(p, va, vg, vs):
    """Whether a stable pre-breakdown state exists: the rate turns negative below the arc."""
    r = rate(p, va, vg, vs, XS)
    return bool(np.any(r < 0.0))


def stable_x(p, va, vg, vs):
    r = rate(p, va, vg, vs, XS)
    neg = np.where(r < 0.0)[0]
    if len(neg) == 0:
        return None
    k = neg[0]
    return brentq(lambda x: rate(p, va, vg, vs, x), XS[k - 1], XS[k]) if k > 0 else XS[0]


def vg_crit(p, va, vs, lo=-150.0, hi=20.0):
    if not holds(p, va, lo, vs):
        return np.nan
    if holds(p, va, hi, vs):
        return np.nan
    for _ in range(50):
        m = 0.5 * (lo + hi)
        if holds(p, va, m, vs):
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def arc(p, ia, vg, vs=0.0):
    """(Va, x) of a steady arc at anode current ia."""

    def va_of(x):
        if ie(p, 700.0, vg, vs, x) < ia or ie(p, -5.0, vg, vs, x) > ia:
            return np.nan
        return brentq(lambda v: ie(p, v, vg, vs, x) - ia, -5.0, 700.0)

    f = lambda lx: rate(p, va_of(np.exp(lx)), vg, vs, np.exp(lx))  # noqa: E731
    lxs = np.linspace(-5, 15, 400)
    fs = np.array([f(v) for v in lxs])
    ok = np.isfinite(fs)
    s = np.where(ok[:-1] & ok[1:] & (np.diff(np.sign(fs)) != 0))[0]
    if len(s) == 0:
        return np.nan, np.nan
    lx = brentq(f, lxs[s[-1]], lxs[s[-1] + 1])
    return va_of(np.exp(lx)), np.exp(lx)


def simulate(p, t_end, va_fn, vg_fn, vs=0.0, w0=None, max_step=None):
    """The state ln x through time, the anode voltage and grid given as functions of t
    (or of (t, ia) via a series resistor: va_fn(t, x) -> va)."""

    def f(t, w):
        x = np.exp(w[0])
        va = va_fn(t, x)
        vg = vg_fn(t)
        return [rate(p, va, vg, vs, x) / x]

    if w0 is None:
        w0 = np.log(stable_x(p, va_fn(0.0, 1e-12), vg_fn(0.0), vs))
    return solve_ivp(
        f,
        (0, t_end),
        [w0],
        method="LSODA",
        rtol=1e-8,
        atol=1e-10,
        max_step=max_step or t_end / 200,
        dense_output=True,
    )


def series_va(p, vsup, r, vg_fn, vs=0.0):
    """Anode voltage of a tube fed from vsup through r, given x (solve Va = vsup - r Ie)."""

    def va(t, x):
        vg = vg_fn(t)
        return brentq(
            lambda v: v - vsup(t) + r * ie(p, v, vg, vs, x), -1.0, max(vsup(t), 0.0) + 1.0
        )

    return va


if __name__ == "__main__":
    p = P0
    for va in (600, 400, 200, 100, 50, 30):
        print(va, [round(vg_crit(p, va, vs), 2) for vs in (0.0, 2.0, 8.0)])
    for ia in (0.025, 0.1, 0.3):
        va, x = arc(p, ia, -5.0)
        print("arc", ia, va, x, ig(p, va, -5.0, x))

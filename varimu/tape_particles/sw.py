"""A Stoner-Wohlfarth particle: a single-domain macrospin with uniaxial anisotropy
(Stoner & Wohlfarth, Phil. Trans. R. Soc. A 240, 599 (1948)), its energy minima and the
barrier between them, and thermally activated switching over that barrier (Neel-Brown:
an Arrhenius rate f0 exp(-dE / kT)).

**Reduced units.** A particle with easy axis n, anisotropy K and magnetization Ms_p in a
field H: E / V = K sin^2(theta) - mu0 Ms_p H . m. With H_K = 2 K / (mu0 Ms_p) and
h = H / H_K, the energy is E = mu0 Ms_p H_K V e with

    e(theta) = 1/2 sin^2(theta) - a cos(theta) - b sin(theta),

theta the moment's angle from n toward u, a = h . n (signed) and b = |h - a n| >= 0 (u
the unit vector of h's part perpendicular to n). The moment stays in the plane of n and h
(the minima of the full energy on the sphere lie there). With b >= 0 both minima and the
saddle between them lie in theta in [0, pi]: e' = -b <= 0 at 0 and +b >= 0 at pi, so
[0, pi] holds one minimum, or two with a maximum between (the other maximum is in (pi,
2 pi)). The minimum nearer +n is state +, the other state -. Outside the astroid
(|a|^{2/3} + b^{2/3} > 1) one minimum survives: + if a > 0, else - (the state against the
field lost its basin: it switches without thermal help).

**Extrema** (`extrema`): e' on a fixed grid of `grid` points over [0, pi] (its sin / cos
precomputed), the sign changes bracketing each root, then safeguarded Newton inside each
bracket. A minimum and the saddle closer than a grid step (near the astroid, where the
barrier is ~(grid step)^3 and thermally negligible) are missed: the state then switches at
that step (the error is measured in tests/test_tape_particles.py).

**Rates** (`step`): two-state master equation over a step dt with the field held, solved
exactly: p+ relaxes to r-/(r+ + r-) at rate r+ + r- (r+: + -> -, f0 exp(-dE+ / kT)). The
`stochastic` variant samples the same two-state chain per particle (kinetic Monte Carlo).
"""

from __future__ import annotations

import math

import numpy as np

MU0 = 4e-7 * math.pi
KB = 1.380649e-23

#: b's floor: keeps e' strictly signed at the grid's ends (b = 0 puts the minima exactly
#: on them); 1e-6 so that f32 (the GPU) resolves it too.
B_FLOOR = 1e-6


def astroid_hsw(psi: np.ndarray) -> np.ndarray:
    """The switching field h_sw / H_K of a field at angle psi to the easy axis (the
    astroid): (cos^{2/3} + sin^{2/3})^{-3/2}."""
    c, s = np.abs(np.cos(psi)), np.abs(np.sin(psi))
    return (c ** (2.0 / 3.0) + s ** (2.0 / 3.0)) ** -1.5


def frame(n: np.ndarray, h: np.ndarray):
    """(a, b, u): h's component along the easy axes n (N x 3, unit), the magnitude of its
    perpendicular part and that part's direction (any perpendicular unit vector where it
    vanishes). h: N x 3."""
    a = np.einsum("ij,ij->i", h, n)
    perp = h - a[:, None] * n
    b = np.sqrt(np.einsum("ij,ij->i", perp, perp))
    # A perpendicular fallback: n x (the axis least aligned with n).
    alt = np.where(np.abs(n[:, :1]) < 0.9, np.array([[1.0, 0.0, 0.0]]), np.array([[0.0, 1.0, 0.0]]))
    fb = np.cross(n, alt)
    fb /= np.linalg.norm(fb, axis=1, keepdims=True)
    small = b < 1e-12
    u = np.where(small[:, None], fb, perp / np.where(small, 1.0, b)[:, None])
    return a, b, u


def energy(theta, a, b):
    return 0.5 * np.sin(theta) ** 2 - a * np.cos(theta) - b * np.sin(theta)


def _fp(theta, a, b):
    s, c = np.sin(theta), np.cos(theta)
    return s * c + a * s - b * c, (c * c - s * s) + a * c + b * s


def _refine(lo, hi, a, b, iters: int):
    """A root of e' in [lo, hi] (e' changes sign there), safeguarded Newton."""
    flo, _ = _fp(lo, a, b)
    t = 0.5 * (lo + hi)
    for _ in range(iters):
        f, d = _fp(t, a, b)
        same = np.sign(f) == np.sign(flo)
        lo = np.where(same, t, lo)
        flo = np.where(same, f, flo)
        hi = np.where(same, hi, t)
        with np.errstate(divide="ignore", invalid="ignore"):
            tn = t - f / d
        bad = ~np.isfinite(tn) | (tn <= lo) | (tn >= hi)
        t = np.where(bad, 0.5 * (lo + hi), tn)
    return t


_GRIDS: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def _grid(g: int):
    if g not in _GRIDS:
        th = np.linspace(0.0, math.pi, g)
        _GRIDS[g] = (th, np.sin(th), np.cos(th))
    return _GRIDS[g]


def extrema(a: np.ndarray, b: np.ndarray, grid: int = 32, iters: int = 10):
    """(theta+, theta-, theta_s, two): the minima nearer +n and -n and the saddle between
    them (radians in [0, pi]); where only one minimum exists (two False) theta+ = theta- =
    that minimum and theta_s is nan."""
    a = np.asarray(a, float)
    b = np.maximum(np.asarray(b, float), B_FLOOR)
    th, sg, cg = _grid(grid)
    f = sg[None, :] * cg[None, :] + a[:, None] * sg[None, :] - b[:, None] * cg[None, :]
    pos = f > 0.0
    rise = ~pos[:, :-1] & pos[:, 1:]  # e' - -> +: a minimum in that cell
    fall = pos[:, :-1] & ~pos[:, 1:]  # + -> -: a maximum
    nrise = rise.sum(axis=1)
    two = (nrise >= 2) & fall.any(axis=1)
    i_first = np.argmax(rise, axis=1)
    # The last rise: from the end.
    i_last = rise.shape[1] - 1 - np.argmax(rise[:, ::-1], axis=1)
    i_fall = np.argmax(fall, axis=1)
    step = th[1] - th[0]
    t1 = _refine(th[i_first], th[i_first] + step, a, b, iters)
    t2 = _refine(th[i_last], th[i_last] + step, a, b, iters)
    ts = _refine(th[i_fall], th[i_fall] + step, a, b, iters)
    # One minimum: t1 == t2 (the same cell).
    t2 = np.where(two, t2, t1)
    ts = np.where(two, ts, np.nan)
    return t1, t2, ts, two


def barriers(a, b, grid: int = 32, iters: int = 10):
    """(de+, de-, theta+, theta-, two): reduced barriers out of each state (e(saddle) -
    e(min)); where one minimum survives, the vanished state's barrier is 0 and the
    survivor's +inf."""
    t1, t2, ts, two = extrema(a, b, grid, iters)
    bb = np.maximum(np.asarray(b, float), B_FLOOR)
    es = energy(np.where(two, ts, 0.0), a, bb)
    dp = np.where(two, es - energy(t1, a, bb), np.where(a >= 0, np.inf, 0.0))
    dm = np.where(two, es - energy(t2, a, bb), np.where(a >= 0, 0.0, np.inf))
    return np.maximum(dp, 0.0), np.maximum(dm, 0.0), t1, t2, two


def _phi(x):
    """(1 - e^{-x}) / x, 1 at 0."""
    x = np.asarray(x, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = -np.expm1(-x) / x
    return np.where(x < 1e-12, 1.0, out)


def transition(dp, dm, two, a, e0_kt, f0_hz: float, dt_s: float):
    """Per particle over dt: (q+, q-) the probabilities that a particle starting in + ends
    in -, and starting in - ends in +. e0_kt: mu0 Ms_p H_K V_act / kT (the reduced energy's
    scale; K V_act / kT = e0_kt / 2). One minimum: the vanished state goes over surely."""
    with np.errstate(over="ignore"):
        rp = f0_hz * np.exp(-np.minimum(dp * e0_kt, 745.0))
        rm = f0_hz * np.exp(-np.minimum(dm * e0_kt, 745.0))
    rp = np.where(np.isinf(dp), 0.0, rp)
    rm = np.where(np.isinf(dm), 0.0, rm)
    g = dt_s * _phi((rp + rm) * dt_s)
    qp = np.where(two, rp * g, np.where(a >= 0, 0.0, 1.0))
    qm = np.where(two, rm * g, np.where(a >= 0, 1.0, 0.0))
    return np.clip(qp, 0.0, 1.0), np.clip(qm, 0.0, 1.0)


def moments(n, u, t1, t2):
    """The unit moments of the + and - states (N x 3 each)."""
    mp = np.cos(t1)[:, None] * n + np.sin(t1)[:, None] * u
    mm = np.cos(t2)[:, None] * n + np.sin(t2)[:, None] * u
    return mp, mm

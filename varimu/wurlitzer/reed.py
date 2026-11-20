"""A Wurlitzer reed as finite elements: a flat steel cantilever clamped under its screw, the
lead at its tip (docs/WURLITZER_PLAN.md, WZ1; "Reeds").

**The plane.** The reed moves in the vertical plane through its axis (the hammer's
direction): x along the reed from its clamped root (the reed screw's edge), w vertical, up
positive (the hammer strikes from below).

**The beam** is Euler-Bernoulli with cubic Hermite elements (w, w' per node; the Rhodes'
elements, `varimu.rhodes.beam`), a uniform rectangular section (its width b, thickness t).
The root is clamped rigidly: the reed bar is a casting, far stiffer than a reed. Shear and
rotary inertia of the steel are left out (t / L < 4%: under 0.2% on the first mode); the
large-swing term (Pfeifle DAFx-17 eq. 9) too (a cantilever's free tip shortens instead of
stretching: second order).

**The lead** is a uniform sleeve over `tip_length_m` at the free end (its mass spread along
it, consistent with the shape functions) with the rotary inertia of a block `tip_height_m`
high sitting on the reed's top face. Its mass sets the pitch with the free length, and the
second mode's ratio to the first (a bare cantilever: 6.27; heavier tips raise it, their
rotary inertia lowers it).

**Losses** are stiffness proportional, `C = eta / omega_1 K`: the fundamental's Q is
exactly 1 / eta, and higher modes decay faster as omega^2 (the clamp's and the lead's loss
are unsourced; WZ1's study compares the second mode's decay with the Pie-finger attacks).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy import linalg, optimize

from varimu.rhodes.beam import _beam_element, hermite


@dataclass(frozen=True)
class Reed:
    length_m: float  # free length, root to tip
    thickness_m: float
    width_m: float
    youngs_pa: float
    density_kg_m3: float
    tip_mass_kg: float
    tip_length_m: float
    tip_height_m: float
    loss: float = 0.0  # eta: the fundamental's 1 / Q
    element_m: float = 1.0e-3

    @property
    def tongue_mass_kg(self) -> float:
        return self.density_kg_m3 * self.width_m * self.thickness_m * self.length_m

    @property
    def ei(self) -> float:
        return self.youngs_pa * self.width_m * self.thickness_m**3 / 12


@dataclass(frozen=True)
class FE:
    m: np.ndarray
    k: np.ndarray
    x_m: np.ndarray  # node positions (root at 0 excluded)
    reed: Reed

    @property
    def n(self) -> int:
        return self.m.shape[0]

    def point(self, x_m: float, slope: bool = False) -> np.ndarray:
        """The row vector giving w (or w') at x from the dofs."""
        xs = np.concatenate([[0.0], self.x_m])
        x_m = float(np.clip(x_m, 0.0, xs[-1]))
        i = int(np.clip(np.searchsorted(xs, x_m, side="right") - 1, 0, xs.size - 2))
        h = xs[i + 1] - xs[i]
        shape = hermite((x_m - xs[i]) / h, h, slope)
        v = np.zeros(self.n)
        for j, (node, b) in enumerate(((i, 0), (i, 1), (i + 1, 0), (i + 1, 1))):
            if node > 0:  # the root is clamped
                v[2 * (node - 1) + b] += shape[j]
        return v


@dataclass(frozen=True)
class Modes:
    f_hz: np.ndarray
    omega: np.ndarray
    sigma: np.ndarray  # amplitude decay rate, 1/s
    phi: np.ndarray  # (n_dof, n_modes), mass normalized

    @property
    def q(self) -> np.ndarray:
        return self.omega / (2 * self.sigma)


def _mesh(r: Reed) -> np.ndarray:
    """Node positions from the root (0) to the tip; a node at the lead's start."""
    tip0 = r.length_m - r.tip_length_m
    xs = [0.0]
    for a, b in ((0.0, tip0), (tip0, r.length_m)):
        if b - a < 1e-6:
            continue
        n = max(1, int(np.ceil((b - a) / r.element_m)))
        xs += list(np.linspace(a, b, n + 1)[1:])
    return np.array(xs)


def assemble(r: Reed) -> FE:
    xs = _mesh(r)
    n_el = xs.size - 1
    n = 2 * n_el
    m = np.zeros((n, n))
    k = np.zeros((n, n))
    rho_a = r.density_kg_m3 * r.width_m * r.thickness_m
    for i in range(n_el):
        ke, me = _beam_element(xs[i + 1] - xs[i], r.ei, rho_a)
        dofs = [2 * (i - 1), 2 * (i - 1) + 1, 2 * i, 2 * i + 1]
        for a, da in enumerate(dofs):
            if da < 0:
                continue
            for b, db in enumerate(dofs):
                if db < 0:
                    continue
                k[da, db] += ke[a, b]
                m[da, db] += me[a, b]
    fe = FE(m, k, xs[1:], r)
    if r.tip_mass_kg > 0 and r.tip_length_m > 0:
        lo, hi = r.length_m - r.tip_length_m, r.length_m
        rho_l = r.tip_mass_kg / (hi - lo)
        # rotary inertia per length of a block tip_height high on the top face, about the
        # reed's mid-plane
        h, t = r.tip_height_m, r.thickness_m
        j_l = rho_l * (h * h / 12 + (t / 2 + h / 2) ** 2)
        g, w = np.polynomial.legendre.leggauss(6)
        xq = 0.5 * (hi - lo) * (g + 1) + lo
        wq = 0.5 * (hi - lo) * w
        for x, wt in zip(xq, wq, strict=True):
            v = fe.point(x)
            s = fe.point(x, slope=True)
            m += wt * (rho_l * np.outer(v, v) + j_l * np.outer(s, s))
        fe = FE(m, k, xs[1:], r)
    return fe


def modes(fe: FE, count: int | None = None, f_max_hz: float | None = None) -> Modes:
    """The modes (all, the lowest `count`, or those below f_max_hz) with the reed's
    stiffness-proportional decay rates."""
    sub = None if count is None else [0, min(count, fe.n) - 1]
    lam, phi = linalg.eigh(fe.k, fe.m, subset_by_index=sub)
    omega = np.sqrt(np.maximum(lam, 0.0))
    if f_max_hz is not None:
        keep = omega / (2 * np.pi) <= f_max_hz
        omega, phi = omega[keep], phi[:, keep]
    sigma = fe.reed.loss * omega**2 / (2 * omega[0])
    return Modes(omega / (2 * np.pi), omega, sigma, phi)


def fundamental_hz(r: Reed) -> float:
    return float(modes(assemble(r), count=1).f_hz[0])


def with_length(
    r: Reed, length_m: float, tip_mass_ratio: float, tip_length_m: float, max_tip_fraction: float
) -> Reed:
    """The reed at a free length, its lead's mass a ratio of the tongue's."""
    r = replace(r, length_m=length_m, tip_length_m=min(tip_length_m, max_tip_fraction * length_m))
    return replace(r, tip_mass_kg=tip_mass_ratio * r.tongue_mass_kg)


def tune(
    r: Reed,
    f_hz: float,
    tip_mass_ratio: float,
    tip_length_m: float,
    max_tip_fraction: float,
    lo_m: float = 4e-3,
    hi_m: float = 0.25,
) -> Reed:
    """The free length at which the reed (its lead `tip_mass_ratio` of its tongue) rings at
    f_hz: longer is lower."""

    def err(length: float) -> float:
        rr = with_length(r, length, tip_mass_ratio, tip_length_m, max_tip_fraction)
        return np.log(fundamental_hz(rr) / f_hz)

    if err(lo_m) < 0 or err(hi_m) > 0:
        raise ValueError(f"no free length in {lo_m}-{hi_m} m rings at {f_hz:.2f} Hz")
    length = optimize.brentq(err, lo_m, hi_m, xtol=1e-9)
    return with_length(r, length, tip_mass_ratio, tip_length_m, max_tip_fraction)


def stiffness_at(fe: FE, x_m: float) -> float:
    """The reed's static stiffness at x (N / m): a unit force there, the displacement."""
    v = fe.point(x_m)
    return float(1.0 / (v @ np.linalg.solve(fe.k, v)))

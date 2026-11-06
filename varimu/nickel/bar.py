"""A Nickel Organ bar: a brass cantilever with a laminated nickel strip bonded to its top
face over the root (docs/NICKEL_ORGAN_PLAN.md).

**The beam** is Euler-Bernoulli with cubic Hermite elements (varimu.rhodes.beam's), clamped
at x = 0 in the yoke. Over the strip, [0, l_s], the section is composite (brass below,
nickel above): EI about the composite neutral axis, rho A of both; beyond it, brass alone.
The strip's centroid sits d above that axis, so a curvature w'' strains it by -d w''
(bending up compresses the top face).

**The coupling to the magnet.** The strip's mean strain is eps = -d w'(l_s) / l_s (w'(0) = 0
at the clamp), so for mode k, s_k = d eps / d q_k = -d phi_k'(l_s) / l_s. varimu.nickel.magnet
explains why that one number per mode carries both directions.

**Tuning.** Each key's bar length is solved so its fundamental is the key's note
(`design`): the strip covers a quarter of the bar (10-40 mm, never past its middle).

**Losses** per mode: Q_k = Q_1 (f_1 / f_k)^q_exponent (the bell partials die first).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

import numpy as np
from scipy import linalg, optimize

from varimu.nickel import spec as nspec
from varimu.rhodes.beam import _beam_element, hermite


@dataclass(frozen=True)
class BarDesign:
    length_m: float
    strip_m: float
    brass_e: float
    brass_rho: float
    thickness_m: float
    width_m: float
    strip_e: float
    strip_rho: float
    strip_t_m: float


@dataclass(frozen=True)
class Bar:
    design: BarDesign
    freq_hz: np.ndarray  # the modes kept
    sigma_per_s: np.ndarray  # decay rates (amplitude), 1/s
    s_strip: np.ndarray  # d eps / d q_k
    phi_strike: np.ndarray  # mode shapes at the hammer
    phi_damper: np.ndarray  # ... and at the damper
    phi_tip: np.ndarray  # ... and at the tip
    strip_volume_m3: float
    strip_d_m: float  # the strip's centroid above the composite neutral axis


def section(dz: BarDesign, composite: bool) -> tuple[float, float, float]:
    """(EI, rho A, d): the section's bending stiffness, mass per length, and the strip's
    centroid above the neutral axis (0 without the strip)."""
    w, hb = dz.width_m, dz.thickness_m
    ab = w * hb
    if not composite:
        return dz.brass_e * w * hb**3 / 12, dz.brass_rho * ab, 0.0
    hn = dz.strip_t_m
    an = w * hn
    yb, yn = hb / 2, hb + hn / 2
    ea = dz.brass_e * ab + dz.strip_e * an
    yna = (dz.brass_e * ab * yb + dz.strip_e * an * yn) / ea
    ei = dz.brass_e * (w * hb**3 / 12 + ab * (yb - yna) ** 2) + dz.strip_e * (
        w * hn**3 / 12 + an * (yn - yna) ** 2
    )
    return ei, dz.brass_rho * ab + dz.strip_rho * an, yn - yna


def _mesh(dz: BarDesign, n_el: int = 40) -> np.ndarray:
    """Node positions: a node at the strip's end."""
    n1 = max(4, round(n_el * dz.strip_m / dz.length_m))
    n2 = max(4, n_el - n1)
    return np.concatenate(
        [np.linspace(0, dz.strip_m, n1 + 1), np.linspace(dz.strip_m, dz.length_m, n2 + 1)[1:]]
    )


def _assemble(dz: BarDesign) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = _mesh(dz)
    n = len(x)
    k = np.zeros((2 * n, 2 * n))
    m = np.zeros((2 * n, 2 * n))
    for e in range(n - 1):
        h = x[e + 1] - x[e]
        ei, ra, _ = section(dz, 0.5 * (x[e] + x[e + 1]) < dz.strip_m)
        ke, me = _beam_element(h, ei, ra)
        sl = slice(2 * e, 2 * e + 4)
        k[sl, sl] += ke
        m[sl, sl] += me
    # clamped at x = 0: drop w0, w0'
    return x, k[2:, 2:], m[2:, 2:]


def _shape(x: np.ndarray, vecs: np.ndarray, xq: float, slope: bool = False) -> np.ndarray:
    """Mode shapes (or slopes) at xq from the nodal vectors (clamped dofs dropped)."""
    full = np.vstack([np.zeros((2, vecs.shape[1])), vecs])
    e = int(np.clip(np.searchsorted(x, xq, side="right") - 1, 0, len(x) - 2))
    h = x[e + 1] - x[e]
    n = hermite((xq - x[e]) / h, h, slope)
    return n @ full[2 * e : 2 * e + 4]


def _eig(dz: BarDesign):
    x, k, m = _assemble(dz)
    w2, vecs = linalg.eigh(k, m)
    return x, np.sqrt(np.maximum(w2, 0)) / (2 * np.pi), vecs


def fundamental_hz(dz: BarDesign) -> float:
    return float(_eig(dz)[1][0])


def design(d: dict, f_hz: float) -> BarDesign:
    """The bar for a note: its length solved for the fundamental."""
    g = functools.partial(nspec.v, d)

    def dz(length):
        return BarDesign(
            length,
            min(
                max(g("strip.length_fraction") * length, g("strip.length_min_m")),
                g("strip.length_max_m"),
                0.5 * length,
            ),
            g("bar.youngs_pa"),
            g("bar.density_kg_m3"),
            g("bar.thickness_m"),
            g("bar.width_m"),
            g("strip.youngs_pa"),
            g("strip.density_kg_m3"),
            g("strip.thickness_m"),
        )

    # a uniform brass cantilever as the start: f = 1.8751^2 / (2 pi L^2) sqrt(EI / rho A)
    c = np.sqrt(g("bar.youngs_pa") * g("bar.thickness_m") ** 2 / (12 * g("bar.density_kg_m3")))
    l0 = np.sqrt(1.8751**2 * c / (2 * np.pi * f_hz))
    length = optimize.brentq(
        lambda ln: np.log(fundamental_hz(dz(ln)) / f_hz), 0.5 * l0, 2.0 * l0, xtol=1e-9
    )
    return dz(length)


def build(d: dict, f_hz: float) -> Bar:
    g = functools.partial(nspec.v, d)
    dz = design(d, f_hz)
    x, f, vecs = _eig(dz)
    keep = f < g("bar.modes_max_hz")
    f, vecs = f[keep], vecs[:, keep]
    _, _, dd = section(dz, True)
    slope_end = _shape(x, vecs, dz.strip_m, slope=True)
    q = g("bar.q_fundamental") * (f[0] / f) ** g("bar.q_exponent")
    return Bar(
        dz,
        f,
        2 * np.pi * f / (2 * q),
        -dd * slope_end / dz.strip_m,
        _shape(x, vecs, g("action.strike_fraction") * dz.length_m),
        _shape(x, vecs, g("action.damper_fraction") * dz.length_m),
        _shape(x, vecs, dz.length_m),
        dz.width_m * dz.strip_t_m * dz.strip_m,
        dd,
    )

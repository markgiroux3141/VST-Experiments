"""The groove: a surface written along arc length, read by a tip (docs/PHONO_PLAN.md, §1).

A hill-and-dale groove (cylinders) is one height per arc length s: the groove bottom's
height h(s) in metres, up (toward the stylus) positive, 0 the uncut surface, sampled every
`ds_m`. Because it is stored along s, not time, a player reads it at any speed.

Writing: a cutter whose tip sits `depth_m` below the surface plus its downward excursion
z(t) cuts h = -(depth + z) where that is below the surface; where the cutter lifts out of
the wax (depth + z < 0, an overloaded acoustic record's "blasting") the surface is left
uncut: h = min(0, -(depth + z)).

Reading: a spherical tip of radius R (along the groove) can't follow the bottom into
troughs narrower than itself. The lowest point of a rigid tip resting on the groove follows
the groove **dilated** by the tip's shape (grayscale morphological dilation):

    y(s) = max over |u| <= R of [h(s + u) + sqrt(R^2 - u^2) - R]

Tracing distortion (Pierce and Hunt 1938, Lewis and Hunt 1941) comes out of this geometry:
for h = A sin(ks), to second order, y = A sin(ks) + R A^2 k^2 / 4 (1 + cos 2ks) at the
tip's contact point, a second harmonic R A k^2 / 4 of the fundamental (`tracing_h2`).

The tip meets the dilated surface through a Hertz contact (sphere on a flat, Johnson,
Contact Mechanics, ch. 4): F = K delta^(3/2), K = (4/3) E* sqrt(R_eff), plus Hunt and
Crossley's damping F = K delta^(3/2) (1 + alpha d(delta)/dt) while in contact. Where the
force would go negative the tip leaves the groove: mistracking is F = 0, no special case.

Roughness (seeded): a Gaussian height field along s with rms `sigma_m` and an exponential
correlation length, drawn from `default_rng([seed, crc32(name)])`.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np
from scipy.signal import lfilter


@dataclass
class Groove:
    h_m: np.ndarray  # groove bottom height per sample along s, up positive
    ds_m: float

    @property
    def length_m(self) -> float:
        return len(self.h_m) * self.ds_m

    def s_m(self) -> np.ndarray:
        return np.arange(len(self.h_m)) * self.ds_m


def write(z_m: np.ndarray, groove_speed_m_s: float, fs_hz: float, depth_m: float) -> Groove:
    """The groove cut by a cutter whose downward excursion is z_m (sampled at fs_hz while
    the surface passes at groove_speed_m_s) about a mean depth depth_m."""
    h = np.minimum(0.0, -(depth_m + np.asarray(z_m, dtype=float)))
    return Groove(h_m=h, ds_m=groove_speed_m_s / fs_hz)


def tip_profile(radius_m: float, ds_m: float, reach_m: float | None = None):
    """The tip's shape b(u) = sqrt(R^2 - u^2) - R on the groove's grid, out to `reach_m`
    (default R). Returns (offsets in samples, b)."""
    reach = radius_m if reach_m is None else min(reach_m, radius_m)
    n = int(np.floor(reach / ds_m))
    k = np.arange(-n, n + 1)
    u = k * ds_m
    return k, np.sqrt(np.maximum(radius_m**2 - u**2, 0.0)) - radius_m


def dilate(h_m: np.ndarray, ds_m: float, radius_m: float) -> np.ndarray:
    """The tip's lowest point resting on the groove at each s (the grayscale dilation of h
    by the tip). Offsets beyond the groove's relief can't touch and are skipped: a point
    u away is lower than the centre by R - sqrt(R^2 - u^2), so only |u| up to where that
    exceeds h's peak-to-peak can matter."""
    return dilate_contact(h_m, ds_m, radius_m, contact=False)[0]


def dilate_contact(
    h_m: np.ndarray, ds_m: float, radius_m: float, contact: bool = True
) -> tuple[np.ndarray, np.ndarray | None]:
    """`dilate`, plus (with contact) the index of the groove sample the tip touches at
    each s (the argmax; the first on ties)."""
    h = np.asarray(h_m, dtype=float)
    relief = float(np.max(h) - np.min(h)) if len(h) else 0.0
    reach = np.sqrt(max(2.0 * radius_m * relief - relief**2, 0.0)) + 2 * ds_m
    ks, b = tip_profile(radius_m, ds_m, reach)
    n = len(h)
    out = np.full(n, -np.inf)
    pad = int(np.max(np.abs(ks)))
    # Beyond the groove's ends the surface continues at its end values.
    hp = np.concatenate([np.full(pad, h[0]), h, np.full(pad, h[-1])])
    idx = np.arange(n) if contact else None
    for k, bk in zip(ks, b, strict=True):
        cand = hp[pad + k : pad + k + n] + bk
        if contact:
            better = cand > out
            idx[better] = np.clip(np.arange(n)[better] + k, 0, n - 1)
            out[better] = cand[better]
        else:
            np.maximum(out, cand, out=out)
    return out, idx


def tracing_h2(radius_m: float, amplitude_m: float, wavelength_m: float) -> float:
    """Lewis and Hunt's second-harmonic ratio for a hill-and-dale sine read by a sphere,
    to second order: H2 / H1 = R A k^2 / 4 = pi^2 R A / lambda^2."""
    return np.pi**2 * radius_m * amplitude_m / wavelength_m**2


def hertz_k(
    radius_along_m: float,
    radius_across_m: float,
    e1_pa: float,
    nu1: float,
    e2_pa: float,
    nu2: float,
) -> float:
    """K in F = K delta^(3/2) for a tip with two principal radii on a flat (the effective
    radius their geometric mean, Johnson ch. 4, a near-circular contact)."""
    e_star = 1.0 / ((1 - nu1**2) / e1_pa + (1 - nu2**2) / e2_pa)
    r_eff = np.sqrt(radius_along_m * radius_across_m)
    return 4.0 / 3.0 * e_star * np.sqrt(r_eff)


def static_indent(force_n: float, k: float) -> float:
    """Hertz indentation under a static force."""
    return (force_n / k) ** (2.0 / 3.0)


def roughness(
    n: int, ds_m: float, sigma_m: float, corr_m: float, seed: int, name: str
) -> np.ndarray:
    """A seeded Gaussian height field with an exponential correlation (an AR(1) along
    s, started in its stationary state): rms sigma_m, correlation length corr_m."""
    rng = np.random.default_rng([seed, zlib.crc32(name.encode())])
    a = np.exp(-ds_m / corr_m)
    w = rng.standard_normal(n) * sigma_m * np.sqrt(1 - a * a)
    w[0] = rng.standard_normal() * sigma_m
    return lfilter([1.0], [1.0, -a], w)

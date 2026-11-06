"""The D6's bar pickups: a string's flux linkage against its position, by reciprocity
(docs/CLAVINET_PLAN.md, "The pickups").

**The section.** The plane across the strings at the pickup (x along the row of bars, y up
from the bars' face toward the strings), extruded the bar's width along the string
(`bar_width_m`, [R12]'s 5 mm: the length of string each bar sees). As in [R12] Fig. 4, the
pickup is a row of six bars (37 or 33 mm long, 3 mm apart, 7 mm high), each a vertically
magnetized ferrite with its own coil around it, the six coils in series. Ten strings cross
each bar.

**The fields** are analytic: a uniformly magnetized bar is two current sheets on its end
faces (K = +-M, M = Br / mu0), a coil's sides two sheets just outside them
(K = +-N I / h). The ferrite's recoil permeability (~1.05) is taken as 1, so free space
holds everywhere (5% at most on the fields, the same on every string).

**The string** is a small permeable cylinder (radius a, mu_r) in the magnet's field: per
metre an induced dipole p = 2 pi a^2 (mu_r - 1)/(mu_r + 1) H_mag. By reciprocity, the flux
it adds to the coils is mu0 p . h_coil, h_coil the coils' field per ampere, so a string at
(x, y) adds

    Lambda(x, y) = w 2 pi a^2 (mu_r - 1)/(mu_r + 1) B_mag . B_coil / mu0   (weber-turns)

The EMF is -dLambda/dt = -(dLambda/dy y' + dLambda/dx x'). This is first order in the
string's size against the fields' scale (a <= 0.4 mm against ~mm). [R12] and [G13] solved
the same section with Vizimag; their curve's shape is the check (`tests/test_clavinet.py`).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

import numpy as np
from scipy import interpolate

from varimu.clavinet import spec

MU0 = 4e-7 * np.pi
COIL_OFFSET_M = 0.5e-3  # the coil's side, centred this far beyond the bar's end
N_BARS = 6


@dataclass(frozen=True)
class Pickup:
    which: str  # "centre" or "bridge"
    bar_length_m: float
    bar_gap_m: float
    bar_width_m: float
    magnet_height_m: float
    br_t: float
    turns_per_coil: float
    strings_per_bar: int
    side: str  # "below" or "above" the strings
    clearance_m: float

    @property
    def pitch_m(self) -> float:
        return self.bar_length_m + self.bar_gap_m

    def bar_x(self, j: int) -> tuple[float, float]:
        x0 = (j - (N_BARS - 1) / 2) * self.pitch_m
        return x0 - self.bar_length_m / 2, x0 + self.bar_length_m / 2

    def string_x(self, n: int) -> float:
        """Key n's string across the row: ten to a bar, evenly within it."""
        j, i = divmod(n - 1, self.strings_per_bar)
        xl, xr = self.bar_x(j)
        return xl + (i + 0.5) * self.bar_length_m / self.strings_per_bar


def pickups(name: str = "d6") -> dict[str, Pickup]:
    cfg = spec.load(name)
    pc = cfg["pickups"]
    coils_dcr = pc["dcr_ohm"] / N_BARS
    turns = coils_dcr / pc["wire_ohm_per_m"] / pc["turn_length_m"]
    return {
        w: Pickup(
            w,
            pc["bar_length_m"][w],
            pc["bar_gap_m"],
            pc["bar_width_m"],
            pc["magnet_height_m"],
            pc["magnet_br_t"],
            float(turns),
            int(pc["strings_per_bar"]),
            pc["side"][w],
            pc["clearance_m"],
        )
        for w in ("centre", "bridge")
    }


def _sheet(
    x: np.ndarray, y: np.ndarray, x0: float, y1: float, y2: float, k: float
) -> tuple[np.ndarray, np.ndarray]:
    """B of a sheet at x = x0 from y1 to y2 carrying k A/m along +z."""
    a = x - x0
    a = np.where(a == 0, 1e-12, a)  # on the sheet's plane (above or below it): the limit
    bx = MU0 * k / (4 * np.pi) * np.log((a * a + (y - y2) ** 2) / (a * a + (y - y1) ** 2))
    by = MU0 * k / (2 * np.pi) * (np.arctan((y2 - y) / a) - np.arctan((y1 - y) / a))
    return bx, by


def fields(pk: Pickup, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, ...]:
    """(B_mag x, y; B_coil per ampere x, y) at points above the bars' face (y > 0)."""
    m = pk.br_t / MU0
    kc = pk.turns_per_coil / pk.magnet_height_m
    y1, y2 = -pk.magnet_height_m, 0.0
    bmx = np.zeros_like(x)
    bmy = np.zeros_like(x)
    bcx = np.zeros_like(x)
    bcy = np.zeros_like(x)
    for j in range(N_BARS):
        xl, xr = pk.bar_x(j)
        for x0, s in ((xl, 1.0), (xr, -1.0)):
            fx, fy = _sheet(x, y, x0, y1, y2, s * m)
            bmx += fx
            bmy += fy
        for x0, s in ((xl - COIL_OFFSET_M, 1.0), (xr + COIL_OFFSET_M, -1.0)):
            fx, fy = _sheet(x, y, x0, y1, y2, s * kc)
            bcx += fx
            bcy += fy
    return bmx, bmy, bcx, bcy


def mean_b_t(pk: Pickup) -> float:
    """The mean vertical flux density through a bar's mid-height (the check against
    [R12] Fig. 5 / [G13] Fig. 10's ~0.075 T)."""
    xl, xr = pk.bar_x(N_BARS // 2)
    x = np.linspace(xl + 1e-5, xr - 1e-5, 2001)
    y = np.full_like(x, -pk.magnet_height_m / 2)
    m = pk.br_t / MU0
    by = np.zeros_like(x)
    for j in range(N_BARS):
        a, b = pk.bar_x(j)
        for x0, s in ((a, 1.0), (b, -1.0)):
            by += _sheet(x, y, x0, -pk.magnet_height_m, 0.0, s * m)[1]
    # inside the magnet B = mu0 (H + M): the sheets give mu0 H + mu0 M there
    return float(np.mean(by))


@dataclass(frozen=True)
class LinkageMap:
    """Lambda(dx, h): a string's linkage (weber-turns) at dx across from its rest place
    and h above the bars' face, for a string of magnetic diameter d."""

    dx_m: np.ndarray
    h_m: np.ndarray
    spline: interpolate.RectBivariateSpline

    def __call__(self, dx: np.ndarray, h: np.ndarray, ddx: int = 0, dh: int = 0) -> np.ndarray:
        return self.spline(dx, h, dx=ddx, dy=dh, grid=False)


@functools.cache
def linkage_map(pk: Pickup, n: int, d_magnetic_m: float, mu_r: float) -> LinkageMap:
    x0 = pk.string_x(n)
    dx = np.linspace(-2.5e-3, 2.5e-3, 101)
    h = np.linspace(0.25e-3, pk.clearance_m + 6e-3, 181)
    xx, hh = np.meshgrid(x0 + dx, h, indexing="ij")
    bmx, bmy, bcx, bcy = fields(pk, xx, hh)
    a = d_magnetic_m / 2
    chi = (mu_r - 1) / (mu_r + 1)
    lam = pk.bar_width_m * 2 * np.pi * a * a * chi * (bmx * bcx + bmy * bcy) / MU0
    return LinkageMap(dx, h, interpolate.RectBivariateSpline(dx, h, lam, kx=3, ky=3))


def emf(
    pk: Pickup, lmap: LinkageMap, y: np.ndarray, x: np.ndarray, vy: np.ndarray, vx: np.ndarray
) -> np.ndarray:
    """The EMF (V) of a string moving (y up, x across) about its rest place. A pickup
    above the strings sees y as moving toward it."""
    sgn = 1.0 if pk.side == "below" else -1.0
    h = pk.clearance_m + sgn * y
    lo, hi = lmap.h_m[0], lmap.h_m[-1]
    h = np.clip(h, lo, hi)
    dxx = np.clip(x, lmap.dx_m[0], lmap.dx_m[-1])
    return -(lmap(dxx, h, dh=1) * sgn * vy + lmap(dxx, h, ddx=1) * vx)

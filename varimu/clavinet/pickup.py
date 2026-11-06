"""The D6's bar pickups: a string's flux linkage against its position, by reciprocity
(docs/CLAVINET_PLAN.md, "The pickups").

**The section.** The plane across the strings at the pickup (x along the row of bars, y up
from the bars' face toward the strings), extruded the bar's width along the string
(`bar_width_m`, [R12]'s 5 mm: the length of string each bar sees). As in [R12] Fig. 4, the
pickup is a row of six bars (37 or 33 mm long, 3 mm apart, 7 mm high), each a vertically
magnetized ferrite with its own coil around it, the six coils in series. Ten strings cross
each bar.

**The fields**, three models (`pickups.model` in the config):

- **along** (the default): the section *along* the string, where a bar is only
  `bar_width_m` (5 mm) wide. A string crosses each bar over that width, so that is where
  the field changes along it and with its height: the gradient the EMF comes from. The bar
  is a pole (faces at +U and -U, solved as below) uniform across the strings, so every
  string over a bar sees the same field whatever its place on the bar (the section across
  the strings, the two models below, put the gradient at the bars' ends: strings mid-bar
  20-40 dB quieter than at the ends, CL1's first tries; [R12] reports no such spread), and
  horizontal motion is invisible to first order ([R12]: 25-30 dB down). The wire is
  magnetized along its axis by the field's component along it (susceptibility mu_r - 1, a
  thin wire has no demagnetization that way) and across it (2 (mu_r - 1)/(mu_r + 1)):
  Lambda(h) = mu0 pi a^2 int [(mu_r - 1) H_x h_x + 2 chi' H_y h_y] dx along the string.
  Saturation of the wire is left out (provisional mu_r; the level is fitted).
- **pole**: [R12]'s "metal bar coils" as high-permeability pole bars on their
  magnets. A pole's faces are magnetic equipotentials, so each bar is two strips (its top
  face at +U, its bottom face at -U) whose surface charge is solved by a 2D boundary
  element system (`SEGS_PER_FACE` segments per face, Chebyshev spaced for the edges'
  singularity; the uniformly charged segment's potential and field are analytic). The
  magnet's field and the coils' field per ampere have the same shape there (both are a
  potential difference between the pole faces): the magnet's scaled to `face_b_t` just
  above the bar's middle ([R12] Fig. 5: ~0.075 T), the coils' to N / (2 h) per ampere (the
  coil's MMF across an air return of about twice the bar's height: provisional).
- **ferrite**: free-space ferrite bars. A uniformly magnetized bar is two current sheets on
  its end faces (K = +-M, M = Br / mu0), a coil's sides two sheets just outside them
  (K = +-N I / h). It concentrates the field at the bars' ends: strings near a bar's middle
  came out ~20 dB quieter than those near its ends (CL1's first try), which [R12] doesn't
  report. Kept for comparison.

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
    model: str = "along"
    face_b_t: float = 0.075

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
            pc.get("model", "along"),
            pc.get("face_b_t", 0.075),
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


SEGS_PER_FACE = 40


def _cheb(a: float, b: float, n: int) -> np.ndarray:
    """n segment edges from a to b, Chebyshev spaced (dense at the ends)."""
    return 0.5 * (a + b) - 0.5 * (b - a) * np.cos(np.linspace(0, np.pi, n + 1))


def _seg_potential(
    x: np.ndarray, y: np.ndarray, x1: np.ndarray, x2: np.ndarray, y0: np.ndarray
) -> np.ndarray:
    """Potential at points (rows) of unit-density segments (columns) on y = y0 from x1 to
    x2, with the 2D Green's function -ln(r) / (2 pi)."""

    def f(u, yy):
        r2 = u * u + yy * yy
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = np.where(r2 > 0, 0.5 * u * np.log(r2), 0.0)
            t3 = np.where(np.abs(yy) > 0, yy * np.arctan(u / np.where(yy == 0, 1, yy)), 0.0)
        return t1 - u + t3

    yy = y[:, None] - y0[None, :]
    return -(f(x2[None, :] - x[:, None], yy) - f(x1[None, :] - x[:, None], yy)) / (2 * np.pi)


@functools.lru_cache(maxsize=8)
def _pole_charges(pk: Pickup) -> tuple[np.ndarray, ...]:
    """The pole faces' segments and their charge densities for +1 / -1 on the faces."""
    x1s, x2s, ys, target = [], [], [], []
    for j in range(N_BARS):
        xl, xr = pk.bar_x(j)
        e = _cheb(xl, xr, SEGS_PER_FACE)
        for y0, u in ((0.0, 1.0), (-pk.magnet_height_m, -1.0)):
            x1s.append(e[:-1])
            x2s.append(e[1:])
            ys.append(np.full(SEGS_PER_FACE, y0))
            target.append(np.full(SEGS_PER_FACE, u))
    x1, x2, y0, tgt = (np.concatenate(v) for v in (x1s, x2s, ys, target))
    xm = 0.5 * (x1 + x2)
    sigma = np.linalg.solve(_seg_potential(xm, y0, x1, x2, y0), tgt)
    return x1, x2, y0, sigma


def _pole_h(pk: Pickup, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """H per unit face potential at points above the faces (y > 0)."""
    x1, x2, y0, sigma = _pole_charges(pk)
    shape = x.shape
    xf, yf = x.ravel(), y.ravel()
    hx = np.zeros(xf.size)
    hy = np.zeros(xf.size)
    for s0 in range(0, x1.size, 120):
        sl = slice(s0, s0 + 120)
        yy = yf[:, None] - y0[None, sl]
        a1 = xf[:, None] - x1[None, sl]
        a2 = xf[:, None] - x2[None, sl]
        hx += (np.log((a1 * a1 + yy * yy) / (a2 * a2 + yy * yy)) / (4 * np.pi)) @ sigma[sl]
        hy += ((np.arctan(a1 / yy) - np.arctan(a2 / yy)) / (2 * np.pi)) @ sigma[sl]
    return hx.reshape(shape), hy.reshape(shape)


def pole_fields(pk: Pickup, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, ...]:
    """(B_mag x, y; B_coil per ampere x, y) of the pole model."""
    hx, hy = _pole_h(pk, x, y)
    xl, xr = pk.bar_x(N_BARS // 2)
    rx, ry = _pole_h(pk, np.array([0.5 * (xl + xr)]), np.array([0.2e-3]))
    ref = float(np.hypot(rx[0], ry[0]))
    b_mag = pk.face_b_t / ref
    b_coil = MU0 * pk.turns_per_coil / (2 * pk.magnet_height_m) / ref
    return b_mag * hx, b_mag * hy, b_coil * hx, b_coil * hy


@functools.lru_cache(maxsize=8)
def _strip_charges(width: float, height: float) -> tuple[np.ndarray, ...]:
    """One pole bar in the section along the string: its top face (+1) and bottom face (-1)."""
    e = _cheb(-width / 2, width / 2, 2 * SEGS_PER_FACE)
    x1 = np.concatenate([e[:-1], e[:-1]])
    x2 = np.concatenate([e[1:], e[1:]])
    n = e.size - 1
    y0 = np.concatenate([np.zeros(n), np.full(n, -height)])
    tgt = np.concatenate([np.ones(n), -np.ones(n)])
    xm = 0.5 * (x1 + x2)
    return x1, x2, y0, np.linalg.solve(_seg_potential(xm, y0, x1, x2, y0), tgt)


def _strip_h(
    width: float, height: float, x: np.ndarray, y: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    x1, x2, y0, sigma = _strip_charges(width, height)
    yy = y[:, None] - y0[None, :]
    a1 = x[:, None] - x1[None, :]
    a2 = x[:, None] - x2[None, :]
    hx = (np.log((a1 * a1 + yy * yy) / (a2 * a2 + yy * yy)) / (4 * np.pi)) @ sigma
    hy = ((np.arctan(a1 / yy) - np.arctan(a2 / yy)) / (2 * np.pi)) @ sigma
    return hx, hy


def along_linkage(pk: Pickup, d_magnetic_m: float, mu_r: float, h: np.ndarray) -> np.ndarray:
    """Lambda(h) of the along-the-string model (weber-turns)."""
    w, hm = pk.bar_width_m, pk.magnet_height_m
    rx, ry = _strip_h(w, hm, np.array([0.0]), np.array([0.2e-3]))
    ref = float(np.hypot(rx[0], ry[0]))
    h_mag = pk.face_b_t / MU0 / ref  # A/m per unit of the solved field
    h_coil = pk.turns_per_coil / (2 * hm) / ref  # per ampere
    x = np.linspace(-6 * w, 6 * w, 1201)
    dx = x[1] - x[0]
    a = d_magnetic_m / 2
    chi_t = 2 * (mu_r - 1) / (mu_r + 1)
    out = np.zeros(h.size)
    for i, hh in enumerate(h):
        hx, hy = _strip_h(w, hm, x, np.full_like(x, hh))
        integrand = (mu_r - 1) * hx * hx + chi_t * hy * hy
        out[i] = MU0 * np.pi * a * a * h_mag * h_coil * np.sum(integrand) * dx
    return out


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
    if pk.model == "along":
        lam = np.tile(along_linkage(pk, d_magnetic_m, mu_r, h), (dx.size, 1))
        return LinkageMap(dx, h, interpolate.RectBivariateSpline(dx, h, lam, kx=3, ky=3))
    xx, hh = np.meshgrid(x0 + dx, h, indexing="ij")
    bmx, bmy, bcx, bcy = (pole_fields if pk.model == "pole" else fields)(pk, xx, hh)
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

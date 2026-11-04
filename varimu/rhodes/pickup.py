"""The pickup's flux map: the flux through the coil against the tine tip's position, by a
2D magnetostatic finite-element solve (docs/RHODES_PLAN.md, RH1; "Pickup").

**The section.** The vertical plane through the tine's axis and the pickup's: x along the
axis (the pickup's pole at x >= 0, its chisel end's edge at x = 0, y = 0; the tine's end
face at x = -gap), y vertical. Planar 2D: everything is extruded a depth D out of the plane
(the magnet's width): the tine is a slab as wide as the magnet, the chisel's edge a line.
That is the plan's first step; the 3D solve (RH5) checks it and sets the absolute level.

**The physics.** Linear magnetostatics in the vector potential A_z: no free currents (the
coil's current is negligible: a high-impedance load), the magnet a remanence Br along x
with a recoil permeability, the tine steel of a constant permeability (RH1 leaves its
saturation out), air elsewhere. The weak form is
`int nu grad(v) . grad(A) = int nu (Br_x dv/dy - Br_y dv/dx)` with nu = 1 / (mu0 mu_r),
A = 0 on the outer boundary (`BOX_M` from the pole). The flux linked by the coil is
`N D / S (int_top A - int_bottom A)` over its two winding sides (each of area S).

**Exact geometry at every sample.** Bilinear rectangles on a tensor grid, uniform in y
(`cell_y` = the tine's diameter / 16) across the band the tine swings through (the bass
tines swing ~10 mm and more). The map samples the tine's height at whole cells, so its
edges are grid lines at every sample (a tine painted between lines, or a mesh sheared
across the 1.6 mm gap, would step or distort); the tip's pull-back from the gap stretches
the gap's columns (no shear). A cubic spline through the samples is the map.

`flux_map(pickup)` solves the samples (cached in `cache/rhodes/`) and returns the spline
Phi(y, dg) with its derivatives; `key.strike` uses it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy import interpolate, sparse
from scipy.sparse import linalg as spla

from varimu.config import REPO_ROOT
from varimu.rhodes.spec import Pickup

MU0 = 4e-7 * np.pi
CACHE_DIR = REPO_ROOT / "cache" / "rhodes"
BOX_M = 0.06  # the outer boundary's distance
CELL_X_M = 0.04e-3  # the fine cells along x around the gap
BAND_Y_M = 20e-3  # uniform cells in y within +-this
GROWTH = 1.18  # the cells' growth outside the fine regions
SWING_M = 18e-3  # the map covers the tine's centre within +-this of the pole's axis
FINE_SWING_M = 6e-3  # every cell within +-this, every third beyond
MAP_DG_M = np.array([0.0, 0.1e-3, 0.2e-3, 0.35e-3])  # the tip's pull-back from the gap


def _grow(start: float, step: float, end: float) -> list[float]:
    """From `start` (exclusive) towards `end`, steps growing by GROWTH from `step`."""
    pts, x, sign = [], start, np.sign(end - start)
    while (end - x) * sign > 0:
        step *= GROWTH
        x += sign * step
        pts.append(end if (end - x) * sign < 0 else x)
    return pts


@dataclass
class Mesh:
    x: np.ndarray  # grid lines
    y: np.ndarray
    cell_y: float
    j0: int  # the index of the cell row starting at y = 0
    nu: np.ndarray  # per cell (ny-1, nx-1), without the tine
    nu_tine: float
    tine_cols: np.ndarray  # cell columns left of the gap (x < -gap)
    tine_rows: int  # the tine's cells either side of its centre
    br_x: np.ndarray  # per cell
    coil_w: np.ndarray  # nodal weights: (int_top A - int_bottom A) / S = coil_w . A
    gap_m: float


def mesh(p: Pickup) -> Mesh:
    g, lw, lm, w = p.gap_m, p.wedge_length_m, p.magnet_length_m, p.magnet_width_m
    c_in, c_out, lc = p.coil_inner_m, p.coil_outer_m, p.coil_length_m
    xc0 = lw + 0.5 * (lm - lc)
    # x: uniform around the gap and the pole's tip, marks for the rest, growing out
    lo, hi = -g - 2e-3, lw + 1e-3
    core = list(np.arange(lo, hi + CELL_X_M / 2, CELL_X_M))
    core = [c for c in core if min(abs(c + g), abs(c), abs(c - lw)) > CELL_X_M / 3]
    x = core + [-g, 0.0, lw] + _grow(lo, CELL_X_M, -BOX_M) + _grow(hi, CELL_X_M, BOX_M)
    for mark in (lw + lm, xc0, xc0 + lc):
        x = [c for c in x if abs(c - mark) > 0.3 * CELL_X_M * GROWTH**8] + [mark]
    x = np.unique(np.round(x, 10))
    # y: uniform cells of d / 16 within the band, symmetric about 0
    cell = p.tine_diameter_m / 16
    n_band = int(np.ceil(BAND_Y_M / cell))
    band = cell * np.arange(-n_band, n_band + 1)
    top = _grow(band[-1], cell, BOX_M)
    y = np.unique(np.round(np.concatenate([-np.array(top[::-1]), band, top]), 12))
    j0 = int(np.flatnonzero(np.isclose(y, 0.0, atol=cell / 10))[0])

    xm = 0.5 * (x[:-1] + x[1:])
    ym = 0.5 * (y[:-1] + y[1:])
    xx, yy = np.meshgrid(xm, ym)
    mu = np.ones_like(xx)
    br = np.zeros_like(xx)
    wedge = (xx >= 0) & (xx < lw) & (np.abs(yy) < 0.5 * w * xx / lw)
    body = (xx >= lw) & (xx < lw + lm) & (np.abs(yy) < w / 2)
    magnet = wedge | body
    mu[magnet] = p.magnet_mu_r
    br[magnet] = p.magnet_br_t
    # the coil's sides: nodal weights of int A dS (bilinear: a quarter of each cell's
    # area to its corners), +top -bottom, over the side's area
    coil_x = (xx >= xc0) & (xx < xc0 + lc)
    top_m = coil_x & (yy > c_in) & (yy < c_out)
    bot_m = coil_x & (yy < -c_in) & (yy > -c_out)
    area = np.outer(np.diff(y), np.diff(x))
    s_side = float(np.sum(area[top_m]))
    nx = x.size
    cw = np.zeros(x.size * y.size)
    for mask, sign in ((top_m, 1.0), (bot_m, -1.0)):
        jj, ii = np.nonzero(mask)
        for dj, di in ((0, 0), (0, 1), (1, 0), (1, 1)):
            np.add.at(cw, (jj + dj) * nx + ii + di, sign * 0.25 * area[jj, ii] / s_side)
    return Mesh(
        x,
        y,
        cell,
        j0,
        1.0 / (MU0 * mu),
        1.0 / (MU0 * p.tine_mu_r),
        np.flatnonzero(xm < -g),
        8,
        br,
        cw,
        g,
    )


_GP = np.array([-1, 1]) / np.sqrt(3.0)


def solve(m: Mesh, steps: int, dg: float) -> np.ndarray:
    """A_z at the nodes (V s / m) with the tine's centre `steps` cells above the pole's
    axis and its end pulled back dg from the gap."""
    s = np.clip(-m.x / m.gap_m, 0.0, 1.0)
    xs = m.x - dg * s  # the gap's columns stretch; left of it all moves by dg
    X, Y = np.meshgrid(xs, m.y)
    ny, nx = X.shape
    nu = m.nu.copy()
    rows = slice(m.j0 + steps - m.tine_rows, m.j0 + steps + m.tine_rows)
    nu[rows, m.tine_cols[0] : m.tine_cols[-1] + 1] = m.nu_tine
    idx = np.arange(nx * ny).reshape(ny, nx)
    conn = np.stack([idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]], axis=-1).reshape(
        -1, 4
    )
    xe, ye = X.ravel()[conn], Y.ravel()[conn]
    nu = nu.ravel()
    br = m.br_x.ravel()
    ne = conn.shape[0]
    ke = np.zeros((ne, 4, 4))
    fe = np.zeros((ne, 4))
    sxi = np.array([-1, 1, 1, -1], float)
    seta = np.array([-1, -1, 1, 1], float)
    for xi in _GP:
        for eta in _GP:
            dn_dxi = 0.25 * sxi * (1 + seta * eta)
            dn_deta = 0.25 * seta * (1 + sxi * xi)
            j11, j12 = xe @ dn_dxi, ye @ dn_dxi
            j21, j22 = xe @ dn_deta, ye @ dn_deta
            det = j11 * j22 - j12 * j21
            dn_dx = (j22[:, None] * dn_dxi - j12[:, None] * dn_deta) / det[:, None]
            dn_dy = (-j21[:, None] * dn_dxi + j11[:, None] * dn_deta) / det[:, None]
            wgt = (nu * det)[:, None, None]
            ke += wgt * (
                dn_dx[:, :, None] * dn_dx[:, None, :] + dn_dy[:, :, None] * dn_dy[:, None, :]
            )
            fe += (nu * br * det)[:, None] * dn_dy
    n = nx * ny
    k = sparse.csr_matrix(
        (ke.ravel(), (np.repeat(conn, 4, axis=1).ravel(), np.tile(conn, (1, 4)).ravel())),
        shape=(n, n),
    )
    f = np.bincount(conn.ravel(), weights=fe.ravel(), minlength=n)
    boundary = np.zeros((ny, nx), bool)
    boundary[0, :] = boundary[-1, :] = boundary[:, 0] = boundary[:, -1] = True
    free = np.flatnonzero(~boundary.ravel())
    a = np.zeros(n)
    a[free] = spla.spsolve(k[free][:, free].tocsc(), f[free])
    return a


def linkage_per_turn_per_depth(m: Mesh, a: np.ndarray) -> float:
    """The flux through one turn per metre of depth (Wb / m)."""
    return float(m.coil_w @ a)


def map_steps(m: Mesh) -> np.ndarray:
    """The sampled heights in cells: every cell within FINE_SWING_M, every third out to
    SWING_M (symmetric)."""
    fine = int(round(FINE_SWING_M / m.cell_y))
    far = int(round(SWING_M / m.cell_y))
    pos = np.concatenate([np.arange(0, fine + 1), np.arange(fine + 3, far + 1, 3)])
    return np.unique(np.concatenate([-pos, pos]))


def _cache_key(p: Pickup) -> str:
    src = Path(__file__).read_bytes()
    blob = json.dumps(
        {
            "pickup": asdict(p),
            "dg": MAP_DG_M.tolist(),
            "consts": [BOX_M, CELL_X_M, BAND_Y_M, GROWTH, SWING_M, FINE_SWING_M],
        },
        sort_keys=True,
    ).encode()
    return hashlib.sha256(src + blob).hexdigest()[:16]


@dataclass(frozen=True)
class FluxMap:
    y_m: np.ndarray
    dg_m: np.ndarray
    phi_wb: np.ndarray  # (y, dg): the linkage N D Phi_turn, weber-turns
    spline: interpolate.RectBivariateSpline

    def __call__(self, y: np.ndarray, dg: np.ndarray, dy: int = 0, ddg: int = 0) -> np.ndarray:
        return self.spline(y, dg, dx=dy, dy=ddg, grid=False)

    @property
    def y_range_m(self) -> tuple[float, float]:
        return float(self.y_m[0]), float(self.y_m[-1])


def flux_map(p: Pickup, progress: bool = False, workers: int = 1) -> FluxMap:
    """Phi(y, dg): the coil's flux linkage (N turns, depth = the magnet's width) with the
    tine's centre at y from the pole's axis and its end dg further than the gap. The
    section is symmetric, so only y >= 0 is solved."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"pickup_{_cache_key(p)}.npz"
    m = mesh(p)
    steps = map_steps(m)
    y = steps * m.cell_y
    if path.exists():
        phi = np.load(path)["phi"]
    else:
        half = steps[steps >= 0]
        jobs = [(int(s), float(dg)) for dg in MAP_DG_M for s in half]
        if workers > 1:
            from concurrent.futures import ProcessPoolExecutor

            with ProcessPoolExecutor(workers) as pool:
                vals = list(pool.map(_one, [(p, s, dg) for s, dg in jobs], chunksize=4))
        else:
            vals = []
            for i, job in enumerate(jobs):
                vals.append(_one((p, *job)))
                if progress and (i + 1) % 50 == 0:
                    print(f"pickup map: {i + 1} / {len(jobs)}", flush=True)
        got = dict(zip(jobs, vals, strict=True))
        phi = np.array([[got[(abs(int(s)), float(dg))] for dg in MAP_DG_M] for s in steps])
        phi *= p.turns * p.magnet_width_m
        np.savez(path, phi=phi)
    spline = interpolate.RectBivariateSpline(y, MAP_DG_M, phi, kx=3, ky=3)
    return FluxMap(y, MAP_DG_M, phi, spline)


_MESH_CACHE: dict[str, Mesh] = {}


def _one(job: tuple[Pickup, int, float]) -> float:
    p, steps, dg = job
    key = json.dumps(asdict(p), sort_keys=True)
    if key not in _MESH_CACHE:
        _MESH_CACHE[key] = mesh(p)
    m = _MESH_CACHE[key]
    return linkage_per_turn_per_depth(m, solve(m, steps, dg))

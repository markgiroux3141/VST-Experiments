"""The electrostatic pickup's map: the plate's capacitance per metre of reed against the reed's
height, by a 2D field solve across the reed in its slot (docs/WURLITZER_PLAN.md, WZ1;
"The pickup").

**The section** is the plane across the reed's outer end, where the slot's prongs run
alongside it: y sideways, z vertical (up positive, the hammer's direction), the plate's
mid-plane at z = 0. The reed is a rectangle b x t centred at (0, z), grounded (its head is
its ground: VV tuning); the plate's prongs are the plate (thickness tp) either side of the
slot, from `side_gap` past the reed's edges out to the neighbouring slot, at 1 V. Above and
below, the shield over the reed bars and the reed bar itself are grounded planes at
+-`shield_distance`. Sideways the section is one reed pitch wide with mirror (Neumann)
walls: the neighbouring reeds at rest.

**The physics.** Laplace's equation for the potential, conductors as Dirichlet nodes, on
bilinear rectangles of a tensor grid, uniform (`field_cell_m`) across the band the reed
swings through and around the slot's edges, growing outside. The reed moves by whole cells,
so its faces are grid lines at every sample. The plate's capacitance per metre to everything
grounded is the field's energy, `c = eps0 phi' K phi` at 1 V: the reed's position moves it
(the rest is the plate's constant capacitance to the shields). By symmetry c(-z) = c(z): the
map is solved for z >= 0; c is largest with the reed in the plate's plane, so a reed at rest
there doubles its frequency at the output (VV tuning: 'a very strong undesirable harmonic').

`field_map(...)` solves the samples (cached in `cache/wurlitzer/`) and returns a spline
c(z) with its derivatives; `key.strike` integrates it along the slot.
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

EPS0 = 8.8541878128e-12
CACHE_DIR = REPO_ROOT / "cache" / "wurlitzer"
GROWTH = 1.2
FINE_MARGIN_M = 0.8e-3  # uniform cells this far past the slot's edges
FINE_SWING_M = 2.0e-3  # every cell's height sampled within this, every second beyond


@dataclass(frozen=True)
class Section:
    reed_width_m: float
    reed_thickness_m: float
    plate_thickness_m: float
    side_gap_m: float
    pitch_m: float
    shield_distance_m: float
    cell_m: float  # the fine cells (rounded so the reed's half thickness is whole cells)
    swing_m: float


def _grow(start: float, step: float, end: float) -> list[float]:
    pts, x, sign = [], start, np.sign(end - start)
    while (end - x) * sign > 0:
        step *= GROWTH
        x += sign * step
        pts.append(end if (end - x) * sign < 0 else x)
    return pts


def section(
    reed_width_m: float,
    reed_thickness_m: float,
    plate_thickness_m: float,
    side_gap_m: float,
    pitch_m: float,
    shield_distance_m: float,
    cell_m: float,
    swing_m: float,
) -> Section:
    """The section with its cell rounded so the reed's and the plate's half thicknesses are
    whole cells (the plate's thickness is rounded to them: within half a cell)."""
    n_half = max(1, int(round(reed_thickness_m / 2 / cell_m)))
    cell = reed_thickness_m / 2 / n_half
    tp = 2 * cell * max(1, int(round(plate_thickness_m / 2 / cell)))
    return Section(
        reed_width_m, reed_thickness_m, tp, side_gap_m, pitch_m, shield_distance_m, cell, swing_m
    )


@dataclass
class Mesh:
    y: np.ndarray
    z: np.ndarray
    k: sparse.csr_matrix  # Laplace stiffness, unit coefficient
    plate: np.ndarray  # bool per node
    boundary: np.ndarray  # bool per node (the grounded planes)
    reed_y: np.ndarray  # node columns inside the reed's width (inclusive of its faces)
    j0: int  # the row index of z = 0
    n_half: int  # the reed's half thickness in cells


def mesh(s: Section) -> Mesh:
    c = s.cell_m
    hb, edge, half_p = s.reed_width_m / 2, s.reed_width_m / 2 + s.side_gap_m, s.pitch_m / 2
    fine = min(edge + FINE_MARGIN_M, half_p)
    n_fine = int(np.ceil(fine / c))
    yf = list(np.arange(0, n_fine + 1) * c)
    yp = [v for v in yf if min(abs(v - hb), abs(v - edge)) > c / 3] + [hb, edge]
    yp = sorted(set(np.round(yp, 12)))
    if yp[-1] < half_p:
        yp += _grow(yp[-1], c, half_p)
    yp = np.unique(np.round(np.array(yp), 12))
    y = np.concatenate([-yp[:0:-1], yp])
    band = s.swing_m + s.reed_thickness_m
    n_band = int(np.ceil(band / c))
    zb = np.arange(-n_band, n_band + 1) * c
    top = _grow(zb[-1], c, s.shield_distance_m)
    z = np.unique(np.round(np.concatenate([-np.array(top[::-1]), zb, top]), 12))
    j0 = int(np.flatnonzero(np.isclose(z, 0.0, atol=c / 10))[0])
    ny, nz = y.size, z.size
    Y, Z = np.meshgrid(y, z)  # (nz, ny)
    idx = np.arange(ny * nz).reshape(nz, ny)
    conn = np.stack([idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]], axis=-1).reshape(
        -1, 4
    )
    hy = np.diff(y)[None, :].repeat(nz - 1, 0).ravel()
    hz = np.diff(z)[:, None].repeat(ny - 1, 1).ravel()
    # the bilinear rectangle's Laplace stiffness (exact): corners (0,0) (1,0) (1,1) (0,1)
    ay = np.array([[2, -2, -1, 1], [-2, 2, 1, -1], [-1, 1, 2, -2], [1, -1, -2, 2]]) / 6.0
    az = np.array([[2, 1, -1, -2], [1, 2, -2, -1], [-1, -2, 2, 1], [-2, -1, 1, 2]]) / 6.0
    ke = (hz / hy)[:, None, None] * ay + (hy / hz)[:, None, None] * az
    k = sparse.csr_matrix(
        (ke.ravel(), (np.repeat(conn, 4, axis=1).ravel(), np.tile(conn, (1, 4)).ravel())),
        shape=(ny * nz, ny * nz),
    )
    tp2 = s.plate_thickness_m / 2
    plate = (np.abs(Y) >= edge - 1e-12) & (np.abs(Z) <= tp2 + 1e-12)
    boundary = np.zeros((nz, ny), bool)
    boundary[0, :] = boundary[-1, :] = True
    reed_y = np.flatnonzero(np.abs(y) <= hb + 1e-12)
    return Mesh(
        y, z, k, plate.ravel(), boundary.ravel(), reed_y, j0, int(round(s.reed_thickness_m / 2 / c))
    )


def capacitance_per_m(m: Mesh, steps: int) -> float:
    """The plate's capacitance per metre (F / m) with the reed's centre `steps` cells above
    the plate's mid-plane."""
    ny = m.y.size
    reed = np.zeros((m.z.size, ny), bool)
    rows = slice(m.j0 + steps - m.n_half, m.j0 + steps + m.n_half + 1)
    reed[rows, m.reed_y[0] : m.reed_y[-1] + 1] = True
    reed = reed.ravel()
    fixed = m.boundary | m.plate | reed
    phi = np.zeros(ny * m.z.size)
    phi[m.plate] = 1.0
    free = np.flatnonzero(~fixed)
    fx = np.flatnonzero(fixed)
    rhs = -(m.k[free][:, fx] @ phi[fx])
    phi[free] = spla.spsolve(m.k[free][:, free].tocsc(), rhs)
    return float(EPS0 * phi @ (m.k @ phi))


def map_steps(m: Mesh, s: Section) -> np.ndarray:
    fine = int(round(FINE_SWING_M / s.cell_m))
    far = int(round(s.swing_m / s.cell_m))
    return np.unique(np.concatenate([np.arange(0, fine + 1), np.arange(fine + 2, far + 1, 2)]))


@dataclass(frozen=True)
class FieldMap:
    z_m: np.ndarray
    c_f_per_m: np.ndarray
    spline: interpolate.CubicSpline
    section: Section

    def __call__(self, z: np.ndarray, dz: int = 0) -> np.ndarray:
        """c(z) (F / m) or its derivatives, z held at the map's edges."""
        zc = np.clip(z, self.z_m[0], self.z_m[-1])
        return self.spline(zc, dz)

    @property
    def z_range_m(self) -> tuple[float, float]:
        return float(self.z_m[0]), float(self.z_m[-1])


def _cache_key(s: Section) -> str:
    src = Path(__file__).read_bytes()
    blob = json.dumps(
        {"section": asdict(s), "consts": [GROWTH, FINE_MARGIN_M, FINE_SWING_M]}, sort_keys=True
    ).encode()
    return hashlib.sha256(src + blob).hexdigest()[:16]


_MESH_CACHE: dict[Section, Mesh] = {}


def _one(job: tuple[Section, int]) -> float:
    s, steps = job
    if s not in _MESH_CACHE:
        _MESH_CACHE[s] = mesh(s)
    return capacitance_per_m(_MESH_CACHE[s], steps)


def field_map(s: Section, progress: bool = False, workers: int | None = None) -> FieldMap:
    """c(z) for the section, solved on `workers` processes (default: the cores less two) when
    it isn't cached."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"field_{_cache_key(s)}.npz"
    m = mesh(s)
    steps = map_steps(m, s)
    if path.exists():
        c = np.load(path)["c"]
    else:
        import os
        from concurrent.futures import ProcessPoolExecutor

        workers = workers or max(1, min(6, (os.cpu_count() or 2) - 2))
        jobs = [(s, int(st)) for st in steps]
        if workers > 1:
            with ProcessPoolExecutor(workers) as pool:
                c = np.array(list(pool.map(_one, jobs, chunksize=4)))
        else:
            c = np.array([_one(j) for j in jobs])
        if progress:
            print(f"field map: {steps.size} heights solved", flush=True)
        np.savez(path, c=c)
    z = steps * s.cell_m
    zz = np.concatenate([-z[:0:-1], z])
    cc = np.concatenate([c[:0:-1], c])
    return FieldMap(zz, cc, interpolate.CubicSpline(zz, cc), s)

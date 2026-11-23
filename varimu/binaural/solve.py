"""A head's HRTFs from its mesh, by reciprocity on the GPU (docs/BINAURAL_PLAN.md).

**Reciprocity.** The pressure at the blocked ear canal from a point source far away in
direction u equals (same source strength) the pressure far away in direction u from a point
source at the ear. So one run per ear, the source at the ear and receivers on a sphere of
radius R round the head, gives that ear's response to every direction at once
(`varimu.binaural.sphere`: SH coefficients on R, then any distance or the far field). The
HRTF is that field over a point source's free field from the head's centre (the interaural
centre, the mesh's origin): H = p r e^{jkr} as r grows.

**The grid** (crates/roomsim `fdtd::head`): a cube of cells of side `dx_m` centred on the
origin (the origin a cell centre), solid where a cell's centre is inside the mesh
(`varimu.binaural.mesh.voxelize`), a sponge layer at the faces, the outermost cells solid.
The step T = 1 / (m fs_out) with m the smallest whole number keeping the Courant number
c T / dx <= 1 / sqrt(3), so a record's FFT lands on the output grid's bins exactly.

**Two runs per ear** (`HeadSpec`): a fine grid for the pinna (the top of the band), small
because of the GPU's memory, so its sponge reflects some of the lows back in time; and a
coarse grid in a box big enough that nothing comes back from its faces before the record
ends (the lows; it resolves the head's shape well below its top). `varimu.binaural.hrtf`
blends them.

**The source** is a unit impulse (free-field 1 / r at r, the room wave solver's
normalization) a fraction of a cell outside the ear's surface point, spread trilinearly over
the air cells round it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from varimu.binaural.mesh import Mesh, ray_hit, voxelize
from varimu.binaural.sphere import gauss_grid

C_M_S = 343.0  # speed of sound used by the solver and the extrapolation (20 C)


@dataclass(frozen=True)
class RunSpec:
    """One grid: spacing, the receiver sphere, the record's length and the sponge."""

    dx_m: float
    radius_m: float  # receivers
    order: int  # the receivers' Gauss grid order
    half_m: float  # the domain's half-width (sponge included)
    sponge_m: float
    g_max: float
    duration_s: float
    fs_out: float = 96_000.0

    @property
    def m(self) -> int:
        return int(np.ceil(C_M_S * np.sqrt(3.0) / (self.dx_m * self.fs_out) - 1e-9))

    @property
    def t_step(self) -> float:
        return 1.0 / (self.m * self.fs_out)

    @property
    def lam(self) -> float:
        return C_M_S * self.t_step / self.dx_m

    @property
    def half_cells(self) -> int:
        return int(np.ceil(self.half_m / self.dx_m))

    @property
    def n_side(self) -> int:
        return 2 * self.half_cells + 1

    @property
    def n_steps(self) -> int:
        return int(np.ceil(self.duration_s / self.t_step)) + 2

    @property
    def sponge_cells(self) -> int:
        return int(round(self.sponge_m / self.dx_m))

    def cells(self) -> int:
        return self.n_side**3


@dataclass
class Records:
    spec: RunSpec
    ear_m: np.ndarray  # the source position
    p: np.ndarray  # (n_steps, Q) receiver pressures, float32
    seconds: float


def ear_point(mesh: Mesh, side: str, dx_m: float, offset_cells: float = 0.75) -> np.ndarray:
    """The source position for an ear: where the interaural axis (the mesh's y axis) leaves
    the head on that side (the blocked canal's entrance), moved `offset_cells` cells out
    along the surface's outward normal."""
    sgn = 1.0 if side == "left" else -1.0
    t, n = ray_hit(mesh, np.zeros(3), np.array([0.0, sgn, 0.0]))
    hit = np.array([0.0, sgn * t, 0.0])
    if n[1] * sgn < 0:  # wound inward
        n = -n
    return hit + offset_cells * dx_m * n


def grid_codes(mesh: Mesh | None, spec: RunSpec) -> np.ndarray:
    """The solver's cell codes (nz, ny, nx) flat: 0 solid, else the air neighbours."""
    n = spec.n_side
    h = spec.half_cells
    x0 = -h * spec.dx_m
    air = np.ones((n, n, n), bool)
    if mesh is not None:
        lo, hi = mesh.bounds()
        i_lo = np.maximum(np.floor((lo - x0) / spec.dx_m).astype(int) - 1, 1)
        i_hi = np.minimum(np.ceil((hi - x0) / spec.dx_m).astype(int) + 2, n - 1)
        sub = tuple(int(v) for v in (i_hi - i_lo)[::-1])
        solid = voxelize(mesh, x0 + i_lo * spec.dx_m, spec.dx_m, sub)
        air[i_lo[2] : i_hi[2], i_lo[1] : i_hi[1], i_lo[0] : i_hi[0]] &= ~solid
    air[0, :, :] = air[-1, :, :] = False
    air[:, 0, :] = air[:, -1, :] = False
    air[:, :, 0] = air[:, :, -1] = False
    k = np.zeros((n, n, n), np.uint8)
    c = (slice(1, -1),) * 3
    for ax in range(3):
        for d in (-1, 1):
            sl = [slice(1, -1)] * 3
            sl[ax] = slice(1 + d, n - 1 + d)
            k[c] += air[tuple(sl)]
    k[~air] = 0
    del air
    return k.ravel()


def receivers(spec: RunSpec) -> np.ndarray:
    """The Gauss grid's points on the sphere, in grid coordinates (x, y, z), flat."""
    g = gauss_grid(spec.order)
    pts = g.unit() * spec.radius_m
    return (pts / spec.dx_m + spec.half_cells).ravel()


def inject(codes: np.ndarray, spec: RunSpec, point_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = spec.n_side
    sg = np.asarray(point_m, float) / spec.dx_m + spec.half_cells
    base = np.floor(sg).astype(int)
    fr = sg - base
    idx, val = [], []
    for dz in (0, 1):
        for dy in (0, 1):
            for dxx in (0, 1):
                w = (
                    (fr[0] if dxx else 1 - fr[0])
                    * (fr[1] if dy else 1 - fr[1])
                    * (fr[2] if dz else 1 - fr[2])
                )
                cell = (base[0] + dxx) + n * ((base[1] + dy) + n * (base[2] + dz))
                if codes[cell] == 0:
                    continue
                idx.append(cell)
                val.append(w)
    tot = sum(val)
    if not idx or tot < 1e-9:
        raise ValueError(f"the source at {list(point_m)} is inside the body")
    scale = 4 * np.pi * spec.lam**2 / (spec.dx_m * spec.t_step) / tot
    return np.array(idx, np.uint32), np.array(val, float) * scale


def run(
    mesh: Mesh | None,
    spec: RunSpec,
    source_m: np.ndarray,
    backend: str = "gpu",
    log=print,
) -> Records:
    import roomsim

    t0 = time.perf_counter()
    codes = grid_codes(mesh, spec)
    ii, vv = inject(codes, spec, source_m)
    mics = receivers(spec)
    n = spec.n_side
    if log:
        log(
            f"  grid {n}^3 = {n**3 / 1e6:.0f} M cells at {spec.dx_m * 1e3:.2f} mm, "
            f"{spec.n_steps} steps, {len(mics) // 3} receivers "
            f"({time.perf_counter() - t0:.1f} s to build)"
        )

    def progress(s, total):
        if log:
            log(f"    step {s}/{total}")

    t1 = time.perf_counter()
    rec = roomsim.body_run(
        (n, n, n),
        codes,
        spec.lam,
        spec.sponge_cells,
        spec.g_max,
        ii,
        vv,
        mics,
        spec.n_steps,
        backend=backend,
        progress=progress,
    )
    del codes
    p = np.asarray(rec, np.float32).reshape(spec.n_steps, -1)
    secs = time.perf_counter() - t1
    if log:
        log(f"  solved in {secs:.1f} s")
    return Records(spec, np.asarray(source_m, float), p, secs)


def reflection_times(spec: RunSpec, source_m: np.ndarray) -> np.ndarray:
    """Per receiver, when the first wave back from the grid's faces can reach it: the image
    of the source in the sponge's inner face (where its damping starts) on each of the six
    sides, the nearest one."""
    inner = (spec.half_cells - spec.sponge_cells) * spec.dx_m
    g = gauss_grid(spec.order)
    pts = g.unit() * spec.radius_m
    s = np.asarray(source_m, float)
    t = np.full(len(pts), np.inf)
    for ax in range(3):
        for sgn in (-1.0, 1.0):
            img = s.copy()
            img[ax] = 2 * sgn * inner - s[ax]
            t = np.minimum(t, np.linalg.norm(pts - img, axis=1) / C_M_S)
    return t


def gate(spec: RunSpec, source_m: np.ndarray, taper_s: float = 2e-4) -> np.ndarray:
    """(n_steps, Q) weights: each receiver's record kept until its first reflection
    (`reflection_times`), a raised cosine of `taper_s` ending there."""
    tr = reflection_times(spec, source_m)
    t = np.arange(spec.n_steps)[:, None] * spec.t_step
    x = np.clip((tr[None, :] - t) / taper_s, 0.0, 1.0)
    return (0.5 - 0.5 * np.cos(np.pi * x)).astype(np.float32)


def spectra(rec: Records, n_out: int, gated: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """(f_hz (n_out // 2 + 1), P (F, Q)): the records' spectra on the output grid's bins
    (an n_out-point FFT at fs_out), normalized so a free field is e^{-jkr} / r; each record
    gated before the grid's faces answer (`gate`)."""
    s = rec.spec
    nfft = n_out * s.m
    if nfft < rec.p.shape[0]:
        raise ValueError("the output FFT is shorter than the record")
    x = rec.p * gate(s, rec.ear_m) if gated else rec.p
    P = s.t_step * np.fft.rfft(x.astype(float), nfft, axis=0)[: n_out // 2 + 1]
    f = np.arange(n_out // 2 + 1) * s.fs_out / n_out
    return f, P

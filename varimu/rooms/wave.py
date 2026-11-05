"""The wave solver below a crossover (docs/ROOM_LOOP_PLAN.md R10; MIC_ROOM_PLAN.md A5's low
half): the room's response from finite differences (crates/roomsim's `fdtd`, the GPU or its
CPU reference), blended under the geometric model (varimu.rooms.shoebox.responses) by a
zero-phase crossover. Below the Schroeder frequency a room's sound is its modes: boomy notes,
bass that changes with position, a corner's build-up, which image sources and rays can't make.

**The grid.** The room (a PolyRoom; a Shoebox as its rectangle) is voxelized at a spacing X
of `PPW` points per wavelength at the crossover (20: the scheme's phase error <= 0.25% there,
<= 0.5% at the blend's top), cells centred half a cell off the floor plan's corners, so walls
lie between cells. A cell is in the room when its centre is. Each link from a cell in the room
to one outside is a piece of wall: the face it crosses, its material, and the staircase's
extra area corrected (a plane of unit normal n is crossed by |nx| + |ny| + |nz| links per X^2
of its area, so each link carries beta / |n|_1). The step T is a whole number m of the
project's samples, as long as the Courant number c T / X stays <= 1 / sqrt(3).

**Walls per band.** A wall is locally reacting with a real normalized admittance beta, chosen
so that its random-incidence absorption (Paris' integral of 1 - |(cos t - beta) / (cos t +
beta)|^2) is the material's alpha in the band. The room is LTI, so its response at f depends
only on the walls at f: one run per octave band whose weight reaches under the crossover,
each with its band's betas, the runs weighted by the band weights the geometric model uses
(varimu.rooms.shoebox.band_weights_at); bands whose walls are all alike share a run. Air:
each band's run decays by its band's ISO 9613-1 absorption over c t.

**Source and mics.** A unit impulse at the source (spread trilinearly over 8 cells), so the
response is the geometric model's (free-field 1 / r at r). Each mic records the pressure and
its gradient; the capsule's two entries are fitted to first order from its entry table,
E(f, theta) ~ A(f) + B(f) cos theta (plane waves; a small capsule below ~1 kHz), and applied
to the field as E = A p + B (aim . grad p) / (j k): the near field's gradient gives a
pressure-gradient capsule its proximity effect. The central difference's sin(kX) / (kX) is
undone.

**The zero-frequency mode.** A pressure impulse is a step of volume velocity: a sealed room
keeps the volume it was given, a pressure offset the walls' admittance doesn't drain (the
scheme's second-order form). Real rooms leak; the response is high-passed at `HP_HZ`
(fourth order, zero phase), far below a room's first mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np

from varimu.separation.room import BANDS_HZ, SPEED_OF_SOUND_M_S, air_absorption_db_per_m

PPW = 20.0
HP_HZ = 15.0
MIN_STEPS = 64


@cache
def _alpha_table() -> tuple[np.ndarray, np.ndarray]:
    """Random-incidence absorption over real normalized admittance (Paris' formula)."""
    beta = np.linspace(0.0, 1.5, 3001)
    th = np.linspace(0, np.pi / 2, 2001)
    c = np.cos(th)[None, :]
    b = beta[:, None]
    a = 1 - ((c - b) / (c + b)) ** 2
    alpha = np.trapezoid(a * np.sin(2 * th)[None, :], th, axis=1)
    k = int(np.argmax(alpha))
    return alpha[: k + 1], beta[: k + 1]


def beta_for_alpha(alpha: np.ndarray) -> np.ndarray:
    """The real normalized admittance whose random-incidence absorption is alpha (capped at
    the largest a locally reacting real admittance reaches, ~0.95)."""
    a_tab, b_tab = _alpha_table()
    return np.interp(np.clip(alpha, 0, a_tab[-1]), a_tab, b_tab)


def poly_of(room, objects: list | None = None):
    """A PolyRoom for a Shoebox (its rectangle; x0 / x1 / y0 / y1 as walls 3 / 1 / 0 / 2),
    with `objects` if given."""
    from varimu.rooms.polyroom import PolyRoom

    if isinstance(room, PolyRoom):
        return room
    lx, ly, lz = room.dims_m
    x0, x1, y0, y1, fl, ce = room.materials
    return PolyRoom(
        [[0, 0], [lx, 0], [lx, ly], [0, ly]],
        "flat",
        lz,
        None,
        0.0,
        8,
        x0,
        fl,
        ce,
        room.temp_c,
        room.rh_percent,
        {"wall 0": y0, "wall 1": x1, "wall 2": y1, "wall 3": x0},
        list(objects or []),
    )


@dataclass
class Voxels:
    dx_m: float
    origin_m: np.ndarray  # the centre of cell (0, 0, 0)
    dims: tuple[int, int, int]  # (nx, ny, nz)
    inside: np.ndarray  # (nz, ny, nx) bool
    codes: np.ndarray  # (n,) uint32: 0 outside, 1 interior, 2 + i a wall cell
    wall_cells: np.ndarray  # (b,) flat indices
    k: np.ndarray  # (b,) neighbours in the room
    beta_links: np.ndarray  # (b, bands): sum over the cell's wall links of beta / |n|_1

    def grid_coords(self, p_m) -> np.ndarray:
        return (np.asarray(p_m, float) - self.origin_m) / self.dx_m


def voxelize(room, dx_m: float) -> Voxels:
    """The room on a grid of spacing dx_m (the module docstring)."""
    from varimu.rooms.shoebox import ROOM_MATERIALS

    room = poly_of(room)
    lo = room.floor.min(0)
    hi = room.floor.max(0)
    top = float(max(room.height_m, room.peak_m))
    pad = 3
    origin = np.r_[lo - (pad - 0.5) * dx_m, -(pad - 0.5) * dx_m]
    nx = int(np.ceil((hi[0] - lo[0]) / dx_m)) + 2 * pad
    ny = int(np.ceil((hi[1] - lo[1]) / dx_m)) + 2 * pad
    nz = int(np.ceil(top / dx_m)) + 2 * pad
    xs = origin[0] + dx_m * np.arange(nx)
    ys = origin[1] + dx_m * np.arange(ny)
    zs = origin[2] + dx_m * np.arange(nz)
    gx, gy = np.meshgrid(xs, ys)  # (ny, nx)
    xy = np.stack([gx, gy], -1)
    in_floor = room.inside_floor(xy)
    h = room.height_at(xy)
    inside = (zs[:, None, None] > 0) & (zs[:, None, None] < h[None]) & in_floor[None]
    # objects (R11) out of the room, each at least a cell thick so a thin panel is a wall
    for b in room.boxes:
        grown = np.maximum(b.size_m, dx_m) - b.size_m
        for kz, z in enumerate(zs):
            pts = np.concatenate([xy, np.full(xy.shape[:2] + (1,), z)], axis=-1)
            q = (pts - b.center_m) @ b.axes
            inside[kz] &= ~np.all(np.abs(q) < 0.5 * (b.size_m + grown), axis=-1)
    # neighbours in the room
    k = np.zeros(inside.shape, np.int8)
    shifts = []
    for ax in (2, 1, 0):  # x, y, z in array axes (z, y, x)
        for sgn in (-1, 1):
            nb = np.zeros_like(inside)
            src = [slice(None)] * 3
            dst = [slice(None)] * 3
            if sgn > 0:
                dst[ax], src[ax] = slice(0, -1), slice(1, None)
            else:
                dst[ax], src[ax] = slice(1, None), slice(0, -1)
            nb[tuple(dst)] = inside[tuple(src)]
            k += nb
            shifts.append((ax, sgn, nb))
    inside &= k > 0  # an isolated cell is no room
    n = nx * ny * nz
    flat_inside = inside.ravel()
    wall = inside & (k < 6)
    wall_cells = np.flatnonzero(wall.ravel())
    codes = np.zeros(n, np.uint32)
    codes[flat_inside] = 1
    codes[wall_cells] = 2 + np.arange(len(wall_cells), dtype=np.uint32)
    # the wall links: each (cell, direction) whose neighbour is outside
    zz, yy, xx = np.unravel_index(wall_cells, inside.shape)
    centres = np.stack([xs[xx], ys[yy], zs[zz]], 1)
    nf = len(room.faces)
    normals = np.array([f.normal for f in room.faces])
    ds = np.array([f.d for f in room.faces])
    beta_faces = beta_for_alpha(np.array([ROOM_MATERIALS[m] for m in room.materials()]))
    beta_faces = beta_faces / np.abs(normals).sum(1)[:, None]  # the staircase's area
    beta_links = np.zeros((len(wall_cells), len(BANDS_HZ)))
    for ax, sgn, nb in shifts:
        missing = ~nb.ravel()[wall_cells]
        if not np.any(missing):
            continue
        a = centres[missing]
        step = np.zeros(3)
        step[{2: 0, 1: 1, 0: 2}[ax]] = sgn * dx_m
        b = a + step
        best_t = np.full(len(a), np.inf)
        best_f = np.full(len(a), -1)
        for fi, f in enumerate(room.faces):
            nd = step @ f.normal
            if abs(nd) < 1e-12:
                continue
            t = (f.d - a @ f.normal) / nd
            ok = (t > -1e-9) & (t <= 1 + 1e-9) & (t < best_t)
            if not np.any(ok):
                continue
            idx = np.flatnonzero(ok)
            hit = a[idx] + t[idx, None] * step
            on = room.on_face(f, hit, tol=1e-6)
            best_t[idx[on]] = t[idx[on]]
            best_f[idx[on]] = fi
        lost = best_f < 0
        if np.any(lost):  # no face crossed exactly (a corner): the nearest plane
            dist = np.abs(a[lost] @ normals.T - ds[None, :])
            best_f[lost] = np.argmin(dist, axis=1)
        beta_links[np.flatnonzero(missing)] += beta_faces[best_f]
    del nf
    return Voxels(
        dx_m,
        origin,
        (nx, ny, nz),
        inside,
        codes,
        wall_cells,
        k[zz, yy, xx].astype(float),
        beta_links,
    )


def first_order_entries(table) -> tuple[np.ndarray, np.ndarray]:
    """A capsule's entries to first order in the plane wave's angle: per entry (front, rear)
    A(f), B(f) on the table's grid, (2, grid) each, by least squares over the sphere."""
    th = np.radians(np.linspace(0, 180, 73))
    front, rear = table.at(th, np.full(len(th), np.inf))
    w = np.sqrt(np.sin(th) + 1e-3)[:, None]
    m = np.stack([np.ones_like(th), np.cos(th)], 1) * w
    pinv = np.linalg.pinv(m)
    a, b = [], []
    for e in (front, rear):
        coef = pinv @ (e * w)  # (2, grid)
        a.append(coef[0])
        b.append(coef[1])
    return np.array(a), np.array(b)


def _bands_under(f_hi: float) -> list[int]:
    return [b for b in range(len(BANDS_HZ)) if b == 0 or BANDS_HZ[b - 1] < f_hi]


def crossover_weights(f: np.ndarray, crossover_hz: float) -> np.ndarray:
    """The wave solver's share at f: 1 below crossover / sqrt 2, 0 above crossover * sqrt 2,
    a raised cosine in log f between (the geometric model takes 1 minus it)."""
    lf = np.log2(np.maximum(f, 1e-3) / crossover_hz)
    u = np.clip((lf + 0.5), 0, 1)
    return 0.5 + 0.5 * np.cos(np.pi * u)


def grid_step(crossover_hz: float, fs: float) -> tuple[float, int, float]:
    """(X in m, m samples per step, the Courant number) for a crossover (the docstring)."""
    c = SPEED_OF_SOUND_M_S
    dx = c / (PPW * crossover_hz)
    m = int(np.floor(fs * dx / (c * np.sqrt(3)) + 1e-9))
    if m < 1:
        raise ValueError(f"crossover {crossover_hz} Hz: too high for {fs} Hz")
    return dx, m, c * (m / fs) / dx


def responses(
    room,
    sources_m: list[np.ndarray],
    mics,
    fs: float,
    n_fft: int,
    *,
    crossover_hz: float,
    rt_s: np.ndarray,
    length_s: float,
    backend: str | None = None,
    log=None,
) -> tuple[np.ndarray, np.ndarray]:
    """The wave solver's spectra of every (source, mic, entry) on the n_fft-point grid at fs,
    up to the crossover's top, times its share (`crossover_weights` and the high-pass), and
    the crossover's weights (the geometric model takes 1 minus them): ((sources, mics, 2,
    bins) complex, (bins,)). `rt_s` per band sets each run's
    length (1.2 RT plus the farthest mic's travel, at most length_s); `mics` are
    varimu.rooms.shoebox.Mic."""
    import time

    from varimu.rooms import gpu
    from varimu.rooms.shoebox import band_weights_at

    b = gpu.resolve(backend)
    if b == "numpy":
        b = "cpu"  # the wave solver has no numpy reference: roomsim's f64 one
    if gpu.module() is None:
        raise RuntimeError("the wave solver needs roomsim: uv sync --extra fast")
    c = SPEED_OF_SOUND_M_S
    dx, m, lam = grid_step(crossover_hz, fs)
    t_step = m / fs
    t0 = time.perf_counter()
    vox = voxelize(room, dx)
    if log:
        n_room = int(vox.inside.sum())
        log(f"wave solver: X {dx * 100:.2f} cm, {n_room:,} cells in the room, {fs / m:.0f} Hz")
    f_hi = crossover_hz * np.sqrt(2)
    f_all = np.fft.rfftfreq(n_fft, 1 / fs)
    kmax = int(np.searchsorted(f_all, f_hi)) + 1
    f = f_all[:kmax]
    hp = np.where(f > 0, (f / HP_HZ) ** 4 / np.sqrt(1 + (f / HP_HZ) ** 8), 0.0)
    xw = crossover_weights(f, crossover_hz)
    share = xw * hp
    bw = band_weights_at(np.maximum(f, 1e-3))
    bands = _bands_under(f_hi)
    groups: list[list[int]] = []
    for bi in bands:
        for g in groups:
            if np.array_equal(vox.beta_links[:, g[0]], vox.beta_links[:, bi]):
                g.append(bi)
                break
        else:
            groups.append([bi])
    k = 2 * np.pi * f / c
    with np.errstate(divide="ignore", invalid="ignore"):
        grad_fix = np.where(k * dx > 1e-9, (k * dx) / np.sin(k * dx), 1.0)
        inv_jk = np.where(k > 0, 1 / (1j * k), 0.0)
    fits = {}
    for mic in mics:
        if id(mic.table) not in fits:
            a, bb = first_order_entries(mic.table)
            fg = mic.table.f_grid

            def interp(v, fg=fg):
                return np.interp(f, fg, v.real) + 1j * np.interp(f, fg, v.imag)

            fits[id(mic.table)] = (
                [interp(a[e]) for e in range(2)],
                [interp(bb[e]) for e in range(2)],
            )
    mics_g = np.array([vox.grid_coords(mm.position_m) for mm in mics])
    out = np.zeros((len(sources_m), len(mics), 2, kmax), complex)
    nx, ny, _ = vox.dims
    for si, src in enumerate(sources_m):
        sg = vox.grid_coords(src)
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
                    cell = (base[0] + dxx) + nx * ((base[1] + dy) + ny * (base[2] + dz))
                    if vox.codes[cell] == 0:
                        raise ValueError(f"a source at {list(src)} is too close to a wall")
                    idx.append(cell)
                    val.append(4 * np.pi * lam**2 / (dx * t_step) * w)
        far = max(np.linalg.norm(mm.position_m - np.asarray(src)) for mm in mics)
        for g in groups:
            rt = float(np.max(rt_s[g]))
            n_steps = int(min(1.2 * rt + far / c, length_s) / t_step)
            n_steps = max(n_steps, MIN_STEPS)
            t1 = time.perf_counter()
            rec = run_band(vox, lam, vox.beta_links[:, g[0]], (idx, val), mics_g, n_steps, b)
            if log:
                log(
                    f"  source {si} bands {[int(BANDS_HZ[x]) for x in g]}: {n_steps} steps "
                    f"in {time.perf_counter() - t1:.1f} s"
                )
            air = air_absorption_db_per_m(BANDS_HZ[g], room.temp_c, room.rh_percent).mean()
            env = 10 ** (-air * c * t_step * np.arange(n_steps) / 20)
            rec = rec * env[:, None, None]
            wsum = bw[g].sum(0)
            for mi, mic in enumerate(mics):
                p = rec[:, mi, 0]
                gr = rec[:, mi, 1:] @ mic.aim / dx
                pf = t_step * np.fft.rfft(p, n_fft)[: kmax * m : m][:kmax]
                gf = t_step * np.fft.rfft(gr, n_fft)[: kmax * m : m][:kmax] * grad_fix
                a, bb = fits[id(mic.table)]
                for e in range(2):
                    out[si, mi, e] += wsum * (a[e] * pf + bb[e] * gf * inv_jk)
    if log:
        log(f"wave solver: {time.perf_counter() - t0:.1f} s")
    return out * share[None, None, None, :], xw


def run_band(vox: Voxels, lam: float, beta_links_b: np.ndarray, inject, mics_g, n_steps, b):
    from varimu.rooms import gpu

    g = 0.5 * lam * beta_links_b
    out = gpu.module().fdtd_run(
        vox.dims,
        np.ascontiguousarray(vox.codes, np.uint32),
        np.ascontiguousarray(vox.k, float),
        np.ascontiguousarray(g, float),
        float(lam),
        np.ascontiguousarray(inject[0], np.uint32),
        np.ascontiguousarray(inject[1], float),
        np.ascontiguousarray(mics_g, float).ravel(),
        int(n_steps),
        backend=b,
    )
    return np.asarray(out).reshape(n_steps, len(mics_g), 4)

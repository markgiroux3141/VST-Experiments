"""The moving head on particles (docs/TAPE_PARTICLES.md, "The moving head"): Sound Talk
No. 21's recording, the Preisach medium's geometry and demagnetization with its Preisach
cells replaced by Stoner-Wohlfarth particles.

The coating is cells (x cells of ds along the tape, `layers` in depth), as in
`varimu.devices.tape`; every cell holds the same sample of particles (the bench's
distributions, fitted to the static data), which see the head's field at their cell's
position as the tape passes the record gap: the deep-gap field a sin(2 pi f t) + B sin(2 pi
f_b t) times (Hx, Hy) of `head_field` at the cell's height, `steps_per_cycle` steps per bias
cycle, while the cell is within the zone (where the head's field can switch a particle),
then `e_steps` in the free demagnetizing field (the tape leaving the head). The particles
switch by the master equation of `sw` (the expectation over thermal histories: no Monte
Carlo noise, so the antithetic +-a difference is exact).

The coating's own field is the Preisach medium's: `demag_fields_vector` of the cells'
(M_x, M_y), from wavelengths above 3 bias wavelengths, with the head's image during the pass
and free after; each cell sees the final pattern's field throughout its pass (the same
approximation as `record_demagnetized_vector`), solved by damped fixed-point iteration.
The readback is `tone_harmonics`'.

Particles don't interact here beyond the cells' demagnetization: the bench measures what
dynamic local interactions add (they don't, at the strength the static data allow).

The time stepping runs on the GPU (`tpsim strip --gpu`, `crates/tapeparticles/src/
strip.rs`, `head.wgsl`; f64 CPU reference without --gpu); `reference` here is the same in
numpy for tiny cases.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import numpy as np

from varimu.devices.tape import (
    HeadGeometry,
    Slab,
    demag_fields_vector,
    head_field,
    head_hx_spectrum,
    head_hy_spectrum,
    lstsq_mgs,
)
from varimu.tape_particles import bench as bn
from varimu.tape_particles import ensemble as ens
from varimu.tape_particles import runner


@dataclass(frozen=True)
class Machine:
    """No. 21's Ampex 300 (scripts/tape_switching_study.py's no21_spec: TapeMachineSpec at
    15 ips, 70 kHz bias, a 51 um record gap; poles, repro gap and spacing its defaults)."""

    speed_m_s: float = 0.381
    f_bias_hz: float = 70e3
    rec: HeadGeometry = HeadGeometry(51e-6, 3e-3, 3e-3)
    rep: HeadGeometry = HeadGeometry(6.35e-6, 3e-3, 3e-3)
    spacing_m: float = 0.5e-6
    coating_m: float = 12.7e-6

    @property
    def lam_min_m(self) -> float:
        return 3.0 * self.speed_m_s / self.f_bias_hz


@dataclass(frozen=True)
class Numerics:
    layers: int = 6
    cells_per_bias_wavelength: float = 7.62
    steps_per_cycle: int = 16
    floor_a_m: float = 60.0 * bn.OE
    e_steps: int = 3
    guard_waves: int = 2
    read_waves: int = 3
    demag_iterations: int = 12
    demag_mix: float = 0.1
    demag_tol: float = 2e-3
    image: bool = True
    #: the cell's own perpendicular demagnetization, -Ms_coat M_y, implicit in each step
    #: (`step_local`: bisection on the cell's M_y; at most 256 particles a cell)
    local_demag: bool = False
    grid: int = 32
    iters: int = 10

    def ds_m(self, mach: Machine) -> float:
        return mach.speed_m_s / mach.f_bias_hz / self.cells_per_bias_wavelength


def zone_m(mach: Machine, peak_a_m: float, floor_a_m: float) -> float:
    x = np.linspace(0, 3e-3, 300001)
    hx, hy = head_field(mach.rec, x, np.full_like(x, mach.spacing_m))
    on = np.hypot(hx, hy) * peak_a_m >= floor_a_m
    return float(x[on].max()) if on.any() else mach.rec.gap_m


def sample(spec: bn.BenchSpec, count: int, seed: int = 1, name: str = "strip"):
    """(axes, H_K, e0_kt, volumes): `count` particles of the bench's distributions."""
    box = bn.make_box(spec.with_(packed=False), count, seed=seed, name=name)
    return box.n, box.hk, box.e0_kt, box.v


def tables(mach: Machine, num: Numerics, z_m: float):
    """The pass's steps: (S, dt, head factors S x layers x 2)."""
    dt = 1.0 / (mach.f_bias_hz * num.steps_per_cycle)
    s = int(math.ceil(2 * z_m / (mach.speed_m_s * dt)))
    rel = z_m - mach.speed_m_s * dt * np.arange(s)  # the cell's position past the gap's centre
    dy = mach.coating_m / num.layers
    heights = mach.spacing_m + (np.arange(num.layers) + 0.5) * dy
    tab = np.zeros((s, num.layers, 2))
    for li, y in enumerate(heights):
        fx, fy = head_field(mach.rec, rel, np.full_like(rel, y))
        tab[:, li, 0], tab[:, li, 1] = fx, fy
    return s, dt, tab


def run(parts, spec, mach, num, f_sig, a_sig, bias, x_cells, hs, he, gpu=True, seed=1):
    """One pass of every cell (both signs): M / M_sat per cell, (2, ncx, layers, 3).
    hs, he: (2, ncx, layers, 2) static fields during and after the pass (A/m)."""
    n, hk, e0, v = parts
    z = zone_m(mach, abs(a_sig) + bias, num.floor_a_m)
    s, dt, tab = tables(mach, num, z)
    ncx, nl = len(x_cells), num.layers
    t0 = (x_cells - z) / mach.speed_m_s  # when each cell enters the zone
    repc = np.zeros((2, ncx, nl, 7))
    repc[..., 0] = np.mod(mach.f_bias_hz * t0, 1.0)[None, :, None]
    repc[..., 1] = np.mod(f_sig * t0, 1.0)[None, :, None]
    repc[..., 2:4] = hs
    repc[..., 4:6] = he
    repc[0, ..., 6], repc[1, ..., 6] = 1.0, -1.0
    meta = {
        "n_particles": len(hk),
        "reps": 2 * ncx * nl,
        "layers": nl,
        "s_steps": s,
        "e_steps": num.e_steps,
        "a_sig": a_sig,
        "bias": bias,
        "fs_dt": f_sig * dt,
        "inv_m": 1.0 / num.steps_per_cycle,
        "dt": dt,
        "f0": spec.f0_hz,
        "grid": num.grid,
        "iters": num.iters,
        "stochastic": False,
        "seed": seed,
        "ms_local": spec.packing * spec.ms_p_a_m if num.local_demag else 0.0,
    }
    d = tempfile.mkdtemp(prefix="tp_strip_")
    try:
        from pathlib import Path

        dd = Path(d)
        runner.write(
            dd,
            meta,
            {
                "n": n,
                "hk": hk,
                "e0_kt": e0,
                "v": v,
                "p0": np.full(len(hk), 0.5),
                "tab": tab,
                "repc": repc,
            },
        )
        cmd = [str(runner.tpsim()), "strip", d] + (["--gpu"] if gpu else ["--threads", "6"])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"tpsim strip failed: {r.stderr}")
        m = runner.read(dd, "out_m").reshape(2, ncx, nl, 3)
        info = json.loads((dd / "out.json").read_text())
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return m, {"steps": s + num.e_steps, "zone_m": z, **info}


def reference(parts, spec, mach, num, f_sig, a_sig, bias, x_cells, hs, he):
    """`run` in numpy (ensemble.step per step; tiny cases only)."""
    n, hk, e0, v = parts
    z = zone_m(mach, abs(a_sig) + bias, num.floor_a_m)
    s, dt, tab = tables(mach, num, z)
    ncx, nl = len(x_cells), num.layers
    t0 = (x_cells - z) / mach.speed_m_s
    pt = ens.Particles(n, hk, v, e0, np.zeros((len(hk), 3)))
    out = np.zeros((2, ncx, nl, 3))
    ms_local = spec.packing * spec.ms_p_a_m if num.local_demag else 0.0
    for si, sg in enumerate((1.0, -1.0)):
        for c in range(ncx):
            for li in range(nl):
                p = np.full(len(hk), 0.5)
                m = None
                for j in range(s + num.e_steps):
                    if j < s:
                        pb = (mach.f_bias_hz * t0[c] % 1.0) + j / num.steps_per_cycle
                        ps = (f_sig * t0[c] % 1.0) + j * f_sig * dt
                        hg = sg * a_sig * math.sin(2 * math.pi * ps) + bias * math.sin(
                            2 * math.pi * pb
                        )
                        h = np.array(
                            [
                                hg * tab[j, li, 0] + hs[si, c, li, 0],
                                hg * tab[j, li, 1] + hs[si, c, li, 1],
                                0.0,
                            ]
                        )
                    else:
                        h = np.array([he[si, c, li, 0], he[si, c, li, 1], 0.0])
                    if ms_local > 0:
                        # Implicit: mu = F(h - Ms mu), bisection (head.wgsl's step_local).
                        lo, hi = -1.0, 1.0
                        for _ in range(14):
                            mu = 0.5 * (lo + hi)
                            hh = h.copy()
                            hh[1] -= ms_local * mu
                            _, mt = ens.step(pt, np.tile(hh, (len(hk), 1)), p, dt, spec, num.grid)
                            fm = float((v * mt[:, 1]).sum() / v.sum())
                            lo, hi = (mu, hi) if fm > mu else (lo, mu)
                        h[1] -= ms_local * 0.5 * (lo + hi)
                    p, m = ens.step(pt, np.tile(h, (len(hk), 1)), p, dt, spec, num.grid)
                out[si, c, li] = (v[:, None] * m).sum(axis=0) / v.sum()
    return out


def readback(mx, my, x_cells, mach, num, f_sig) -> complex:
    """tone_harmonics' fundamental of one sign's pattern (layers x cells, M / Ms of any
    scale)."""
    lam = mach.speed_m_s / f_sig
    k = 2 * math.pi / lam
    a0 = num.guard_waves * lam
    sel = (x_cells >= a0) & (x_cells < a0 + num.read_waves * lam)
    ph = np.exp(-1j * k * x_cells[sel])
    ax = (mx[:, sel] * ph).mean(axis=1) * 2
    ay = (my[:, sel] * ph).mean(axis=1) * 2
    dy = mach.coating_m / num.layers
    ys = mach.spacing_m + (np.arange(num.layers) + 0.5) * dy
    ks = np.array([k])
    wx = np.array([head_hx_spectrum(mach.rep, ks, y)[0] for y in ys]) / mach.rep.gap_m
    wy = np.array([head_hy_spectrum(mach.rep, ks, y)[0] for y in ys]) / mach.rep.gap_m
    return complex(1j * k * mach.speed_m_s * ((ax * wx).sum() - (ay * wy).sum()) * mach.rep.gap_m)


def tone(spec, parts, mach, num, f_sig, a_sig, bias, gpu=True, log=None):
    """A tone recorded at bias: (the antithetic fundamental, info). The demagnetization's
    fixed point: each iteration records every cell with the last pattern's field."""
    lam = mach.speed_m_s / f_sig
    ds = num.ds_m(mach)
    length = (2 * num.guard_waves + num.read_waves) * lam
    x_cells = (np.arange(int(round(length / ds))) + 0.5) * ds
    ncx, nl = len(x_cells), num.layers
    slab = Slab(mach.coating_m, nl, ds, mach.spacing_m)
    ms_coat = spec.packing * spec.ms_p_a_m
    hs = np.zeros((2, ncx, nl, 2))
    he = np.zeros((2, ncx, nl, 2))
    hist = []

    def fields(m):
        for si in range(2):
            mx = ms_coat * m[si, :, :, 0].T  # layers x cells, A/m
            my = ms_coat * m[si, :, :, 1].T
            (fx, fy), (ix, iy) = demag_fields_vector(
                mx, my, slab, 1.0, mach.lam_min_m, image_spacings_m=(None, mach.spacing_m)
            )
            if num.local_demag:
                # The cell's own -Ms M_y is solved inside each step (`step_local`): leave
                # the rest (its long-wavelength limit is that self term).
                fy, iy = fy + my, iy + my
            he[si, :, :, 0], he[si, :, :, 1] = fx.T, fy.T
            if num.image:
                hs[si, :, :, 0], hs[si, :, :, 1] = ix.T, iy.T
            else:
                hs[si] = he[si]

    # Anderson-accelerated fixed point on the cells' (M_x, M_y), as
    # record_demagnetized_vector does it (history 6, the same least squares).
    m, info = run(parts, spec, mach, num, f_sig, a_sig, bias, x_cells, hs, he, gpu=gpu)
    xs, gs = [], []
    x = m[..., :2].ravel().copy()
    for it in range(num.demag_iterations):
        fields(m)
        mr, info = run(parts, spec, mach, num, f_sig, a_sig, bias, x_cells, hs, he, gpu=gpu)
        g = mr[..., :2].ravel() - x
        hist.append(float(np.sqrt(np.mean(g**2))))
        if log:
            log(f"      demag it {it}: rms change {hist[-1]:.2e}")
        if hist[-1] < num.demag_tol:
            m = mr
            break
        xs.append(x.copy())
        gs.append(g.copy())
        xs, gs = xs[-6:], gs[-6:]
        if len(gs) > 1:
            dg = [gs[i + 1] - gs[i] for i in range(len(gs) - 1)]
            dx = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
            for c, a_, b_ in zip(lstsq_mgs(dg, g), dx, dg, strict=True):
                if c != 0.0:
                    x = x - c * (a_ + b_)
            x = x + g
        else:
            x = x + num.demag_mix * g
        x = np.clip(x, -1.0, 1.0)
        m = mr.copy()
        m[..., :2] = x.reshape(m[..., :2].shape)
    r = [readback(m[si, :, :, 0].T, m[si, :, :, 1].T, x_cells, mach, num, f_sig) for si in range(2)]
    return 0.5 * (r[0] - r[1]), {"demag_changes": hist, "cells": ncx, **info}


def tone_coupled(
    spec,
    parts,
    mach,
    num,
    f_sig,
    a_sig,
    bias,
    q: int = 2,
    update_every: int = 1,
    lam_min: str = "medium",
    log=None,
    demag_scale: float = 1.0,
):
    """A tone with the coating's field causal: every cell steps in absolute time (the step
    dt = ds / (v q), so cell c enters the zone at step c q), and every `update_every` steps
    the cells' present (M_x, M_y) give the field on all of them (imaged for the cells in the
    zone, free for the rest: `tpsim strip --coupled`). This replaces the fixed point of
    `tone`, which with particles settles into a limit cycle (docs/TAPE_PARTICLES.md).
    lam_min: "medium" (the Preisach medium's: wavelengths above 3 bias wavelengths) or
    "none" (the whole pattern). Returns (the antithetic fundamental, info)."""
    from pathlib import Path

    from varimu.devices.tape import _demag_kernels

    n, hk, e0, v = parts
    lam = mach.speed_m_s / f_sig
    ds = num.ds_m(mach)
    length = (2 * num.guard_waves + num.read_waves) * lam
    x_cells = (np.arange(int(round(length / ds))) + 0.5) * ds
    ncx, nl = len(x_cells), num.layers
    dt = ds / (mach.speed_m_s * q)
    z = zone_m(mach, abs(a_sig) + bias, num.floor_a_m)
    s_steps = int(math.ceil(2 * z / (mach.speed_m_s * dt)))
    rel = z - mach.speed_m_s * dt * np.arange(s_steps)
    dy = mach.coating_m / nl
    heights = mach.spacing_m + (np.arange(nl) + 0.5) * dy
    tab = np.zeros((s_steps, nl, 2))
    for li, y in enumerate(heights):
        fx, fy = head_field(mach.rec, rel, np.full_like(rel, y))
        tab[:, li, 0], tab[:, li, 1] = fx, fy
    t_c = (x_cells - z) / mach.speed_m_s
    repc = np.zeros((2, ncx, nl, 7))
    repc[..., 0] = np.mod(mach.f_bias_hz * t_c, 1.0)[None, :, None]
    repc[..., 1] = np.mod(f_sig * t_c, 1.0)[None, :, None]
    repc[0, ..., 6], repc[1, ..., 6] = 1.0, -1.0
    k0 = np.broadcast_to((np.arange(ncx) * q)[None, :, None], (2, ncx, nl)).astype(float)
    total = (ncx - 1) * q + s_steps + num.e_steps
    n_fft = 1 << int(math.ceil(math.log2(2 * ncx)))
    slab = Slab(mach.coating_m, nl, ds, mach.spacing_m)
    lm = mach.lam_min_m if lam_min == "medium" else None
    arrays = {
        "n": n,
        "hk": hk,
        "e0_kt": e0,
        "v": v,
        "p0": np.full(len(hk), 0.5),
        "tab": tab,
        "repc": repc,
        "k0": k0,
    }
    for name, img in (("img", mach.spacing_m if num.image else None), ("free", None)):
        keep, kern = _demag_kernels(n_fft, slab, lm, 16, img)
        arrays[f"{name}_kept"] = np.nonzero(keep)[0]
        arrays[f"{name}_k"] = np.stack([np.stack(kern).real, np.stack(kern).imag], axis=-1)
    meta = {
        "n_particles": len(hk),
        "reps": 2 * ncx * nl,
        "layers": nl,
        "s_steps": s_steps,
        "e_steps": num.e_steps,
        "a_sig": a_sig,
        "bias": bias,
        "fs_dt": f_sig * dt,
        "inv_m": mach.f_bias_hz * dt,
        "dt": dt,
        "f0": spec.f0_hz,
        "grid": num.grid,
        "iters": num.iters,
        "stochastic": False,
        "seed": 1,
        "ncx": ncx,
        "n_fft": n_fft,
        "total_steps": total,
        "update_every": update_every,
        "ms_coat": demag_scale * spec.packing * spec.ms_p_a_m,
    }
    d = tempfile.mkdtemp(prefix="tp_cstrip_")
    try:
        dd = Path(d)
        runner.write(dd, meta, arrays)
        r = subprocess.run(
            [str(runner.tpsim()), "strip", d, "--coupled"], capture_output=True, text=True
        )
        if r.returncode != 0:
            raise RuntimeError(f"tpsim strip --coupled failed: {r.stderr}")
        m = runner.read(dd, "out_m").reshape(2, ncx, nl, 3)
        info = json.loads((dd / "out.json").read_text())
    finally:
        shutil.rmtree(d, ignore_errors=True)
    rb = [
        readback(m[si, :, :, 0].T, m[si, :, :, 1].T, x_cells, mach, num, f_sig) for si in range(2)
    ]
    return 0.5 * (rb[0] - rb[1]), {"cells": ncx, "steps": total, "zone_m": z, **info}

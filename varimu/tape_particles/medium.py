"""Recording on a strip of coating moving past the record head (docs/TAPE_PARTICLES.md,
"The moving head"): Stoner-Wohlfarth particles placed in the coating, the head's field
(`varimu.devices.tape.head_field`) times the deep-gap field s sin(2 pi f t) + B sin(2 pi
f_b t), and the coating's own field as cells (`varimu.devices.tape._demag_kernels`: layered
2D magnetostatics, with the head's image while a cell is in the zone, free after), updated
every few steps; then the strip off the head relaxes in its free demagnetizing field. The
readback is tone_harmonics': each particle's moment through the repro head's spectrum at
its depth, projected on the tone over whole wavelengths.

The time stepping runs in `crates/tapeparticles` (`tpsim medium`, f64 on the CPU's
threads, `medium.rs`), which this module drives; `record_reference` is the same algorithm
in numpy for small strips (the tests hold the two together).

The local interactions here are a quenched random field per particle (`sigma_int_a_m`):
the bench (`bench`) measures what dynamic interactions add.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from varimu.devices.tape import (
    HeadGeometry,
    Slab,
    _demag_kernels,
    head_field,
    head_hx_spectrum,
    head_hy_spectrum,
)
from varimu.tape_particles import bench as bn
from varimu.tape_particles import ensemble as ens
from varimu.tape_particles import runner, sw


@dataclass(frozen=True)
class Machine:
    """No. 21's Ampex 300 (scripts/tape_switching_study.py's no21_spec)."""

    speed_m_s: float = 0.381
    f_bias_hz: float = 70e3
    rec: HeadGeometry = HeadGeometry(51e-6, 3e-3, 3e-3)
    rep: HeadGeometry = HeadGeometry(6.35e-6, 3e-3, 3e-3)
    spacing_m: float = 0.5e-6
    coating_m: float = 12.7e-6


@dataclass(frozen=True)
class Numerics:
    width_m: float = 0.5e-6
    ds_m: float = 0.5e-6
    layers: int = 8
    steps_per_cycle: int = 16
    update_every: int = 4
    floor_a_m: float = 40.0 * bn.OE
    guard_waves: int = 2
    read_waves: int = 3
    relax_steps: int = 3
    relax_dt_s: float = 0.03
    grid: int = 32
    iters: int = 10
    image: bool = True


@dataclass
class Strip:
    x: np.ndarray  # along the tape (m)
    depth: np.ndarray  # into the coating (m)
    n: np.ndarray
    hk: np.ndarray
    e0_kt: np.ndarray
    hloc: np.ndarray
    v: np.ndarray
    cell: np.ndarray
    cell_start: np.ndarray
    ncx: int
    length_m: float


def place(
    spec: bn.BenchSpec,
    sigma_int_a_m: float,
    length_m: float,
    mach: Machine,
    num: Numerics,
    seed: int = 1,
    name: str = "strip",
) -> Strip:
    """Particles of the bench's distributions, uniform in the strip (length x coating x
    width), sorted by (x cell, layer)."""
    g = {k: ens.rng_for(seed, f"{name}.{k}") for k in ("l", "hk", "axis", "phi", "x", "y", "hloc")}
    v_med = 0.25 * math.pi * (spec.length_median_m / spec.aspect) ** 2 * spec.length_median_m
    v_mean = v_med * math.exp(0.5 * (3 * spec.sigma_ln_length) ** 2)
    count = int(round(spec.packing * length_m * mach.coating_m * num.width_m / v_mean))
    l = spec.length_median_m * np.exp(spec.sigma_ln_length * g["l"].standard_normal(count))  # noqa: E741 (l: the needles' lengths)
    w = l / spec.aspect
    v = 0.25 * math.pi * w * w * l
    t = ens.watson_cos(spec.kappa, g["axis"].random(count))
    phi = 2 * math.pi * g["phi"].random(count)
    st = np.sqrt(np.maximum(0.0, 1 - t * t))
    n = np.stack([t, st * np.cos(phi), st * np.sin(phi)], axis=1)
    hk = spec.hk_median_a_m * np.exp(spec.sigma_ln_hk * g["hk"].standard_normal(count))
    c = 2.0 * spec.kv_kt_median * spec.kt_j / (sw.MU0 * spec.ms_p_a_m * spec.hk_median_a_m * v_med)
    e0 = sw.MU0 * spec.ms_p_a_m * hk * c * v / spec.kt_j
    x = length_m * g["x"].random(count)
    depth = mach.coating_m * g["y"].random(count)
    hloc = sigma_int_a_m * g["hloc"].standard_normal((count, 3))
    ncx = int(math.ceil(length_m / num.ds_m))
    xc = np.minimum((x / num.ds_m).astype(int), ncx - 1)
    lay = np.minimum((depth / (mach.coating_m / num.layers)).astype(int), num.layers - 1)
    cell = xc * num.layers + lay
    o = np.lexsort((x, cell))
    cell = cell[o]
    starts = np.searchsorted(cell, np.arange(ncx * num.layers + 1))
    return Strip(x[o], depth[o], n[o], hk[o], e0[o], hloc[o], v[o], cell, starts, ncx, length_m)


def zone_m(mach: Machine, peak_a_m: float, floor_a_m: float) -> float:
    """How far from the gap's centre |H| at the coating's front reaches floor at the peak."""
    x = np.linspace(0, 3e-3, 300001)
    hx, hy = head_field(mach.rec, x, np.full_like(x, mach.spacing_m))
    on = np.hypot(hx, hy) * peak_a_m >= floor_a_m
    return float(x[on].max()) if on.any() else mach.rec.gap_m


def schedule(
    strip: Strip,
    mach: Machine,
    num: Numerics,
    f_sig: float,
    a_sig: float,
    bias: float,
    phase: float = 0.0,
):
    """Per step: the gap's position, the deep-gap field, the zone's x cells [c0, c1)."""
    z = zone_m(mach, abs(a_sig) + bias, num.floor_a_m)
    dt = 1.0 / (mach.f_bias_hz * num.steps_per_cycle)
    x0, x1 = -z, strip.length_m + z
    steps = int(math.ceil((x1 - x0) / (mach.speed_m_s * dt)))
    t = np.arange(steps) * dt
    xg = x0 + mach.speed_m_s * t
    tt = xg / mach.speed_m_s  # the signal's time: the tape at x is recorded at x / v
    hg = a_sig * np.sin(2 * math.pi * f_sig * tt) + bias * np.sin(
        2 * math.pi * mach.f_bias_hz * t + phase
    )
    c0 = np.clip(np.floor((xg - z) / num.ds_m), 0, strip.ncx).astype(int)
    c1 = np.clip(np.ceil((xg + z) / num.ds_m) + 1, 0, strip.ncx).astype(int)
    return xg, hg, c0, np.maximum(c1, c0), dt


def kernels(strip: Strip, mach: Machine, num: Numerics):
    n_fft = 1 << int(math.ceil(math.log2(2 * strip.ncx)))
    slab = Slab(mach.coating_m, num.layers, num.ds_m, mach.spacing_m)
    out = {}
    for name, img in (("img", mach.spacing_m if num.image else None), ("free", None)):
        keep, (kxx, kxy, kyx, kyy) = _demag_kernels(n_fft, slab, None, 16, img)
        out[name] = (np.nonzero(keep)[0], np.stack([kxx, kxy, kyx, kyy]))
    return n_fft, out


def record(
    strip: Strip,
    spec: bn.BenchSpec,
    mach: Machine,
    num: Numerics,
    f_sig: float,
    a_sig: float,
    bias: float,
    threads: int = 6,
    seed: int = 1,
    phase: float = 0.0,
    keep: Path | None = None,
):
    """Runs tpsim medium: (p, m (N x 3)) after the pass and the relaxation."""
    xg, hg, c0, c1, dt = schedule(strip, mach, num, f_sig, a_sig, bias, phase)
    n_fft, ker = kernels(strip, mach, num)
    d = Path(tempfile.mkdtemp(prefix="tp_medium_")) if keep is None else keep
    meta = {
        "n_particles": len(strip.x),
        "layers": num.layers,
        "ncx": strip.ncx,
        "steps": len(xg),
        "n_fft": n_fft,
        "update_every": num.update_every,
        "dt": dt,
        "f0": spec.f0_hz,
        "grid": num.grid,
        "iters": num.iters,
        "stochastic": False,
        "seed": seed,
        "relax_steps": num.relax_steps,
        "relax_dt": num.relax_dt_s,
        "head": [mach.rec.gap_m, mach.rec.pole_m, mach.rec.relax_m],
        "ms_p": spec.ms_p_a_m,
        "cell_vol": num.ds_m * (mach.coating_m / num.layers) * num.width_m,
    }
    arrays = {
        "n": strip.n,
        "hk": strip.hk,
        "e0_kt": strip.e0_kt,
        "hloc": strip.hloc,
        "x": strip.x,
        "y": mach.spacing_m + strip.depth,
        "v": strip.v,
        "cell": strip.cell,
        "p0": np.full(len(strip.x), 0.5),
        "cell_start": strip.cell_start,
        "step_x": xg,
        "step_hg": hg,
        "step_c0": c0,
        "step_c1": c1,
    }
    for name, (kept, k) in ker.items():
        arrays[f"{name}_kept"] = kept
        arrays[f"{name}_k"] = np.stack([k.real, k.imag], axis=-1)
    runner.write(d, meta, arrays)
    r = subprocess.run(
        [str(runner.tpsim()), "medium", str(d), "--threads", str(threads)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"tpsim medium failed: {r.stderr}")
    p = runner.read(d, "out_p")
    m = runner.read(d, "out_m").reshape(-1, 3)
    info = json.loads((d / "out.json").read_text())
    if keep is None:
        shutil.rmtree(d, ignore_errors=True)
    return p, m, info


def readback(strip: Strip, m: np.ndarray, mach: Machine, num: Numerics, f_sig: float) -> complex:
    """The repro EMF's fundamental (tone_harmonics' units: i k v times the head's flux per
    unit gap, times the repro gap), from the read window's particles."""
    lam = mach.speed_m_s / f_sig
    k = 2 * math.pi / lam
    a0 = num.guard_waves * lam
    sel = (strip.x >= a0) & (strip.x < a0 + num.read_waves * lam)
    ph = np.exp(-1j * k * strip.x[sel])
    yy = mach.spacing_m + strip.depth[sel]
    ks = np.array([k])
    wx = np.array([head_hx_spectrum(mach.rep, ks, y)[0] for y in yy]) / mach.rep.gap_m
    wy = np.array([head_hy_spectrum(mach.rep, ks, y)[0] for y in yy]) / mach.rep.gap_m
    vol = num.read_waves * lam * mach.coating_m * num.width_m
    mu = strip.v[sel] / vol  # each particle's share of the window's magnetization
    ax = 2 * np.sum(mu * m[sel, 0] * ph * wx)
    ay = 2 * np.sum(mu * m[sel, 1] * ph * wy)
    return complex(1j * k * mach.speed_m_s * (ax - ay) * mach.rep.gap_m)


def tone(spec, sigma_int, mach, num, f_sig, a_sig, bias, seed=1, threads=6):
    """A tone's fundamental, antithetic (+-signal on the same particles)."""
    lam = mach.speed_m_s / f_sig
    strip = place(spec, sigma_int, (2 * num.guard_waves + num.read_waves) * lam, mach, num, seed)
    out = []
    for sg in (1.0, -1.0):
        _, m, info = record(strip, spec, mach, num, f_sig, sg * a_sig, bias, threads, seed)
        out.append(readback(strip, m, mach, num, f_sig))
    return 0.5 * (out[0] - out[1]), len(strip.x), info

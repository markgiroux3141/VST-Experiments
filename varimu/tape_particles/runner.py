"""Running `crates/tapeparticles`' binary `tpsim` on scenarios written from Python.

The binary is built by `cargo build --release -p tapeparticles` (target/release/tpsim);
`tpsim()` builds it on first use if it is missing. Scenarios are directories of raw
little-endian f64 arrays plus meta.json (crates/tapeparticles/src/io.rs).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT
from varimu.tape_particles import bench as bn

EXE = REPO_ROOT / "target" / "release" / ("tpsim.exe" if os.name == "nt" else "tpsim")


def tpsim() -> Path:
    if not EXE.exists():
        env = dict(os.environ, CARGO_BUILD_JOBS=os.environ.get("CARGO_BUILD_JOBS", "4"))
        subprocess.run(
            ["cargo", "build", "--release", "-p", "tapeparticles"], cwd=REPO_ROOT, check=True, env=env
        )
    return EXE


def write(d: Path, meta: dict, arrays: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta))
    for k, v in arrays.items():
        np.ascontiguousarray(np.asarray(v, "<f8")).tofile(d / f"{k}.f64")


def read(d: Path, name: str) -> np.ndarray:
    return np.fromfile(d / f"{name}.f64", dtype="<f8")


def bench_run(
    box: bn.Box,
    spec: bn.BenchSpec,
    h_app: np.ndarray,
    dt_s: float,
    seed: int = 1,
    gpu: bool = True,
    trace: bool = False,
    threads: int = 6,
    grid: int = 32,
    iters: int = 10,
    keep: Path | None = None,
    field_only: bool = False,
):
    """h_app: steps x reps x 3 (A/m). Returns (final M per replica reps x 3, trace steps x
    reps x 3 or None, info), M = sum V m / sum V; info["hint"]: the GPU's last interaction
    field (reps x N x 3), or field_only: the CPU's field of the erased state (1 x N x 3)."""
    h_app = np.asarray(h_app, float)
    if h_app.ndim == 2:
        h_app = h_app[:, None, :]
    steps, reps, _ = h_app.shape
    d = Path(tempfile.mkdtemp(prefix="tp_bench_")) if keep is None else keep
    meta = {
        "n_particles": len(box),
        "steps": steps,
        "reps": reps,
        "side_m": box.side_m,
        "ms_p": spec.ms_p_a_m,
        "soften_m": spec.soften_m,
        "target_points": spec.target_points,
        "sample_demag": list(spec.sample_demag),
        "interactions": spec.interactions,
        "interaction_scale": spec.interaction_scale,
        "f0": spec.f0_hz,
        "dt": dt_s,
        "grid": grid,
        "iters": iters,
        "seed": seed,
    }
    write(
        d,
        meta,
        {
            "r": box.r,
            "n": box.n,
            "hk": box.hk,
            "e0_kt": box.e0_kt,
            "l": box.l,
            "v": box.v,
            "h_app": h_app,
            "p0": bn.erased_state(len(box), seed),
        },
    )
    cmd = [str(tpsim()), "field" if field_only else "bench", str(d), "--threads", str(threads)]
    if gpu:
        cmd.append("--gpu")
    if trace:
        cmd.append("--trace")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"tpsim failed: {r.stderr}")
    info = json.loads((d / "out.json").read_text())
    if (d / "out_hint.f64").exists():
        info["hint"] = read(d, "out_hint").reshape(-1, len(box), 3)
    if field_only:
        fin, tr = None, None
    else:
        fin = read(d, "out_m").reshape(reps, 3)
        tr = read(d, "out_trace").reshape(steps, reps, 3) if trace else None
    if keep is None:
        shutil.rmtree(d, ignore_errors=True)
    return fin, tr, info

"""Cached, parallel renders: (circuit parameters, input audio) -> output audio + internal signals.

A render is keyed by a hash of everything that determines its result: the
netlist text and the files it reads, the input samples, the transient
settings, and the varimu source code. A finished render lives in
cache/renders/<key>/:

    out.wav        output, mono float32, in dBFS-scaled units (volts / full scale)
    vectors.npz    every saved vector in circuit volts (CV, B+, grids, ...)
    meta.json      parameters, settings, timing, cache key components

Every render, cached or not, appends a line to cache/renders/timing.csv
(wall-clock seconds per second of audio).

Device tables are generated once per tube model under cache/tables/ (see
varimu.devices.table.cached_table) and hard-linked into each job directory.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import os
import shutil
import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

import varimu
from varimu.circuit import netlist as nl
from varimu.config import REPO_ROOT, load_sim_settings
from varimu.sim.io import TransientSettings, run_transient, write_audio

CACHE_DIR = REPO_ROOT / "cache"
RENDER_DIR = CACHE_DIR / "renders"
JOB_DIR = CACHE_DIR / "jobs"

_timing_lock = threading.Lock()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# The code that can change a render's result. Edits elsewhere (the listen app,
# measurements, the CLI) must not invalidate the cache.
RESULT_CODE = ("sim/*.py", "circuit/*.py", "devices/*.py", "config.py")


def code_version() -> str:
    """varimu version plus a hash of the sources in RESULT_CODE."""
    h = hashlib.sha256()
    pkg = Path(varimu.__file__).parent
    for path in sorted(p for pattern in RESULT_CODE for p in pkg.glob(pattern)):
        h.update(path.relative_to(pkg).as_posix().encode())
        h.update(path.read_bytes())
    return f"{varimu.__version__}+{h.hexdigest()[:12]}"


def default_jobs() -> int:
    """sim_settings runner.max_parallel_jobs, or cpu_count - 2 (keeps the desktop responsive)."""
    n = load_sim_settings().data.get("runner", {}).get("max_parallel_jobs")
    return int(n) if n else max(1, (os.cpu_count() or 2) - 2)


@dataclass
class Render:
    key: str
    path: Path
    output: np.ndarray  # dBFS-scaled (1.0 = full scale)
    vectors: dict[str, np.ndarray]  # circuit volts
    meta: dict[str, Any]
    cached: bool

    @property
    def sample_rate(self) -> int:
        return int(self.meta["sample_rate"])


@dataclass
class RenderJob:
    samples: np.ndarray  # input, dBFS-scaled, at settings.sample_rate
    overrides: dict[str, Any] = field(default_factory=dict)
    label: str = ""  # free text for logs (e.g. clip name)


def _key(circuit: nl.Circuit, samples: np.ndarray, s: TransientSettings) -> tuple[str, dict]:
    parts = {
        "netlist": _sha(circuit.text.encode()),
        "files": {k: Path(v).name for k, v in sorted(circuit.files.items())},
        "input": _sha(np.ascontiguousarray(samples, "<f8").tobytes()),
        "settings": s.as_dict(),
        "save": list(circuit.save),
        "code": code_version(),
    }
    return _sha(json.dumps(parts, sort_keys=True).encode()), parts


def _log_timing(meta: dict[str, Any]) -> None:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    path = RENDER_DIR / "timing.csv"
    row = {
        "when": _dt.datetime.now().isoformat(timespec="seconds"),
        "key": meta["key"][:12],
        "label": meta.get("label", ""),
        "cached": meta["cached"],
        "audio_s": round(meta["duration_s"], 3),
        "wall_s": round(meta["wall_s"], 2),
        "wall_per_audio_s": round(meta["realtime_factor"], 2),
        "oversample": meta["settings"]["oversample"],
        "method": meta["settings"]["method"],
        "reltol": meta["settings"]["reltol"],
    }
    with _timing_lock:
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)


def load_render(path: Path) -> Render:
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    with np.load(path / "vectors.npz") as z:
        vectors = {k: z[k].astype(float) for k in z.files}
    out = vectors["v(out)"] / meta["settings"]["full_scale_volts_peak"]
    return Render(meta["key"], path, out, vectors, meta, cached=True)


def render(
    job: RenderJob,
    *,
    settings: TransientSettings | None = None,
    progress: Callable[[float], None] | None = None,
    use_cache: bool = True,
) -> Render:
    """Run (or fetch from cache) one render."""
    s = settings or TransientSettings.from_sim_settings()
    circuit = nl.build(job.overrides)
    samples = np.asarray(job.samples, float)
    key, parts = _key(circuit, samples, s)
    path = RENDER_DIR / key
    if use_cache and (path / "meta.json").exists():
        r = load_render(path)
        r.meta.update(cached=True, label=job.label or r.meta.get("label", ""))
        _log_timing(r.meta)
        if progress:
            progress(1.0)
        return r

    workdir = JOB_DIR / key
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    try:
        res = run_transient(
            circuit.text,
            samples * s.full_scale_volts_peak,
            input_node=circuit.input_node,
            save=circuit.save,
            settings=s,
            workdir=workdir,
            progress=progress,
            files=circuit.files,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    meta = {
        "key": key,
        "label": job.label,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "sample_rate": s.sample_rate,
        "duration_s": res.duration_s,
        "wall_s": res.wall_s,
        "realtime_factor": res.realtime_factor,
        "sim_points": res.sim_points,
        "params": {k: v for k, v in circuit.params.items()},
        "overrides": dict(job.overrides),
        "settings": s.as_dict(),
        "key_parts": parts,
        "cached": False,
    }
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    out = res.vectors["v(out)"] / s.full_scale_volts_peak
    write_audio(tmp / "out.wav", out, s.sample_rate)
    np.savez_compressed(tmp / "vectors.npz", **{k: v.astype("<f4") for k, v in res.vectors.items()})
    (tmp / "meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    if path.exists():
        shutil.rmtree(path)
    os.replace(tmp, path)
    _log_timing(meta)
    return Render(key, path, out, res.vectors, meta, cached=False)


def render_many(
    jobs: Iterable[RenderJob],
    *,
    settings: TransientSettings | None = None,
    max_jobs: int | None = None,
    progress: Callable[[int, float], None] | None = None,
) -> list[Render]:
    """Run renders in parallel (threads; each waits on its own ngspice process)."""
    jobs = list(jobs)
    n = min(max_jobs or default_jobs(), max(1, len(jobs)))

    def one(i_job):
        i, job = i_job
        cb = (lambda f: progress(i, f)) if progress else None
        return render(job, settings=settings, progress=cb)

    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(one, enumerate(jobs)))


def parse_overrides(pairs: Iterable[str]) -> dict[str, Any]:
    """["threshold=0.7", "time_constant=3"] -> {...}; values parse as int, float or string."""
    out: dict[str, Any] = {}
    for pair in pairs:
        k, sep, v = pair.partition("=")
        if not sep:
            raise ValueError(f"expected key=value, got {pair!r}")
        for cast in (int, float):
            try:
                out[k.strip()] = cast(v)
                break
            except ValueError:
                continue
        else:
            out[k.strip()] = v.strip()
    return out


def summarize(r: Render) -> Mapping[str, Any]:
    return {
        "key": r.key[:12],
        "cached": r.cached,
        "audio_s": round(r.meta["duration_s"], 3),
        "wall_s": round(r.meta["wall_s"], 1),
        "realtime_factor": round(r.meta["realtime_factor"], 1),
        "path": str(r.path),
    }

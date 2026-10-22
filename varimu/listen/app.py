"""Tweak-and-listen page for the 670 slice (offline renders, not live).

    uv sync --extra listen --extra fast
    uv run varimu listen            # http://127.0.0.1:8765

Pick a clip from data/clips/ (or a test signal), move the sliders, press
Render. Renders run in the background through varimu.sim.runner (cached, at
reduced CPU priority) and show progress, on the configured engine
(sim_settings.yaml simulator.engine: circuitsim by default, about 3-5x slower
than real time on program material; ngspice 20-30x). Playback switches between dry, the
current render and the previous render at the same position; all three are
loudness-matched (varimu.listen.matching). Each render also shows its gain
over time and the sidechain control voltage on the 6386 grids.
"""

from __future__ import annotations

import csv
import io
import itertools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from pydantic import BaseModel  # listen extra (comes with fastapi)

from varimu.circuit import netlist as nl
from varimu.config import DATA_DIR, load_genome_bounds, load_sim_settings
from varimu.listen import matching
from varimu.measure import signals
from varimu.sim import runner
from varimu.sim.io import configured_engine, load_audio

CLIP_DIR = DATA_DIR / "clips"
AUDIO_EXT = {".wav", ".flac", ".aif", ".aiff", ".ogg"}
TEST_SIGNALS = ["burst_1000hz_0dbfs", "burst_1000hz_-10dbfs", "steps_1000hz", "smpte_-10dbfs"]

# Sliders beyond the front panel: the physical values the user asked for.
PHYSICAL = [
    ("v6386_a.emission_scale", "6386 bank A emission"),
    ("v6386_b.emission_scale", "6386 bank B emission"),
    ("v6386_a.mu_spread", "6386 bank A mu"),
    ("v6386_b.mu_spread", "6386 bank B mu"),
    ("grid_contact_v", "6386 grid contact potential (both banks)"),
    ("l302_r_ohm", "Bias choke L302 resistance (6386 cathode return)"),
    ("t302_r_half_ohm", "Mains transformer HV winding resistance"),
]
LABELS = {
    "input_atten_db": "Input attenuator (dB)",
    "ac_threshold": "Threshold (AC)",
    "time_constant": "Time constant",
    "dc_threshold": "DC threshold trim",
    "balance": "Balance trim",
    "zero": "Zero trim (standing grid bias)",
}


def control_schema() -> list[dict[str, Any]]:
    """Every slider: key, label, group, min, max, step, default, source."""
    spec = nl.load_spec()
    bounds = load_genome_bounds()
    defaults = spec.defaults()
    out = []
    for k, e in spec.controls.items():
        out.append(
            {
                "key": k,
                "label": LABELS.get(k, k),
                "group": "Front panel and trims",
                "min": e["min"],
                "max": e["max"],
                "step": 1 if k in ("time_constant", "input_atten_db") else 0.01,
                "default": e["value"],
                "source": e["source"],
            }
        )
    links = nl.genome_links(spec)
    for key, label in PHYSICAL:
        if key == "grid_contact_v":
            b = bounds["tubes.v6386_a.grid_contact_v"]
            default = load_device_contact()
        elif key.startswith("v6386_"):
            side, param = key.split(".")
            b = bounds[f"tubes.{side}.{param}"]
            default = defaults[key]
        else:
            b = bounds[links[key]]
            default = defaults[key]
        out.append(
            {
                "key": key,
                "label": label,
                "group": "Physical (genome)",
                "min": b.min,
                "max": b.max,
                "step": (b.max - b.min) / 200,
                "default": default,
                "source": b.source,
            }
        )
    return out


def load_device_contact() -> float:
    from varimu.devices.library import load_device

    return load_device("6386").grid.contact_v


def to_overrides(values: dict[str, float]) -> dict[str, Any]:
    """Slider values -> netlist overrides (expands the shared grid-contact slider)."""
    ov = dict(values)
    if "grid_contact_v" in ov:
        v = ov.pop("grid_contact_v")
        ov["v6386_a.grid_contact_v"] = v
        ov["v6386_b.grid_contact_v"] = v
    if "time_constant" in ov:
        ov["time_constant"] = int(round(ov["time_constant"]))
    return ov


TYPICAL_SPEED = {"circuitsim": 5.0, "ngspice": 30.0}  # x slower than real time (plan, M5)


def last_speed(engine: str) -> float:
    """Wall seconds per audio second of the engine's last uncached render
    (cache/renders/timing.csv), or a typical figure: the page's time estimate."""
    path = runner.RENDER_DIR / "timing.csv"
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = [
                r
                for r in csv.DictReader(f)
                if r.get("engine") == engine and r.get("cached") == "False"
            ]
        return float(rows[-1]["wall_per_audio_s"])
    except (OSError, IndexError, KeyError, ValueError):
        return TYPICAL_SPEED.get(engine, 30.0)


# --- Sources -----------------------------------------------------------------------------


def list_sources() -> list[str]:
    clips = sorted(p.name for p in CLIP_DIR.glob("*") if p.suffix.lower() in AUDIO_EXT)
    return [f"clip:{c}" for c in clips] + [f"signal:{s}" for s in TEST_SIGNALS]


@lru_cache(maxsize=16)
def _load_source(source: str) -> np.ndarray:
    st = load_sim_settings()
    kind, _, name = source.partition(":")
    if kind == "clip":
        path = (CLIP_DIR / name).resolve()
        if path.parent != CLIP_DIR.resolve() or not path.exists():
            raise FileNotFoundError(name)
        return load_audio(path, st.sample_rate)
    if kind == "signal" and name in TEST_SIGNALS:
        spec = next(s for s in signals.default_library() if s.name == name)
        return signals.render(spec, sample_rate=st.sample_rate, seed=st.seed).samples
    raise FileNotFoundError(source)


def excerpt(source: str, start_s: float, seconds: float | None) -> np.ndarray:
    x = _load_source(source)
    fs = load_sim_settings().sample_rate
    a = int(max(0.0, start_s) * fs)
    b = len(x) if not seconds else min(len(x), a + int(seconds * fs))
    return x[a:b]


# --- Jobs --------------------------------------------------------------------------------


@dataclass
class Job:
    id: int
    source: str
    start_s: float
    seconds: float | None
    values: dict[str, float]
    status: str = "queued"  # queued | running | done | failed
    progress: float = 0.0
    error: str = ""
    key: str = ""
    created: float = field(default_factory=time.time)
    finished: float = 0.0
    wall_s: float = 0.0
    realtime_factor: float = 0.0

    def public(self) -> dict[str, Any]:
        return {
            k: getattr(self, k)
            for k in (
                "id", "source", "start_s", "seconds", "values", "status", "progress", "error",
                "key", "wall_s", "realtime_factor",
            )
        }  # fmt: skip


class Jobs:
    def __init__(self, workers: int):
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.jobs: dict[int, Job] = {}
        self.pool = ThreadPoolExecutor(max_workers=workers)

    def submit(self, source: str, start_s: float, seconds: float | None, values: dict) -> Job:
        job = Job(next(self._ids), source, start_s, seconds, values)
        with self._lock:
            self.jobs[job.id] = job
        self.pool.submit(self._run, job)
        return job

    def _run(self, job: Job) -> None:
        job.status = "running"
        try:
            x = excerpt(job.source, job.start_s, job.seconds)

            def cb(f: float) -> None:
                job.progress = f

            r = runner.render(
                runner.RenderJob(x, to_overrides(job.values), label=job.source), progress=cb
            )
            job.key, job.status, job.progress = r.key, "done", 1.0
            job.wall_s, job.realtime_factor = r.meta["wall_s"], r.meta["realtime_factor"]
        except Exception as e:  # shown in the page
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"[-2000:]
        job.finished = time.time()


# --- Audio and analysis --------------------------------------------------------------------


def _wav_bytes(x: np.ndarray, fs: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.asarray(x, "<f4"), fs, format="WAV", subtype="FLOAT")
    return buf.getvalue()


def compare(job_ids: list[int], jobs: Jobs) -> dict[str, Any]:
    """Loudness-matched dry + renders, plus gain and CV traces for each render."""
    fs = load_sim_settings().sample_rate
    chosen = [jobs.jobs[i] for i in job_ids if i in jobs.jobs and jobs.jobs[i].status == "done"]
    if not chosen:
        raise KeyError("no finished renders")
    first = chosen[0]
    dry = excerpt(first.source, first.start_s, first.seconds)
    renders = [runner.load_render(runner.RENDER_DIR / j.key) for j in chosen]
    clips = [dry] + [r.output for r in renders]
    n = min(len(c) for c in clips)
    clips = [c[:n] for c in clips]
    matched, info = matching.match_loudness(clips, fs)
    traces = []
    for j, r in zip(chosen, renders, strict=True):
        dry_j = excerpt(j.source, j.start_s, j.seconds)[:n]
        t, g = matching.gain_trace(dry_j, r.output[:n], fs)
        cv = r.vectors["v(cv)"][:n]
        step = max(1, len(cv) // 800)
        traces.append(
            {
                "job": j.id,
                "t": t.round(4).tolist(),
                "gain_db": [None if not np.isfinite(v) else round(float(v), 2) for v in g],
                "cv_t": (np.arange(0, len(cv), step) / fs).round(4).tolist(),
                "cv_v": cv[::step].round(3).tolist(),
                "median_gain_db": round(float(np.nanmedian(g)), 2)
                if np.any(np.isfinite(g))
                else None,
            }
        )
    return {
        "fs": fs,
        "clips": matched,
        "match": {
            "target_lufs": round(info.target_lufs, 2),
            "measured_lufs": [round(v, 2) if np.isfinite(v) else None for v in info.measured_lufs],
            "gains_db": [round(g, 2) for g in info.gains_db],
        },
        "traces": traces,
    }


class RenderRequest(BaseModel):
    source: str
    start_s: float = 0.0
    seconds: float | None = None
    values: dict[str, float]


# --- App ---------------------------------------------------------------------------------------


def create_app(workers: int | None = None):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, Response

    app = FastAPI(title="varimu listen")
    jobs = Jobs(workers or runner.default_jobs())
    audio_cache: dict[str, bytes] = {}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (Path(__file__).parent / "page.html").read_text(encoding="utf-8")

    @app.get("/api/controls")
    def controls():
        engine = configured_engine()
        return {
            "controls": control_schema(),
            "sources": list_sources(),
            "engine": engine,
            "realtime_factor": last_speed(engine),
        }

    @app.post("/api/render")
    def submit(req: RenderRequest):
        if req.source not in list_sources():
            raise HTTPException(404, f"unknown source {req.source}")
        try:
            nl.resolve(to_overrides(req.values))
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        return jobs.submit(req.source, req.start_s, req.seconds, req.values).public()

    @app.get("/api/jobs")
    def list_jobs():
        return [j.public() for j in sorted(jobs.jobs.values(), key=lambda j: -j.id)]

    @app.get("/api/source_info")
    def source_info(source: str):
        try:
            x = _load_source(source)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        return {"duration_s": len(x) / load_sim_settings().sample_rate}

    @app.get("/api/compare")
    def api_compare(ids: str):
        try:
            res = compare([int(i) for i in ids.split(",") if i], jobs)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        names = ["dry"] + [f"job{i}" for i in ids.split(",") if i]
        stamp = f"{ids}-{time.time_ns()}"
        urls = []
        for name, clip in zip(names, res.pop("clips"), strict=False):
            k = f"{stamp}-{name}"
            audio_cache[k] = _wav_bytes(clip, res["fs"])
            urls.append(f"/api/audio/{k}.wav")
        while len(audio_cache) > 30:
            audio_cache.pop(next(iter(audio_cache)))
        res["audio"] = dict(zip(names, urls, strict=False))
        return res

    @app.get("/api/audio/{key}.wav")
    def audio(key: str):
        if key not in audio_cache:
            raise HTTPException(404)
        return Response(audio_cache[key], media_type="audio/wav")

    return app


def serve(host: str = "127.0.0.1", port: int = 8765, workers: int | None = None) -> None:
    import uvicorn

    uvicorn.run(create_app(workers), host=host, port=port, log_level="warning")

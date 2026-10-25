"""Tweak-and-listen page for the 670 slice (offline renders, not live), and blind A/B.

    uv sync --extra listen --extra fast
    uv run varimu listen            # http://127.0.0.1:8765  (blind A/B: /ab)

Blind A/B (Phase 5, /ab): sessions over the stimuli `varimu ab-prepare` matched
(varimu.listen.prepare); see the AB class below and varimu.listen.session. The
same page has the listening aids (no new renders): difference listening (the
residual A - B turned up, A + k (B - A) exaggerated; varimu.listen.difference)
and ABX discrimination with an exaggeration staircase (varimu.listen.abx), whose
judgments are stored apart from the preference data.

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


class SessionRequest(BaseModel):
    listener: str = ""
    seed: int | None = None


class AnswerRequest(BaseModel):
    trial_id: int
    choice: str  # "A" | "B" | "none"
    response_ms: float
    plays_a: int = 0
    plays_b: int = 0


class AbxSessionRequest(BaseModel):
    listener: str = ""
    seed: int | None = None
    pairs: list[tuple[int, int]] | None = None  # stimulus ids; None: every pair
    mode: str = "staircase"  # or "fixed"
    k: float = 1.0  # mode "fixed"
    trials_per_pair: int = 12
    part: str = "all"  # what is exaggerated: "all", "character" or "tone" (difference.PARTS)


class AbxAnswerRequest(BaseModel):
    trial_id: int
    answer: str  # what X is: "A" | "B"
    response_ms: float
    plays: dict[str, int] = {}


# --- Blind A/B (Phase 5) ---------------------------------------------------------------------


class AB:
    """The blind A/B side of the app: sessions over the prepared stimuli
    (varimu.listen.prepare), judgments into SQLite (varimu.listen.store). The page
    sees trial ids and audio only, never which candidate is which."""

    def __init__(
        self, db=None, version: str | None = None, render_audio=None, clips=None, candidates=None
    ):
        from varimu.listen import prepare, store

        self.db = db or store.connect()
        self.clips = tuple(clips) if clips else None  # sessions play these (None: all)
        self.candidates = tuple(candidates) if candidates else None  # candidate ids, ditto
        self.version = version or prepare.code_version()
        self.render_audio = render_audio or prepare._render_audio
        self.lock = threading.Lock()
        self.audio: dict[int, tuple[bytes, bytes]] = {}
        self.abx_audio: dict[int, dict[str, bytes]] = {}
        self.explore_audio: dict[str, bytes] = {}
        self._arrays: dict[str, np.ndarray] = {}
        self._levels: dict[tuple[int, int], dict[str, float]] = {}

    def _stimuli(self):
        from varimu.listen import store

        return store.stimuli(self.db, self.version, clips=self.clips,
                             candidate_ids=self.candidates)  # fmt: skip

    # --- The listening aids: shared helpers ---

    def _array(self, key: str) -> np.ndarray:
        """A render's output, kept for a while (loading one reads every vector)."""
        if key not in self._arrays:
            while len(self._arrays) >= 24:
                self._arrays.pop(next(iter(self._arrays)))
            self._arrays[key] = np.asarray(self.render_audio(key), float)
        return self._arrays[key]

    def _stim(self, sid: int):
        r = self.db.execute(
            "SELECT s.*, c.name AS candidate FROM stimuli s JOIN candidates c "
            "ON c.id = s.candidate_id WHERE s.id = ? AND s.code_version = ?",
            (sid, self.version),
        ).fetchone()
        if r is None:
            raise KeyError(sid)
        return r

    def _audio4(self, base, other) -> tuple[np.ndarray, ...]:
        """(base, other, base's reference, other's reference) outputs."""
        return tuple(self._array(s[k]) for k in ("render_key", "reference_key")
                     for s in (base, other))  # fmt: skip

    def _pair_levels(self, a, b) -> dict[str, float]:
        """The pair's difference per part, dB re the lower stimulus id (difference.levels)."""
        from varimu.listen import difference

        key = (min(a["id"], b["id"]), max(a["id"], b["id"]))
        if key not in self._levels:
            sa, sb = self._stim(key[0]), self._stim(key[1])
            self._levels[key] = difference.levels(
                self._array(sa["render_key"]), self._array(sb["render_key"])
            )
        return self._levels[key]

    def _residual_db(self, a, b, part: str = "all") -> float:
        return self._pair_levels(a, b)[part]

    def pairs(self) -> list[dict[str, Any]]:
        """Every prepared pair (per condition) with its residual level: what the aids
        work on. Names are included: the page shows them only on request."""
        from varimu.listen import session

        with self.lock:
            out = []
            for a, b in session.pairs(self._stimuli()):
                out.append({
                    "a": a["id"], "b": b["id"], "names": [a["candidate"], b["candidate"]],
                    "clip": a["clip"], "gr_target_db": a["gr_target_db"],
                    "time_constant": a["time_constant"],
                    "residual_db": self._residual_db(a, b),
                    "levels_db": self._pair_levels(a, b),
                })  # fmt: skip
            return out

    def explore(self, a: int, b: int, part: str = "all") -> dict[str, Any]:
        """Difference listening on a pair: A, B, the part's difference turned up and
        A + k d for k = 2, 4, 8 (d: the pair's `part`, difference.PARTS), each loudness
        matched, with its GR, envelope and artifacts."""
        from varimu.listen import difference

        with self.lock:
            sa, sb = self._stim(a), self._stim(b)
            fs = load_sim_settings().sample_rate
            ya, yb, ra, rb = self._audio4(sa, sb)
            res = difference.streams(ya, yb, ra, rb, fs, part=part)
            self.explore_audio.clear()
            stamp = f"{a}-{b}-{time.time_ns()}"
            for i, st in enumerate([*res["streams"], res["residual"]]):
                token = f"{stamp}-{i}"
                self.explore_audio[token] = _wav_bytes(st.pop("audio"), fs)
                st["audio"] = f"/api/ab/explore/audio/{token}.wav"
            res["names"] = [sa["candidate"], sb["candidate"]]
            return res

    # --- ABX discrimination (varimu.listen.abx) ---

    def abx_start(self, req: AbxSessionRequest) -> dict[str, Any]:
        from varimu.listen import abx

        with self.lock:
            stims = self._stimuli()
            if len(stims) < 2:
                raise LookupError(self.status()["hint"])
            sid = abx.start(
                self.db, stims, residual_db=lambda x, y: self._residual_db(x, y, req.part),
                code_version=self.version, listener=req.listener, seed=req.seed,
                chosen=req.pairs, mode=req.mode, k_fixed=req.k,
                trials_per_pair=req.trials_per_pair, part=req.part,
            )  # fmt: skip
            return self._abx_progress(sid)

    def _abx_progress(self, sid: str) -> dict[str, Any]:
        from varimu.listen import abx

        s = abx.summary(self.db, sid)
        return {k: s[k] for k in ("session", "mode", "answered", "planned", "share_x_is_a")}

    def abx_next(self, sid: str) -> dict[str, Any]:
        from varimu.listen import abx, difference, store

        with self.lock:
            prog = self._abx_progress(sid)
            t = abx.next_trial(self.db, sid)
            if t is None:
                s = abx.summary(self.db, sid)
                store.end_abx_session(self.db, sid, s["share_x_is_a"])
                return {"done": True, "summary": s}
            if t["id"] not in self.abx_audio:
                p = self.db.execute(
                    "SELECT * FROM abx_pairs WHERE id = ?", (t["pair_id"],)
                ).fetchone()
                fs = load_sim_settings().sample_rate
                ya, yb, ra, rb = self._audio4(self._stim(p["base"]), self._stim(p["other"]))
                part = abx.session_part(self.db, sid)
                v = difference.exaggerated_pair(ya, yb, ra, rb, t["k"], fs, part=part)
                order = (0, 1) if t["a_is_base"] else (1, 0)  # which is labelled A, B
                wav = {s: _wav_bytes(v["audio"][i], fs) for s, i in zip("AB", order, strict=True)}
                # X is the same file as the side it is (a WAV's PEAK chunk carries the time
                # it was written: encoding it again would differ in that byte).
                wav["X"] = wav[t["x_is"]]
                store.abx_presented(self.db, t["id"], [v["gains_db"][i] for i in order],
                                    [v["lufs_after"][i] for i in order],
                                    [v["gr_db"][i] for i in order], v["artifacts"])  # fmt: skip
                self.abx_audio = {t["id"]: wav}
            return {
                "done": False,
                "trial_id": t["id"],
                "audio": {s: f"/api/ab/abx/audio/{t['id']}/{s}.wav" for s in "ABX"},
                "progress": prog,
            }

    def abx_answer(self, req: AbxAnswerRequest) -> dict[str, Any]:
        from varimu.listen import abx

        with self.lock:
            hit = abx.answer(self.db, req.trial_id, req.answer, req.response_ms, req.plays)
            t = self.db.execute("SELECT * FROM abx_trials WHERE id = ?", (req.trial_id,)).fetchone()
            return {"correct": hit, "k": t["k"], "anchor": bool(t["anchor"]),
                    "progress": self._abx_progress(t["session_id"])}  # fmt: skip

    def abx_summary(self, sid: str) -> dict[str, Any]:
        from varimu.listen import abx

        with self.lock:
            return abx.summary(self.db, sid)

    def status(self) -> dict[str, Any]:

        rows = self._stimuli()
        conds = {(r["clip"], r["start_s"], r["seconds"], r["time_constant"], r["gr_target_db"])
                 for r in rows}  # fmt: skip
        return {
            "stimuli": len(rows),
            "conditions": len(conds),
            "candidates": len({r["candidate_id"] for r in rows}),
            "ready": len(rows) >= 2,
            "hint": ""
            if len(rows) >= 2
            else "run `varimu ab-prepare` first (program clips "
            "in data/clips, candidates in config/listening.yaml)",
        }

    def start(self, listener: str, seed: int | None) -> dict[str, Any]:
        from varimu.listen import session

        with self.lock:
            stims = self._stimuli()
            if len(stims) < 2:
                raise LookupError(self.status()["hint"])
            sid = session.start(self.db, stims, listener=listener, code_version=self.version,
                                seed=seed)  # fmt: skip
            return session.progress(self.db, sid)

    def next(self, sid: str) -> dict[str, Any]:
        from varimu.listen import session, stimuli, store

        with self.lock:
            prog = session.progress(self.db, sid)
            t = session.next_trial(self.db, sid)
            if t is None:
                store.end_session(self.db, sid)
                return {"done": True, "progress": session.progress(self.db, sid)}
            if t["id"] not in self.audio:
                keys = {
                    r["id"]: r["render_key"]
                    for r in self.db.execute(
                        "SELECT id, render_key FROM stimuli WHERE id IN (?, ?)",
                        (t["stimulus_a"], t["stimulus_b"]),
                    )
                }
                fs = load_sim_settings().sample_rate
                ya, yb = (self.render_audio(keys[t[k]]) for k in ("stimulus_a", "stimulus_b"))
                n = min(len(ya), len(yb))
                v = stimuli.verify_pair(ya[:n], yb[:n], fs)
                store.presented(self.db, t["id"], v["gains_db"], v["lufs_after"])
                self.audio = {t["id"]: tuple(_wav_bytes(y, fs) for y in v["audio"])}
            seed = self.db.execute("SELECT seed FROM sessions WHERE id = ?", (sid,)).fetchone()
            first = "AB"[int(np.random.default_rng([seed["seed"], 3, t["id"]]).integers(2))]
            return {
                "done": False,
                "trial_id": t["id"],
                "first": first,  # the side that sounds first (seeded, like the rest)
                "audio": {s: f"/api/ab/audio/{t['id']}/{s}.wav" for s in ("A", "B")},
                "progress": prog,
            }

    def answer(self, req: AnswerRequest) -> dict[str, Any]:
        from varimu.listen import session, store

        if req.choice not in ("A", "B", "none"):
            raise ValueError(f"choice must be A, B or none, not {req.choice!r}")
        with self.lock:
            store.answer(self.db, req.trial_id, req.choice, req.response_ms, req.plays_a,
                         req.plays_b)  # fmt: skip
            sid = self.db.execute(
                "SELECT session_id FROM trials WHERE id = ?", (req.trial_id,)
            ).fetchone()["session_id"]
            return session.progress(self.db, sid)


# --- App ---------------------------------------------------------------------------------------


def create_app(workers: int | None = None, ab: AB | None = None):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, Response

    app = FastAPI(title="varimu listen")
    jobs = Jobs(workers or runner.default_jobs())
    audio_cache: dict[str, bytes] = {}
    ab_box: list[AB] = [ab] if ab else []

    def get_ab() -> AB:
        if not ab_box:
            from varimu.listen.candidates import load_pool

            pool = load_pool()
            ids = [pool.candidates[n].id for n in pool.session_candidates or pool.candidates]
            ab_box.append(AB(clips=pool.pool_clips, candidates=ids))
        return ab_box[0]

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (Path(__file__).parent / "page.html").read_text(encoding="utf-8")

    @app.get("/ab", response_class=HTMLResponse)
    def ab_page():
        return (Path(__file__).parent / "ab.html").read_text(encoding="utf-8")

    @app.get("/api/ab/status")
    def ab_status():
        return get_ab().status()

    @app.post("/api/ab/session")
    def ab_session(req: SessionRequest):
        try:
            return get_ab().start(req.listener, req.seed)
        except LookupError as e:
            raise HTTPException(409, str(e)) from e

    @app.get("/api/ab/next")
    def ab_next(session: str):
        try:
            return get_ab().next(session)
        except KeyError as e:
            raise HTTPException(404, f"unknown session {e}") from e

    @app.get("/api/ab/audio/{trial_id}/{side}.wav")
    def ab_audio(trial_id: int, side: str):
        clips = get_ab().audio.get(trial_id)
        if clips is None or side not in ("A", "B"):
            raise HTTPException(404)
        return Response(clips[0 if side == "A" else 1], media_type="audio/wav")

    @app.post("/api/ab/answer")
    def ab_answer(req: AnswerRequest):
        try:
            return get_ab().answer(req)
        except KeyError as e:
            raise HTTPException(404, f"unknown trial {e}") from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/ab/pairs")
    def ab_pairs():
        return get_ab().pairs()

    @app.get("/api/ab/explore")
    def ab_explore(a: int, b: int, part: str = "all"):
        try:
            return get_ab().explore(a, b, part)
        except KeyError as e:
            raise HTTPException(404, f"unknown stimulus {e}") from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/ab/explore/audio/{token}.wav")
    def ab_explore_audio(token: str):
        clip = get_ab().explore_audio.get(token)
        if clip is None:
            raise HTTPException(404)
        return Response(clip, media_type="audio/wav")

    @app.post("/api/ab/abx/session")
    def abx_session(req: AbxSessionRequest):
        try:
            return get_ab().abx_start(req)
        except LookupError as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/ab/abx/next")
    def abx_next(session: str):
        try:
            return get_ab().abx_next(session)
        except KeyError as e:
            raise HTTPException(404, f"unknown session {e}") from e

    @app.get("/api/ab/abx/audio/{trial_id}/{side}.wav")
    def abx_audio(trial_id: int, side: str):
        clips = get_ab().abx_audio.get(trial_id)
        if clips is None or side not in clips:
            raise HTTPException(404)
        return Response(clips[side], media_type="audio/wav")

    @app.post("/api/ab/abx/answer")
    def abx_answer(req: AbxAnswerRequest):
        try:
            return get_ab().abx_answer(req)
        except KeyError as e:
            raise HTTPException(404, f"unknown trial {e}") from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/ab/abx/summary")
    def abx_summary(session: str):
        try:
            return get_ab().abx_summary(session)
        except KeyError as e:
            raise HTTPException(404, f"unknown session {e}") from e

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

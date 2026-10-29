"""The schematic editor's page and API in `varimu listen` (device builder B4a).

    /editor                      the page (editor.html, ES modules from editor/)
    GET  /api/editor/symbols     the symbol table (varimu.editor.symbols)
    GET  /api/editor/library     what a part can be swapped for: device files by kind,
                                 core materials
    GET  /api/editor/circuits    circuit files, drawn (a <name>.drawing.json) or hand-written
    GET  /api/editor/open        a circuit's drawing (generated for a hand-written one) and
                                 its connectivity and parameters
    POST /api/editor/analyze     a drawing's connectivity, compile errors, parameters
    POST /api/editor/check       the pre-flight checks at every switch combination, as
                                 markers on the drawing
    GET  /api/editor/sources     clips and test signals to listen through
    POST /api/editor/render      render a drawing (compiled to cache/editor/) on an excerpt:
                                 a job of the listen app's queue (GET /api/jobs?ids=...)
    GET  /api/editor/compare     dry and renders, loudness-matched, with envelopes
    POST /api/editor/save        save a drawing as a new circuit (never over a hand-written
                                 one)

The page holds the drawing; the server is stateless apart from the render queue.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from varimu.config import CONFIG_DIR, load_genome_bounds, load_sim_settings
from varimu.editor.compile import (
    cached_circuit,
    check_drawing,
    compile_drawing,
    save_circuit,
)
from varimu.editor.connect import Connectivity
from varimu.editor.drawing import Drawing, drawing_path, load_drawing
from varimu.editor.layout import drawing_of_circuit
from varimu.editor.symbols import library_json

HERE = Path(__file__).parent
CIRCUITS = CONFIG_DIR / "circuits"
NAME = re.compile(r"[a-z][a-z0-9_]{1,47}")
ENVELOPE_BINS = 900
OUTPUT_NODE = "out"  # the node every render saves as its output (varimu.sim.runner)


def list_circuits() -> list[dict[str, Any]]:
    import yaml

    out = []
    for p in sorted(CIRCUITS.glob("*.yaml")):
        with open(p, encoding="utf-8") as f:
            title = (yaml.safe_load(f) or {}).get("title", p.stem)
        drawn = drawing_path(p.stem).exists()
        out.append({"name": p.stem, "title": title, "kind": "drawn" if drawn else "hand-written"})
    return out


def open_circuit(name: str) -> tuple[Drawing, str]:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        raise KeyError(name)
    if drawing_path(name).exists():
        return load_drawing(drawing_path(name)), "drawn"
    path = CIRCUITS / f"{name}.yaml"
    if not path.exists():
        raise KeyError(name)
    return drawing_of_circuit(path), "hand-written"


def part_library() -> dict[str, Any]:
    """Device files (every saved component version, by its `NAME@N` reference) by kind
    and core materials, with their sources: what the inspector offers when a part's type
    is swapped."""
    import yaml

    from varimu.devices import versions

    devices = []
    for folder in versions.names():
        for n in versions.versions(folder):
            d = yaml.safe_load(versions.path(f"{folder}@{n}").read_text(encoding="utf-8")) or {}
            devices.append({"name": f"{d.get('name', folder)}@{n}", "kind": d.get("kind"),
                            "source": d.get("source", "")})  # fmt: skip
    with open(CONFIG_DIR / "magnetics.yaml", encoding="utf-8") as f:
        mats = (yaml.safe_load(f) or {}).get("materials") or {}
    materials = [{"name": k, "source": v.get("source", "")} for k, v in mats.items()]
    return {"devices": devices, "materials": materials}


def _nets_json(conn: Connectivity) -> list[dict[str, Any]]:
    return [
        {"name": n.name, "node": n.node, "pins": [[p.ref, p.unit, p.number] for p in n.pins],
         "wires": n.wires, "labels": n.labels, "grounds": n.grounds}
        for n in conn.nets
    ]  # fmt: skip


def _params(data: dict[str, Any] | None, d: Drawing) -> dict[str, Any]:
    """The circuit's parameters by key (controls, values, device parameters) with their
    genome bounds, and each tolerance class's band, for the inspector."""
    src = data or d.circuit
    bounds = load_genome_bounds()
    params: dict[str, Any] = {}
    for kind in ("controls", "values", "device_params"):
        for k, e in (src.get(kind) or {}).items():
            entry = {"kind": kind, **e}
            g = e.get("genome")
            if g and g in bounds:
                b = bounds[g]
                choices = list(b.choices) if isinstance(b.choices, tuple) else b.choices
                entry["bounds"] = {"min": b.min, "max": b.max, "source": b.source,
                                   "choices": choices}  # fmt: skip
            params[k] = entry
    for k, e in ((src.get("derived") or {}).get("values") or {}).items():
        params[k] = {"kind": "derived", **e}
    bands = {}
    tol = src.get("tolerance") or {}
    for cls, band in (tol.get("bands") or {}).items():
        keys = band if isinstance(band, list) else [band]
        vals = [params.get(k, {}).get("value") for k in keys]
        bands[cls] = {"keys": keys, "pct": vals}
    return {"params": params, "bands": bands}


def analyze(d: Drawing) -> dict[str, Any]:
    c = compile_drawing(d)
    return {
        "ok": c.ok,
        "errors": c.errors,
        "problems": c.problems,
        "warnings": c.warnings,
        "nets": _nets_json(c.conn),
        "junctions": c.conn.junctions,
        "loose": c.conn.loose,
        # Renders read node `out` (varimu.sim.runner): without it the drawing can't be heard.
        "has_output": any(n.node == OUTPUT_NODE for n in c.conn.nets),
        **_params(c.data, d),
    }


def _envelope(x: np.ndarray, bins: int = ENVELOPE_BINS) -> list[list[float]]:
    """Min and max per bin, for the waveform strip."""
    n = len(x) // bins * bins
    if n == 0:
        return []
    b = x[:n].reshape(bins, -1)
    return np.round(np.stack([b.min(axis=1), b.max(axis=1)], axis=1), 4).tolist()


def register(app, jobs) -> None:
    from fastapi import Body, HTTPException
    from fastapi.responses import HTMLResponse, Response

    from varimu.listen import matching
    from varimu.listen.app import _wav_bytes, excerpt, last_speed, list_sources
    from varimu.sim import runner
    from varimu.sim.io import configured_engine

    audio_cache: dict[str, bytes] = {}

    @app.get("/editor", response_class=HTMLResponse)
    def editor_page():
        return (HERE / "editor.html").read_text(encoding="utf-8")

    @app.get("/editor/{module}.js")
    def editor_module(module: str):
        path = HERE / "editor" / f"{module}.js"
        if not re.fullmatch(r"[a-z_]+", module) or not path.exists():
            raise HTTPException(404)
        return Response(path.read_text(encoding="utf-8"), media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})  # fmt: skip

    @app.get("/api/editor/symbols")
    def editor_symbols():
        return library_json()

    @app.get("/api/editor/library")
    def editor_library():
        return part_library()

    @app.get("/api/editor/circuits")
    def editor_circuits():
        return list_circuits()

    @app.get("/api/editor/open")
    def editor_open(circuit: str):
        try:
            d, kind = open_circuit(circuit)
        except KeyError as e:
            raise HTTPException(404, f"no circuit {circuit}") from e
        return {"name": circuit, "kind": kind, "drawing": d.to_json(), **analyze(d)}

    def _drawing(body: dict) -> Drawing:
        try:
            return Drawing.from_json(body["drawing"])
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, f"not a drawing: {e}") from e

    @app.post("/api/editor/analyze")
    def editor_analyze(body: dict = Body(...)):  # noqa: B008
        return analyze(_drawing(body))

    @app.post("/api/editor/check")
    def editor_check(body: dict = Body(...)):  # noqa: B008
        _, found = check_drawing(_drawing(body))
        return {"markers": [m.to_json() for m in found]}

    @app.get("/api/editor/sources")
    def editor_sources():
        engine = configured_engine()
        return {"sources": list_sources(), "engine": engine, "realtime_factor": last_speed(engine)}

    @app.post("/api/editor/render")
    def editor_render(body: dict = Body(...)):  # noqa: B008
        d = _drawing(body)
        source = body.get("source", "")
        if source not in list_sources():
            raise HTTPException(404, f"unknown source {source}")
        c = compile_drawing(d)
        if not c.ok:
            raise HTTPException(409, "the drawing doesn't compile: " + "; ".join(c.errors))
        if not any(n.node == OUTPUT_NODE for n in c.conn.nets):
            msg = f"no node named {OUTPUT_NODE!r}: label the output {OUTPUT_NODE} to hear it"
            raise HTTPException(409, msg)
        path = cached_circuit(c, str(body.get("origin") or "a drawing"))
        start = float(body.get("start_s") or 0.0)
        seconds = body.get("seconds")
        quality = body.get("quality") or None
        try:
            job = jobs.submit(source, start, float(seconds) if seconds else None, {}, str(path),
                              quality=quality)  # fmt: skip
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {**job.public(), "circuit_file": path.name}

    @app.get("/api/editor/compare")
    def editor_compare(ids: str):
        """Dry and the renders `ids` (in that order), loudness-matched (CLAUDE.md:
        loudness lies), cut to the shortest, with their waveform envelopes."""
        fs = load_sim_settings().sample_rate
        chosen = []
        for i in [int(x) for x in ids.split(",") if x.strip().isdigit()]:
            j = jobs.jobs.get(i)
            if j is None or j.status != "done":
                raise HTTPException(404, f"render {i} isn't done")
            chosen.append(j)
        if not chosen:
            raise HTTPException(400, "no renders")
        first = chosen[0]
        dry = excerpt(first.source, first.start_s, first.seconds)
        outs = [runner.load_render(runner.RENDER_DIR / j.key).output for j in chosen]
        n = min(len(x) for x in [dry, *outs])
        matched, info = matching.match_loudness([x[:n] for x in [dry, *outs]], fs)
        stamp = f"{ids}-{time.time_ns()}"
        urls, envelopes = [], []
        for k, clip in enumerate(matched):
            key = f"{stamp}-{k}"
            audio_cache[key] = _wav_bytes(clip, fs)
            urls.append(f"/api/editor/audio/{key}.wav")
            envelopes.append(_envelope(np.asarray(clip)))
        while len(audio_cache) > 24:
            audio_cache.pop(next(iter(audio_cache)))
        return {
            "fs": fs,
            "seconds": n / fs,
            "audio": urls,  # dry, then the renders in the order asked
            "envelopes": envelopes,
            "match": {
                "target_lufs": round(info.target_lufs, 2),
                "measured_lufs": [
                    round(v, 2) if np.isfinite(v) else None for v in info.measured_lufs
                ],
                "gains_db": [round(g, 2) for g in info.gains_db],
            },
            "renders": [
                {"id": j.id, "wall_s": j.wall_s, "realtime_factor": j.realtime_factor}
                for j in chosen
            ],  # fmt: skip
        }

    @app.get("/api/editor/audio/{key}.wav")
    def editor_audio(key: str):
        if key not in audio_cache:
            raise HTTPException(404)
        return Response(audio_cache[key], media_type="audio/wav")

    @app.post("/api/editor/save")
    def editor_save(body: dict = Body(...)):  # noqa: B008
        d = _drawing(body)
        name = str(body.get("name", ""))
        if not NAME.fullmatch(name):
            raise HTTPException(400, "a name is 2-48 characters: lowercase letters, digits, _")
        try:
            paths = save_circuit(d, name, origin=str(body.get("origin") or ""))
        except FileExistsError as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {"name": name, "files": [p.name for p in paths]}

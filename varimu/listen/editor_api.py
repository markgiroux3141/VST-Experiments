"""The schematic editor's page and API in `varimu listen` (device builder B4a).

    /editor                      the page (editor.html, ES modules from editor/)
    GET  /api/editor/symbols     the symbol table (varimu.editor.symbols)
    GET  /api/editor/circuits    circuit files, drawn (a <name>.drawing.json) or hand-written
    GET  /api/editor/open        a circuit's drawing (generated for a hand-written one) and
                                 its connectivity and parameters
    POST /api/editor/analyze     a drawing's connectivity, compile errors, parameters
    POST /api/editor/check       the pre-flight checks at every switch combination, as
                                 markers on the drawing

The page holds the drawing; the server is stateless.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from varimu.config import CONFIG_DIR, load_genome_bounds
from varimu.editor.compile import check_drawing, compile_drawing
from varimu.editor.connect import Connectivity
from varimu.editor.drawing import Drawing, drawing_path, load_drawing
from varimu.editor.layout import drawing_of_circuit
from varimu.editor.symbols import library_json

HERE = Path(__file__).parent
CIRCUITS = CONFIG_DIR / "circuits"


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
        **_params(c.data, d),
    }


def register(app) -> None:
    from fastapi import Body, HTTPException
    from fastapi.responses import HTMLResponse, Response

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

"""Write the native app's editor fixtures (docs/NATIVE_APP_PLAN.md, R3).

    uv run python scripts/export_editor_fixtures.py

What Python's editor (varimu.editor, the reference) makes of every drawn circuit in
config/circuits/ and of a few deliberately broken copies: the connectivity (nets,
junctions, loose ends, errors and warnings), the compiled circuit (its data and its
file's text), the IR the compiled circuit builds at its defaults, and the pre-flight
markers. Plus the symbol table as the page gets it. crates/varimu-circuit's tests port
each step and compare (tests/editor.rs). tests/test_editor_fixtures.py fails when the
fixtures are stale.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.editor.compile import check_drawing, circuit_text, compiled_spec
from varimu.editor.drawing import Drawing, load_drawing
from varimu.editor.symbols import library_json

FIXTURE_DIR = REPO_ROOT / "crates" / "varimu-circuit" / "tests" / "fixtures" / "editor"
ORIGIN = "a fixture"


def drawn_names() -> list[str]:
    return sorted(
        p.name[: -len(".drawing.json")] for p in (CONFIG_DIR / "circuits").glob("*.drawing.json")
    )


def broken(d: Drawing) -> dict[str, Drawing]:
    """Copies of the triode stage with something wrong, one thing each."""
    out = {}
    a = copy.deepcopy(d)
    a.wires.pop(0)
    out["wire_removed"] = a
    b = copy.deepcopy(d)
    ref = next(r for r, s in b.symbols.items() if "Source" in s.fields)
    del b.symbols[ref].fields["Source"]
    out["source_removed"] = b
    c = copy.deepcopy(d)
    first = c.labels[0]
    c.labels.append(type(first)("other_name", first.x, first.y, 0))
    out["two_labels"] = c
    e = copy.deepcopy(d)
    e.symbols["RX"] = copy.deepcopy(next(s for s in e.symbols.values() if s.symbol == "R"))
    for u in e.symbols["RX"].units.values():
        u.x += 200.0
    out["loose_resistor"] = e
    return out


def case(d: Drawing) -> dict[str, Any]:
    c, markers = check_drawing(d)
    conn = c.conn
    out: dict[str, Any] = {
        "drawing": d.to_json(),
        "nets": [
            {
                "name": n.name,
                "node": n.node,
                "pins": [[p.ref, p.unit, p.number] for p in n.pins],
                "wires": n.wires,
                "labels": n.labels,
                "grounds": n.grounds,
            }
            for n in conn.nets
        ],
        "errors": conn.errors,
        "warnings": conn.warnings,
        "junctions": sorted(conn.junctions),
        "loose": sorted(conn.loose),
        "compile_errors": c.errors,
        "problems": c.problems,
        "markers": [m.to_json() for m in markers],
    }
    if c.ok:
        out["data"] = c.data
        out["text"] = circuit_text(c, ORIGIN)
        cs = compiled_spec(c)
        out["ir"] = builder.build_ir(cs, spec.resolve(cs, {}), "ja").to_dict()
    return out


def fixtures() -> dict[str, str]:
    files = {"symbols.json": library_json()}
    for name in drawn_names():
        d = load_drawing(CONFIG_DIR / "circuits" / f"{name}.drawing.json")
        files[f"{name}.json"] = case(d)
        if name == "triode_stage_drawn":
            for k, b in broken(d).items():
                files[f"{name}__{k}.json"] = case(b)
    return {k: json.dumps(v, indent=None, separators=(",", ":"), ensure_ascii=False) + "\n"
            for k, v in files.items()}  # fmt: skip


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    texts = fixtures()
    for old in FIXTURE_DIR.glob("*.json"):
        if old.name not in texts:
            old.unlink()
    total = 0
    for name, text in texts.items():
        (FIXTURE_DIR / name).write_text(text, encoding="utf-8", newline="\n")
        total += len(text)
    print(f"{FIXTURE_DIR.relative_to(REPO_ROOT)}: {len(texts)} files, {total / 1000:.0f} kB")


if __name__ == "__main__":
    main()

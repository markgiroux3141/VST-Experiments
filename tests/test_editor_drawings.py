"""The hand-planned drawings of the hand-written circuits (scripts/draw_*.py, device
builder B4a): each script still draws the saved drawing, the drawing kit
(varimu.editor.sketch) finds nothing wrong with it, and the 670's builds the hand-written
IR. The EQP-1A's IR comparison is tests/test_editor.py's (test_eqp1a_drawn_by_hand)."""

from __future__ import annotations

import importlib.util
import json

import pytest

from varimu.circuit import builder
from varimu.circuit.spec import circuit_path, load_circuit, resolve
from varimu.config import REPO_ROOT
from varimu.editor.compile import check_drawing, compiled_spec
from varimu.editor.drawing import drawing_path, load_drawing
from varimu.kicad.compare import ir_differences
from varimu.preflight import switch_configs

SCRIPTS = {
    "pultec_eqp1a_drawn": "draw_pultec_eqp1a.py",
    "fairchild_670_drawn": "draw_fairchild_670.py",
}


def _script(name: str):
    path = REPO_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_script_draws_the_saved_drawing(name):
    sk = _script(SCRIPTS[name]).draw()
    assert sk.problems() == []
    saved = load_drawing(drawing_path(name)).to_json()
    assert json.loads(json.dumps(sk.d.to_json())) == saved


def test_670_drawn_builds_the_hand_written_ir():
    """The 670 drawn as a schematic passes the checks and builds the hand-written IR at
    every Time Constant position and with drawn tolerances, with both core models."""
    c, found = check_drawing(load_drawing(drawing_path("fairchild_670_drawn")))
    assert c.ok and [m.message for m in found] == []
    a, b = load_circuit(circuit_path("fairchild_670")), compiled_spec(c)
    configs = [*switch_configs(a), {"passive_spread": 1.0, "passive_seed": 7}]
    assert len(configs) == 7
    for ov in configs:
        for cores in ("linear", "ja"):
            diff = ir_differences(builder.build_ir(a, resolve(a, ov), cores),
                                  builder.build_ir(b, resolve(b, ov), cores))  # fmt: skip
            assert diff == [], (ov, cores)

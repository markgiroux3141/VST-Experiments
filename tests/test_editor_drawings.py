"""The hand-planned drawings of the hand-written circuits (scripts/draw_*.py, device
builder B4a): each script still draws the saved drawing, and the drawing kit
(varimu.editor.sketch) finds nothing wrong with it. That the saved drawings build the
hand-written IR is tests/test_editor.py's (test_eqp1a_drawn_by_hand)."""

from __future__ import annotations

import importlib.util
import json

import pytest

from varimu.config import REPO_ROOT
from varimu.editor.drawing import drawing_path, load_drawing

SCRIPTS = {"pultec_eqp1a_drawn": "draw_pultec_eqp1a.py"}


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

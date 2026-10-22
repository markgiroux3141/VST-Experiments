"""The emitted SPICE netlist is byte-identical to the captured goldens.

The goldens were captured before netlist.py was split into IR + SPICE emitter
(circuit-sim plan, M1). Regenerate with
`uv run python scripts/export_circuit_fixtures.py --golden` only when the
circuit is meant to change.
"""

import json
from pathlib import Path

import pytest

from varimu.circuit import netlist as nl

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "netlist_golden"
CASES = json.loads((GOLDEN_DIR / "cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(CASES))
def test_netlist_matches_golden(name):
    case = CASES[name]
    c = nl.build(case["overrides"], triode_formulation=case["triode_formulation"], cores="linear")
    assert c.text.encode("utf-8") == (GOLDEN_DIR / f"{name}.cir").read_bytes()
    assert {k: Path(v).name for k, v in c.files.items()} == case["files"]

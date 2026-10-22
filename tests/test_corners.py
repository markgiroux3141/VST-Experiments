"""Phase 3's "done when" (main plan): the circuit simulates across the corners of the
genome bounds, and the compressor reduces gain more as the input level rises.

The tests run scripts/corner_sweep.py's quick subset (all at their minimum, all at their
maximum, two random corners with part tolerances on), each set up as a technician would
(varimu.sim.setup) and as built. The full sweep (`uv run --extra fast python
scripts/corner_sweep.py`: every parameter alone at each bound too) writes
reports/corners/summary.json.
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from varimu.sim import fast, runner, setup

pytestmark = pytest.mark.skipif(not fast.available(), reason="needs `uv sync --extra fast`")

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import corner_sweep  # noqa: E402


@pytest.fixture(scope="module")
def quick_sweep():
    corners = corner_sweep.genomes(0, 0, quick=True)
    todo = [(label, g, trimmed) for label, g, _ in corners for trimmed in (True, False)]
    with ThreadPoolExecutor(max_workers=min(len(todo), runner.default_jobs())) as ex:
        return list(ex.map(lambda a: corner_sweep.run_one(*a), todo))


def test_corners_simulate_compress_and_stay_quiet(quick_sweep):
    for r in quick_sweep:
        what = f"{r['label']} ({'set up' if r['trimmed'] else 'as built'})"
        assert r["simulated"], f"{what}: {r.get('error')}"
        assert r["gr_rises"], f"{what}: GR per step {r['gr_db']}"
        assert r["gr_db"][-1] > 10, f"{what}: GR per step {r['gr_db']}"
        assert r["idle_quiet"], f"{what}: idle {r['idle_out_dbfs']} dBFS"


def test_setup_meets_the_manuals_procedures():
    """B+ ADJ, BALANCE and ZERO on a unit with its parts and tubes spread: the regulated
    rail at the nominal unit's, the meter equal in both BALANCE positions, the stage's
    total current at the nominal unit's (all on the DC operating point)."""
    unit = {"passive_spread": 1.0, "passive_seed": 2}
    adjusted = setup.adjust(unit)
    bp, total = setup._nominal_targets()
    before, after = (setup._readings(setup.dc(g)) for g in (unit, adjusted))
    assert abs(before["bp"] - bp) > 1.0 and abs(before["balance"]) > 0.01  # it needed setting up
    assert after["bp"] == pytest.approx(bp, abs=0.01)
    assert after["balance"] == pytest.approx(0.0, abs=1e-3)
    assert after["total"] == pytest.approx(total, rel=1e-3)

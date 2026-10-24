"""Phase 4's plausibility checks on real renders: the nominal unit passes, broken ones
don't (main plan Phase 4, "done when"; the whole set is scripts/plausibility_check.py).

Each genome runs the cheap screen (three short renders, ~1-2 min) or, for the slow
release, the suite's TC2 burst; they run in parallel. Covered here: one of each kind
Phase 3's corner sweep flagged (an HF oscillator, a weak-supply corner wandering at
LF, gain reduction folding back at T101's 20 mH leakage bound) and three
deliberately broken genomes (no sidechain drive, absurd distortion, a CV that never
returns: C109 300x). Comparisons with the 670's published figures don't reject.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from varimu.measure import plausibility, suite
from varimu.sim import fast

pytestmark = pytest.mark.skipif(not fast.available(), reason="needs `uv sync --extra fast`")

PHASE3 = ("phase3:random-15", "phase3:random-13", "phase3:t101_leakage_h=0.02")
BROKEN = ("no_sidechain_drive", "saturated_input_transformer", "slow_release")


@pytest.fixture(scope="module")
def judged():
    flagged = plausibility.phase3_flagged()
    todo = {"nominal": ({}, True, "screen")}
    todo |= {k: (flagged[k][0], flagged[k][1], "screen") for k in PHASE3}
    todo |= {k: (plausibility.BROKEN[k][0], True, plausibility.BROKEN[k][2]) for k in BROKEN}
    with ThreadPoolExecutor(max_workers=len(todo)) as ex:
        futs = {
            k: ex.submit(suite.judge, k, g, adjust=a, stage=st, log=lambda m: None)
            for k, (g, a, st) in todo.items()
        }
        return {k: f.result() for k, f in futs.items()}


def test_the_nominal_unit_passes_the_screen(judged):
    r = judged["nominal"]
    assert r["passes"], r["failed"]
    assert -6.5 < r["idle"]["cv_v"] < -4.5
    assert r["hot"]["gr_db"][-1] > 15


@pytest.mark.parametrize("name", PHASE3)
def test_phase3_flagged_genomes_are_rejected(judged, name):
    r = judged[name]
    assert not r["passes"], r


@pytest.mark.parametrize("name", BROKEN)
def test_deliberately_broken_genomes_are_rejected_for_the_right_reason(judged, name):
    r = judged[name]
    expected = plausibility.BROKEN[name][1]
    assert not r["passes"]
    assert expected & set(r["failed"]), (expected, r["failed"])

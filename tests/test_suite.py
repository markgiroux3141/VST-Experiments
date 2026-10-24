"""The Phase 4 suite's pieces that need no renders: signals, chunking, checks.

The renders themselves (a unit's report, the screen on broken genomes) are in
test_plausibility.py.
"""

import numpy as np
import pytest

from varimu.measure import levels, plausibility, suite

FS = 96000


def test_probe_tones_avoid_the_pilot_and_its_products():
    f = suite.probe_freqs(FS)
    assert len(f) == suite.PROBE_TONES and np.all(np.diff(f) > 0)
    assert f[0] >= 20 and f[-1] <= 20500
    bin_hz = 1 / suite.PROBE_PERIOD_S
    assert np.allclose(f / bin_hz, np.round(f / bin_hz))  # on bins: no leakage
    for k in range(1, 21):
        assert np.all(np.abs(f - k * suite.PILOT_HZ) >= 3 * bin_hz)
    for i, a in enumerate(f):
        for b in f[:i]:
            for k in (1, 2, 3):
                assert abs(abs(a - b) - k * suite.PILOT_HZ) >= 0.5 * bin_hz
                assert abs(a + b - k * suite.PILOT_HZ) >= 0.5 * bin_hz


def test_staircase_chunks_cover_every_step_once():
    st = levels.Staircase({}, [-30.0 + 2.5 * i for i in range(15)], 1000.0, hold_s=0.1)
    steps = [s for _, segs in st._parts for s in segs]
    assert [s["level_dbfs"] for s in steps] == [-30.0 + 2.5 * i for i in range(15)]
    for job, segs in st._parts:
        assert segs[-1]["stop"] == len(job.samples)
    with pytest.raises(ValueError):
        levels.Staircase({}, [0.0, -1.0])


def test_whole_periods():
    assert levels._whole_periods(1000, 1000.0, FS) == 960
    assert levels._whole_periods(1000, 6000.0, FS) == 992
    assert levels._whole_periods(5000, 100.0, FS) == 4800


def _report(**changes):
    """A minimal full report that passes every check."""
    step = {"gr_db": 0.0, "spur_db": -90.0}
    curve = {"steps": [step, dict(step, gr_db=5.0)], "gr_monotonic": True, "gr_max_db": 15.0}
    r = {
        "curves": {
            "1000hz_factory": curve,
            "1000hz_ac0": curve,
            "vs_curve3": {"max_abs_diff_db": 0.3},
        },
        "distortion": {"no_limiting_thd_pct_at_4dbm_out": 0.2},
        "timing": {
            f"timing_tc{tc}": {
                "attack_cv_63_ms": 1.5,
                "release_cv_90_s": 0.8 * pub,
                "published_release_s": pub,
                "cv_end_v": -5.7,
                "cv_before_v": -5.66,
            }
            for tc, (_, pub) in suite.PUBLISHED_TIMING.items()
        },
        "response": {"0": {"band_40hz_15khz_db": [-0.4, 0.3]}},
        "imd": {"0": {"smpte_pct": 0.5}},
    }
    for path, v in changes.items():
        node = r
        *keys, last = path.split("__")
        for k in keys:
            node = node[k]
        node[last] = v
    return r


def test_full_checks_pass_a_working_unit_and_name_what_breaks():
    assert all(c["passes"] for c in plausibility.full_checks(_report()).values())
    cases = {
        "factory_curve": {"curves__vs_curve3__max_abs_diff_db": 6.0},
        "release": {"timing__timing_tc2__release_cv_90_s": 9.0},
        "attack": {"timing__timing_tc1__attack_cv_63_ms": 50.0},
        "cv_returns": {"timing__timing_tc3__cv_end_v": -30.0},
        "response": {"response__0__band_40hz_15khz_db": [-6.0, 0.2]},
        "nominal_distortion": {"distortion__no_limiting_thd_pct_at_4dbm_out": 12.0},
    }
    for check, change in cases.items():
        failed = [
            k for k, c in plausibility.full_checks(_report(**change)).items() if not c["passes"]
        ]
        assert failed == [check], (check, failed)
    # A release too long for its window reads NaN: rejected, not passed.
    r = _report(timing__timing_tc4__release_cv_90_s=float("nan"))
    assert not plausibility.full_checks(r)["release"]["passes"]


def test_curve3_and_the_factory_target():
    """The digitized factory curve: unity gain at its start, limiting harder as it
    rises, and the procedure's two points (3 dB of limiting at +3.66 dBm out, 10 dB
    at +5.41 dBm out) read off it."""
    from varimu.sim import setup

    x, y = setup.curve3()
    assert x[0] == 2.0 and x[-1] == 25.0
    assert np.all(np.diff(y) >= -0.02)  # output never falls (to the digitizing error)
    assert np.all(np.diff(x - y) > 0)  # limiting rises with level
    t = setup.factory_target()
    assert t.out_3db_dbm == pytest.approx(3.66, abs=0.01)
    assert t.out_10db_dbm == pytest.approx(5.41, abs=0.01)
    assert suite.gr_points() == pytest.approx({"0": -10.0, "3": 6.66, "10": 15.41}, abs=0.01)

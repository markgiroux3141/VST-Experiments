"""The Minimoog VCF (config/circuits/minimoog_filter_board.yaml, docs/MINIMOOG_PLAN.md MM1): its
idle bias from the drawing, and Folkman's three adjustment procedures met at the circuit file's
trims (scripts/minimoog_vcf_trim.py --write sets them)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("circuitsim")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import minimoog_vcf_study as st  # noqa: E402


@pytest.fixture(scope="module")
def s():
    return st.load()


def test_idle_bias_follows_the_string(s):
    """+10 V over R4 220 + 4 x 150 + R61 200: the input pair's bases at 1.96 V, the top
    stage's emitters one Vbe under its bases (7.84 V); the output amp's collectors in range."""
    v = st.idle(s)
    assert v["v(nb)"] == pytest.approx(10.0 * 200 / 1020, abs=0.02)
    assert 7.84 - 0.7 < v["v(a4)"] < 7.84 - 0.45
    assert v["v(a4)"] == pytest.approx(v["v(b4)"], abs=1e-3)
    assert 1.0 < v["v(o7)"] < 8.0


def test_regeneration_starts_between_emphasis_7_and_8(s):
    """Folkman, 'Regeneration Cal.': CUTOFF -1, regeneration starts between EMPHASIS 7 and 8."""
    assert not st.oscillates(st.build(s, {"emphasis": 0.7}))[0]
    assert st.oscillates(st.build(s, {"emphasis": 0.8}))[0]


def test_range_rings_at_440_with_the_keyboard_off(s):
    """Folkman, 'Filter Range': keyboard control off, CUTOFF -1, EMPHASIS 10: the A-440."""
    ok, _, f = st.oscillates(st.build(s, {"emphasis": 1.0, "kb1": 0, "kb2": 0}))
    assert ok
    assert f == pytest.approx(440.0, rel=0.01)


def test_scale_tracks_three_octaves(s):
    """Folkman, 'Filter Scale': the filter tracks the keyboard over three octaves (its four A keys
    on the string's volts, ~1.012 V / octave), within 3 % of an octave per keyboard octave."""
    import minimoog_vcf_trim as trim

    ir = st.build(s, {"emphasis": 1.0})
    f = np.array([st.oscillates(ir, key_v=trim.key_volts(s, 45 + 12 * i))[2] for i in range(4)])
    assert np.all(np.abs(np.diff(np.log2(f)) - 1.0) < 0.03)


def test_four_pole_low_pass(s):
    """EMPHASIS 0: a plateau around 80-170 Hz (below it the input's C27 10 uF into ~470 ohm,
    a high-pass near 35 Hz: the drawing's), then ~24 dB / octave (4 kHz to 8 kHz, with the
    cutoff near 440 Hz, is well into the asymptote). EMPHASIS takes the passband down as
    the peak grows (the ladder's loss of bass with resonance)."""
    r = st.response(s, {"emphasis": 0.0})
    fr, db = np.array(r["freq_hz"]), np.array(r["gain_db"])

    def g(hz):
        return np.interp(np.log(hz), np.log(fr), db)

    assert abs(g(80.0) - g(160.0)) < 1.0
    assert g(20.0) < g(120.0) - 5.0
    assert g(8000.0) - g(4000.0) == pytest.approx(-24.0, abs=2.5)
    r5 = st.response(s, {"emphasis": 0.5})
    assert r5["g0"] < 0.6 * r["g0"]
    assert max(r5["gain_db"]) > max(r["gain_db"]) + 4.0

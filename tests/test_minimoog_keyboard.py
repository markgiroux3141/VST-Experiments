"""The Minimoog's keyboard circuit (board No. 2, Fig 9-7's circuit No. 1; docs/MINIMOOG_PLAN.md
MM4):
the string's current, tracking through the sample-and-hold and the glide follower, glide, the
hold."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("circuitsim")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import minimoog_keyboard_study as kb  # noqa: E402


@pytest.fixture(scope="module")
def s():
    return kb.load()


def test_current_source_sets_the_key_volts(s):
    """Q9 / Q11 into the 430 ohm string: between Fig 9-7's 8.33 mA and Fig 9-17's 8.48 mA, and the
    circuit file's key_v_per_semitone (what the app's keys put on the pitch bar) is 10 ohm times
    it."""
    c = kb.current(s)
    assert 8.30 < c["current_ma"] < 8.52
    assert kb.value(s, "key_v_per_semitone") == pytest.approx(c["v_per_key"], rel=2e-4)
    assert kb.value(s, "key_max_v") == pytest.approx(43 * c["v_per_key"], rel=2e-4)


def test_tracks_one_volt_per_octave(s):
    """A key held: the output follows the pitch bar, octave steps within 0.5 % of the string's
    (12 x 84.4 mV; the follower's base currents add ~0.35 %), within 2 % of 1 V (the oscillators'
    and the filter's Scale trims take the rest out), offset under 15 mV over the keyboard."""
    t = kb.track(s)
    rows = {r["note"]: r for r in t["rows"]}
    for lo in (45, 57, 69):
        step = rows[lo + 12]["out_v"] - rows[lo]["out_v"]
        assert step == pytest.approx(12 * kb.value(s, "key_v_per_semitone"), rel=5e-3)
        assert step == pytest.approx(1.0, rel=0.02)
    assert max(abs(r["offset_mv"]) for r in t["rows"]) < 15.0


def test_glide_times_follow_the_knob(s):
    """GLIDE off (or at 0): under a millisecond; on: an octave's 1/e time grows with the knob to
    tenths of a second at 10 (R2 5M on C6 1 uF, the op-amp's swing driving it); down slower than up
    (the op-amp swings to +10 V but only -4.4 V, C6 a JFET's Vgs under the output)."""
    off = kb.glide_time(s, 0.5, on=0)
    assert off["t_1e_ms"] < 1.0
    times = [kb.glide_time(s, k, on=1)["t_1e_ms"] for k in (0.25, 0.5, 1.0)]
    assert times[0] < times[1] < times[2]
    assert 3.0 < times[0] < 30.0
    assert 150.0 < times[2] < 1000.0
    down = kb.glide_time(s, 0.5, on=1, up=False)["t_1e_ms"]
    assert down > 1.5 * times[1]


def test_key_up_holds_the_last_pitch(s):
    """After key-up Q13 opens (its gate pulled down through CR5) and C6 holds: the output stays
    within 1 mV over two seconds."""
    h = kb.hold(s)
    assert abs(h["out_at_s"][2.4] - h["out_at_s"][0.32]) < 1e-3
    assert h["out_at_s"][0.32] == pytest.approx(h["key_v"], abs=0.02)


def test_voice_keys_reach_the_filter_through_the_partition():
    """minimoog_voice through the app's partition: two keys an octave apart move the keyboard's
    output (the filter's KEYBOARD CONTROL node) by the string's octave; the gate on the trigger
    contact opens the VCA (shut before the first key)."""
    import minimoog_gate_check as gc

    from varimu.circuit import builder, spec
    from varimu.config import CONFIG_DIR

    vs = spec.load_circuit(CONFIG_DIR / "circuits" / "minimoog_voice.yaml")
    ir = builder.build_ir(vs, spec.resolve(vs, {}), "ja")
    g_off, g_on = gc.gate_levels(vs, "gate")
    fs = int(kb.FS)
    n = int(1.0 * fs)
    gate = np.full(n, g_off)
    gate[int(0.2 * fs) : int(0.45 * fs)] = g_on
    gate[int(0.55 * fs) : int(0.8 * fs)] = g_on
    key = np.full(n, gc.key_volts(vs, 45))
    key[int(0.5 * fs) :] = gc.key_volts(vs, 57)
    import dataclasses

    from varimu.sim import fast

    st = dataclasses.replace(
        gc.st.settings("draft-1x"),
        newton_reltol=1e-5,
        newton_vntol=1e-5,
        partition=gc.VOICE_PARTITION,
        partition_coupling="hold",
    )
    t = np.arange(n) / fs
    x = 0.25 * (2 * ((t * 220.0) % 1.0) - 1)
    r = fast.run_transient(ir, x, settings=st, controls={"key": key, "gate": gate})
    kbd = np.asarray(r.vectors["v(kbd)"])
    out = np.asarray(r.vectors["v(out)"])
    step = kbd[int(0.75 * fs)] - kbd[int(0.4 * fs)]
    assert step == pytest.approx(12 * kb.value(vs, "key_v_per_semitone"), rel=0.01)
    assert np.std(out[int(0.3 * fs) : int(0.4 * fs)]) > 0.3
    assert np.std(out[int(0.05 * fs) : int(0.15 * fs)]) < 1e-3

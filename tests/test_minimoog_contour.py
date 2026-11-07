"""The Minimoog's filter contour generator (board No. 2, Fig 9-7), alone (docs/MINIMOOG_PLAN.md, MM4)."""

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("circuitsim")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import minimoog_contour_times as ct  # noqa: E402

FS = ct.FS
T_ON = ct.T_ON


def test_attack_range_matches_the_panel():
    """ATTACK at 0 is a few ms (the trigger's C7 delay included), at 10 several seconds (1 ms - 10 s)."""
    out0, _ = ct.one(0.0, 0.0, 1.0, 1.0, 1.5)
    seg = out0[int(T_ON * FS) :]
    t_fast = np.argmax(seg > 0.98 * seg.max()) / FS
    assert t_fast < 0.01
    assert 4.0 < seg.max() < 5.5  # the peak detector's top (a germanium CR3 would sit ~0.3 V lower)
    out1, _ = ct.one(1.0, 0.0, 1.0, 12.0, 13.0)
    seg = out1[int(T_ON * FS) :]
    t_slow = np.argmax(seg > 0.98 * seg.max()) / FS
    assert 5.0 < t_slow < 12.0


def test_decay_range_and_the_sustain_level():
    """DECAY at 0 falls in ~1 ms, at 8 in seconds; the fall stops at the SUSTAIN level while the key is held."""
    out, env = ct.one(0.0, 0.0, 0.0, 1.0, 1.4)
    seg = out[int(T_ON * FS) :]
    ipk = int(np.argmax(seg))
    assert np.argmax(seg[ipk:] < seg.max() / 2) / FS < 0.005
    assert seg[int(0.8 * FS)] < 0.3  # SUSTAIN 0: back to idle
    out, _ = ct.one(0.0, 0.0, 1.0, 1.0, 1.4)
    assert out[int((T_ON + 0.9) * FS)] > 3.0  # SUSTAIN 10: stays near the peak
    out, _ = ct.one(0.0, 0.4, 0.0, 6.0, 7.0)
    seg = out[int(T_ON * FS) :]
    ipk = int(np.argmax(seg))
    tau = np.argmax(seg[ipk:] < seg.max() / np.e) / FS
    assert 0.3 < tau < 1.5


def test_release_follows_decay_and_gate_off_ends_the_note():
    """After the key goes up the output falls to ~0 (release through DECAY), and a second gate attacks again."""
    ir = ct.cs.build({"attack": 0.0, "decay": 0.2, "sustain": 1.0})
    n = int(FS * 3.0)
    gate = np.zeros(n)
    gate[int(0.2 * FS) : int(0.8 * FS)] = 5.0
    gate[int(1.5 * FS) : int(2.0 * FS)] = 5.0
    out = ct.cs.run(ir, gate)["outn"]
    assert out[int(0.7 * FS)] > 3.5
    assert out[int(1.4 * FS)] < 0.4
    assert out[int(1.9 * FS)] > 3.5

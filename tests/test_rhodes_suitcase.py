"""The Rhodes Suitcase's 100 W preamp (config/circuits/rhodes_suitcase.yaml, docs/RHODES_PLAN.md
"The Suitcase"): it passes the pre-flight checks, idles where fig11-1's circuit must, and its
vibrato pans at the reference recording's rate, in antiphase, as scripts/suitcase_study.py
calibrated it (the recording itself is untracked: its figures are written here)."""

from __future__ import annotations

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec

CIRCUIT = "rhodes_suitcase"


def load():
    return spec.load_circuit(spec.circuit_path(CIRCUIT))


def test_the_checks_pass_at_every_switch():
    assert preflight.check_circuit(load()) == []


def test_it_idles_as_drawn():
    """Silence in, the vibrato off (0.2 s at draft after the run's settle): the decoupled rails
    a few tenths inside 15 V (the LED strings' ~6 mA through R21 / R19), the audio path at
    0 V, `v` resting between the two LED strings."""
    pytest.importorskip("circuitsim")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    ir = builder.build(load(), {"accessory_in": 1, "vibrato": 0}).ir
    v = fast.run_transient(ir, np.zeros(int(0.2 * s.sample_rate)), settings=s).vectors
    mean = {k[2:-1]: float(np.mean(x)) for k, x in v.items()}
    assert 14.0 < mean["vbp"] < 15.0
    assert -15.0 < mean["vbn"] < -14.0
    for node in ("a1o", "n9", "out", "out_r"):
        assert abs(mean[node]) < 0.05, node
    assert abs(mean["v"]) < 2.0
    # Nearly steady: with S1 open only VB-'s ripple moves it (the oscillator still runs and
    # its timing current returns through C3 into VB-, which the LED strings share): 0.19 V.
    assert np.ptp(v["v(v)"]) < 0.5


def test_the_vibrato_pans_at_the_reference_rate():
    """Draft, 4 s of a tone through ACCESSORY IN: the balance at the reference's 3.83 Hz
    within 1%, +-6.75 dB of fundamental at full INTENSITY (the recording's +-7.8: the VTL5C2
    stand-in's limit), a sawtooth-like shape (the recording's 3rd harmonic 0.17 of the
    fundamental, the 2nd 0.02), and the two outputs in antiphase."""
    pytest.importorskip("circuitsim")
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    import suitcase_study as ss

    r = ss.measure({}, "draft", 4.0)
    assert r["rate_hz"] == pytest.approx(3.834, rel=0.01)
    assert r["fundamental_db"] == pytest.approx(6.75, abs=0.5)
    h2, h3 = r["harmonics_re_fundamental"][:2]
    assert h2 < 0.1
    assert 0.05 < h3 < 0.3
    assert r["left_vs_mean_fundamental_db"] == pytest.approx(r["fundamental_db"] / 2, rel=0.05)
    # the vibrato off: no pan
    off = ss.measure({"vibrato": 0}, "draft", 2.0)
    folded = np.array(off["folded_db"])
    assert np.ptp(folded) < 0.5

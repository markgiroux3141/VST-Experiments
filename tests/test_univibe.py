"""The Uni-Vibe (config/circuits/univibe.yaml, docs/MODULATION_PLAN.md MD1): its LFO's range is
the measured unit's, its cells are trimmed to that unit's minimum resistances, CANCEL darkens
them, and the lamp idles at a dim glow."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.devices.library import load_device

PROBES = ["spd", "lt", "vc"] + [f"ps{k}" for k in range(1, 5)] + [f"l{k}b" for k in range(1, 5)]
# DAFx-19 (Darabundit, Wedelich, Bischoff) Table 1: each cell's measured minimum.
PAPER_MIN_OHM = (12.7e3, 6.86e3, 7.69e3, 6.22e3)


def _run(sets: dict, seconds: float = 5.0, measure_s: float = 2.5):
    from varimu.sim import fast, io

    c = spec.load_circuit(spec.circuit_path("univibe"))
    ir = builder.build_ir(c, spec.resolve(c, sets))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in PROBES))
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    fs = st.sample_rate
    v = fast.run_transient(ir, np.zeros(round(seconds * fs)), settings=st).vectors
    m = round(measure_s * fs)
    v = {k: a[-m:] for k, a in v.items()}
    cell = load_device("PDVP9203@1")
    g = [(v[f"v(ps{k})"] - v[f"v(l{k}b)"]) * cell.s_unit_s for k in range(1, 5)]
    ohms = 1.0 / (cell.g_dark_s + np.maximum(np.array(g), 0.0))
    lamp_k = v["v(lt)"] - v["v(vc)"] + 300.0
    y = v["v(spd)"] - v["v(spd)"].mean()
    z = np.where((y[:-1] < 0) & (y[1:] >= 0))[0]
    hz = fs / np.mean(np.diff(z)) if len(z) > 2 else 0.0
    return hz, lamp_k, ohms


def test_the_circuit_passes_its_checks():
    c = spec.load_circuit(spec.circuit_path("univibe"))
    assert preflight.check_circuit(c) == []


@pytest.mark.parametrize(("speed", "want_hz"), [(0.0, 0.86), (1.0, 7.98)])
def test_speed_spans_the_measured_units_range(speed, want_hz):
    """SPEED from heel to toe: the DAFx-19 unit's 'approximately 0 Hz to 7.6 Hz' (its 0 the
    cancel switch); ours 0.86-7.98 Hz (scripts/univibe_study.py rates)."""
    pytest.importorskip("circuitsim")
    hz, lamp_k, _ = _run({"speed": speed, "intensity": 1.0}, seconds=6.5, measure_s=4.5)
    assert hz == pytest.approx(want_hz, rel=0.05)
    assert lamp_k.max() - lamp_k.min() > 150.0  # the lamp swings


def test_the_cells_meet_the_measured_minimum():
    """At full INTENSITY, mid SPEED (where scripts/univibe_trim.py's sweep finds the minimum):
    each cell's minimum within 5% of the paper's, its maximum past a megohm."""
    pytest.importorskip("circuitsim")
    _, _, ohms = _run({"speed": 0.5, "intensity": 1.0})
    np.testing.assert_allclose(ohms.min(axis=1), PAPER_MIN_OHM, rtol=0.05)
    assert np.all(ohms.max(axis=1) > 1e6)


def test_cancel_darkens_the_cells():
    """CANCEL grounds the lamp driver's base: the filament cools to below a glow and the cells
    go dark (megohms), as the original's bypass."""
    pytest.importorskip("circuitsim")
    _, lamp_k, ohms = _run({"cancel": 1, "intensity": 1.0}, seconds=4.0, measure_s=1.0)
    assert lamp_k.max() < 900.0
    assert np.all(ohms.min(axis=1) > 2e6)

"""The Neumann U 87 (docs/CHAINS_PLAN.md WP22): config/circuits/neumann_u87.yaml (Neumann's 1980
drawing) with K87@2, the K87 fitted to the U 87 i's curves through the circuit's feedback
(scripts/fit_k87.py; the feedback as drawn costs 5.6 dB). The sensitivity, the patterns' equal
sensitivity, the cardioid's rear rejection and the source impedance against Neumann's figures."""

from __future__ import annotations

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

U87 = CONFIG_DIR / "circuits" / "neumann_u87.yaml"


@pytest.fixture(scope="module")
def u87():
    return spec.load_circuit(U87)


def test_builds_and_every_value_is_sourced(u87):
    for cores in ("ja", "linear"):
        assert [x.name for x in builder.build(u87, cores=cores).ir.controls] == ["p_rear"]
    assert spec.check_genome_links(u87) == []


def test_preflight_passes(u87):
    assert preflight.check_circuit(u87) == []


def test_the_capsule_is_two_50_pf_halves(u87):
    """cat: 2 x ~50 pF (c0 is one side's: the backplate's radius derived from it at the
    published 40 um gap; K87@1 had 103.5 pF a side)."""
    from varimu.devices.library import component_data

    lp = component_data(spec.resolve(u87)["capsule_model"])["lumped"]
    assert 1e12 * lp["c0_f"] == pytest.approx(50.0, rel=0.05)


def _level(u87, pattern, f0, angle_deg, over=None):
    from varimu.devices.library import component_data
    from varimu.measure import metrics
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    g = component_data(spec.resolve(u87)["capsule_model"])["geometry"]
    t = np.arange(int(0.4 * fs)) / fs
    p = np.sqrt(2) * np.sin(2 * np.pi * f0 * t) * np.minimum(1, t / 0.05)
    front, rear, _ = capsule_entry_pressures(g, p, np.radians(angle_deg), fs)
    ir = builder.build(u87, {"pattern": pattern, **(over or {})}).ir
    v = fast.run_transient(ir, front, settings=s, controls={"p_rear": rear}).vectors
    return metrics.harmonics(np.asarray(v["v(out)"])[-fs // 5 :], f0, fs).amps[0] / np.sqrt(2)


def test_idle_drain(u87):
    """sch: the drain 'ca. 11V' (the selected source resistor's fit)."""
    pytest.importorskip("circuitsim")
    from varimu.sim import fast

    ir = builder.build_ir(u87, spec.resolve(u87), "ja")
    v = fast.run_transient(ir, np.zeros(960), controls={"p_rear": np.zeros(960)}).vectors
    assert v["v(d)"][-1] == pytest.approx(11.0, abs=0.5)


def test_sensitivity_and_patterns(u87):
    """cat: ~8 mV/Pa at every pattern (Ue1's ratio fitted to the source impedance; the capsule
    to the curves and this through the feedback), the patterns within 1 dB of each other; the
    cardioid 90 deg about -6.5 dB (Neumann's polar -3.7: the model's halves are equal), its rear
    better than 20 dB down at 1 kHz."""
    pytest.importorskip("circuitsim")
    lv = {pat: _level(u87, pat, 1000.0, 0) for pat in (0, 1, 2)}
    for pat, x in lv.items():
        assert 20 * np.log10(1e3 * x / 8.0) == pytest.approx(0.0, abs=1.0), pat
    db = [20 * np.log10(x) for x in lv.values()]
    assert max(db) - min(db) < 1.0
    side = 20 * np.log10(_level(u87, 1, 1000.0, 90) / lv[1])
    back = 20 * np.log10(_level(u87, 1, 1000.0, 180) / lv[1])
    assert -7.5 < side < -5.5
    assert back < -20.0


def test_source_impedance(u87):
    """cat: ~200 ohm (Ue1's ratio fitted to it)."""
    pytest.importorskip("circuitsim")
    a = _level(u87, 1, 1000.0, 0)
    b = _level(u87, 1, 1000.0, 0, {"r_load_ohm": 1e6})
    assert 1000.0 * (b / a - 1) == pytest.approx(200.0, rel=0.2)

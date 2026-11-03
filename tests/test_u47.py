"""The Neumann U47 (MIC_ROOM_PLAN.md A3): config/circuits/neumann_u47.yaml, and the U47
into the V76 as one netlist (config/circuits/u47_v76.yaml, scripts/compose_chain.py).

The U47 builds in both patterns, passes the pre-flight checks, and idles at the 1959
drawing's printed voltages with its underheated VF14M (B6's space-charge shift at the
heater's printed 35 V: without it the anode sits at ~27 V against the printed 34)."""

import subprocess
import sys

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.devices.cathode import Cathode, load_cathodes

PRINTED_V = {"a": 34.0, "k": 1.1, "f2": 36.0, "bp": 63.0, "b105": 105.0}  # sch


@pytest.fixture(scope="module")
def u47():
    return spec.load_circuit(spec.circuit_path("neumann_u47"))


def test_builds_in_both_patterns(u47):
    assert preflight.check_circuit(u47) == []
    for pattern in (0, 1):
        ir = builder.build(u47, {"pattern": pattern}).ir
        names = {e.name for e in ir.elements()}
        rear_source = any(n.startswith("GKK47") and n.endswith("_xr") for n in names)
        assert rear_source == (pattern == 1)  # omni polarizes the rear diaphragm


def test_space_charge_shift_is_the_cathode_models(u47):
    ox, tubes = load_cathodes()
    t = tubes["VF14T"]
    c = Cathode(t["heater_v"], t["heater_a"], 1.0, ox.phi_ev, ox.n, t0_k=ox.t0_k)
    shift = ox.shift_t(c.steady_k(volts=35.0))
    assert spec.resolve(u47)["space_charge_v"] == pytest.approx(shift, abs=1e-3)


def test_idles_at_the_printed_voltages(u47):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    n = int(0.5 * s.sample_rate)
    ir = builder.build(u47).ir
    v = fast.run_transient(ir, np.zeros(n), settings=s, controls={"p_rear": np.zeros(n)}).vectors
    for node, d in PRINTED_V.items():
        assert np.mean(v[f"v({node})"][-n // 5 :]) == pytest.approx(d, rel=0.08), node
    ia = (np.mean(v["v(b105)"][-n // 5 :]) - np.mean(v["v(a)"][-n // 5 :])) / 130e3
    assert ia == pytest.approx(0.55e-3, rel=0.1)  # sch: about 0.55 mA


def test_chain_is_current_and_builds():
    r = subprocess.run(
        [sys.executable, "scripts/compose_chain.py", "--mic", "neumann_u47",
         "--pre", "telefunken_v76", "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr
    c = spec.load_circuit(spec.circuit_path("u47_v76"))
    ir = builder.build(c, {"pattern_u47": 1, "gain_db_v76": 52}).ir
    assert [x.name for x in ir.controls] == ["p_rear"]
    nodes = {
        n for e in ir.elements() for n in getattr(e, "__dict__", {}).values() if isinstance(n, str)
    }
    assert "ia_v76" in nodes and "out" in nodes and "in" in nodes


def test_sensitivity_and_directivity_against_neumanns(u47):
    """The whole mic (K47@2 on its sphere, the VF14 stage, the BV 8 into 1 kOhm at the
    200 ohm setting) against ds58: cardioid 25-28 mV/Pa (measured 25.4 at 1 kHz), omni
    14-17 (19.1: ~1 dB over); the cardioid's front / back 13.2 dB at 100 Hz and 15.1 at
    1 kHz against the 1958 polars' 11.7 and 16.2 (measured 2026-11-03)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.devices.library import component_data
    from varimu.measure import metrics
    from varimu.mics.free_field import sphere_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    g = component_data(spec.resolve(u47)["capsule_model"])["geometry"]
    sph = (g["sphere_radius_m"], g["diaphragm"]["radius_m"])
    t = np.arange(int(0.5 * fs)) / fs

    def level(pattern, f0, angle_deg):
        p = np.sqrt(2) * np.sin(2 * np.pi * f0 * t) * np.minimum(1, t / 0.05)
        front, rear = sphere_entry_pressures(p, np.radians(angle_deg), *sph, fs)
        ir = builder.build(u47, {"pattern": pattern}).ir
        v = fast.run_transient(ir, front, settings=s, controls={"p_rear": rear}).vectors
        return metrics.harmonics(v["v(out)"][-fs // 5 :], f0, fs).amps[0] / np.sqrt(2)

    card = level(0, 1000.0, 0)
    assert 23e-3 < card < 29e-3
    assert 13e-3 < level(1, 1000.0, 0) < 21e-3
    for f0, lo in ((100.0, 10.0), (1000.0, 12.0)):
        assert 20 * np.log10(level(0, f0, 0) / level(0, f0, 180)) > lo

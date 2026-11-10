"""The Telefunken ELA M 251 E (the chains build-out's WP18), built by inference:
config/circuits/telefunken_ela_m251.yaml (data/schematics/telefunken_ela_m251/README.md).

It builds, passes the pre-flight checks at its three patterns, idles at a cathode-biased 6072
point, each pattern's capsule is polarized as the DC solution puts its electrodes, and the
whole microphone's sensitivity (an original's 10 mV/Pa) and front / back meet the figures.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

M251 = CONFIG_DIR / "circuits" / "telefunken_ela_m251.yaml"
POL = {0: "pol_rear_omni_v", 1: "pol_rear_cardioid_v", 2: "pol_rear_eight_v"}


@pytest.fixture(scope="module")
def m251():
    return spec.load_circuit(M251)


def test_builds_and_every_value_is_sourced(m251):
    for cores in ("ja", "linear"):
        assert [x.name for x in builder.build(m251, cores=cores).ir.controls] == ["p_rear"]
    assert spec.check_genome_links(m251) == []
    a = builder.build_ir(m251, spec.resolve(m251, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(m251, spec.resolve(m251))
    moved = sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True))
    assert moved > 8


def test_preflight_passes(m251):
    assert preflight.check_circuit(m251) == []


def _idle(c, pattern):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    n = int(0.1 * st.sample_rate)
    ir = builder.build_ir(c, spec.resolve(c, {"pattern": pattern}))
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls={"p_rear": np.zeros(n)})
    return {k[2:-1]: float(np.mean(a[-n // 2 :])) for k, a in v.vectors.items()}


def test_idle_and_polarizations(m251):
    """The 6072 at 0.62 mA with 1.12 V of cathode bias (R11 1.8k; measured 2026-11-10); the
    backplate at B+ / 2 and each pattern's rear polarization as its capsule is built."""
    q = spec.resolve(m251)
    for k in (0, 1, 2):
        m = _idle(m251, k)
        i_a = (m["bplus"] - m["a"]) / q["r10_ohm"]
        assert i_a == pytest.approx(0.62e-3, rel=0.1)
        assert m["k"] == pytest.approx(i_a * q["r11_ohm"], rel=0.05)
        assert m["bp"] == pytest.approx(q["pol_front_v"], rel=0.02)
        assert m["bp"] - m["rd"] == pytest.approx(q[POL[k]], abs=0.02 * q["pol_front_v"])


def test_sensitivity_and_front_to_back(m251):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.devices.library import component_data
    from varimu.measure import metrics
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    g = component_data(spec.resolve(m251)["capsule_model"])["geometry"]
    t = np.arange(int(0.5 * fs)) / fs

    def level(pattern, f0, angle_deg):
        p = np.sqrt(2) * np.sin(2 * np.pi * f0 * t) * np.minimum(1, t / 0.05)
        front, rear, _ = capsule_entry_pressures(g, p, np.radians(angle_deg), fs)
        ir = builder.build(m251, {"pattern": pattern}).ir
        v = fast.run_transient(ir, front, settings=s, controls={"p_rear": rear}).vectors
        return metrics.harmonics(v["v(out)"][-fs // 5 :], f0, fs).amps[0] / np.sqrt(2)

    for pattern in (0, 1, 2):
        assert 20 * np.log10(level(pattern, 1000.0, 0) / 10e-3) == pytest.approx(0.0, abs=2.0)
    assert 20 * np.log10(level(1, 1000.0, 0) / level(1, 1000.0, 180)) > 20.0
    eight = 20 * np.log10(level(2, 1000.0, 0) / level(2, 1000.0, 90))
    assert eight > 15.0

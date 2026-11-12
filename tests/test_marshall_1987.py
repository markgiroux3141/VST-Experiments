"""The Marshall 1987 Lead 50 W (config/circuits/marshall_1987.yaml): every value sourced, the
pre-flight checks at every input, the bias settled from the first sample, and the idle near
the only published voltage chart (data/schematics/marshall_1987/README.md "Published
voltages": a 1959 Mark II 100 W's, whose preamp and inverter are this circuit on another
supply, so the preamp's plates within +-25%; the EL34s at the default bias near 2/3 of
their rating).
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

PLEXI = CONFIG_DIR / "circuits" / "marshall_1987.yaml"

# The chart's preamp plates (V1 pins 1 / 6, V2 pin 1, V3 pins 1 / 6).
CHART_V = {"p1n": 135.0, "p1b": 195.0, "p2a": 153.0, "pa3": 210.0, "pb3": 195.0}


@pytest.fixture(scope="module")
def plexi():
    return spec.load_circuit(PLEXI)


def test_builds_and_every_value_is_sourced(plexi):
    assert spec.check_genome_links(plexi) == []
    assert plexi.full_scale == (1.0, 100.0)
    builder.build(plexi)


def test_preflight_passes_at_every_input(plexi):
    assert preflight.check_circuit(plexi) == []
    assert len(preflight.switch_configs(plexi)) == 5


def test_idles_settled_near_the_chart(plexi):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    x = np.zeros(int(0.5 * st.sample_rate))
    vec = fast.run_transient(builder.build(plexi).ir, x, settings=st).vectors
    n = int(0.05 * st.sample_rate)
    early = {k[2:-1]: float(np.mean(a[:n])) for k, a in vec.items() if k.startswith("v(")}
    late = {k[2:-1]: float(np.mean(a[-n:])) for k, a in vec.items() if k.startswith("v(")}
    # The bias starts settled (its capacitors' start voltages: measured 2026-11-12, -40.2 V).
    assert early["bias"] == pytest.approx(late["bias"], abs=0.1)
    assert late["bias"] == pytest.approx(-40.2, abs=1.0)
    for node, v in CHART_V.items():
        assert late[node] == pytest.approx(v, rel=0.25), node
    # Each EL34 at the default bias: ~37 mA at ~447 V (the OT half's DC drop over 42.4 ohm).
    ia = (late["b1"] - late["p4"]) / 42.4
    assert 0.030 < ia < 0.045, ia
    assert ia * late["p4"] < 25.0 * 0.75

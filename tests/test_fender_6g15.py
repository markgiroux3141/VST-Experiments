"""The Fender 6G15 Reverb (docs/REVERB_PLAN.md, E4): config/circuits/fender_6g15.yaml.

It builds from the generic format with its tank (ACC4AB3C1B@1) and its 6K6GT, passes the
pre-flight checks, and idles within the drawing's stated +-20% of its printed voltages.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.circuit.ir import Spring
from varimu.config import CONFIG_DIR

REVERB = CONFIG_DIR / "circuits" / "fender_6g15.yaml"

# Printed on schematic 6G15 H-FA ("values shown + or - 20%").
DRAWING_V = {"b1": 300.0, "b2": 295.0, "b3": 250.0, "p1a": 105.0, "k1a": 1.8, "p1b": 120.0,
             "k1b": 2.0, "p6": 285.0, "k6": 24.0, "p3a": 160.0, "k3a": 1.2, "g3b": 120.0,
             "k3b": 130.0}  # fmt: skip


@pytest.fixture(scope="module")
def reverb():
    return spec.load_circuit(REVERB)


def test_builds_with_its_tank_and_every_value_is_sourced(reverb):
    c = builder.build(reverb)
    springs = [e for e in c.ir.elements() if isinstance(e, Spring)]
    assert len(springs) == 1 and len(springs[0].springs) == 2
    assert c.text is None  # JA cores: no SPICE text
    lin = builder.build(reverb, cores="linear")
    # SPICE cuts the tank out at its ports: its EMF held at 0 V.
    assert "VSP sp_e 0 dc 0" in lin.text
    assert spec.check_genome_links(reverb) == []
    assert reverb.full_scale == (1.0, 1.0)


def test_preflight_passes(reverb):
    assert preflight.check_circuit(reverb) == []


def test_idles_within_the_drawings_tolerance(reverb):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    x = np.zeros(int(0.5 * st.sample_rate))
    v = fast.run_transient(builder.build(reverb).ir, x, settings=st).vectors
    n = int(0.1 * st.sample_rate)
    for node, d in DRAWING_V.items():
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(d, rel=0.20), node
    # The supply, calibrated to the first filter capacitor's +300 V, within 3%.
    for node in ("b1", "b2", "b3"):
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(DRAWING_V[node], rel=0.03), node

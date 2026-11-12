"""The Fender 5F1 Champ (config/circuits/fender_5f1.yaml): every value sourced, the pre-flight
checks at both inputs, the feedback negative, and the idle within Fender's layout K-EE's +-20%
of its printed voltages (data/schematics/fender_5f1/README.md "Published voltages"; the
reproduction power transformer on its 275 V taps).
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

CHAMP = CONFIG_DIR / "circuits" / "fender_5f1.yaml"

# Fender's layout (+-20 %): B+1 / B+2 / B+3, the 6V6's cathode, both 12AX7 plates and cathodes.
LAY_V = {"b1": 340.0, "b2": 295.0, "b3": 250.0, "k6": 18.0, "p1a": 150.0, "p1b": 150.0,
         "k1a": 1.5, "k1b": 1.5}  # fmt: skip


@pytest.fixture(scope="module")
def champ():
    return spec.load_circuit(CHAMP)


def test_builds_and_every_value_is_sourced(champ):
    assert spec.check_genome_links(champ) == []
    assert champ.full_scale == (1.0, 30.0)
    builder.build(champ)


def test_preflight_passes_at_both_inputs(champ):
    assert preflight.check_circuit(champ) == []
    assert len(preflight.switch_configs(champ)) == 2


def _run(champ, x, **values):
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    ir = builder.build(champ, spec.resolve(champ, values)).ir
    return st.sample_rate, fast.run_transient(ir, x, settings=st).vectors


def test_idles_within_the_layouts_tolerance(champ):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    fs, v = _run(champ, np.zeros(48000))
    n = int(0.1 * fs)
    for node, d in LAY_V.items():
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(d, rel=0.20), node
    # The supply within 5% (the 275 V taps: 338 / 296 / 259 V measured 2026-11-12).
    for node in ("b1", "b2"):
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(LAY_V[node], rel=0.05), node


def test_the_feedback_is_negative(champ):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    t = np.arange(28800) / 96000.0
    x = 0.02 * np.sin(2 * np.pi * 1000 * t)

    def level(**values):
        fs, v = _run(champ, x, **values)
        s = v["v(spk)"][len(x) // 2 :]
        return float(np.sqrt(np.mean(s**2)))

    # Measured 2026-11-12: 0.33 V rms with the 22K, 0.61 V without (6 dB of feedback).
    assert level() < 0.7 * level(r_feedback_ohm=1e12)

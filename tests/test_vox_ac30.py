"""The Vox AC30/6 Top Boost (config/circuits/vox_ac30.yaml): every value sourced, the pre-flight
checks at both inputs, the idle near JMI's printed voltages (data/schematics/vox_ac30/
README.md: OS/065 and OS/010; the Top Boost's stage, its follower conducting grid current,
within 40%), and BASS and TREBLE turning the right way.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

AC30 = CONFIG_DIR / "circuits" / "vox_ac30.yaml"

# JMI's printed voltages: the 320 V rail, V1's node, V1's plate and cathode, the inverter's
# cathode, tail junction and plate, the EL84s' cathodes (+-10%).
PRINTED = {"b2": 320.0, "b4": 290.0, "p1b": 170.0, "k1": 1.6, "kt2": 56.5, "kj2": 55.0,
           "pa2": 230.0, "ka": 10.0}  # fmt: skip


@pytest.fixture(scope="module")
def ac30():
    return spec.load_circuit(AC30)


def test_builds_and_every_value_is_sourced(ac30):
    assert spec.check_genome_links(ac30) == []
    builder.build(ac30)


def test_preflight_passes_at_both_inputs(ac30):
    assert preflight.check_circuit(ac30) == []
    assert len(preflight.switch_configs(ac30)) == 2


def _run(ac30, x, **values):
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    ir = builder.build(ac30, spec.resolve(ac30, values)).ir
    return st.sample_rate, fast.run_transient(ir, x, settings=st).vectors


def test_idles_near_the_printed_voltages(ac30):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    fs, v = _run(ac30, np.zeros(48000))
    n = int(0.1 * fs)
    mean = {k[2:-1]: float(np.mean(a[-n:])) for k, a in v.items() if k.startswith("v(")}
    for node, d in PRINTED.items():
        assert mean[node] == pytest.approx(d, rel=0.10), node
    # The Top Boost: plate 180 V, cathode 1.65 V, follower 180 V printed (TB65).
    for node, d in {"ptb": 180.0, "kcf": 180.0, "ktb": 1.65}.items():
        assert mean[node] == pytest.approx(d, rel=0.40), node


def test_tone_controls_turn_the_right_way(ac30):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

    def gain_db(f_hz, **values):
        t = np.arange(24000) / 96000.0
        x = 0.005 * np.sin(2 * np.pi * f_hz * t)
        _, v = _run(ac30, x, **values)
        y = v["v(mix)"][len(t) // 2 :]
        return 20 * np.log10(np.std(y))

    # Measured 2026-11-12: BASS 0 / 1 at 100 Hz 1.9 / 17.2 dB; TREBLE 0 / 1 at 5 kHz 22.2 / 34.7 dB.
    assert gain_db(100.0, bass=1.0) > gain_db(100.0, bass=0.0) + 10.0
    assert gain_db(5000.0, treble=1.0) > gain_db(5000.0, treble=0.0) + 8.0

"""The EMI REDD.47 (the chains build-out's WP28): config/circuits/emi_redd47.yaml, from EMI's
drawing REDD.47/C1/1 and its description REDD.M47 (data/schematics/emi_redd47/).

It builds, passes the pre-flight checks, idles near the drawing's printed voltages and currents
(V2 18 mA at 3.7 V and 138 V; V1's cathode 1.65 V and anode 73 V, +-20%: the EF86 fit runs ~12%
more current there), and gives REDD.M47's 34 / 40 / 46 dB into 200 ohm (VR1 trimmed for 40 at the
mid position by scripts/redd47_trim.py), +14 dBm with little distortion.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

REDD = CONFIG_DIR / "circuits" / "emi_redd47.yaml"


@pytest.fixture(scope="module")
def redd():
    return spec.load_circuit(REDD)


def test_builds_and_every_value_is_sourced(redd):
    for cores in ("ja", "linear"):
        assert not builder.build(redd, cores=cores).ir.controls
    assert spec.check_genome_links(redd) == []


def test_preflight_passes(redd):
    assert preflight.check_circuit(redd) == []


def test_idles_at_the_drawings_voltages(redd):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    ir = builder.build_ir(redd, spec.resolve(redd))
    v = fast.run_transient(ir, np.zeros(int(0.2 * s.sample_rate)), settings=s).vectors
    assert v["v(k2)"][-1] / 200.0 == pytest.approx(18e-3, rel=0.05)  # V2's 18 mA
    assert v["v(k2)"][-1] == pytest.approx(3.7, rel=0.06)
    assert v["v(a2)"][-1] == pytest.approx(138.0, rel=0.06)
    assert v["v(r205)"][-1] == pytest.approx(205.0, rel=0.02)
    assert v["v(k1)"][-1] == pytest.approx(1.65, rel=0.20)
    assert v["v(a1)"][-1] == pytest.approx(73.0, rel=0.20)


@pytest.fixture(scope="module")
def gain(redd):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.measure import metrics
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    t = np.arange(int(0.3 * fs)) / fs

    def f(over, vin_rms=1e-3, f0=1000.0):
        x = vin_rms * np.sqrt(2) * np.sin(2 * np.pi * f0 * t) * np.minimum(1, t / 0.05)
        v = fast.run_transient(builder.build(redd, over).ir, x, settings=s).vectors
        o = metrics.harmonics(v["v(out)"][-fs // 5 :], f0, fs)
        i = metrics.harmonics(v["v(ia)"][-fs // 5 :], f0, fs)
        # re the input terminals (REDD.M47's gain), and re the 200 ohm generator's EMF
        return 20 * np.log10(o.amps[0] / i.amps[0]), o.thd, 20 * np.log10(o.amps[0] / x.max())

    return f


def test_gain_steps(gain):
    for g in (34, 40, 46):
        db, _, _ = gain({"gain": g})
        assert db == pytest.approx(g, abs=0.6), g


def test_response_and_overload(gain):
    # flat from the generator's EMF (re the terminals the top rises: the input impedance falls
    # to ~1.4k at 15 kHz, the loading REDD.M47 describes)
    _, _, ref = gain({"gain": 40})
    for f0 in (40.0, 15000.0):
        _, _, db = gain({"gain": 40}, f0=f0)
        assert db - ref == pytest.approx(0.0, abs=1.0), f0
    # +14 dBm into 200 ohm: 2.18 V rms at the output
    _, thd, _ = gain({"gain": 40}, vin_rms=2.18 / 100.0)
    assert thd < 0.01

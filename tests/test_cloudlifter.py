"""The Cloudlifter CL-1 (the chains build-out's WP27): config/circuits/cloudlifter.yaml, from a
traced CL-1 schematic (data/schematics/cloudlifter/) on Linear Systems' LSK389A card, and the
three-stage chains scripts/compose_chain.py writes with it.

It builds and passes the pre-flight checks; the floating input holds the gates at +-v / 2; it idles
on the phantom feed with both legs alike; its gain is near Cloud's "up to +25 dB" into the clean
preamp's 10 kOhm and near the traced schematic's simulated 29.9 dB per output unloaded; and the
booster chains compose into one netlist (mic -> booster -> preamp).
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

CL = CONFIG_DIR / "circuits" / "cloudlifter.yaml"


@pytest.fixture(scope="module")
def cl():
    return spec.load_circuit(CL)


def test_builds_and_preflight(cl):
    builder.build(cl)
    assert spec.check_genome_links(cl) == []
    assert preflight.check_circuit(cl) == []


@pytest.fixture(scope="module")
def run(cl):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.measure import metrics
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    t = np.arange(int(0.4 * fs)) / fs

    def f(amp_v, over=None):
        x = amp_v * np.sin(2 * np.pi * 1000.0 * t) * np.minimum(1, t / 0.05)
        v = fast.run_transient(builder.build(cl, over or {}).ir, x, settings=s).vectors

        def a(node):
            return metrics.harmonics(v[f"v({node})"][-fs // 5 :], 1000.0, fs)

        return v, a

    return f


def test_idle_and_symmetry(run):
    v, a = run(0.001)
    # 48 V through 6.81k: ~1.4 mA a leg (the LSK389A at R1 + its share of R3)
    i_ma = (48.0 - v["v(dp)"][-1]) / 6.81
    assert 1.0 < i_ma < 2.0
    assert v["v(dp)"][-1] == pytest.approx(v["v(dn)"][-1], abs=0.01)
    assert a("dp").amps[0] == pytest.approx(a("dn").amps[0], rel=1e-3)


def test_gain(run):
    _, a = run(0.001)
    g = 20 * np.log10(a("out").amps[0] / a("ia").amps[0])
    assert g == pytest.approx(25.0, abs=2.5)  # web: Cloud, "up to +25 dB"
    # unloaded (the preamp's legs open): each output against the differential input, as the
    # traced schematic's simulation (29.9 dB)
    _, a = run(0.001, {"r_pre_leg_ohm": 1e9})
    g1 = 20 * np.log10(a("dp").amps[0] / a("ia").amps[0])
    assert g1 == pytest.approx(29.9, abs=2.0)


def test_booster_chains_build():
    for name in ("r44_cl_clean", "sm7_cl_clean"):
        c = spec.load_circuit(CONFIG_DIR / "circuits" / f"{name}.yaml")
        ir = builder.build(c).ir
        assert any(e.name.startswith("GD_cl") for e in ir.elements()), name

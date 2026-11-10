"""The AKG C414 B-ULS (the chains build-out's WP23), built by inference:
config/circuits/akg_c414.yaml (data/schematics/akg_c414/README.md; CHAINS_PLAN.md WP23).

It builds, passes the pre-flight checks at its four patterns and three pads, and meets AKG's
C414B/ULS sheet where it was fitted: 12.5 mV/Pa (cardioid, 1 kHz), 180 ohm, 0.5% THD at 140
dB SPL; the pads' -10 / -20 dB; the cardioid's and figure-8's nulls.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

C414 = CONFIG_DIR / "circuits" / "akg_c414.yaml"


@pytest.fixture(scope="module")
def c414():
    return spec.load_circuit(C414)


def test_builds_and_every_value_is_sourced(c414):
    for cores in ("ja", "linear"):
        assert [x.name for x in builder.build(c414, cores=cores).ir.controls] == ["p_rear"]
    assert spec.check_genome_links(c414) == []


def test_preflight_passes(c414):
    assert preflight.check_circuit(c414) == []


@pytest.fixture(scope="module")
def level(c414):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.devices.library import component_data
    from varimu.measure import metrics
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    g = component_data(spec.resolve(c414)["capsule_model"])["geometry"]
    t = np.arange(int(0.3 * fs)) / fs

    def f(over, pa_rms=1.0, angle_deg=0.0, f0=1000.0):
        p = pa_rms * np.sqrt(2) * np.sin(2 * np.pi * f0 * t) * np.minimum(1, t / 0.05)
        front, rear, _ = capsule_entry_pressures(g, p, np.radians(angle_deg), fs)
        ir = builder.build(c414, over).ir
        v = fast.run_transient(ir, front, settings=s, controls={"p_rear": rear}).vectors
        h = metrics.harmonics(v["v(out)"][-fs // 5 :], f0, fs)
        return h.amps[0] / np.sqrt(2), h.thd

    return f


def test_sensitivity_impedance_and_max_spl(level):
    card, _ = level({"pattern": 1})
    assert card * 1e3 == pytest.approx(12.5, abs=0.1)
    for pattern in (0, 2, 3):  # AKG: 12.5 mV/Pa at every pattern; the CK12@1's spread +-0.6 dB
        a, _ = level({"pattern": pattern})
        assert 20 * np.log10(a / card) == pytest.approx(0.0, abs=0.8)
    open_, _ = level({"pattern": 1, "r_load_ohm": 1e6})
    assert 1000 * (open_ / card - 1) == pytest.approx(180.0, abs=5.0)
    _, thd = level({"pattern": 1}, pa_rms=200.0)  # 140 dB SPL
    assert 100 * thd == pytest.approx(0.5, abs=0.05)


def test_pads_and_nulls(level):
    card, _ = level({"pattern": 1})
    for pad in (10, 20):
        a, _ = level({"pattern": 1, "pad": pad})
        assert 20 * np.log10(a / card) == pytest.approx(-pad, abs=0.3)
    back, _ = level({"pattern": 1}, angle_deg=180.0)
    assert 20 * np.log10(back / card) < -20.0
    eight, _ = level({"pattern": 3})
    side, _ = level({"pattern": 3}, angle_deg=90.0)
    assert 20 * np.log10(side / eight) < -30.0

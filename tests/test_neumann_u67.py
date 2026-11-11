"""The Neumann U 67 (the chains build-out's WP28): config/circuits/neumann_u67.yaml, from
Neumann's drawing 1020390101 and the 1966 specification sheets (data/schematics/neumann_u67/).

It builds, passes the pre-flight checks at every switch setting, idles at the drawing's printed
voltages, and the whole microphone meets the sheets: 1.1 / 2.0 / 1.4 mV/ub (11 / 20 / 14 mV/Pa)
across 1000 ohm, the preamplifier's -2.0 / 0 dB at the calibrating input (C_GA fitted to the
cardioid's), 200 ohm +-20%, <= 0.5% THD at 116 dB SPL, the pad about -10 dB.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

U67 = CONFIG_DIR / "circuits" / "neumann_u67.yaml"


@pytest.fixture(scope="module")
def u67():
    return spec.load_circuit(U67)


def test_builds_and_every_value_is_sourced(u67):
    for cores in ("ja", "linear"):
        ir = builder.build(u67, cores=cores).ir
        assert [x.name for x in ir.controls] == ["p_rear"]
    assert spec.check_genome_links(u67) == []


def test_preflight_passes(u67):
    assert preflight.check_circuit(u67) == []


def test_idles_at_the_drawings_voltages(u67):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    n = int(0.2 * s.sample_rate)
    z = np.zeros(n)
    ir = builder.build_ir(u67, spec.resolve(u67))
    v = fast.run_transient(ir, z, settings=s, controls={"p_rear": z}).vectors
    # sch's ovals: the anode "approx. +75 V" (the EF86 fit: 80.6), the grid -1.6..-1.8, the
    # backplate +59, the rear's line +120
    assert v["v(a)"][-1] == pytest.approx(75.0, rel=0.10)
    assert -1.8 <= v["v(g)"][-1] <= -1.6
    assert v["v(bp)"][-1] == pytest.approx(59.0, rel=0.02)
    assert v["v(y)"][-1] == pytest.approx(120.0, rel=0.02)


@pytest.fixture(scope="module")
def level(u67):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.devices.library import component_data
    from varimu.measure import metrics
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    g = component_data(spec.resolve(u67)["capsule_model"])["geometry"]
    t = np.arange(int(0.4 * fs)) / fs
    ramp = np.minimum(1, t / 0.05)

    def f(over, pa_rms=1.0, angle_deg=0.0, cal_rms=0.0):
        p = pa_rms * np.sqrt(2) * np.sin(2 * np.pi * 1000.0 * t) * ramp
        front, rear, _ = capsule_entry_pressures(g, p, np.radians(angle_deg), fs)
        if cal_rms:  # the calibrating input's sine at R20 (VCAL), the capsule silent
            front, rear = 0 * front, 0 * rear
            over = {**over, "cal_v": cal_rms * np.sqrt(2)}
        v = fast.run_transient(
            builder.build(u67, over).ir, front, settings=s, controls={"p_rear": rear}
        )
        h = metrics.harmonics(v.vectors["v(out)"][-fs // 5 :], 1000.0, fs)
        return h.amps[0] / np.sqrt(2), h.thd

    return f


def test_sensitivity_per_pattern(level):
    for pattern, want_mv in ((0, 11.0), (1, 20.0), (2, 14.0)):
        a, _ = level({"pattern": pattern})
        assert 20 * np.log10(a * 1e3 / want_mv) == pytest.approx(0.0, abs=1.0), pattern


def test_preamplifier_gain_at_the_calibrating_input(level):
    for pattern, want_db in ((0, 0.0), (1, -2.0)):
        a, _ = level({"pattern": pattern}, cal_rms=0.01)
        assert 20 * np.log10(a / 0.01) == pytest.approx(want_db, abs=0.3), pattern


def test_impedance_distortion_rear_and_pad(level):
    a, _ = level({"pattern": 1})
    b, _ = level({"pattern": 1, "r_load_ohm": 1e6})
    assert 160.0 <= 1000 * (b / a - 1) <= 240.0
    _, thd = level({"pattern": 1}, pa_rms=12.6)  # 116 dB SPL
    assert thd < 5e-3
    back, _ = level({"pattern": 1}, angle_deg=180.0)
    assert 20 * np.log10(back / a) < -18.0
    pad, _ = level({"pattern": 1, "pad": 1})
    assert -13.0 < 20 * np.log10(pad / a) < -9.0

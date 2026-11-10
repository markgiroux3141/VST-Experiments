"""The Neumann U 47 fet (the chains build-out's WP25): config/circuits/neumann_u47_fet.yaml,
from Neumann's circuit diagram (data/schematics/neumann_u47_fet/README.md).

It builds, passes the pre-flight checks, idles at the drawing's printed voltages (+-5%), and
the whole microphone meets Neumann's data: 8 mV/Pa into 1 kohm (fitted: Ü1's ratio), ~150 ohm,
< 0.5% THD at 137 dB SPL; the cardioid's rear; the pad ~-10 dB (S1 shorts C2: -9 dB).
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

U47F = CONFIG_DIR / "circuits" / "neumann_u47_fet.yaml"


@pytest.fixture(scope="module")
def u47f():
    return spec.load_circuit(U47F)


def test_builds_and_every_value_is_sourced(u47f):
    for cores in ("ja", "linear"):
        assert [x.name for x in builder.build(u47f, cores=cores).ir.controls] == ["p_rear"]
    assert spec.check_genome_links(u47f) == []


def test_preflight_passes(u47f):
    assert preflight.check_circuit(u47f) == []


def test_idles_at_the_drawings_voltages(u47f):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    n = int(0.2 * s.sample_rate)
    ir = builder.build_ir(u47f, spec.resolve(u47f))
    v = fast.run_transient(ir, np.zeros(n), settings=s, controls={"p_rear": np.zeros(n)}).vectors
    printed = {"a": 46.5, "p45": 45.0, "p43": 43.0, "nd": 22.4, "b": 21.5}
    for node, want in printed.items():
        assert v[f"v({node})"][-1] == pytest.approx(want, rel=0.05), node


@pytest.fixture(scope="module")
def level(u47f):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.devices.library import component_data
    from varimu.measure import metrics
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    g = component_data(spec.resolve(u47f)["capsule_model"])["geometry"]
    t = np.arange(int(0.3 * fs)) / fs

    def f(over, pa_rms=1.0, angle_deg=0.0):
        p = pa_rms * np.sqrt(2) * np.sin(2 * np.pi * 1000.0 * t) * np.minimum(1, t / 0.05)
        front, rear, _ = capsule_entry_pressures(g, p, np.radians(angle_deg), fs)
        v = fast.run_transient(
            builder.build(u47f, over).ir, front, settings=s, controls={"p_rear": rear}
        )
        h = metrics.harmonics(v.vectors["v(out)"][-fs // 5 :], 1000.0, fs)
        return h.amps[0] / np.sqrt(2), h.thd

    return f


def test_sensitivity_impedance_max_spl_and_pad(level):
    a, _ = level({})
    assert a * 1e3 == pytest.approx(8.0, abs=0.1)
    b, _ = level({"r_load_ohm": 1e6})
    assert 1000 * (b / a - 1) == pytest.approx(150.0, abs=10.0)
    _, thd = level({}, pa_rms=141.6)  # 137 dB SPL
    assert thd < 5e-3
    pad, _ = level({"pad": 1})
    assert 20 * np.log10(pad / a) == pytest.approx(-9.0, abs=0.5)
    back, _ = level({}, angle_deg=180.0)
    assert 20 * np.log10(back / a) < -15.0

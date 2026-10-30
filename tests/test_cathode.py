"""The cathode's temperature and what it does (device builder B6, the heater):
varimu.devices.cathode against Phywe's EC92 and the warm-up anchor."""

from __future__ import annotations

import json

import numpy as np
import pytest

from varimu.config import REPO_ROOT
from varimu.devices import cathode as ca
from varimu.devices.library import load_device

FIT = REPO_ROOT / "reports" / "devices" / "cathode_ec92.json"


def test_the_config_is_the_fit():
    """config/cathodes.yaml's fitted constants are scripts/fit_cathode.py's (rerun it and
    copy them after a change to the data or the model)."""
    ox, _ = ca.load_cathodes()
    f = json.loads(FIT.read_text(encoding="utf-8"))
    assert ox.phi_ev == pytest.approx(f["phi_ev"], abs=1e-3)
    assert ox.n == pytest.approx(f["n"], abs=1e-2)
    assert ox.emission_a_per_w == pytest.approx(f["is0_a"] / (6.3 * 0.150), rel=1e-3)
    assert ox.t0_k == f["t0_k"]
    # The fit: within the reading's +-0.3 mA, a work function inside oxide cathodes' range.
    assert f["rms_ma"] < 0.35
    assert 1.0 < f["phi_ev"] < 1.3
    # Fig. 5's retarding shift, an independent check: the model's is ~2/3 of the measured.
    for row in f["fig5_check"].values():
        if row["measured_v_re_150"]:
            assert 0.5 < row["model_v_re_150"] / row["measured_v_re_150"] < 1.0


def test_the_heater_holds_its_temperature_and_warms_in_seconds():
    ox, _ = ca.load_cathodes()
    c = ca.Cathode(6.3, 1.5 / 6.3, 1.0, ox.phi_ev, ox.n, tau_s=ox.tau_s)
    assert c.steady_k(volts=6.3) == pytest.approx(ox.t0_k, rel=1e-9)
    # 1% of heater voltage: 2 / (4 + alpha) % of temperature (~4 K).
    dt = c.steady_k(volts=6.3 * 1.01) - ox.t0_k
    assert dt == pytest.approx(ox.t0_k * 0.01 * 2 / (4 + ox.alpha), rel=0.02)
    # From cold, a 1.5 W cathode reaches 10% of a tube's current (at a 54x emission
    # reserve) in ~5.5 s: the anchor tau was set by.
    temps = c.warm(np.full(4000, 6.3), ox.t_amb_k, 0.005)
    frac = np.array([c.is_a(t) for t in temps]) / (c.is0_a / 54.0)
    t10 = (np.argmax(frac >= 0.1) + 1) * 0.005
    assert t10 == pytest.approx(5.5, abs=0.5)


def test_the_shift_and_the_ceiling():
    ox, tubes = ca.load_cathodes()
    is0 = ca.instance_is0_a(ox, tubes["12AX7"])
    c = ca.Cathode(1.0, 1.0, is0, ox.phi_ev, ox.n)
    assert c.shift_v(ox.t0_k, 1e-3) == 0.0
    assert ox.shift_t(ox.t0_k) == 0.0
    assert 1.5e-3 < ox.shift_t(ox.t0_k + 1) < 2.2e-3  # ~mV per K, the same for every tube
    # Hotter: a deeper potential minimum, the grid as if more positive (~mV per K).
    s = float(c.shift_v(ox.t0_k + 4.0, 1e-3))
    assert 4e-3 < s < 10e-3
    assert float(c.shift_v(ox.t0_k - 4.0, 1e-3)) < 0


def test_a_heated_tube_at_its_rated_temperature_is_its_model():
    ox, tubes = ca.load_cathodes()
    m = load_device("12AX7@1")
    is0 = ca.instance_is0_a(ox, tubes["12AX7"])

    def currents(v):  # ports (Vpk, Vgk)
        return [float(m.ip(v[1], v[0])), float(m.ig(v[1]))]

    for v in ([250.0, -1.5], [100.0, -0.5], [300.0, 0.5]):
        assert ca.heated(currents, v, 1, ox.t0_k, is0, ox) == pytest.approx(currents(v), rel=1e-12)
    # Cold: the emission ceiling; hot: more current (the shift).
    cold = ca.heated(currents, [250.0, -1.5], 1, 750.0, is0, ox)
    hot = ca.heated(currents, [250.0, -1.5], 1, ox.t0_k + 20, is0, ox)
    nominal = currents([250.0, -1.5])[0]
    assert cold[0] < 0.5 * nominal and hot[0] > nominal


def test_cathode_fixture_is_current():
    path = REPO_ROOT / "crates/circuitsim/tests/fixtures/cathode/cathode.json"
    assert path.read_text("utf-8") == ca.cathode_fixtures_json(), (
        "rerun scripts/export_circuit_fixtures.py"
    )


def test_a_heated_run():
    """The triode stage: warm at the rated heater equals the circuit unheated; from cold it is
    silent ~3 s, comes alive by ~6 s and creeps to its warm operating point over tens of
    seconds (the space-charge shift as the cathode's last kelvins come)."""
    pytest.importorskip("circuitsim")
    from varimu.circuit import builder, spec
    from varimu.sim import fast

    sp = spec.load_circuit(spec.circuit_path("triode_stage"))
    p = spec.resolve(sp)
    x = np.zeros(48000)
    plain = fast.run_transient(builder.build_ir(sp, p), x).vectors["v(p)"]
    warm = fast.run_transient(builder.build_ir(sp, p, heaters="warm"), x).vectors["v(p)"]
    assert np.max(np.abs(warm - plain)) < 1e-9
    cold = fast.run_transient(builder.build_ir(sp, p, heaters="cold"), np.zeros(96000 * 12))
    vp = cold.vectors["v(p)"]
    at = lambda s: vp[int(s * 96000)]  # noqa: E731
    assert at(2.0) > plain[-1] + 75  # no emission yet: the plate at B+
    assert at(11.9) < plain[-1] + 15  # alive, still creeping
    assert at(11.9) > plain[-1] + 1


def _ngspice():
    from varimu.sim import ngspice

    try:
        ngspice.find_ngspice()
    except ngspice.SimulatorNotFound:
        pytest.skip("ngspice not available")


def _both(start: str, ratio: float, seconds: float, tone: bool, reference: bool):
    import dataclasses

    from varimu.circuit import builder, spec, spice
    from varimu.sim import fast, io

    sp = spec.load_circuit(spec.circuit_path("triode_stage"))
    ir = builder.build_ir(sp, spec.resolve(sp), cores="linear", heaters=start)
    ir = dataclasses.replace(ir, heaters=dataclasses.replace(ir.heaters, heater_ratio=ratio))
    fs = 96000
    t = np.arange(int(seconds * fs)) / fs
    x = 0.3 * np.sin(2 * np.pi * 1000 * t) * np.minimum(t / 0.01, 1) if tone else 0 * t
    cs = fast.run_transient(ir, x).vectors["v(p)"]
    text, files = spice.emit(ir, triode_formulation="exact")
    s = io.TransientSettings.from_sim_settings(engine="ngspice")
    if start == "cold":
        s = dataclasses.replace(s, settle_s=0.0)
    ng = io.run_transient(
        text, x, input_node=ir.input_node, save=("v(p)",), settings=s, files=files,
        noise=spice.noise_streams(ir), max_step_div=8 if reference else 1,
        grid_breakpoints=reference,
    ).vectors["v(p)"]  # fmt: skip
    return cs, ng


def test_the_engines_agree_on_a_cooler_cathode():
    """The triode stage at a 90% heater (~40 K cool: the plate ~2 V higher), a tone through
    it, ngspice as a reference: measured -82.6 dB re signal, the same as unheated."""
    pytest.importorskip("circuitsim")
    _ngspice()
    cs, ng = _both("warm", 0.9, 0.05, tone=True, reference=True)
    assert abs(np.mean(cs) - np.mean(ng)) < 1e-3
    assert 20 * np.log10(np.std(cs - ng) / np.std(cs - np.mean(cs))) < -70


def test_the_engines_agree_on_a_cold_start():
    """5 s from cold (ngspice at its production settings): measured to the millivolt."""
    pytest.importorskip("circuitsim")
    _ngspice()
    cs, ng = _both("cold", 1.0, 5.0, tone=False, reference=False)
    assert np.max(np.abs(cs - ng)) < 0.01
    assert cs[-1] < cs[0] - 20  # alive by 5 s

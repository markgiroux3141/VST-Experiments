"""The incandescent lamp (varimu.devices.lamp; SYNTH_IDEAS.md #7): its component from the #327's
rating, the reference model's Jacobian, and circuitsim's transient (the thermal node's 1 F
capacitor integrating the device's dT/dt) against an ODE of the reference.

The SPICE subcircuit's agreement is tests/test_spice_agreement.py's test_lamp_agrees, the
compiled port's tests/devices.rs (fixtures from varimu.devices.fixtures)."""

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from varimu.circuit import builder, spec
from varimu.devices.lamp import T_MAX_K
from varimu.devices.library import load_device

LAMP = "LAMP327@1"


def test_component_holds_its_rating():
    lamp = load_device(LAMP)
    assert lamp.steady_k(28.0) == pytest.approx(2300.0, abs=1e-6)
    assert 28.0 / lamp.r_ohm(lamp.steady_k(28.0)) == pytest.approx(0.040, rel=1e-9)
    # ~56 ohm cold: a #327's filament is ~12x colder-resistive than hot at ~2300 K
    assert 50.0 < float(lamp.r_ohm(300.0)) < 62.0
    # the loss is radiation at the rating, conduction (the wire's ends) when dull
    assert lamp.steady_k(0.0) == 300.0


def test_jacobian_matches_finite_differences():
    lamp = load_device(LAMP)
    for v, u in [(0.0, 0.0), (1.0, 300.0), (-3.0, 900.0), (28.0, 2000.0), (0.5, -50.0)]:
        _, jac = lamp.eval(v, u)
        for j, (dv, du) in enumerate(((1e-6, 0.0), (0.0, 1e-4))):
            hi = lamp.currents(v + dv, u + du)
            lo = lamp.currents(v - dv, u - du)
            for i in range(2):
                fd = (hi[i] - lo[i]) / (2 * (dv + du))
                assert float(jac[i][j]) == pytest.approx(float(fd), rel=1e-6, abs=1e-9)


def test_beyond_the_fits_the_temperature_is_pulled_back():
    """Past T_MAX_K (a molten filament) the model holds the edge's values and restores the
    temperature, so a Newton iterate there isn't stuck (the thermal port keeps a slope)."""
    lamp = load_device(LAMP)
    (_, it), jac = lamp.eval(5.0, T_MAX_K + 100.0 - lamp.t_amb_k)
    (_, it_edge), _ = lamp.eval(5.0, T_MAX_K - lamp.t_amb_k)
    assert it == pytest.approx(it_edge + 100.0 * 100.0)
    assert float(jac[1][1]) == 100.0


CIRCUIT = """\
title: "lamp step"
input: in
probes: [lt, la]
values:
  r_feed: {value: 10.0, source: "provisional: test"}
  c_thermal: {value: 1.0, source: "numerical: the lamp's thermal node"}
devices:
  LP: {device: LAMP327@1}
sections:
  - title: lamp
    parts:
      RF: {R: [in, la], r: r_feed}
      XLP: {device: [la, lt, "0"], model: LP}
      CLT: {C: [lt, "0"], c: c_thermal}
"""


def test_circuitsim_transient_follows_the_heat_balance(tmp_path: Path):
    """20 V switched onto the lamp through 10 ohm and off again: circuitsim's filament
    temperature against scipy's ODE of the reference model."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast, io

    path = tmp_path / "lamp_step.yaml"
    path.write_text(CIRCUIT, encoding="utf-8")
    s = spec.load_circuit(path)
    ir = builder.build_ir(s, spec.resolve(s, {}), cores="ja")
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim"),
        full_scale_volts_peak=1.0,
        settle_s=0.0,
    )
    fs = st.sample_rate
    n_on, n_off, n = int(0.02 * fs), int(0.25 * fs), int(0.5 * fs)
    # Raised-cosine edges (5 ms): a hard step rings in production's 5th-order input
    # interpolation, which the ODE's linear input doesn't see.
    k = np.arange(n)
    ramp = int(0.005 * fs)
    up = np.clip((k - n_on) / ramp, 0, 1)
    down = np.clip((k - n_off) / ramp, 0, 1)
    x = 20.0 * 0.5 * ((1 - np.cos(np.pi * up)) - (1 - np.cos(np.pi * down)))
    v = fast.run_transient(ir, x, settings=st).vectors
    got = v["v(lt)"] + 300.0

    lamp = load_device(LAMP)
    r_feed = 10.0

    def vin(t):
        return float(np.interp(t * fs, np.arange(n), x))

    def rhs(t, y):
        r = float(lamp.r_ohm(lamp.t_amb_k + y[0]))
        vl = vin(t) * r / (r + r_feed)
        return [float(lamp.currents(vl, y[0])[1]) * -1.0]

    ts = np.arange(n) / fs
    sol = solve_ivp(
        rhs, (0, ts[-1]), [0.0], t_eval=ts, method="Radau", rtol=1e-9, atol=1e-6, max_step=1.0 / fs
    )
    want = sol.y[0] + 300.0
    # it heats to ~2040 K within the 0.23 s and cools to ~1120 K in the next 0.25 s
    assert want[n_off - 1] > 1500.0 and want[-1] < 1300.0
    np.testing.assert_allclose(got, want, rtol=0, atol=0.05)

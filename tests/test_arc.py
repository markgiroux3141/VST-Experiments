"""The carbon arc (varimu.devices.arc; docs/INVENTED_LIVE_PLAN.md IL7): the reference's static
curve is Ayrton's law, its Jacobian, and circuitsim's singing arc (config/circuits/arc_test.yaml:
Duddell's, one condenser).

The SPICE subcircuit's agreement is tests/test_spice_agreement.py's test_arc_agrees, the
compiled port's tests/devices.rs (fixtures from varimu.devices.fixtures)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from varimu.devices import arc as arc_mod
from varimu.devices.library import load_device

ARC = "CARBON_ARC@1"


@pytest.mark.parametrize("gap_mm", [1.0, 2.0, 4.0])
def test_the_static_curve_is_ayrtons_law(gap_mm: float):
    """Burning steadily (d ln g / dt = 0) at any current, the arc's voltage is Ayrton's
    a + b l + (c + d l) / I (up to the smoothing of |i| at a milliampere)."""
    a = dataclasses.replace(load_device(ARC), gap_mm=gap_mm)
    for i_a in (2.0, 5.0, 9.0):
        v = float(a.static_v(i_a))
        assert v == pytest.approx(
            38.88 + 2.074 * gap_mm + (11.66 + 10.54 * gap_mm) / i_a, rel=1e-12
        )
        ia, i_s, i_w = a.currents(v, a.steady_ln_g(i_a))
        assert float(ia) == pytest.approx(i_a, rel=1e-12)
        assert abs(float(i_s)) < 1e-2  # vs 1 / tau = 3.3e4 per second
        assert float(i_w) == pytest.approx(-v * i_a, rel=1e-12)  # the power, out of w


def test_the_jacobian_matches_finite_differences():
    a = load_device(ARC)
    for v in (-60.0, -3.0, 0.5, 30.0, 49.6, 72.0, 77.5):
        for u in (-8.0, -5.0, -2.3, 0.5, 1.9):
            _, jac = a.eval(v, u)
            for j, (dv, du) in enumerate(((1e-6, 0.0), (0.0, 1e-7))):
                hi = a.currents(v + dv, u + du)
                lo = a.currents(v - dv, u - du)
                for i in range(3):
                    fd = (float(hi[i]) - float(lo[i])) / (2 * (dv + du))
                    assert float(jac[i][j]) == pytest.approx(fd, rel=1e-5, abs=1e-3)


def test_past_the_floor_the_state_is_pulled_back():
    """Below the hot carbons' residual conductance the model holds the floor's values and
    restores the state (the port keeps a slope)."""
    a = load_device(ARC)
    lo = math.log(a.g_floor_s)
    (_, i_s, _), jac = a.eval(10.0, lo - 0.5)
    (_, i_edge, _), _ = a.eval(10.0, lo)
    assert float(i_s) == pytest.approx(float(i_edge) - 0.5 * arc_mod.G_EXT_PER_S)
    assert float(jac[1][1]) == arc_mod.G_EXT_PER_S


def _sing(values: dict, seconds: float = 0.6):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.circuit import builder, spec
    from varimu.sim import fast, io

    sp = spec.load_circuit(spec.circuit_path("arc_test"))
    ir = builder.build_ir(sp, spec.resolve(sp, values))
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    st = dataclasses.replace(st, full_scale_volts_peak=1.0, settle_s=0.0)
    fs = st.sample_rate
    v = fast.run_transient(ir, np.zeros(int(seconds * fs)), settings=st).vectors
    k = int(0.3 * fs)
    return fs, np.asarray(v["v(arc)"]), np.asarray(v["v(w)"])[k:], np.asarray(v["v(out)"])[k:]


def test_the_arc_sings():
    """Duddell's arc at 5 A on a 2 mm gap: it starts at Ayrton's voltage (the DC operating
    point on its static curve), and its negative resistance sustains the tank near the tank's
    own frequency (pulled flat by the arc: ~423 Hz against the LC's 456), loud as a thermophone
    (~0.27 Pa rms at 1 m)."""
    fs, arc, w, out = _sing({})
    assert arc[0] == pytest.approx(49.576, abs=0.01)
    assert np.ptp(w) > 300.0  # the power swings by hundreds of watts
    sp = np.abs(np.fft.rfft(out * np.hanning(out.size)))
    fr = np.fft.rfftfreq(out.size, 1 / fs)
    f0 = fr[np.argmax(sp * (fr > 50))]
    lc = 1 / (2 * math.pi * math.sqrt(4e-3 * 30.5e-6))
    assert 0.88 * lc < f0 < lc
    assert 0.15 < np.sqrt(np.mean(out**2)) < 0.5


def test_a_lossy_tank_never_starts():
    """The arc's small-signal resistance at 5 A is -1.31 ohm (the sketch's finding): a tank
    with more resistance than that stays silent (SPEAK's far end)."""
    _, _, w, out = _sing({"tank_ohm": 2.0})
    assert np.ptp(w) < 1.0
    assert np.sqrt(np.mean(out**2)) < 1e-3

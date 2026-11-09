"""The lamp-lit CdS photocell (varimu/devices/photocell.py): its component is the fit, the fit
meets the sheet, its Jacobian is the derivative, its closed-form response the ODE's, and its
light follows the filament's temperature as Wien's law says."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from varimu.devices.library import load_device
from varimu.devices.photocell import (
    C2_M_K,
    T_REF_K,
    fit_pdvp9203,
    photocell_from_data,
)


def _cell(lux=40.0):
    return dataclasses.replace(load_device("PDVP9203@1"), lux=lux)


def test_the_component_is_the_fit():
    import yaml

    from varimu.devices import versions

    _, text = versions.read_text("PDVP9203@1")
    saved = yaml.safe_load(text)
    assert photocell_from_data(saved, "PDVP9203@1") == photocell_from_data(fit_pdvp9203(), "x")


def test_the_fit_meets_the_sheet():
    """10-30 kOhm at 10 lux, a sensitivity of 0.90 between 10 and 100 lux, and response times
    within the sheet's 25-60 ms (one state: the two come out alike)."""
    d = load_device("PDVP9203@1")
    r10, r100 = float(d.steady_r_ohm(10.0)), float(d.steady_r_ohm(100.0))
    assert 10e3 <= r10 <= 30e3
    # The fit trades the sensitivity against the response times (0.95 for the sheet's 0.90).
    assert math.log10(r10 / r100) == pytest.approx(0.90, abs=0.06)
    for t in (d.rise_s(10.0), d.fall_s(10.0)):
        assert 25e-3 <= t <= 60e-3
    assert float(d.steady_r_ohm(0.0)) == pytest.approx(5e6)


def test_the_light_is_wiens_law():
    """`lux` at 2856 K; at another temperature the ratio exp(c2 / lambda (1/T_ref - 1/T));
    below the floor, dark."""
    d = _cell(10.0)
    e_ref, _ = d.illuminance(T_REF_K - d.t_amb_k)
    assert float(e_ref) == pytest.approx(10.0)
    t = 2300.0
    e, _ = d.illuminance(t - d.t_amb_k)
    want = 10.0 * math.exp(C2_M_K / d.lambda_m * (1.0 / T_REF_K - 1.0 / t))
    assert float(e) == pytest.approx(want)
    assert 0.08 < float(e) / 10.0 < 0.2  # a filament at ~2300 K: a tenth of illuminant A's
    assert float(d.illuminance(-250.0)[0]) < 1e-30


def test_jacobian_matches_finite_differences():
    d = _cell()
    for v in [
        (2000.0, 0.0, 3e3, 2.0),
        (2521.0, 21.0, 2e4, -3.0),
        (921.0, 21.0, 0.01, 0.4),
        (1500.0, -5.0, 5e4, 9.0),
    ]:
        _, j = d.eval(v)
        for k in range(4):
            # The thermal ports in kelvin: a millikelvin is well inside the curvature of
            # exp(-c2 / lambda T) and well above the state current's roundoff.
            h = 1e-3 if k < 2 else 1e-7 * max(abs(v[k]), 1e-3)
            lo, hi = list(v), list(v)
            lo[k] -= h
            hi[k] += h
            fd = (d.currents(hi) - d.currents(lo)) / (2 * h)
            np.testing.assert_allclose(j[:, k], fd, rtol=1e-5, atol=1e-12)


def test_the_closed_form_response_is_the_ode():
    d = load_device("PDVP9203@1")
    t = np.linspace(1e-4, 0.2, 40)
    for lux, g0 in ((100.0, 0.0), (10.0, 0.0), (0.0, float(d.steady_g(10.0)))):
        sol = solve_ivp(
            lambda _t, g, lux=lux: [d.rate(g[0], lux)],
            (0, t[-1]),
            [g0],
            t_eval=t,
            rtol=1e-10,
            atol=1e-14,
            method="LSODA",
        )
        np.testing.assert_allclose(d.conductance_response(lux, g0, t), sol.y[0], rtol=1e-6)


def test_the_lamp_drives_the_cell_to_its_steady_state():
    """At the device's ports: the state at its steady value for the filament's light, the
    state current zero, the cell conducting 1 / steady_r_ohm; the sensing pins draw nothing."""
    d = _cell(40.0)
    for t_k in (1800.0, 2300.0, 2856.0):
        e = float(d.illuminance(t_k - d.t_amb_k)[0])
        u = float(d.steady_g(e)) / d.s_unit_s
        i = d.currents((t_k - d.t_amb_k + 21.0, 21.0, u, 1.0))
        assert i[0] == 0.0 and i[1] == 0.0
        assert abs(i[2]) < 1e-9 * u
        assert i[3] == pytest.approx(1.0 / float(d.steady_r_ohm(e)))

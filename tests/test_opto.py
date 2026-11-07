"""The LED / photocell optocoupler (varimu/devices/opto.py): its component is the fit, its
Jacobian the derivative, its closed-form response the ODE's, its device the steady state."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from varimu.devices.library import load_device
from varimu.devices.opto import fit_vactrol, fit_vtl5c1, opto_from_data


@pytest.mark.parametrize("part", ["VTL5C1", "VTL5C2"])
def test_the_component_is_the_fit(part):
    import yaml

    from varimu.devices import versions

    _, text = versions.read_text(f"{part}@1")
    saved = yaml.safe_load(text)
    fresh = fit_vactrol(part)
    assert opto_from_data(saved, f"{part}@1") == opto_from_data(fresh, part)


def test_the_slow_cell_darkens_slowly():
    """The VTL5C2 (the Suitcase's stand-in): its sheet's turn-off from 40 mA to 10 kOhm in
    ~80 ms and to 100 kOhm in ~190 ms (500 max.), the VTL5C1's in ~12 / ~21 ms; its fit within
    ~15% on the turn-off curves."""
    fit = fit_vactrol("VTL5C2")["fit"]
    assert fit["rms_log_r_response"]["off_40mA"] < 0.15
    assert fit["rms_log_r_response"]["off_10mA"] < 0.15
    t = np.array([0.08, 0.19])
    for part, want in (("VTL5C2@1", (1e4, 1e5)), ("VTL5C1@1", None)):
        d = load_device(part)
        r = d.response(0.0, float(d.steady_g(40e-3)), t)
        if want is None:
            assert r[0] > 1e6  # the fast cell is long dark by then
        else:
            np.testing.assert_allclose(np.log(r), np.log(want), atol=np.log(1.4))


def test_the_fit_meets_the_sheet():
    """Light adapted, steady: within ~25% rms (ln R 0.23); the response curves within ~45%
    but the dim turn-on's first millisecond (one state: no trap filling)."""
    fit = fit_vtl5c1()["fit"]
    assert fit["rms_log_r_steady"] < 0.3
    for name in ("on_40mA", "off_40mA", "off_10mA"):
        assert fit["rms_log_r_response"][name] < 0.4, name


def test_jacobian_matches_finite_differences():
    d = load_device("VTL5C1@1")
    for v in [(1.5, 0.0, 0.3, 2.0), (6.6, 5.0, 2.0, -3.0), (0.2, 0.5, 0.01, 0.4), (1.45, 0, 4, 9)]:
        _, j = d.eval(v)
        for k in range(4):
            h = 1e-7 * max(abs(v[k]), 1e-3)
            lo, hi = list(v), list(v)
            lo[k] -= h
            hi[k] += h
            fd = (d.currents(hi) - d.currents(lo)) / (2 * h)
            np.testing.assert_allclose(j[:, k], fd, rtol=1e-5, atol=1e-12)


def test_the_closed_form_response_is_the_ode():
    d = load_device("VTL5C1@1")
    t = np.linspace(1e-4, 0.03, 40)
    for i_a, g0 in ((40e-3, 0.0), (10e-3, 0.0), (0.0, float(d.steady_g(10e-3)))):
        lum = float(d.light(i_a)[0])
        sol = solve_ivp(
            lambda _t, g, lum=lum: [d.rate(g[0], lum)],
            (0, t[-1]),
            [g0],
            t_eval=t,
            rtol=1e-10,
            atol=1e-14,
            method="LSODA",
        )
        want = 1.0 / (d.g_dark_s + np.maximum(sol.y[0], 0.0))
        np.testing.assert_allclose(d.response(i_a, g0, t), want, rtol=1e-6)


def test_the_led_drives_the_cell_to_its_steady_state():
    """At the device's ports: with the state node at its steady value the state current is
    zero and the cell conducts 1 / steady_r_ohm."""
    d = load_device("VTL5C1@1")
    for vled in (1.45, 1.52, 1.58):
        il = float(d.led(vled)[0])
        u = float(d.steady_g(il)) / d.s_unit_s
        i = d.currents((vled, 0.0, u, 1.0))
        assert i[0] == pytest.approx(il)
        assert abs(i[2]) < 1e-9 * (1.0 / d.tau0_s) * max(u, 1e-6)
        assert i[3] == pytest.approx(1.0 / float(d.steady_r_ohm(il)))

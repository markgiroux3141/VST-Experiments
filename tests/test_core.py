"""The Jiles-Atherton core model (varimu.devices.core), on its own.

- The inverse map H(B) agrees with the JA model driven by H (forward
  integration of dM/dH, reversals located exactly).
- Loops look like loops: width, coercivity sign, saturation; the map is
  rate-independent (H depends on the path of B, not on how densely it is
  sampled).
- The linear limit is the small-signal slope at the demagnetized origin.
"""

import math

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from varimu.devices.core import (
    DEMAGNETIZED,
    MU0,
    TESLA_PER_V,
    MagneticCore,
    core_model,
    materials,
)

# A wide-loop literature set (Jiles & Atherton 1986, via Holters & Zoelzer, DAFx-16,
# Table 1; c converted to the 1992 form): exercises the irreversible term hard.
JA1986 = MagneticCore("JA1986", 1.6e6, 1100.0, 400.0, 0.17, 1.6e-3, 0.1)


def cores():
    return [core_model(n, n, 0.1) for n in materials()] + [JA1986]


def test_materials_are_sourced_and_valid():
    for name, m in materials().items():
        assert m["source"].strip(), name
        c = core_model(name, name, 0.1)
        assert c.validate() == [], (name, c.validate())
        # Saturation flux density mu0 Ms of a soft magnetic material: 0.5..2.2 T.
        assert 0.5 < MU0 * c.ms_a_per_m < 2.2, name


@pytest.mark.parametrize("core", cores(), ids=lambda c: c.name)
def test_inverse_map_agrees_with_the_forward_model(core):
    """Drive H = 3a sin(2 pi t) through two periods; integrate dM/dH between the
    reversals; feed the resulting B back through the inverse map."""
    h_pk = 3 * core.a_a_per_m
    h_of_t = lambda t: h_pk * np.sin(2 * np.pi * t)  # noqa: E731
    dh_dt = lambda t: h_pk * 2 * np.pi * np.cos(2 * np.pi * t)  # noqa: E731
    t = np.linspace(0, 2, 20001)
    m = np.zeros_like(t)
    m0 = 0.0
    for t0, t1 in [(0, 0.25), (0.25, 0.75), (0.75, 1.25), (1.25, 1.75), (1.75, 2.0)]:
        delta = float(np.sign(dh_dt(0.5 * (t0 + t1))))

        def rhs(tt, y, delta=delta):
            return [core.susceptibility(h_of_t(tt), y[0], delta) * dh_dt(tt)]

        sol = solve_ivp(rhs, (t0, t1), [m0], method="DOP853", rtol=1e-12, atol=1e-6,
                        dense_output=True)  # fmt: skip
        sel = (t >= t0) & (t <= t1)
        m[sel] = sol.sol(t[sel])[0]
        m0 = sol.y[0, -1]
    h_inv = np.array(core.trace(MU0 * (h_of_t(t) + m)))
    err = np.max(np.abs(h_inv - h_of_t(t))) / h_pk
    print(f"{core.name}: max H error {err:.1e} of the peak")
    # Measured 2026-10-21: 2e-9 .. 5e-8; mumetall 4e-6 (its H is ~1e-5 of B / mu0, so
    # the forward solve's tolerance on M shows).
    assert err < 2e-5


@pytest.mark.parametrize("core", cores(), ids=lambda c: c.name)
def test_loops_have_width_and_saturate(core):
    b_pk = 0.99 * MU0 * core.ms_a_per_m  # deep into saturation
    t = np.linspace(0, 3, 6001)
    b = b_pk * np.sin(2 * np.pi * t) * np.minimum(1, t)
    h = np.array(core.trace(b))
    last = t >= 2
    # On the last period, at B = 0: H > 0 coming up, < 0 going down (coercivity).
    tb, hb, bb = t[last], h[last], b[last]
    up = [hb[i] for i in range(1, len(tb)) if bb[i - 1] < 0 <= bb[i]]
    down = [hb[i] for i in range(1, len(tb)) if bb[i - 1] > 0 >= bb[i]]
    assert up and down and min(up) > 0 > max(down), (up, down)
    # Loop area (hysteresis loss per cycle, J/m^3) is positive.
    area = -np.trapezoid(bb, hb)
    assert area > 0
    # Saturation: at the peak, going on up, the incremental permeability nears mu0.
    state = DEMAGNETIZED
    for x in b[: np.argmax(b) + 1]:
        state = core.advance(float(x), state)
    _, dh = core.h_of_b(state.b + 1e-4, state)
    # (mumetall: 85 at 0.99 Ms, against 250000 at its maximum)
    assert 1 / (MU0 * dh) < 200, (core.name, 1 / (MU0 * dh))


@pytest.mark.parametrize("core", cores(), ids=lambda c: c.name)
def test_the_map_is_rate_independent(core):
    """A B path (30 Hz into saturation, sampled at 192 kHz as a transient at 2x sees
    it) taken in the map's steps, and the same path cut into 50x finer pieces: H
    agrees within 3e-6 of its peak-to-peak (measured 2026-10-21: 1e-6 for mumetall).
    (A sine sampled 50x denser is another path: it reaches higher at every peak, by
    ~1e-8 T, and on mumetall's sharp knee that moves H by 2.4e-4 of its peak-to-peak:
    the material's sensitivity, not the map's error.)"""
    b_pk = 0.9 * MU0 * core.ms_a_per_m
    t = np.arange(0, 2 / 30, 1 / 192000)
    b = b_pk * np.sin(2 * np.pi * 30 * t) * np.minimum(1, t * 30)
    coarse = np.array(core.trace(b))
    pieces = [np.linspace(b[i], b[i + 1], 51)[:-1] for i in range(len(b) - 1)]
    fine = np.array(core.trace(np.concatenate([*pieces, b[-1:]])))[::50]
    err = np.max(np.abs(coarse - fine)) / np.ptp(fine)
    assert err < 3e-6, err


@pytest.mark.parametrize("core", cores(), ids=lambda c: c.name)
def test_linear_limit_is_the_small_signal_slope(core):
    # 10 pT: mumetall's Rayleigh region (the irreversible term) starts below 1 uT.
    i, g = core.port_current(1e-8, DEMAGNETIZED)
    assert math.isclose(g, core.linear_conductance(), rel_tol=1e-4)
    assert math.isclose(i, core.linear_conductance() * 1e-8, rel_tol=1e-4)
    assert TESLA_PER_V == 1e-3


def test_validation_rejects_a_divergent_parameter_set():
    bad = MagneticCore("bad", 1e6, 10.0, 5.0, 0.9, 1e-4, 0.1)  # alpha c Ms / 3a = 3
    assert any("diverges" in p for p in bad.validate())


def test_fitted_materials_meet_their_datasheet():
    """Materials with a `datasheet:` block were fitted to it (scripts/fit_core_material.py);
    the stored parameters still meet every figure within 3%."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import fit_core_material as fcm

    fitted = [n for n, m in materials().items() if "datasheet" in m]
    assert fitted
    for name in fitted:
        want, b_loss, _ = fcm.targets(name)
        got = fcm.figures(core_model(name, name, 0.1), b_loss)
        for k, v in want.items():
            assert abs(got[k] / v - 1) < 0.03, (name, k, got[k], v)

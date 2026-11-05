"""The permeable spherical shell's series (varimu.mics.permeable; SM57_PLAN.md SM8's check case)."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.devices.capsule import C_AIR, RHO_AIR
from varimu.mics import permeable
from varimu.mics.free_field import sphere_entry_factors


def test_a_transparent_shell_is_the_free_field():
    """zeta -> 0: the incident plane wave, e^{jkz}, inside and out."""
    f, a = 3000.0, 0.025
    k = 2 * np.pi * f / C_AIR
    r = np.array([0.0, 0.01, 0.02, 0.04, 0.05])
    th = np.array([0.0, 0.7, 1.9, 2.5, 3.1])
    p = permeable.field(f, a, 1e-9, r, th)
    assert np.allclose(p, np.exp(1j * k * r * np.cos(th)), atol=1e-9)


def test_an_impermeable_shell_is_the_rigid_sphere():
    """zeta -> infinity: silence inside, the rigid sphere's surface pressure outside (the
    exact series of free_field.sphere_entry_factors, at a pole with a tiny cap)."""
    a = 0.02
    for f in (500.0, 4000.0, 12000.0):
        p_in = permeable.field(f, a, 1e12, np.array([0.005]), np.array([0.3]))
        assert abs(p_in[0]) < 1e-6
        p_out = permeable.field(f, a, 1e12, np.array([a * (1 + 1e-9)]), np.array([0.0]))
        front, _ = sphere_entry_factors(np.array([f]), 0.0, a, 1e-5)
        assert p_out[0] == pytest.approx(front[0], rel=1e-5)


def test_low_frequency_inside_is_an_rc():
    """At low frequency the inside is the shell's air filled through the sheet: A_0 = 1 / (1 +
    j w R C), R = Z_s / (4 pi a^2), C = (4/3) pi a^3 / (rho c^2)."""
    a, z_s, f = 0.025, 400.0, 20.0
    w = 2 * np.pi * f
    rc = (z_s / (4 * np.pi * a * a)) * (4 / 3 * np.pi * a**3 / (RHO_AIR * C_AIR**2))
    p = permeable.field(f, a, z_s, np.array([0.0]), np.array([0.0]))[0]
    assert p == pytest.approx(1 / (1 + 1j * w * rc), rel=1e-3)

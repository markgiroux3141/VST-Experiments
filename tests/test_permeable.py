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


def _shell_mesh(a, n_sheet, core_m=0.0, n_core=0):
    from varimu.mics import bor_permeable as bp

    beta = np.linspace(0.0, np.pi, n_sheet + 1)
    sh = a * np.c_[np.sin(beta), np.cos(beta)]
    p0, p1, kind = [sh[:-1]], [sh[1:]], [np.full(n_sheet, bp.SHEET)]
    if core_m:
        cb = np.linspace(0.0, np.pi, n_core + 1)
        co = core_m * np.c_[np.sin(cb), np.cos(cb)]
        p0.append(co[:-1])
        p1.append(co[1:])
        kind.append(np.full(n_core, bp.RIGID_IN))
    chief = min(a, core_m or a) * np.array([[0.2, 0.3], [0.5, -0.1], [0.3, -0.55], [0.1, -0.2]])
    return bp.PermeableMesh(np.vstack(p0), np.vstack(p1), np.concatenate(kind), chief)


@pytest.mark.parametrize("core_m", [0.0, 0.012])
def test_bem_sheet_agrees_with_the_series(core_m):
    """bor_permeable's two-domain BEM against the exact series: a spherical sheet (with a
    rigid core inside), its outside and inside pressures (and the core's surface)."""
    from varimu.mics import bor_permeable as bp

    a = 0.025
    m = _shell_mesh(a, 80, core_m, 40)
    op = bp.operator(m)
    th = np.arctan2(m.mid[:, 0], m.mid[:, 1])
    sheet = m.kind == bp.SHEET
    for z_s, f in ((400.0, 3000.0), (2000.0, 8000.0)):
        p, v = bp.plane_wave_fields(op, f, z_s, np.array([0.0]))
        so = permeable.field(f, a, z_s, np.full(sheet.sum(), a * (1 + 1e-9)), th[sheet], core_m)
        si = permeable.field(f, a, z_s, np.full(sheet.sum(), a * (1 - 1e-9)), th[sheet], core_m)
        p_in = p[sheet, 0] + z_s * v[sheet, 0]
        assert np.max(abs(p[sheet, 0] - so)) < 2e-3 * np.max(abs(so))
        assert np.max(abs(p_in - si)) < 3e-3 * np.max(abs(si))
        if core_m:
            sc = permeable.field(f, a, z_s, np.full((~sheet).sum(), core_m * (1 + 1e-9)),
                                 th[~sheet], core_m)  # fmt: skip
            assert np.max(abs(p[~sheet, 0] - sc)) < 3e-3 * np.max(abs(sc))


def test_bem_rigid_body_alone_is_the_rigid_sphere():
    """RIGID_OUT panels alone: the rigid sphere (free_field's exact series at its pole)."""
    from varimu.mics import bor_permeable as bp

    a = 0.02
    beta = np.linspace(0.0, np.pi, 81)
    pts = a * np.c_[np.sin(beta), np.cos(beta)]
    m = bp.PermeableMesh(pts[:-1], pts[1:], np.full(80, bp.RIGID_OUT),
                         a * np.array([[0.2, 0.3], [0.5, -0.1], [0.3, -0.55]]))  # fmt: skip
    op = bp.operator(m)
    for f in (1000.0, 6000.0):
        p, _ = bp.plane_wave_fields(op, f, 0.0, np.array([0.0]))
        front, _ = sphere_entry_factors(np.array([f]), 0.0, a, 1e-5)
        assert p[0, 0] == pytest.approx(front[0], rel=5e-3)

"""The Rhodes pickup's 3D field (varimu/rhodes/pickup3d.py): the fields it is built from against
closed forms, and the flux linkage by reciprocity against the direct flux through the coil."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from varimu.rhodes import pickup3d as p3
from varimu.rhodes import spec


def test_a_uniformly_magnetized_cube_has_minus_a_third_inside():
    lo, hi = np.array([[-1.0, -1, -1]]), np.array([[1.0, 1, 1]])
    n = p3.cuboid_field(np.zeros((1, 3)), lo, hi)[0]
    assert n == pytest.approx(-np.eye(3) / 3, abs=1e-12)


def test_a_cube_far_away_is_a_dipole():
    lo, hi = np.array([[-1.0, -1, -1]]), np.array([[1.0, 1, 1]])
    r = np.array([12.0, 5.0, -3.0])
    h = p3.cuboid_field(r[None], lo, hi)[0][:, 0]
    m = np.array([8.0, 0.0, 0.0])  # the cube's volume times M = x
    dip = (3 * r * (m @ r) / (r @ r) ** 2.5 - m / (r @ r) ** 1.5) / (4 * np.pi)
    assert h == pytest.approx(dip, rel=2e-3, abs=1e-7)


def test_a_staircase_sphere_magnetizes_as_a_sphere():
    """A linear sphere in a uniform field: M = 3 chi / (chi + 3) H0 (chi 0.5, where a
    staircase of cubes is close)."""
    chi, n = 0.5, 11
    a = 2.0 / n
    c = (np.arange(n) + 0.5) * a - 1
    x, y, z = np.meshgrid(c, c, c, indexing="ij")
    keep = x**2 + y**2 + z**2 <= 1
    cen = np.stack([x[keep], y[keep], z[keep]], 1)
    k = len(cen)
    t = np.zeros((3 * k, 3 * k))
    for j in range(k):
        lo = np.repeat(cen[j : j + 1] - a / 2, k, 0)
        t[:, 3 * j : 3 * j + 3] = p3.cuboid_field(cen, lo, lo + a).reshape(3 * k, 3)
    m = np.linalg.solve(np.eye(3 * k) / chi - t, np.tile([1.0, 0, 0], k)).reshape(-1, 3)
    assert m[:, 0].mean() == pytest.approx(3 * chi / (chi + 3), rel=0.01)
    assert np.abs(m[:, 1:]).max() < 0.05  # the staircase corners: 0.023


def test_a_loop_on_its_axis():
    a, x = 4e-3, 3e-3
    h = p3.loop_field(np.array([[x, 0.0, 0.0]]), np.array([a]), np.array([0.0]), np.array([1.0]))
    assert h[0] == pytest.approx([a**2 / (2 * (a**2 + x**2) ** 1.5), 0, 0], abs=1e-9)


def test_reciprocity_equals_the_direct_flux_through_the_turns(monkeypatch):
    """The tine's share of the linkage, mu0 int M . h dV, against the flux of the tine's own
    field (B = mu0 H outside it) through each loop's disk, summed over the turns."""
    monkeypatch.setattr(p3, "COIL_LOOPS", (2, 3))
    p = replace(spec.key(49).pickup, field="3d")
    s = p3.Solver(p, 0.01, across=4)
    y = 1.2e-3
    want = s.linkage(y, 0.0)
    cen, m = s.magnetization(y, 0.0)
    lo = s.geo.cell_lo + np.array([0.0, y, 0.0])
    hi = s.geo.cell_hi + np.array([0.0, y, 0.0])
    g, w = np.polynomial.legendre.leggauss(24)
    th = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    direct = 0.0
    for r_l, x_l, n_l in zip(s.geo.loop_r, s.geo.loop_x, s.geo.loop_n, strict=True):
        rr = 0.5 * r_l * (g + 1)
        wr = 0.5 * r_l * w * rr  # r dr
        R, T = np.meshgrid(rr, th, indexing="ij")
        pts = np.stack([np.full(R.size, x_l), (R * np.cos(T)).ravel(), (R * np.sin(T)).ravel()], 1)
        hx = np.zeros(pts.shape[0])
        for j in range(cen.shape[0]):
            f = p3.cuboid_field(
                pts,
                np.repeat(lo[j : j + 1], pts.shape[0], 0),
                np.repeat(hi[j : j + 1], pts.shape[0], 0),
            )
            hx += f[:, 0, :] @ m[j]
        flux = p3.MU0 * np.sum(hx.reshape(R.shape) * wr[:, None]) * (2 * np.pi / th.size)
        direct += n_l * flux
    assert direct == pytest.approx(want, rel=2e-3)


def test_the_field_is_even_and_peaks_its_slope_a_few_mm_out():
    """The 3D map's shape (mk1's pickup): symmetric about the pole's axis, its slope's peak
    ~2.5 mm out (the 2D section's: ~3.1 mm), what the harmonics depend on."""
    p = replace(spec.key(49).pickup, field="3d")
    s = p3.Solver(p, 0.04)
    ys = np.linspace(0.0, 6e-3, 25)
    phi = np.array([s.linkage(y, 0.0) for y in ys])
    assert s.linkage(-1.5e-3, 0.0) == pytest.approx(s.linkage(1.5e-3, 0.0), rel=1e-9)
    slope = np.abs(np.gradient(phi, ys))
    assert 2.0e-3 <= ys[np.argmax(slope)] <= 3.0e-3
    assert phi[0] > 0 and np.all(np.diff(phi) < 0)

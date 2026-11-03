"""The body-of-revolution BEM for capsule entries (varimu/mics/bor.py; MIC_ROOM_PLAN.md A3)
against the rigid sphere's exact series (plane wave and point source, Duda & Martens) and
Lamb's thin disk (the low-frequency path 16 a / (5 pi), mode-weighted)."""

import numpy as np
import pytest

from varimu.devices.capsule import C_AIR
from varimu.mics import bor
from varimu.mics.free_field import sphere_entry_factors, sphere_point_factors

A, CAP = 0.011, 0.0095
F = np.array([50.0, 5000.0, 15600.0, 20000.0])  # 15.6 kHz: ka = pi, an interior resonance
TH = np.radians([0.0, 60.0, 135.0, 180.0])


@pytest.fixture(scope="module")
def sphere_op():
    return bor.operator(bor.sphere_mesh(A, CAP, 80))


def test_sphere_plane_wave(sphere_op):
    """Within 0.005 dB / 0.1 deg of the series at 80 panels (measured: <= 0.002 dB),
    CHIEF holding at ka = pi."""
    front, rear = bor.entry_factors(sphere_op, F, TH)
    for i, t in enumerate(TH):
        sf, sr = sphere_entry_factors(F, t, A, CAP)
        for got, ref in ((front[:, i], sf), (rear[:, i], sr)):
            assert np.max(np.abs(20 * np.log10(np.abs(got / ref)))) < 0.005
            assert np.max(np.abs(np.degrees(np.angle(got / ref)))) < 0.1


@pytest.mark.parametrize("distance_m", [0.05, 0.3])
def test_sphere_point_source(sphere_op, distance_m):
    front, rear = bor.entry_factors(sphere_op, F[:2], TH, distance_m)
    for i, t in enumerate(TH):
        sf, sr = sphere_point_factors(F[:2], t, A, CAP, distance_m)
        assert np.max(np.abs(20 * np.log10(np.abs(front[:, i] / sf)))) < 0.005
        assert np.max(np.abs(20 * np.log10(np.abs(rear[:, i] / sr)))) < 0.005


def test_point_series_tends_to_plane_wave():
    sf, sr = sphere_entry_factors(F, 0.7, A, CAP)
    pf, pr = sphere_point_factors(F, 0.7, A, CAP, 1e5)
    assert np.allclose(pf, sf, rtol=1e-4) and np.allclose(pr, sr, rtol=1e-4)


def test_thin_disk_low_frequency_path():
    """The path at 20 Hz for disks of thickness 2% and 5% of the radius, extrapolated
    linearly to zero thickness: Lamb's 16 a / (5 pi) = 1.019 a (measured 1.028 a)."""
    a = 0.0165
    k = 2 * np.pi * 20.0 / C_AIR
    paths = []
    for t_rel in (0.02, 0.05):
        body = dict(
            radius_m=a, rim_radius_m=a, rim_thickness_m=0.5 * t_rel * a,
            spacing_m=t_rel * a, ring_proud_m=0.0,
        )  # fmt: skip
        op = bor.operator(bor.capsule_mesh(body, 0.9999 * a, 0.6e-3))
        fr, rr = bor.entry_factors(op, [20.0], [0.0])
        paths.append(np.imag(fr[0, 0] - rr[0, 0]) / k / a)
    thin = paths[0] - (paths[1] - paths[0]) * 0.02 / 0.03
    assert thin == pytest.approx(16 / (5 * np.pi), rel=0.02)


def test_capsule_body_is_symmetric():
    """A body symmetric front to back: theta and pi - theta swap the entries; at 90 deg
    they are equal (to 1e-4: the CHIEF points aren't mirrored, so the least squares
    weighs the discretization error a little unevenly; measured <= 3e-5)."""
    body = dict(
        radius_m=14.9e-3, rim_radius_m=16.5e-3, rim_thickness_m=1.5e-3,
        spacing_m=5.75e-3, ring_proud_m=0.3e-3,
    )  # fmt: skip
    op = bor.operator(bor.capsule_mesh(body, 12.5e-3, 0.8e-3))
    front, rear = bor.entry_factors(op, [3000.0, 12000.0], np.radians([30.0, 150.0, 90.0]))
    assert np.allclose(front[:, 0], rear[:, 1], rtol=1e-4)
    assert np.allclose(front[:, 2], rear[:, 2], rtol=1e-4)

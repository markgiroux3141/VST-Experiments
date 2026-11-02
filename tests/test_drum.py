"""The two-headed drum (varimu/drums/drum.py; docs/DRUM_PLAN.md, D1)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from scipy import special

from varimu.drums import drum as dr
from varimu.drums import membrane as mb

FS = 96000


def small(f_max_hz: float = 700.0, **drum_changes) -> dr.Drum2:
    d2 = dr.load("tom_13")
    return dataclasses.replace(
        d2, drum=dataclasses.replace(d2.drum, f_max_hz=f_max_hz, **drum_changes)
    )


def zeros(head: mb.Head, f_max_hz: float, m: int) -> np.ndarray:
    md = mb.modes(head, f_max_hz)
    return md.j[md.m == m]


def test_a_piston_gets_its_added_mass():
    a, rho0 = 0.1651, 1.204
    assert dr.piston_mass_check(a, rho0) == pytest.approx(8 / 3 * rho0 * a**3, rel=1e-6)


def test_the_hankel_transform_is_the_radial_integral():
    a, m = 0.2, 2
    j = special.jn_zeros(m, 4)
    norm = np.ones(4)
    kappa = np.array([0.0, 3.0, j[1] / a, 40.0])
    x, w = np.polynomial.legendre.leggauss(400)
    r = 0.5 * a * (x + 1)
    wr = 0.5 * a * w * r
    direct = (
        special.jv(m, j[:, None, None] * r / a) * special.jv(m, kappa[None, :, None] * r)
    ) @ wr
    np.testing.assert_allclose(dr.hankel(m, j, norm, a, kappa), direct, atol=1e-12)


def test_without_air_the_heads_and_cavity_are_free():
    """In a near vacuum every head mode keeps its in-vacuo frequency."""
    d2 = small(air_density_kg_m3=1e-9)
    for m in (0, 1, 3):
        jb, jr = zeros(d2.drum.head, 700.0, m), zeros(d2.resonant, 700.0, m)
        blk = dr.block(d2, m, jb, jr)
        c_b = np.sqrt(d2.drum.head.tension_n_m / d2.drum.head.sigma_kg_m2)
        for f in np.concatenate([jb, jr]) * c_b / d2.drum.head.radius_m:
            assert np.min(np.abs(blk.omega / f - 1)) < 1e-6


def test_the_cavity_split_doesnt_move_the_low_modes():
    """Cavity modes above the cut are added mass instead of oscillators: far below the
    cut the drum's modes don't care where it is."""
    d2 = small()
    for m in (0, 1):
        jb, jr = zeros(d2.drum.head, 700.0, m), zeros(d2.resonant, 700.0, m)
        lo = dr.block(d2, m, jb, jr, f_cavity_hz=900.0)
        hi = dr.block(d2, m, jb, jr, f_cavity_hz=3000.0)
        f_lo = lo.omega[lo.omega < 2 * np.pi * 300] / (2 * np.pi)
        f_hi = hi.omega[hi.omega < 2 * np.pi * 300] / (2 * np.pi)
        assert f_lo.size == f_hi.size >= 2
        np.testing.assert_allclose(f_lo, f_hi, rtol=5e-3)


def test_the_air_splits_the_lowest_mode():
    """Rossing: the air couples the heads and splits the (0,1) mode; the heads moving
    together (the air column shaking) below their in-vacuo frequency, breathing against
    the air spring above it."""
    d2 = small()
    jb, jr = zeros(d2.drum.head, 700.0, 0), zeros(d2.resonant, 700.0, 0)
    blk = dr.block(d2, 0, jb, jr)
    f = blk.omega / (2 * np.pi)
    cav = blk.vb.shape[0] + blk.vr.shape[0]
    head_led = [n for n in range(f.size) if np.sum(blk.vb[:, n] ** 2 + blk.vr[:, n] ** 2) > 0]
    low = sorted(head_led, key=lambda n: f[n])[:2]
    f01 = d2.drum.head.f01_hz
    assert f[low[0]] < f01 < f[low[1]]
    # outward displacements: together = one out, one in; breathing = both out
    for n, sign in ((low[0], -1), (low[1], +1)):
        assert np.sign(blk.vb[0, n] * blk.vr[0, n]) == sign
    assert cav > 0


def test_the_far_field_is_the_heads_integral():
    """A(theta) = sum over heads of integral (outward displacement) e^{i k r.r'} dS, by
    brute-force quadrature over both discs (phi = 0 plane)."""
    d2 = small()
    a, half = d2.drum.head.radius_m, 0.5 * d2.body.depth_m
    m = 1
    jb, jr = zeros(d2.drum.head, 700.0, m), zeros(d2.resonant, 700.0, m)
    blk = dr.block(d2, m, jb, jr)
    pick = np.argsort(blk.omega)[:4]
    theta = np.array([0.3, 1.2, 2.5])
    fast = dr._far_field(blk, d2, theta)[pick]
    x, w = np.polynomial.legendre.leggauss(120)
    r = 0.5 * a * (x + 1)
    wr = 0.5 * a * w * r
    n_phi = 256
    phi = 2 * np.pi * np.arange(n_phi) / n_phi
    rr, pp = np.meshgrid(r, phi, indexing="ij")
    wgt = (wr[:, None] * np.full(n_phi, 2 * np.pi / n_phi)).ravel()
    for i, n in enumerate(pick):
        k = blk.omega[n] / d2.drum.sound_speed_m_s
        for t_i, th in enumerate(theta):
            total = 0j
            for vh, jh, z in ((blk.vb, jb, -half), (blk.vr, jr, half)):
                norm = np.sqrt(2.0 / (np.pi * a * a * special.jv(m + 1, jh) ** 2))
                shape = norm[:, None] * special.jv(m, jh[:, None] * rr.ravel() / a)
                shape = shape * np.cos(m * pp.ravel())
                w_n = vh[:, n] @ shape
                ph = np.exp(
                    1j * k * (np.sin(th) * rr.ravel() * np.cos(pp.ravel()) + z * np.cos(th))
                )
                total += np.sum(w_n * ph * wgt)
            # the fast form carries i^m cos(m phi) outside: at phi = 0, times i^m
            assert total == pytest.approx(1j**m * fast[i, t_i], rel=1e-6, abs=1e-12)


def test_a_compact_drum_radiates_as_a_monopole_when_it_breathes():
    """A drum far smaller than the wavelength: a mode's power is a monopole's of its net
    outward volume, rho0 Omega^2 Q^2 / (8 pi c), and a mode whose heads move together has
    no net volume (a dipole, far quieter). To 2% only: the tiny drum's stiff air spring
    makes its breathing mode cancel most of its volume, so the r^2 term (0.8% at the
    side) isn't negligible against Q."""
    d2 = small(f_max_hz=3000.0)
    tiny = dataclasses.replace(
        d2,
        drum=dataclasses.replace(
            d2.drum,
            head=dataclasses.replace(d2.drum.head, radius_m=0.01),
            strike_radius_m=0.0,
            beater=dataclasses.replace(d2.drum.beater, face_radius_m=0.002),
        ),
        resonant=dataclasses.replace(d2.resonant, radius_m=0.01),
        body=dataclasses.replace(d2.body, depth_m=0.01),
    )
    a = 0.01
    jb = zeros(tiny.drum.head, 3000.0, 0)
    jr = zeros(tiny.resonant, 3000.0, 0)
    blk = dr.block(tiny, 0, jb, jr)
    norm = np.sqrt(2.0 / (2.0 * np.pi * a * a * special.jv(1, jb) ** 2))
    vol = 2 * np.pi * norm * a * special.jv(1, jb) / (jb / a)  # integral of Phi_k
    x, w = np.polynomial.legendre.leggauss(96)
    theta = 0.5 * np.pi * (x + 1)
    far = dr._far_field(blk, tiny, theta)
    s = (
        1.204 * blk.omega**2 * 2 * np.pi / (32 * np.pi**2 * 343.0)
        * (np.abs(far) ** 2 @ (0.5 * np.pi * w * np.sin(theta)))
    )  # fmt: skip
    q = vol @ blk.vb + vol @ blk.vr
    expect = 1.204 * blk.omega**2 * q**2 / (8 * np.pi * 343.0)
    order = np.argsort(blk.omega)
    together, breathing = [n for n in order if blk.omega[n] > 0][:2]
    assert s[breathing] == pytest.approx(expect[breathing], rel=2e-2)
    # moving together, the heads' volumes cancel: far below a monopole of one head's
    one_head = (
        1.204 * blk.omega[together] ** 2 * (vol @ blk.vb[:, together]) ** 2 / (8 * np.pi * 343.0)
    )
    assert s[together] < 1e-2 * one_head


def test_the_sparse_stretch_matches_the_dense(monkeypatch):
    d2 = small(f_max_hz=500.0)
    sparse_prep = dr.prepare(d2)
    monkeypatch.setattr(dr, "G_TOL", 0.0)
    dense_prep = dr.prepare(d2)
    assert sparse_prep.g_heads[0].nnz <= dense_prep.g_heads[0].nnz
    a = dr.run(sparse_prep, fs=FS, seconds=0.15, velocity_m_s=4.0).pressure_pa
    b = dr.run(dense_prep, fs=FS, seconds=0.15, velocity_m_s=4.0).pressure_pa
    assert np.sqrt(np.mean((a - b) ** 2)) < 1e-4 * np.sqrt(np.mean(b**2))


def test_a_strike_on_the_drum():
    d2 = small()
    prep = dr.prepare(d2)
    soft = dr.run(prep, fs=FS, seconds=0.25, velocity_m_s=0.5)
    hard = dr.run(prep, fs=FS, seconds=0.25, velocity_m_s=3.0)
    flat = dr.run(prep, fs=FS, seconds=0.25, velocity_m_s=3.0, tension_modulation=False)
    for h in (soft, hard, flat):
        assert np.all(np.isfinite(h.pressure_pa))
        assert h.force_n.max() > 0 and h.force_n[-1] == 0.0
    assert np.abs(hard.pressure_pa).max() > 3 * np.abs(soft.pressure_pa).max()
    f0 = prep.omega[dr.fundamental(prep)] / (2 * np.pi)
    assert hard.f_fund_hz.max() / f0 - 1 > 4 * (soft.f_fund_hz.max() / f0 - 1) > 0
    np.testing.assert_allclose(flat.f_fund_hz, f0, rtol=1e-12)
    # the batter's tension rises more than the resonant head's, which only the air drives
    assert (
        hard.tension_n_m[0].max() - prep.d2.drum.head.tension_n_m
        > (hard.tension_n_m[1].max() - prep.d2.resonant.tension_n_m)
        > 0
    )

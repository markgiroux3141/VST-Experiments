"""The struck drumhead (varimu/drums/membrane.py; docs/DRUM_PLAN.md, D1's first test)."""

from __future__ import annotations

import dataclasses
import re

import numpy as np
import pytest
from scipy import special

from varimu.drums import membrane as mb

FS = 96000


def small_tom(**head) -> mb.Drum:
    drum = mb.load("tom_13")
    return dataclasses.replace(drum, head=dataclasses.replace(drum.head, **head), f_max_hz=1500.0)


def lossless(drum: mb.Drum) -> mb.Drum:
    return dataclasses.replace(
        drum, head=dataclasses.replace(drum.head, loss_factor=0.0), air_density_kg_m3=1e-12
    )


def test_modes_are_the_bessel_zeros():
    drum = small_tom()
    md = mb.modes(drum.head, drum.f_max_hz)
    assert md.f0_hz[0] == pytest.approx(drum.head.f01_hz, rel=1e-12)
    for m, n in ((0, 1), (1, 1), (2, 1), (0, 2), (3, 1), (1, 2)):
        k = np.flatnonzero((md.m == m) & (md.n == n))[0]
        assert md.f0_hz[k] / md.f0_hz[0] == pytest.approx(
            special.jn_zeros(m, n)[-1] / special.jn_zeros(0, 1)[0], rel=1e-12
        )
    # the textbook ratios (Fletcher & Rossing, the ideal membrane)
    ratio = {
        (int(m), int(n)): f / md.f0_hz[0] for m, n, f in zip(md.m, md.n, md.f0_hz, strict=True)
    }
    assert ratio[(1, 1)] == pytest.approx(1.594, abs=1e-3)
    assert ratio[(2, 1)] == pytest.approx(2.136, abs=1e-3)
    assert ratio[(0, 2)] == pytest.approx(2.296, abs=1e-3)
    assert np.all(md.f0_hz <= drum.f_max_hz)
    # every zero below f_max is there
    for m in range(int(md.m.max()) + 2):
        zeros = special.jn_zeros(m, 60)
        expect = np.sum(zeros * md.f0_hz[0] / md.j[0] <= drum.f_max_hz)
        assert np.sum(md.m == m) == expect


def test_modes_are_orthonormal():
    drum = small_tom()
    md = mb.modes(drum.head, drum.f_max_hz)
    a = drum.head.radius_m
    pick = [k for k in range(md.m.size) if md.f0_hz[k] < 600]
    sub = mb.Modes(*(getattr(md, f.name)[pick] for f in dataclasses.fields(mb.Modes)))
    x, w = np.polynomial.legendre.leggauss(80)
    r = 0.5 * a * (x + 1)
    wr = 0.5 * a * w * r
    n_phi = 64
    phi = 2 * np.pi * np.arange(n_phi) / n_phi
    rr, pp = np.meshgrid(r, phi, indexing="ij")
    weights = (wr[:, None] * np.full(n_phi, 2 * np.pi / n_phi)).ravel()
    s = mb.shape(sub, a, rr.ravel(), pp.ravel())
    gram = (s * weights) @ s.T
    np.testing.assert_allclose(gram, np.eye(len(pick)), atol=1e-9)


def test_a_small_face_averages_to_the_point():
    drum = small_tom()
    md = mb.modes(drum.head, drum.f_max_hz)
    a = drum.head.radius_m
    point = mb.shape(md, a, np.array([0.05]), np.array([0.0]))[:, 0]
    np.testing.assert_allclose(mb.face_average(md, a, 0.05, 1e-5), point, rtol=1e-6, atol=1e-6)


def test_radiation_is_a_monopole_when_small():
    """A head much smaller than the wavelength: its (0,1) mode radiates as a baffled
    monopole of volume velocity Q q', P = rho0 omega^4 Q^2 q^2 / (4 pi c)."""
    drum = small_tom(radius_m=0.005, f01_hz=200.0)
    prep = mb.prepare(dataclasses.replace(drum, f_max_hz=300.0))
    md = prep.modes
    a = drum.head.radius_m
    q_vol = md.norm[0] * 2 * np.pi * a * a * special.jv(1, md.j[0]) / md.j[0]
    rho0, c0 = drum.air_density_kg_m3, drum.sound_speed_m_s
    expect = rho0 * md.omega0[0] ** 2 * q_vol**2 / (4 * np.pi * c0 * drum.head.sigma_kg_m2)
    assert prep.decay_radiation[0] == pytest.approx(expect, rel=1e-4)


def test_a_free_mode_rings_at_its_frequency_and_decay():
    drum = small_tom()
    prep = mb.prepare(drum)
    md = prep.modes
    k = np.flatnonzero((md.m == 1) & (md.n == 1))[0]
    q0 = np.zeros(md.m.size)
    q0[k] = 1e-7
    hit = mb.run(prep, fs=FS, seconds=0.5, q0=q0, tension_modulation=False)
    x = hit.pressure_pa
    up = np.flatnonzero((x[:-1] < 0) & (x[1:] >= 0))
    frac = x[up] / (x[up] - x[up + 1])  # linear interpolation of each crossing
    t = (up + frac) / FS
    f = (len(t) - 1) / (t[-1] - t[0])
    s = prep.decay[k]
    omega_d = np.sqrt(md.omega0[k] ** 2 - s * s)
    assert f == pytest.approx(omega_d / (2 * np.pi), rel=2e-4)
    # the envelope: peaks a known time apart
    n = int(0.1 * FS)
    e1 = np.abs(x[:n]).max()
    e2 = np.abs(x[3 * n : 4 * n]).max()
    assert np.log(e1 / e2) / (0.3) == pytest.approx(s, rel=0.02)
    assert np.all(hit.tension_n_m == drum.head.tension_n_m)


def test_tension_modulation_is_a_duffing_shift():
    """One mode at amplitude A: T lambda q has a cubic term, stretch lambda^2 q^3, so the
    frequency squared rises by 3/4 stretch lambda A^2 / T0 (Duffing, first order)."""
    drum = lossless(small_tom())
    prep = mb.prepare(drum)
    md = prep.modes
    for amp in (1e-4, 2e-4):
        q0 = np.zeros(md.m.size)
        q0[0] = amp
        hit = mb.run(prep, fs=FS, seconds=0.2, q0=q0)
        x = hit.pressure_pa
        up = np.flatnonzero((x[:-1] < 0) & (x[1:] >= 0))
        t = (up + x[up] / (x[up] - x[up + 1])) / FS
        f = (len(t) - 1) / (t[-1] - t[0])
        shift = 0.75 * drum.head.stretch_n_m * md.lam[0] * amp**2 / drum.head.tension_n_m
        assert 0.002 < shift < 0.05
        assert (f / md.f0_hz[0]) ** 2 - 1 == pytest.approx(shift, rel=0.03)


def test_a_strike():
    drum = small_tom()
    prep = mb.prepare(drum)
    soft = mb.run(prep, fs=FS, seconds=0.3, velocity_m_s=0.5)
    hard = mb.run(prep, fs=FS, seconds=0.3, velocity_m_s=3.0)
    flat = mb.run(prep, fs=FS, seconds=0.3, velocity_m_s=3.0, tension_modulation=False)
    for h in (soft, hard, flat):
        assert np.all(np.isfinite(h.pressure_pa))
        assert h.force_n[0] >= 0 and h.force_n.max() > 0
        assert h.force_n[-1] == 0.0  # the stick has left
    assert np.abs(hard.pressure_pa).max() > 3 * np.abs(soft.pressure_pa).max()
    f01 = drum.head.f01_hz
    assert hard.f01_hz.max() / f01 - 1 > 4 * (soft.f01_hz.max() / f01 - 1) > 0
    np.testing.assert_allclose(flat.f01_hz, f01, rtol=1e-12)
    # the glide decays back toward the tuning
    assert hard.f01_hz[-1] < hard.f01_hz.max()


def test_values_need_sources(tmp_path):
    text = (mb.DRUMS_DIR / "tom_13.yaml").read_text(encoding="utf-8")
    bad = re.sub(r"(?m)^  poisson: .*$", "  poisson: 0.38", text)
    assert bad != text
    path = tmp_path / "bad.yaml"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError, match="poisson"):
        mb.load("bad", path)

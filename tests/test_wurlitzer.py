"""WZ1: the Wurlitzer 200A's reed, pickup and plate (docs/WURLITZER_PLAN.md)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from varimu.wurlitzer import key as ky
from varimu.wurlitzer import pickup as pk
from varimu.wurlitzer import reed as rd
from varimu.wurlitzer import spec as sp


def _bare(length_m: float = 0.04) -> rd.Reed:
    return rd.Reed(
        length_m, 0.5e-3, 3.0e-3, 2.07e11, 7850.0, 0.0, 0.0, 1e-3, loss=1e-3, element_m=1e-3
    )


def test_bare_cantilever_matches_euler_bernoulli():
    r = _bare()
    md = rd.modes(rd.assemble(r), count=2)
    rho_a = r.density_kg_m3 * r.width_m * r.thickness_m
    f1 = 1.875104**2 / (2 * np.pi) * np.sqrt(r.ei / (rho_a * r.length_m**4))
    assert md.f_hz[0] == pytest.approx(f1, rel=1e-4)
    assert md.f_hz[1] / md.f_hz[0] == pytest.approx((4.694091 / 1.875104) ** 2, rel=1e-3)


def test_stiffness_proportional_loss_sets_the_fundamentals_q():
    md = rd.modes(rd.assemble(_bare()), count=3)
    assert md.q[0] == pytest.approx(1000.0, rel=1e-9)
    assert md.q[1] < md.q[0] / 5  # higher modes decay faster (omega^2)


def test_a_tip_mass_lowers_the_pitch_and_raises_the_second_modes_ratio():
    bare = _bare()
    tipped = replace(
        bare, tip_mass_kg=0.5 * bare.tongue_mass_kg, tip_length_m=2e-3, tip_height_m=0.0
    )
    a = rd.modes(rd.assemble(bare), count=2)
    b = rd.modes(rd.assemble(tipped), count=2)
    assert b.f_hz[0] < 0.8 * a.f_hz[0]
    assert b.f_hz[1] / b.f_hz[0] > a.f_hz[1] / a.f_hz[0] + 1.0


@pytest.mark.parametrize("n", [1, 14, 15, 21, 37, 50, 64])
def test_every_reed_is_tuned_to_its_note(n):
    k = sp.key(n, with_plate=False)
    f = rd.fundamental_hz(k.reed)
    assert 1200 * abs(np.log2(f / sp.note_hz(n))) < 0.01
    assert 10e-3 < k.reed.length_m < 90e-3
    assert k.slot_lo_m < k.slot_hi_m < k.reed.length_m
    assert 0 < k.hammer.strike_x_m < k.slot_lo_m


def test_the_capacitance_is_largest_with_the_reed_in_the_plates_plane():
    s = pk.section(3.0e-3, 0.5e-3, 0.8e-3, 0.35e-3, 12e-3, 8e-3, 0.05e-3, 1.5e-3)
    m = pk.mesh(s)
    c = [pk.capacitance_per_m(m, st) for st in (0, 4, 10, 20)]
    assert c[0] > c[1] > c[2] > c[3] > 0
    # the reed's share: a few tens of pF per metre (two narrow gaps across the plate's edges)
    assert 20e-12 < c[0] - c[3] < 200e-12


def test_a_narrower_gap_couples_more():
    wide = pk.section(3.0e-3, 0.5e-3, 0.8e-3, 0.5e-3, 12e-3, 8e-3, 0.05e-3, 1.0e-3)
    narrow = replace(wide, side_gap_m=0.25e-3)
    cw = [pk.capacitance_per_m(pk.mesh(wide), st) for st in (0, 10)]
    cn = [pk.capacitance_per_m(pk.mesh(narrow), st) for st in (0, 10)]
    assert cn[0] - cn[1] > cw[0] - cw[1]


def test_the_plates_linear_model_matches_the_exact_equation():
    k = sp.key(28)
    s = ky.strike(k, 2.0, duration_s=0.2, fs_hz=48000.0, oversample=8)
    sysm = ky.System(k)
    # rebuild the capacitance at the stepped rate from the decimated one is lossy: compare on
    # a capacitance signal of the strike's size and spectrum instead
    t = np.arange(int(0.05 * 384000)) / 384000
    dc = np.ptp(s.c_f) / 2 * np.sin(2 * np.pi * k.f_hz * t) + 0.1 * np.ptp(s.c_f) * np.sin(
        4 * np.pi * k.f_hz * t
    )
    a = ky.plate_voltage(dc, k, 384000.0)
    b = ky.plate_voltage_exact(dc, k, 384000.0)
    assert np.sqrt(np.mean((a - b) ** 2)) < 1e-2 * np.sqrt(np.mean(b**2))
    assert sysm.n >= 3


def _h(y: np.ndarray, fs: float, f0: float) -> tuple[float, float]:
    a, b = int(0.1 * fs), int(0.4 * fs)
    seg = y[a:b] * np.hanning(b - a)
    s = np.abs(np.fft.rfft(seg, 1 << 20))
    fr = np.fft.rfftfreq(1 << 20, 1 / fs)

    def pk_(f):
        lo, hi = np.searchsorted(fr, [f * 0.98, f * 1.02])
        return s[lo:hi].max()

    return pk_(f0), pk_(2 * f0)


def test_a_reed_at_rest_in_the_plates_plane_doubles_its_frequency():
    """VV tuning: 'When a reed at rest is positioned inside the pickup, a very strong
    undesirable harmonic will be generated.'"""
    k = sp.key(28)
    centred = ky.strike(k, 1.0, duration_s=0.5, fs_hz=48000.0, oversample=8, voicing_m=0.0)
    voiced = ky.strike(k, 1.0, duration_s=0.5, fs_hz=48000.0, oversample=8, voicing_m=0.6e-3)
    h1, h2 = _h(centred.plate_v, 48000.0, k.f_hz)
    assert h2 > 10 * h1
    h1, h2 = _h(voiced.plate_v, 48000.0, k.f_hz)
    assert h1 > 3 * h2


def test_the_bark_grows_with_the_strike():
    k = sp.key(4)
    soft = ky.strike(k, 0.3, duration_s=0.5, fs_hz=48000.0, oversample=8)
    hard = ky.strike(k, 2.0, duration_s=0.5, fs_hz=48000.0, oversample=8)
    r_soft = np.divide(*_h(soft.plate_v, 48000.0, k.f_hz)[::-1])
    r_hard = np.divide(*_h(hard.plate_v, 48000.0, k.f_hz)[::-1])
    assert r_hard > 3 * r_soft
    assert hard.strikes == 1 and 0.2e-3 < hard.contact_s < 3e-3


def test_the_plates_pull_on_a_reed_is_negligible():
    for n in (1, 28, 64):
        assert abs(ky.electrostatic_shift_cents(sp.key(n))) < 0.1

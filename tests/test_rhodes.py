"""The Rhodes, RH1 (varimu/rhodes/; docs/RHODES_PLAN.md): the tone bar assembly's finite
elements, a key's fits, the pickup's field solve and a strike."""

from __future__ import annotations

import csv
from dataclasses import replace

import numpy as np
import pytest

from varimu.rhodes import beam as bm
from varimu.rhodes import key as ky
from varimu.rhodes import pickup as pk
from varimu.rhodes import spec


def cantilever(length=0.1, d=1.5e-3, spring=0.0, x_s=None) -> bm.Assembly:
    """A uniform tine on a rigid, heavy mount, no tone bar."""
    return bm.Assembly(
        (bm.Section(length, d, d),),
        2e11,
        7850.0,
        spring,
        4e-3,
        x_s if x_s is not None else 0.7 * length,
        None,
        1.0,
        1e-3,
        0.0,
        (0.0, 0.01),
        1e9,
        0.0,
        1e-4,
        100.0,
    )


def test_beam_is_the_cantilever():
    a = cantilever()
    fe = bm.assemble(a)
    md = bm.modes(fe, count=4)
    i = np.pi * (1.5e-3) ** 4 / 64
    area = np.pi * (1.5e-3) ** 2 / 4
    f1 = 1.87510**2 / (2 * np.pi * 0.1**2) * np.sqrt(2e11 * i / (7850 * area))
    k = bm.tine_mode(fe, md)
    assert md.f_hz[k] == pytest.approx(f1, rel=1e-4)
    # the second bending mode at 6.267x (4.6941^2 / 1.8751^2)
    bending = [f for f in md.f_hz if f > 1.5 * f1 and abs(f / f1 - 6.267) < 0.1]
    assert bending and bending[0] / f1 == pytest.approx(6.267, rel=1e-3)


def test_spring_moved_outwards_lowers_the_pitch():
    # the manual (ch.5): outwards, away from the fixed end, lowers the pitch
    f = [bm.fundamental_hz(cantilever(spring=2e-4, x_s=x)) for x in (0.03, 0.06, 0.09)]
    assert f[0] > f[1] > f[2]
    tuned = bm.tune(cantilever(spring=2e-4), 0.97 * bm.fundamental_hz(cantilever(spring=2e-4)))
    assert bm.fundamental_hz(tuned) == pytest.approx(
        0.97 * bm.fundamental_hz(cantilever(spring=2e-4)), rel=1e-6
    )


def test_tine_lengths_from_the_chart():
    with spec.TINE_LENGTHS.open(encoding="utf-8") as f:
        rows = [(int(r["key"]), float(r["free_length_m"])) for r in csv.DictReader(f)]
    keys, lengths = zip(*rows, strict=True)
    assert keys == tuple(range(1, 89))
    # Shear 2011: 157 mm to 18 mm on an 88
    assert lengths[0] == pytest.approx(0.157, abs=0.5e-3)
    assert lengths[-1] == pytest.approx(0.0185, abs=0.6e-3)
    steps = np.diff(lengths)
    # never longer up the keyboard but at the chart's seam (key 53 -> 54, as printed)
    assert np.all((steps <= 1e-9) | (np.arange(1, 88) == 53))


def test_gent_relation():
    # Gent (1958): ~1.1 MPa at 30 Shore A, rising steeply towards 90
    assert spec.gent_youngs_pa(30) == pytest.approx(1.14e6, rel=0.02)
    e = [spec.gent_youngs_pa(s) for s in (30, 50, 70, 90)]
    assert all(b > 2 * a for a, b in zip(e[:-1], e[1:], strict=True))


@pytest.mark.parametrize("n", [1, 8, 49, 88])
def test_key_fits(n):
    k = spec.key(n)
    assert k.fits["fundamental_hz"] == pytest.approx(k.note_hz, rel=1e-5)
    if k.fits["tine_loss"] > 0:
        assert k.fits["fundamental_q"] == pytest.approx(k.q_target, rel=0.01)
    else:  # the mount's rubber alone damps it more (keys 46-49: RHODES_PLAN.md RH2)
        assert k.fits["fundamental_q"] <= 1.01 * k.q_target
    assert (k.assembly.tonebar is None) == (n < 8)  # Shear: the 88's lowest seven are bare
    assert 0 < k.assembly.spring_x_m < k.assembly.tine_length_m
    # the hammer's tip gets harder up the keyboard (the manual's grading)
    assert k.hammer.stiffness > 0


@pytest.mark.parametrize("n", [19, 61])
def test_tonebar_balances_the_fork(n):
    k = spec.key(n)
    # the tine's fundamental hardly moves the mount: a balanced fork
    assert k.fits["mount_share"] < 1e-3
    # and balancing it puts the bar alone near the note (the manual: "alike in pitch")
    assert k.fits["tonebar_clamped_hz"] == pytest.approx(k.note_hz, rel=0.1)
    # the mount's lowest mode at Muenster & Pfeifle's measured bar resonance
    fe = bm.assemble(k.assembly, k.element_m)
    md = bm.modes(fe, count=24)
    assert md.f_hz[bm.mount_mode(fe, md)] == pytest.approx(k.tonebar_f0_hz, rel=0.02)


def test_pickup_flux_is_even_and_smooth():
    p = spec.key(49).pickup
    m = pk.mesh(p)
    steps = [-12, -6, 0, 6, 12]

    def phi(s, dg=0.0):
        return pk.linkage_per_turn_per_depth(m, pk.solve(m, s, dg))

    ph = np.array([phi(s) for s in steps])
    # the section is symmetric about the pole's axis
    assert np.max(np.abs(ph - ph[::-1])) < 1e-10 * abs(ph[2])
    # the tine centred on the axis links the most flux; off it, less (an even law: the
    # fundamental cancels there, Shear's voicing finding)
    assert ph[2] > ph[1] > ph[0]
    # pulled back from the gap, less
    assert phi(6, 0.2e-3) < ph[3]
    # whole cells: the geometry is exact at every sample, so the samples are smooth
    fine = np.array([phi(s) for s in range(8, 14)])
    d2 = np.diff(fine, 2)
    assert np.max(np.abs(np.diff(d2))) < 0.1 * np.max(np.abs(d2))


class _LinearFlux:
    """dPhi/dy = 1: the EMF is the tip's velocity."""

    y_range_m = (-1.0, 1.0)
    dg_m = np.array([0.0, 1.0])

    def __call__(self, y, dg, dy=0, ddg=0):
        return np.ones_like(y) if dy == 1 else np.zeros_like(y)


def test_strike_live_against_reference():
    k = spec.key(49)
    live = ky.strike(k, 1.0, duration_s=0.15, flux=_LinearFlux())
    ref = ky.strike(k, 1.0, duration_s=0.15, flux=_LinearFlux(), tier="full", step_oversample=16)
    assert live.strikes == 1 and ref.strikes == 1
    assert live.contact_s == pytest.approx(ref.contact_s, rel=0.05)
    err = 10 * np.log10(np.mean((live.emf_v - ref.emf_v) ** 2) / np.mean(ref.emf_v**2))
    assert err < -30
    # the tine rings at its note once the strike is over (and the assembly's rocking on
    # its grommets, ~38 Hz with a Q of ~8, has died away)
    live = ky.strike(k, 1.0, duration_s=0.6, flux=_LinearFlux())
    seg = live.tip_m[int(0.3 * 96000) :]
    n = 1 << 18
    s = np.abs(np.fft.rfft(seg * np.hanning(seg.size), n))
    f = np.fft.rfftfreq(n, 1 / 96000)
    assert f[np.argmax(s)] == pytest.approx(k.note_hz, rel=0.01)


def test_harder_strike_contacts_shorter():
    k = spec.key(49)
    soft = ky.strike(k, 0.5, duration_s=0.05, flux=_LinearFlux())
    hard = ky.strike(k, 2.0, duration_s=0.05, flux=_LinearFlux())
    # a Hertz contact stiffens as it compresses
    assert hard.contact_s < soft.contact_s
    assert hard.max_force_n > 2 * soft.max_force_n


def test_steel_loss_floor():
    # without the grommets' dashpots and the tine's own loss the steel alone decays the
    # tine (Q ~ 1 / eta)
    k = spec.key(49)
    a = replace(k.assembly, grommet_c_n_s_m=0.0, tine_loss=0.0)
    fe = bm.assemble(a)
    md = bm.modes(fe, count=12)
    q = md.q[bm.tine_mode(fe, md)]
    assert 0.5 / a.steel_loss < q < 2 / a.steel_loss

"""The Nickel Organ (docs/NICKEL_ORGAN_PLAN.md): the bar, nickel's fit, the transducer and
the loop."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from varimu.nickel import bar as nbar
from varimu.nickel import magnet, organ
from varimu.nickel import spec as nspec
from varimu.nickel import voice as nvoice

FS = organ.FS


@pytest.fixture(scope="module")
def d():
    return nspec.load()


def test_every_value_has_a_source(d):
    nspec._check(d, "organ.yaml")  # load() already does: a value without one raises


def test_uniform_cantilever_matches_euler_bernoulli(d):
    dz = replace(nbar.design(d, 440.0), strip_t_m=1e-12)
    f = nbar._eig(dz)[1][:4]
    beta = np.array([1.8751041, 4.6940911, 7.8547574, 10.9955407])
    np.testing.assert_allclose(f / f[0], (beta / beta[0]) ** 2, rtol=2e-3)
    ei, ra, _ = nbar.section(dz, False)
    f1 = beta[0] ** 2 / (2 * math.pi * dz.length_m**2) * math.sqrt(ei / ra)
    assert f[0] == pytest.approx(f1, rel=1e-3)


@pytest.mark.parametrize("f_hz", [65.406, 440.0, 2093.005])
def test_bars_are_tuned(d, f_hz):
    b = nbar.build(d, f_hz)
    assert b.freq_hz[0] == pytest.approx(f_hz, rel=1e-6)
    assert 0.25 * b.design.length_m == pytest.approx(b.design.strip_m, rel=1e-9) or (
        b.design.strip_m in (0.010, 0.040)
    )


def test_nickel_fit_meets_its_recorded_figures(d):
    """The stored JA parameters reproduce the figures config/nickel/organ.yaml records (the
    fit's compromise: mu_max and Hc +53%, Br -34% against the handbook)."""
    ni = magnet.from_spec(d["nickel"])
    _, h0 = magnet.targets(d["nickel"])
    got = magnet.figures(ni.core, h0)
    assert got["mu_initial"] == pytest.approx(110.0, rel=0.02)
    assert got["mu_max"] == pytest.approx(919.0, rel=0.03)
    assert got["coercivity_a_per_m"] == pytest.approx(85.6, rel=0.03)
    assert got["remanence_t"] == pytest.approx(0.198, rel=0.03)


def test_magnetostriction_is_even_and_shrinks_nickel(d):
    ni = magnet.from_spec(d["nickel"])
    assert ni.lam(1e5) == ni.lam(-1e5) < 0
    assert ni.lam(ni.ms) == pytest.approx(ni.lambda_s)
    assert ni.dlam(0.0) == 0.0  # no first-order coupling at zero magnetization


def _struck(note, polarize, v0=None, velocity=1, oversample=2, n=4800):
    vc = nvoice.make_voice(note, noise=False, oversample=oversample)
    organ._power_on(vc, polarize)
    vc.strike(velocity)
    if v0 is not None:
        vc.vh = v0
    return vc.run(n, sustain=0.0, polarize=polarize), vc


def test_a_virgin_strip_at_zero_bias_hears_nothing():
    """No magnetization, no Villari EMF to first order: the struck bar is (nearly) silent."""
    y0, vc = _struck(69, 0.0)
    y1, _ = _struck(69, 0.35)
    assert abs(vc.m1) < 1e-6 * vc.p.ni.ms
    assert np.abs(y0).max() < 1e-4 * np.abs(y1).max()


def test_small_strikes_are_linear():
    """At a few um of tip the transducer is linear: twice the hammer's speed, twice the line out."""
    y1, _ = _struck(69, 0.35, v0=0.004)
    y2, _ = _struck(69, 0.35, v0=0.008)
    r = np.sqrt(np.mean(y2[480:] ** 2) / np.mean(y1[480:] ** 2))
    assert r == pytest.approx(2.0, rel=0.05)


def test_the_step_converges():
    a, _ = _struck(69, 0.35, velocity=64, oversample=2)
    b, _ = _struck(69, 0.35, velocity=64, oversample=4)
    rel = np.sqrt(np.mean((a - b) ** 2) / np.mean(b**2))
    assert 20 * np.log10(rel) < -30


def test_the_loop_regenerates_the_fundamental():
    """Closing the loop slows the fundamental's decay (the polarity is the regenerating one),
    and the onset sits within the SUSTAIN pot's reach."""
    m = organ.measure_onset(69)
    assert m["rate_open"] < 0
    assert m["rate_probe"] > m["rate_open"]
    assert 0 < m["g_star"] < 1


def test_decay_rate_reads_an_exponential():
    t = np.arange(int(0.3 * FS)) / FS
    y = np.exp(-2.5 * t) * np.sin(2 * np.pi * 440 * t)
    assert organ.decay_rate(y, 440.0) == pytest.approx(-2.5, abs=0.02)

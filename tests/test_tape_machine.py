"""The first print's machine (varimu.devices.tape_machine): its networks and the print's
mechanics. The alignment itself takes minutes (scripts/tape_print.py runs it; its numbers
are in docs/TAPE_PLAN.md)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from varimu.devices import library
from varimu.devices.tape_machine import (
    Alignment,
    TapeMachineSpec,
    _resp,
    _trim_tz,
    print_audio,
    rec_network,
    rep_network,
    tone_harmonics,
)

SPEC = TapeMachineSpec()


def test_the_nab_networks():
    """Repro: T1 (1 + s T2) / (1 + s T1). Record: +20 dB at most below 50 Hz, flat above."""
    b, a = rep_network(SPEC, 0.0, 1e-12)
    f = np.array([5.0, 50.0, 500.0, 5000.0, 50000.0])
    r = np.abs(_resp(b, a, f))
    t1, t2 = SPEC.t1_s, SPEC.t2_s
    want = t1 * np.abs(1 + 2j * math.pi * f * t2) / np.abs(1 + 2j * math.pi * f * t1)
    np.testing.assert_allclose(r, want, rtol=1e-6)
    b, a = rec_network(SPEC, 0.0, 1e-12)
    g = np.abs(_resp(b, a, np.array([0.01, 1000.0, 20000.0])))
    assert g[0] == pytest.approx(10.0, rel=1e-3) and g[1] == pytest.approx(1.0, abs=0.01)


def test_the_heads_loss_against_an_ideal_reader_is_the_gap_and_the_spacing():
    """A test tape's reading (the real head's over an ideal reproducer's, of one recorded
    pattern) at short wavelengths: the gap loss sinc(g / lambda) times the spacing loss
    exp(-k d), the pole edges' contour ripple aside (< 0.15 dB here). The ideal reader is
    the gap's term alone: a vanishing gap between finite poles (the first print's) read
    its far pole edges as loud as the gap, +16..+30 dB at 7.5-15 kHz."""
    tape = library.load_tape("SCOTCH111@3")
    hc = tape.preisach.hc_median_a_m
    for f in (7500.0, 15000.0):
        real, ideal = tone_harmonics(SPEC, tape, f, 0.05 * hc, 3.0 * hc, harmonics=1, ideal=True)
        lam = SPEC.speed_m_s / f
        theory = np.sinc(SPEC.rep_gap_m / lam) * math.exp(-2 * math.pi * SPEC.spacing_m / lam)
        assert 20 * math.log10(abs(real[0] / ideal[0]) / theory) == pytest.approx(0, abs=0.15)


def test_the_trim_reaches_its_gain():
    tp = 1 / (2 * math.pi * 30e3)
    for gain in (1.2, 2.0, 3.5):
        tz = _trim_tz(gain, 10e3, tp)
        w = 2 * math.pi * 10e3
        assert abs((1 + 1j * w * tz) / (1 + 1j * w * tp)) == pytest.approx(gain, rel=1e-9)


@pytest.fixture(scope="module")
def coarse():
    """A cheap machine (3 layers, 2 um cells, 4 orientations, no demag) with a fixed
    alignment in the aligned machine's proportions (bias 3 Hc, 0 VU 0.65 Hc)."""
    pytest.importorskip("circuitsim")
    tape = library.load_tape("SCOTCH111@2")
    tape = dataclasses.replace(tape, orientation=dataclasses.replace(tape.orientation, n=4))
    spec = dataclasses.replace(SPEC, layers=3, ds_m=2e-6, demag_iterations=0)
    hc = tape.preisach.hc_median_a_m
    al = Alignment(3.0 * hc, 0.65 * hc, 0.0, 0.0, 1.0)
    return spec, tape, al


def test_a_print_is_linear_at_low_level_and_saturates_hot(coarse):
    """Halving a quiet tone halves its print; a hot one comes back compressed and
    distorted, mostly 3rd harmonic."""
    spec, tape, al = coarse
    fs = 96_000
    n = int(0.08 * fs)
    tone = np.sin(2 * math.pi * 1000.0 * np.arange(n) / fs)

    def amps(y):
        seg = y[n // 3 :]
        k = np.arange(len(seg))
        return [
            abs(2 * np.mean(seg * np.exp(-2j * math.pi * h * 1000.0 * k / fs))) for h in (1, 2, 3)
        ]

    quiet = amps(print_audio(0.01 * tone, fs, spec, tape, al))
    half = amps(print_audio(0.005 * tone, fs, spec, tape, al))
    assert half[0] / quiet[0] == pytest.approx(0.5, rel=0.03)
    hot = amps(print_audio(1.0 * tone, fs, spec, tape, al))  # ~+15 dB over 0 VU
    gain_quiet, gain_hot = quiet[0] / 0.01, hot[0] / 1.0
    assert gain_hot < 0.8 * gain_quiet  # compressed
    assert hot[2] > 0.05 * hot[0] and hot[2] > 5 * hot[1]  # 3rd harmonic, little 2nd

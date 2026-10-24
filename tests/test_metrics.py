"""Measurement metrics on synthetic signals with known answers."""

import numpy as np
import pytest

from varimu.measure import metrics


@pytest.mark.parametrize("tau_s", [0.13e-3, 0.2e-3, 0.3])
def test_cv_timing_reads_time_constants_between_samples(tau_s):
    """A CV that moves exponentially with time constant tau gives 63% times of tau and a
    90% release of tau ln 10, to well under a sample, even for a 0.13 ms attack
    (12.5 samples at 96 kHz, where whole samples would be off by up to 8%)."""
    fs = 96000
    a, b = fs // 10, fs // 10 + int(max(20 * tau_s, 0.05) * fs)
    n = b + int(max(30 * tau_s, 0.05) * fs)
    t = np.arange(n) / fs
    lo, hi = -5.0, -60.0
    cv = np.full(n, lo)
    cv[a:b] = hi + (lo - hi) * np.exp(-(t[a:b] - t[a]) / tau_s)
    end = cv[b - 1]
    cv[b:] = lo + (end - lo) * np.exp(-(t[b:] - t[b]) / tau_s)
    r = metrics.cv_timing(cv, fs, a, b)
    # Linear interpolation of an exponential: error ~ (dt/tau)^2 / 8 of a sample.
    assert r.attack_s == pytest.approx(tau_s, rel=2e-3, abs=0.05 / fs)
    assert r.release_63_s == pytest.approx(tau_s, rel=2e-3, abs=0.05 / fs)
    assert r.release_90_s == pytest.approx(tau_s * np.log(10), rel=2e-3, abs=0.05 / fs)


FS = 96000


def test_harmonics_reads_amplitudes_and_the_residual():
    t = np.arange(FS // 10) / FS  # 100 periods of 1 kHz
    y = 2.0 * np.sin(2 * np.pi * 1000 * t) + 0.02 * np.cos(2 * np.pi * 2000 * t + 0.3)
    y += 0.002 * np.sin(2 * np.pi * 3000 * t) + 0.5 + 1e-3 * np.sin(2 * np.pi * 23456 * t)
    h = metrics.harmonics(y, 1000.0, FS)
    assert h.amps[:3] == pytest.approx([2.0, 0.02, 0.002], abs=1e-6)
    assert h.thd == pytest.approx(np.hypot(0.02, 0.002) / 2.0, rel=1e-4)
    assert h.db(2) == pytest.approx(-40.0, abs=1e-3)
    # The residual is the non-harmonic tone (the DC is fitted away).
    assert h.residual_hz == pytest.approx(23456, abs=20)
    assert h.residual_db == pytest.approx(20 * np.log10(1e-3 / 2.0), abs=0.2)
    # The non-harmonic tone is a spur; modulation sidebands next to a harmonic aren't.
    assert h.spur_hz == pytest.approx(23456, abs=20)
    # (within the Hann window's scalloping loss, <= 1.42 dB between bins)
    assert h.spur_db == pytest.approx(20 * np.log10(1e-3 / 2.0), abs=1.5)
    am = 2.0 * (1 + 0.05 * np.sin(2 * np.pi * 30 * t)) * np.sin(2 * np.pi * 1000 * t)
    assert metrics.harmonics(am, 1000.0, FS).spur_db < -100


def test_intermodulation_reads_known_sidebands():
    t = np.arange(FS // 2) / FS
    c = np.sin(2 * np.pi * 7000 * t)
    y = 4 * np.sin(2 * np.pi * 60 * t) + c
    y += 0.01 * (np.sin(2 * np.pi * 6940 * t) + np.sin(2 * np.pi * 7060 * t))
    y += 0.005 * np.sin(2 * np.pi * 7120 * t)
    assert metrics.smpte_imd(y, 60, 7000, FS) == pytest.approx(np.sqrt(2e-4 + 0.25e-4), rel=1e-6)
    y = np.sin(2 * np.pi * 19000 * t) + np.sin(2 * np.pi * 20000 * t)
    y += 0.003 * np.sin(2 * np.pi * 1000 * t) + 0.004 * np.sin(2 * np.pi * 18000 * t)
    r = metrics.ccif_imd(y, 19000, 20000, FS)
    assert r["d2"] == pytest.approx(0.003 / np.sqrt(2), rel=1e-6)
    assert r["d3"] == pytest.approx(0.004 / np.sqrt(2), rel=1e-6)

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

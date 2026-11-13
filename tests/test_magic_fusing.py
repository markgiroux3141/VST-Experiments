"""AM7's constructed noises: equal power and spectrum; the followers follow."""

from __future__ import annotations

import numpy as np
from scipy import signal

from varimu.magic import fusing

FS = 48000


def test_constructed_noises_match_and_follow():
    rng = np.random.default_rng(1)
    t = np.arange(6 * FS) / FS
    trem = 0.55 + 0.45 * np.sin(2 * np.pi * 4 * t)
    y0 = trem * np.sin(2 * np.pi * 220 * t) + 0.3 * trem * np.sin(2 * np.pi * 1760 * t)
    n_ref = signal.lfilter([1], [1, -0.5], rng.standard_normal(len(t))) * 1e-3
    ns = fusing.noises(y0, y0 + n_ref, FS)
    r = {k: np.sqrt(np.mean(v**2)) for k, v in ns.items()}
    for k in ("n_stat", "n_env", "n_band"):
        assert abs(20 * np.log10(r[k] / r["n_phys"])) < 0.01
    # Long-term spectra within 1 dB per third octave (n_stat vs n_phys).
    f, p1 = signal.welch(ns["n_phys"], FS, nperseg=4096)
    _, p2 = signal.welch(ns["n_stat"], FS, nperseg=4096)
    for fc in 1000 * 2 ** (np.arange(-12, 13) / 3):
        s = (f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6))
        assert abs(10 * np.log10(p1[s].sum() / p2[s].sum())) < 1.0
    assert fusing.follow_measures(y0, ns["n_stat"], FS)["coherence_cross"] < 0.15
    assert fusing.follow_measures(y0, ns["n_env"], FS)["coherence_cross"] > 0.6

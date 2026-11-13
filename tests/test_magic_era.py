"""AM3's statistics distance on synthetic material."""

from __future__ import annotations

import numpy as np
from scipy import signal

from varimu.magic import era

FS = 24000


def _music(seed: int, seconds: float = 30.0) -> np.ndarray:
    """Notes of filtered noise with envelopes: a texture with modulation."""
    rng = np.random.default_rng(seed)
    n = int(seconds * FS)
    x = np.zeros(n)
    t = 0
    while t < n - FS:
        d = int(rng.uniform(0.15, 0.6) * FS)
        f0 = rng.uniform(100, 800)
        k = np.arange(d)
        env = np.exp(-k / (0.2 * FS))
        note = sum(np.sin(2 * np.pi * f0 * h * k / FS) / h for h in range(1, 6)) * env
        x[t : t + d] += note
        t += int(rng.uniform(0.1, 0.4) * FS)
    return x / np.std(x) * 0.1


def test_frechet_identity_and_floor():
    f = era.features(_music(1), FS)
    assert era.frechet(f, f, diagonal=True) < 1e-9
    corpus = era.Corpus([f[: len(f) // 2]])
    d_half = corpus.distance(f[len(f) // 2 :])
    lp = signal.sosfilt(signal.butter(4, 2000, fs=FS, output="sos"), _music(1))
    d_lp = corpus.distance(era.features(lp, FS))
    assert d_lp > 2 * d_half


def test_delta_sign_follows_the_change():
    """A corpus band-limited at 3 kHz: a band-limited variant of new material moves toward it."""
    sos = signal.butter(6, 3000, fs=FS, output="sos")
    corpus = era.Corpus([era.features(signal.sosfilt(sos, _music(s)), FS) for s in (2, 3)])
    base = _music(4)
    r = era.era_delta(era.features(signal.sosfilt(sos, base), FS), era.features(base, FS),
                      corpus, n_boot=20)
    assert r["delta"] < 0 and r["ci95"][1] < 0

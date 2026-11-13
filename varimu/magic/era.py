"""Distance to an era (ANALOG_MAGIC_FABLE.md AM3), step 1: a statistics distance with no new
dependency.

`features` gives, per 2 s window (1 s hop), texture statistics after McDermott and
Simoncelli (Neuron 2011; from memory, not checked) on grouping's 32 ERB envelopes:
- per band, the envelope's mean in dB re the window's mean over bands (spectral shape, not
  level), its coefficient of variation and skewness;
- the correlation of envelopes between bands 2, 4 and 8 channels apart;
- per band, the envelope's power in modulation bands at 2, 4, 8, 16, 32 Hz, re its mean^2.
The modulation bands are filtered on the whole file first (a 2 s window is too short for 2 Hz).

`frechet` is the Frechet distance between two Gaussians fitted to two sets of windows:
|mu_a - mu_b|^2 + tr(S_a + S_b - 2 (S_a S_b)^(1/2)), each covariance shrunk toward its diagonal
(0.9 S + 0.1 diag S; the 0.1 is a choice), or the diagonal alone (`diagonal=True`, for corpora
under 30 minutes: about 1800 windows against ~340 dimensions). The features are z-scored with
the corpus's own mean and spread first, so no statistic dominates by its units.

`era_delta(variant, baseline, corpus)` = D(variant) - D(baseline): negative means the variant
moved toward the corpus. Only differences on the same performance mean anything (era
correlates with repertoire, arrangement and performance).
"""

from __future__ import annotations

import numpy as np
from scipy import linalg, signal

from varimu.separation import grouping

WINDOW_S, HOP_S = 2.0, 1.0
RATES_HZ = (2.0, 4.0, 8.0, 16.0, 32.0)
OFFSETS = (2, 4, 8)
SHRINK = 0.1


def features(x: np.ndarray, fs: int) -> np.ndarray:
    """(windows, d) texture statistics of a mono signal."""
    x = np.asarray(x, float)
    if x.ndim == 2:
        x = x.mean(axis=1)
    e = grouping.envelopes(x, fs).env  # (32, n) at 1 kHz
    fe = grouping.FS_ENV
    edge = int(grouping.EDGE_S * fe)
    mods = []
    for r in RATES_HZ:
        sos = signal.butter(2, [r / np.sqrt(2), r * np.sqrt(2)], "bandpass", fs=fe, output="sos")
        mods.append(signal.sosfiltfilt(sos, e, axis=1))
    e = e[:, edge:-edge]
    mods = [m[:, edge:-edge] for m in mods]
    w, h = int(WINDOW_S * fe), int(HOP_S * fe)
    rows = []
    for s in range(0, e.shape[1] - w + 1, h):
        seg = e[:, s : s + w]
        mean = seg.mean(axis=1) + 1e-12
        if mean.max() < 1e-6:  # silence
            continue
        db = 20 * np.log10(mean)
        f_mean = db - db.mean()
        sd = seg.std(axis=1)
        f_cv = sd / mean
        z = (seg - mean[:, None]) / (sd[:, None] + 1e-12)
        f_skew = (z**3).mean(axis=1)
        zc = z / np.sqrt(w)
        corr = []
        for o in OFFSETS:
            corr.append(np.sum(zc[:-o] * zc[o:], axis=1))
        f_mod = [np.mean(m[:, s : s + w] ** 2, axis=1) / mean**2 for m in mods]
        rows.append(np.concatenate([f_mean, f_cv, f_skew, *corr, *(10 * np.log10(np.array(f_mod) + 1e-12))]))
    return np.array(rows)


def _gauss(f: np.ndarray, diagonal: bool):
    mu = f.mean(axis=0)
    if diagonal:
        return mu, np.var(f, axis=0)
    s = np.cov(f, rowvar=False)
    return mu, (1 - SHRINK) * s + SHRINK * np.diag(np.diag(s))


def frechet(f_a: np.ndarray, f_b: np.ndarray, *, diagonal: bool = False) -> float:
    mu_a, s_a = _gauss(f_a, diagonal)
    mu_b, s_b = _gauss(f_b, diagonal)
    d = float(np.sum((mu_a - mu_b) ** 2))
    if diagonal:
        return d + float(np.sum(s_a + s_b - 2 * np.sqrt(s_a * s_b)))
    cs = linalg.sqrtm(s_a @ s_b)
    return d + float(np.trace(s_a + s_b - 2 * np.real(cs)))


class Corpus:
    """The corpus's windows and the z-scoring they define."""

    def __init__(self, feats: list[np.ndarray]):
        self.f = np.vstack(feats)
        self.mu = self.f.mean(axis=0)
        self.sd = self.f.std(axis=0) + 1e-9

    def z(self, f: np.ndarray) -> np.ndarray:
        return (f - self.mu) / self.sd

    def distance(self, f: np.ndarray, diagonal: bool = True) -> float:
        return frechet(self.z(f), self.z(self.f), diagonal=diagonal)


def era_delta(f_variant: np.ndarray, f_baseline: np.ndarray, corpus: Corpus, *,
              diagonal: bool = True, n_boot: int = 200, seed: int = 0) -> dict:
    """D(variant) - D(baseline) against the corpus, with a bootstrap interval over the two
    versions' windows (paired: the same window indices resampled in both)."""
    d = corpus.distance(f_variant, diagonal) - corpus.distance(f_baseline, diagonal)
    rng = np.random.default_rng([seed, 0xE7A])
    n = min(len(f_variant), len(f_baseline))
    zc = corpus.z(corpus.f)
    boots = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        boots.append(frechet(corpus.z(f_variant[i]), zc, diagonal=diagonal)
                     - frechet(corpus.z(f_baseline[i]), zc, diagonal=diagonal))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"delta": float(d), "ci95": [float(lo), float(hi)]}

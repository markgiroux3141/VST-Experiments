"""Loudness and gain-reduction matching for listening comparisons ("loudness lies").

Every clip played side by side is normalized to the same integrated loudness
(ITU-R BS.1770 via pyloudnorm). Gain reduction is measured and shown next to
each render; *matching* it (solving each candidate's threshold for a target
average GR) is Phase 5 work. Until then the app reports GR so the listener
knows when two renders differ in how hard they compress.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TARGET_LUFS = -23.0
PEAK_CEILING = 0.98  # linear; the shared target drops if any clip would exceed it


def integrated_lufs(x: np.ndarray, sample_rate: int) -> float:
    import pyloudnorm

    x = np.asarray(x, float)
    min_len = int(0.4 * sample_rate) + 1  # BS.1770 gating blocks are 400 ms
    if len(x) < min_len:
        x = np.concatenate([x, np.zeros(min_len - len(x))])
    return float(pyloudnorm.Meter(sample_rate).integrated_loudness(x))


@dataclass(frozen=True)
class Matched:
    gains_db: list[float]  # applied to each input
    target_lufs: float
    measured_lufs: list[float]


def match_loudness(clips: list[np.ndarray], sample_rate: int, target: float = TARGET_LUFS):
    """Gains that bring every clip to one integrated loudness without any clipping.

    The target is `target` LUFS unless that would push some clip's peak over
    PEAK_CEILING, in which case all clips share a lower target. Returns the
    scaled clips and the match details.
    """
    lufs = [integrated_lufs(c, sample_rate) for c in clips]
    finite = [v if np.isfinite(v) else None for v in lufs]
    headroom = [
        20 * np.log10(PEAK_CEILING / max(np.max(np.abs(c)), 1e-12)) - (target - v)
        for c, v in zip(clips, finite, strict=True)
        if v is not None
    ]
    if headroom and min(headroom) < 0:
        target += min(headroom)
    gains = [0.0 if v is None else target - v for v in finite]
    out = [c * 10 ** (g / 20) for c, g in zip(clips, gains, strict=True)]
    return out, Matched(gains, target, lufs)


def gain_trace(
    dry: np.ndarray, wet: np.ndarray, sample_rate: int, window_s: float = 0.01, points: int = 800
):
    """(times, gain dB) of wet relative to dry over short windows, for display.

    Silence in the dry signal makes gain undefined; those windows are NaN.
    """
    w = max(1, int(window_s * sample_rate))
    n = (min(len(dry), len(wet)) // w) * w
    d = np.sqrt(np.mean(np.square(dry[:n]).reshape(-1, w), axis=1))
    y = np.sqrt(np.mean(np.square(wet[:n]).reshape(-1, w), axis=1))
    with np.errstate(divide="ignore", invalid="ignore"):
        g = 20 * np.log10(y / d)
    g[d < 10 ** (-60 / 20)] = np.nan
    t = (np.arange(len(g)) + 0.5) * w / sample_rate
    step = max(1, len(g) // points)
    return t[::step], g[::step]

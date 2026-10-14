"""Measurements on renders: static compression curve, gain envelope, attack and release.

Levels are peak dBFS for sines (CLAUDE.md conventions). "Gain" is output level
minus input level, so gain reduction is the drop in gain relative to a
reference (usually the lowest input level, where the unit isn't compressing).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np


def rms_dbfs_peak(x: np.ndarray) -> float:
    """Level of a sine segment as peak dBFS: 20 log10(sqrt(2) * rms)."""
    return float(20 * np.log10(np.sqrt(2 * np.mean(np.square(x))) + 1e-20))


def segment_gains(
    x: np.ndarray, y: np.ndarray, segments: Sequence[Mapping[str, Any]], tail: float = 0.3
) -> list[tuple[float, float]]:
    """(input dBFS, gain dB) per stepped segment, measured over its last `tail` fraction.

    Segments come from varimu.measure.signals metadata ({start, stop, level_dbfs}).
    Use a whole number of carrier cycles where possible; `tail` long enough
    covers many cycles and the remainder bias is negligible.
    """
    out = []
    for seg in segments:
        if seg["level_dbfs"] is None:
            continue
        a, b = seg["start"], seg["stop"]
        a = b - max(1, int((b - a) * tail))
        lin, lout = rms_dbfs_peak(x[a:b]), rms_dbfs_peak(y[a:b])
        out.append((lin, lout - lin))
    return out


def envelope_db(x: np.ndarray, sample_rate: int, window_s: float = 0.002) -> np.ndarray:
    """Short-term level (peak dBFS of a sine) from a moving RMS window."""
    w = max(1, int(window_s * sample_rate))
    ms = np.convolve(np.square(x), np.ones(w) / w, mode="same")
    return 10 * np.log10(2 * ms + 1e-20)


@dataclass(frozen=True)
class CvTiming:
    cv_before_v: float
    cv_burst_v: float
    attack_s: float  # CV covers 63% of its swing after the burst starts
    release_63_s: float  # CV recovers 63% of the way after the burst ends
    release_90_s: float


def cv_timing(cv: np.ndarray, sample_rate: int, burst_start: int, burst_stop: int) -> CvTiming:
    """Attack/release read off the control voltage itself (no envelope smoothing).

    The CV is what the simulation exposes that a hardware measurement can't:
    the 6386 grid bias set by the sidechain. Its 63% times are the network's
    effective time constants; the 90% release is closer to how the 670's
    published release times are quoted (several time constants).
    """
    ms = max(1, int(0.001 * sample_rate))
    before = float(np.median(cv[max(0, burst_start - 50 * ms) : burst_start - ms]))
    dur = burst_stop - burst_start
    during = float(np.median(cv[burst_stop - dur // 4 : burst_stop - ms]))
    swing = during - before

    def first(mask):
        hit = np.flatnonzero(mask)
        return hit[0] / sample_rate if len(hit) else float("nan")

    # Progress from 0 (start of the move) to 1 (end), whichever way the CV moves.
    attack = (cv[burst_start:burst_stop] - before) / swing
    release = (during - cv[burst_stop:]) / swing
    tc = 1 - np.exp(-1)  # one time constant
    return CvTiming(
        before, during, first(attack >= tc), first(release >= tc), first(release >= 0.9)
    )


@dataclass(frozen=True)
class BurstTiming:
    gain_before_db: float  # steady gain before the burst
    gain_burst_db: float  # settled gain during the burst
    attack_s: float  # time for gain to cover 63% of its drop
    release_s: float  # time after the burst for gain to recover 63% of the way back
    release_90_s: float  # ... 90% of the way back (closer to how specs quote it)


def burst_timing(
    x: np.ndarray, y: np.ndarray, sample_rate: int, burst_start: int, burst_stop: int
) -> BurstTiming:
    """Attack/release of the gain from a tone burst (varimu.measure.signals.tone_burst)."""
    g = envelope_db(y, sample_rate) - envelope_db(x, sample_rate)
    ms = int(0.005 * sample_rate)
    before = float(np.median(g[max(0, burst_start - 20 * ms) : burst_start - ms]))
    dur = burst_stop - burst_start
    during = float(np.median(g[burst_stop - dur // 4 : burst_stop - ms]))
    drop = before - during

    target = before - 0.63 * drop
    seg = g[burst_start:burst_stop]
    hit = np.flatnonzero(seg <= target)
    attack = hit[0] / sample_rate if len(hit) else float("nan")

    after = g[burst_stop + ms :]
    rel = []
    for frac in (0.63, 0.9):
        hit = np.flatnonzero(after >= during + frac * drop)
        rel.append((hit[0] + ms) / sample_rate if len(hit) else float("nan"))
    return BurstTiming(before, during, attack, rel[0], rel[1])

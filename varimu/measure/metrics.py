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

    def first(progress, level):
        """Time of the first crossing of `level`, interpolated between samples (a
        whole-sample answer would quantize a 0.1 ms attack by ~10%)."""
        hit = np.flatnonzero(progress >= level)
        if not len(hit):
            return float("nan")
        i = hit[0]
        if i == 0:
            return 0.0
        a, b = progress[i - 1], progress[i]
        return (i - 1 + (level - a) / (b - a)) / sample_rate

    # Progress from 0 (start of the move) to 1 (end), whichever way the CV moves.
    attack = (cv[burst_start:burst_stop] - before) / swing
    release = (during - cv[burst_stop:]) / swing
    tc = 1 - np.exp(-1)  # one time constant
    return CvTiming(before, during, first(attack, tc), first(release, tc), first(release, 0.9))


def cv_attack(
    cv: np.ndarray, sample_rate: int, burst_start: int, ref_stop: int, fractions=(0.1, 0.63)
) -> list[float]:
    """Times (s) for the CV to cover each fraction of its fast swing: from its value
    before the burst to its median over the 4 ms ending at `ref_stop` (a few tens of
    ms in). A long burst's CV keeps creeping after that (it tracks the supply's sag
    under the burst at constant gain), so the end of the burst isn't the attack's
    reference."""
    ms = max(1, int(0.001 * sample_rate))
    before = float(np.median(cv[max(0, burst_start - 50 * ms) : burst_start - ms]))
    ref = float(np.median(cv[ref_stop - 4 * ms : ref_stop]))
    p = (cv[burst_start:ref_stop] - before) / (ref - before)
    out = []
    for f in fractions:
        hit = np.flatnonzero(p >= f)
        if not len(hit):
            out.append(float("nan"))
            continue
        i = hit[0]
        out.append(0.0 if i == 0 else (i - 1 + (f - p[i - 1]) / (p[i] - p[i - 1])) / sample_rate)
    return out


def cv_release_estimate(
    cv: np.ndarray, sample_rate: int, burst_stop: int, before_v: float, during_v: float
) -> tuple[float, bool]:
    """The CV's 90% release time (s) after `burst_stop`, and whether it was
    extrapolated: when the window ends before the CV is 90% back, the remaining
    distance's decay rate over the window's second half carries it on (the slowest
    part of a multi-capacitor release, so an upper estimate). inf if the CV isn't
    coming back at all."""
    rem = (cv[burst_stop:] - before_v) / (during_v - before_v)  # 1 at release start, 0 back
    hit = np.flatnonzero(rem <= 0.1)
    if len(hit):
        return hit[0] / sample_rate, False
    n = len(rem)
    ms = max(1, int(0.001 * sample_rate))
    r1 = float(np.median(rem[n // 2 - 10 * ms : n // 2 + 10 * ms]))
    r2 = float(np.median(rem[n - 20 * ms :]))
    if not (0 < r2 < r1):
        return float("inf"), True
    rate = np.log(r1 / r2) / ((n - 10 * ms - n // 2) / sample_rate)
    return (n - 10 * ms) / sample_rate + np.log(r2 / 0.1) / rate, True


def gain_attack(
    x: np.ndarray,
    y: np.ndarray,
    sample_rate: int,
    freq_hz: float,
    burst_start: int,
    burst_stop: int,
    levels_db=(1.0, 3.0, 6.0),
) -> list[float]:
    """Times (s, at the end of the half period that gets there) for the gain to fall by
    each of `levels_db`: the output's peak per half period of the tone re the input's,
    against the gain over the 50 ms before the burst. No smoothing window, so this
    resolves a sub-millisecond attack (an envelope's window would smear it)."""
    hp = round(sample_rate / freq_hz / 2)
    pre = slice(max(0, burst_start - int(0.05 * sample_rate)), burst_start)
    g0 = 20 * np.log10(np.max(np.abs(y[pre])) / np.max(np.abs(x[pre])))
    n = (burst_stop - burst_start) // hp * hp
    seg = slice(burst_start, burst_start + n)
    gy = np.abs(y[seg]).reshape(-1, hp).max(1)
    gx = np.abs(x[seg]).reshape(-1, hp).max(1)
    gr = g0 - 20 * np.log10(gy / gx)
    out = []
    for db in levels_db:
        hit = np.flatnonzero(gr >= db)
        out.append((hit[0] + 1) * hp / sample_rate if len(hit) else float("nan"))
    return out


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
    # The burst's last quarter, short of its end (for a short peak, by less than ms).
    during = float(np.median(g[burst_stop - dur // 4 : burst_stop - min(ms, dur // 8)]))
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


# --- Spectral measurements (Phase 4) ------------------------------------------------------


@dataclass(frozen=True)
class Harmonics:
    """A steady tone's output fitted at its frequency's multiples (least squares)."""

    freq_hz: float
    amps: np.ndarray  # peak amplitude of harmonic k = 1, 2, ... (fit units)
    residual_rms: float  # what the harmonics leave over (hum, noise, oscillation)
    residual_hz: float  # the residual's strongest frequency
    # The residual's strongest spectral peak more than SPUR_GUARD_HZ from every
    # harmonic (and from DC): an oscillation, not the tone's own modulation (a
    # gain still settling leaves sidebands close to the harmonics).
    spur_amp: float = 0.0
    spur_hz: float = 0.0

    @property
    def thd(self) -> float:
        """sqrt(sum of harmonics 2.. squared) / fundamental."""
        return float(np.sqrt(np.sum(self.amps[1:] ** 2)) / self.amps[0])

    def db(self, k: int) -> float:
        """Harmonic k re the fundamental (dB); -inf past the fit."""
        if k > len(self.amps):
            return float("-inf")
        return float(20 * np.log10(self.amps[k - 1] / self.amps[0] + 1e-300))

    @property
    def residual_db(self) -> float:
        """The residual's rms re the fundamental's rms (dB)."""
        return float(20 * np.log10(self.residual_rms / (self.amps[0] / np.sqrt(2)) + 1e-300))

    @property
    def spur_db(self) -> float:
        """The strongest spur's amplitude re the fundamental (dB)."""
        return float(20 * np.log10(self.spur_amp / self.amps[0] + 1e-300))


SPUR_GUARD_HZ = 300.0


def harmonics(
    y: np.ndarray, freq_hz: float, sample_rate: int, n_harmonics: int = 9, dc: bool = True
) -> Harmonics:
    """Fit y with sines and cosines at k * freq_hz (k = 1 .. n_harmonics, below Nyquist)
    plus a constant. Use a whole number of periods of freq_hz for an exact fit."""
    t = np.arange(len(y)) / sample_rate
    ks = [k for k in range(1, n_harmonics + 1) if k * freq_hz < 0.5 * sample_rate]
    cols = [np.ones_like(t)] if dc else []
    for k in ks:
        w = 2 * np.pi * k * freq_hz * t
        cols += [np.sin(w), np.cos(w)]
    a = np.column_stack(cols)
    coef, *_ = np.linalg.lstsq(a, y, rcond=None)
    c = coef[1:] if dc else coef
    amps = np.hypot(c[0::2], c[1::2])
    res = y - a @ coef
    w = np.hanning(len(res))
    spec = np.abs(np.fft.rfft(res * w))
    f = np.fft.rfftfreq(len(res), 1 / sample_rate)
    res_hz = float(f[np.argmax(spec)])
    near = np.abs(f - freq_hz * np.round(f / freq_hz)) < SPUR_GUARD_HZ
    far = np.where(near, 0.0, spec)
    i = int(np.argmax(far))
    spur_amp = float(2 * far[i] / np.sum(w))  # a sinusoid's amplitude through the window
    return Harmonics(freq_hz, amps, float(np.sqrt(np.mean(res**2))), res_hz, spur_amp, float(f[i]))


def tone_amplitudes(y: np.ndarray, freqs_hz, sample_rate: int) -> np.ndarray:
    """Complex amplitudes of y at each frequency (one DFT bin each: use a whole number of
    periods of every frequency for no leakage)."""
    t = np.arange(len(y)) / sample_rate
    return np.array([2 * np.mean(y * np.exp(-2j * np.pi * f * t)) for f in freqs_hz])


def smpte_imd(y: np.ndarray, f_lo: float, f_hi: float, sample_rate: int, orders: int = 4) -> float:
    """SMPTE / DIN intermodulation: the rms sum of the sidebands f_hi +- n f_lo (n = 1 ..
    orders) re the f_hi carrier (a fraction). Whole periods of both tones."""
    side = [f_hi + s * n * f_lo for n in range(1, orders + 1) for s in (-1, 1)]
    a = np.abs(tone_amplitudes(y, [f_hi, *side], sample_rate))
    return float(np.sqrt(np.sum(a[1:] ** 2)) / a[0])


def ccif_imd(y: np.ndarray, f1: float, f2: float, sample_rate: int) -> dict[str, float]:
    """CCIF twin-tone intermodulation re the two tones' rms sum (fractions): the
    difference tone f2 - f1 (2nd order) and 2 f1 - f2, 2 f2 - f1 (3rd order)."""
    d = f2 - f1
    a = np.abs(tone_amplitudes(y, [f1, f2, d, 2 * f1 - f2, 2 * f2 - f1], sample_rate))
    ref = np.sqrt(a[0] ** 2 + a[1] ** 2)
    return {"d2": float(a[2] / ref), "d3": float(np.hypot(a[3], a[4]) / ref)}


def lowpass(y: np.ndarray, cutoff_hz: float, sample_rate: int, order: int = 8) -> np.ndarray:
    """Zero-phase Butterworth low-pass (forward-backward)."""
    from scipy.signal import butter, sosfiltfilt

    sos = butter(order // 2, cutoff_hz, "low", fs=sample_rate, output="sos")
    return sosfiltfilt(sos, y)

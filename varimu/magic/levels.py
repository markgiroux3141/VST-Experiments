"""Noise-forced gain staging (ANALOG_MAGIC_FABLE.md AM6): a stage's impairment against its
input level, (noise^2 + character^2) / signal^2, and the level where it is least.

A-weighting from IEC 61672-1's analog poles (20.598997, 107.65265, 737.86223 and
12194.217 Hz; web: https://en.wikipedia.org/wiki/A-weighting, citing IEC 61672-1:2013),
bilinear-transformed (prewarped at 1 kHz) and normalized to 0 dB at 1 kHz.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

A_POLES_HZ = (20.598997, 107.65265, 737.86223, 12194.217)


def a_weight_sos(fs: float) -> np.ndarray:
    f1, f2, f3, f4 = A_POLES_HZ
    w = 2 * np.pi
    z = [0, 0, 0, 0]
    p = [-w * f1, -w * f1, -w * f4, -w * f4, -w * f2, -w * f3]
    k = 1.0
    zd, pd, kd = signal.bilinear_zpk(z, p, k, fs)
    sos = signal.zpk2sos(zd, pd, kd)
    _, h = signal.sosfreqz(sos, worN=[1000.0], fs=fs)
    sos[0, :3] /= np.abs(h[0])
    return sos


def a_gain(f_hz: np.ndarray) -> np.ndarray:
    """The analog A-weighting magnitude (IEC 61672-1's formula), 0 dB at 1 kHz."""
    f1, f2, f3, f4 = A_POLES_HZ
    f2_ = np.asarray(f_hz, float) ** 2
    r = (f4**2 * f2_**2) / ((f2_ + f1**2) * np.sqrt((f2_ + f2**2) * (f2_ + f3**2)) * (f2_ + f4**2))
    r1k = (f4**2 * 1e12) / ((1e6 + f1**2) * np.sqrt((1e6 + f2**2) * (1e6 + f3**2)) * (1e6 + f4**2))
    return r / r1k


def a_weight(x: np.ndarray, fs: float) -> np.ndarray:
    """x A-weighted with the analog magnitude exactly (zero phase, in the frequency
    domain): the bilinear filter (a_weight_sos) reads 0.25 dB low at 10 kHz at 96 kHz."""
    x = np.asarray(x, float)
    X = np.fft.rfft(x)
    return np.fft.irfft(X * a_gain(np.fft.rfftfreq(len(x), 1 / fs)), len(x))


def a_rms(x: np.ndarray, fs: float, skip_s: float = 0.2) -> float:
    y = a_weight(x, fs)[int(skip_s * fs) :]
    return float(np.sqrt(np.mean(y * y)))


def optimum(levels_db: np.ndarray, impairment: np.ndarray) -> float:
    """The level of the least impairment, refined by a parabola through the three points
    around the grid's minimum (in dB of impairment)."""
    lv = np.asarray(levels_db, float)
    im = 10 * np.log10(np.asarray(impairment, float))
    i = int(np.argmin(im))
    if 0 < i < len(lv) - 1:
        a, b, c = im[i - 1], im[i], im[i + 1]
        den = a - 2 * b + c
        if den > 0:
            return float(lv[i] + 0.5 * (a - c) / den * (lv[1] - lv[0]))
    return float(lv[i])

"""Oscillators (tube synth S4): pitch, its stability and the spectrum's cleanliness, read
off a rendered waveform.

- `frequency`: the mean frequency over a stretch, from interpolated upward zero crossings
  of the signal less its mean (any periodic waveform crosses its mean once each way per
  cycle, unless it rings: a waveform that does is read through a low-pass first).
- `cycle_frequencies`: one frequency per cycle, at the cycle's end: glide, drift and
  ripple FM.
- `harmonics_db`: the first harmonics' levels re the fundamental.
- `inharmonic_db`: the power that isn't at a harmonic of f0 (aliases, FM sidebands,
  subharmonics, hum) re the harmonics' power, in a Blackman-Harris window. An oscillator's
  supply ripple puts FM sidebands beside each harmonic: masked with `sidebands_hz`, what
  is left is aliasing and noise (compare the qualities, as amp_suite's aliasing does).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfiltfilt
from scipy.signal.windows import blackmanharris


def _crossings(y: np.ndarray, fs: float, lowpass_hz: float | None) -> np.ndarray:
    """Times (s) of the upward crossings of y's mean, interpolated between samples."""
    y = np.asarray(y, float)
    if lowpass_hz is not None:
        y = sosfiltfilt(butter(4, lowpass_hz, fs=fs, output="sos"), y)
    y = y - y.mean()
    i = np.nonzero((y[:-1] < 0.0) & (y[1:] >= 0.0))[0]
    return (i + -y[i] / (y[i + 1] - y[i])) / fs


def frequency(y: np.ndarray, fs: float, *, lowpass_hz: float | None = None) -> float:
    """Mean frequency (Hz) over y; nan with fewer than three cycles."""
    t = _crossings(y, fs, lowpass_hz)
    if len(t) < 3:
        return float("nan")
    return (len(t) - 1) / (t[-1] - t[0])


def cycle_frequencies(
    y: np.ndarray, fs: float, *, lowpass_hz: float | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """(time at each cycle's end in s, that cycle's frequency in Hz)."""
    t = _crossings(y, fs, lowpass_hz)
    return t[1:], 1.0 / np.diff(t)


def smoothed(t: np.ndarray, f: np.ndarray, window_s: float) -> np.ndarray:
    """Per-cycle frequencies f (at times t) averaged over the cycles within +-window_s / 2."""
    lo = np.searchsorted(t, t - 0.5 * window_s)
    hi = np.searchsorted(t, t + 0.5 * window_s, side="right")
    c = np.concatenate([[0.0], np.cumsum(f)])
    return (c[hi] - c[lo]) / (hi - lo)


def cents(f: np.ndarray | float, ref: float) -> np.ndarray | float:
    return 1200.0 * np.log2(np.asarray(f) / ref)


def _spectrum(y: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y, float) - np.mean(y)
    w = blackmanharris(len(y))
    p = np.abs(np.fft.rfft(y * w)) ** 2
    return np.fft.rfftfreq(len(y), 1.0 / fs), p


def harmonics_db(y: np.ndarray, fs: float, f0: float, n: int = 20) -> np.ndarray:
    """The levels of harmonics 1..n (dB re the fundamental; -inf above fs / 2)."""
    f, p = _spectrum(y, fs)
    df = f[1]
    out = np.full(n, -np.inf)
    for k in range(1, n + 1):
        if k * f0 >= fs / 2:
            break
        j = int(round(k * f0 / df))
        out[k - 1] = p[max(j - 4, 0) : j + 5].sum()
    return 10.0 * np.log10(out / out[0])


def inharmonic_db(
    y: np.ndarray,
    fs: float,
    f0: float,
    *,
    band_hz: float = 20000.0,
    lobe_bins: int = 5,
    sidebands_hz: tuple[float, ...] = (),
    spread_hz: float = 0.0,
) -> float:
    """Power off the harmonics of f0 within `band_hz`, re the harmonics' power (dB). A
    harmonic owns +-lobe_bins bins (Blackman-Harris' main lobe is +-4), and with
    `sidebands_hz` also its sidebands at each of those offsets (the supply ripple's FM:
    multiples of the mains frequency), so what is left is aliasing and noise. `spread_hz`:
    the fundamental's spread within the window (a glide, drift): harmonic k owns k times
    it more on each side."""
    f, p = _spectrum(y, fs)
    df = f[1]
    inb = (f > 0.5 * f0) & (f <= band_hz)
    harm = np.zeros(len(f), bool)
    k = np.arange(1, int(band_hz / f0) + 1)
    offsets = (0.0, *sidebands_hz, *(-x for x in sidebands_hz))
    for kk in k:
        w = lobe_bins + int(np.ceil(kk * spread_hz / df))
        for off in offsets:
            j = (kk * f0 + off) / df
            if j > 0:
                harm[max(int(j) - w, 0) : int(j) + w + 2] = True
    on = p[inb & harm].sum()
    off = p[inb & ~harm].sum()
    return 10.0 * np.log10(off / on + 1e-30)

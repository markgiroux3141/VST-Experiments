"""Dispersion before saturation (ANALOG_MAGIC_FABLE.md AM5): each stage's small-signal phase
measured by rendering a sweep (varimu.measure.ac refuses circuits with devices), the chain's
accumulated phase as an all-pass FIR, and the commutator of that all-pass with a saturating
stage.

`small_signal` takes a render function f(x) -> y (dBFS in, dBFS out, same length), so a
circuit, the 351 or the tape machine are measured alike.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy import optimize, signal

SWEEP_LO_HZ, SWEEP_HI_HZ = 10.0, 40000.0


def exp_sweep(fs: int, seconds: float = 10.0, level_dbfs: float = -40.0) -> np.ndarray:
    """An exponential sine sweep 10 Hz - 40 kHz (peak level_dbfs), 50 ms fades, 0.5 s of
    silence after it (the response's tail)."""
    t = np.arange(int(seconds * fs)) / fs
    k = np.log(SWEEP_HI_HZ / SWEEP_LO_HZ)
    x = np.sin(2 * np.pi * SWEEP_LO_HZ * seconds / k * (np.exp(t * k / seconds) - 1))
    f = int(0.05 * fs)
    x[:f] *= np.linspace(0, 1, f)
    x[-f:] *= np.linspace(1, 0, f)
    return np.concatenate([x * 10 ** (level_dbfs / 20), np.zeros(int(0.5 * fs))])


def small_signal(
    render: Callable[[np.ndarray], np.ndarray],
    fs: int,
    *,
    seconds: float = 10.0,
    level_dbfs: float = -40.0,
    n_freqs: int = 400,
) -> dict:
    """(f, H) of a stage on a log grid 12 Hz - 30 kHz, from one sweep: H = FFT(y) / FFT(x)
    (the sweep's band only), the pure delay (the unwrapped phase's slope between 1 and
    5 kHz) taken out and reported."""
    x = exp_sweep(fs, seconds, level_dbfs)
    y = np.asarray(render(x), float)[: len(x)]
    n = 1 << int(np.ceil(np.log2(len(x))))
    X, Y = np.fft.rfft(x, n), np.fft.rfft(y, n)
    f = np.fft.rfftfreq(n, 1 / fs)
    sel = (f >= 12) & (f <= 30000)
    H = Y[sel] / X[sel]
    ff = f[sel]
    ph = np.unwrap(np.angle(H))
    band = (ff >= 1000) & (ff <= 5000)
    slope = np.polyfit(2 * np.pi * ff[band], ph[band], 1)[0]
    # A pure delay is whole samples here (a head distance, a converter); the slope's
    # fraction is the stages' own phase, kept.
    delay_s = round(-slope * fs) / fs
    # Remove the delay; keep the phase at 1 kHz as it is (no 2 pi offsets).
    H = H * np.exp(2j * np.pi * ff * delay_s)
    grid = np.geomspace(12, 30000, n_freqs)
    # Smooth onto the grid: average H over a 1/24 octave around each grid point.
    Hg = np.empty(len(grid), complex)
    for i, fc in enumerate(grid):
        s = (ff >= fc * 2 ** (-1 / 48)) & (ff <= fc * 2 ** (1 / 48))
        Hg[i] = (
            H[s].mean() if s.any() else np.interp(fc, ff, H.real) + 1j * np.interp(fc, ff, H.imag)
        )
    return {"f": grid, "H": Hg, "delay_s": float(delay_s)}


def group_delay(f: np.ndarray, H: np.ndarray) -> np.ndarray:
    """-d(phase)/d(omega), seconds."""
    ph = np.unwrap(np.angle(H))
    return -np.gradient(ph, 2 * np.pi * np.asarray(f))


def hp_phase(f: np.ndarray, n_poles: float, f0: float) -> np.ndarray:
    """Phase of n first-order high-passes at f0 (radians, leading)."""
    return n_poles * np.arctan(f0 / np.asarray(f))


def fit_poles(f: np.ndarray, H: np.ndarray, f_max: float = 200.0) -> dict:
    """The count n and corner f0 of first-order high-passes whose phase best fits the
    cumulative phase below f_max (the phase referred to 1 kHz's, where it is ~flat)."""
    ph = np.unwrap(np.angle(H))
    ph = ph - ph[np.argmin(np.abs(f - 1000))]
    s = f <= f_max

    def resid(p):
        return hp_phase(f[s], p[0], p[1]) - hp_phase(1000.0, p[0], p[1]) - ph[s]

    r = optimize.least_squares(resid, [4.0, 10.0], bounds=([0.0, 0.1], [200.0, 200.0]))
    return {
        "n_poles": float(r.x[0]),
        "f0_hz": float(r.x[1]),
        "rms_err_deg": float(np.degrees(np.sqrt(np.mean(r.fun**2)))),
    }


def allpass_fir(f: np.ndarray, H: np.ndarray, fs: int, n: int = 2**16) -> np.ndarray:
    """Unit magnitude, the chain's phase: irfft(exp(j phase)) on n bins (the phase
    interpolated from the log grid, held flat outside it), rotated to be causal, windowed
    (Hann over the last quarter)."""
    fb = np.fft.rfftfreq(n, 1 / fs)
    ph = np.unwrap(np.angle(H))
    # A real filter's phase at DC and at Nyquist is a multiple of pi: the grid's ends are
    # joined linearly to the nearest multiples (a phase that goes as f near DC, as every
    # high-pass's and all-pass's does).
    p0 = np.round(ph[0] / np.pi) * np.pi
    pn = np.round(ph[-1] / np.pi) * np.pi
    phb = np.interp(fb, np.r_[0.0, f, fs / 2], np.r_[p0, ph, pn])
    h = np.fft.irfft(np.exp(1j * phb), n)
    # Causal: the energy's centre to the first quarter.
    shift = n // 4
    h = np.roll(h, shift)
    w = np.ones(n)
    q = n // 4
    w[-q:] = np.hanning(2 * q)[q:]
    w[: shift // 4] = np.hanning(2 * (shift // 4))[: shift // 4]
    return h * w


def apply_fir(h: np.ndarray, x: np.ndarray, shift: int | None = None) -> np.ndarray:
    """x through h, the bulk shift (n // 4, allpass_fir's rotation) taken out, same length."""
    s = len(h) // 4 if shift is None else shift
    y = signal.fftconvolve(x, h)
    return y[s : s + len(x)]


def first_order_allpass(f0: float, fs: int):
    c = (np.tan(np.pi * f0 / fs) - 1) / (np.tan(np.pi * f0 / fs) + 1)
    return [c, 1.0], [1.0, c]

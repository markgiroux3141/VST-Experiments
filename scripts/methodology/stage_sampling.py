# ruff: noqa: B023  (the Newton lambdas are called within their iteration)
"""Toy check: do a DIRK method's stage values, used as extra (nonuniform) output samples,
suppress aliasing like running the whole solve at twice the rate?

Circuit: a diode clipper, C v' = (u - v)/R - 2 Is sinh(v / Vt), driven hard at 2902 Hz.
Solver: TR-BDF2 (stage at gamma h, end at h), Newton to 1e-12.

Compared at a 48 kHz output:
  points   the 48 kHz run's end points (what a 1x run gives)
  stages   the 48 kHz run's end points + stage values -> a 96 kHz stream by a
           least-squares interpolator for recurrent nonuniform samples -> decimated
  run2x    a 96 kHz run's end points, decimated (twice the solves)
  truth    a 768 kHz run decimated in one go
"""

from __future__ import annotations

import numpy as np
from scipy import signal

R, C, IS, VT = 2200.0, 10e-9, 2.52e-9, 0.045
GAMMA = 2.0 - np.sqrt(2.0)  # TR-BDF2's stage time (fraction of the step)
F0, AMP = 2902.0, 10.0


def f(v, u):
    return ((u - v) / R - 2 * IS * np.sinh(v / VT)) / C


def dfdv(v):
    return (-1.0 / R - 2 * IS / VT * np.cosh(v / VT)) / C


def newton(g, dg, v):
    for _ in range(200):
        r = g(v)
        step = r / dg(v)
        # damp: diode limiting
        step = np.clip(step, -0.3, 0.3)
        v -= step
        if abs(step) < 1e-13:
            break
    return v


def trbdf2(fs, seconds, u_of_t):
    h = 1.0 / fs
    n = int(round(seconds * fs))
    ends = np.zeros(n)
    stages = np.zeros(n)
    v = 0.0
    g = GAMMA
    for k in range(n):
        t = k * h
        u0, ug, u1 = u_of_t(t), u_of_t(t + g * h), u_of_t(t + h)
        f0 = f(v, u0)
        # TR over gamma h
        vg = newton(
            lambda x: x - v - 0.5 * g * h * (f0 + f(x, ug)),
            lambda x: 1 - 0.5 * g * h * dfdv(x),
            v,
        )
        # BDF2 over the rest
        a = 1.0 / (g * (2 - g))
        b = (1 - g) ** 2 / (g * (2 - g))
        c = (1 - g) / (2 - g)
        v1 = newton(
            lambda x: x - a * vg + b * v - c * h * f(x, u1),
            lambda x: 1 - c * h * dfdv(x),
            vg,
        )
        stages[k] = vg  # at t + g h
        ends[k] = v1  # at t + h
        v = v1
    return ends, stages


def interpolator(half=24, band=0.92, reg=1e-9):
    """Weights for v((n + 1/2) T) from v(kT) and v((k - 1 + GAMMA) T + T) = v((k + GAMMA) T),
    k = n - half + 1 .. n + half, least squares over |f| < band * fs (two Nyquist zones)."""
    ks = np.arange(-half + 1, half + 1)
    times = np.concatenate([ks.astype(float), ks + GAMMA])  # in units of T
    fgrid = np.linspace(-band, band, 2001)  # in units of fs
    a = np.exp(2j * np.pi * np.outer(fgrid, times))
    d = np.exp(2j * np.pi * fgrid * 0.5)
    ar = np.vstack([a.real, a.imag, np.sqrt(reg) * np.eye(len(times))])
    dr = np.concatenate([d.real, d.imag, np.zeros(len(times))])
    w, *_ = np.linalg.lstsq(ar, dr, rcond=None)
    return ks, w[: len(ks)], w[len(ks) :]


def alias_db(y, fs, n_fft):
    """Inharmonic power re the harmonics above the fundamental (dB), 20 Hz - 20 kHz."""
    y = y[-n_fft:]
    spec = np.abs(np.fft.rfft(y * signal.windows.blackmanharris(n_fft))) ** 2
    freqs = np.fft.rfftfreq(n_fft, 1 / fs)
    harm = np.zeros(len(freqs), bool)
    k = 1
    while k * F0 < fs / 2:
        harm |= np.abs(freqs - k * F0) < 12.0
        k += 1
    band = (freqs > 20) & (freqs < 20000)
    fund = np.abs(freqs - F0) < 12.0
    p_h = spec[band & harm & ~fund].sum()
    p_a = spec[band & ~harm].sum()
    return 10 * np.log10(p_a / p_h)


def main():
    fs = 48000
    seconds = 1.5
    u = lambda t: AMP * np.sin(2 * np.pi * F0 * t)  # noqa: E731
    dec2 = signal.firwin(255, 0.5 - 0.04, window=("kaiser", 12.0))

    ends, stages = trbdf2(fs, seconds, u)
    # ends[k] is v((k + 1) T); stages[k] is v((k + GAMMA) T)
    ks, wa, wb = interpolator()
    n = len(ends)
    v_grid = np.concatenate([[0.0], ends])  # v(kT), k = 0..n
    mid = np.zeros(n)
    for m in range(40, n - 40):
        # v((m + 1/2) T) from v((m + k) T) and v((m + k + GAMMA) T)
        mid[m] = wa @ v_grid[m + ks] + wb @ stages[m + ks]
    up = np.zeros(2 * n)
    up[0::2] = v_grid[:n]
    up[1::2] = mid
    y_stage = signal.lfilter(dec2, 1.0, up)[::2]

    e2, _ = trbdf2(2 * fs, seconds, u)
    y_2x = signal.lfilter(dec2, 1.0, np.concatenate([[0.0], e2])[: 2 * n])[::2]

    over = 16
    e16, _ = trbdf2(over * fs, seconds, u)
    dec16 = signal.firwin(over * 128 + 1, 0.92 / over, window=("kaiser", 14.0))
    y_true = signal.lfilter(dec16, 1.0, e16)[::over]

    n_fft = 48000
    print(f"points  (1x end points)             {alias_db(ends, fs, n_fft):7.1f} dB")
    print(f"stages  (1x end points + stages)    {alias_db(y_stage[: n - 60], fs, n_fft):7.1f} dB")
    print(f"run2x   (2x run, decimated)         {alias_db(y_2x, fs, n_fft):7.1f} dB")
    print(f"truth   (16x run, decimated)        {alias_db(y_true, fs, n_fft):7.1f} dB")


if __name__ == "__main__":
    main()

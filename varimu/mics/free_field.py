"""A capsule in free field, driven by a plane wave from an angle (MIC_ROOM_PLAN.md: "free
field first"): the pressures at its front and rear entries.

A plane wave from angle theta (0: on axis, from the front) reaches the front entry and,
`path_m` cos(theta) later, the rear entry: the pressure-gradient capsule's drive. The
phase reference is the capsule's centre (front leads by half the delay, rear lags by
half). `path_m` is the capsule's effective front-to-rear path (around the capsule and
its head basket: a fitted, bounded value). Diffraction by the body and basket (the
pressure build-up on the front face at high frequencies) is a later fidelity item
(MIC_ROOM_PLAN.md); here both entries see the free-field pressure.

For renders: `entry_pressures(p, theta, path_m, fs)` gives the two pressure signals
(the rear the front delayed by a fractional number of samples, an FFT delay on the
whole signal).
"""

from __future__ import annotations

import numpy as np

from varimu.devices.capsule import C_AIR


def entry_factors(
    f_hz: np.ndarray, theta_rad: float, path_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """Complex pressure at the front and rear entries per pascal of the plane wave at
    the capsule's centre."""
    w = 2 * np.pi * np.asarray(f_hz, float)
    tau = path_m * np.cos(theta_rad) / C_AIR
    return np.exp(0.5j * w * tau), np.exp(-0.5j * w * tau)


def _delay(x: np.ndarray, delay_s: float, fs: int) -> np.ndarray:
    n = len(x)
    m = 1 << int(np.ceil(np.log2(2 * n)))
    f = np.fft.rfftfreq(m, 1.0 / fs)
    y = np.fft.irfft(np.fft.rfft(x, m) * np.exp(-2j * np.pi * f * delay_s), m)
    return y[:n]


def entry_pressures(
    p: np.ndarray, theta_rad: float, path_m: float, fs: int
) -> tuple[np.ndarray, np.ndarray]:
    """The front and rear entries' pressure signals for a plane wave whose pressure at
    the capsule's centre is `p` (pascals at fs)."""
    tau = path_m * np.cos(theta_rad) / C_AIR
    return _delay(p, -0.5 * tau, fs), _delay(p, 0.5 * tau, fs)

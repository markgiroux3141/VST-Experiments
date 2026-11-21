"""I14, the Buzz Zither: keyed steel strings over curved (jawari) bridges.

The phenomenon is a distributed one-sided contact. A string leaving a gently curved bridge
grazes it once a cycle; the contact point slides with the amplitude, which shortens the
string for part of each cycle and pumps energy upward into a bright, sweeping formant
that sustains (the tanpura's and sitar's buzz: Raman 1921; Valette 1995; van Walstijn,
Bridges & Mehes, DAFx-16, the model this follows). No instrument here has it: the
Clavinet's and the harp's contacts are points at a hammer or tangent.

The model: a finite-difference stiff-free string (the plain wave equation, frequency-
dependent loss sigma0 + sigma1), fixed at both ends, over a parabolic bridge occupying its
first BRIDGE_M; the contact a one-sided linear penalty per unit length,
solved implicitly at each bridge point (stiff: rigid in effect). The soundboard reads the
force on the bridge: the string's end tension plus every
contact force. JAWARI sets the bridge's curvature (0 = a sharp bridge, no buzz).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from .common import FS

OVERSAMPLE = 2
LENGTH_M = 1.0  # a tanpura's speaking length: provisional, model knowledge
RHO_A = 6.0e-4  # kg/m, a 0.31 mm steel string: provisional, model knowledge
BRIDGE_M = 0.012  # the jawari's contact length: provisional, model knowledge
DROP_M = 50e-6  # the bridge's drop over that length at JAWARI 1: provisional, model knowledge
K_CONTACT = 1e11  # penalty, N/m^2: numerics (implicit per point: rigid in effect, stable)
T60_LOW_S = 12.0  # decay of the fundamental (steel on bone): provisional, model knowledge
T60_HIGH_S = 2.0  # at 5 kHz


def string(
    f0_hz: float,
    seconds: float,
    pluck_amp_m: float,
    jawari: float = 1.0,
    pluck_at: float = 0.3,
    damp_at_s: float | None = None,
    length_m: float = LENGTH_M,
) -> np.ndarray:
    """Force on the bridge (N) at FS after one pluck at t = 0."""
    fs = FS * OVERSAMPLE
    k = 1 / fs
    c = 2 * length_m * f0_hz
    h = c * k / 0.98  # Courant 0.98
    nx = int(length_m / h)
    h = length_m / nx
    lam2 = (c * k / h) ** 2
    # sigma0, sigma1 from two decay times (Bilbao, Numerical Sound Synthesis, 7.1)
    w1, w2 = 2 * math.pi * f0_hz, 2 * math.pi * 5000.0
    xi1 = (w1 / c) ** 2  # the wavenumber squared at w (no stiffness)
    xi2 = (w2 / c) ** 2
    s1 = 6 * math.log(10) / (xi2 - xi1) * (1 / T60_HIGH_S - 1 / T60_LOW_S)
    s0 = 6 * math.log(10) / (xi2 - xi1) * (xi2 / T60_LOW_S - xi1 / T60_HIGH_S)
    s1 = max(s1, 0.0)
    if lam2 + 4 * s1 * k / (h * h) > 1:
        raise ValueError("unstable: lower T60_HIGH_S or Courant")
    x = np.arange(nx + 1) * h
    nb = int(BRIDGE_M / h) + 1 if jawari > 0 else 0  # a sharp bridge: no contact
    xb = x[:nb]
    bridge = -jawari * DROP_M * (xb / BRIDGE_M) ** 2  # height of the bridge under the string
    u = np.zeros(nx + 1)
    # a plucked shape (a finger: rounded triangle), at rest
    p = pluck_at * length_m
    tri = np.where(x < p, x / p, (length_m - x) / (length_m - p))
    u = pluck_amp_m * signal.savgol_filter(tri, 9, 2)
    u[0] = u[-1] = 0.0
    u1 = u.copy()
    steps = int(seconds * fs)
    out = np.empty(steps)
    a0 = 1 / (1 + s0 * k)
    bs = 2 * s1 * k / (h * h)
    kc = a0 * K_CONTACT * k * k / RHO_A
    t_n = c * c * RHO_A  # tension
    damp_step = None if damp_at_s is None else int(damp_at_s * fs)
    for n in range(steps):
        if n == damp_step:  # the key's felt damper
            s0 *= 60.0
            a0 = 1 / (1 + s0 * k)
        lap = np.empty_like(u)
        lap[1:-1] = u[2:] - 2 * u[1:-1] + u[:-2]
        lap[0] = lap[-1] = 0.0
        lap1 = np.empty_like(u)
        lap1[1:-1] = u1[2:] - 2 * u1[1:-1] + u1[:-2]
        lap1[0] = lap1[-1] = 0.0
        un = a0 * (2 * u - (1 - s0 * k) * u1 + lam2 * lap + bs * (lap - lap1))
        # the contact, implicit per point: un = un_free + kc (b - un) where it touches
        contact_n = 0.0
        if nb:
            free = un[1:nb]
            touch = free < bridge[1:nb]
            if touch.any():
                fixed = (free + kc * bridge[1:nb]) / (1 + kc)
                contact_n = K_CONTACT * h * float(np.sum((bridge[1:nb] - fixed)[touch]))
                un[1:nb] = np.where(touch, fixed, free)
        un[0] = un[-1] = 0.0
        u1, u = u, un
        out[n] = t_n * u[1] / h + contact_n
    return signal.resample_poly(out, 1, OVERSAMPLE)


def soundboard(x: np.ndarray) -> np.ndarray:
    """A gourd and a top: a few broad body resonances (provisional, design choice)."""
    y = x.copy()
    for f, q, gn in ((180.0, 4.0, 1.5), (420.0, 5.0, 1.0), (1100.0, 3.0, 0.6), (2600.0, 2.0, 0.4)):
        b, a = signal.iirpeak(f, q, fs=FS)
        y += gn * signal.lfilter(b, a, x)
    return y

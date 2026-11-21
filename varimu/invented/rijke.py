"""I7, the Rijke Organ: pipes that sing from heat (sketched 2026-11-21).

The phenomenon is thermoacoustics (Rijke 1859; Rayleigh's criterion): a hot gauze a
quarter of the way up a vertical open pipe gives heat to the rising air in step with the
acoustic velocity, a little late, and the pipe sings at its own modes. Each key heats its
pipe's gauze through a resistor; the gauze's thermal lag makes the attack a slow bloom
and the release a slow fade, and the instability is subcritical (Hopf), so a note starts
suddenly once the gauze passes a threshold and holds below it (hysteresis).

The model is the standard reduced Rijke tube (Balasubramanian & Sujith, Phys. Fluids 20,
044103, 2008; Juniper, JFM 667, 2011): Galerkin modes of an open-open duct in time units
of L / c, the heat release by King's law with a time lag,
    eta_j'' + 2 zeta_j omega_j eta_j' + omega_j^2 eta_j
        = -j pi K [sqrt|1/3 + u_f(t - tau)| - sqrt(1/3)] sin(j pi x_f),
    u_f = sum cos(j pi x_f) eta_j,  omega_j = j pi,
    zeta_j = (c1 omega_j / omega_1 + c2 sqrt(omega_1 / omega_j)) / (2 pi),
with their c1 = 0.1, c2 = 0.06, x_f = 0.29 and tau = 0.45 (dimensionless; at their 0.2 a
key here sings ~3 % sharp). K is the heater's
power. The sound is the volume velocity leaving both open ends, differentiated (two
monopoles). Seeded turbulence forces the modes a little (the hot plume's breath).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from .common import FS, smooth_noise

C_AIR = 343.0
X_F = 0.29
TAU = 0.45  # chosen in their range so the fundamental sings in this pipe
C1, C2 = 0.1, 0.06
MODES = 8
K_PLAY = 0.8  # the heater's power when a key is held (K): design choice (above the Hopf point)
GAUZE_S = 0.6  # the gauze's thermal time constant: provisional, model knowledge (nichrome gauze)
TURBULENCE = 2e-3  # the plume's breath (dimensionless forcing): design choice


def pipe(f1_hz: float, heater: np.ndarray, g: np.random.Generator) -> np.ndarray:
    """Pressure (arbitrary) at FS for the heater's drive per sample (0..1 x K_PLAY); the
    gauze follows it with its thermal lag."""
    n = heater.size
    length = C_AIR / (2 * f1_hz)
    dt = (C_AIR / length) / FS  # dimensionless step
    j = np.arange(1, MODES + 1)
    w = j * math.pi
    zeta = (C1 * w / w[0] + C2 * np.sqrt(w[0] / w)) / (2 * math.pi)
    wd = w * np.sqrt(1 - zeta**2)
    e = np.exp(-zeta * w * dt)
    cs, sn = np.cos(wd * dt), np.sin(wd * dt)
    p00 = e * (cs + zeta * w / wd * sn)
    p01 = e * sn / wd
    p10 = -e * w * w / wd * sn
    p11 = e * (cs - zeta * w / wd * sn)
    g0 = (1 - p00) / (w * w)
    g1 = -p10 / (w * w)
    sf = np.sin(j * math.pi * X_F)
    cf = np.cos(j * math.pi * X_F)
    lag = max(int(round(TAU / dt)), 1)
    buf = np.zeros(lag)
    a = math.exp(-1 / (GAUZE_S * FS))
    k_gauze = signal.lfilter([1 - a], [1, -a], heater * K_PLAY)
    # the plume rises with the heat
    turb = TURBULENCE * smooth_noise(g, n, 2000.0) * k_gauze / K_PLAY
    eta = 1e-4 * g.standard_normal(MODES)
    deta = np.zeros(MODES)
    # outward volume velocity at both open ends (-u(0) + u(L)), heard broadside
    ends = (-1.0) ** j - 1.0
    out = np.empty(n)
    s3 = math.sqrt(1 / 3)
    for i in range(n):
        uf_late = buf[i % lag]
        q = k_gauze[i] * (math.sqrt(abs(1 / 3 + uf_late)) - s3)
        force = -j * math.pi * q * sf + turb[i] * sf
        eta, deta = p00 * eta + p01 * deta + g0 * force, p10 * eta + p11 * deta + g1 * force
        buf[i % lag] = float(cf @ eta)
        out[i] = float(ends @ eta)
    return np.gradient(out) * FS

"""I12, the Aeolian Keyboard: gut strings sung by the wind.

The phenomenon is vortex shedding. Wind across a string sheds vortices at the Strouhal
frequency St U / D, and the string locks in to whichever of its harmonics is nearest, so the
wind's speed picks the harmonic: the aeolian harp's floating, whistling overtones. A
blower feeds a wind chest; each key opens a slot under its string, and a WIND pedal sets
the speed. Each string's diameter is voiced so that the nominal wind speaks the same
harmonic everywhere (D = St U / (h f1)), so the pedal moves the whole keyboard up and
down the harmonic series together.

The model: the string's transverse modes (gut, slightly stiff), and along the windswept
part of it a few segments, each with a wake oscillator (Facchinetti, de Langre & Biolley,
J. Fluids Struct. 19, 2004: a van der Pol lift variable q driven by the local
acceleration, A = 12, epsilon = 0.3), whose lift 1/4 rho U^2 D C_L0 q drives the modes.
Gusts are seeded low-passed noise on the chest's speed and per segment.
"""

from __future__ import annotations

import math

import numpy as np

from .common import FS, smooth_noise

RHO_AIR = 1.2  # kg/m^3
ST = 0.2  # Strouhal number of a cylinder at Re ~ 100-1000 (any fluids text)
CL0 = 0.3  # the fluctuating lift coefficient: Facchinetti et al. 2004
A_WAKE = 12.0  # their coupling A
EPS_WAKE = 0.3  # their epsilon
RHO_GUT = 1300.0  # kg/m^3, provisional, model knowledge (gut strings)
LENGTH_M = 0.7  # every string, as on an aeolian harp: provisional, design choice
HARMONIC = 4  # the harmonic the nominal wind speaks: design choice
U_NOMINAL = 2.5  # m/s, the nominal wind: design choice (a gentle draught)
Q_STRING = 400.0  # gut in air: provisional, model knowledge
INHARM_B = 1e-4  # gut's stiffness: provisional, model knowledge
SEGMENTS = 6  # the slot spans 15-85 % of the string


def diameter_m(f1_hz: float) -> float:
    return ST * U_NOMINAL / (HARMONIC * f1_hz)


def string(
    f1_hz: float, wind_m_s: np.ndarray, g: np.random.Generator, gust: float = 0.06
) -> np.ndarray:
    """The force on the bridge (N) for a slot speed per sample (0 = the slot shut)."""
    n = wind_m_s.size
    d = diameter_m(f1_hz)
    mu = RHO_GUT * math.pi * d * d / 4
    tension = (2 * LENGTH_M * f1_hz) ** 2 * mu
    k = np.arange(1, 64)
    f = k * f1_hz * np.sqrt(1 + INHARM_B * k * k)
    keep = f < 0.3 * FS
    k, f = k[keep], f[keep]
    w = 2 * math.pi * f
    zeta = 1 / (2 * Q_STRING) * np.sqrt(f / f1_hz) ** 0.5
    m_modal = mu * LENGTH_M / 2
    z = np.linspace(0.15, 0.85, SEGMENTS) * LENGTH_M
    seg_len = 0.7 * LENGTH_M / SEGMENTS
    shape = np.sin(np.outer(z, k) * math.pi / LENGTH_M)  # (segments, modes)
    h = 1 / FS
    # exact free motion per mode over a step, force held over the step
    wd = w * np.sqrt(1 - zeta**2)
    e = np.exp(-zeta * w * h)
    cs, sn = np.cos(wd * h), np.sin(wd * h)
    p00 = e * (cs + zeta * w / wd * sn)
    p01 = e * sn / wd
    p10 = -e * w * w / wd * sn
    p11 = e * (cs - zeta * w / wd * sn)
    g0 = (1 - p00) / (w * w) / m_modal  # displacement per unit force (step response)
    g1 = -p10 / (w * w) / m_modal  # velocity per unit force
    x = np.zeros_like(f)
    v = np.zeros_like(f)
    q = 0.1 * g.standard_normal(SEGMENTS)
    p = np.zeros(SEGMENTS)
    chest = 1 + gust * smooth_noise(g, n, 1.5)
    turb = 1 + 0.04 * np.stack([smooth_noise(g, n, 30.0) for _ in range(SEGMENTS)], axis=1)
    slope = tension * k * math.pi / LENGTH_M
    out = np.empty(n)
    for i in range(n):
        u = wind_m_s[i] * chest[i] * turb[i]
        om = 2 * math.pi * ST * u / d
        lift = 0.25 * RHO_AIR * u * u * d * CL0 * q * seg_len
        force = shape.T @ lift
        acc = force / m_modal - 2 * zeta * w * v - w * w * x
        yacc = shape @ acc
        p += h * (-EPS_WAKE * om * (q * q - 1) * p - om * om * q + A_WAKE / d * yacc)
        q += h * p
        x, v = p00 * x + p01 * v + g0 * force, p10 * x + p11 * v + g1 * force
        out[i] = float(slope @ x)
    return out

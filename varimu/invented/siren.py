"""I15, the Siren Organ: one spinning disc, a ring of holes per key.

The phenomenon is a chopped air jet (Seebeck's and Cagniard de la Tour's sirens, 1819-
1841). Wind from a bellows passes through a ring of N holes on a disc turning at n rev/s
and a matching hole in a fixed plate; the flow pulses N n times a second. One motor turns
every ring, so every pitch is a whole multiple of the shaft's speed: the keyboard IS the
harmonic series (16:18:20:21:24:27:28:30:32 on a 13.75 Hz shaft = A3 B3 C#4 D4- E4 F#4 G4-
G#4 A4, with the 7th and 11th harmonics' famous flat notes). A chord is in just intonation
by construction, and it is coupled twice over: each open ring loads the motor (the pitch
of every sounding note sags together) and draws on the same bellows (the level sags).
The SPEED lever glides everything: the siren's own sound.

The radiated pressure ~ d(volume velocity)/dt. Two stops: FLUTE (wide holes, the flow
through a Helmholtz chamber tuned to the key's fundamental: round) and REED (narrow holes
venting straight from the disc: a buzzy pulse train). Jet noise rides on the pulses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal

from .common import FS, smooth_noise

SHAFT_HZ = 13.75  # rev/s with one key down (A3 = 16 holes): design choice
RHO = 1.2
CD = 0.61  # an orifice's discharge coefficient (any fluids text)
RING_R_M = 0.15  # mean ring radius: design choice
P_MAX_PA = 1000.0  # the blower's stall pressure (~100 mm water, organ wind): provisional
BLOWER_Q_M3_S = 0.015  # its free flow (15 L/s, a small organ blower): provisional, design choice
BELLOWS_M3_PA = 2.0e-6  # the bellows' compliance (~0.2 s with a few keys): design choice
MOTOR_SLOPE = 1.0  # torque per (rev/s) of the motor's droop, normalized: design choice
FRICTION = 0.05  # the shaft's own drag, same units
KEY_DRAG = 0.0123  # an open ring's pumping drag, same units (~20 cents a key): design choice
INERTIA = 0.37  # the disc, same units (~0.35 s to settle): design choice
CHAMBER_Q = 6.0  # the Helmholtz chamber's Q: provisional, design choice
JET_NOISE = 0.015  # turbulence, relative to the flow: provisional, design choice
CONTROL_HZ = 1000
STOPS = {"flute": 0.7, "reed": 0.35}  # hole width / hole pitch along the ring
HOLE_M2 = 1.2e-4  # a hole's area at 16 holes, smaller up the scale as organ pipes: design choice


@dataclass(frozen=True)
class Key:
    holes: int
    start_s: float
    dur_s: float
    vel: float = 1.0  # the valve's opening (0..1)


def overlap(d_over_a: np.ndarray) -> np.ndarray:
    """Open fraction of two equal holes (radius a) whose centres are d apart."""
    x = np.clip(d_over_a / 2.0, 0.0, 1.0)
    return (2 * np.arccos(x) - 2 * x * np.sqrt(1 - x * x)) / math.pi


def play(
    keys: list[Key],
    seconds: float,
    g: np.random.Generator,
    stop: str = "flute",
    speed: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """Pressure (arbitrary units) at FS; speed (optional) is the SPEED lever per control
    step, 1 = nominal."""
    nc = int(seconds * CONTROL_HZ)
    tc = np.arange(nc) / CONTROL_HZ
    valves = np.zeros((len(keys), nc))
    for i, k in enumerate(keys):
        up = np.clip((tc - k.start_s) / 0.012, 0, 1)
        down = np.clip(1 - (tc - k.start_s - k.dur_s) / 0.02, 0, 1)
        valves[i] = k.vel * np.minimum(up, down)
    lever = np.ones(nc) if speed is None else speed
    w_nl = SHAFT_HZ * (MOTOR_SLOPE + FRICTION + KEY_DRAG) / MOTOR_SLOPE
    duty = STOPS[stop]
    mean_open = np.array([np.mean(overlap(np.abs(np.linspace(-0.5, 0.5, 512)) * 2 / duty))])[0]
    hole_area = np.array([HOLE_M2 * math.sqrt(16 / k.holes) for k in keys])
    hunt = (
        1 + 0.0015 * np.sin(2 * math.pi * 4.1 * tc) + 0.002 * smooth_noise(g, nc, 0.5, CONTROL_HZ)
    )
    w = SHAFT_HZ
    p = P_MAX_PA * 0.85
    rps = np.empty(nc)
    pres = np.empty(nc)
    dt = 1 / CONTROL_HZ
    for j in range(nc):
        drag = FRICTION + KEY_DRAG * float(np.sum(valves[:, j]))
        w += dt / INERTIA * (MOTOR_SLOPE * (w_nl * lever[j] - w) - drag * w)
        q_out = CD * mean_open * float(np.sum(valves[:, j] * hole_area)) * math.sqrt(2 * p / RHO)
        q_in = BLOWER_Q_M3_S * (1 - p / P_MAX_PA)
        p = min(max(p + dt / BELLOWS_M3_PA * (q_in - q_out), 1.0), P_MAX_PA)
        rps[j] = w * hunt[j]
        pres[j] = p
    n = int(seconds * FS)
    t = np.arange(n) / FS
    rev = np.cumsum(np.interp(t, tc, rps)) / FS
    p_a = np.interp(t, tc, pres)
    jet_v = np.sqrt(2 * p_a / RHO)
    out = np.zeros(n)
    noise = smooth_noise(g, n, 4000.0)
    for i, k in enumerate(keys):
        a0 = int(max(k.start_s - 0.05, 0) * FS)
        a1 = min(int((k.start_s + k.dur_s + 0.6) * FS), n)
        if a1 <= a0:
            continue
        v = np.interp(t[a0:a1], tc, valves[i])
        ph = k.holes * rev[a0:a1]
        d = np.abs(ph - np.round(ph)) * 2 / duty  # centre distance over hole radius
        q = CD * hole_area[i] * overlap(d) * jet_v[a0:a1] * v
        q = q + JET_NOISE * q * noise[a0:a1]  # turbulence rides on the jet
        if stop == "flute":  # through the key's Helmholtz chamber
            wn = 2 * math.pi * k.holes * SHAFT_HZ
            b, a = signal.bilinear([wn * wn], [1, wn / CHAMBER_Q, wn * wn], FS)
            u = signal.lfilter(b, a, q)
        else:  # the reed stop vents straight from the disc
            u = q
        out[a0:a1] += np.gradient(u) * FS
    info = {
        "rps_min": float(rps.min()),
        "rps_max": float(rps.max()),
        "wind_pa_min": float(pres.min()),
    }
    return out, info

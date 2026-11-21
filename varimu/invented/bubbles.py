"""I16, the Bubble Organ: notes made of air bubbles in water.

The phenomenon is the bubble's breathing mode (Minnaert, 1933): a bubble of radius r rings
at f = sqrt(3 gamma P / rho) / (2 pi r) (f r ~ 3.3 m/s at the surface) when it pinches off
a nozzle, and rises toward the surface, whose image (a pressure-release mirror) raises
its pitch as it nears (Strasberg 1953): a little upward chirp on every note. Each key
opens air to its own nozzle at the bottom of a water tank, read by a hydrophone. Struck,
a key releases one bubble (a pitched drop); held, a stream at the rate the flow sets,
with the jitter of real pinch-off; blown harder, the bubbles grow (Davidson & Schueler:
V ~ Q^(6/5) at constant flow) and the note bends flat. Nothing else here is a liquid.

Each bubble is synthesized from those laws in closed form: a damped sinusoid whose
frequency follows the image correction along its rise; the damping is radiation (omega r /
c) plus a thermal term (Devin 1959's magnitude, provisional). The surface pop is a short
noise burst when it arrives.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from .common import FS

GAMMA = 1.4  # air, adiabatic (the polytropic index is a little lower for small bubbles)
RHO_W = 998.0
C_W = 1480.0
P_ATM = 101_325.0
DEPTH_M = 0.08  # the nozzles' depth: design choice
RISE_M_S = 0.25  # a large bubble's rise speed (Clift, Grace & Weber): provisional
# thermal damping at r = 3 mm, ~ r^-1/2: provisional, model knowledge (Devin 1959)
THERMAL_DELTA_3MM = 0.025
SIZE_SPREAD = 0.02  # pinch-off size jitter (sd, relative): provisional, model knowledge
RATE_JITTER = 0.18  # interval jitter (sd, relative): provisional, model knowledge
POP_LEVEL = 0.01  # the surface pop relative to the bubble (faint through the water): design choice


def minnaert_hz(r_m: float, depth_m: float = DEPTH_M) -> float:
    p = P_ATM + RHO_W * 9.81 * depth_m
    return math.sqrt(3 * GAMMA * p / RHO_W) / (2 * math.pi * r_m)


def radius_for(f_hz: float) -> float:
    """The nozzle's bubble radius for f_hz at the nozzle (the chirp rides above it)."""
    return minnaert_hz(1.0) / f_hz


def bubble(r_m: float, g: np.random.Generator, depth_m: float = DEPTH_M) -> np.ndarray:
    """One bubble's pressure at the hydrophone (arbitrary units, ~ r) from pinch-off."""
    f0 = minnaert_hz(r_m, depth_m)
    delta = 2 * math.pi * f0 * r_m / C_W + THERMAL_DELTA_3MM * math.sqrt(3e-3 / r_m)
    tau = 1 / (math.pi * delta * f0)
    n = int(min(7 * tau, 1.0) * FS)
    t = np.arange(n) / FS
    h = np.maximum(depth_m - RISE_M_S * t, 1.2 * r_m)
    f = f0 / np.sqrt(1 - r_m / (2 * h))  # the surface's image
    ph = 2 * math.pi * np.cumsum(f) / FS
    env = np.exp(-t / tau) * (1 - np.exp(-t / 2e-4))
    y = r_m * env * np.sin(ph)
    # the pop when it breaks the surface (if it still rings by then, it's long gone)
    t_pop = (depth_m - r_m) / RISE_M_S
    k = int(t_pop * FS)
    pop_n = int(0.004 * FS)
    burst = g.standard_normal(pop_n) * np.exp(-np.arange(pop_n) / (0.0008 * FS))
    b, a = signal.butter(2, [1500 / (FS / 2), 7000 / (FS / 2)], "bandpass")
    burst = POP_LEVEL * r_m * signal.lfilter(b, a, burst) * 4
    out = np.zeros(max(n, k + pop_n))
    out[:n] += y
    out[k : k + pop_n] += burst
    return out


def stream(
    f_hz: float,
    dur_s: float,
    rate_hz: float,
    g: np.random.Generator,
    flow: np.ndarray | None = None,
) -> np.ndarray:
    """A held key: bubbles at rate_hz (scaled by flow, a relative air flow per sample, 1 =
    nominal) for dur_s; bigger flow, bigger bubbles (V ~ Q^1.2, so r ~ Q^0.4)."""
    r_nom = radius_for(f_hz)
    total = int((dur_s + 1.0) * FS)
    out = np.zeros(total)
    t = 0.0
    while t < dur_s:
        q = 1.0 if flow is None else float(flow[min(int(t * FS), flow.size - 1)])
        r = r_nom * q**0.4 * math.exp(SIZE_SPREAD * g.standard_normal())
        y = bubble(r, g)
        k = int(t * FS)
        m = min(y.size, total - k)
        out[k : k + m] += y[:m]
        # V ~ Q^1.2, so the rate Q / V ~ Q^-0.2 x Q: bubbles come faster but not in proportion
        t += max(1 / (rate_hz * q**0.8) * (1 + RATE_JITTER * g.standard_normal()), 0.012)
    return out

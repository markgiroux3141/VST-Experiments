"""I13, the Arc Organ: a carbon arc that sings.

The phenomenon is a plasma's negative resistance. A DC carbon arc's voltage falls as its
current rises (Ayrton's law), so an LC circuit across it oscillates (Duddell's singing arc,
1900; he played tunes by switching condensers from a keyboard). The arc is its own
loudspeaker: its power swings, the hot gas expands and contracts, and the pressure follows
d(power)/dt. A key switches its condenser across the arc; the sound is raw, whistling,
breathy, its pitch pulled by the arc's own resistance, and at high current the arc
"hisses" (Ayrton's hissing arc).

Here a Mayr arc (d ln g / dt = (v i / P(i) - 1) / tau), with P(i) from Ayrton's static law so
that its steady state is Ayrton's V(I) = a + b l + (c + d l) / I (carbon, l in mm; Hertha
Ayrton, The Electric Arc, 1902), fed from 110 V DC through a ballast and choke, the tank
(L_t, R_t, the key's C) across it, a small condenser across the carbons. One trapezoidal
step per substep with the arc's conductance held, which reduces to one scalar equation.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from .common import FS, smooth_noise

# a (V), b (V/mm), c (W), d (W/mm): Ayrton 1902, solid carbons
AYRTON = (38.88, 2.074, 11.66, 10.54)
# the arc's thermal time constant: provisional, model knowledge (a free carbon arc's Mayr tau)
TAU_S = 30e-6
SUPPLY_V = 110.0  # Edison DC mains: provisional, model knowledge
CHOKE_H = 0.1  # the ballast choke: design choice
TANK_H = 4e-3  # the tank coil: design choice (Duddell used mH coils and uF condensers)
TANK_OHM = 0.4  # its resistance: provisional, design choice
SHUNT_F = 0.5e-6  # a mica condenser across the carbons: design choice
SUB = 8  # substeps per sample
STRIKE_V = 75.0  # hot carbons restrike above this: provisional, model knowledge
RELEASE_S = 0.03  # a key lets go through a rising quench resistance: design choice
QUENCH_OHM = 200.0
G_FLOOR_S = 1e-4  # the residual conductance of hot carbons: provisional, model knowledge


def ayrton_v(i_a: float, l_mm: float) -> float:
    a, b, c, d = AYRTON
    return a + b * l_mm + (c + d * l_mm) / i_a


def condenser_f(f_hz: float) -> float:
    """The key's condenser for f_hz with the tank coil alone (the arc pulls it)."""
    return 1.0 / ((2 * math.pi * f_hz) ** 2 * TANK_H)


def sing(
    cap_f: np.ndarray,
    current_a: float,
    g: np.random.Generator,
    arc_mm: float = 2.0,
    hiss: float | None = None,
    preroll_s: float = 0.3,
    tank_ohm: float = TANK_OHM,
) -> tuple[np.ndarray, np.ndarray]:
    """(pressure, tank current) at FS for a condenser per sample (0 = no key: the tank open),
    the ballast set for current_a. Pressure in arbitrary units (d power / dt). A key lets go
    through its quench resistor (RELEASE_S); the arc burns preroll_s before the take."""
    pre = int(preroll_s * FS)
    cap_f = np.concatenate([np.zeros(pre), cap_f])
    n = cap_f.size
    # the tank's series resistance: TANK_OHM, rising to QUENCH_OHM over RELEASE_S before a
    # key's condenser is switched out
    tank_r = np.full(n, tank_ohm)
    rel = int(RELEASE_S * FS)
    offs = np.flatnonzero((cap_f[:-1] > 0) & (cap_f[1:] != cap_f[:-1])) + 1
    for o in offs:
        a0 = max(o - rel, 0)
        tank_r[a0:o] = tank_ohm * (QUENCH_OHM / tank_ohm) ** np.linspace(0, 1, o - a0)
    a, b, c, d = AYRTON
    v0 = ayrton_v(current_a, arc_mm)
    r_b = (SUPPLY_V - v0) / current_a
    h = 1.0 / (FS * SUB)
    al = h / 2
    # the arc's feed wanders as the carbons burn and the feed hunts (+-0.25 mm, ~0.3 Hz)
    l_mm = arc_mm + 0.25 * smooth_noise(g, n, 0.3)
    if hiss is None:
        hiss = 0.01 + 0.12 * max(0.0, current_a - 6.0) / 4.0
    flutter = 1.0 + hiss * smooth_noise(g, n * SUB, 6000.0, FS * SUB)
    ib, it, vc, v = current_a, 0.0, 0.0, v0
    lng = math.log(current_a / v0)
    power = np.empty(n * SUB)
    tank = np.empty(n)
    b1 = al / (CHOKE_H + al * r_b)
    cf_prev = 0.0
    for k in range(n):
        cf = cap_f[k]
        if cf > 0 and cf_prev == 0:
            # an idle condenser rests at the arc's voltage (its keep-alive resistor)
            vc = v
        cf_prev = cf
        lmm = l_mm[k]
        pa, pc = a + b * lmm, c + d * lmm
        rt = tank_r[k]
        if cf > 0:
            b2 = al / (TANK_H + al * rt + al * al / cf)
        for s in range(SUB):
            gg = math.exp(lng)
            a1 = (CHOKE_H * ib + al * (2 * SUPPLY_V - r_b * ib - v)) / (CHOKE_H + al * r_b)
            if cf > 0:
                a2 = (TANK_H * it + al * (v - rt * it - 2 * vc) - (al * al / cf) * it) / (
                    TANK_H + al * rt + al * al / cf
                )
                bb2 = b2
            else:
                a2, bb2 = 0.0, 0.0
            vn = (SHUNT_F * v + al * (ib - it - gg * v) + al * (a1 - a2)) / (
                SHUNT_F + al * gg + al * (b1 + bb2)
            )
            ibn = a1 - b1 * vn
            itn = a2 + bb2 * vn
            if cf > 0:
                vc = vc + (al / cf) * (it + itn)
            ib, it, v = ibn, itn, vn
            i_arc = gg * v
            p = v * i_arc
            ratio = min(p / ((pa * abs(i_arc) + pc) * flutter[k * SUB + s]), 20.0)
            if abs(v) > STRIKE_V:
                ratio = 20.0
            lng = min(max(lng + h / TAU_S * (ratio - 1.0), math.log(G_FLOOR_S)), 2.0)
            power[k * SUB + s] = p
        tank[k] = it
    pw = signal.resample_poly(power, 1, SUB)
    return (np.gradient(pw) * FS)[pre:], tank[pre:]


def key_condensers(n: int, notes: list[tuple[float, float, float]]) -> np.ndarray:
    """notes: (start_s, dur_s, f_hz) -> the condenser switched in per sample."""
    out = np.zeros(n)
    for start, dur, f in notes:
        out[int(start * FS) : int((start + dur) * FS)] = condenser_f(f)
    return out


def measure_f0(p: np.ndarray) -> float:
    """The strongest spectral peak above 50 Hz, refined by a parabola on log magnitude."""
    w = np.hanning(p.size)
    sp = np.abs(np.fft.rfft(p * w)) + 1e-30
    fr = np.fft.rfftfreq(p.size, 1 / FS)
    lo = np.searchsorted(fr, 50.0)
    k = lo + int(np.argmax(sp[lo:]))
    y0, y1, y2 = np.log(sp[k - 1 : k + 2])
    return float(fr[k] + (y0 - y2) / (2 * (y0 - 2 * y1 + y2)) * (fr[1] - fr[0]))


_TRIMS: dict[tuple[float, ...], float] = {}


def tuned_condenser(
    f_hz: float, current_a: float, arc_mm: float = 2.0, tank_ohm: float = TANK_OHM
) -> float:
    """The factory trim: the condenser that sounds f_hz with this arc (three passes of a
    0.8 s render, a fixed seed)."""
    key = (round(f_hz, 3), current_a, arc_mm, tank_ohm)
    if key in _TRIMS:
        return _TRIMS[key]
    from .common import rng

    cf = condenser_f(f_hz)
    n = int(0.8 * FS)
    for _ in range(3):
        caps = np.full(n, cf)
        p, _ = sing(caps, current_a, rng(0, "trim"), arc_mm, hiss=0.0, tank_ohm=tank_ohm)
        f = measure_f0(p[int(0.4 * FS) :])
        cf *= (f / f_hz) ** 2
    _TRIMS[key] = cf
    return cf

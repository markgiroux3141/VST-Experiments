"""IL5, the Bubble Organ's keyboard (docs/INVENTED_LIVE_PLAN.md): the sketch's bubbles
(varimu.invented.bubbles) per key, played by note events, as circuitsim's invented.rs plays
them.

Per key: a nozzle at the bottom of a water tank and up to SLOTS bubbles ringing at once,
each in closed form, sample by sample: Minnaert's breathing mode at the nozzle's depth, its
pitch raised by the surface's image as it rises (Strasberg), damped by radiation plus a
thermal term, its envelope exp(-t / tau) (1 - exp(-t / 0.2 ms)) as two decaying exponentials;
then the pop as it breaks the surface (Gaussian noise under a 0.8 ms decay, band-passed: an
RBJ band-pass at 3.2 kHz, Q 0.59, for the sketch's 1.5-7 kHz Butterworth). A new bubble takes
the first free slot, else the oldest one's.

Each nozzle sits at max(DEPTH_M, 3 r) (a big bubble needs room to rise) and is voiced so the
bubble's pitch at pinch-off is the key's, the image included. Flow: velocity sets the air
flow q (Q_RANGE), aftertouch adds up to Q_PRESSURE, FLOW scales it; bigger flow, bigger
bubbles (Davidson & Schueler: V ~ q^1.2, so r ~ q^0.4: the note bends flat) and, held, a faster
stream (the rate ~ q^0.8). MODE STRUCK: a key releases one bubble (its pinch-off's excitation
0.5 + velocity, the sketch's); HELD: a stream while the key (or the pedal) holds its valve
open, the intervals jittered (RATE_JITTER) and the sizes too (SIZE_SPREAD). A voice sleeps
once its valve is shut and no bubble rings. The hydrophone's gain per nozzle is voiced as
r(A3) / r (a bubble's pressure goes as its radius: unvoiced, C2 rang 25 dB over C6).

The panel: k0 MODE (< 0.5 STRUCK, else HELD), k1 FLOW (0.6-1.6x the key's flow; 1x at 0.4),
k2 RATE (the held stream's rate 3-24 Hz at q = 1; 9 Hz at 0.2857), k3 DEPTH (the nozzles'
depths 0.5-2.5x; 1x at 0.25: a deeper tank, a longer chirp and a later pop).

Draws from the key's Gaussian stream, in order within a sample: a new bubble's size, then (held)
the next interval, then the popping bubbles' noise in slot order.
"""

from __future__ import annotations

import math
from typing import Any

from varimu.invented import bubbles as bb
from varimu.invented.keys.common import Gauss, bandpass, key_seed

KIND = "bubble_organ"
LOW, HIGH = 36, 84  # C2-C6: bubbles ~5 cm-3 mm
SLOTS = 16
Q_RANGE = (0.9, 1.1)  # in tune at velocity 64; +-3/4 semitone (the sketch's swell: 0.7-1.4)
Q_PRESSURE = 0.4
FLOW_RANGE = (0.6, 1.6)
RATE_RANGE_HZ = (3.0, 24.0)
DEPTH_RANGE = (0.5, 2.5)
NOZZLE_DEPTH_R = 3.0  # a nozzle at least 3 radii deep
ATTACK_S = 2e-4  # the pinch-off's rise (the sketch's)
LIFE_MAX_S = 1.0
POP_S = 0.004
POP_DECAY_S = 0.0008
POP_HZ, POP_Q = 3240.0, 0.59  # sqrt(1500 x 7000), / 5500
POP_GAIN = 4.0  # the sketch's
INTERVAL_MIN_S = 0.012
HYDROPHONE_V = 50.0  # volts per unit of the sketch's pressure (~ r) at A3's nozzle: ~1 V peak
VOICING_REF_NOTE = 57  # A3: each nozzle's hydrophone voiced as its r / this one's
SEED = 1


def minnaert_k(depth_m: float) -> float:
    """f r (m/s) at depth_m."""
    return bb.minnaert_hz(1.0, depth_m)


def voiced(f_hz: float) -> tuple[float, float]:
    """(radius, depth) of a nozzle whose bubble pinches off at f_hz, the image included."""
    r = bb.radius_for(f_hz)
    d = bb.DEPTH_M
    for _ in range(200):
        d = max(bb.DEPTH_M, NOZZLE_DEPTH_R * r)
        r = minnaert_k(d) / (f_hz * math.sqrt(1.0 - r / (2.0 * d)))
    return r, d


def model() -> dict[str, Any]:
    """The keyboard's data, as the component saves it and invented.rs reads it."""
    keys = []
    r_ref = voiced(440.0 * 2.0 ** ((VOICING_REF_NOTE - 69) / 12))[0]
    for n in range(LOW, HIGH + 1):
        f = 440.0 * 2.0 ** ((n - 69) / 12)
        r, d = voiced(f)
        keys.append({"note": n, "f_hz": f, "r_m": r, "depth_m": d, "voicing": r_ref / r})
    return {
        "instrument": KIND,
        "source": "varimu/invented/keys/bubbles.py from varimu/invented/bubbles.py's values",
        "keys": keys,
        "gamma": bb.GAMMA,
        "rho_w": bb.RHO_W,
        "c_w": bb.C_W,
        "p_atm": bb.P_ATM,
        "rise_m_s": bb.RISE_M_S,
        "thermal_delta_3mm": bb.THERMAL_DELTA_3MM,
        "size_spread": bb.SIZE_SPREAD,
        "rate_jitter": bb.RATE_JITTER,
        "pop_level": bb.POP_LEVEL,
        "slots": SLOTS,
        "q_range": list(Q_RANGE),
        "q_pressure": Q_PRESSURE,
        "flow_range": list(FLOW_RANGE),
        "rate_range_hz": list(RATE_RANGE_HZ),
        "depth_range": list(DEPTH_RANGE),
        "attack_s": ATTACK_S,
        "life_max_s": LIFE_MAX_S,
        "pop_s": POP_S,
        "pop_decay_s": POP_DECAY_S,
        "pop_hz": POP_HZ,
        "pop_q": POP_Q,
        "pop_gain": POP_GAIN,
        "interval_min_s": INTERVAL_MIN_S,
        "hydrophone_v": HYDROPHONE_V,
        "seed": SEED,
    }


def knob(lo_hi: list[float], k: float) -> float:
    return lo_hi[0] + (lo_hi[1] - lo_hi[0]) * k


class Bubble:
    """One bubble's state (invented.rs's Bubble)."""

    def __init__(self, m: dict[str, Any], r: float, depth: float, amp: float, fs: float):
        p = m["p_atm"] + m["rho_w"] * 9.81 * depth
        f0 = math.sqrt(3.0 * m["gamma"] * p / m["rho_w"]) / (2.0 * math.pi * r)
        delta = 2.0 * math.pi * f0 * r / m["c_w"] + m["thermal_delta_3mm"] * math.sqrt(3e-3 / r)
        tau = 1.0 / (math.pi * delta * f0)
        self.r, self.depth, self.f0, self.amp = r, depth, f0, amp
        self.n_ring = int(min(7.0 * tau, m["life_max_s"]) * fs)
        self.k_pop = int((depth - r) / m["rise_m_s"] * fs)
        self.n_pop = int(m["pop_s"] * fs)
        self.n_life = max(self.n_ring, self.k_pop + self.n_pop)
        self.d1 = math.exp(-1.0 / (tau * fs))
        self.d2 = math.exp(-1.0 / (tau * fs) - 1.0 / (m["attack_s"] * fs))
        self.e1 = 1.0
        self.e2 = 1.0
        self.ph = 0.0
        self.pe = 1.0
        self.pd = math.exp(-1.0 / (m["pop_decay_s"] * fs))
        self.bx1 = self.bx2 = self.by1 = self.by2 = 0.0
        self.i = 0


class Voice:
    """One key's nozzle (invented.rs's BubbleVoice, step for step)."""

    def __init__(self, m: dict[str, Any], key: dict[str, Any], fs: float, knobs: list[float]):
        self.m = m
        self.fs = fs
        self.r_key = key["r_m"]
        self.depth_key = key["depth_m"]
        self.voicing = key["voicing"]
        self.slots: list[Bubble | None] = [None] * m["slots"]
        self.bp = bandpass(m["pop_hz"], m["pop_q"], fs)
        self.gauss = Gauss(key_seed(m["seed"], key["note"]))
        self.down = False
        self.pedal_down = False
        self.held = False
        self.pending = False
        self.velocity = 0.0
        self.aftertouch = 0.0
        self.next_n = 0  # samples to the held stream's next bubble
        self.awake = False
        self.set_knobs(knobs)

    def set_knobs(self, k: list[float]) -> None:
        m = self.m
        self.held_mode = k[0] >= 0.5
        self.flow = knob(m["flow_range"], k[1])
        self.rate = knob(m["rate_range_hz"], k[2])
        self.depth_scale = knob(m["depth_range"], k[3])

    def asleep(self) -> bool:
        return not self.awake

    def on(self, velocity: int) -> None:
        self.down = True
        self.held = True
        self.velocity = velocity / 127.0
        self.awake = True
        self.pending = True
        self.next_n = 0

    def off(self) -> None:
        self.down = False
        self.held = self.pedal_down

    def pedal(self, down: bool) -> None:
        self.pedal_down = down
        self.held = self.down or (down and self.held)

    def pressure(self, value: int) -> None:
        self.aftertouch = value / 127.0

    def emit(self, q: float, amp: float) -> None:
        m = self.m
        r = self.r_key * q**0.4 * math.exp(m["size_spread"] * self.gauss.next())
        depth = self.depth_key * self.depth_scale
        b = Bubble(m, r, max(depth, 1.2 * r), amp, self.fs)
        free = -1
        oldest = 0
        for j in range(len(self.slots)):
            s = self.slots[j]
            if s is None:
                free = j
                break
            if s.i > self.slots[oldest].i:
                oldest = j
        self.slots[free if free >= 0 else oldest] = b

    def step(self) -> float:
        m = self.m
        q = self.flow * (knob(m["q_range"], self.velocity) + m["q_pressure"] * self.aftertouch)
        if self.held_mode:
            if self.held:
                if self.next_n <= 0:
                    self.emit(q, 1.0)
                    iv = 1.0 / (self.rate * q**0.8) * (1.0 + m["rate_jitter"] * self.gauss.next())
                    self.next_n = int(max(iv, m["interval_min_s"]) * self.fs)
                self.next_n -= 1
            self.pending = False
        elif self.pending:
            self.emit(q, 0.5 + self.velocity)
            self.pending = False
        y = 0.0
        sounding = False
        two_pi_fs = 2.0 * math.pi / self.fs
        for j in range(len(self.slots)):
            b = self.slots[j]
            if b is None:
                continue
            i = b.i
            if i < b.n_ring:
                t = i / self.fs
                h = max(b.depth - m["rise_m_s"] * t, 1.2 * b.r)
                f = b.f0 / math.sqrt(1.0 - b.r / (2.0 * h))
                b.ph += two_pi_fs * f
                y += b.amp * b.r * (b.e1 - b.e2) * math.sin(b.ph)
                b.e1 *= b.d1
                b.e2 *= b.d2
            if b.k_pop <= i < b.k_pop + b.n_pop:
                x = self.gauss.next() * b.pe
                b.pe *= b.pd
                b0, b1, b2, a1, a2 = self.bp
                yb = b0 * x + b1 * b.bx1 + b2 * b.bx2 - a1 * b.by1 - a2 * b.by2
                b.bx2, b.bx1 = b.bx1, x
                b.by2, b.by1 = b.by1, yb
                y += m["pop_level"] * b.r * m["pop_gain"] * b.amp * yb
            b.i = i + 1
            if b.i >= b.n_life:
                self.slots[j] = None
            else:
                sounding = True
        if not sounding and not self.pending and not (self.held_mode and self.held):
            self.awake = False
        return m["hydrophone_v"] * self.voicing * y


def keyboard(m: dict[str, Any], fs: float, knobs: list[float]) -> dict[int, Voice]:
    return {k["note"]: Voice(m, k, fs, knobs) for k in m["keys"]}

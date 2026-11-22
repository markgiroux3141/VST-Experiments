"""IL4, the Aeolian Keyboard's keyboard (docs/INVENTED_LIVE_PLAN.md): the sketch's wind-sung
gut string (varimu.invented.aeolian) per key, played by note events, as circuitsim's
invented.rs plays it.

Per key: a 0.7 m gut string's transverse modes below F_TOP_HZ (exact per step, the force
held over it), and along the windswept 15-85 % of it SEGMENTS wake oscillators (Facchinetti,
de Langre & Biolley 2004: a van der Pol lift q driven by the local acceleration; one
semi-implicit Euler step a sample, substepped where the shedding's omega h passes OMH_MAX:
the treble's thin strings in a strong wind, which diverged otherwise). Each string's
diameter is voiced so that the nominal wind speaks its 4th harmonic, so WIND walks the
keyboard up and down the series together.

A key opens the slot under its string over ATTACK_S (a smoothstep of the slot's wind; it
shuts over RELEASE_S). Velocity sets how far it opens: the chest's pressure sets the jet's
speed through any opening (Bernoulli), so the opening is the jet's width along the string
(OPEN_MIN-1 of the slot), i.e. the lift, not the pitch; aftertouch opens it further, the
pedal holds released keys' slots open. Once a slot is shut the felt damper falls (every
mode's Q at most Q_DAMPED) and the voice sleeps SLEEP_S later.

Gusts: the chest's (one blower: GUST, low-passed at GUST_HZ) is a smooth noise of absolute
time shared by every string (`chest`: value noise on a seeded Gaussian lattice, smoothstep
between); each segment's turbulence (TURB_HZ) is the key's own (one-pole low-passed Gaussian
noise, updated every TURB_EVERY samples and held). The bridge reads the strings' end slopes
times their tension, at a piezo's sensitivity voiced per string as f1 / VOICING_REF_HZ (the
lift goes as the diameter, which the nominal wind sets as 1 / f1: unvoiced, the treble falls
~6 dB an octave).

The panel: k0 WIND (the chest's speed 1.0-5.0 m/s; 2.5, the nominal, at 0.375), k1 GUST (the
chest's gusts 0-0.25; the sketch's 0.06 at 0.24). Voices need the absolute time: the
reference's `play` sets `voice.now` (the sample) before each step, keyed.rs's
`KeyVoice::chunk_start` gives it to the Rust.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from varimu.invented import aeolian as ae
from varimu.invented.keys.common import M64, Gauss, key_seed

KIND = "aeolian_keyboard"
LOW, HIGH = 36, 84  # C2-C6: gut 1.9 mm-0.12 mm
F_TOP_HZ = 14_400.0  # modes kept below this (the sketch's 0.3 x 48 kHz)
MAX_HARMONIC = 40  # the sketch's 63 cost ~35 % more; the wind locks to the 2nd-8th
ATTACK_S = 0.2
RELEASE_S = 0.3
OPEN_MIN = 0.3
PRESSURE_OPEN = 1.0  # aftertouch's share of the rest of the opening
Q_DAMPED = 30.0
SLEEP_S = 1.0  # after the damper falls (Q 30 at 65 Hz: -60 dB in ~1 s... the top's sooner)
WIND_RANGE_M_S = (1.0, 5.0)
GUST_RANGE = (0.0, 0.25)
GUST_HZ = 1.5  # the sketch's
TURB = 0.04  # the sketch's
TURB_HZ = 30.0  # the sketch's
TURB_EVERY = 8  # samples per turbulence draw (a one-pole at fs / 8, held: 12 kHz >> 30 Hz)
Q0 = 0.1  # the wake's start (the sketch's)
OMH_MAX = 0.5  # the wake's largest omega h per Euler step (C6 at 5 m/s with gusts diverged at ~1)
V_PER_N = 300.0  # a piezo under the bridge at VOICING_REF_HZ: ~0.35 V rms a string at WIND 2.5
VOICING_REF_HZ = 220.0  # A3
SEED = 1


def model() -> dict[str, Any]:
    """The keyboard's data, as the component saves it and invented.rs reads it."""
    keys = []
    for n in range(LOW, HIGH + 1):
        f1 = 440.0 * 2.0 ** ((n - 69) / 12)
        keys.append(
            {"note": n, "f_hz": f1, "d_m": ae.diameter_m(f1), "voicing": f1 / VOICING_REF_HZ}
        )
    return {
        "instrument": KIND,
        "source": "varimu/invented/keys/aeolian.py from varimu/invented/aeolian.py's values",
        "keys": keys,
        "rho_air": ae.RHO_AIR,
        "st": ae.ST,
        "cl0": ae.CL0,
        "a_wake": ae.A_WAKE,
        "eps_wake": ae.EPS_WAKE,
        "rho_gut": ae.RHO_GUT,
        "length_m": ae.LENGTH_M,
        "q_string": ae.Q_STRING,
        "inharm_b": ae.INHARM_B,
        "segments": ae.SEGMENTS,
        "f_top_hz": F_TOP_HZ,
        "max_harmonic": MAX_HARMONIC,
        "attack_s": ATTACK_S,
        "release_s": RELEASE_S,
        "open_min": OPEN_MIN,
        "pressure_open": PRESSURE_OPEN,
        "q_damped": Q_DAMPED,
        "sleep_s": SLEEP_S,
        "wind_range_m_s": list(WIND_RANGE_M_S),
        "gust_range": list(GUST_RANGE),
        "gust_hz": GUST_HZ,
        "turb": TURB,
        "turb_hz": TURB_HZ,
        "turb_every": TURB_EVERY,
        "q0": Q0,
        "omh_max": OMH_MAX,
        "v_per_n": V_PER_N,
        "seed": SEED,
    }


def knob(lo_hi: list[float], k: float) -> float:
    return lo_hi[0] + (lo_hi[1] - lo_hi[0]) * k


def lattice(seed: int, i: int) -> float:
    """The chest's gust lattice: a Gaussian per index (one Box-Muller cosine of splitmix64)."""
    g = Gauss((seed ^ ((i * 0xD1B54A32D192ED03) & M64)) & M64)
    u, v = g.uniform(), g.uniform()
    return math.sqrt(-2.0 * math.log(u)) * math.cos(2.0 * math.pi * v)


class Chest:
    """The chest's gust at absolute sample t (shared by every string; invented.rs's Chest)."""

    def __init__(self, seed: int, fs: float, gust_hz: float) -> None:
        self.seed = seed
        self.per = fs / (2.0 * gust_hz)  # lattice points every half period
        self.i = -1
        self.a = self.b = 0.0

    def at(self, t: int) -> float:
        x = t / self.per
        i = math.floor(x)
        if i != self.i:
            self.i = i
            self.a = lattice(self.seed, i)
            self.b = lattice(self.seed, i + 1)
        s = x - i
        s = s * s * (3.0 - 2.0 * s)
        return self.a + (self.b - self.a) * s


def tables(m: dict[str, Any], f: list[float], f1: float, h: float, mass: float, q_cap: float):
    """Per mode [p00, p01, p10, p11, g0, g1]: the exact damped step, force held."""
    out = []
    for fk in f:
        w = 2.0 * math.pi * fk
        zeta = 1.0 / (2.0 * m["q_string"]) * math.sqrt(math.sqrt(fk / f1))
        zeta = max(zeta, 1.0 / (2.0 * q_cap))
        wd = w * math.sqrt(1.0 - zeta * zeta)
        e = math.exp(-zeta * w * h)
        cs, sn = math.cos(wd * h), math.sin(wd * h)
        p00 = e * (cs + zeta * w / wd * sn)
        p01 = e * sn / wd
        p10 = -e * w * w / wd * sn
        p11 = e * (cs - zeta * w / wd * sn)
        out.append([p00, p01, p10, p11, (1.0 - p00) / (w * w) / mass, -p10 / (w * w) / mass, zeta])
    return np.array(out)


class Voice:
    """One key's string (invented.rs's AeolianVoice, step for step)."""

    def __init__(self, m: dict[str, Any], key: dict[str, Any], fs: float, knobs: list[float]):
        self.m = m
        self.fs = fs
        self.h = h = 1.0 / fs
        f1, d, length = key["f_hz"], key["d_m"], m["length_m"]
        self.d = d
        self.voicing = key["voicing"]
        mu = m["rho_gut"] * math.pi * d * d / 4.0
        tension = (2.0 * length * f1) * (2.0 * length * f1) * mu
        f = []
        for k in range(1, m["max_harmonic"] + 1):
            fk = k * f1 * math.sqrt(1.0 + m["inharm_b"] * k * k)
            if fk < m["f_top_hz"]:
                f.append(fk)
        nk = len(f)
        mass = mu * length / 2.0
        self.free = tables(m, f, f1, h, mass, 1e300)
        self.damped_t = tables(m, f, f1, h, mass, m["q_damped"])
        ns = m["segments"]
        self.ns = ns
        self.seg_len = 0.7 * length / ns
        shape = np.empty((ns, nk))
        for s in range(ns):
            z = (0.15 + s * (0.7 / (ns - 1))) * length
            for k in range(nk):
                shape[s, k] = math.sin(z * (k + 1) * math.pi / length)
        self.shape = shape
        self.slope = np.array([tension * (k + 1) * math.pi / length for k in range(nk)])
        self.w = np.array([2.0 * math.pi * fk for fk in f])
        self.w2 = self.w * self.w
        self.mass = mass
        self.x = np.zeros(nk)
        self.v = np.zeros(nk)
        g = Gauss(key_seed(m["seed"], key["note"]))
        self.gauss = g
        self.q = [m["q0"] * g.next() for _ in range(ns)]
        self.p = [0.0] * ns
        self.nz = [0.0] * ns
        a = math.exp(-2.0 * math.pi * m["turb_hz"] * m["turb_every"] / fs)
        self.tick = 0
        self.na = a
        self.norm = math.sqrt((1.0 + a) / (1.0 - a))
        self.chest = Chest(m["seed"], fs, m["gust_hz"])
        self.slot = 0.0
        self.down = False
        self.pedal_down = False
        self.held = False
        self.velocity = 0.0
        self.aftertouch = 0.0
        self.damped = True
        self.quiet = 0
        self.awake = False
        self.sleep_n = int(m["sleep_s"] * fs)
        self.now = 0
        self.set_knobs(knobs)

    def set_knobs(self, k: list[float]) -> None:
        self.wind = knob(self.m["wind_range_m_s"], k[0])
        self.gust = knob(self.m["gust_range"], k[1])

    def asleep(self) -> bool:
        return not self.awake

    def on(self, velocity: int) -> None:
        self.down = True
        self.held = True
        self.velocity = velocity / 127.0
        self.awake = True
        self.damped = False
        self.quiet = 0

    def off(self) -> None:
        self.down = False
        self.held = self.pedal_down

    def pedal(self, down: bool) -> None:
        self.pedal_down = down
        self.held = self.down or (down and self.held)

    def pressure(self, value: int) -> None:
        self.aftertouch = value / 127.0

    def step(self) -> float:
        m = self.m
        if self.held:
            self.slot = min(self.slot + self.h / m["attack_s"], 1.0)
        else:
            self.slot = max(self.slot - self.h / m["release_s"], 0.0)
            if self.slot == 0.0 and not self.damped:
                self.damped = True
                self.quiet = 0
        sl = self.slot
        shape_s = sl * sl * (3.0 - 2.0 * sl)
        o_v = knob([m["open_min"], 1.0], self.velocity)
        opening = o_v + (1.0 - o_v) * m["pressure_open"] * self.aftertouch
        chest = 1.0 + self.gust * self.chest.at(self.now)
        u0 = self.wind * chest * shape_s
        lift = []
        om = []
        draw = self.tick == 0
        self.tick = (self.tick + 1) % m["turb_every"]
        for s in range(self.ns):
            if draw:
                self.nz[s] = self.na * self.nz[s] + (1.0 - self.na) * self.gauss.next()
            u = u0 * (1.0 + m["turb"] * self.nz[s] * self.norm)
            om.append(2.0 * math.pi * m["st"] * u / self.d)
            lift.append(
                0.25 * m["rho_air"] * u * u * self.d * m["cl0"] * self.q[s] * self.seg_len * opening
            )
        t = self.damped_t if self.damped else self.free
        force = np.zeros(self.x.size)
        for s in range(self.ns):
            force += self.shape[s] * lift[s]
        acc = (force / self.mass - 2.0 * t[:, 6] * self.w * self.v) - self.w2 * self.x
        yacc = np.add.accumulate(self.shape * acc, axis=1)[:, -1]
        for s in range(self.ns):
            q, p, o = self.q[s], self.p[s], om[s]
            nsub = max(math.ceil(o * self.h / m["omh_max"]), 1)
            hs = self.h / nsub
            drive = m["a_wake"] / self.d * yacc[s]
            for _ in range(nsub):
                p = p + hs * ((-m["eps_wake"] * o * (q * q - 1.0) * p - o * o * q) + drive)
                q = q + hs * p
            self.p[s] = p
            self.q[s] = q
        x, v = self.x, self.v
        self.x = (t[:, 0] * x + t[:, 1] * v) + t[:, 4] * force
        self.v = (t[:, 2] * x + t[:, 3] * v) + t[:, 5] * force
        out = float(np.add.accumulate(self.slope * self.x)[-1])
        if self.damped:
            self.quiet += 1
            if self.quiet >= self.sleep_n:
                self.awake = False
        return m["v_per_n"] * self.voicing * out


def keyboard(m: dict[str, Any], fs: float, knobs: list[float]) -> dict[int, Voice]:
    return {k["note"]: Voice(m, k, fs, knobs) for k in m["keys"]}

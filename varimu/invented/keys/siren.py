"""IL6, the Siren Organ's keyboard (docs/INVENTED_LIVE_PLAN.md): the sketch's siren
(varimu.invented.siren) per key, played by note events, as circuitsim's invented.rs plays it.

One motor turns a stack of discs; each key's ring of holes chops a jet from one bellows, so
every pitch is a whole multiple of the shaft's speed. The keyboard is the harmonic series on
A: each pitch class is a harmonic 16-30 of the shaft (HARMONICS: A 16, A# 17, B 18, C 19,
C# 20, D 21, D# 22 (the 11th harmonic, ~half a semitone flat), E 24, F 25, F# 27, G 28 (the
7th harmonic, a third of a semitone flat), G# 30), each octave up doubling the holes. The
shaft runs at 3.4375 rev/s (A1 = 16 holes), so C2 is a ring of 19 holes and C6 one of 304. A
chord is in just intonation by construction. Each ring is drilled at its own angle (its note's
golden-ratio fraction of a hole pitch: design choice; the sketch's rings all had a hole at
angle 0, so a chord's pulses lined up once a revolution, a 3.4 Hz accent with peaks ~5x the
chord's rms).

The shared state (`Shaft`): the motor (its speed sags as every open ring adds drag, the
sketch's KEY_DRAG), the bellows (every open hole draws on it: the wind sags), the motor's
hunting (a 4.1 Hz wobble and a slow wander), and the shaft's angle in revolutions, stepped per
sample after that sample's events and before any voice reads it. It depends only on the
valves, which follow the events, so circuitsim steps it per chunk before the voices render
(keyed.rs's `KeyVoice::prepare`): exact, the same on any number of threads.

Each key (`Voice`): its valve opens over VALVE_OPEN_S to its opening (velocity, aftertouch the
rest of the way; the pedal holds a released key's valve), closes over VALVE_CLOSE_S. The flow
through its ring is CD x area x the holes' open fraction (two equal circles' overlap, the
sketch's) x the jet's speed x the valve, with jet turbulence riding on it (2nd-order low-passed
noise, unit rms, its band JET_NOISE_HZ at A3's ring and as the holes elsewhere: every ring at
the sketch's one radius, so a slot's width along it goes as 1 / holes and the turbulence's
band, U / w, as holes; the sketch's fixed 4 kHz band swamped the bass reeds); the FLUTE stop
passes it through the key's Helmholtz chamber (Q 6, tuned to the key at the nominal speed;
bilinear), the REED stop vents it straight. The sound:
the pressure 1 m away of a monopole, rho / (4 pi r) dU/dt (a backward difference), read by a
microphone. Each ring's hole area is voiced as 1 / holes (the derivative goes as the pitch:
the sketch's sqrt(16 / holes) left the treble ~6 dB an octave over the bass).

The panel: k0 SPEED (the motor's no-load speed 0.5-2x, 2^(2 k - 1): 1x at 0.5; the mod wheel),
k1 STOP (< 0.5 FLUTE: wide holes into chambers; else REED: narrow holes, straight), k2 WIND
(the blower's stall pressure 0.5-1.5x of 1000 Pa; 1x at 0.5), k3 MOTOR (the motor's stiffness,
torque per droop, 0.25-4x, 2^(4 k - 2): 1x at 0.5; a weak motor sags further under a chord).
One key down at its full opening runs the shaft at its nominal speed at any MOTOR.

Draws from the key's Gaussian stream: one a sample while it's awake (the jet's turbulence).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from varimu.invented import siren as sr
from varimu.invented.keys.aeolian import Chest
from varimu.invented.keys.common import Gauss, key_seed

KIND = "siren_organ"
LOW, HIGH = 36, 84  # C2-C6
TONIC_NOTE = 33  # A1: the shaft's 16th harmonic
HARMONICS = (16, 17, 18, 19, 20, 21, 22, 24, 25, 27, 28, 30)  # per semitone above A
SHAFT_HZ = 55.0 / 16.0  # rev/s, so A1 = 16 holes: design choice (the sketch's 13.75 / 4)
AREA_REF_HOLES = 64  # A3's ring: the sketch's hole area (its A3 = 16 holes)
OPEN_RANGE = (0.2, 1.0)  # the valve's opening at velocity 1 / 127: design choice
VALVE_OPEN_S = 0.012  # the sketch's
VALVE_CLOSE_S = 0.020
SPEED_OCTAVES = 1.0  # SPEED: +-1 octave
WIND_RANGE = (0.5, 1.5)
MOTOR_OCTAVES = 2.0  # MOTOR: 0.25-4x
HUNT_HZ = 4.1  # the sketch's hunting
HUNT_DEPTH = 0.0015
WANDER = 0.002  # the sketch's slow wander (a Gaussian lattice at 0.5 Hz, smoothstepped)
WANDER_HZ = 0.5
JET_NOISE_HZ = 4000.0  # the sketch's turbulence band, at A3's ring (as holes: the slots' width)
TAIL_S = 0.3  # a key sleeps this long after its valve shuts (the chamber long rung out)
MIC_R_M = 1.0  # the pressure 1 m from the ring
MIC_V_PER_PA = 2.0  # a microphone, provisional: ~1 V peak a key (scripts/invented_live_render.py)
RING_PHASE = 0.6180339887498949  # each ring drilled at its own angle: the note's golden fraction
SEED = 1
WANDER_SEED = 0x51BE  # the motor's wander (shared)


def holes_of(note: int) -> int:
    o, s = divmod(note - TONIC_NOTE, 12)
    return HARMONICS[s] * 2**o


def mean_open(duty: float) -> float:
    """The open fraction averaged over a hole pitch (the sketch's)."""
    return float(np.mean(sr.overlap(np.abs(np.linspace(-0.5, 0.5, 512)) * 2 / duty)))


def model() -> dict[str, Any]:
    """The keyboard's data, as the component saves it and invented.rs reads it."""
    keys = []
    for n in range(LOW, HIGH + 1):
        h = holes_of(n)
        keys.append(
            {
                "note": n,
                "holes": float(h),
                "f_hz": h * SHAFT_HZ,
                "area_m2": sr.HOLE_M2 * AREA_REF_HOLES / h,
                "phase": (n * RING_PHASE) % 1.0,
            }
        )
    duty = [sr.STOPS["flute"], sr.STOPS["reed"]]
    return {
        "instrument": KIND,
        "source": "varimu/invented/keys/siren.py from varimu/invented/siren.py's values",
        "keys": keys,
        "shaft_hz": SHAFT_HZ,
        "rho": sr.RHO,
        "cd": sr.CD,
        "p_max_pa": sr.P_MAX_PA,
        "blower_q_m3_s": sr.BLOWER_Q_M3_S,
        "bellows_m3_pa": sr.BELLOWS_M3_PA,
        "motor_slope": sr.MOTOR_SLOPE,
        "friction": sr.FRICTION,
        "key_drag": sr.KEY_DRAG,
        "inertia": sr.INERTIA,
        "chamber_q": sr.CHAMBER_Q,
        "jet_noise": sr.JET_NOISE,
        "jet_noise_hz": JET_NOISE_HZ,
        "noise_ref_holes": float(AREA_REF_HOLES),
        "duty": duty,
        "mean_open": [mean_open(d) for d in duty],
        "open_range": list(OPEN_RANGE),
        "valve_open_s": VALVE_OPEN_S,
        "valve_close_s": VALVE_CLOSE_S,
        "speed_octaves": SPEED_OCTAVES,
        "wind_range": list(WIND_RANGE),
        "motor_octaves": MOTOR_OCTAVES,
        "hunt_hz": HUNT_HZ,
        "hunt_depth": HUNT_DEPTH,
        "wander": WANDER,
        "wander_hz": WANDER_HZ,
        "tail_s": TAIL_S,
        "mic_r_m": MIC_R_M,
        "mic_v_per_pa": MIC_V_PER_PA,
        "seed": SEED,
        "wander_seed": WANDER_SEED,
    }


def knob(lo_hi: list[float], k: float) -> float:
    return lo_hi[0] + (lo_hi[1] - lo_hi[0]) * k


class Valve:
    """A key's valve (invented.rs's Valve): the voice and the shaft each keep one, moved by
    the same events."""

    def __init__(self, m: dict[str, Any], fs: float) -> None:
        self.m = m
        self.up = 1.0 / (m["valve_open_s"] * fs)
        self.dn = 1.0 / (m["valve_close_s"] * fs)
        self.v = 0.0
        self.down = False
        self.pedal_down = False
        self.held = False
        self.opening = 0.0
        self.after = 0.0

    def on(self, velocity: int) -> None:
        self.down = True
        self.held = True
        self.opening = knob(self.m["open_range"], velocity / 127.0)

    def off(self) -> None:
        self.down = False
        self.held = self.pedal_down

    def pedal(self, down: bool) -> None:
        self.pedal_down = down
        self.held = self.down or (down and self.held)

    def pressure(self, value: int) -> None:
        self.after = value / 127.0

    def target(self) -> float:
        if self.held:
            return self.opening + (1.0 - self.opening) * self.after
        return 0.0

    def step(self) -> float:
        t = self.target()
        if self.v < t:
            self.v = min(self.v + self.up, t)
        elif self.v > t:
            self.v = max(self.v - self.dn, t)
        return self.v


class Shaft:
    """The motor, the bellows and the shaft's angle, shared by every key (invented.rs's
    Shaft, step for step)."""

    def __init__(self, m: dict[str, Any], fs: float, knobs: list[float]) -> None:
        self.m = m
        self.fs = fs
        self.dt = 1.0 / fs
        self.keys = [k["note"] for k in m["keys"]]
        self.valves = {k["note"]: Valve(m, fs) for k in m["keys"]}
        self.area = {k["note"]: k["area_m2"] for k in m["keys"]}
        self.wander = Chest(m["wander_seed"], fs, m["wander_hz"])
        self.t = 0
        self.knobs = knobs
        self.set_panel()
        self.w = self.w_nl * self.lever * self.motor / (self.motor + m["friction"])
        self.p = self.p_max
        self.rev = 0.0
        self.jet = math.sqrt(2.0 * self.p / m["rho"])

    def set_panel(self) -> None:
        m = self.m
        k = self.knobs
        self.lever = 2.0 ** (m["speed_octaves"] * (2.0 * k[0] - 1.0))
        self.stop = 1 if k[1] >= 0.5 else 0
        self.p_max = m["p_max_pa"] * knob(m["wind_range"], k[2])
        self.motor = m["motor_slope"] * 2.0 ** (m["motor_octaves"] * (2.0 * k[3] - 1.0))
        self.w_nl = m["shaft_hz"] * (self.motor + m["friction"] + m["key_drag"]) / self.motor

    def event(self, kind: str, note: int, value: float) -> None:
        if kind == "on" and value > 0 and note in self.valves:
            self.valves[note].on(int(value))
        elif kind in ("on", "off") and note in self.valves:
            self.valves[note].off()
        elif kind == "pedal":
            for v in self.valves.values():
                v.pedal(value > 0)
        elif kind == "pressure":
            for v in self.valves.values():
                v.pressure(int(value))

    def step(self) -> None:
        m = self.m
        open_sum = 0.0
        draw = 0.0
        mo = m["mean_open"][self.stop]
        for n in self.keys:
            v = self.valves[n].step()
            if v > 0.0:
                open_sum += v
                draw += mo * v * self.area[n]
        drag = m["friction"] + m["key_drag"] * open_sum
        pull = self.motor * (self.w_nl * self.lever - self.w) - drag * self.w
        self.w += self.dt / m["inertia"] * pull
        q_out = m["cd"] * draw * math.sqrt(2.0 * self.p / m["rho"])
        q_in = m["blower_q_m3_s"] * (1.0 - self.p / self.p_max)
        self.p = min(max(self.p + self.dt / m["bellows_m3_pa"] * (q_in - q_out), 1.0), self.p_max)
        t = self.t
        hunt = (
            1.0
            + m["hunt_depth"] * math.sin(2.0 * math.pi * m["hunt_hz"] * t / self.fs)
            + m["wander"] * self.wander.at(t)
        )
        self.rev += self.w * hunt * self.dt
        self.rev -= math.floor(self.rev)
        self.jet = math.sqrt(2.0 * self.p / m["rho"])
        self.t = t + 1


def chamber(f_hz: float, q: float, fs: float) -> tuple[float, float, float, float, float]:
    """wn^2 / (s^2 + wn / Q s + wn^2), bilinear: (b0, b1, b2, a1, a2)."""
    wn = 2.0 * math.pi * f_hz
    k = 2.0 * fs
    k2 = k * k
    w2 = wn * wn
    a0 = k2 + wn * k / q + w2
    a1 = (2.0 * w2 - 2.0 * k2) / a0
    a2 = (k2 - wn * k / q + w2) / a0
    return (w2 / a0, 2.0 * w2 / a0, w2 / a0, a1, a2)


class Voice:
    """One key's ring (invented.rs's SirenVoice, step for step)."""

    def __init__(
        self, m: dict[str, Any], key: dict[str, Any], fs: float, knobs: list[float], shaft: Shaft
    ) -> None:
        self.m = m
        self.fs = fs
        self.shaft = shaft
        self.holes = key["holes"]
        self.phase = key["phase"]
        self.area = key["area_m2"]
        self.valve = Valve(m, fs)
        self.ch = chamber(key["f_hz"], m["chamber_q"], fs)
        self.gauss = Gauss(key_seed(m["seed"], key["note"]))
        band = m["jet_noise_hz"] * self.holes / m["noise_ref_holes"]
        a = math.exp(-2.0 * math.pi * band / fs)
        self.na = a
        # two one-poles in cascade, unit rms: var = (1 - a)^4 (1 + a^2) / (1 - a^2)^3
        self.norm = 1.0 / math.sqrt((1.0 - a) ** 4 * (1.0 + a * a) / (1.0 - a * a) ** 3)
        self.gain = m["mic_v_per_pa"] * m["rho"] / (4.0 * math.pi * m["mic_r_m"]) * fs
        self.tail_n = int(m["tail_s"] * fs)
        self.awake = False
        self.quiet = 0
        self.reset()
        self.set_knobs(knobs)

    def reset(self) -> None:
        self.nz = self.nz1 = 0.0
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0
        self.u1 = 0.0

    def set_knobs(self, k: list[float]) -> None:
        self.stop = 1 if k[1] >= 0.5 else 0

    def asleep(self) -> bool:
        return not self.awake

    def on(self, velocity: int) -> None:
        self.valve.on(velocity)
        self.awake = True
        self.quiet = 0

    def off(self) -> None:
        self.valve.off()

    def pedal(self, down: bool) -> None:
        self.valve.pedal(down)

    def pressure(self, value: int) -> None:
        self.valve.pressure(value)

    def step(self) -> float:
        m = self.m
        v = self.valve.step()
        x = self.holes * self.shaft.rev + self.phase
        f = x - math.floor(x)
        dist = min(f, 1.0 - f)
        xx = min(dist / m["duty"][self.stop], 1.0)
        open_frac = (2.0 * math.acos(xx) - 2.0 * xx * math.sqrt(1.0 - xx * xx)) / math.pi
        q = m["cd"] * self.area * open_frac * self.shaft.jet * v
        self.nz1 = self.na * self.nz1 + (1.0 - self.na) * self.gauss.next()
        self.nz = self.na * self.nz + (1.0 - self.na) * self.nz1
        q = q + m["jet_noise"] * q * (self.nz * self.norm)
        if self.stop == 0:
            b0, b1, b2, a1, a2 = self.ch
            u = b0 * q + b1 * self.x1 + b2 * self.x2 - a1 * self.y1 - a2 * self.y2
            self.x2, self.x1 = self.x1, q
            self.y2, self.y1 = self.y1, u
        else:
            u = q
        y = self.gain * (u - self.u1)
        self.u1 = u
        if v == 0.0 and self.valve.target() == 0.0:
            self.quiet += 1
            if self.quiet >= self.tail_n:
                self.awake = False
                self.reset()
        else:
            self.quiet = 0
        return y


def keyboard(m: dict[str, Any], fs: float, knobs: list[float]) -> tuple[dict[int, Voice], Shaft]:
    """The keys and the shaft they share (pass the shaft to common.play's `shared`)."""
    shaft = Shaft(m, fs, knobs)
    return {k["note"]: Voice(m, k, fs, knobs, shaft) for k in m["keys"]}, shaft

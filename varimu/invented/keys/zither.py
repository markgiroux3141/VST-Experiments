"""IL2, the Buzz Zither's keyboard (docs/INVENTED_LIVE_PLAN.md): the sketch's jawari string
(varimu.invented.jawari) per key, played by note events, as circuitsim's invented.rs plays
it.

Per key: a finite-difference string (the plain wave equation with the loss sigma0 +
sigma1 from two decay times, Bilbao's scheme), fixed at both ends, over a parabolic bridge
along its first BRIDGE_M; the contact is a one-sided penalty solved implicitly at each
bridge point (rigid in effect). The grid follows the stream's rate: h = c k / COURANT, so
every string has ~0.98 fs / (2 f0) points (C3 at 96 kHz: 359, the sketch's own grid). A key
down plucks its string with a force F (the finger's rounded triangle, A = F p (L - p) / (T L),
replaces the string's state: a ringing string is caught and plucked again; the bridge then
feels ~F (1 - p / L) on every string, long or short); a key up drops the felt damper (sigma0 x DAMPER) and
the voice sleeps SLEEP_S later. The soundboard reads the force on the bridge (the end's
tension plus every contact force) through the gourd and top's four body resonances.

The tanpura: four more strings (Pa, Sa, Sa, low Sa), plucked in turn by a cam while the
sustain pedal is down (one every DRONE_GAP_S), damped by the cam's felt when it lifts.

The panel: k0 JAWARI (0 = a sharp bridge, no contact; above 0 the bridge's drop over its
length is DROP_FLAT_M / k0: flatter, more buzz), k1 PLUCK POINT (0.1-0.5 of the length,
at the next pluck), k2 DRONE (the cam's pluck force, 0 = silent), k3 DRONE TONIC (Sa
C3 up to B3 in semitones, at each drone string's next pluck). Velocity sets the pluck's
force (FORCE_MIN_N-FORCE_MAX_N, linear).

Bit-exactness: elementwise numpy is exactly rounded, as Rust's scalar loop is, so the
string's update is vectorized; every sum is a plain loop in Rust's order.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from varimu.invented import jawari as jw
from varimu.invented.keys.common import bandpass

KIND = "buzz_zither"
LOW, HIGH = 36, 84  # C2-C6
SA_NOTE = 48  # C3: the strings' reference length and the drone's Sa at DRONE TONIC 0
LENGTH_REF_M = jw.LENGTH_M  # C3's speaking length; the others scale as 1 / f (a harp's)
LENGTH_RANGE_M = (0.2, 1.4)  # design choice: the bass capped at 1.4 m, the treble at 0.2 m
COURANT = 0.98
F_HIGH_HZ = 5000.0  # the second decay time's frequency (the sketch's)
DROP_FLAT_M = 6e-6  # JAWARI 1's drop over BRIDGE_M (the sketch's best, 10 um, at k0 0.6)
DAMPER = 60.0  # the felt multiplies sigma0 (the sketch's)
SLEEP_S = 1.0  # after the damper falls (sigma0 x 60: T60 ~0.2 s, -300 dB in 1 s)
FORCE_MIN_N, FORCE_MAX_N = 0.1, 1.0  # a finger's release force: provisional, model knowledge
PLUCK_RANGE = (0.1, 0.5)
DRONE_OFFSETS = (-5, 0, 0, -12)  # Pa (a fourth below Sa), Sa, Sa, low Sa
DRONE_PLUCK_AT = (0.27, 0.29, 0.31, 0.33)  # the sketch's
DRONE_GAP_S = 0.95  # the cam: a string every 0.95 s (the sketch's tanpura cycle)
DRONE_FORCE_N = 0.45  # at DRONE 1 (the sketch's tanpura, 1.5 mm at C3, is 0.29 N: DRONE 0.67)
DRONE_STEPS = 11  # DRONE TONIC's semitones
SOUNDBOARD = ((180.0, 4.0, 1.5), (420.0, 5.0, 1.0), (1100.0, 3.0, 0.6), (2600.0, 2.0, 0.4))
V_PER_N = 1.0  # a piezo under the bridge: provisional, model knowledge
SAVGOL_9_2 = (-21.0, 14.0, 39.0, 54.0, 59.0, 54.0, 39.0, 14.0, -21.0)  # / 231


def length_m(f_hz: float) -> float:
    f_ref = 440.0 * 2.0 ** ((SA_NOTE - 69) / 12)
    return min(max(LENGTH_REF_M * f_ref / f_hz, LENGTH_RANGE_M[0]), LENGTH_RANGE_M[1])


def hz(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12)


def model() -> dict[str, Any]:
    """The keyboard's data, as the component saves it and invented.rs reads it."""
    keys = [
        {"note": n, "f_hz": hz(n), "length_m": length_m(hz(n))} for n in range(LOW, HIGH + 1)
    ]
    drone_hz = [[hz(SA_NOTE + o + s) for s in range(DRONE_STEPS + 1)] for o in DRONE_OFFSETS]
    return {
        "instrument": KIND,
        "source": "varimu/invented/keys/zither.py from varimu/invented/jawari.py's values",
        "keys": keys,
        "sa_note": SA_NOTE,
        "length_ref_m": LENGTH_REF_M,
        "length_range_m": list(LENGTH_RANGE_M),
        "rho_a_kg_m": jw.RHO_A,
        "bridge_m": jw.BRIDGE_M,
        "drop_flat_m": DROP_FLAT_M,
        "k_contact": jw.K_CONTACT,
        "t60_low_s": jw.T60_LOW_S,
        "t60_high_s": jw.T60_HIGH_S,
        "f_high_hz": F_HIGH_HZ,
        "courant": COURANT,
        "damper": DAMPER,
        "sleep_s": SLEEP_S,
        "force_range_n": [FORCE_MIN_N, FORCE_MAX_N],
        "pluck_range": list(PLUCK_RANGE),
        "drone_hz": drone_hz,
        "drone_length_m": [[length_m(f) for f in row] for row in drone_hz],
        "drone_pluck_at": list(DRONE_PLUCK_AT),
        "drone_gap_s": DRONE_GAP_S,
        "drone_force_n": DRONE_FORCE_N,
        "drone_steps": DRONE_STEPS,
        "soundboard": [list(b) for b in SOUNDBOARD],
        "v_per_n": V_PER_N,
    }


def knob(lo_hi: list[float], k: float) -> float:
    return lo_hi[0] + (lo_hi[1] - lo_hi[0]) * k


class String:
    """One string over the jawari (invented.rs's JawariString, step for step)."""

    def __init__(self, m: dict[str, Any], fs: float) -> None:
        self.m = m
        self.k = 1.0 / fs
        self.jawari = 0.0
        self.damped = True

    def tune(self, f_hz: float, length: float) -> None:
        """The string's grid and losses for pitch f_hz over length (at rest)."""
        m, k = self.m, self.k
        c = 2.0 * length * f_hz
        h = c * k / m["courant"]
        nx = int(length / h)
        h = length / nx
        self.nx, self.h, self.length = nx, h, length
        lam = c * k / h
        self.lam2 = lam * lam
        w1 = 2.0 * math.pi * f_hz
        w2 = 2.0 * math.pi * m["f_high_hz"]
        xi1 = (w1 / c) * (w1 / c)
        xi2 = (w2 / c) * (w2 / c)
        g = 6.0 * math.log(10.0) / (xi2 - xi1)
        s1 = g * (1.0 / m["t60_high_s"] - 1.0 / m["t60_low_s"])
        self.s0_free = g * (xi2 / m["t60_low_s"] - xi1 / m["t60_high_s"])
        self.s1 = max(s1, 0.0)
        self.bs = 2.0 * self.s1 * k / (h * h)
        if self.lam2 + 4.0 * self.s1 * k / (h * h) > 1.0:
            raise ValueError(f"unstable string at {f_hz} Hz")
        self.t_n = c * c * m["rho_a_kg_m"]
        self.nb = int(m["bridge_m"] / h) + 1
        self.r2 = []
        for i in range(self.nb):
            r = (i * h) / m["bridge_m"]
            self.r2.append(r * r)
        self.u = np.zeros(nx + 1)
        self.u1 = np.zeros(nx + 1)
        self.lapp = np.zeros(nx + 1)
        self.set_damped(self.damped)
        self.set_jawari(self.jawari)

    def set_damped(self, damped: bool) -> None:
        m, k = self.m, self.k
        self.damped = damped
        s0 = self.s0_free * m["damper"] if damped else self.s0_free
        self.c1 = 1.0 - s0 * k
        self.a0 = 1.0 / (1.0 + s0 * k)
        self.kc = self.a0 * m["k_contact"] * k * k / m["rho_a_kg_m"]

    def set_jawari(self, j: float) -> None:
        self.jawari = j
        if j > 0.0:
            drop = self.m["drop_flat_m"] / j
            self.b = [-(drop * r2) for r2 in self.r2]

    def pluck(self, force_n: float, at: float) -> None:
        """Released from the finger's rounded triangle (a 9-point Savitzky-Golay smoothing of
        it), held by `force_n` at `at` of the length, at rest."""
        nx, h, length = self.nx, self.h, self.length
        amp_m = force_n * at * (1.0 - at) * length / self.t_n
        p = at * length
        tri = []
        for i in range(nx + 1):
            x = i * h
            tri.append(x / p if x < p else (length - x) / (length - p))
        u = np.zeros(nx + 1)
        for i in range(nx + 1):
            if 4 <= i <= nx - 4:
                s = 0.0
                for j in range(9):
                    s += SAVGOL_9_2[j] * tri[i + j - 4]
                u[i] = amp_m * (s / 231.0)
            else:
                u[i] = amp_m * tri[i]
        u[0] = 0.0
        u[nx] = 0.0
        self.u = u
        self.u1 = u.copy()
        self.lapp = np.zeros(nx + 1)
        self.lapp[1:-1] = (u[2:] - 2.0 * u[1:-1]) + u[:-2]

    def step(self) -> float:
        """One step: the force on the bridge (N)."""
        u, u1 = self.u, self.u1
        lap = np.zeros(self.nx + 1)
        lap[1:-1] = (u[2:] - 2.0 * u[1:-1]) + u[:-2]
        un = self.a0 * (
            ((2.0 * u - self.c1 * u1) + self.lam2 * lap) + self.bs * (lap - self.lapp)
        )
        un[0] = 0.0
        un[-1] = 0.0
        contact = 0.0
        if self.jawari > 0.0:
            acc = 0.0
            kc = self.kc
            for i in range(1, self.nb):
                free = float(un[i])
                b = self.b[i]
                if free < b:
                    fixed = (free + kc * b) / (1.0 + kc)
                    acc += b - fixed
                    un[i] = fixed
            contact = self.m["k_contact"] * self.h * acc
        self.u1, self.u, self.lapp = u, un, lap
        return self.t_n * float(un[1]) / self.h + contact


class Voice:
    """One key's string, or one of the tanpura's (invented.rs's ZitherVoice, step for step)."""

    def __init__(
        self, m: dict[str, Any], fs: float, knobs: list[float], key: dict | None, drone: int
    ):
        self.m = m
        self.fs = fs
        self.drone = drone  # -1: a key; else the cam's string 0-3
        self.string = String(m, fs)
        self.note = -1
        if key is not None:
            self.string.tune(key["f_hz"], key["length_m"])
        else:
            self.retune(0)
        self.bp = [bandpass(f, q, fs) for f, q, _ in m["soundboard"]]
        self.gain = [g for _, _, g in m["soundboard"]]
        self.st = [[0.0, 0.0, 0.0, 0.0] for _ in self.bp]  # x1, x2, y1, y2
        self.awake = False
        self.quiet = 0
        self.sleep_n = int(m["sleep_s"] * fs)
        self.cam = -1  # samples since the pedal went down; -1: the cam stopped
        self.gap_n = int(m["drone_gap_s"] * fs)
        self.set_knobs(knobs)

    def retune(self, step: int) -> None:
        """The drone string tuned DRONE TONIC's `step` semitones up (re-strung at rest)."""
        if step != self.note:
            self.note = step
            d = self.drone
            self.string.tune(self.m["drone_hz"][d][step], self.m["drone_length_m"][d][step])

    def set_knobs(self, k: list[float]) -> None:
        self.k = list(k)
        if k[0] != self.string.jawari:
            self.string.set_jawari(k[0])

    def asleep(self) -> bool:
        return not self.awake

    def wake(self) -> None:
        self.awake = True
        self.quiet = 0
        self.string.set_damped(False)

    def on(self, velocity: int) -> None:
        if self.drone >= 0:
            return
        force = knob(self.m["force_range_n"], velocity / 127.0)
        self.string.pluck(force, knob(self.m["pluck_range"], self.k[1]))
        self.wake()

    def damp(self) -> None:
        if not self.string.damped:
            self.string.set_damped(True)
            self.quiet = 0

    def off(self) -> None:
        if self.drone < 0:
            self.damp()

    def pedal(self, down: bool) -> None:
        if self.drone < 0:
            return
        if down and self.cam < 0:
            self.cam = 0
            self.wake()
        elif not down and self.cam >= 0:
            self.cam = -1
            self.damp()

    def pressure(self, value: int) -> None:
        pass

    def step(self) -> float:
        m = self.m
        if self.cam >= 0:
            at = self.drone * self.gap_n
            if self.cam >= at and (self.cam - at) % (4 * self.gap_n) == 0:
                step = math.floor(self.k[3] * m["drone_steps"] + 0.5)
                self.retune(min(max(step, 0), m["drone_steps"]))
                self.string.pluck(self.k[2] * m["drone_force_n"], m["drone_pluck_at"][self.drone])
            self.cam += 1
        x = self.string.step()
        y = x
        for i in range(len(self.bp)):
            b0, b1, b2, a1, a2 = self.bp[i]
            s = self.st[i]
            yb = b0 * x + b1 * s[0] + b2 * s[1] - a1 * s[2] - a2 * s[3]
            s[1], s[0] = s[0], x
            s[3], s[2] = s[2], yb
            y += self.gain[i] * yb
        if self.string.damped:
            self.quiet += 1
            if self.quiet >= self.sleep_n:
                self.awake = False
        return m["v_per_n"] * y


def keyboard(m: dict[str, Any], fs: float, knobs: list[float]) -> dict[int, Voice]:
    """The drone's strings on notes 0-3 (no key plays them), then the keys."""
    kb = {i: Voice(m, fs, knobs, None, i) for i in range(len(m["drone_hz"]))}
    for k in m["keys"]:
        kb[k["note"]] = Voice(m, fs, knobs, k, -1)
    return kb

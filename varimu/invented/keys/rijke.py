"""IL3, the Rijke Organ's keyboard (docs/INVENTED_LIVE_PLAN.md): the sketch's reduced Rijke
tube (varimu.invented.rijke) per key, played by note events, as circuitsim's invented.rs
plays it.

Per key: an open pipe's MODES Galerkin modes in time units of L / c (one exact step of each
damped oscillator a sample, the force held over it), driven by the gauze's heat release by
King's law with the time lag TAU (a delay line of round(TAU / dt) samples: re-derived from
the stream's rate). A key switches the gauze's heater on at a power set by its velocity
(aftertouch adds to it, the pedal holds released keys' heaters on); the gauze follows with
its thermal lag (a one-pole of GAUZE_S). The instability is subcritical: a pipe starts
suddenly once the gauze passes ~0.55 and holds down to ~0.25 (the sketch's). The plume's
breath forces the modes in proportion to the heat (Gaussian noise, one-pole low-passed at
BREATH_HZ, from the key's seed). The sound is the volume velocity leaving both open ends,
differentiated (a backward difference), at a microphone's sensitivity, scaled by the pipe's
bore: its area goes as 1 / f (BORE_REF_HZ's pipe 1), so every pipe radiates alike (the
derivative alone puts the treble +6 dB an octave up; organ builders' normal scale halves the
diameter at the 17th note, this one every second octave). A voice sleeps once
its gauze is cold and its modes quiet.

The panel: k0 HEAT (the heaters' power 0.5-1.5x the key's), k1 GAUZE (the gauze's place up
the pipe, 0.15-0.45 of the length; 0.29 the sketch's: a stop of gauzes), k2 BREATH (the
plume's turbulence 0-4x the sketch's). Velocity sets the heater's power (K_MIN-K_MAX,
linear); aftertouch adds up to K_PRESSURE.
"""

from __future__ import annotations

import math
from typing import Any

from varimu.invented import rijke as rj
from varimu.invented.keys.common import Gauss, key_seed

KIND = "rijke_organ"
LOW, HIGH = 36, 84  # C2-C6: pipes 2.6 m-0.16 m
K_MIN, K_MAX = 0.6, 1.2  # the heater's power (dimensionless K; the sketch's key 0.8)
K_PRESSURE = 0.4  # aftertouch's most
K_REF = rj.K_PLAY  # the breath's scale (the sketch's: in proportion to K / 0.8)
HEAT_RANGE = (0.5, 1.5)
GAUZE_RANGE = (0.15, 0.45)
BREATH_MAX = 4.0
BREATH_HZ = 2000.0  # the sketch's
SLEEP_K = 1e-3  # the gauze cold
SLEEP_ENERGY = 1e-12  # the modes quiet (sum of eta^2)
MIC_V = 2e-4  # volts per unit of the ends' outflow rate at BORE_REF_HZ: ~0.5 V rms a held pipe
BORE_REF_HZ = 220.0  # A3
SEED = 1


def model() -> dict[str, Any]:
    """The keyboard's data, as the component saves it and invented.rs reads it."""
    keys = []
    for n in range(LOW, HIGH + 1):
        f = 440.0 * 2.0 ** ((n - 69) / 12)
        keys.append({"note": n, "f_hz": f, "bore": BORE_REF_HZ / f})
    return {
        "instrument": KIND,
        "source": "varimu/invented/keys/rijke.py from varimu/invented/rijke.py's values",
        "keys": keys,
        "c_air_m_s": rj.C_AIR,
        "modes": rj.MODES,
        "tau": rj.TAU,
        "c1": rj.C1,
        "c2": rj.C2,
        "gauze_s": rj.GAUZE_S,
        "turbulence": rj.TURBULENCE,
        "k_range": [K_MIN, K_MAX],
        "k_pressure": K_PRESSURE,
        "k_ref": K_REF,
        "heat_range": list(HEAT_RANGE),
        "gauze_range": list(GAUZE_RANGE),
        "breath_max": BREATH_MAX,
        "breath_hz": BREATH_HZ,
        "sleep_k": SLEEP_K,
        "sleep_energy": SLEEP_ENERGY,
        "mic_v": MIC_V,
        "seed": SEED,
    }


def knob(lo_hi: list[float], k: float) -> float:
    return lo_hi[0] + (lo_hi[1] - lo_hi[0]) * k


class Voice:
    """One key's pipe (invented.rs's RijkeVoice, step for step)."""

    def __init__(self, m: dict[str, Any], key: dict[str, Any], fs: float, knobs: list[float]):
        self.m = m
        self.fs = fs
        f1 = key["f_hz"]
        length = m["c_air_m_s"] / (2.0 * f1)
        dt = (m["c_air_m_s"] / length) / fs
        n = m["modes"]
        self.n = n
        w1 = math.pi
        self.p, self.g = [], []
        for j in range(1, n + 1):
            w = j * math.pi
            zeta = (m["c1"] * w / w1 + m["c2"] * math.sqrt(w1 / w)) / (2.0 * math.pi)
            wd = w * math.sqrt(1.0 - zeta * zeta)
            e = math.exp(-zeta * w * dt)
            cs, sn = math.cos(wd * dt), math.sin(wd * dt)
            p00 = e * (cs + zeta * w / wd * sn)
            p01 = e * sn / wd
            p10 = -e * w * w / wd * sn
            p11 = e * (cs - zeta * w / wd * sn)
            self.p.append((p00, p01, p10, p11))
            self.g.append(((1.0 - p00) / (w * w), -p10 / (w * w)))
        self.lag = max(math.floor(m["tau"] / dt + 0.5), 1)
        self.buf = [0.0] * self.lag
        self.at = 0
        self.eta = [0.0] * n
        self.deta = [0.0] * n
        self.ends = [-2.0 if j % 2 == 1 else 0.0 for j in range(1, n + 1)]
        self.prev = 0.0
        self.bore = key["bore"]
        self.ag = math.exp(-1.0 / (m["gauze_s"] * fs))
        self.kg = 0.0  # the gauze's heat (K)
        a = math.exp(-2.0 * math.pi * m["breath_hz"] / fs)
        self.na = a
        self.norm = math.sqrt((1.0 + a) / (1.0 - a))
        self.nz = 0.0
        self.gauss = Gauss(key_seed(m["seed"], key["note"]))
        self.down = False
        self.pedal_down = False
        self.held = False
        self.velocity = 0.0
        self.aftertouch = 0.0
        self.awake = False
        self.x_f = -1.0
        self.set_knobs(knobs)

    def set_knobs(self, k: list[float]) -> None:
        m = self.m
        self.heat = knob(m["heat_range"], k[0])
        x_f = knob(m["gauze_range"], k[1])
        if x_f != self.x_f:
            self.x_f = x_f
            self.sf = [math.sin(j * math.pi * x_f) for j in range(1, self.n + 1)]
            self.cf = [math.cos(j * math.pi * x_f) for j in range(1, self.n + 1)]
        self.breath = m["breath_max"] * k[2]

    def asleep(self) -> bool:
        return not self.awake

    def on(self, velocity: int) -> None:
        self.down = True
        self.held = True
        self.velocity = velocity / 127.0
        self.awake = True

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
        k_in = 0.0
        if self.held:
            k_in = self.heat * (knob(m["k_range"], self.velocity) + m["k_pressure"] * self.aftertouch)
        self.kg = (1.0 - self.ag) * k_in + self.ag * self.kg
        self.nz = self.na * self.nz + (1.0 - self.na) * self.gauss.next()
        turb = m["turbulence"] * self.breath * self.nz * self.norm * self.kg / m["k_ref"]
        uf_late = self.buf[self.at]
        q = self.kg * (math.sqrt(abs(1.0 / 3.0 + uf_late)) - math.sqrt(1.0 / 3.0))
        uf = 0.0
        out = 0.0
        energy = 0.0
        for i in range(self.n):
            jp = (i + 1) * math.pi
            force = (-jp * q) * self.sf[i] + turb * self.sf[i]
            p00, p01, p10, p11 = self.p[i]
            g0, g1 = self.g[i]
            e, de = self.eta[i], self.deta[i]
            e2 = p00 * e + p01 * de + g0 * force
            self.deta[i] = p10 * e + p11 * de + g1 * force
            self.eta[i] = e2
            uf += self.cf[i] * e2
            out += self.ends[i] * e2
            energy += e2 * e2
        self.buf[self.at] = uf
        self.at = (self.at + 1) % self.lag
        y = (out - self.prev) * self.fs
        self.prev = out
        if not self.held and self.kg < m["sleep_k"] and energy < m["sleep_energy"]:
            self.awake = False
        return m["mic_v"] * self.bore * y


def keyboard(m: dict[str, Any], fs: float, knobs: list[float]) -> dict[int, Voice]:
    return {k["note"]: Voice(m, k, fs, knobs) for k in m["keys"]}

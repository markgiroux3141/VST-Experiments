"""IL1, the Rosin Wheel Organ's keyboard (docs/INVENTED_LIVE_PLAN.md): the sketch's bowed
bar (varimu.invented.friction) per key, played by note events, as circuitsim's invented.rs
plays it.

Per key: a free-free steel bar's bending modes (one trapezoidal step a sample), bowed at its
end by the wheel. The contact force at the step's end is solved exactly from the rosin
curve: stick while the static limit holds, else the slip speed from a quadratic. The key's
press rises over ATTACK_S as a smoothstep and falls over RELEASE_S. When it reaches zero
after a release, the felt damper falls (every mode's Q at most Q_DAMPED), and the voice
sleeps SLEEP_S later. The pickup reads the far end's velocity through the bar's tuned tube
(a band-pass at f1 added). Rosin noise is one-pole low-passed Gaussian noise, and the
wheel's eccentricity is a rotating phasor.

The panel: k0 WHEEL (0-1: 0.1-0.5 m/s), k1 RESONATOR (0-1: the tube's gain 0-4), k2 TOUCH
(0-1: the press 0.5-2x), k3 LIMIT (0: off; else a check felt at each bar's free end, set
closer as it turns up). Velocity sets the press force (FORCE_MIN_N-FORCE_MAX_N, ^1.5),
aftertouch adds up to PRESSURE_GAIN of it, and the pedal holds released keys pressed.

LIMIT (ROSIN_WHEEL@2 on; a model without `felt_c_n_s_m` has none): a held bar's stick-slip
grows until its limit cycle, whose size follows the wheel's speed (at the fastest WHEEL one
bar alone swells for 5-10 s past the full scale). The check felt rests a gap from the bar's
free end; past the gap the bar rubs it (a viscous drag FELT_C on the end's velocity, engaging
over a smoothstep across FELT_WIDTH of the gap), which caps the held swing. Each bar's gap is
v_lim / (2 pi f1): voiced so every bar meets its felt at the same end velocity; LIMIT sets
v_lim from LIMIT_V_M_S[0] (barely) to [1] (closest), evenly in log. The felt's force is
explicit (from the step's start: stable while FELT_C < m / (2 n h), thousands of N s/m) and
folded into the bar's free step before the wheel's contact is solved.
"""

from __future__ import annotations

import math
from typing import Any

from varimu.invented import friction as fr
from varimu.invented.keys.common import Gauss, bandpass, key_seed, modal_step

KIND = "rosin_wheel"
LOW, HIGH = 36, 84  # C2-C6: bars 0.80 m-0.20 m
F_TOP_HZ = 18_000.0  # modes kept below this
ATTACK_S = 0.08
RELEASE_S = 0.04
SLEEP_S = 1.5  # after the damper falls (Q 40 at 65 Hz: -100 dB well before)
FORCE_MIN_N, FORCE_MAX_N, FORCE_EXP = 0.4, 4.0, 1.5
PRESSURE_GAIN = 1.0
NOISE_HZ = 3000.0
PICKUP_V_PER_M_S = 2.0  # a magnetic pickup's sensitivity: provisional, model knowledge
WHEEL_RANGE_M_S = (0.1, 0.5)
RESONATOR_MAX = 4.0
RESONATOR_Q = 18.0
TOUCH_RANGE = (0.5, 2.0)
# the check felt's drag: provisional, design choice (firm: 10 let hard-pressed bars through)
FELT_C_N_S_M = 30.0
# the end velocity where the felt engages, LIMIT just on .. full: held ~2.4 V .. ~0.22 V
# (just on: above a bar's own level at the default panel, 1.6 V)
LIMIT_V_M_S = (0.3, 0.03)
FELT_WIDTH = 0.5  # the felt engages over this fraction of its gap beyond it
SEED = 1


def model() -> dict[str, Any]:
    """The keyboard's data, as the component saves it and invented.rs reads it."""
    keys = []
    for note in range(LOW, HIGH + 1):
        f1 = 440.0 * 2.0 ** ((note - 69) / 12)
        length = fr.bar_length_m(f1)
        mass = fr.STEEL_RHO * fr.BAR_W_M * fr.BAR_T_M * length
        f = [f1 * (b / fr.BETA[0]) ** 2 for b in fr.BETA]
        f = [float(x) for x in f if x < F_TOP_HZ]
        q = [float(fr.Q1 * (x / f1) ** -0.5) for x in f]
        keys.append({"note": note, "f_hz": f, "q": q, "mass_kg": float(mass)})
    return {
        "instrument": KIND,
        "source": "varimu/invented/keys/rosin.py from varimu/invented/friction.py's values",
        "keys": keys,
        "mu_s": fr.MU_S,
        "mu_d": fr.MU_D,
        "v0_m_s": fr.V0_M_S,
        "wheel_range_m_s": list(WHEEL_RANGE_M_S),
        "wheel_hz": fr.WHEEL_HZ,
        "wobble": 0.03,
        "rosin_noise": 0.04,
        "noise_hz": NOISE_HZ,
        "force_min_n": FORCE_MIN_N,
        "force_max_n": FORCE_MAX_N,
        "force_exp": FORCE_EXP,
        "pressure_gain": PRESSURE_GAIN,
        "touch_range": list(TOUCH_RANGE),
        "attack_s": ATTACK_S,
        "release_s": RELEASE_S,
        "q_damped": fr.Q_DAMPED,
        "sleep_s": SLEEP_S,
        "resonator_max": RESONATOR_MAX,
        "resonator_q": RESONATOR_Q,
        "pickup_v_per_m_s": PICKUP_V_PER_M_S,
        "felt_c_n_s_m": FELT_C_N_S_M,
        "limit_v_m_s": list(LIMIT_V_M_S),
        "felt_width": FELT_WIDTH,
        "seed": SEED,
    }


def knob(lo_hi: list[float], k: float) -> float:
    return lo_hi[0] + (lo_hi[1] - lo_hi[0]) * k


class Voice:
    """One key's bar (invented.rs's RosinVoice, step for step)."""

    def __init__(self, m: dict[str, Any], key: dict[str, Any], fs: float, knobs: list[float]):
        h = 1.0 / fs
        self.h = h
        self.m = m
        fq = list(zip(key["f_hz"], key["q"], strict=True))
        self.free = [modal_step(f, q, h, key["mass_kg"]) for f, q in fq]
        qd = m["q_damped"]
        self.damped_steps = [modal_step(f, min(q, qd), h, key["mass_kg"]) for f, q in fq]
        self.n = len(key["f_hz"])
        self.phi_pick = [2.0 if i % 2 == 0 else -2.0 for i in range(self.n)]
        self.bp = bandpass(key["f_hz"][0], m["resonator_q"], fs)
        self.f1 = key["f_hz"][0]
        self.x = [0.0] * self.n
        self.v = [0.0] * self.n
        self.f_prev = 0.0
        self.bx1 = self.bx2 = self.by1 = self.by2 = 0.0
        self.press = 0.0
        self.down = False
        self.held_by_pedal = False
        self.pedal_down = False
        self.velocity = 0.0
        self.aftertouch = 0.0
        self.damped = True
        self.quiet = 0  # samples since the damper fell
        self.awake = False
        w = 2.0 * math.pi * m["wheel_hz"] * h
        self.cw, self.sw = math.cos(w), math.sin(w)
        self.pc, self.ps = 1.0, 0.0
        a = math.exp(-2.0 * math.pi * m["noise_hz"] * h)
        self.na = a
        self.norm = math.sqrt((1.0 + a) / (1.0 - a))
        self.nz = 0.0
        self.gauss = Gauss(key_seed(m["seed"], key["note"]))
        self.sleep_n = int(m["sleep_s"] * fs)
        self.set_knobs(knobs)

    def set_knobs(self, k: list[float]) -> None:
        m = self.m
        self.wheel = knob(m["wheel_range_m_s"], k[0])
        self.res_gain = m["resonator_max"] * k[1]
        self.touch = knob(m["touch_range"], k[2])
        # LIMIT: the check felt's gap (0: no felt)
        self.gap = 0.0
        if "felt_c_n_s_m" in m and k[3] > 0.0:
            lo, hi = m["limit_v_m_s"]
            v_lim = lo * (hi / lo) ** min(k[3], 1.0)
            self.gap = v_lim / (2.0 * math.pi * self.f1)

    # events
    def asleep(self) -> bool:
        return not self.awake

    def on(self, velocity: int) -> None:
        self.down = True
        self.velocity = velocity / 127.0
        self.awake = True
        self.damped = False
        self.quiet = 0

    def off(self) -> None:
        self.down = False

    def pedal(self, down: bool) -> None:
        self.pedal_down = down

    def pressure(self, value: int) -> None:
        self.aftertouch = value / 127.0

    # one sample
    def step(self) -> float:
        m = self.m
        held = self.down or (self.pedal_down and self.press > 0.0)
        if held:
            self.press = min(self.press + self.h / m["attack_s"], 1.0)
        else:
            self.press = max(self.press - self.h / m["release_s"], 0.0)
            if self.press == 0.0 and not self.damped:
                self.damped = True
                self.quiet = 0
        p = self.press
        shape = p * p * (3.0 - 2.0 * p)
        f_vel = (
            m["force_min_n"]
            + (m["force_max_n"] - m["force_min_n"]) * self.velocity ** m["force_exp"]
        )
        pc = self.pc * self.cw - self.ps * self.sw
        ps = self.ps * self.cw + self.pc * self.sw
        self.pc, self.ps = pc, ps
        fn = (
            self.touch
            * f_vel
            * (1.0 + m["pressure_gain"] * self.aftertouch)
            * shape
            * (1.0 + m["wobble"] * ps)
        )
        self.nz = self.na * self.nz + (1.0 - self.na) * self.gauss.next()
        rosin = 1.0 + m["rosin_noise"] * self.nz * self.norm
        steps = self.damped_steps if self.damped else self.free
        # LIMIT's felt at the free end (mode shapes +-2, the pickup's): its drag from the
        # step's start, held over the step (gf: the trapezoid's two ends)
        gf = 0.0
        if self.gap > 0.0:
            xf = 0.0
            vf = 0.0
            for i in range(self.n):
                xf += self.phi_pick[i] * self.x[i]
                vf += self.phi_pick[i] * self.v[i]
            e = min(max((abs(xf) - self.gap) / (m["felt_width"] * self.gap), 0.0), 1.0)
            gf = 2.0 * (-m["felt_c_n_s_m"] * (e * e * (3.0 - 2.0 * e)) * vf)
        # the free step and the contact's admittance (mode shape 2 at the bowed end)
        xn = [0.0] * self.n
        vn = [0.0] * self.n
        vh = 0.0
        y_adm = 0.0
        for i in range(self.n):
            s = steps[i]
            xn[i] = s[0] * self.x[i] + s[1] * self.v[i]
            vn[i] = s[2] * self.x[i] + s[3] * self.v[i]
            if gf != 0.0:
                xn[i] = xn[i] + s[4] * (self.phi_pick[i] * gf)
                vn[i] = vn[i] + s[5] * (self.phi_pick[i] * gf)
            vh += 2.0 * vn[i]
            y_adm += 2.0 * (2.0 * s[5])
        f_prev = self.f_prev
        a = vh + y_adm * f_prev - self.wheel
        if fn <= 0.0:
            f_new = 0.0
        else:
            ms, md = m["mu_s"] * rosin, m["mu_d"] * rosin
            f_stick = -a / y_adm
            if abs(f_stick) <= ms * fn:
                f_new = f_stick
            else:
                v0 = m["v0_m_s"]
                yf = y_adm * fn
                bb = abs(a) - yf * md
                c0 = v0 * (yf * (ms - md) - bb)
                bq = v0 - bb
                u = 0.5 * (-bq + math.sqrt(max(bq * bq - 4.0 * c0, 0.0)))
                mu = md + (ms - md) * v0 / (v0 + u)
                f_new = -math.copysign(fn * mu, a)
        fsum = 2.0 * (f_prev + f_new)  # the mode shape at the bowed end
        pick = 0.0
        for i in range(self.n):
            s = steps[i]
            self.x[i] = xn[i] + s[4] * fsum
            self.v[i] = vn[i] + s[5] * fsum
            pick += self.phi_pick[i] * self.v[i]
        self.f_prev = f_new
        b0, b1, b2, a1, a2 = self.bp
        y = b0 * pick + b1 * self.bx1 + b2 * self.bx2 - a1 * self.by1 - a2 * self.by2
        self.bx2, self.bx1 = self.bx1, pick
        self.by2, self.by1 = self.by1, y
        if self.damped:
            self.quiet += 1
            if self.quiet >= self.sleep_n:
                self.awake = False
        return m["pickup_v_per_m_s"] * (pick + self.res_gain * y)


def keyboard(m: dict[str, Any], fs: float, knobs: list[float]) -> dict[int, Voice]:
    return {k["note"]: Voice(m, k, fs, knobs) for k in m["keys"]}

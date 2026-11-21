"""I11, the Rosin Wheel Organ: tuned steel bars bowed by a rosined wheel the key presses on.

The phenomenon is stick-slip friction, which no instrument here has: every one so far is
struck, plucked, blown by a reed or electronic. A key lowers its bar onto a turning wheel
(the hurdy-gurdy's mechanism, Chladni's clavicylinder's idea of 1799 with bars); the press
force is the key's depth, so a note swells, scratches, or, pressed hard, breaks into the
raucous multi-mode regime a bow gives on a bar.

The bar: a free-free steel bar's bending modes (Euler-Bernoulli, beta_n L = 4.730, 7.853,
...), bowed at one end, its far end read by a magnetic pickup; generalized mass = the bar's
mass, so each mode's shape is 2 at the ends. One trapezoidal step per sample for the modes;
the contact force at the step's end is solved exactly from the friction curve (stick when
the static limit holds, else the slip velocity from a quadratic).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from .common import FS, envelope, smooth_noise

BETA = np.array([4.7300, 7.8532, 10.9956, 14.1372, 17.2788, 20.4204, 23.5619])
"""Free-free bar roots beta_n L (any beam text, e.g. Rao, Mechanical Vibrations, table 8.4)."""

STEEL_C_M_S = 5100.0  # sqrt(E / rho), steel: provisional, model knowledge (handbook value)
STEEL_RHO = 7850.0  # kg/m^3, provisional, model knowledge
BAR_T_M = 0.008  # thickness: provisional, design choice (an 8 mm x 25 mm bar)
BAR_W_M = 0.025
Q1 = 2500.0  # the fundamental's Q: provisional, model knowledge (steel bars, mounted on cord)
MU_S = 0.8  # rosin static friction: provisional, model knowledge (Smith & Woodhouse 2000 range)
MU_D = 0.35  # rosin dynamic friction at high slip: same source
V0_M_S = 0.06  # the friction curve's slip scale: same source
WHEEL_M_S = 0.25  # the wheel's surface speed: provisional, design choice
WHEEL_HZ = 2.7  # its turns per second (eccentricity wobble): design choice
Q_DAMPED = 40.0  # a felt damper on the bar after the key lifts: provisional, design choice


def bar_length_m(f1_hz: float) -> float:
    """The length giving f1 (f1 = beta1^2 / (2 pi L^2) * c * t / sqrt(12))."""
    return math.sqrt(BETA[0] ** 2 * STEEL_C_M_S * BAR_T_M / math.sqrt(12) / (2 * math.pi * f1_hz))


def bowed_bar(
    f1_hz: float,
    force_n: np.ndarray,
    g: np.random.Generator,
    wheel_m_s: float = WHEEL_M_S,
    rosin_noise: float = 0.04,
    damp_at: int | None = None,
) -> np.ndarray:
    """The pickup's reading (the far end's velocity, m/s) for a press force per sample.
    From sample damp_at on, a felt damper rests on the bar (every mode's Q at most
    Q_DAMPED)."""
    n = force_n.size
    length = bar_length_m(f1_hz)
    mass = STEEL_RHO * BAR_W_M * BAR_T_M * length
    f = f1_hz * (BETA / BETA[0]) ** 2
    keep = f < 0.4 * FS
    f = f[keep]
    w = 2 * math.pi * f
    q = Q1 * (f / f1_hz) ** -0.5  # higher modes lose faster (air, mounts)
    sets = [
        step_matrices(w, 1 / (2 * q), mass),
        step_matrices(w, 1 / (2 * np.minimum(q, Q_DAMPED)), mass),
    ]
    (p00, p01, p10, p11, r0, r1, y_adm) = sets[0]
    phi_bow = 2.0 * np.ones_like(f)
    phi_pick = 2.0 * (-1.0) ** np.arange(f.size)
    x = np.zeros_like(f)
    v = np.zeros_like(f)
    f_prev = 0.0
    wobble = 1 + 0.03 * np.sin(2 * math.pi * WHEEL_HZ * np.arange(n) / FS)
    rosin = 1 + rosin_noise * smooth_noise(g, n, 3000.0)
    fn_all = force_n * wobble
    out = np.empty(n)
    for k in range(n):
        if k == damp_at:
            (p00, p01, p10, p11, r0, r1, y_adm) = sets[1]
        xn = p00 * x + p01 * v
        vn = p10 * x + p11 * v
        fn = fn_all[k]
        vh = float(np.dot(phi_bow, vn))
        a = vh + y_adm * f_prev - wheel_m_s
        if fn <= 0.0:
            f_new = 0.0
        else:
            ms, md = MU_S * rosin[k], MU_D * rosin[k]
            f_stick = -a / y_adm  # the force holding the contact at the wheel's speed
            if abs(f_stick) <= ms * fn:
                f_new = f_stick
            else:
                yf = y_adm * fn
                bb = abs(a) - yf * md
                c0 = V0_M_S * (yf * (ms - md) - bb)
                bq = V0_M_S - bb
                u = 0.5 * (-bq + math.sqrt(max(bq * bq - 4 * c0, 0.0)))
                mu = md + (ms - md) * V0_M_S / (V0_M_S + u)
                f_new = -math.copysign(fn * mu, a)
        fs_sum = f_prev + f_new
        x = xn + r0 * fs_sum
        v = vn + r1 * fs_sum
        f_prev = f_new
        out[k] = float(np.dot(phi_pick, v))
    return out


def step_matrices(w: np.ndarray, zeta: np.ndarray, mass: float) -> tuple:
    """One trapezoidal step per mode, y+ = P y + r (F + F+), y = (x, v), the force at the
    bowed end (mode shape 2); and the contact admittance sum(phi r_v)."""
    h = 1 / FS
    det = 1 + h * zeta * w + (h * w / 2) ** 2  # det(I - h/2 A)
    i00, i01, i10, i11 = (1 + h * zeta * w) / det, (h / 2) / det, (-(h / 2) * w * w) / det, 1 / det
    a00, a01, a10, a11 = 1.0, h / 2, -(h / 2) * w * w, 1 - h * zeta * w  # I + h/2 A
    p00 = i00 * a00 + i01 * a10
    p01 = i00 * a01 + i01 * a11
    p10 = i10 * a00 + i11 * a10
    p11 = i10 * a01 + i11 * a11
    b = (h / 2) * 2.0 / mass
    r0, r1 = i01 * b, i11 * b
    return p00, p01, p10, p11, r0, r1, float(np.sum(2.0 * r1))


def resonator(x: np.ndarray, f_hz: float, q: float = 18.0, gain: float = 2.0) -> np.ndarray:
    """A tuned tube under the bar (a vibraphone's): the fundamental reinforced. A linear
    filter after the pickup, adequate for a sketch (provisional, design choice)."""
    b, a = signal.iirpeak(f_hz, q, fs=FS)
    return x + gain * signal.lfilter(b, a, x)


def press(n: int, dur_s: float, vel: float, attack_s: float = 0.08) -> np.ndarray:
    """The key's force: 0.4 N (pp) .. 4 N (ff), held, lifted in 40 ms."""
    return (0.4 + 3.6 * vel**1.5) * envelope(n, 0.0, dur_s, attack_s, 0.04)

"""A cylinder machine's drive: a spring motor, a flyball governor, a leather belt and the
mandrel with its cylinder (docs/PHONO_PLAN.md §3 / §5, "The motor"). Its output is the
speed of the groove under the cutter or the stylus, which `cylinder.py` uses to write the
groove along arc length (recording) and to read it (playing): wow and flutter come out of
this machine's mechanics, not from a modulation curve.

Rotation in the mobility sense (angular velocity, torque). Seven states:

    J_p w_p' = T_spring(t) - T_brake - r1(th_p) F - b_p w_p        motor side (spring
                                                                     barrel, gears and the
                                                                     governor, at the motor
                                                                     pulley)
    J_d w_d' = r2(th_d) F - T_load(t) - b_d w_d                     mandrel and cylinder
    u'       = r1(th_p) w_p - r2(th_d) w_d,  F = k u + c u'         the belt's stretch
    y''      = wg^2 ((G w_p / W0)^2 - y) - 2 zeta wg y'             the governor's collar

The governor's balls fly out with the square of its shaft's speed (G w_p) against their
springs; y is the collar's travel, 1 at the nominal speed W0. Past the speed screw's
setting y_set the collar presses the brake pad: T_brake = k_b (y - y_set) mu(phi) / mu0,
phi the brake disc's angle (G th_p), mu the felt's friction around the disc. The collar's
mass on its springs is a lag inside a speed loop: with too little damping the governor
hunts. The speed screw is set by the operator: y_set puts the machine at the target speed
under the load it has when the run starts (`simulate` solves the equilibrium).

Seeded imperfections (each a physical condition): the mainspring's torque irregularity
(coils sticking and releasing: an AR(1) process), the felt's friction around the disc (a
random Fourier series), both pulleys' eccentricity, and the cylinder's runout on the
mandrel (an eccentric seat, once per turn, and an oval warp, twice per turn).

A rigid circle turning at w about a point near its centre passes arc length under a fixed
stylus at w times the radius at the contact, to first order in the offset (cylinder.py's
geometry; derived in `surface_speed`'s docstring): the runout both lifts the surface
(which the floating weight absorbs) and modulates the groove's speed (which it can't).
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np

FELT_HARMONICS = 8


@dataclass
class Motion:
    fs_hz: float
    omega: np.ndarray  # the mandrel's angular velocity (rad/s)
    theta: np.ndarray  # its angle (rad)
    runout_m: np.ndarray  # the surface's radial offset under the stylus / cutter
    speed_m_s: np.ndarray  # arc length per second under it
    s_m: np.ndarray  # arc length passed

    @property
    def seconds(self) -> float:
        return len(self.omega) / self.fs_hz


def _rng(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(name.encode())])


def runout(theta: np.ndarray, m: dict, seed: int, name: str) -> np.ndarray:
    """The cylinder's radial offset at the contact for mandrel angle theta: an eccentric
    seat (once per turn) and an oval warp (twice per turn), phases seeded."""
    rng = _rng(seed, f"{name}/runout")
    p1, p2 = rng.uniform(0, 2 * np.pi, 2)
    return m["runout_eccentric_m"] * np.cos(theta + p1) + m["runout_oval_m"] * np.cos(
        2 * theta + p2
    )


def surface_speed(omega: np.ndarray, runout_m: np.ndarray, radius_m: float) -> np.ndarray:
    """Arc length per second under a fixed stylus. For a circle of radius R whose centre
    sits e from the axis (angle th), the stylus line x = 0 meets it where e cos th + R cos
    psi = 0; the material angle there is psi - th, whose rate is -w (1 + (e/R) sin th) to
    first order, so the arc rate is w (R + e sin th): w times the contact's radius."""
    return omega * (radius_m + runout_m)


def ideal(seconds: float, fs_hz: float, rpm: float, radius_m: float) -> Motion:
    n = int(round(seconds * fs_hz))
    w = 2 * np.pi * rpm / 60.0
    t = np.arange(n) / fs_hz
    v = np.full(n, w * radius_m)
    return Motion(fs_hz, np.full(n, w), w * t, np.zeros(n), v, v[0] * t)


def simulate(
    m: dict,
    rpm: float,
    radius_m: float,
    seconds: float,
    fs_hz: float,
    load_torque_n_m,
    seed: int,
    name: str,
) -> Motion:
    """The machine `m` (a config block) run for `seconds` at its target `rpm` under the
    mandrel's load torque (a constant, or an array sampled at m's `fs_hz`, the transport
    rate, held per step). The result is resampled to fs_hz (the audio simulation's)."""
    ft = m["fs_hz"]
    h = 1.0 / ft
    n = int(math.ceil(seconds * ft)) + 2
    load = _fit(np.atleast_1d(np.asarray(load_torque_n_m, dtype=float)), n)

    r1, r2 = m["motor_pulley_radius_m"], m["mandrel_pulley_radius_m"]
    e1, e2 = m["motor_pulley_eccentricity_m"], m["mandrel_pulley_eccentricity_m"]
    jp, jd = m["motor_inertia_kg_m2"], m["mandrel_inertia_kg_m2"]
    bp, bd = m["motor_friction_nm_s"], m["mandrel_friction_nm_s"]
    kb, cb = m["belt_stiffness_n_m"], m["belt_damping_ns_m"]
    g_ratio = m["governor_ratio"]
    wg = 2 * np.pi * m["governor_f_hz"]
    zeta = m["governor_zeta"]
    k_brake = m["brake_gain_n_m"]
    t_spring0 = m["spring_torque_n_m"]
    droop = m["spring_droop_per_s"]

    rng = _rng(seed, name)
    pe1, pe2 = rng.uniform(0, 2 * np.pi, 2)
    # The mainspring's irregularity: AR(1) at the transport rate, relative.
    a_s = math.exp(-h / m["spring_irregularity_s"])
    noise = rng.standard_normal(n) * m["spring_irregularity"] * math.sqrt(1 - a_s * a_s)
    noise[0] = rng.standard_normal() * m["spring_irregularity"]
    spring = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc = a_s * acc + noise[i]
        spring[i] = acc
    # The felt around the brake disc: mu(phi) / mu0 = 1 + sum a_k cos(k phi + p_k).
    ks = np.arange(1, FELT_HARMONICS + 1)
    amps = (
        rng.standard_normal(FELT_HARMONICS) * m["felt_irregularity"] / np.sqrt(FELT_HARMONICS / 2)
    )
    phs = rng.uniform(0, 2 * np.pi, FELT_HARMONICS)

    def felt(phi: float) -> float:
        return 1.0 + float(np.dot(amps, np.cos(ks * phi + phs)))

    # The operating point: the target speed, the belt carrying the start's load, the
    # collar at 1, the speed screw where the brake absorbs the spring's surplus.
    wd0 = 2 * np.pi * rpm / 60.0
    wp0 = wd0 * r2 / r1
    f0 = (load[0] + bd * wd0) / r2
    brake0 = t_spring0 * (1 + spring[0]) - r1 * f0 - bp * wp0
    if brake0 <= 0:
        raise ValueError(f"{name}: the mainspring can't drive this load at {rpm} rpm")
    y_set = 1.0 - brake0 / (k_brake * felt(0.0))
    w_gov0 = g_ratio * wp0

    def deriv(i: int, st: tuple, frac: float) -> tuple:
        thp, wp, thd, wd, u, y, yd = st
        r1t = r1 + e1 * math.cos(thp + pe1)
        r2t = r2 + e2 * math.cos(thd + pe2)
        ud = r1t * wp - r2t * wd
        force = kb * u + cb * ud
        t = (i + frac) * h
        ts = t_spring0 * (1.0 - droop * t) * (1.0 + spring[i])
        brake = k_brake * max(0.0, y - y_set) * felt(g_ratio * thp)
        wpd = (ts - brake - r1t * force - bp * wp) / jp
        wdd = (r2t * force - load[i] - bd * wd) / jd
        ydd = wg * wg * ((g_ratio * wp / w_gov0) ** 2 - y) - 2 * zeta * wg * yd
        return (wp, wpd, wd, wdd, ud, yd, ydd)

    # u0 so the belt carries f0 with the pulleys at their initial radii.
    st = (0.0, wp0, 0.0, wd0, f0 / kb, 1.0, 0.0)
    out_w = np.empty(n)
    out_th = np.empty(n)
    for i in range(n):
        out_w[i], out_th[i] = st[3], st[2]
        k1 = deriv(i, st, 0.0)
        s2 = tuple(a + 0.5 * h * b for a, b in zip(st, k1, strict=True))
        k2 = deriv(i, s2, 0.5)
        s3 = tuple(a + 0.5 * h * b for a, b in zip(st, k2, strict=True))
        k3 = deriv(i, s3, 0.5)
        s4 = tuple(a + h * b for a, b in zip(st, k3, strict=True))
        k4 = deriv(i, s4, 1.0)
        st = tuple(
            a + h / 6 * (b1 + 2 * b2 + 2 * b3 + b4)
            for a, b1, b2, b3, b4 in zip(st, k1, k2, k3, k4, strict=True)
        )

    tt = np.arange(n) * h
    na = int(round(seconds * fs_hz))
    ta = np.arange(na) / fs_hz
    omega = np.interp(ta, tt, out_w)
    theta = np.interp(ta, tt, out_th)
    ro = runout(theta, m, seed, name)
    v = surface_speed(omega, ro, radius_m)
    s = np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) / fs_hz)])
    return Motion(fs_hz, omega, theta, ro, v, s)


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.full(n - len(x), x[-1])])


def pitch_cents(rec: Motion, play: Motion, groove_length_m: float) -> np.ndarray:
    """The played pitch's deviation (cents) per playback sample: the speed the groove
    passes under the stylus over the speed it passed under the cutter at the same arc
    length, against the nominal ratio of the two machines' mean speeds."""
    s = play.s_m[play.s_m < min(groove_length_m, rec.s_m[-1])]
    v_rec_at = np.interp(s, rec.s_m, rec.speed_m_s)
    ratio = play.speed_m_s[: len(s)] / v_rec_at
    return 1200 * np.log2(ratio / np.median(ratio))

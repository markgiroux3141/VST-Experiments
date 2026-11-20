"""A record changer's rim drive (docs/PHONO_PLAN.md, "The 1960s record player"): a
shaded-pole induction motor, its stepped pulley, a rubber-tyred idler wheel and the
platter's rim. Like transport.py, its output is the platter's angle and angular velocity:
wow and flutter come out of the mechanics, not a modulation curve.

Rotation in the mobility sense. Nine states (motor, idler, platter angles and speeds, the
two contacts' tangential compressions, the platter's bearing drag as a first-order lag is
not needed: bearing friction is viscous):

    J_m w_m' = T_motor(w_m, t) - r_p(th_m) F_1 - b_m w_m          motor and its pulley
    J_i w_i' = r_i(th_i) (F_1 - F_2) - b_i w_i                     idler (its two contacts
                                                                    turn it the same way)
    J_p w_p' = R(th_p) F_2 - T_load(t) - b_p w_p                   platter and record
    u_1'     = r_p w_m - r_i w_i,   F_1 = k_1 u_1 + c_1 u_1'        pulley on the tyre
    u_2'     = r_i w_i - R w_p,     F_2 = k_2 u_2 + c_2 u_2'        tyre on the rim

The motor's torque falls linearly from stall to synchronous speed (a shaded-pole motor's
torque curve is close to a line over its working range: `stall_torque_n_m` at rest, zero
at 2 f_mains / poles revolutions per second), scaled by the mains voltage squared, with
the torque pulsation every induction motor on single-phase mains has at twice the mains
frequency (`torque_ripple`, relative). The idler's rubber takes a set where it stood
pressed against the pulley and rim while the changer was off: its radius has a dent once
per idler turn (`idler_flat_m`, a raised-cosine over `idler_flat_rad`), and an
eccentricity; the pulley and the rim are slightly eccentric too. A contact's tangential
spring is the tyre's shear stiffness at the nip.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np


@dataclass
class Motion:
    fs_hz: float
    omega: np.ndarray  # the platter's angular velocity (rad/s)
    theta: np.ndarray  # its angle (rad)
    motor_rpm: float  # the motor's mean speed under this load


def _rng(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(name.encode())])


def _radius(r0: float, th: float, ecc: float, phase: float, flat: float, flat_rad: float,
            flat_phase: float) -> float:  # fmt: skip
    r = r0 + ecc * math.cos(th + phase)
    if flat:
        d = (th + flat_phase + math.pi) % (2 * math.pi) - math.pi
        if abs(d) < flat_rad:
            r -= flat * 0.5 * (1 + math.cos(math.pi * d / flat_rad))
    return r


def synchronous(m: dict) -> float:
    """The motor's synchronous speed (rad/s): 2 f_mains / poles revolutions per second."""
    return 2 * math.pi * 2 * m["mains_hz"] / m["poles"]


def motor_slope(m: dict, mains_v: float) -> float:
    """The torque line's slope, stall torque over synchronous speed, at a mains voltage."""
    return m["stall_torque_n_m"] * (mains_v / m["rated_v"]) ** 2 / synchronous(m)


def motor_speed(m: dict, r_p: float, a: float, load_torque_n_m: float) -> float:
    """The motor's steady speed (rad/s) driving the platter through a pulley of radius r_p:
    a (w_s - w) = T_L r_p / R + w (b_m + b_p (r_p / R)^2 + b_i (r_p / r_i)^2)."""
    big_r, r_i = m["rim_radius_m"], m["idler_radius_m"]
    drag = (
        m["motor_friction_nm_s"]
        + m["platter_friction_nm_s"] * (r_p / big_r) ** 2
        + m["idler_friction_nm_s"] * (r_p / r_i) ** 2
    )
    return (a * synchronous(m) - load_torque_n_m * r_p / big_r) / (a + drag)


def pulley_radius(m: dict, rpm: float) -> float:
    """The pulley step the factory ground for `rpm`: the platter at speed at the rated
    voltage under the rated load (`rated_load_n_m`). Changers' pulley diameters aren't
    published; their speeds are, and the steps were sized to them."""
    w_target = 2 * math.pi * rpm / 60.0
    a = motor_slope(m, m["rated_v"])
    r_p = w_target * m["rim_radius_m"] / synchronous(m)
    for _ in range(50):
        wm = motor_speed(m, r_p, a, m["rated_load_n_m"])
        r_new = w_target * m["rim_radius_m"] / wm
        if abs(r_new - r_p) < 1e-15:
            break
        r_p = r_new
    return r_p


def simulate(
    m: dict, rpm: float, seconds: float, fs_hz: float, load_torque_n_m: float, seed: int,
    name: str = "changer",
) -> Motion:  # fmt: skip
    """The changer `m` (a config block) at its `rpm` step (the pulley step for that speed)
    for `seconds`, under the platter's load torque (stylus drag and bearing). Integrated
    by RK4 at m's `fs_hz`, resampled to fs_hz. The run starts at the operating point under
    that load (the platter has been turning)."""
    ft = m["fs_hz"]
    h = 1.0 / ft
    n = int(math.ceil(seconds * ft)) + 2
    r_i, big_r = m["idler_radius_m"], m["rim_radius_m"]
    jm, ji, jp = m["motor_inertia_kg_m2"], m["idler_inertia_kg_m2"], m["platter_inertia_kg_m2"]
    bm, bi, bp = m["motor_friction_nm_s"], m["idler_friction_nm_s"], m["platter_friction_nm_s"]
    k1 = k2 = m["contact_stiffness_n_m"]
    c1 = c2 = m["contact_damping_ns_m"]
    f_mains = m["mains_hz"]
    ripple = m["torque_ripple"]
    r_p = pulley_radius(m, rpm)
    a = motor_slope(m, m["mains_v"])
    w_sync = synchronous(m)

    g = _rng(seed, name)
    pe_p, pe_i, pe_r, pf = g.uniform(0, 2 * math.pi, 4)
    e_p, e_i, e_r = m["pulley_ecc_m"], m["idler_ecc_m"], m["rim_ecc_m"]
    flat, flat_rad = m["idler_flat_m"], m["idler_flat_rad"]
    ph_ripple = g.uniform(0, 2 * math.pi)

    wm0 = motor_speed(m, r_p, a, load_torque_n_m)
    if wm0 <= 0:
        raise ValueError(f"{name}: the motor stalls under this load")
    wi0 = wm0 * r_p / r_i
    wp0 = wm0 * r_p / big_r
    f2 = (load_torque_n_m + bp * wp0) / big_r
    f1 = f2 + bi * wi0 / r_i

    def deriv(i: int, st: tuple, frac: float) -> tuple:
        thm, wm, thi, wi, thp, wp, u1, u2 = st
        rp = r_p + e_p * math.cos(thm + pe_p)
        ri = _radius(r_i, thi, e_i, pe_i, flat, flat_rad, pf)
        rr = big_r + e_r * math.cos(thp + pe_r)
        u1d = rp * wm - ri * wi
        u2d = ri * wi - rr * wp
        fa = k1 * u1 + c1 * u1d
        fb = k2 * u2 + c2 * u2d
        t = (i + frac) * h
        tm = a * (w_sync - wm) * (1 + ripple * math.cos(2 * math.pi * 2 * f_mains * t + ph_ripple))
        wmd = (tm - rp * fa - bm * wm) / jm
        wid = (ri * (fa - fb) - bi * wi) / ji
        wpd = (rr * fb - load_torque_n_m - bp * wp) / jp
        return (wm, wmd, wi, wid, wp, wpd, u1d, u2d)

    st = (0.0, wm0, 0.0, wi0, 0.0, wp0, f1 / k1, f2 / k2)
    out_w = np.empty(n)
    out_th = np.empty(n)
    for i in range(n):
        out_w[i], out_th[i] = st[5], st[4]
        d1 = deriv(i, st, 0.0)
        s2 = tuple(x + 0.5 * h * d for x, d in zip(st, d1, strict=True))
        d2 = deriv(i, s2, 0.5)
        s3 = tuple(x + 0.5 * h * d for x, d in zip(st, d2, strict=True))
        d3 = deriv(i, s3, 0.5)
        s4 = tuple(x + h * d for x, d in zip(st, d3, strict=True))
        d4 = deriv(i, s4, 1.0)
        st = tuple(
            x + h / 6 * (a1 + 2 * a2 + 2 * a3 + a4)
            for x, a1, a2, a3, a4 in zip(st, d1, d2, d3, d4, strict=True)
        )
    tt = np.arange(n) * h
    na = int(round(seconds * fs_hz))
    ta = np.arange(na) / fs_hz
    return Motion(
        fs_hz, np.interp(ta, tt, out_w), np.interp(ta, tt, out_th), wm0 * 60 / (2 * math.pi)
    )

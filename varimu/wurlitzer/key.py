"""One key struck: the hammer's felt on the reed, the reed's motion, the plate's voltage
(docs/WURLITZER_PLAN.md, WZ1).

**The reed** is its modes below `f_max_hz` (`reed.py`: proportional damping, so real modes,
each a damped oscillator), stepped exactly for a force linear over the step (first-order
hold, the Rhodes' `key._foh`).

**The contact can't be a sample late** (as the Rhodes'): the reed's displacement under the
hammer at the end of a step is its free motion plus g F_{n+1}, the hammer's likewise, and
the felt's force `F = K d^p (1 + alpha d')` (d its compression, F >= 0; Pfeifle DAFx-17
eq. 1) is solved for F_{n+1} by a scalar Newton each step. The hammer is a free mass (gravity
on it) leaving the let-off at `hammer_speed_m_s`; the let-off's last 1/8 in of free flight
is left out (gravity takes ~1% of the speed). It can strike again if the reed comes back to
it; after `contact_window_s` it is caught (the check) and the reed rings free, evaluated in
closed form.

**The pickup** (`pickup.py`) integrates the map along the slot: the reed's height at
`n_slices` Gauss points between `slot_lo_m` and `slot_hi_m`, C(t) = sum w_s c(h0 + w(x_s, t)),
h0 the voicing.

**The plate's node** (WZ1's load; WZ2 puts the 200A's preamp there): the plate fed from
`polarizing_v` through `feed_ohm`, its constant capacitance `plate_f` (every reed at rest, the
preamp's input), the reed's capacitance changing. Exactly, with u the plate's voltage,
d/dt[(C_p + dC(t)) u] = (V0 - u) / R. The reed's dC is ~1e-3 of C_p and the signal ~1e-3 of
V0, so to that order the plate's AC voltage v is linear and time invariant,
`(C_p s + 1 / R) v = -V0 s dC`: `plate_voltage` (the bilinear transform at the stepped
rate); `plate_voltage_exact` steps the exact equation (the tests' check).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import linalg, signal

from varimu.rhodes.key import _foh
from varimu.wurlitzer import reed as rd
from varimu.wurlitzer import spec as sp

GRAVITY_M_S2 = 9.81


@dataclass(frozen=True)
class Strike:
    t_s: np.ndarray  # at the output rate
    plate_v: np.ndarray  # the plate's AC voltage
    tip_m: np.ndarray  # the reed tip's displacement from rest
    c_f: np.ndarray  # the reed's capacitance to the plate (at the output rate)
    contact_s: float
    max_force_n: float
    strikes: int
    off_map_s: float


class System:
    """The reed's modal state x = (q, q') with x' = A x + b F (F at the strike point), and the
    rows reading the strike point, the tip and the slot's slices."""

    def __init__(self, k: sp.Key, n_slices: int = 8):
        fe = rd.assemble(k.reed)
        md = rd.modes(fe, f_max_hz=k.f_max_hz)
        self.fe, self.md = fe, md
        n = md.omega.size
        phi = md.phi
        strike = fe.point(k.hammer.strike_x_m) @ phi
        tip = fe.point(k.reed.length_m) @ phi
        g, w = np.polynomial.legendre.leggauss(n_slices)
        xs = 0.5 * (k.slot_hi_m - k.slot_lo_m) * (g + 1) + k.slot_lo_m
        self.slice_x = xs
        self.slice_w = 0.5 * (k.slot_hi_m - k.slot_lo_m) * w
        self.slices = np.array([fe.point(x) @ phi for x in xs])  # (n_slices, n)
        a = np.zeros((2 * n, 2 * n))
        a[:n, n:] = np.eye(n)
        a[n:, :n] = -np.diag(md.omega**2)
        a[n:, n:] = -np.diag(2 * md.sigma)
        b = np.concatenate([np.zeros(n), strike])
        z = np.zeros(n)
        self.a, self.b, self.n = a, b, n
        self.c_strike = np.concatenate([strike, z])
        self.c_strike_v = np.concatenate([z, strike])
        self.c_tip = np.concatenate([tip, z])
        self.c_slices = np.hstack([self.slices, np.zeros_like(self.slices)])

    def free(
        self, x0: np.ndarray, t: np.ndarray, chunk: int = 8192
    ) -> tuple[np.ndarray, np.ndarray]:
        """The tip's and the slices' displacements from x0 at the times t (closed form)."""
        lam, v = linalg.eig(self.a)
        z0 = np.linalg.solve(v, x0.astype(complex))
        ct = self.c_tip @ v
        cs = self.c_slices @ v
        tip = np.zeros(t.size)
        sl = np.zeros((self.slices.shape[0], t.size))
        for s in range(0, t.size, chunk):
            ez = np.exp(np.outer(lam, t[s : s + chunk])) * z0[:, None]
            tip[s : s + chunk] = np.real(ct @ ez)
            sl[:, s : s + chunk] = np.real(cs @ ez)
        return tip, sl


def contact(
    sysm: System, hm: sp.Hammer, x: np.ndarray, speed: float, h: float, every: int, n_out: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[int, float, int]]:
    """The hammer thrown at the reed from state x: n_out * every steps of h with the contact
    solved inside each. Returns the end state, the tip and the slices every `every` steps
    (n_out of each, the start excluded) and (the first contact's steps, the largest force,
    the contacts)."""
    phi, g0, g1 = _foh(sysm.a, sysm.b, h)
    gd = float(sysm.c_strike @ g1)
    gv = float(sysm.c_strike_v @ g1)
    m = hm.mass_kg
    z, v = float(sysm.c_strike @ x), speed
    f_prev = 0.0
    tip = np.zeros(n_out)
    sl = np.zeros((sysm.slices.shape[0], n_out))
    contact_steps, strikes, in_contact, first_done, f_max = 0, 0, False, False, 0.0
    for i in range(n_out * every):
        xf = phi @ x + g0 * f_prev
        y_free = sysm.c_strike @ xf
        yv_free = sysm.c_strike_v @ xf
        z_free = z + h * v - h * h * (2 * f_prev / m) / 6 - 0.5 * GRAVITY_M_S2 * h * h
        v_free = v - h * f_prev / (2 * m) - GRAVITY_M_S2 * h
        d_free = z_free - y_free  # the felt's compression (the hammer below the reed)
        dd_free = v_free - yv_free
        cd = gd + h * h / (6 * m)
        cv = gv + h / (2 * m)
        f = 0.0
        if d_free > 0:
            f = f_prev if f_prev > 0 else 0.0
            for _ in range(60):
                d = d_free - cd * f
                dd = dd_free - cv * f
                if d <= 0:
                    r, dr = f, 1.0
                else:
                    hc = 1 + hm.hysteresis_s_m * dd
                    r = f - hm.stiffness * d**hm.exponent * max(hc, 0.0)
                    dr = 1.0
                    if hc > 0:
                        dr += hm.stiffness * (
                            hm.exponent * d ** (hm.exponent - 1) * cd * hc
                            + d**hm.exponent * hm.hysteresis_s_m * cv
                        )
                step = r / dr
                f = max(f - step, 0.0)
                if abs(step) < 1e-13 * max(1.0, abs(f)):
                    break
        x = xf + g1 * f
        z = z_free - h * h * f / (6 * m)
        v = v_free - h * f / (2 * m)
        if f > 0:
            if not in_contact:
                strikes += 1
                in_contact = True
            if not first_done:
                contact_steps += 1
            f_max = max(f_max, f)
        elif in_contact:
            in_contact = False
            first_done = True
        f_prev = f
        if (i + 1) % every == 0:
            j = (i + 1) // every - 1
            tip[j] = sysm.c_tip @ x
            sl[:, j] = sysm.c_slices @ x
    return x, tip, sl, (contact_steps, f_max, strikes)


def plate_voltage(dc_f: np.ndarray, k: sp.Key, fs_hz: float) -> np.ndarray:
    """The plate's AC voltage for the reed's capacitance change dc (linear, time invariant:
    the module's docstring)."""
    r, cp, v0 = k.feed_ohm, k.plate_f, k.polarizing_v
    b, a = signal.bilinear([-v0 * r, 0.0], [r * cp, 1.0], fs_hz)
    return signal.lfilter(b, a, dc_f - dc_f[0])


def plate_voltage_exact(dc_f: np.ndarray, k: sp.Key, fs_hz: float) -> np.ndarray:
    """d/dt[(C_p + dc) u] = (V0 - u) / R stepped by the trapezoidal rule in the charge."""
    r, cp, v0 = k.feed_ohm, k.plate_f, k.polarizing_v
    h = 1.0 / fs_hz
    c = cp + (dc_f - dc_f[0])
    q = c[0] * v0
    u = np.empty(c.size)
    u[0] = v0
    for i in range(1, c.size):
        # q1 = q0 + h/2 [(V0 - q0/c0)/R + (V0 - q1/c1)/R]
        rhs = q + 0.5 * h * ((v0 - q / c[i - 1]) / r + v0 / r)
        q = rhs / (1 + 0.5 * h / (r * c[i]))
        u[i] = q / c[i]
    return u - v0


def strike(
    k: sp.Key,
    hammer_speed_m_s: float,
    duration_s: float = 2.0,
    fs_hz: float = 96000.0,
    oversample: int = 4,
    step_oversample: int | None = None,
    contact_window_s: float = 0.03,
    voicing_m: float | None = None,
    n_slices: int = 8,
) -> Strike:
    """Key k struck at `hammer_speed_m_s`: the plate's voltage, computed at `oversample` x
    fs_hz and decimated; the contact stepped at `step_oversample` x fs_hz."""
    sysm = System(k, n_slices)
    step_oversample = step_oversample or oversample
    if step_oversample % oversample:
        raise ValueError("step_oversample must be a multiple of oversample")
    every = step_oversample // oversample
    h = 1.0 / (fs_hz * step_oversample)
    h_out = 1.0 / (fs_hz * oversample)
    n_out = int(round(contact_window_s / h_out))
    x = np.zeros(2 * sysm.n)
    x, tip_c, sl_c, stats = contact(sysm, k.hammer, x, hammer_speed_m_s, h, every, n_out)
    n_total = int(round(duration_s / h_out))
    t_rest = h_out * np.arange(1, n_total - n_out + 1)
    tip_r, sl_r = sysm.free(x, t_rest)
    tip = np.concatenate([[0.0], tip_c, tip_r])
    sl = np.hstack([np.zeros((sl_c.shape[0], 1)), sl_c, sl_r])
    fmap = sp.field(k)
    h0 = k.voicing_m if voicing_m is None else voicing_m
    zz = h0 + sl
    lo, hi = fmap.z_range_m
    off = np.any((zz < lo) | (zz > hi), axis=0)
    c = sysm.slice_w @ fmap(zz)
    v = plate_voltage(c, k, fs_hz * oversample)
    if oversample > 1:
        v = signal.resample_poly(v, 1, oversample)
        c_out = c[::oversample]
        tip = tip[::oversample]
    else:
        c_out = c
    t = np.arange(v.size) / fs_hz
    contact_steps, f_max, strikes = stats
    return Strike(t, v, tip, c_out, contact_steps * h, f_max, strikes, float(np.sum(off)) * h_out)


def electrostatic_shift_cents(k: sp.Key, voicing_m: float | None = None) -> float:
    """The plate's pull on the reed at rest as a spring, its fundamental's shift: the force
    is 1/2 V0^2 dC/dz, so a stiffness -1/2 V0^2 c''(h0) per metre of slot."""
    sysm = System(k)
    fmap = sp.field(k)
    h0 = k.voicing_m if voicing_m is None else voicing_m
    kz = -0.5 * k.polarizing_v**2 * fmap(np.array([h0]), dz=2)[0]
    d_w2 = float(np.sum(sysm.slice_w * kz * sysm.slices[:, 0] ** 2))
    w2 = float(sysm.md.omega[0] ** 2)
    return float(1200 * np.log2(np.sqrt(1 + d_w2 / w2)))

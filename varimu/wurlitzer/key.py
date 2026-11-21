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
from scipy import linalg, optimize, signal

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


DB_PER_NEPER = 20 / np.log(10)


class System:
    """The reed's modal state x = (q, q') with x' = A x + b F (F at the strike point), and the
    rows reading the strike point, the tip and the slot's slices.

    `damped`: the damper's felt on the reed (WZ3), a dashpot c at `k.damper_x_m` in the
    modal damping block, `C = diag(2 sigma) + c phi_d phi_d'` (mass normalized modes, the same
    coordinates as the free system's, so the state carries across a switch); c is solved so
    the fundamental's mode decays at `k.damper_decay_db_s` (`damper_ns_m`). A key without a
    damper (`damper_decay_db_s` None) is its free system."""

    def __init__(self, k: sp.Key, n_slices: int = 8, damped: bool = False):
        fe = rd.assemble(k.reed)
        md = rd.modes(fe, f_max_hz=k.f_max_hz)
        self.fe, self.md = fe, md
        n = md.omega.size
        phi = md.phi
        strike = fe.point(k.hammer.strike_x_m) @ phi
        tip = fe.point(k.reed.length_m) @ phi
        self.slice_x, self.slice_w, self.slices = self.slot_rows(
            k.slot_lo_m, k.slot_hi_m, n_slices
        )  # slices: (n_slices, n)
        self.phi_d = fe.point(k.damper_x_m) @ phi
        self.damper_ns_m = 0.0
        if damped and k.damper_decay_db_s is not None:
            self.damper_ns_m = damper_ns_m(md, self.phi_d, k.damper_decay_db_s)
        a = _a(md, self.phi_d, self.damper_ns_m)
        b = np.concatenate([np.zeros(n), strike])
        z = np.zeros(n)
        self.a, self.b, self.n = a, b, n
        self.c_strike = np.concatenate([strike, z])
        self.c_strike_v = np.concatenate([z, strike])
        self.c_tip = np.concatenate([tip, z])
        self.c_slices = np.hstack([self.slices, np.zeros_like(self.slices)])

    def slot_rows(
        self, lo_m: float, hi_m: float, n_slices: int = 8
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """A slot from lo_m to hi_m (from the root): its Gauss points, their weights and the
        rows reading the reed's height there from the modal displacements."""
        g, w = np.polynomial.legendre.leggauss(n_slices)
        xs = 0.5 * (hi_m - lo_m) * (g + 1) + lo_m
        rows = np.array([self.fe.point(x) @ self.md.phi for x in xs])
        return xs, 0.5 * (hi_m - lo_m) * w, rows

    def strike_bound_m(self, x: np.ndarray) -> float:
        """An upper bound on the strike point's swing from state x (each mode's amplitude
        sqrt(q^2 + (q' / omega)^2), light damping)."""
        q, qd = x[: self.n], x[self.n :]
        amp = np.sqrt(q * q + (qd / self.md.omega) ** 2)
        return float(np.sum(np.abs(self.c_strike[: self.n]) * amp))

    def free(
        self, x0: np.ndarray, t: np.ndarray, chunk: int = 8192, rows: np.ndarray | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """The tip's displacement and `rows` @ x (default: the slices' displacements) from x0
        at the times t (closed form)."""
        rows = self.c_slices if rows is None else rows
        lam, v = linalg.eig(self.a)
        z0 = np.linalg.solve(v, x0.astype(complex))
        ct = self.c_tip @ v
        cs = rows @ v
        tip = np.zeros(t.size)
        sl = np.zeros((rows.shape[0], t.size))
        for s in range(0, t.size, chunk):
            ez = np.exp(np.outer(lam, t[s : s + chunk])) * z0[:, None]
            tip[s : s + chunk] = np.real(ct @ ez)
            sl[:, s : s + chunk] = np.real(cs @ ez)
        return tip, sl


def _a(md: rd.Modes, phi_d: np.ndarray, c_ns_m: float) -> np.ndarray:
    n = md.omega.size
    a = np.zeros((2 * n, 2 * n))
    a[:n, n:] = np.eye(n)
    a[n:, :n] = -np.diag(md.omega**2)
    a[n:, n:] = -np.diag(2 * md.sigma) - c_ns_m * np.outer(phi_d, phi_d)
    return a


def _fundamental_decay_db_s(md: rd.Modes, phi_d: np.ndarray, c_ns_m: float) -> float:
    lam = linalg.eigvals(_a(md, phi_d, c_ns_m))
    up = lam[lam.imag > 0]
    i = int(np.argmin(np.abs(up.imag - md.omega[0])))
    return float(DB_PER_NEPER * up[i].real)


def damper_ns_m(md: rd.Modes, phi_d: np.ndarray, decay_db_s: float) -> float:
    """The dashpot (N s / m) at the damper's point giving the fundamental `decay_db_s`
    (negative). A point dashpot's damping of a mode peaks and falls again as it pins the
    point, so the root is taken below the peak; a target past the peak gets the peak."""
    free = _fundamental_decay_db_s(md, phi_d, 0.0)
    if decay_db_s >= free:
        return 0.0
    # the light-damping estimate, then a bracket below the peak
    c1 = 2 * (free - decay_db_s) / DB_PER_NEPER / phi_d[0] ** 2
    cs = c1 * np.geomspace(1e-3, 1e3, 61)
    d = np.array([_fundamental_decay_db_s(md, phi_d, c) for c in cs])
    i_peak = int(np.argmin(d))
    if d[i_peak] > decay_db_s:
        return float(cs[i_peak])
    j = int(np.flatnonzero(d[: i_peak + 1] <= decay_db_s)[0])
    lo = cs[j - 1] if j > 0 else 0.0
    return float(
        optimize.brentq(
            lambda c: _fundamental_decay_db_s(md, phi_d, c) - decay_db_s, lo, cs[j], xtol=1e-12
        )
    )


def contact(
    sysm: System,
    hm: sp.Hammer,
    x: np.ndarray,
    speed: float,
    h: float,
    every: int,
    n_out: int,
    rows: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[int, float, int]]:
    """The hammer thrown at the reed from state x: n_out * every steps of h with the contact
    solved inside each. Returns the end state, the tip and `rows` @ x (default: the slices)
    every `every` steps (n_out of each, the start excluded) and (the first contact's steps,
    the largest force, the contacts).

    The hammer starts at the reed's strike point at rest; a reed already ringing (a key
    struck again) is met where it is: the hammer starts at the lowest the strike point can
    swing (`strike_bound_m`), so it flies up to the moving reed."""
    phi, g0, g1 = _foh(sysm.a, sysm.b, h)
    gd = float(sysm.c_strike @ g1)
    gv = float(sysm.c_strike_v @ g1)
    m = hm.mass_kg
    z, v = min(float(sysm.c_strike @ x), -sysm.strike_bound_m(x)), speed
    rows = sysm.c_slices if rows is None else rows
    f_prev = 0.0
    tip = np.zeros(n_out)
    sl = np.zeros((rows.shape[0], n_out))
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
            sl[:, j] = rows @ x
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


@dataclass(frozen=True)
class Motion:
    """A strike from rest: the reed's tip and the slot's slices from t = 0 at fs x
    oversample (`h_out` apart), the contact's statistics."""

    slice_w: np.ndarray
    tip_m: np.ndarray
    slices_m: np.ndarray  # (n_slices, samples)
    h_out: float
    contact_s: float
    max_force_n: float
    strikes: int


def motion(
    k: sp.Key,
    hammer_speed_m_s: float,
    duration_s: float = 2.0,
    fs_hz: float = 96000.0,
    oversample: int = 4,
    step_oversample: int | None = None,
    contact_window_s: float = 0.03,
    n_slices: int = 8,
    modal: bool = False,
) -> Motion:
    """Key k struck from rest at `hammer_speed_m_s`, the contact stepped at
    `step_oversample` x fs_hz; the motion at `oversample` x fs_hz (independent of the
    voicing, which only enters the pickup's map). `modal`: `slices_m` holds the modal
    displacements q instead (n_modes rows: any slot's heights are `System.slot_rows` @ q)."""
    sysm = System(k, n_slices)
    step_oversample = step_oversample or oversample
    if step_oversample % oversample:
        raise ValueError("step_oversample must be a multiple of oversample")
    every = step_oversample // oversample
    h = 1.0 / (fs_hz * step_oversample)
    h_out = 1.0 / (fs_hz * oversample)
    n_out = int(round(contact_window_s / h_out))
    rows = np.eye(sysm.n, 2 * sysm.n) if modal else None
    x = np.zeros(2 * sysm.n)
    x, tip_c, sl_c, stats = contact(sysm, k.hammer, x, hammer_speed_m_s, h, every, n_out, rows)
    n_total = int(round(duration_s / h_out))
    t_rest = h_out * np.arange(1, n_total - n_out + 1)
    tip_r, sl_r = sysm.free(x, t_rest, rows=rows)
    tip = np.concatenate([[0.0], tip_c, tip_r])
    sl = np.hstack([np.zeros((sl_c.shape[0], 1)), sl_c, sl_r])
    contact_steps, f_max, strikes = stats
    return Motion(sysm.slice_w, tip, sl, h_out, contact_steps * h, f_max, strikes)


def capacitance(k: sp.Key, mo: Motion, voicing_m: float | None = None) -> tuple[np.ndarray, float]:
    """The reed's capacitance to the plate over the motion (F, at its rate) and the time
    spent off the map's range (s)."""
    fmap = sp.field(k)
    h0 = k.voicing_m if voicing_m is None else voicing_m
    zz = h0 + mo.slices_m
    lo, hi = fmap.z_range_m
    off = np.any((zz < lo) | (zz > hi), axis=0)
    return mo.slice_w @ fmap(zz), float(np.sum(off)) * mo.h_out


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
    """Key k struck at `hammer_speed_m_s`: the plate's voltage (WZ1's load), computed at
    `oversample` x fs_hz and decimated; the contact stepped at `step_oversample` x fs_hz."""
    mo = motion(
        k,
        hammer_speed_m_s,
        duration_s,
        fs_hz,
        oversample,
        step_oversample,
        contact_window_s,
        n_slices,
    )
    c, off_s = capacitance(k, mo, voicing_m)
    v = plate_voltage(c, k, fs_hz * oversample)
    tip = mo.tip_m
    if oversample > 1:
        v = signal.resample_poly(v, 1, oversample)
        c_out = c[::oversample]
        tip = tip[::oversample]
    else:
        c_out = c
    t = np.arange(v.size) / fs_hz
    return Strike(t, v, tip, c_out, mo.contact_s, mo.max_force_n, mo.strikes, off_s)


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

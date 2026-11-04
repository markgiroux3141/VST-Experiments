"""One key struck: the hammer's contact on the tone bar assembly, the tine's motion, the
pickup's EMF (docs/RHODES_PLAN.md, RH1).

Two tiers from the same finite-element assembly (`beam.py`):

- **live** (`tier="modes"`): the damped system's complex modes below `f_max_hz` (one
  complex pole each, a conjugate pair per resonance: the damping's off-diagonal terms
  kept, they couple the tine's and the bar's modes near the note, where the grommets'
  dashpots are strong), stepped at the output rate times `oversample`;
- **reference** (`tier="full"`): the whole damped system in physical coordinates (every
  degree of freedom), stepped at a higher rate.

Both step exactly for a force that is linear over the step (first-order hold: the
augmented matrix exponential), so the only differences are the reduction and the rate.

**The contact can't be a sample late** (RHODES_PLAN.md, "Action and hammer"): the tine's
displacement under the hammer at the end of a step is its free motion plus g F_{n+1}, g the
system's instantaneous response at the strike point (folded into the port), and the
hammer's likewise; the Hunt-Crossley force `F = K d^p (1 + alpha d')` (d the tip's
compression, d' its rate, F >= 0) is solved for F_{n+1} by a scalar Newton each step. The
hammer is a free mass (gravity on it) from `hammer_speed_m_s` upwards at the tine; it can
strike again if the tine comes back to it. After `contact_window_s` the hammer is taken
away (caught by the action) and the motion continues free, evaluated in closed form.

**The pickup** reads the tine's tip: its height (above the pole's axis by the voicing)
and its pull-back from the gap as it swings on an arc (`dg = 1/2 int_0^L w'^2 dx`, the
inextensible tine's shortening: quadratic in the modes). The EMF is
`-(dPhi/dy y' + dPhi/ddg dg')` from the flux map's spline, computed at the stepped rate and
decimated to the output rate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import linalg, signal

from varimu.rhodes import beam as bm
from varimu.rhodes import pickup as pk
from varimu.rhodes.spec import Key

GRAVITY_M_S2 = 9.81


@dataclass(frozen=True)
class Strike:
    t_s: np.ndarray  # at the output rate
    emf_v: np.ndarray
    tip_m: np.ndarray  # the tip's displacement from rest
    contact_s: float  # the first contact's duration
    max_force_n: float
    strikes: int  # contacts in the window (a re-strike: > 1)
    off_map_s: float  # time the tine's tip spent beyond the flux map (held at its edge)


def _foh(a: np.ndarray, b: np.ndarray, h: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact step of x' = A x + b u for u linear over the step: x1 = Phi x0 + g0 u0 + g1 u1."""
    n = a.shape[0]
    big = np.zeros((n + 2, n + 2), dtype=np.result_type(a, b))
    big[:n, :n] = a * h
    big[:n, n] = b * h
    big[n, n + 1] = 1.0
    e = linalg.expm(big)
    phi, ga, gb = e[:n, :n], e[:n, n], e[:n, n + 1]
    return phi, ga - gb, gb


class _System:
    """The state-space model x' = A x + b F, its outputs (rows giving the strike point's
    displacement and velocity, the tip's) and the maps from the state to the tine's slopes
    at its quadrature points and their rates (for the arc).

    `full`: x = (displacements, velocities) of every degree of freedom, A real.
    `modes`: x = the complex modal coordinates of the damped system (the state matrix's
    eigenvectors: non-proportional damping kept, it couples the tine's and the bar's modes
    near the note), those with |lambda| <= 2 pi f_max; A diagonal. Outputs are real parts.
    """

    def __init__(self, k: Key, tier: str, asm: bm.Assembly | None = None):
        fe = bm.assemble(asm or k.assembly, k.element_m)
        strike = fe.tine_point(k.hammer.strike_x_m)
        tip = fe.tip
        # the arc: 1/2 int w'^2 dx over the tine = 1/2 sum_g w_g s_g^2, s_g the slope at
        # 3 Gauss points per element (exact: the slope is quadratic in an element)
        xs = np.concatenate([[0.0], fe.tine_x_m])
        gp, gw = np.polynomial.legendre.leggauss(3)
        slope_rows, weights = [], []
        for a, b in zip(xs[:-1], xs[1:], strict=True):
            for xi, wt in zip(gp, gw, strict=True):
                slope_rows.append(fe.tine_point(0.5 * (b - a) * (xi + 1) + a, slope=True))
                weights.append(0.5 * (b - a) * wt)
        slope = np.array(slope_rows)
        n = fe.n
        minv = np.linalg.inv(fe.m)
        a_full = np.zeros((2 * n, 2 * n))
        a_full[:n, n:] = np.eye(n)
        a_full[n:, :n] = -minv @ fe.k
        a_full[n:, n:] = -minv @ fe.c
        b_full = np.concatenate([np.zeros(n), minv @ strike])
        zeros = np.zeros(n)
        rows = {
            "strike": np.concatenate([strike, zeros]),
            "strike_v": np.concatenate([zeros, strike]),
            "tip": np.concatenate([tip, zeros]),
            "tip_v": np.concatenate([zeros, tip]),
        }
        q_map = np.hstack([slope, np.zeros_like(slope)])  # state -> slopes
        qd_map = np.hstack([np.zeros_like(slope), slope])  # state -> their rates
        self.n_state = 2 * n
        if tier == "full":
            self.a, self.b = a_full, b_full
            self.to_phys = self.from_phys = None
        elif tier == "modes":
            lam, v = linalg.eig(a_full)
            keep = np.abs(lam) <= 2 * np.pi * k.f_max_hz
            w = np.linalg.inv(v)[keep]
            v = v[:, keep]
            self.a = np.diag(lam[keep])
            self.lam = lam[keep]
            self.b = w @ b_full
            self.to_phys, self.from_phys = v, w  # modal state <-> (displacements, velocities)
            rows = {key: row @ v for key, row in rows.items()}
            q_map, qd_map = q_map @ v, qd_map @ v
            self.n_modes = int(np.sum(keep & (lam.imag > 0)))
        else:
            raise ValueError(f"tier {tier!r}: 'modes' or 'full'")
        self.c_strike, self.c_strike_v = rows["strike"], rows["strike_v"]
        self.c_tip, self.c_tip_v = rows["tip"], rows["tip_v"]
        self.q_map, self.qd_map, self.w = q_map, qd_map, np.array(weights)

    def free(self, x0: np.ndarray, t: np.ndarray, chunk: int = 4096) -> tuple[np.ndarray, ...]:
        """The free motion from x0 at the times t: the tip's displacement and velocity,
        the arc's pull-back and its rate. By the state matrix's eigenvectors; the
        eigenpairs that die within one sample of t or ring above its Nyquist frequency
        are left out (the full system's stiff element modes)."""
        lam, v = linalg.eig(self.a)
        z0 = np.linalg.solve(v, x0.astype(complex))
        dt = t[1] - t[0]
        keep = (lam.real * dt > -30) & (np.abs(lam.imag) * dt < np.pi)
        lam, v, z0 = lam[keep], v[:, keep], z0[keep]
        ct, ctv = self.c_tip @ v, self.c_tip_v @ v
        qm, qdm = self.q_map @ v, self.qd_map @ v
        out = [np.zeros(t.size) for _ in range(4)]
        for s in range(0, t.size, chunk):
            tt = t[s : s + chunk]
            ez = np.exp(np.outer(lam, tt)) * z0[:, None]
            out[0][s : s + chunk] = np.real(ct @ ez)
            out[1][s : s + chunk] = np.real(ctv @ ez)
            q = np.real(qm @ ez)
            qd = np.real(qdm @ ez)
            out[2][s : s + chunk] = 0.5 * self.w @ (q * q)
            out[3][s : s + chunk] = self.w @ (q * qd)
        return tuple(out)


def stepper(sysm: _System, h: float, diagonal: bool):
    """The exact first-order-hold step of the system at h: (advance, g0, g1)."""
    phi, g0, g1 = _foh(sysm.a, sysm.b, h)
    if diagonal:
        phi_d = np.diagonal(phi).copy()

        def advance(x: np.ndarray) -> np.ndarray:
            return phi_d * x
    else:

        def advance(x: np.ndarray) -> np.ndarray:
            return phi @ x

    return advance, g0, g1


def contact(
    sysm: _System,
    k: Key,
    x: np.ndarray,
    hammer_speed_m_s: float,
    h: float,
    every: int,
    n_out: int,
    advance,
    g0: np.ndarray,
    g1: np.ndarray,
) -> tuple[np.ndarray, tuple[np.ndarray, ...], tuple[int, float, int]]:
    """The hammer thrown at the tine from the state x (the tine may be moving: a key
    struck again): `n_out * every` steps of h with the contact solved inside each. The
    hammer starts at the strike point, moving up at `hammer_speed_m_s`. Returns the end
    state, the tip's (displacement, velocity, arc, arc rate) every `every` steps (n_out of
    each, the start excluded) and (the first contact's steps, the largest force, the
    contacts)."""
    hm = k.hammer
    # the strike point's instantaneous responses to F_{n+1}
    gd = float(np.real(sysm.c_strike @ g1))
    gv = float(np.real(sysm.c_strike_v @ g1))
    m = hm.mass_kg
    y0 = float(np.real(sysm.c_strike @ x))
    z, v = y0, hammer_speed_m_s  # the hammer at the strike point
    f_prev = 0.0
    n_win = n_out * every
    tip = np.zeros(n_out + 1)
    tip_v = np.zeros(n_out + 1)
    arc = np.zeros(n_out + 1)
    arc_v = np.zeros(n_out + 1)
    contact_steps, strikes, in_contact, first_done = 0, 0, False, False
    f_max = 0.0
    for i in range(n_win):
        xf = advance(x) + g0 * f_prev  # free part (F_{n+1} = 0)
        y_free = np.real(sysm.c_strike @ xf)
        yv_free = np.real(sysm.c_strike_v @ xf)
        # the hammer with F linear over the step (gravity constant)
        z_free = z + h * v - h * h * (2 * f_prev / m) / 6 - 0.5 * GRAVITY_M_S2 * h * h
        v_free = v - h * f_prev / (2 * m) - GRAVITY_M_S2 * h
        d_free = z_free - y_free
        dd_free = v_free - yv_free
        cd = gd + h * h / (6 * m)  # d = d_free - cd F
        cv = gv + h / (2 * m)  # d' = dd_free - cv F
        f = 0.0
        if d_free > 0:
            f = f_prev if f_prev > 0 else 0.0
            for _ in range(50):
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
                if abs(step) < 1e-12 * max(1.0, abs(f)):
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
            j = (i + 1) // every
            q = np.real(sysm.q_map @ x)
            qd = np.real(sysm.qd_map @ x)
            tip[j] = np.real(sysm.c_tip @ x)
            tip_v[j] = np.real(sysm.c_tip_v @ x)
            arc[j] = 0.5 * sysm.w @ (q * q)
            arc_v[j] = sysm.w @ (q * qd)
    return x, (tip[1:], tip_v[1:], arc[1:], arc_v[1:]), (contact_steps, f_max, strikes)


def strike(
    k: Key,
    hammer_speed_m_s: float,
    duration_s: float = 2.0,
    fs_hz: float = 96000.0,
    tier: str = "modes",
    oversample: int = 4,
    step_oversample: int | None = None,
    contact_window_s: float = 0.03,
    voicing_m: float | None = None,
    flux: pk.FluxMap | None = None,
) -> Strike:
    """Key k struck at `hammer_speed_m_s`. The EMF is computed at `oversample` x fs_hz and
    decimated; the contact is stepped at `step_oversample` x fs_hz (a multiple of
    `oversample`; by default the same)."""
    sysm = _System(k, tier)
    step_oversample = step_oversample or oversample
    if step_oversample % oversample:
        raise ValueError("step_oversample must be a multiple of oversample")
    every = step_oversample // oversample
    h = 1.0 / (fs_hz * step_oversample)
    h_out = 1.0 / (fs_hz * oversample)
    advance, g0, g1 = stepper(sysm, h, tier == "modes")
    n_out = int(round(contact_window_s / h_out))
    x = np.zeros(sysm.a.shape[0], dtype=sysm.a.dtype)
    x, outs, stats = contact(sysm, k, x, hammer_speed_m_s, h, every, n_out, advance, g0, g1)
    tip, tip_v, arc, arc_v = (np.concatenate([[0.0], o]) for o in outs)
    contact_steps, f_max, strikes = stats
    # the rest: free, in closed form
    n_total = int(round(duration_s / h_out))
    t_rest = h_out * np.arange(1, n_total - n_out + 1)
    rest = sysm.free(x, t_rest)
    tip = np.concatenate([tip, rest[0]])
    tip_v = np.concatenate([tip_v, rest[1]])
    arc = np.concatenate([arc, rest[2]])
    arc_v = np.concatenate([arc_v, rest[3]])

    flux = flux or pk.flux_map(k.pickup)
    voicing = k.pickup.voicing_m if voicing_m is None else voicing_m
    y = voicing + tip
    lo, hi = flux.y_range_m
    off = (y < lo) | (y > hi)
    y = np.clip(y, lo, hi)
    arc = np.clip(arc, flux.dg_m[0], flux.dg_m[-1])
    emf = -(flux(y, arc, dy=1) * tip_v + flux(y, arc, ddg=1) * arc_v)
    if oversample > 1:
        emf = signal.resample_poly(emf, 1, oversample)
        tip = tip[::oversample]
    t = np.arange(emf.size) / fs_hz
    return Strike(t, emf, tip, contact_steps * h, f_max, strikes, float(np.sum(off)) * h_out)

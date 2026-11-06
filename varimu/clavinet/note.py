"""A key played: the tangent's strike, the hold, the release, the pickups' EMF
(docs/CLAVINET_PLAN.md, CL1).

**Strike** (`strike_window_s`, longer if the pinch hasn't closed): the released string's
modes stepped exactly for forces linear over the step (first-order hold), with two
contacts at the anvil point solved inside each step (a scalar 2x2 Newton, as the Rhodes'
hammer: the contact can't be a sample late):
- the tangent's rubber, Hunt-Crossley F = K d^1.5 (1 + alpha d'), between the tangent (a
  mass thrown up at the key's velocity from `travel_m` below the string, pushed by the
  finger's constant force) and the string;
- the anvil, a spring and dashpot along its face normal (tilted from the vertical), when
  the string reaches it.

**Hold:** once both contacts have been closed for `settle_s`, the state (the string's
coordinates and the tangent's) moves to the held system's modes, relative to the held
static press (`strings.static`), and runs in closed form.

**Release:** the finger lets go: the state, the static press included, moves to the
released system's modes, and the contacts are solved inside each step again while the
key's return force pulls the tangent away (the rubber unloads and the string leaves the
anvil over a few milliseconds; letting go of the pinch at once snapped the bent string back
in one step, a click across the whole band: CL1's first try). Then closed form: the string
springs back and the yarn damps it.

**Tension modulation** (`tension_mod=True`, the default; CL4): the hold's modes follow
the tension their energies add (the string's elongation 1/2 int w'^2 through the geometric
stiffness, both planes), per chunk of the closed form: the slack low plain strings glide
down in pitch as a hard note decays. First order: each mode's frequency scales by
1 + dT / 2T; the strike phase and the release are linear.

**Pickups** read the string's displacement and velocity averaged over each bar's width
(the static press shifts the operating point, it is included) through `pickup.emf`. The
analytic free-space map has [R12]'s shape but not the bars' steel, so its level is scaled
once to [G13]'s 400 mV (`level_factor`). The EMF is computed at `oversample` x fs and
decimated.
"""

from __future__ import annotations

import functools
import hashlib
import json
from dataclasses import dataclass, replace

import numpy as np
from scipy import signal

from varimu.clavinet import fit, pickup, spec, strings
from varimu.clavinet import knock as keybed

PICKUPS = ("centre", "bridge")


@dataclass(frozen=True)
class Played:
    t_s: np.ndarray
    emf_v: dict[str, np.ndarray]  # per pickup, at fs
    disp_m: dict[str, np.ndarray]  # each pickup's y displacement (static included), at fs
    contact_s: float  # the first rubber contact's start to the pinch's closing
    max_force_n: float
    hold_from_s: float
    release_s: float


def pickup_distance_m(which: str, n: int, name: str = "d6") -> float:
    cfg = spec.load(name)
    pc = cfg["pickups"]
    if which == "bridge":
        return float(pc["bridge_distance_m"])
    a, b = pc["centre_distance_m"]
    keys = int(cfg["tuning"]["keys"])
    return float(a + (b - a) * (n - 1) / (keys - 1))


def _foh(lam: np.ndarray, h: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For x' = lam x + b u, u linear over h: x1 = phi x0 + b (e0 u0 + e1 u1)."""
    x = lam * h
    phi = np.exp(x)
    small = np.abs(x) < 1e-2
    with np.errstate(divide="ignore", invalid="ignore"):
        e1 = np.where(small, h * (1 + x / 2 + x * x / 6 + x**3 / 24), np.expm1(x) / lam)
        e2 = np.where(
            small, h * (0.5 + x / 6 + x * x / 24 + x**3 / 120), (np.expm1(x) - x) / (lam * x)
        )
    return phi, e1 - e2, e2


def _closed_form(
    sysm: strings.System,
    z0: np.ndarray,
    rows: np.ndarray,
    n_out: int,
    h: float,
    chunk: int = 1024,
    fm: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """rows (r x 2n) applied to the state from modal state z0 at times h, 2h, ... n_out h
    (the start excluded): conjugate pairs folded, modes above Nyquist dropped. `fm`: the
    tension modulation's coupling (`tension_coupling`): each mode's frequency then follows
    the tension the modes' energies add, updated per chunk. Returns (outputs, each mode's
    accumulated extra phase at the end, per eigenvalue: conjugates negated)."""
    lam_all = sysm.lam
    amp = (rows @ sysm.v) * z0  # (r, 2n)
    pos = lam_all.imag > 1e-9
    real = np.abs(lam_all.imag) <= 1e-9
    keep = (pos | real) & (np.abs(lam_all.imag) * h < np.pi)
    lam = lam_all[keep]
    amp = amp[:, keep] * np.where(pos[keep], 2.0, 1.0)
    out = np.zeros((rows.shape[0], n_out))
    steps = np.exp(np.outer(lam, h * np.arange(1, chunk + 1)))
    adv = np.exp(lam * h * chunk)
    a = amp.copy()
    phase = np.zeros(lam_all.size)
    e0 = np.abs(z0) ** 2 if fm is not None else None
    for s in range(0, n_out, chunk):
        m = min(chunk, n_out - s)
        if fm is not None:
            t_mid = (s + 0.5 * m) * h
            rel = float(np.sum(fm * e0 * np.exp(2 * lam_all.real * t_mid)))  # dT / T
            dphi = lam_all.imag * rel / 2 * m * h
            a = a * np.exp(1j * dphi[keep])
            phase += dphi
        out[:, s : s + m] = np.real(a @ steps[:, :m])
        a = a * adv
    return out, phase


def tension_coupling(p: strings.Params, held: strings.System) -> np.ndarray:
    """Per eigenvalue k: the share of dT / T one unit of |z_k|^2 adds. The string's
    elongation is 1/2 x' Kg x (Kg the geometric stiffness per unit tension, both planes), so
    a conjugate pair (z_k, conj z_k) adds |z_k|^2 v_k^H Kg v_k on average, and
    dT = EA / L_total times the elongation."""
    lay = held.lay
    bump = replace(p, tension_held_n=p.tension_held_n + 1.0)
    k1 = strings.matrices(bump, True, lay)[2]
    k0 = held.k
    kg = k1 - k0  # exact: K is linear in the tension
    n = held.n
    v = held.v[:n]
    quad = np.real(np.einsum("ik,ij,jk->k", v.conj(), kg, v))
    total_len = p.geom.length_m + p.nonspeaking_m
    # only the ringing modes: lightly damped, in the band. The damped system's modes aren't
    # orthogonal, and a bent shape decomposes into large mutually cancelling amplitudes on
    # the stiff, heavily damped ones (the anvil's contact mode near 280 kHz): counting
    # their |z|^2 as energy gave dT / T ~ 2 from the static press alone
    ringing = (
        (held.lam.imag > 1e-9)
        & (-held.lam.real < RINGING_SIGMA)
        & (held.lam.imag < 2 * np.pi * RINGING_HZ)
    )
    return np.where(ringing, 2.0, 0.0) * quad * p.geom.ea_n / total_len / (2 * p.tension_held_n)


RINGING_SIGMA = 100.0  # 1/s
RINGING_HZ = 8000.0


@dataclass(frozen=True)
class _Rows:
    """Output rows on the physical state (displacements; velocities), per pickup: y, x."""

    disp: np.ndarray  # (4, n_coords): centre y, centre x, bridge y, bridge x
    n_coords: int

    def state_rows(self) -> np.ndarray:
        z = np.zeros_like(self.disp)
        return np.vstack([np.hstack([self.disp, z]), np.hstack([z, self.disp])])  # 8 rows


def _rows(p: strings.Params, lay: strings.Layout, n_coords: int, name: str) -> _Rows:
    cfg = spec.load(name)
    width = cfg["pickups"]["bar_width_m"]
    rs = []
    for w in PICKUPS:
        d = pickup_distance_m(w, p.geom.n, name)
        for plane in (0, 1):
            r = strings.point_rows(p, lay, plane, d, width)
            rs.append(np.concatenate([r, np.zeros(n_coords - r.size)]))
    return _Rows(np.array(rs), n_coords)


def play(
    n: int,
    velocity_m_s: float,
    hold_s: float,
    tail_s: float = 0.3,
    fs_hz: float = 96000.0,
    oversample: int = 2,
    step_oversample: int = 16,
    strike_window_s: float = 0.010,
    settle_s: float = 0.002,
    f_cut_hz: float | None = None,
    hold_force_n: float | None = None,
    params: strings.Params | None = None,
    name: str = "d6",
    level: bool = True,
    knock: bool = True,
    knock_s: float = 0.4,
    tension_mod: bool = True,
) -> Played:
    """Key n struck at `velocity_m_s` (the tangent's speed), held `hold_s`, then released
    and followed for `tail_s`."""
    cfg = spec.load(name)
    p = params or fit.params(n, name)
    if f_cut_hz is not None:
        p = replace(p, f_cut_hz=f_cut_hz)
    if hold_force_n is not None:
        p = replace(p, hold_force_n=hold_force_n)
    lay = strings.layout(p)
    rel = strings.system(p, False, lay)
    held = strings.system(p, True, lay)
    ns = lay.n_string
    h = 1.0 / (fs_hz * step_oversample)
    every = step_oversample // oversample
    h_out = 1.0 / (fs_hz * oversample)

    # --- strike: released modes + two contacts at the anvil point ---
    rows8 = _rows(p, lay, ns, name).state_rows()
    stepper = _ContactStepper(rel, p, lay, h, rows8)
    z = np.zeros(2 * ns, dtype=complex)
    zt, vt = -cfg["tangent"]["travel_m"], velocity_m_s
    z, zt, vt, strike_out, st = stepper.run(
        z,
        zt,
        vt,
        p.hold_force_n,
        every,
        until="closed",
        window_s=strike_window_s,
        settle_s=settle_s,
    )
    t_first, t_closed, f_max = st["t_first"], st["t_closed"], st["f_max"]
    t_hold0 = st["t_end"]

    # --- hold: the held system's modes about the static press ---
    us = strings.static(p)
    x_phys = rel.to_phys(z)  # (u, v) of the string
    nh = held.n
    u = np.concatenate([x_phys[:ns], [zt]])
    v = np.concatenate([x_phys[ns:], [vt]])
    zh = held.to_modal(np.concatenate([u - us, v]))
    rows_h = np.vstack([np.hstack([np.pad(r, (0, 1)), np.zeros(nh)]) for r in rows8[:4, :ns]])
    rows_h = np.vstack(
        [rows_h, np.vstack([np.hstack([np.zeros(nh), np.pad(r, (0, 1))]) for r in rows8[4:, ns:]])]
    )
    static_out = np.concatenate([rows_h[:4, :nh] @ us, np.zeros(4)])
    n_hold = max(int(round((hold_s - t_hold0) / h_out)), 0)
    fm = tension_coupling(p, held) if tension_mod else None
    hold_out, hold_phase = _closed_form(held, zh, rows_h, n_hold, h_out, fm=fm)
    hold_out = hold_out + static_out[:, None]
    knock_state = None
    if knock and n_hold > 0:
        # the board's ringing under the anvil, pushing the pinched string along the anvil's
        # normal through its contact stiffness (knock.py), stepped on the held modes
        n_k = min(n_hold, int(round(knock_s / h_out)))
        u_kb = keybed.anvil_motion(n, st["fa"], h, n_k, h_out, name)
        nrm = np.array([np.cos(p.tilt_rad), np.sin(p.tilt_rad)])
        b_kn = nrm[0] * held.input(lay.ua(0)) + nrm[1] * held.input(lay.ua(1))
        f_kn = p.anvil_k_n_m * u_kb
        ph, e0k, e1k = _foh(held.lam, h_out)
        zk = np.zeros_like(zh)
        rows_hm = rows_h @ held.v
        k_out = np.zeros((rows_h.shape[0], n_k))
        f_prev = 0.0
        for j in range(n_k):
            zk = ph * zk + b_kn * (e0k * f_prev + e1k * f_kn[j])
            f_prev = f_kn[j]
            k_out[:, j] = np.real(rows_hm @ zk)
        hold_out[:, :n_k] += k_out
        knock_state = (zk, n_k)  # carried on (free) to the release

    # --- release: back to the released modes, the press included; the tangent pulled
    # away by the key's return force, the contacts solved until they have opened ---
    zh_end = zh * np.exp(held.lam * n_hold * h_out + 1j * hold_phase)
    if knock_state is not None:
        zk, n_k = knock_state
        zh_end = zh_end + zk * np.exp(held.lam * (n_hold - n_k) * h_out)
    xh = held.to_phys(zh_end)
    u = xh[:nh] + us
    v = xh[nh:]
    zr = rel.to_modal(np.concatenate([u[:ns], v[:ns]]))
    zr, _, _, release_out, _ = stepper.run(
        zr, u[nh - 1], v[nh - 1], -cfg["tangent"]["return_force_n"], every, until="open"
    )
    n_tail = max(int(round(tail_s / h_out)) - release_out.shape[1], 0)
    tail_out, _ = _closed_form(rel, zr, rows8, n_tail, h_out)

    allout = np.hstack([strike_out, hold_out, release_out, tail_out])
    pks = pickup.pickups(name)
    g = p.geom
    mu_r = cfg["steel"]["mu_r"]
    emf, disp = {}, {}
    scale = level_factor(name) if level else 1.0
    for j, w in enumerate(PICKUPS):
        pk = pks[w]
        lmap = pickup.linkage_map(pk, g.n, g.d_magnetic_m, mu_r)
        y, x = allout[2 * j], allout[2 * j + 1]
        vy, vx = allout[4 + 2 * j], allout[4 + 2 * j + 1]
        e = scale * pickup.emf(pk, lmap, y, x, vy, vx)
        if oversample > 1:
            e = signal.resample_poly(e, 1, oversample)
            y = y[::oversample]
        emf[w] = e
        disp[w] = y
    t = np.arange(emf[PICKUPS[0]].size) / fs_hz
    contact = (
        (t_closed - t_first) if (t_closed is not None and t_first is not None) else float("nan")
    )
    return Played(
        t, emf, disp, float(contact), float(f_max), float(t_hold0), float(t_hold0 + n_hold * h_out)
    )


class _ContactStepper:
    """The released modes stepped exactly for forces linear over the step, with the
    tangent's rubber and the anvil solved inside each step (a 2x2 Newton): the strike, and
    the release (the tangent then pulled away)."""

    def __init__(self, rel, p, lay, h, rows8):
        ns = lay.n_string
        ay, ax = lay.ua(0), lay.ua(1)
        self.h = h
        self.phi, e0, e1 = _foh(rel.lam, h)
        b_y, b_x = rel.input(ay), rel.input(ax)
        self.g0y, self.g1y, self.g0x, self.g1x = b_y * e0, b_y * e1, b_x * e0, b_x * e1

        def row(coord, vel):
            r = np.zeros(2 * ns)
            r[coord + (ns if vel else 0)] = 1.0
            return r @ rel.v

        self.cy, self.cx = row(ay, False), row(ax, False)
        self.cvy, self.cvx = row(ay, True), row(ax, True)
        self.gyy, self.gyx = np.real(self.cy @ self.g1y), np.real(self.cy @ self.g1x)
        self.gxy, self.gxx = np.real(self.cx @ self.g1y), np.real(self.cx @ self.g1x)
        self.hyy, self.hyx = np.real(self.cvy @ self.g1y), np.real(self.cvy @ self.g1x)
        self.hxy, self.hxx = np.real(self.cvx @ self.g1y), np.real(self.cvx @ self.g1x)
        self.p = p
        self.rows_m = rows8 @ rel.v  # (8, 2n): outputs from the modal state

    def _forces(self, z, zt, vt):
        """The contacts' forces at a state (the first step's force history)."""
        p = self.p
        cs, sn = np.cos(p.tilt_rad), np.sin(p.tilt_rad)
        ya, xa = np.real(self.cy @ z), np.real(self.cx @ z)
        vya, vxa = np.real(self.cvy @ z), np.real(self.cvx @ z)
        dr, ddr = zt - ya, vt - vya
        fr = 0.0
        if dr > 0:
            fr = p.rubber_k * dr**p.rubber_p * max(1 + p.rubber_alpha_s_m * ddr, 0.0)
        da, dda = cs * ya + sn * xa - p.anvil_gap_m, cs * vya + sn * vxa
        fa = max(p.anvil_k_n_m * da + p.anvil_c_ns_m * dda, 0.0) if da > 0 else 0.0
        return float(fr), float(fa)

    def run(self, z, zt, vt, f_h, every, until, window_s=0.0, settle_s=0.002, max_s=0.06):
        """Step from modal state z, the tangent at zt, vt, the finger's force f_h on it
        (negative: the key's return force), until both contacts have been closed for
        settle_s past window_s ("closed": the strike) or open for 1 ms past 2 ms ("open":
        the release). Returns (z, zt, vt, outputs (8, n), stats)."""
        p, h = self.p, self.h
        cs, sn = np.cos(p.tilt_rad), np.sin(p.tilt_rad)
        m_t = p.tangent_mass_kg
        k_r, p_r, a_r = p.rubber_k, p.rubber_p, p.rubber_alpha_s_m
        k_a, c_a, gap = p.anvil_k_n_m, p.anvil_c_ns_m, p.anvil_gap_m
        gyy, gyx, gxy, gxx = self.gyy, self.gyx, self.gxy, self.gxx
        hyy, hyx, hxy, hxx = self.hyy, self.hyx, self.hxy, self.hxx
        fr_prev, fa_prev = self._forces(z, zt, vt)
        k_g, c_g = p.grip_k_n_m, p.grip_c_ns_m
        # entering held (the release), the grip carries the state's sideways force
        x_now, vx_now = float(np.real(self.cx @ z)), float(np.real(self.cvx @ z))
        x_stick = 0.0 if fr_prev > 0 else None
        fg_prev = -k_g * x_now - c_g * vx_now if fr_prev > 0 else 0.0
        fy_prev, fx_prev = fr_prev - fa_prev * cs, -fa_prev * sn + fg_prev
        out = []
        fa_hist = []
        t_first = t_closed = closed_since = open_since = None
        f_max = 0.0
        max_steps = int(round(max_s / h))
        cz, cv = h * h / (6 * m_t), h / (2 * m_t)  # zt = ztf + cz (f_h - fr), vt likewise
        i = 0
        while True:
            zf = self.phi * z + self.g0y * fy_prev + self.g0x * fx_prev
            yf, xf = np.real(self.cy @ zf), np.real(self.cx @ zf)
            vyf, vxf = np.real(self.cvy @ zf), np.real(self.cvx @ zf)
            a_prev = (f_h - fr_prev) / m_t
            ztf = zt + h * vt + h * h * (2 * a_prev) / 6 + cz * f_h
            vtf = vt + h * a_prev / 2 + cv * f_h
            # the unknowns: the rubber's push fr, the anvil's push fa, the rubber's sideways
            # grip fg (its shear, stuck where the rubber first touched: without it the
            # anvil's tilted face slid the string millimetres sideways, CL1's first try)
            if x_stick is None and fr_prev > 0:
                x_stick = float(np.real(self.cx @ z))

            def resid(
                f: np.ndarray,
                yf=yf,
                xf=xf,
                vyf=vyf,
                vxf=vxf,
                ztf=ztf,
                vtf=vtf,
                x_stick=x_stick,
            ) -> tuple[np.ndarray, float, float]:
                fr_, fa_, fg_ = f
                fy_, fx_ = fr_ - fa_ * cs, -fa_ * sn + fg_
                ya_ = yf + gyy * fy_ + gyx * fx_
                xa_ = xf + gxy * fy_ + gxx * fx_
                vya_ = vyf + hyy * fy_ + hyx * fx_
                vxa_ = vxf + hxy * fy_ + hxx * fx_
                dr_, ddr_ = ztf - cz * fr_ - ya_, vtf - cv * fr_ - vya_
                da_, dda_ = cs * ya_ + sn * xa_ - gap, cs * vya_ + sn * vxa_
                frh = k_r * dr_**p_r * max(1 + a_r * ddr_, 0.0) if dr_ > 0 else 0.0
                fah = max(k_a * da_ + c_a * dda_, 0.0) if da_ > 0 else 0.0
                stick = x_stick if x_stick is not None else xa_
                fgh = -k_g * (xa_ - stick) - c_g * vxa_ if dr_ > 0 else 0.0
                return np.array([fr_ - frh, fa_ - fah, fg_ - fgh]), dr_, da_

            f = np.array([fr_prev, fa_prev, fg_prev])
            for _ in range(40):
                r, _, _ = resid(f)
                jac = np.empty((3, 3))
                for c_ in range(3):
                    d = 1e-7 * max(1.0, abs(f[c_]))
                    fp = f.copy()
                    fp[c_] += d
                    jac[:, c_] = (resid(fp)[0] - r) / d
                step = np.linalg.solve(jac, r)
                f_new = f - step
                f_new[0] = max(f_new[0], 0.0)
                f_new[1] = max(f_new[1], 0.0)
                done = np.all(np.abs(f_new - f) < 1e-10 * np.maximum(1.0, np.abs(f)))
                f = f_new
                if done:
                    break
            fr, fa, fg = (float(v) for v in f)
            if fr == 0.0:
                fg = 0.0
            fy, fx = fr - fa * cs, -fa * sn + fg
            z = zf + self.g1y * fy + self.g1x * fx
            zt, vt = ztf - cz * fr, vtf - cv * fr
            fr_prev, fa_prev, fg_prev, fy_prev, fx_prev = fr, fa, fg, fy, fx
            if fr == 0.0:
                x_stick = None
            fa_hist.append(fa)
            f_max = max(f_max, fr)
            i += 1
            t = i * h
            if fr > 0 and t_first is None:
                t_first = t
            closed = fr > 0 and fa > 0
            closed_since = (closed_since if closed_since is not None else t) if closed else None
            opened = fr == 0 and fa == 0
            open_since = (open_since if open_since is not None else t) if opened else None
            if i % every == 0:
                out.append(np.real(self.rows_m @ z))
                if until == "closed" and t >= window_s and closed_since is not None:
                    if t - closed_since >= settle_s:
                        t_closed = closed_since
                        break
                if until == "open" and t >= 0.002 and open_since is not None:
                    if t - open_since >= 0.001:
                        break
                if i >= max_steps:
                    t_closed = closed_since
                    break
        stats = {
            "t_first": t_first,
            "t_closed": t_closed,
            "f_max": f_max,
            "t_end": i * h,
            "fa": np.array(fa_hist),
        }
        outs = np.array(out).T if out else np.zeros((8, 0))
        return z, zt, vt, outs, stats


LEVEL_KEY = 36


@functools.cache
def level_factor(name: str = "d6") -> float:
    """The pickups' flux concentration (the bars' steel, missing from the free-space map):
    [G13]'s figure, as configured, for E4 at the top velocity on the centre pickup."""
    cfg = spec.load(name)
    pc = cfg["pickups"]
    key = hashlib.sha256((fit._cache_key(name) + "level4-grip").encode()).hexdigest()[:16]
    spec.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = spec.CACHE_DIR / f"level_{key}.json"
    if path.exists():
        return float(json.loads(path.read_text())["factor"])
    v_top = cfg["tangent"]["velocity_range_m_s"][1]
    pl = play(LEVEL_KEY, v_top, 0.3, tail_s=0.0, name=name, level=False)
    peak = float(np.max(np.abs(pl.emf_v["centre"])))
    factor = pc["level_v"] / peak
    path.write_text(json.dumps({"factor": factor, "peak_raw_v": peak}))
    return factor

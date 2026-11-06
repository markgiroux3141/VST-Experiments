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
    sysm: strings.System, z0: np.ndarray, rows: np.ndarray, n_out: int, h: float, chunk: int = 2048
) -> np.ndarray:
    """rows (r x 2n) applied to the state from modal state z0 at times h, 2h, ... n_out h
    (the start excluded): conjugate pairs folded, modes above Nyquist dropped."""
    lam = sysm.lam
    amp = (rows @ sysm.v) * z0  # (r, 2n)
    pos = lam.imag > 1e-9
    real = np.abs(lam.imag) <= 1e-9
    keep = (pos | real) & (np.abs(lam.imag) * h < np.pi)
    lam = lam[keep]
    amp = amp[:, keep] * np.where(pos[keep], 2.0, 1.0)
    out = np.zeros((rows.shape[0], n_out))
    steps = np.exp(np.outer(lam, h * np.arange(1, chunk + 1)))
    adv = np.exp(lam * h * chunk)
    a = amp.copy()
    for s in range(0, n_out, chunk):
        m = min(chunk, n_out - s)
        out[:, s : s + m] = np.real(a @ steps[:, :m])
        a = a * adv
    return out


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
    hold_out = _closed_form(held, zh, rows_h, n_hold, h_out) + static_out[:, None]

    # --- release: back to the released modes, the press included; the tangent pulled
    # away by the key's return force, the contacts solved until they have opened ---
    zh_end = zh * np.exp(held.lam * n_hold * h_out)
    xh = held.to_phys(zh_end)
    u = xh[:nh] + us
    v = xh[nh:]
    zr = rel.to_modal(np.concatenate([u[:ns], v[:ns]]))
    zr, _, _, release_out, _ = stepper.run(
        zr, u[nh - 1], v[nh - 1], -cfg["tangent"]["return_force_n"], every, until="open"
    )
    n_tail = max(int(round(tail_s / h_out)) - release_out.shape[1], 0)
    tail_out = _closed_form(rel, zr, rows8, n_tail, h_out)

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
        fy_prev, fx_prev = fr_prev - fa_prev * cs, -fa_prev * sn
        out = []
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
            fr, fa = fr_prev, fa_prev
            for _ in range(40):
                fy, fx = fr - fa * cs, -fa * sn
                ya = yf + gyy * fy + gyx * fx
                xa = xf + gxy * fy + gxx * fx
                vya = vyf + hyy * fy + hyx * fx
                vxa = vxf + hxy * fy + hxx * fx
                ztn, vtn = ztf - cz * fr, vtf - cv * fr
                dr, ddr = ztn - ya, vtn - vya
                da, dda = cs * ya + sn * xa - gap, cs * vya + sn * vxa
                dr_r, dr_a = -cz - gyy, gyy * cs + gyx * sn
                ddr_r, ddr_a = -cv - hyy, hyy * cs + hyx * sn
                da_r = cs * gyy + sn * gxy
                da_a = -(cs * (gyy * cs + gyx * sn) + sn * (gxy * cs + gxx * sn))
                dda_r = cs * hyy + sn * hxy
                dda_a = -(cs * (hyy * cs + hyx * sn) + sn * (hxy * cs + hxx * sn))
                if dr > 0:
                    hc = max(1 + a_r * ddr, 0.0)
                    frh = k_r * dr**p_r * hc
                    j_r = k_r * p_r * dr ** (p_r - 1) * hc
                    j_rv = k_r * dr**p_r * a_r if hc > 0 else 0.0
                else:
                    frh, j_r, j_rv = 0.0, 0.0, 0.0
                fah, j_a, j_av = 0.0, 0.0, 0.0
                if da > 0:
                    fah = k_a * da + c_a * dda
                    if fah > 0:
                        j_a, j_av = k_a, c_a
                    else:
                        fah = 0.0
                r1, r2 = fr - frh, fa - fah
                a11 = 1 - (j_r * dr_r + j_rv * ddr_r)
                a12 = -(j_r * dr_a + j_rv * ddr_a)
                a21 = -(j_a * da_r + j_av * dda_r)
                a22 = 1 - (j_a * da_a + j_av * dda_a)
                det = a11 * a22 - a12 * a21
                s1 = (a22 * r1 - a12 * r2) / det
                s2 = (-a21 * r1 + a11 * r2) / det
                fr_new, fa_new = max(fr - s1, 0.0), max(fa - s2, 0.0)
                done = abs(fr_new - fr) < 1e-10 * max(1.0, fr)
                done = done and abs(fa_new - fa) < 1e-10 * max(1.0, fa)
                fr, fa = fr_new, fa_new
                if done:
                    break
            fy, fx = fr - fa * cs, -fa * sn
            z = zf + self.g1y * fy + self.g1x * fx
            zt, vt = ztf - cz * fr, vtf - cv * fr
            fr_prev, fa_prev, fy_prev, fx_prev = fr, fa, fy, fx
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
        stats = {"t_first": t_first, "t_closed": t_closed, "f_max": f_max, "t_end": i * h}
        outs = np.array(out).T if out else np.zeros((8, 0))
        return z, zt, vt, outs, stats


LEVEL_KEY = 36


@functools.cache
def level_factor(name: str = "d6") -> float:
    """The pickups' flux concentration (the bars' steel, missing from the free-space map):
    [G13]'s figure, as configured, for E4 at the top velocity on the centre pickup."""
    cfg = spec.load(name)
    pc = cfg["pickups"]
    key = hashlib.sha256((fit._cache_key(name) + "level3-along-release").encode()).hexdigest()[:16]
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

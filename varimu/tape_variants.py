"""Opt-in variants of the tape medium for the over-bias study (docs/TAPE_PLAN.md, "Over-bias
options (2026-11-12, overnight study)"; scripts/tape_overbias_study.py).

Sound Talk No. 21's bias curves come out too narrow in bias (TAPE_PLAN.md TM2 step 7), and
the cheap model terms that could widen them are measured here as options. Nothing here runs
unless a caller asks for it. It lives outside varimu/devices on purpose: an edit there moves
every render's cache key (varimu.sim.runner.RESULT_CODE), so the base model's IRs, renders,
caches and tape alignments stay exactly as they were. An option the user adopts moves into
varimu/devices/{preisach,tape,tape_fit}.py and the tape component.

1. **The moving model** (Della Torre, "Magnetic Hysteresis", IEEE Press 1999, ch. 4; the
   "moving Preisach" of the plan's untried list): every hysteron of a cell sees H + alpha Ms
   M, M the cell's own irreversible magnetization (a vector: the easy axes share it). The
   static interaction field of the base model (the Gaussian g(Hi)) stays; this is its mean,
   magnetization-dependent part. alpha < 0: demagnetizing (shearing) interactions, as
   particulate gamma-Fe2O3's negative Henkel (delta-M) plots say; alpha > 0: magnetizing,
   the sign Della Torre's fits to square loops take. The state is followed forward (a
   cell's history can no longer be read backward from its extrema): `Stack` is the
   wiping-out memory, `moving_step` the self-consistent M at one sample. circuitsim's
   `tape_record(..., mean_field=, ms_a_m=)` (`crate::tape::record_mean_field`) is the port;
   `record_reference` is this reference over the same arrays (tests/test_tape_variants.py).
   The static fit to Sound Talk No. 20 is redone with the mean field on (`along_x`,
   `fit_preisach`).
2. **The record head's field against current** (`HeadLaw`): the deep-gap field the kernel
   sees is Hg_lin times the head's efficiency eta(B) / eta(0), B the core's flux density
   at that instant, from a magnetic circuit (gap and core reluctances) whose core
   permeability depends on B (mumetall's measured amplitude permeability, eddy-limited at
   the bias frequency, saturating at its 0.8 T). Memoryless, so the bias peaks carry it
   exactly. Applied to the kernel's `hg` (the head's whole field: signal plus bias).
3. **The easy axes in 3D** (`Orientation3D`): the axes on the sphere with a Bingham density
   exp(kappa u_x^2 - lam u_y^2) (u_x along the tape, u_y into the coating, u_z across the
   track). The head's field has no z component, so an axis u acts as the in-plane axis
   (u_x, u_y) of length < 1: driven by (u_x, u_y) . H and contributing m (u_x, u_y) to
   (M_x, M_y). The kernels take such axes as they are (their `axes` need not be unit).
   The base model's `Orientation` spreads the axes in the x-y plane (the head's plane).

`variant_kernel` swaps varimu.devices.tape's Rust kernel call for one with these options
(and a thread limit) inside a `with` block: the medium's code is otherwise the base model's.
"""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass

import numpy as np

from varimu.devices import tape as tape_mod
from varimu.devices.preisach import Preisach

MU0 = 4e-7 * math.pi

# --- 1. The moving model: the reference -------------------------------------------------

#: The solver's tolerance on M / Ms and its iteration limit (as circuitsim's).
MOVING_TOL = 1e-12
MOVING_ITER = 400
MOVING_DET_MIN = 0.05


class _Tables:
    """Scalar reads of a Preisach ensemble's production tables (Q, the corner formula)."""

    def __init__(self, pre: Preisach):
        self.pre = pre
        self.big = 4.0 * pre.p.h_max_a_m

    def q(self, a: float, b: float) -> float:
        return float(self.pre._q(np.array([a]), np.array([b]))[0])

    def corner_up(self, x: float) -> float:
        """The up weight after the single sample x from the erased state (the corner
        formula: Q(x, inf) - Q(-inf, inf) plus the never-reached part)."""
        b, a_next = self.big, -self.big
        up = self.q(x, b) - self.q(a_next, b)
        top, bot = x, x
        xx = max(top, -bot)
        d = float(self.pre._d(np.array([xx]))[0])
        return up + (self.q(xx, bot) - self.q(top, bot) + d)


@dataclass
class _Trial:
    x: float
    up: float
    keep: int
    max: bool


class Stack:
    """One easy axis's wiping-out memory: the history's alternating dominant extrema with
    the up weight after each (circuitsim's `tape::Stack`). The erased start puts a virtual
    extremum of the other kind at -e below the first entry e."""

    def __init__(self) -> None:
        self.v: list[float] = []
        self.up: list[float] = []
        self.max: list[bool] = []

    def trial(self, t: _Tables, x: float) -> _Trial:
        n = len(self.v)
        if n and x == self.v[-1]:
            return _Trial(x, self.up[-1], n - 1, self.max[-1])
        rising = x > 0.0 if n == 0 else x > self.v[-1]
        i = n
        while True:
            if i == 0:
                return _Trial(x, t.corner_up(x), 0, rising)
            top = i - 1
            if self.max[top] == rising:
                i -= 1
                continue
            e = self.v[top]
            below = self.v[top - 1] if top >= 1 else -e
            if (rising and x >= below) or (not rising and x <= below):
                i = max(top - 1, 0)
                continue
            if rising:
                up = self.up[top] + (t.q(x, x) - t.q(x, e))
            else:
                up = self.up[top] - (t.q(e, e) - t.q(e, x))
            return _Trial(x, up, top + 1, rising)

    def commit(self, tr: _Trial) -> None:
        del self.v[tr.keep :], self.up[tr.keep :], self.max[tr.keep :]
        self.v.append(tr.x)
        self.up.append(tr.up)
        self.max.append(tr.max)


def moving_step(t: _Tables, axes, stacks, h, a: float, m0):
    """The cell's M (in Ms) at one sample: each axis sees its share of h + a M (a = alpha
    Ms); commits the axes' states (circuitsim's `tape::moving_step`, step for step): damped
    Newton while its Jacobian's determinant exceeds MOVING_DET_MIN, else the fixed-point
    iteration from m0 (near an avalanche). Returns (M, converged)."""
    hx, hy = h
    trials: list[_Trial] = [None] * len(stacks)  # type: ignore[list-item]

    def ev(m):
        fx, fy = hx + a * m[0], hy + a * m[1]
        ox = oy = 0.0
        for j, (st, ax) in enumerate(zip(stacks, axes, strict=True)):
            trials[j] = st.trial(t, ax[0] * fx + ax[1] * fy)
            mj = 2.0 * trials[j].up - 1.0
            ox += ax[2] * ax[0] * mj
            oy += ax[2] * ax[1] * mj
        return ox, oy

    m = m0
    f = ev(m)
    res = max(abs(f[0] - m[0]), abs(f[1] - m[1]))
    done = res <= MOVING_TOL
    it = 0
    while not done and it < MOVING_ITER:
        it += 1
        fx, fy = hx + a * m[0], hy + a * m[1]
        j11, j12, j22 = 1.0, 0.0, 1.0
        for st, ax, tr in zip(stacks, axes, trials, strict=True):
            x = ax[0] * fx + ax[1] * fy
            dx = 1e-6 * (abs(x) + t.pre.p.h_max_a_m * 1e-3)
            chi = 2.0 * (st.trial(t, x + dx).up - tr.up) / dx
            k = -a * ax[2] * chi
            j11 += k * ax[0] * ax[0]
            j12 += k * ax[0] * ax[1]
            j22 += k * ax[1] * ax[1]
        det = j11 * j22 - j12 * j12
        if det > MOVING_DET_MIN:
            gx, gy = m[0] - f[0], m[1] - f[1]
            step = ((j22 * gx - j12 * gy) / det, (j11 * gy - j12 * gx) / det)
            cand = (m[0] - step[0], m[1] - step[1])
            fc = ev(cand)
            rc = max(abs(fc[0] - cand[0]), abs(fc[1] - cand[1]))
            halvings = 0
            while rc > res and halvings < 30:
                step = (0.5 * step[0], 0.5 * step[1])
                cand = (m[0] - step[0], m[1] - step[1])
                fc = ev(cand)
                rc = max(abs(fc[0] - cand[0]), abs(fc[1] - cand[1]))
                halvings += 1
            f, res = fc, rc
            nxt = cand
        else:
            cand = f
            f = ev(cand)
            res = max(abs(f[0] - cand[0]), abs(f[1] - cand[1]))
            nxt = cand
        m = nxt
        done = res <= MOVING_TOL
    for st, tr in zip(stacks, trials, strict=True):
        st.commit(tr)
    return f, done


def _kernel_inputs(args: dict, li: int, ci: int):
    cells = len(args["s_cells"])
    zones = args["zones"]
    layers = len(args["heights"])
    xz = zones[li] if len(zones) == layers else zones[li * cells + ci]
    s = args["s_cells"][ci]
    s_rec = args["s_rec"]
    k0 = int(np.searchsorted(s_rec, s - xz, side="left"))
    k1 = int(np.searchsorted(s_rec, s + xz, side="right"))

    def at(h):
        if h is None or h[0] is None:
            return 0.0, 0.0
        return float(h[0][li * cells + ci]), float(h[1][li * cells + ci])

    hs = at(args.get("h_static"))
    he = at(args["h_end"]) if args.get("h_end") is not None and args["h_end"][0] is not None else hs
    return s, k0, k1, hs, he


def record_reference(args: dict, alpha: float, ms_a_m: float) -> tuple[np.ndarray, np.ndarray]:
    """The moving model's recording over circuitsim `tape_record`'s inputs (`args`, as
    `variant_kernel` captures them; the exact head field: table_step 0), every cell forward
    in pure Python: the reference of `crate::tape::record_mean_field` (slow: tests only).
    Returns (M_x, M_y) / Ms flattened, layers x cells."""
    if args.get("table_step", 0.0) != 0.0:
        raise ValueError("the reference reads the exact head field (table_step 0)")
    pre = args["pre"]
    t = _Tables(pre)
    a = alpha * ms_a_m
    axes = args["axes"]
    head = tape_mod.HeadGeometry(*args["head"])
    layers, cells = len(args["heights"]), len(args["s_cells"])
    mx = np.zeros(layers * cells)
    my = np.zeros(layers * cells)
    for li in range(layers):
        y = args["heights"][li]
        for ci in range(cells):
            s, k0, k1, (hsx, hsy), end = _kernel_inputs(args, li, ci)
            stacks = [Stack() for _ in axes]
            m = (0.0, 0.0)
            for j in range(k0, max(k1, k0)):
                fx, fy = tape_mod.head_field(head, np.array([s - args["s_rec"][j]]), np.array([y]))
                hg = args["hg"][j]
                h = (hg * float(fx[0]) + hsx, hg * float(fy[0]) + hsy)
                m, _ = moving_step(t, axes, stacks, h, a, m)
            m, _ = moving_step(t, axes, stacks, (hsx, hsy), a, m)
            m, _ = moving_step(t, axes, stacks, end, a, m)
            mx[li * cells + ci], my[li * cells + ci] = m
    return mx, my


def along_x(pre: Preisach, h: np.ndarray, orientation=None, a_a_m: float = 0.0) -> np.ndarray:
    """M_x / Ms after field histories along x (rows of h), as `tape_fit.along_x`, with the
    moving model's mean field a M (a = alpha Ms in A/m, M in Ms: the sample is a long strip
    along x, so no shape demagnetization). a 0: tape_fit's."""
    from varimu.devices import tape_fit

    if a_a_m == 0.0:
        return tape_fit.along_x(pre, h, orientation)
    h = np.atleast_2d(np.asarray(h, float))
    if orientation is None:
        axes = [(1.0, 0.0, 1.0)]
    else:
        cs, sn, wt = orientation.axes()
        axes = list(zip(cs, sn, wt, strict=True))
    t = _Tables(pre)
    out = np.empty(h.shape[0])
    for r in range(h.shape[0]):
        stacks = [Stack() for _ in axes]
        m = (0.0, 0.0)
        for x in h[r]:
            m, _ = moving_step(t, axes, stacks, (float(x), 0.0), a_a_m, m)
        out[r] = m[0]
    return out


def along_x_rust(pre: Preisach, h: np.ndarray, orientation=None, a_a_m: float = 0.0) -> np.ndarray:
    """`along_x` in circuitsim (`tape_moving_along_x`, the port; a 0 too: the forward
    memory, not the corner formula)."""
    import circuitsim

    h = np.atleast_2d(np.asarray(h, float))
    if orientation is None:
        axes = np.array([[1.0, 0.0, 1.0]])
    else:
        axes = np.stack(orientation.axes(), axis=1)
    p = pre.p
    return np.asarray(
        circuitsim.tape_moving_along_x(
            (p.hc_median_a_m, p.sigma_ln_hc, p.sigma_hi_a_m, p.h_max_a_m, p.n_table),
            np.ascontiguousarray(axes, float).ravel(),
            np.ascontiguousarray(h).ravel(),
            h.shape[1],
            float(a_a_m),
        )
    )


@dataclass(frozen=True)
class MovingFit:
    params: object
    ms_a_m: float
    saturation_remanence: float
    coercivity_a_m: float
    rms_sigma: float
    max_abs_wb_per_m: float


def fit_preisach(h_peak, phi_r, coercivity_a_m, coating_m, alpha, orientation=None, n_fit=256):
    """`tape_fit.fit_preisach` with the mean field on: the ensemble (Hc median, its spread,
    the interaction spread) that gives Bulletin 20's remanence curve and Eilers' coercivity
    with the moving model at alpha. Ms then follows from the saturated remanence, and the
    mean field's a = alpha Ms depends on Ms: solved together (a few passes)."""
    from scipy.optimize import least_squares

    from varimu.devices.preisach import PreisachParams
    from varimu.devices.tape_fit import H_MAX_A_M, MU0, SIGMA_PHI_WB_PER_M

    h_peak, phi_r = np.asarray(h_peak, float), np.asarray(phi_r, float)
    top = float(phi_r.max())
    ms = 7.0e4  # a start; refined with the fit's saturation remanence

    def pre_of(x, n=n_fit):
        return Preisach(PreisachParams(x[0], x[1], x[2], H_MAX_A_M, n_table=n))

    def curves(pre, a):
        hs = 2.0 * pre.p.h_max_a_m
        sat = along_x_rust(pre, np.array([[hs, 0.0]]), orientation, a)[0]
        hist = np.stack([h_peak, -h_peak, h_peak, -h_peak, h_peak, np.zeros_like(h_peak)], axis=1)
        rem = along_x_rust(pre, hist, orientation, a)
        return sat, rem

    def coercivity(pre, a):
        lo, hi = 0.0, pre.p.h_max_a_m
        sat = 2.0 * pre.p.h_max_a_m
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            m = along_x_rust(pre, np.array([[sat, -mid]]), orientation, a)[0]
            lo, hi = (mid, hi) if m > 0 else (lo, mid)
        return 0.5 * (lo + hi)

    x = np.array([1.1 * coercivity_a_m, 0.3, 0.3 * coercivity_a_m])
    for _ in range(3):
        a = alpha * ms

        def resid(v, a=a):
            pre = pre_of(v)
            sat, rem = curves(pre, a)
            r_curve = (rem * top / sat - phi_r) / SIGMA_PHI_WB_PER_M
            r_hc = (coercivity(pre, a) - coercivity_a_m) / (0.1 * coercivity_a_m)
            return np.r_[r_curve, r_hc]

        lo = [0.3 * coercivity_a_m, 0.03, 0.01 * coercivity_a_m]
        hi = [3.0 * coercivity_a_m, 1.0, 2.0 * coercivity_a_m]
        r = least_squares(resid, x, bounds=(lo, hi), x_scale=[coercivity_a_m, 0.1, coercivity_a_m])
        x = r.x
        pre = pre_of(x)
        sat, rem = curves(pre, a)
        ms_new = top / (MU0 * coating_m * sat)
        if abs(ms_new - ms) < 1e-4 * ms:
            ms = ms_new
            break
        ms = ms_new
    a = alpha * ms
    pre = pre_of(x)
    sat, rem = curves(pre, a)
    curve = rem * top / sat
    params = PreisachParams(*(float(v) for v in x), H_MAX_A_M, n_table=1024)
    return MovingFit(
        params=params,
        ms_a_m=ms,
        saturation_remanence=float(sat),
        coercivity_a_m=coercivity(pre, a),
        rms_sigma=float(np.sqrt(np.mean(((curve - phi_r) / SIGMA_PHI_WB_PER_M) ** 2))),
        max_abs_wb_per_m=float(np.abs(curve - phi_r).max()),
    )


# --- 5. The astroid: switching in a rotating field -------------------------------------


def astroid_drive(c, s, hx, hy):
    """The field (hx, hy) on an easy axis (c, s) as the equivalent field along it:
    sign(h_par) |H| / h_sw(psi), h_sw = (cos^{2/3} psi + sin^{2/3} psi)^{-3/2} the
    Stoner-Wohlfarth switching field at the angle psi between field and axis, relative to
    the field along it (Stoner & Wohlfarth, Phil. Trans. A 240, 599 (1948)). The particle
    bench's finding (docs/TAPE_PARTICLES.md on the `tape-particles` branch: the over-bias
    fall comes from switching in the head's rotating field, which projections lack) as a
    vector Preisach rule: each hysteron of the axis switches at its own astroid. Along the
    axis it is the projection; at 45 degrees twice it. circuitsim's `tape::astroid_drive`
    is the port. Arrays broadcast.

    A 3D axis (`Orientation3D`: (c, s) its in-plane part, shorter than 1): the field has no
    z component, so psi is the angle between the field and the whole axis, cos psi =
    |h_par| / |H| (the in-plane formula's perpendicular part would be the axis's in-plane
    length times too short)."""
    hx, hy = np.asarray(hx, float), np.asarray(hy, float)
    par = c * hx + s * hy
    if abs(c * c + s * s - 1.0) > 1e-12:
        mag = np.hypot(hx, hy)
        safe = np.where(mag == 0.0, 1.0, mag)
        cp = np.minimum(np.abs(par) / safe, 1.0)
        sp = np.sqrt(1.0 - cp * cp)
    else:
        perp = -s * hx + c * hy
        mag = np.sqrt(par * par + perp * perp)
        safe = np.where(mag == 0.0, 1.0, mag)
        cp, sp = np.abs(par) / safe, np.abs(perp) / safe
    k = np.cbrt(cp) ** 2 + np.cbrt(sp) ** 2
    return np.where((mag == 0.0) | (par == 0.0), 0.0, np.sign(par) * mag * k * np.sqrt(k))


def record_astroid_reference(args: dict) -> tuple[np.ndarray, np.ndarray]:
    """The astroid variant's recording over circuitsim `tape_record`'s inputs (as
    `variant_kernel` captures them; table_step 0), each cell's history per axis through
    `astroid_drive` and the corner formula (the tests' reference)."""
    pre = args["pre"]
    head = tape_mod.HeadGeometry(*args["head"])
    layers, cells = len(args["heights"]), len(args["s_cells"])
    mx = np.zeros(layers * cells)
    my = np.zeros(layers * cells)
    for li in range(layers):
        y = args["heights"][li]
        for ci in range(cells):
            s, k0, k1, (hsx, hsy), (hex_, hey) = _kernel_inputs(args, li, ci)
            j = np.arange(k0, max(k1, k0))
            fx, fy = tape_mod.head_field(head, s - args["s_rec"][j], np.full(len(j), y))
            hx = np.r_[args["hg"][j] * fx + hsx, hsx, hex_]
            hy = np.r_[args["hg"][j] * fy + hsy, hsy, hey]
            for c, sn, w in args["axes"]:
                m = float(pre.state_after(astroid_drive(c, sn, hx, hy)[None, :])[0])
                mx[li * cells + ci] += w * c * m
                my[li * cells + ci] += w * sn * m
    return mx, my


def along_x_astroid(pre: Preisach, h: np.ndarray, orientation=None) -> np.ndarray:
    """`tape_fit.along_x` with each axis driven by `astroid_drive` of the field along x."""
    h = np.atleast_2d(np.asarray(h, float))
    if orientation is None:
        return pre.state_after(h)
    cs, sn, wt = orientation.axes()
    return sum(
        w * c * pre.state_after(astroid_drive(c, s, h, np.zeros_like(h)))
        for c, s, w in zip(cs, sn, wt, strict=True)
    )


def fit_preisach_astroid(h_peak, phi_r, coercivity_a_m, coating_m, orientation):
    """`tape_fit.fit_preisach` with the astroid drive in the B-H meter's loops (its along_x
    swapped for `along_x_astroid` while it fits)."""
    from varimu.devices import tape_fit

    original = tape_fit.along_x
    tape_fit.along_x = along_x_astroid
    try:
        return tape_fit.fit_preisach(
            h_peak, phi_r, coercivity_a_m, coating_m, orientation=orientation
        )
    finally:
        tape_fit.along_x = original


# --- 2. The record head's field against its current -------------------------------------


@dataclass(frozen=True)
class HeadLaw:
    """The record head as a magnetic circuit: the gap's reluctance g / (mu0 A_g) and the
    core's l_c / (mu0 mu A_c), efficiency eta = R_g / (R_g + R_c), the deep-gap field
    eta N I / g. mu is the core's effective permeability at its peak flux density
    B = mu0 Hg A_g / A_c (the gap's flux through the core's section): the static amplitude
    permeability `mu_static(B)` reduced by the laminations' eddy currents at the bias
    frequency (`eddy_factor`, which itself depends on mu), and by saturation toward
    bs_t. The kernel's hg (the base model's linear head, eta at B -> 0) becomes
    hg eta(B) / eta(0), B solved per sample (it depends on the field it sets). Memoryless:
    the bias peaks carry it exactly.

    reluctance_ratio: l_c A_g / (g A_c), the core path over the gap in reluctance at mu = 1
    (R_c / R_g = reluctance_ratio / mu); area_ratio: A_g / A_c (the gap face over the pole
    tips' section, where the core's flux density is highest)."""

    reluctance_ratio: float
    area_ratio: float
    f_hz: float
    lamination_m: float
    resistivity_ohm_m: float = 5.5e-7
    bs_t: float = 0.8

    def mu_eff(self, b_t: np.ndarray) -> np.ndarray:
        b_t = np.abs(np.atleast_1d(np.asarray(b_t, float)))
        mu = mumetall_mu_static(b_t)
        eddy = np.array([eddy_factor(self.f_hz, self.lamination_m, self.resistivity_ohm_m, m)
                         for m in mu])  # fmt: skip
        sat = np.clip(1.0 - (b_t / self.bs_t) ** 4, 1e-3, 1.0)
        return mu / eddy * sat

    def eta(self, b_t: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + self.reluctance_ratio / self.mu_eff(b_t))

    def table(self, h_max_a_m: float, n: int = 400) -> tuple[np.ndarray, np.ndarray]:
        """(hg_lin, hg) over 0..h_max: the law tabulated (each point's B by a fixed point)."""
        e0 = float(self.eta(np.array([1e-6]))[0])
        lin = np.linspace(0.0, h_max_a_m, n)
        out = lin.copy()
        for _ in range(100):
            new = lin * self.eta(MU0 * out * self.area_ratio) / e0
            if np.max(np.abs(new - out)) <= 1e-10 * h_max_a_m:
                out = new
                break
            out = new
        return lin, out

    def apply(self, hg: np.ndarray) -> np.ndarray:
        hg = np.asarray(hg, float)
        top = float(np.max(np.abs(hg))) if hg.size else 0.0
        if top == 0.0:
            return hg.copy()
        lin, out = self.table(1.001 * top)
        return np.sign(hg) * np.interp(np.abs(hg), lin, out)


def eddy_factor(f_hz: float, lamination_m: float, resistivity_ohm_m: float, mu_r: float) -> float:
    """|mu_static / mu_eff| of a lamination at f: the classical eddy-current reduction,
    mu_eff / mu = tanh(z) / z, z = (1 + j) d / (2 delta) (Bozorth, "Ferromagnetism", 1951,
    ch. 17)."""
    delta = math.sqrt(resistivity_ohm_m / (math.pi * f_hz * MU0 * mu_r))
    z = (1 + 1j) * lamination_m / (2.0 * delta)
    return float(abs(z / np.tanh(z)))


def mumetall_mu_static(b_t: np.ndarray) -> np.ndarray:
    """mumetall's static amplitude permeability against its peak flux density: the
    digitized final-annealed curve (data/datasheets/matthey_mumetall_mu_a.csv, Matthey /
    Vacuumschmelze, mu_a against H, 0.11-590 A/m), B = mu0 mu_a H; held at its ends."""
    from varimu.devices.fit import load_csv

    rows = load_csv("matthey_mumetall_mu_a.csv")
    h, mu = rows[:, 0], rows[:, 1]
    b = MU0 * mu * h
    order = np.argsort(b)
    b_t = np.atleast_1d(np.asarray(b_t, float))
    return np.interp(b_t, b[order], mu[order])


# --- 3. The easy axes in 3D -----------------------------------------------------------


@dataclass(frozen=True)
class Orientation3D:
    """Easy axes on the sphere, density exp(kappa u_x^2 - lam u_y^2) (a Bingham
    distribution: kappa concentrates them along the tape, lam > 0 keeps them out of the
    depth direction, toward the tape's plane). u = (cos t, sin t cos p, sin t sin p): Gauss-
    Legendre in cos t over [0, 1] (axial: u and -u are one axis), midpoints in p over
    [0, pi) (p and -p give one (u_x, u_y)). axes() as `tape.Orientation.axes`: (u_x, u_y,
    weight), the first two not unit (see the module docs)."""

    kappa: float
    lam: float = 0.0
    n_t: int = 4
    n_p: int = 6

    def axes(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        xg, wg = np.polynomial.legendre.leggauss(self.n_t)
        ct = 0.5 * (xg + 1.0)  # cos t over (0, 1)
        wct = 0.5 * wg
        p = (np.arange(self.n_p) + 0.5) * math.pi / self.n_p
        ct, p = np.meshgrid(ct, p, indexing="ij")
        w = np.broadcast_to(wct[:, None], ct.shape)
        st = np.sqrt(1.0 - ct * ct)
        ux, uy = ct, st * np.cos(p)
        dens = np.exp(self.kappa * (ux * ux - 1.0) - self.lam * uy * uy)
        wt = (w * dens).ravel()
        return ux.ravel(), uy.ravel(), wt / wt.sum()

    def ratios(self) -> dict:
        """The orientation's remanence ratios for an ideal (square) particle: <|u_x|>,
        <|u_y|>, <|u_z|> (a saturated-then-released ensemble's remanence along each
        direction, per Ms), and the orientation ratio <|u_x|> / <|u_z|> (longitudinal over
        transverse, as tape makers quote it)."""
        xg, wg = np.polynomial.legendre.leggauss(64)
        ct = 0.5 * (xg + 1.0)
        p = (np.arange(256) + 0.5) * math.pi / 256
        ct, p = np.meshgrid(ct, p, indexing="ij")
        w = np.broadcast_to(0.5 * wg[:, None], ct.shape)
        st = np.sqrt(1.0 - ct * ct)
        ux, uy, uz = ct, st * np.cos(p), st * np.sin(p)
        dens = w * np.exp(self.kappa * (ux * ux - 1.0) - self.lam * uy * uy)
        dens = dens / dens.sum()
        r = {k: float((dens * np.abs(u)).sum()) for k, u in (("x", ux), ("y", uy), ("z", uz))}
        r["or_xz"] = r["x"] / r["z"]
        return r


def inplane_ratios(kappa: float) -> dict:
    """`Orientation3D.ratios` for the base model's in-plane (x-y) distribution."""
    phi = -math.pi / 2 + (np.arange(4096) + 0.5) * math.pi / 4096
    w = np.exp(kappa * (np.cos(2 * phi) - 1.0))
    w = w / w.sum()
    return {
        "x": float((w * np.abs(np.cos(phi))).sum()),
        "y": float((w * np.abs(np.sin(phi))).sum()),
        "z": 0.0,
    }


# --- 6. The exact record gap (Westmijze's head) -----------------------------------------
#
# docs/TAPE_HEAD_RESEARCH.md 1.3 and 1.6: the base model's head is Karlqvist's, a potential
# falling linearly across the gap's mouth. The exact field of the same head (infinitely
# permeable poles, square corners, the gap running deep: Westmijze, Philips Res. Rep. 8,
# 1953) maps from the upper w half-plane by Schwarz-Christoffel,
#     z(w) = g/2 + (g / pi) [s(w) - arccos(1 / w)],   s(w) = sqrt(w - 1) sqrt(w + 1),
#     Hx - i Hy = i Hg / s(w),
# w = +-1 the corners, w -> 0 the gap's depth (Hx -> Hg). It replaces only the gap's term:
# the pole faces' finite length and their relaxation (the contour) stay the base model's
# (`tape.head_field`), whose gap term is that ramp's field. No free parameter. Each point is
# found by Newton on z(w) = x + iy (circuitsim's `tape::exact_gap_w` the port, warm-started
# along its tables).

#: Newton's tolerance on |z(w) - z| / (g + |z|) and its iteration limit (as circuitsim's).
EXACT_GAP_TOL = 1e-14
EXACT_GAP_ITER = 100


def _sc_s(w):
    return np.sqrt(w - 1.0) * np.sqrt(w + 1.0)


def _sc_z(w, g: float):
    u = 1.0 / w
    acos = -1j * np.log(u + 1j * np.sqrt(1.0 - u * u))  # arccos(1 / w), principal branches
    return g / 2.0 + (g / math.pi) * (_sc_s(w) - acos)


def exact_gap_w(g: float, x, y) -> np.ndarray:
    """The map's preimage w of z = x + iy (y > 0), for the gap g."""
    z = np.asarray(x, float) + 1j * np.asarray(y, float)
    w = np.pi * z / g
    w = np.where(w.imag < 1e-3, w.real + 1e-3j, w)
    for _ in range(EXACT_GAP_ITER):
        f = _sc_z(w, g) - z
        todo = np.abs(f) > EXACT_GAP_TOL * (g + np.abs(z))
        if not todo.any():
            return w
        step = f / ((g / math.pi) * _sc_s(w) / w)
        lam = np.ones(w.shape)
        wn = w - step
        for _ in range(60):  # halve until in the upper half plane and |f| falls
            bad = todo & ((wn.imag <= 0.0) | (np.abs(_sc_z(wn, g) - z) >= np.abs(f)))
            if not bad.any():
                break
            lam = np.where(bad, 0.5 * lam, lam)
            wn = np.where(bad, w - lam * step, wn)
        w = np.where(todo, wn, w)
    raise ValueError("exact_gap_w: Newton didn't converge")


def exact_gap_field(g: float, x, y) -> tuple[np.ndarray, np.ndarray]:
    """(Hx, Hy) / Hg of the gap's term alone (semi-infinite poles), y > 0; Hy positive away
    from the head, as `tape.head_field`'s."""
    h = 1j / _sc_s(exact_gap_w(g, x, y))
    return h.real, -h.imag


def _edges(head, x, y):
    """`tape.head_field`'s pole-edge terms (its sum less the gap's), as Hx - i Hy."""
    z = x + 1j * y
    g, p, r = head.gap_m, head.pole_m, head.relax_m
    e = g / 2.0 + p
    if r <= 0.0:
        acc = (g / 2.0) / (z + e) + (g / 2.0) / (z - e)
    else:
        c = g / 2.0 / r
        acc = c * (np.log(z + e + r) - np.log(z + e)) + c * (np.log(z - e) - np.log(z - e - r))
    return -(1j / math.pi) * acc


def exact_head_field(head, x, y) -> tuple[np.ndarray, np.ndarray]:
    """`tape.head_field` with the gap's term exact (Westmijze's head with the base model's
    finite poles)."""
    x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
    gx, gy = exact_gap_field(head.gap_m, x, y)
    w = _edges(head, x, y)
    return gx + w.real, gy - w.imag


def exact_head_hx(head, x, y) -> np.ndarray:
    return exact_head_field(head, x, y)[0]


@contextlib.contextmanager
def exact_gap_head():
    """Inside the block, varimu.devices.tape's record head (its recordings' field and
    zones, the Python reference's and the zones handed to the kernel) is Westmijze's
    exact gap; `variant_kernel(exact_gap=True)` tells circuitsim's kernel the same."""
    saved = tape_mod.head_field, tape_mod.head_hx
    tape_mod._ZONE_TABLES.clear()
    tape_mod.head_field, tape_mod.head_hx = exact_head_field, exact_head_hx
    try:
        yield
    finally:
        tape_mod.head_field, tape_mod.head_hx = saved
        tape_mod._ZONE_TABLES.clear()


# --- The kernel with the options --------------------------------------------------------

#: What the last kernel calls were given (tests: `record_reference` reruns them).
CAPTURE: list[dict] = []


@contextlib.contextmanager
def variant_kernel(
    mean_field: float = 0.0,
    ms_a_m: float | None = None,
    threads: int = 0,
    head_law: HeadLaw | None = None,
    capture: bool = False,
    astroid: bool = False,
    exact_gap: bool = False,
):
    """Inside the block, varimu.devices.tape's Rust kernel call (`_record_rust`) runs with
    the moving model's mean field (alpha, with the tape's Ms), at most `threads` threads
    (0: every core), the head's field mapped by `head_law`, with `astroid` each axis
    driven by `astroid_drive`, and with `exact_gap` the record head's gap exact
    (`exact_gap_head`, the zones too). capture: keep each call's inputs in CAPTURE."""
    if mean_field != 0.0 and not ms_a_m:
        raise ValueError("the mean field needs the tape's Ms")
    import circuitsim

    original = tape_mod._record_rust

    def patched(
        pre, head, slab, srec, hg, s_cells, zones, h_static, vector, axes, h_end=None,
        table_step=0.0,
    ):  # fmt: skip
        heights = slab.spacing_m + slab.depths_m
        p = pre.p
        if head_law is not None:
            hg = head_law.apply(hg)

        def flat(h):
            if h is None:
                return None, None
            if isinstance(h, tuple):
                return tuple(np.ascontiguousarray(a, float).ravel() for a in h)
            return np.ascontiguousarray(h, float).ravel(), None

        hx, hy = flat(h_static)
        ex, ey = flat(h_end)
        if hx is not None and hy is None:
            hy = np.zeros_like(hx)
        if ex is not None and ey is None:
            ey = np.zeros_like(ex)
        kw = dict(
            preisach=(p.hc_median_a_m, p.sigma_ln_hc, p.sigma_hi_a_m, p.h_max_a_m, p.n_table),
            head=(head.gap_m, head.pole_m, head.relax_m),
            heights=np.ascontiguousarray(heights, float),
            zones=np.ascontiguousarray(zones, float).ravel(),
            s_rec=np.ascontiguousarray(srec, float),
            hg=np.ascontiguousarray(hg, float),
            s_cells=np.ascontiguousarray(s_cells, float),
            axes=np.ascontiguousarray(axes, float).ravel(),
        )
        if capture:
            CAPTURE.append(
                kw
                | {
                    "pre": pre,
                    "axes": [tuple(r) for r in np.asarray(axes, float)],
                    "h_static": (hx, hy),
                    "h_end": (ex, ey),
                    "table_step": table_step,
                    "exact_gap": exact_gap,
                }
            )
        mx, my = circuitsim.tape_record(
            *kw.values(),
            hx,
            hy,
            ex,
            ey,
            table_step,
            False,
            threads,
            mean_field,
            ms_a_m or 0.0,
            astroid,
            exact_gap,
        )
        shape = (slab.layers, len(s_cells))
        mx, my = np.asarray(mx).reshape(shape), np.asarray(my).reshape(shape)
        return (mx, my) if vector else mx

    tape_mod._record_rust = patched
    try:
        with exact_gap_head() if exact_gap else contextlib.nullcontext():
            yield
    finally:
        tape_mod._record_rust = original


@contextlib.contextmanager
def static_mean_field(alpha: float, ms_a_m: float):
    """Inside the block, the recorded pattern's own field in the medium's self-consistent
    demagnetization (`record_demagnetized_vector` with the head's image, as the machines
    record) also carries the mean field alpha Ms M of each cell's recorded magnetization:
    the moving model's term frozen at the remanence (the literature study's "carried inside
    the existing demagnetization fixed point"), where `variant_kernel(mean_field=)` follows
    M through every bias cycle."""
    original = tape_mod.demag_fields_vector
    a = alpha * ms_a_m

    def patched(mx, my, *args, **kwargs):
        out = original(mx, my, *args, **kwargs)
        return [(hx + a * mx, hy + a * my) for hx, hy in out]

    tape_mod.demag_fields_vector = patched
    try:
        yield
    finally:
        tape_mod.demag_fields_vector = original


# --- 4. Print-through from a barrier distribution (an estimate, not a medium change) ----


@dataclass(frozen=True)
class PrintThrough:
    """A minimal Preisach-Neel carrier of print-through (the literature study's section
    3.4; TAPE_PLAN.md "Later"). The particles' barriers kappa = K V / kT are lognormal
    (median kappa_median at t0_k, log spread sigma_ln: the volume's), kappa proportional to
    V. A particle is thermally active over a time t at temperature T when kappa T0 / T <
    ln(f0 t / ln 2) (Neel; K's own temperature dependence left out); an active particle sits
    in equilibrium in the field there, its moment along its axis tanh(2 kappa_T H cos / H0)
    (mu0 Ms_p V / kT = 2 kappa / H0: kappa = mu0 Ms_p H0 V / (2 kT), the switching study's
    convention, H0 the athermal switching field). Inactive ones keep what they had. So the
    neighbouring turn's stray field prints into the active tail, and the print decays once
    the turns part (its particles re-equilibrate in no field) as fast as it grew.

    packing_ms_a_m: the coating's particle magnetization (packing x Ms_p); cos2_x / cos2_y:
    <cos^2> of the axes along x / y (the orientation)."""

    kappa_median: float
    sigma_ln: float
    h0_a_m: float
    packing_ms_a_m: float
    cos2_x: float
    cos2_y: float
    f0_hz: float = 1e9
    t0_k: float = 293.15

    def _kappas(self, n: int = 4001) -> tuple[np.ndarray, np.ndarray]:
        z = np.linspace(-8.0, 8.0, n)
        k = self.kappa_median * np.exp(self.sigma_ln * z)
        w = np.exp(-0.5 * z * z)
        return k, w / w.sum()

    def threshold(self, t_s: float, temp_k: float) -> float:
        """The largest barrier (at t0_k) active within t_s at temp_k."""
        return math.log(self.f0_hz * t_s / math.log(2.0)) * temp_k / self.t0_k

    def printed(self, h_a_m: float, t_s: float, temp_k: float, apart_s: float = 0.0) -> tuple:
        """(M_x, M_y) per unit field component (A/m printed per A/m of stray field, the
        field h_a_m's amplitude setting the tanh's level) after t_s in contact at temp_k,
        then apart_s apart at t0_k (those active within apart_s relax)."""
        k, w = self._kappas()
        active = k < self.threshold(t_s, temp_k)
        if apart_s > 0.0:
            active &= k >= self.threshold(apart_s, self.t0_k)
        kt = k * self.t0_k / temp_k

        def resp(c2):
            # The axis at the field's angle: <tanh(x cos) cos> over a cos^2 of c2, by its
            # rms cosine (the linear regime exact).
            c = math.sqrt(c2)
            x = 2.0 * kt * h_a_m * c / self.h0_a_m
            return float((w * active * np.tanh(x) * c).sum()) * self.packing_ms_a_m / h_a_m

        return resp(self.cos2_x), resp(self.cos2_y)


def print_ratio_db(
    pt: PrintThrough,
    m0_a_m: float,
    lam_m: float,
    coating_m: float,
    base_m: float,
    t_s: float,
    temp_k: float = 293.15,
    apart_s: float = 0.0,
    sense: int = 1,
) -> float:
    """The printed signal over the master (dB), read by the same reproducer: the master a
    pattern M0 cos(k x) uniform through its coating; its field through the base (the outer
    turn: separated by the base only, Sound Talk No. 38) H(z) = (M0 / 2)(1 - e^{-k delta})
    e^{-k z} in both components (in quadrature); the print chi_x Hx + chi_y Hy into the
    neighbour's coating from the face toward the master, which is the face a reproducer
    reads (oxide-in wind). Its longitudinal and perpendicular parts read with the same depth
    weight e^{-k y} and add for one side (sense 1: the pre-print of a tails-out reel ... the
    worse side) and subtract for the other (sense -1)."""
    k = 2.0 * math.pi / lam_m
    h_face = 0.5 * m0_a_m * (1.0 - math.exp(-k * coating_m)) * math.exp(-k * base_m)
    cx, cy = pt.printed(h_face, t_s, temp_k, apart_s)
    # Depth weights over the coating: the print falls as e^{-k y} into it, read as e^{-k y}.
    read_print = (1.0 - math.exp(-2.0 * k * coating_m)) / (2.0 * k)
    read_master = (1.0 - math.exp(-k * coating_m)) / k
    chi = cx + sense * cy
    return 20.0 * math.log10(abs(chi) * h_face / m0_a_m * read_print / read_master + 1e-300)

"""The tone bar assembly as finite elements: the tine, its tuning spring, the tone bar and
the block that joins them, on the grommets of the tone bar rail (docs/RHODES_PLAN.md, RH1).

**The plane.** Everything moves in the vertical plane through the tine (the hammer's
direction; the second polarization is RH5's): x along the tine from its clamped root at the
tone generator's inside face (where the service manual's cutting chart measures from), w
vertical, up positive (the hammer strikes upwards).

**Beams** are Euler-Bernoulli with cubic Hermite elements (w, w' per node), each element's
EI and rho A taken at its middle (the tine's tapered root in short elements). Shear and
rotary inertia are left out (the tine is slender: 1.5 mm across, 18-157 mm long; the
first-mode error of Euler-Bernoulli is ~(d / L)^2, under 1%), and so is the large-swing
nonlinearity (a cantilever's free tip lets it shorten instead of stretching: second order,
RH5 measures it).

**The block** (the tone generator with the tone bar's root screwed to it) is a rigid body
with two degrees of freedom at the tine's root: its vertical motion w_b and rotation
theta_b. The tine's root and the tone bar's root are slaved to it (w = w_b + theta_b dx,
w' = theta_b), and it sits on the grommets: vertical springs with dashpots at their x.

**Losses.** The damping matrix is the grommets' dashpots (rubber), the steel's own loss in
both beams and the tine's own losses besides (its pressed-in root, the air), each stiffness
proportional (`eta / omega_ref K`: the loss factor eta at the tine's fundamental, rising
with frequency above it, so the bell partials die fast). `fit_tine_loss` sets the tine's
so its fundamental decays at a measured Q. (Setting that Q through the grommets instead
took dashpots ~200x critical in the bass: the tine's sustain isn't the mount's.)

**Modes** are those of the undamped system (mass normalized), with decay rates from the
damping matrix's diagonal projection, `sigma_k = phi_k' C phi_k / 2` (light damping: the Qs
are in the thousands for the tine's fundamental). The full damped system is the reference
(`key.py`): it keeps the off-diagonal terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from scipy import linalg, optimize


@dataclass(frozen=True)
class Section:
    """A run of the tine: length and the diameters at its ends (a linear taper)."""

    length_m: float
    d_start_m: float
    d_end_m: float


@dataclass(frozen=True)
class ToneBar:
    length_m: float
    thickness_m: float  # in the plane of vibration
    width_m: float
    youngs_pa: float
    density_kg_m3: float
    root_dx_m: float  # its root's x from the tine's root


@dataclass(frozen=True)
class Assembly:
    tine: tuple[Section, ...]
    tine_youngs_pa: float
    tine_density_kg_m3: float
    spring_mass_kg: float
    spring_length_m: float
    spring_x_m: float  # the spring's centre, from the tine's root
    tonebar: ToneBar | None
    block_mass_kg: float
    block_inertia_kg_m2: float  # about its centre
    block_x_m: float  # its centre's x from the tine's root
    grommet_x_m: tuple[float, ...]
    grommet_k_n_m: float  # each
    grommet_c_n_s_m: float  # each
    steel_loss: float  # eta of the beams
    loss_ref_hz: float  # where the losses' eta are exact
    tine_loss: float = 0.0  # eta of the tine's own losses besides the steel's (its root, air)
    damper_x_m: float = 0.0  # where the damper's felt presses on the tine
    damper_c_n_s_m: float = 0.0  # the felt as a dashpot there (0: the damper lifted)

    @property
    def tine_length_m(self) -> float:
        return sum(s.length_m for s in self.tine)


@dataclass(frozen=True)
class FE:
    m: np.ndarray
    k: np.ndarray
    c: np.ndarray
    tine_x_m: np.ndarray  # node positions along the tine (root excluded)
    tine_dofs: np.ndarray  # (n, 2): w and w' of each tine node
    bar_dofs: np.ndarray  # (n, 2) for the tone bar's nodes (empty without one)
    bar_x_m: np.ndarray
    asm: Assembly = field(repr=False)
    k_tine: np.ndarray | None = field(default=None, repr=False)  # the tine's own stiffness
    k_beams: np.ndarray | None = field(default=None, repr=False)  # tine's and bar's

    @property
    def n(self) -> int:
        return self.m.shape[0]

    def tine_point(self, x_m: float, slope: bool = False) -> np.ndarray:
        """The row vector giving the tine's w (or w') at x from the dofs."""
        return _point(self, x_m, slope)

    @property
    def tip(self) -> np.ndarray:
        return self.tine_point(self.asm.tine_length_m)


@dataclass(frozen=True)
class Modes:
    f_hz: np.ndarray
    omega: np.ndarray
    sigma: np.ndarray  # amplitude decay rate, 1/s
    phi: np.ndarray  # (n_dof, n_modes), mass normalized

    @property
    def q(self) -> np.ndarray:
        return self.omega / (2 * self.sigma)


def _beam_element(h: float, ei: float, rho_a: float) -> tuple[np.ndarray, np.ndarray]:
    k = (ei / h**3) * np.array(
        [
            [12, 6 * h, -12, 6 * h],
            [6 * h, 4 * h * h, -6 * h, 2 * h * h],
            [-12, -6 * h, 12, -6 * h],
            [6 * h, 2 * h * h, -6 * h, 4 * h * h],
        ]
    )
    m = (rho_a * h / 420) * np.array(
        [
            [156, 22 * h, 54, -13 * h],
            [22 * h, 4 * h * h, 13 * h, -3 * h * h],
            [54, 13 * h, 156, -22 * h],
            [-13 * h, -3 * h * h, -22 * h, 4 * h * h],
        ]
    )
    return k, m


def hermite(xi: float, h: float, slope: bool = False) -> np.ndarray:
    """Cubic Hermite shape functions (w0, w0', w1, w1') at xi in [0, 1] of an element of
    length h, or their x derivatives."""
    if slope:
        return np.array(
            [
                (-6 * xi + 6 * xi * xi) / h,
                1 - 4 * xi + 3 * xi * xi,
                (6 * xi - 6 * xi * xi) / h,
                -2 * xi + 3 * xi * xi,
            ]
        )
    return np.array(
        [
            1 - 3 * xi**2 + 2 * xi**3,
            h * (xi - 2 * xi**2 + xi**3),
            3 * xi**2 - 2 * xi**3,
            h * (-(xi**2) + xi**3),
        ]
    )


def _tine_mesh(asm: Assembly, max_el_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Node positions (root at 0) and each element's middle diameter. A node falls on the
    spring's ends and every section boundary."""
    marks = [0.0]
    for s in asm.tine:
        marks.append(marks[-1] + s.length_m)
    length = marks[-1]
    half = asm.spring_length_m / 2
    if asm.spring_mass_kg > 0:
        marks += [max(asm.spring_x_m - half, 0.0), min(asm.spring_x_m + half, length)]
    marks = np.unique(np.round(marks, 12))
    # merge marks closer than 10 um (a sliver element makes the matrices singular)
    keep = np.concatenate([[True], np.diff(marks) > 1e-5])
    marks = marks[keep]
    marks[-1] = length
    xs = [0.0]
    for a, b in zip(marks[:-1], marks[1:], strict=True):
        n = max(1, int(np.ceil((b - a) / max_el_m)))
        xs += list(np.linspace(a, b, n + 1)[1:])
    xs = np.array(xs)
    mid = 0.5 * (xs[:-1] + xs[1:])
    d = np.array([_diameter(asm, x) for x in mid])
    return xs, d


def _diameter(asm: Assembly, x: float) -> float:
    start = 0.0
    for s in asm.tine:
        if x <= start + s.length_m:
            t = (x - start) / s.length_m
            return s.d_start_m + t * (s.d_end_m - s.d_start_m)
        start += s.length_m
    return asm.tine[-1].d_end_m


def assemble(asm: Assembly, max_el_m: float = 2e-3) -> FE:
    xs, d = _tine_mesh(asm, max_el_m)
    n_t = xs.size - 1  # tine nodes besides the root
    if asm.tonebar is not None:
        tb = asm.tonebar
        n_b = max(4, int(np.ceil(tb.length_m / (2 * max_el_m))))  # the bar is stiffer
        xb = np.linspace(0, tb.length_m, n_b + 1)
    else:
        n_b, xb = 0, np.zeros(1)
    n = 2 + 2 * n_t + 2 * n_b
    m = np.zeros((n, n))
    k_el = np.zeros((n, n))
    tine_dofs = np.arange(2, 2 + 2 * n_t).reshape(n_t, 2)
    bar_dofs = np.arange(2 + 2 * n_t, n).reshape(n_b, 2)

    def root_map(dx: float) -> np.ndarray:
        """(2 x n): a beam root at dx from the block's reference, slaved to (w_b, theta_b)."""
        t = np.zeros((2, n))
        t[0, 0], t[0, 1], t[1, 1] = 1.0, dx, 1.0
        return t

    def node_map(dofs: np.ndarray, i: int, root: np.ndarray) -> np.ndarray:
        if i == 0:
            return root
        t = np.zeros((2, n))
        t[0, dofs[i - 1, 0]] = 1.0
        t[1, dofs[i - 1, 1]] = 1.0
        return t

    e, rho = asm.tine_youngs_pa, asm.tine_density_kg_m3
    root_t = root_map(0.0)
    for i in range(n_t):
        h = xs[i + 1] - xs[i]
        ke, me = _beam_element(h, e * np.pi * d[i] ** 4 / 64, rho * np.pi * d[i] ** 2 / 4)
        t = np.vstack([node_map(tine_dofs, i, root_t), node_map(tine_dofs, i + 1, root_t)])
        k_el += t.T @ ke @ t
        m += t.T @ me @ t
    k_tine = k_el.copy()
    if asm.tonebar is not None:
        tb = asm.tonebar
        root_b = root_map(tb.root_dx_m)
        ei = tb.youngs_pa * tb.width_m * tb.thickness_m**3 / 12
        rho_a = tb.density_kg_m3 * tb.width_m * tb.thickness_m
        for i in range(n_b):
            ke, me = _beam_element(xb[i + 1] - xb[i], ei, rho_a)
            t = np.vstack([node_map(bar_dofs, i, root_b), node_map(bar_dofs, i + 1, root_b)])
            k_el += t.T @ ke @ t
            m += t.T @ me @ t

    # the block: a rigid body at block_x
    xb_c = asm.block_x_m
    mb, jb = asm.block_mass_kg, asm.block_inertia_kg_m2
    m[:2, :2] += np.array([[mb, mb * xb_c], [mb * xb_c, mb * xb_c**2 + jb]])
    # the grommets
    k_g = np.zeros((n, n))
    for xg in asm.grommet_x_m:
        v = np.zeros(n)
        v[0], v[1] = 1.0, xg
        k_g += np.outer(v, v)
    fe_partial = FE(m, k_el, k_g, xs[1:], tine_dofs, bar_dofs, xb[1:], asm)

    # the tuning spring: a short uniform sleeve (its mass and rotary inertia spread
    # over its length, consistent with the beam's shape functions)
    if asm.spring_mass_kg > 0:
        lo = max(asm.spring_x_m - asm.spring_length_m / 2, 0.0)
        hi = min(asm.spring_x_m + asm.spring_length_m / 2, asm.tine_length_m)
        g, w = np.polynomial.legendre.leggauss(6)
        xq = 0.5 * (hi - lo) * (g + 1) + lo
        wq = 0.5 * (hi - lo) * w
        rho_l = asm.spring_mass_kg / (hi - lo)
        for x, wt in zip(xq, wq, strict=True):
            v = _point(fe_partial, x, False)
            m += rho_l * wt * np.outer(v, v)

    w_ref = 2 * np.pi * asm.loss_ref_hz
    c = (asm.steel_loss / w_ref) * k_el + (asm.tine_loss / w_ref) * k_tine
    c += asm.grommet_c_n_s_m * k_g
    k = k_el + asm.grommet_k_n_m * k_g
    fe = FE(m, k, c, xs[1:], tine_dofs, bar_dofs, xb[1:], asm, k_tine, k_el)
    if asm.damper_c_n_s_m > 0:
        v = _point(fe, asm.damper_x_m, False)
        fe = replace(fe, c=c + asm.damper_c_n_s_m * np.outer(v, v))
    return fe


def _point(fe: FE, x_m: float, slope: bool) -> np.ndarray:
    xs = np.concatenate([[0.0], fe.tine_x_m])
    x_m = float(np.clip(x_m, 0.0, xs[-1]))
    i = int(np.clip(np.searchsorted(xs, x_m, side="right") - 1, 0, xs.size - 2))
    h = xs[i + 1] - xs[i]
    shape = hermite((x_m - xs[i]) / h, h, slope)
    v = np.zeros(fe.n)
    for j, (a, b) in enumerate(((i, 0), (i, 1), (i + 1, 0), (i + 1, 1))):
        if a == 0:
            # the root: slaved to the block (w = w_b, w' = theta_b at dx = 0)
            if b == 0:
                v[0] += shape[j]
            else:
                v[1] += shape[j]
        else:
            v[fe.tine_dofs[a - 1, b]] += shape[j]
    return v


def modes(fe: FE, f_max_hz: float | None = None, count: int | None = None) -> Modes:
    """The undamped modes below f_max_hz (all without it), or only the lowest `count`."""
    sub = None if count is None else [0, min(count, fe.n) - 1]
    lam, phi = linalg.eigh(fe.k, fe.m, subset_by_index=sub)
    lam = np.maximum(lam, 0.0)
    omega = np.sqrt(lam)
    keep = slice(None) if f_max_hz is None else omega / (2 * np.pi) <= f_max_hz
    omega, phi = omega[keep], phi[:, keep]
    sigma = 0.5 * np.einsum("ik,ij,jk->k", phi, fe.c, phi)
    return Modes(omega / (2 * np.pi), omega, sigma, phi)


def tine_mode(fe: FE, md: Modes, near_hz: float | None = None) -> int:
    """The tine's fundamental: the lowest mode with most of its strain energy in the tine
    (`phi' K_tine phi / omega^2` over 1/2: the block bouncing or rocking on the grommets
    stores it there, the tone bar's own modes in the bar). `near_hz` is accepted for the
    callers' symmetry; the energy test doesn't need it."""
    share = np.einsum("ik,ij,jk->k", md.phi, fe.k_tine, md.phi) / np.maximum(md.omega, 1e-9) ** 2
    tine = np.flatnonzero(share > 0.5)
    if tine.size == 0:
        raise ValueError("no mode has most of its strain energy in the tine")
    return int(tine[np.argmin(md.f_hz[tine])])


def mount_mode(fe: FE, md: Modes) -> int:
    """The struck bar's lowest resonance on its mount (what an impulse hammer on the bar
    shows: Muenster & Pfeifle's measurement): the lowest mode with most of its strain
    energy outside the tine (in the grommets, pitching or bouncing, and the bar; in the
    bass the two mix)."""
    tine = np.einsum("ik,ij,jk->k", md.phi, fe.k_tine, md.phi) / np.maximum(md.omega, 1e-9) ** 2
    other = np.flatnonzero(tine < 0.5)
    if other.size == 0:
        raise ValueError("every mode solved has most of its strain energy in the tine")
    return int(other[np.argmin(md.f_hz[other])])


def fundamental_hz(asm: Assembly, near_hz: float | None = None) -> float:
    fe = assemble(asm)
    md = modes(fe, count=12)
    return float(md.f_hz[tine_mode(fe, md, near_hz)])


def tune(asm: Assembly, f_hz: float, margin_m: float = 0.5e-3) -> Assembly:
    """The spring slid along the tine until the tine's fundamental is f_hz (outwards
    lowers it). Raises ValueError when no position on the tine reaches it."""
    half = asm.spring_length_m / 2
    lo = half + margin_m
    hi = asm.tine_length_m - half

    def err(x: float) -> float:
        return np.log(fundamental_hz(replace(asm, spring_x_m=x), f_hz) / f_hz)

    e_lo, e_hi = err(lo), err(hi)
    if e_lo < 0 or e_hi > 0:
        raise ValueError(
            f"untunable: {f_hz:.2f} Hz is outside the spring's reach "
            f"({f_hz * np.exp(e_hi):.2f}-{f_hz * np.exp(e_lo):.2f} Hz)"
        )
    x = optimize.brentq(err, lo, hi, xtol=1e-7)
    return replace(asm, spring_x_m=x)


def damped_q(asm: Assembly, f_hz: float) -> float:
    """The tine's fundamental's Q in the damped system (the state matrix's eigenvalue
    nearest it: the damping's off-diagonal terms kept)."""
    fe = assemble(asm)
    md = modes(fe, count=12)
    w = md.omega[tine_mode(fe, md, f_hz)]
    n = fe.n
    minv = np.linalg.inv(fe.m)
    a = np.zeros((2 * n, 2 * n))
    a[:n, n:] = np.eye(n)
    a[n:, :n] = -minv @ fe.k
    a[n:, n:] = -minv @ fe.c
    lam = linalg.eigvals(a)
    lam = lam[lam.imag > 0]
    near = lam[np.argmin(np.abs(lam.imag - w))]
    return float(abs(near.imag) / (-2 * near.real))


def fit_tine_loss(asm: Assembly, f_hz: float, q: float) -> Assembly:
    """The tine's own loss (stiffness proportional on the tine, eta at `loss_ref_hz`) set so
    its fundamental (near f_hz) has the quality factor q in the damped system: first by the
    modes' diagonal decay rates, then a secant on the exact eigenvalue. 0 if the rest
    already decays it faster."""
    fe = assemble(replace(asm, tine_loss=0.0))
    md = modes(fe, count=12)
    k = tine_mode(fe, md, f_hz)
    phi = md.phi[:, k]
    sigma_target = md.omega[k] / (2 * q)
    rest = 0.5 * phi @ fe.c @ phi
    per = 0.5 * phi @ fe.k_tine @ phi / (2 * np.pi * asm.loss_ref_hz)
    eta = max(0.0, (sigma_target - rest) / per)
    if eta == 0.0:
        # the diagonal estimate says the rest damps it enough; the exact Q may disagree
        if damped_q(replace(asm, tine_loss=0.0), f_hz) <= q:
            return replace(asm, tine_loss=0.0)
        eta = 1e-6

    def err(e: float) -> float:  # decay rates are ~linear in the loss: 1 / Q
        return 1.0 / damped_q(replace(asm, tine_loss=e), f_hz) - 1.0 / q

    e0, e1 = eta, eta * 1.1
    r0, r1 = err(e0), err(e1)
    for _ in range(8):
        if abs(r1) < 1e-3 / q or r1 == r0:
            break
        e0, e1, r0 = e1, max(0.0, e1 - r1 * (e1 - e0) / (r1 - r0)), r1
        r1 = err(e1)
    return replace(asm, tine_loss=float(e1))


def total_mass_kg(fe: FE) -> float:
    """The assembly's mass: the mass matrix applied to a rigid vertical translation."""
    rigid = np.zeros(fe.n)
    rigid[0] = 1.0
    rigid[fe.tine_dofs[:, 0]] = 1.0
    if fe.bar_dofs.size:
        rigid[fe.bar_dofs[:, 0]] = 1.0
    return float(rigid @ fe.m @ rigid)

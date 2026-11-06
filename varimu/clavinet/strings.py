"""A key's string as two substructures joined at the anvil, released and held
(docs/CLAVINET_PLAN.md, CL1, "The string" and "The release").

**Substructures (Craig-Bampton, numeric).** The string runs from the tuning pin (fixed)
through the anvil to the tailpiece. Two segments, each a uniform tensioned Euler-Bernoulli
beam in Hermite cubic elements (w, w' per node):

- **S**, the speaking part, anvil to tailpiece (length L), read by the pickups;
- **N**, the non-speaking part, pin to anvil (length l), with the yarn woven over its pin
  end (added mass and a dashpot per metre).

The interface degrees of freedom are the anvil point's deflection w_a **and slope**
theta_a (the wire is continuous through the pinch: bending carries motion across it), and
the tailpiece end's deflection w_t. Both ends are moment free (pinned).

Each segment's coordinates are:
- its fixed-interface modes (clamped at the anvil, held at the tailpiece or pin) up to
  `f_cut_hz`, mass-normalized, by a sparse eigensolve;
- the static constraint modes of its interface DOFs.

The basis is computed once per key at the nominal tension mu (2 L f)^2, without the yarn,
and used for both systems at their own tensions (a Rayleigh-Ritz basis: the reduced
stiffness is exactly Kb + T Kg projected). An earlier version used analytic sines with the
anvil as a hinge: the plain finite-element reference (`reference.py`) showed it missed the
bending path into the pinch and the yarn (decays up to 100x short of loss on the sideways
polarization).

Both transverse planes are modelled: y (the tangent's push, the pickups' vertical) and x
(across the strings, which the pickups barely see: [R12], [G13] 2.3.5). They share the
basis; per plane the coordinates are (q_S, q_N, w_a, theta_a, w_t).

**Released** (no key): the tailpiece end on a spring and dashpot to ground, nothing at the
anvil; tension `tension_rest_n`.

**Held:** the pinch at the anvil point, linearized about the static press:
- the anvil (its contact stiffness) along its face normal n, tilted by `tilt_rad` from y;
- the rubber's friction grip along the face (t, perpendicular to n);
- the tangent, a mass on the rubber (Hunt-Crossley, linearized at the hold force's
  compression), pushed by the finger's constant force.

The tension is `tension_held_n` (the string stretched by the pinch's deflection, `fit.py`).
The anvil is bilateral in the linearization, so the static state (`static`) has the string
pressed on it.

**Losses:**
- each fixed-interface mode's air drag (Valette & Cuesta's formula on the outer diameter),
  the steel's loss factor on its bending energy (its exact share, from the element
  matrices) and, on a wound string, the wrap's friction (sigma = pi f eta_wrap);
- the yarn's dashpot;
- the tailpiece's dashpot;
- the pinch's dashpots and the rubber's;
- the mute bar's felt (a spring and dashpot pressed on S near the tailpiece, both planes),
  when its slider is on.

The two systems share the coordinates, so a state moves between them exactly, through the
physical coordinates.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field

import numpy as np
from scipy import linalg, sparse
from scipy.sparse import linalg as spla

from varimu.clavinet.spec import StringGeom

ELEMENTS_PER_WAVELENGTH = 6.0  # at f_cut_hz, nominal tension
MAX_ELEMENT_M = 4e-3
GAUSS = np.polynomial.legendre.leggauss(4)


@dataclass(frozen=True)
class Params:
    """Everything a key's two systems need (spec.py's geometry, fit.py's unknowns)."""

    geom: StringGeom
    tension_rest_n: float
    tension_held_n: float
    nonspeaking_m: float
    yarn_length_m: float
    yarn_mass_kg_m: float
    yarn_damping_ns_m2: float  # N s / m per metre of yarn
    tailpiece_k_n_m: float
    tailpiece_c_ns_m: float
    anvil_gap_m: float
    anvil_k_n_m: float  # the contact (wire on stud)
    anvil_c_ns_m: float
    grip_k_n_m: float
    grip_c_ns_m: float
    tilt_rad: float
    tangent_mass_kg: float
    rubber_k: float  # Hunt-Crossley F = K d^p (1 + alpha d')
    rubber_p: float
    rubber_alpha_s_m: float
    hold_force_n: float
    air_density_kg_m3: float
    air_viscosity_pa_s: float
    eta_bend: float
    wrap_k_n_m: float = float("inf")  # the press's extra deflection beside the anvil (tension only)
    eta_wrap: float = 0.0  # a wound string's wrap friction: a loss factor on all its energy
    mute_distance_m: float = 0.02  # the mute bar's felt, from the tailpiece
    mute_k_n_m: float = 0.0  # its spring and dashpot (0: the slider off)
    mute_c_ns_m: float = 0.0
    f_cut_hz: float = 24000.0
    extra: dict = field(default_factory=dict, compare=False)

    def rubber_static(self, force_n: float | None = None) -> tuple[float, float, float]:
        """(compression, stiffness, damping) of the rubber pressed with `force_n`."""
        f = self.hold_force_n if force_n is None else force_n
        d0 = (f / self.rubber_k) ** (1 / self.rubber_p)
        k = self.rubber_p * self.rubber_k * d0 ** (self.rubber_p - 1)
        return float(d0), float(k), float(f * self.rubber_alpha_s_m)


def air_sigma(f_hz: np.ndarray, p: Params) -> np.ndarray:
    """Amplitude decay rate from air drag (Valette & Cuesta 1993, as in Chaigne &
    Askenfelt 1994): R = 2 pi eta + 2 pi d sqrt(pi eta rho f), sigma = R / (2 mu)."""
    eta, rho, d = p.air_viscosity_pa_s, p.air_density_kg_m3, p.geom.d_outer_m
    r = 2 * np.pi * eta + 2 * np.pi * d * np.sqrt(np.pi * eta * rho * np.asarray(f_hz))
    return r / (2 * p.geom.mu_kg_m)


# --- one segment in finite elements ------------------------------------------------------


def _element(h: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Hermite cubic element matrices per unit EI, unit T, unit mass per length."""
    kb = (
        np.array(
            [
                [12, 6 * h, -12, 6 * h],
                [6 * h, 4 * h * h, -6 * h, 2 * h * h],
                [-12, -6 * h, 12, -6 * h],
                [6 * h, 2 * h * h, -6 * h, 4 * h * h],
            ]
        )
        / h**3
    )
    kg = np.array(
        [
            [36, 3 * h, -36, 3 * h],
            [3 * h, 4 * h * h, -3 * h, -h * h],
            [-36, -3 * h, 36, -3 * h],
            [3 * h, -h * h, -3 * h, 4 * h * h],
        ]
    ) / (30 * h)
    m = (
        np.array(
            [
                [156, 22 * h, 54, -13 * h],
                [22 * h, 4 * h * h, 13 * h, -3 * h * h],
                [54, 13 * h, 156, -22 * h],
                [-13 * h, -3 * h * h, -22 * h, 4 * h * h],
            ]
        )
        * h
        / 420
    )
    return kb, kg, m


def hermite(xi: np.ndarray, h: float) -> np.ndarray:
    """Shape functions (4, n) at xi in [0, 1] of an element of length h."""
    xi = np.asarray(xi, float)
    return np.array(
        [
            1 - 3 * xi**2 + 2 * xi**3,
            h * (xi - 2 * xi**2 + xi**3),
            3 * xi**2 - 2 * xi**3,
            h * (-(xi**2) + xi**3),
        ]
    )


def _assemble(x: np.ndarray, weight: np.ndarray | None = None):
    """(Kb, Kg, M) of a mesh per unit EI / T / mass (sparse); `weight` per element scales M."""
    ne = x.size - 1
    n = 2 * (ne + 1)
    rows, cols, vb, vg, vm = [], [], [], [], []
    for e in range(ne):
        h = x[e + 1] - x[e]
        kb, kg, m = _element(h)
        idx = np.arange(2 * e, 2 * e + 4)
        rr, cc = np.meshgrid(idx, idx, indexing="ij")
        rows.append(rr.ravel())
        cols.append(cc.ravel())
        vb.append(kb.ravel())
        vg.append(kg.ravel())
        vm.append(m.ravel() * (1.0 if weight is None else weight[e]))
    r, c = np.concatenate(rows), np.concatenate(cols)

    def mk(v):
        return sparse.csr_matrix((np.concatenate(v), (r, c)), shape=(n, n))

    return mk(vb), mk(vg), mk(vm)


@dataclass(frozen=True)
class Segment:
    """A segment's reduction: physical DOFs d = T @ (q, u_b); its interface DOFs (indices
    into d) and the reduced matrices per unit EI / T / mass."""

    x: np.ndarray  # node positions from the segment's start
    t: np.ndarray  # (n_dof, nq + nb)
    nq: int
    boundary: tuple[int, ...]  # physical DOF indices of the interface, in order
    kb: np.ndarray  # reduced, per unit EI
    kg: np.ndarray  # per unit T
    m: np.ndarray  # per unit mass per length
    omega_nominal: np.ndarray  # the fixed-interface modes' rad/s at the nominal T
    bend_share: np.ndarray  # their bending energy's share at the nominal T

    def rows(self, xs: np.ndarray) -> np.ndarray:
        """Displacement rows (len(xs), nq + nb) at positions xs."""
        e = np.clip(np.searchsorted(self.x, xs, side="right") - 1, 0, self.x.size - 2)
        h = self.x[e + 1] - self.x[e]
        xi = (xs - self.x[e]) / h
        out = np.zeros((xs.size, self.t.shape[1]))
        for i in range(xs.size):
            nfun = hermite(np.array([xi[i]]), h[i])[:, 0]
            out[i] = nfun @ self.t[2 * e[i] : 2 * e[i] + 4]
        return out

    def matrix_on(self, x0: float, x1: float, per_m: float) -> np.ndarray:
        """Reduced int over [x0, x1] of per_m * w_i * w_j (consistent: the yarn)."""
        n = self.t.shape[1]
        out = np.zeros((n, n))
        if x1 <= x0:
            return out
        gx, gw = GAUSS
        for e in range(self.x.size - 1):
            a, b = max(self.x[e], x0), min(self.x[e + 1], x1)
            if b <= a:
                continue
            h = self.x[e + 1] - self.x[e]
            xs = 0.5 * (b - a) * (gx + 1) + a
            ws = 0.5 * (b - a) * gw
            nf = hermite((xs - self.x[e]) / h, h)  # (4, g)
            local = (nf * ws) @ nf.T
            te = self.t[2 * e : 2 * e + 4]
            out += per_m * te.T @ local @ te
        return out


@functools.lru_cache(maxsize=256)
def segment(
    length: float, ei: float, mu: float, t_nominal: float, f_cut: float, anvil_at_start: bool
) -> Segment:
    """S (anvil at the start, the tailpiece end's w an interface) or N (the pin at the
    start, held; the anvil at the end): fixed-interface modes to f_cut plus constraint modes."""
    c = np.sqrt(t_nominal / mu)
    h_max = min(MAX_ELEMENT_M, c / (f_cut * ELEMENTS_PER_WAVELENGTH))
    ne = max(int(np.ceil(length / h_max)), 8)
    x = np.linspace(0.0, length, ne + 1)
    kb, kg, m = _assemble(x)
    n = 2 * (ne + 1)
    k = ei * kb + t_nominal * kg
    mm = mu * m
    last = n - 2
    if anvil_at_start:
        boundary, fixed = (0, 1, last), ()  # w_a, theta_a, w_t
    else:
        boundary, fixed = (last, last + 1), (0,)  # w_a, theta_a; the pin's w held
    interior = np.setdiff1d(np.arange(n), np.r_[list(boundary), list(fixed)].astype(int))
    k = k.tocsc()
    mm = mm.tocsc()
    kii = k[interior][:, interior]
    mii = mm[interior][:, interior]
    kib = k[interior][:, list(boundary)].toarray()
    # how many modes: a stiff pinned string's count to f_cut, plus a margin
    kk = np.arange(1, 4000) * np.pi / length
    om = np.sqrt(kk**2 * t_nominal / mu + kk**4 * ei / mu)
    want = int(np.searchsorted(om, 2 * np.pi * f_cut)) + 6
    want = min(want, interior.size - 2)
    # rng=0: eigsh's starting vector is otherwise drawn from OS entropy on every call, and
    # the bases (with the fits and the compiled component built on them) then differed at
    # rounding from run to run (the Hard rules' reproducibility)
    lam, phi = spla.eigsh(kii, k=want, M=mii, sigma=0.0, which="LM", rng=0)
    order = np.argsort(lam)
    lam, phi = lam[order], phi[:, order]
    keep = lam <= (2 * np.pi * f_cut) ** 2 * 1.0001
    if not keep.any():
        keep[0] = True
    lam, phi = lam[keep], phi[:, keep]
    phi = phi / np.sqrt(np.einsum("ij,ij->j", phi, mii @ phi))
    psi = -spla.splu(kii).solve(kib)
    nq, nb = phi.shape[1], len(boundary)
    t = np.zeros((n, nq + nb))
    t[interior, :nq] = phi
    t[interior, nq:] = psi
    for j, b in enumerate(boundary):
        t[b, nq + j] = 1.0
    kbr = t.T @ (kb @ t)
    kgr = t.T @ (kg @ t)
    mr = t.T @ (m @ t)
    bend = ei * np.einsum("ij,ij->j", phi, kb[interior][:, interior] @ phi)
    share = bend / lam
    return Segment(x, t, nq, boundary, kbr, kgr, mr, np.sqrt(lam), share)


def segments(p: Params) -> tuple[Segment, Segment]:
    g = p.geom
    t_nom = g.mu_kg_m * (2 * g.length_m * g.f_hz) ** 2
    s = segment(g.length_m, g.ei_n_m2, g.mu_kg_m, t_nom, p.f_cut_hz, True)
    n = segment(p.nonspeaking_m, g.ei_n_m2, g.mu_kg_m, t_nom, p.f_cut_hz, False)
    return s, n


@dataclass
class Layout:
    """Coordinate indices. Per plane: q_S (ns), q_N (nn), w_a, theta_a, w_t."""

    ns: int
    nn: int

    @property
    def per_plane(self) -> int:
        return self.ns + self.nn + 3

    def qs(self, plane: int) -> slice:
        o = plane * self.per_plane
        return slice(o, o + self.ns)

    def qn(self, plane: int) -> slice:
        o = plane * self.per_plane + self.ns
        return slice(o, o + self.nn)

    def ua(self, plane: int) -> int:
        return plane * self.per_plane + self.ns + self.nn

    def tha(self, plane: int) -> int:
        return self.ua(plane) + 1

    def ut(self, plane: int) -> int:
        return self.ua(plane) + 2

    @property
    def n_string(self) -> int:
        return 2 * self.per_plane


def layout(p: Params) -> Layout:
    s, n = segments(p)
    return Layout(s.nq, n.nq)


def _s_index(lay: Layout, pl: int) -> np.ndarray:
    """S's reduced coordinates (q_S, w_a, theta_a, w_t) in the plane's global indices."""
    return np.r_[np.arange(lay.qs(pl).start, lay.qs(pl).stop), lay.ua(pl), lay.tha(pl), lay.ut(pl)]


def _n_index(lay: Layout, pl: int) -> np.ndarray:
    """N's reduced coordinates (q_N, w_a, theta_a)."""
    return np.r_[np.arange(lay.qn(pl).start, lay.qn(pl).stop), lay.ua(pl), lay.tha(pl)]


def matrices(p: Params, held: bool, lay: Layout | None = None) -> tuple[np.ndarray, ...]:
    """(M, C, K, f): the system's matrices and its constant forces (held: the static press).
    Held systems have one more coordinate, the tangent, last."""
    g = p.geom
    lay = lay or layout(p)
    seg_s, seg_n = segments(p)
    mu, ei = g.mu_kg_m, g.ei_n_m2
    tension = p.tension_held_n if held else p.tension_rest_n
    n = lay.n_string + (1 if held else 0)
    m = np.zeros((n, n))
    c = np.zeros((n, n))
    k = np.zeros((n, n))
    f = np.zeros(n)
    wrap = p.eta_wrap if g.wound else 0.0

    def modal_sigma(seg: Segment) -> np.ndarray:
        f_hz = seg.omega_nominal / (2 * np.pi)
        return air_sigma(f_hz, p) + np.pi * f_hz * (p.eta_bend * seg.bend_share + wrap)

    yarn_end = min(p.yarn_length_m, p.nonspeaking_m)
    yarn_m = seg_n.matrix_on(0.0, yarn_end, p.yarn_mass_kg_m)
    yarn_c = seg_n.matrix_on(0.0, yarn_end, p.yarn_damping_ns_m2)
    for pl in (0, 1):
        for seg, idx, extra_m, extra_c in (
            (seg_s, _s_index(lay, pl), None, None),
            (seg_n, _n_index(lay, pl), yarn_m, yarn_c),
        ):
            ii = np.ix_(idx, idx)
            m[ii] += mu * seg.m + (0 if extra_m is None else extra_m)
            k[ii] += ei * seg.kb + tension * seg.kg
            if extra_c is not None:
                c[ii] += extra_c
            q = idx[: seg.nq]
            c[q, q] += 2 * modal_sigma(seg)
        t = lay.ut(pl)
        k[t, t] += p.tailpiece_k_n_m
        c[t, t] += p.tailpiece_c_ns_m
    if p.mute_k_n_m > 0 or p.mute_c_ns_m > 0:
        for pl in (0, 1):
            r = point_rows(p, lay, pl, p.mute_distance_m, 0.0)
            r = np.concatenate([r, np.zeros(n - r.size)])
            k += p.mute_k_n_m * np.outer(r, r)
            c += p.mute_c_ns_m * np.outer(r, r)
    if held:
        ay, ax = lay.ua(0), lay.ua(1)
        nrm = np.array([np.cos(p.tilt_rad), np.sin(p.tilt_rad)])  # (y, x)
        tan = np.array([-np.sin(p.tilt_rad), np.cos(p.tilt_rad)])
        kp = p.anvil_k_n_m * np.outer(nrm, nrm) + p.grip_k_n_m * np.outer(tan, tan)
        cp = p.anvil_c_ns_m * np.outer(nrm, nrm) + p.grip_c_ns_m * np.outer(tan, tan)
        ii = np.array([ay, ax])
        k[np.ix_(ii, ii)] += kp
        c[np.ix_(ii, ii)] += cp
        f[ii] += p.anvil_k_n_m * p.anvil_gap_m * nrm
        z = n - 1
        d0, kr, cr = p.rubber_static()
        m[z, z] = p.tangent_mass_kg
        for i, j, s in ((ay, ay, 1), (z, z, 1), (ay, z, -1), (z, ay, -1)):
            k[i, j] += s * kr
            c[i, j] += s * cr
        f[ay] += p.hold_force_n - kr * d0
        f[z] += kr * d0
    return m, c, k, f


def static(p: Params) -> np.ndarray:
    """The held system's static state (the string pressed on the anvil)."""
    _, _, k, f = matrices(p, True)
    return np.linalg.solve(k, f)


@dataclass
class System:
    """x' = A x + B u in the state (displacements, velocities), and its eigensystem.
    `lam` are the eigenvalues (all of them: the basis is already truncated), `v` the
    eigenvectors, `w` = inv(v)."""

    held: bool
    lay: Layout
    m: np.ndarray
    c: np.ndarray
    k: np.ndarray
    f: np.ndarray
    lam: np.ndarray
    v: np.ndarray
    w: np.ndarray

    @property
    def n(self) -> int:
        return self.m.shape[0]

    def input(self, coord: int) -> np.ndarray:
        """Modal input vector for a unit force on a coordinate."""
        e = np.zeros(self.n)
        e[coord] = 1.0
        b = np.concatenate([np.zeros(self.n), np.linalg.solve(self.m, e)])
        return self.w @ b

    def to_modal(self, x_phys: np.ndarray) -> np.ndarray:
        return self.w @ x_phys

    def to_phys(self, z: np.ndarray) -> np.ndarray:
        return np.real(self.v @ z)


def system(p: Params, held: bool, lay: Layout | None = None) -> System:
    lay = lay or layout(p)
    m, c, k, f = matrices(p, held, lay)
    n = m.shape[0]
    minv = np.linalg.inv(m)
    a = np.zeros((2 * n, 2 * n))
    a[:n, n:] = np.eye(n)
    a[n:, :n] = -minv @ k
    a[n:, n:] = -minv @ c
    lam, v = linalg.eig(a)
    w = np.linalg.inv(v)
    return System(held, lay, m, c, k, f, lam, v, w)


def point_rows(
    p: Params, lay: Layout, plane: int, dist_from_tailpiece_m: float, width_m: float
) -> np.ndarray:
    """The row giving the displacement on S averaged over `width_m` centred
    `dist_from_tailpiece_m` from the tailpiece end (a pickup's bar), in physical coordinates."""
    seg_s, _ = segments(p)
    big_l = p.geom.length_m
    xc = big_l - dist_from_tailpiece_m
    if width_m > 0:
        gx, gw = GAUSS
        xs = xc + 0.5 * width_m * gx
        local = (gw[:, None] * seg_s.rows(np.clip(xs, 0, big_l))).sum(axis=0) / 2
    else:
        local = seg_s.rows(np.array([xc]))[0]
    row = np.zeros(lay.n_string)
    row[_s_index(lay, plane)] = local
    return row


def mode_table(sysm: System, row: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For the eigenpairs with positive frequency: (frequency Hz, decay rate 1/s, the
    output's share of a unit modal amplitude through `row` on displacement)."""
    n = sysm.n
    full = np.concatenate([row, np.zeros(sysm.n - row.size)]) if row.size < n else row
    pick = sysm.lam.imag > 0
    amp = np.abs(full @ sysm.v[:n, pick])
    return sysm.lam.imag[pick] / (2 * np.pi), -sysm.lam.real[pick], amp

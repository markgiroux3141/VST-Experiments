"""A key's string as two substructures joined at the anvil, released and held
(docs/CLAVINET_PLAN.md, CL1, "The string" and "The release").

**Substructures (Craig-Bampton).** The string runs from the tuning pin (fixed) through the
anvil to the tailpiece. The anvil point a and the tailpiece end t are interface degrees of
freedom; between them are two segments, each a uniform tensioned Euler-Bernoulli string
pinned at its ends:

- **S**, the speaking part, anvil to tailpiece (length L), read by the pickups;
- **N**, the non-speaking part, pin to anvil (length l), with the yarn woven over its pin
  end (added mass and a dashpot per metre).

Each segment's coordinates are its fixed-interface modes, sin(k pi x / l) mass-normalized,
exact for a pinned stiff string (omega_k^2 = (k pi / l)^2 T / mu + (k pi / l)^4 EI / mu), plus
the static constraint shapes (linear: a tensioned beam pinned at both ends deflects in a
straight line under an end displacement), whose stiffness coupling to the modes is exactly
zero. The anvil is a hinge for bending (the slope isn't carried across it: the pinch holds
the wire like one; B ~ 1e-4, so bending carries ~0.01% of the energy there).

Both transverse planes are modelled: y (the tangent's push, the pickups' vertical) and x
(across the strings, which the pickups barely see: [R12], [G13] 2.3.5). They share the
basis, so the coordinates are (q_S, q_N, u_a, u_t) for y, then the same for x.

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
- each segment mode's air drag (Valette & Cuesta's formula on the outer diameter), the
  steel's loss factor on its bending energy and, on a wound string, the wrap's friction
  (a loss factor on all its energy: sigma = pi f eta_wrap);
- the yarn's dashpot;
- the tailpiece's dashpot;
- the pinch's dashpots and the rubber's;
- the mute bar's felt (a spring and dashpot pressed on S near the tailpiece, both planes),
  when its slider is on.

The basis is the same for both systems (modes kept up to `f_cut_hz` at the rest tension),
so a state moves between them exactly, through the physical coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import linalg

from varimu.clavinet.spec import StringGeom


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


def _seg_omegas(n: int, length: float, tension: float, mu: float, ei: float) -> np.ndarray:
    kk = np.arange(1, n + 1) * np.pi / length
    return np.sqrt(kk**2 * tension / mu + kk**4 * ei / mu)


def _count(length: float, tension: float, mu: float, ei: float, f_cut: float) -> int:
    n = 1
    while _seg_omegas(n + 1, length, tension, mu, ei)[-1] <= 2 * np.pi * f_cut:
        n += 1
    return n


def air_sigma(f_hz: np.ndarray, p: Params) -> np.ndarray:
    """Amplitude decay rate from air drag (Valette & Cuesta 1993, as in Chaigne &
    Askenfelt 1994): R = 2 pi eta + 2 pi d sqrt(pi eta rho f), sigma = R / (2 mu)."""
    eta, rho, d = p.air_viscosity_pa_s, p.air_density_kg_m3, p.geom.d_outer_m
    r = 2 * np.pi * eta + 2 * np.pi * d * np.sqrt(np.pi * eta * rho * np.asarray(f_hz))
    return r / (2 * p.geom.mu_kg_m)


@dataclass
class Layout:
    """Coordinate indices. Per plane: q_S (ns), q_N (nn), u_a, u_t."""

    ns: int
    nn: int

    @property
    def per_plane(self) -> int:
        return self.ns + self.nn + 2

    def qs(self, plane: int) -> slice:
        o = plane * self.per_plane
        return slice(o, o + self.ns)

    def qn(self, plane: int) -> slice:
        o = plane * self.per_plane + self.ns
        return slice(o, o + self.nn)

    def ua(self, plane: int) -> int:
        return plane * self.per_plane + self.ns + self.nn

    def ut(self, plane: int) -> int:
        return plane * self.per_plane + self.ns + self.nn + 1

    @property
    def n_string(self) -> int:
        return 2 * self.per_plane


def layout(p: Params) -> Layout:
    g = p.geom
    t = min(p.tension_rest_n, p.tension_held_n)
    return Layout(
        _count(g.length_m, t, g.mu_kg_m, g.ei_n_m2, p.f_cut_hz),
        _count(p.nonspeaking_m, t, g.mu_kg_m, g.ei_n_m2, p.f_cut_hz),
    )


def _yarn_matrix(p: Params, lay: Layout, per_m: float) -> np.ndarray:
    """int over the yarn of per_m * shape_i * shape_j on (q_N, u_a) of one plane."""
    ln, mu = p.nonspeaking_m, p.geom.mu_kg_m
    xy = min(p.yarn_length_m, ln)
    pts = 64 + 8 * lay.nn
    xg, wg = np.polynomial.legendre.leggauss(pts)
    x = 0.5 * xy * (xg + 1)
    w = 0.5 * xy * wg
    k = np.arange(1, lay.nn + 1)
    shapes = np.vstack([np.sqrt(2 / (mu * ln)) * np.sin(np.outer(k, x) * np.pi / ln), x / ln])
    return per_m * (shapes * w) @ shapes.T


def matrices(p: Params, held: bool, lay: Layout | None = None) -> tuple[np.ndarray, ...]:
    """(M, C, K, f): the system's matrices and its constant forces (held: the static press).
    Held systems have one more coordinate, the tangent, last."""
    g = p.geom
    lay = lay or layout(p)
    mu, ei = g.mu_kg_m, g.ei_n_m2
    tension = p.tension_held_n if held else p.tension_rest_n
    big_l, ln = g.length_m, p.nonspeaking_m
    n = lay.n_string + (1 if held else 0)
    m = np.zeros((n, n))
    c = np.zeros((n, n))
    k = np.zeros((n, n))
    f = np.zeros(n)
    ks = np.arange(1, lay.ns + 1)
    kn = np.arange(1, lay.nn + 1)
    om_s = _seg_omegas(lay.ns, big_l, tension, mu, ei)
    om_n = _seg_omegas(lay.nn, ln, tension, mu, ei)

    def seg_sigma(om: np.ndarray, length: float, kk: np.ndarray) -> np.ndarray:
        wave = (kk * np.pi / length) ** 2
        bend_frac = wave**2 * ei / (wave * tension + wave**2 * ei)
        f_hz = om / (2 * np.pi)
        wrap = p.eta_wrap if g.wound else 0.0
        return air_sigma(f_hz, p) + np.pi * f_hz * (p.eta_bend * bend_frac + wrap)

    sig_s = seg_sigma(om_s, big_l, ks)
    sig_n = seg_sigma(om_n, ln, kn)
    # coupling of each segment's modes to its constraint shapes: int mu phi_k psi
    cs_a = np.sqrt(2 * mu / big_l) * big_l / (ks * np.pi)  # psi = 1 - x/L (anvil at x=0)
    cs_t = np.sqrt(2 * mu / big_l) * big_l * (-1.0) ** (ks + 1) / (ks * np.pi)  # psi = x/L
    cn_a = np.sqrt(2 * mu / ln) * ln * (-1.0) ** (kn + 1) / (kn * np.pi)  # psi = x/l (anvil at x=l)
    yarn_m = _yarn_matrix(p, lay, p.yarn_mass_kg_m)
    yarn_c = _yarn_matrix(p, lay, p.yarn_damping_ns_m2)
    for pl in (0, 1):
        s_, n_, a, t = lay.qs(pl), lay.qn(pl), lay.ua(pl), lay.ut(pl)
        m[s_, s_] = np.eye(lay.ns)
        m[n_, n_] = np.eye(lay.nn)
        m[s_, a] = m[a, s_] = cs_a
        m[s_, t] = m[t, s_] = cs_t
        m[n_, a] = m[a, n_] = cn_a
        m[a, a] = mu * big_l / 3 + mu * ln / 3
        m[t, t] = mu * big_l / 3
        m[a, t] = m[t, a] = mu * big_l / 6
        idx = np.r_[np.arange(n_.start, n_.stop), a]
        m[np.ix_(idx, idx)] += yarn_m
        c[np.ix_(idx, idx)] += yarn_c
        k[s_, s_] = np.diag(om_s**2)
        k[n_, n_] = np.diag(om_n**2)
        c[s_, s_] += np.diag(2 * sig_s)
        c[n_, n_] += np.diag(2 * sig_n)
        k[a, a] = tension / big_l + tension / ln
        k[t, t] = tension / big_l + p.tailpiece_k_n_m
        k[a, t] = k[t, a] = -tension / big_l
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
    g = p.geom
    big_l, mu = g.length_m, g.mu_kg_m
    xc = big_l - dist_from_tailpiece_m
    x1, x2 = xc - width_m / 2, xc + width_m / 2
    ks = np.arange(1, lay.ns + 1)
    row = np.zeros(lay.n_string)
    if width_m > 0:
        avg = (
            big_l
            / (ks * np.pi * width_m)
            * (np.cos(ks * np.pi * x1 / big_l) - np.cos(ks * np.pi * x2 / big_l))
        )
    else:
        avg = np.sin(ks * np.pi * xc / big_l)
    row[lay.qs(plane)] = np.sqrt(2 / (mu * big_l)) * avg
    row[lay.ua(plane)] = 1 - xc / big_l
    row[lay.ut(plane)] = xc / big_l
    return row


def mode_table(sysm: System, row: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For the eigenpairs with positive frequency: (frequency Hz, decay rate 1/s, the
    output's share of a unit modal amplitude through `row` on displacement)."""
    n = sysm.n
    full = np.concatenate([row, np.zeros(sysm.n - row.size)]) if row.size < n else row
    pick = sysm.lam.imag > 0
    amp = np.abs(full @ sysm.v[:n, pick])
    return sysm.lam.imag[pick] / (2 * np.pi), -sysm.lam.real[pick], amp

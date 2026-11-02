"""A two-headed drum (docs/DRUM_PLAN.md, D1): a batter head and a resonant head on the
ends of a rigid cylindrical shell, coupled through the air inside, loaded by the air
outside, radiating from both heads. Offline, Python only; the heads' own physics (modes,
the beater, tension modulation) is membrane.py's.

**The linear drum.** Per azimuthal order m (the cos(m phi) family: strike and mic lie on
phi = 0, so nothing couples orders), the unknowns are both heads' modal displacements
(outward from the cavity) and the cavity's dynamic acoustic modes. The cavity's pressure
is expanded in its rigid-wall modes `Psi = R_n(r) cos(m phi) cos(l pi z / L)` (R_n =
J_m(beta_n r / a), beta_n the zeros of J_m'), which a head's outward acceleration drives
(`P_j'' + omega_j^2 P_j = -(rho0 c^2 / Lambda_j) sum_k G_jk q_k''`, G the overlap of Psi_j
with the head's mode at its end) and which push back on the heads (force G_jk P_j).
Writing `P_j = (rho0 c^2 / Lambda_j)(chi_j - G_j q)` makes the system symmetric,
`M x'' + K x = f` (M: the heads' sigma plus the air's added mass; K: the heads' tension
lambda_k, the air's stiffness, the coupling), solved for its normal modes once
(scipy.linalg.eigh, M-orthonormal). Three parts of the air:

- **The air spring**: the uniform mode (m = 0, beta = 0, l = 0) is static: the cavity's
  pressure follows the net volume the heads sweep, `p = -(rho0 c^2 / V) dV`.
- **Dynamic cavity modes** below f_max (the axial plane waves, the transverse modes):
  oscillators chi_j with mass rho0 c^2 / (Lambda_j omega_j^2) and stiffness
  rho0 c^2 / Lambda_j.
- **Every other cavity mode as added mass** (they are far above the heads' frequencies):
  per radial order n the sum over l in closed form, `rho0 O O^T / S_n * g_n`, with
  `g_n = coth(q L) / q` (a head on itself) and `1 / (q sinh(q L))` (across the shell),
  q = beta_n / a (for beta = 0, l >= 1: L / 3 and -L / 6, the air column), minus the
  dynamic modes' own static share.

**The air outside** each head is an added mass, the incompressible limit of a baffled
head's radiation load, `M_kl = rho0 eps'_m integral_0^inf H_k(kappa) H_l(kappa) dkappa`
with H the modes' Hankel transforms (eps'_m = 2 pi for m = 0, else pi; a piston gives
8/3 rho0 a^3). The heads are subsonic (c_head ~ 40-60 m/s against 343), so the near field
is local and this holds for every mode; for the lowest modes (ka ~ 1) it overstates the
load a little. Provisional: the shell isn't a baffle.

**Radiation** per normal mode, from both heads as monopole layers in free space (their
outward volume accelerations, `p = rho0 / (4 pi R) sum integral a_n e^{i k r.r'} dS`):
compact, a drum whose heads breathe together is a monopole, one whose air column shakes is
a dipole of the shell's length (it rings longer). The decay rate is the power over the
sphere over twice the energy; the film's loss adds `eta Omega / 2` times each head's share
of the mode's tension energy.

**Nonlinear parts**, in normal coordinates (eta, M-orthonormal): the beater on the batter
head (membrane.py's contact law), and tension modulation per head,
`T_h = T0_h + stretch_h sum_k lambda_k q_hk^2` with `q_h = V_h eta`, which is `eta^T G_h
eta` with `G_h = V_h^T diag(lambda) V_h`; the extra tension's force on the normal modes is
`(T_h - T0_h) G_h eta`. G_h is kept sparse (entries below G_TOL of the geometric mean of
their diagonals dropped): its weight is in the pairs of normal modes the two heads' modes
form. The pairs matter: heads tuned alike make every normal mode half batter, half
resonant head, and only the pair's cross terms keep a hit's stretch on the batter (a
diagonal G spreads it over both heads at once). The pressure's 90-degree lead for odd m
is taken at the rest frequency.

`load(name)` reads `config/drums/<name>.yaml`: membrane.py's blocks plus `resonant` (a
head) and `body` (the shell's depth, the mic's angle from the drum's axis out of the
resonant head: 180 = out of the batter head).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from scipy import linalg, sparse, special

from varimu.drums import membrane as mb

G_TOL = 1e-4  # tests/test_drum.py: against the dense G


@dataclass(frozen=True)
class Body:
    depth_m: float
    mic_angle_deg: float
    f_coupled_hz: float | None = None  # numerical: the top of the coupled range (_blocks)


@dataclass(frozen=True)
class Drum2:
    drum: mb.Drum  # the batter head, the beater, the strike, the mic's distance, the air
    resonant: mb.Head
    body: Body


def load(name: str, path: Path | None = None) -> Drum2:
    path = path or mb.DRUMS_DIR / f"{name}.yaml"
    drum = mb.load(name, path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    res = mb._values(data["resonant"], "resonant")
    res["radius_m"] = drum.head.radius_m
    return Drum2(drum, mb.Head(**res), Body(**mb._values(data["body"], "body")))


def _eps(m: int) -> float:
    return 2 * np.pi if m == 0 else np.pi


def hankel(m: int, j: np.ndarray, norm: np.ndarray, a: float, kappa: np.ndarray) -> np.ndarray:
    """H_k(kappa) = N_k integral_0^a J_m(j_k r / a) J_m(kappa r) r dr (Lommel, with
    J_m(j_k) = 0): N_k a p J_m'(j_k) J_m(kappa a) / (kappa^2 - p^2), p = j_k / a. Shape
    (modes, kappas)."""
    p = (j / a)[:, None]
    jmp = special.jvp(m, j)[:, None]
    kap = np.asarray(kappa, dtype=float)[None, :]
    den = kap * kap - p * p
    near = np.abs(den) < 1e-9 * p * p
    safe = np.where(near, 1.0, den)
    out = a * p * jmp * special.jv(m, kap * a) / safe
    out = np.where(near, 0.5 * a * a * jmp * jmp, out)
    return norm[:, None] * out


def external_mass(m: int, j: np.ndarray, norm: np.ndarray, a: float, rho0: float) -> np.ndarray:
    """The air outside a baffled head on its modes of order m (the incompressible limit)."""
    if j.size == 0:
        return np.zeros((0, 0))
    x_top = max(6.0 * j.max(), j.max() + 200.0)
    x = np.linspace(0.0, x_top, int(x_top / 0.02) + 1)
    h = hankel(m, j, norm, a, x / a)
    w = np.full(x.size, x[1] - x[0]) / a
    w[[0, -1]] *= 0.5
    return rho0 * _eps(m) * (h * w) @ h.T


def piston_mass_check(a: float, rho0: float) -> float:
    """The same integral for a piston (H = a J_1(kappa a) / kappa): 8/3 rho0 a^3."""
    x = np.linspace(1e-9, 4000.0, 400_001)
    h = a * a * special.jv(1, x) / x  # a J1(kappa a) / kappa, kappa = x / a
    w = np.full(x.size, x[1] - x[0]) / a
    w[[0, -1]] *= 0.5
    return rho0 * 2 * np.pi * float(np.sum(h * h * w))


def _norm(m: int, j: np.ndarray, a: float) -> np.ndarray:
    return np.sqrt(2.0 / ((2.0 if m == 0 else 1.0) * np.pi * a * a * special.jv(m + 1, j) ** 2))


def _cavity_radial(
    m: int, j: np.ndarray, norm: np.ndarray, a: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The cavity's radial functions R_n = J_m(beta_n r / a) (beta = 0 for m = 0, then the
    zeros of J_m') up to well past the heads' modes: their wavenumbers q, the norms S_n of
    R_n cos(m phi) over the disc, and the overlaps O[n, k] with the heads' modes."""
    eps = _eps(m)
    x_top = max(6.0 * j.max(), j.max() + 200.0)
    count = int(x_top / np.pi + m + 10)
    betas = special.jnp_zeros(m, count)
    betas = betas[betas <= x_top]
    if m == 0:
        betas = np.concatenate([[0.0], betas])
    safe = np.where(betas > 0, betas, 1.0)
    s_n = np.where(
        betas > 0,
        eps * 0.5 * a * a * (1 - (m / safe) ** 2) * special.jv(m, betas) ** 2,
        eps * 0.5 * a * a,
    )
    p = j / a
    q = betas / a
    lommel = -a * p[None, :] * special.jvp(m, j)[None, :] * special.jv(m, betas)[:, None]
    o = eps * norm[None, :] * lommel / (p[None, :] ** 2 - q[:, None] ** 2)
    return q, s_n, o


def _g_static(q: np.ndarray, big_l: float) -> tuple[np.ndarray, np.ndarray]:
    """Per radial order, the sum over all axial orders l of a cavity mode's static share,
    a head on itself (coth(q L) / q) and across the shell (1 / (q sinh(q L))); for q = 0
    the l >= 1 terms only (the air column: L / 3, -L / 6; l = 0 is the air spring)."""
    g_self = np.empty(q.size)
    g_cross = np.empty(q.size)
    for n, qn in enumerate(q):
        if qn > 0:
            e = np.exp(-qn * big_l)
            g_self[n] = (1 + e * e) / (1 - e * e) / qn
            g_cross[n] = 2 * e / (1 - e * e) / qn
        else:
            g_self[n], g_cross[n] = big_l / 3, -big_l / 6
    return g_self, g_cross


@dataclass(frozen=True)
class Block:
    """One azimuthal order's linear drum."""

    m: int
    omega: np.ndarray  # normal modes, rad/s
    vb: np.ndarray  # the batter head's modal displacements (outward) per normal mode
    vr: np.ndarray  # the resonant head's
    jb: np.ndarray  # the batter's Bessel zeros (its modes of this order)
    jr: np.ndarray
    n_cavity: int


def block(
    d2: Drum2, m: int, jb: np.ndarray, jr: np.ndarray, f_cavity_hz: float | None = None
) -> Block:
    """Assemble and solve order m. jb, jr: the zeros of J_m of each head's modes; the
    cavity's modes below f_cavity_hz (default f_max) are dynamic, the rest added mass."""
    drum = d2.drum
    a = drum.head.radius_m
    big_l = d2.body.depth_m
    rho0, c0 = drum.air_density_kg_m3, drum.sound_speed_m_s
    vol = np.pi * a * a * big_l
    nb, nr = jb.size, jr.size
    jall = jb if nb >= nr else jr  # the same shapes on both heads (one radius)
    norm = _norm(m, jall, a)
    q, s_n, o = _cavity_radial(m, jall, norm, a)

    # dynamic cavity modes below f_max, and every radial order's static remainder
    w_top = 2 * np.pi * (f_cavity_hz or drum.f_max_hz)
    dyn = []  # (n, l)
    g_self, g_cross = _g_static(q, big_l)
    for n, qn in enumerate(q):
        for l_ax in range(0, 10_000):
            if qn == 0 and l_ax == 0:
                continue
            kz = l_ax * np.pi / big_l
            if c0 * np.hypot(qn, kz) > w_top:
                break
            dyn.append((n, l_ax))
            e_l = 1.0 if l_ax == 0 else 2.0
            share = e_l / (big_l * (qn * qn + kz * kz))
            g_self[n] -= share
            g_cross[n] -= (-1) ** l_ax * share
    nc = len(dyn)

    ob = o[:, :nb]
    orr = o[:, :nr]
    m_int_bb = rho0 * (ob.T * (g_self / s_n)) @ ob
    m_int_rr = rho0 * (orr.T * (g_self / s_n)) @ orr
    m_int_br = rho0 * (ob.T * (g_cross / s_n)) @ orr
    size = nb + nr + nc
    mm = np.zeros((size, size))
    kk = np.zeros((size, size))
    sb, sr = slice(0, nb), slice(nb, nb + nr)
    mm[sb, sb] = drum.head.sigma_kg_m2 * np.eye(nb) + m_int_bb
    mm[sr, sr] = d2.resonant.sigma_kg_m2 * np.eye(nr) + m_int_rr
    mm[sb, sr] = m_int_br
    mm[sr, sb] = m_int_br.T
    mm[sb, sb] += external_mass(m, jb, norm[:nb], a, rho0)
    mm[sr, sr] += external_mass(m, jr, norm[:nr], a, rho0)
    kk[sb, sb] = np.diag(drum.head.tension_n_m * (jb / a) ** 2)
    kk[sr, sr] = np.diag(d2.resonant.tension_n_m * (jr / a) ** 2)
    if m == 0:  # the air spring
        g0 = np.concatenate([ob[0], orr[0]])
        kk[: nb + nr, : nb + nr] += rho0 * c0 * c0 / vol * np.outer(g0, g0)
    for i, (n, l_ax) in enumerate(dyn):
        e_l = 1.0 if l_ax == 0 else 2.0
        lam_j = s_n[n] * big_l / e_l
        cj = rho0 * c0 * c0 / lam_j
        wj2 = c0 * c0 * (q[n] ** 2 + (l_ax * np.pi / big_l) ** 2)
        g = np.concatenate([ob[n], (-1) ** l_ax * orr[n]])
        kk[: nb + nr, : nb + nr] += cj * np.outer(g, g)
        kk[: nb + nr, nb + nr + i] = -cj * g
        kk[nb + nr + i, : nb + nr] = -cj * g
        kk[nb + nr + i, nb + nr + i] = cj
        mm[nb + nr + i, nb + nr + i] = cj / wj2
    w2, v = linalg.eigh(kk, mm)
    return Block(m, np.sqrt(np.maximum(w2, 0.0)), v[sb], v[sr], jb, jr, nc)


def local_block(d2: Drum2, m: int, j: np.ndarray, resonant: bool) -> Block:
    """One head's modes of order m on their own (above the coupled range): each its own
    normal mode, its mass the head's plus the diagonal of the air's outside and inside
    (every cavity mode as added mass: a subsonic mode's overlap is with cavity modes far
    above it), its stiffness the tension's."""
    drum = d2.drum
    head = d2.resonant if resonant else drum.head
    a = drum.head.radius_m
    rho0 = drum.air_density_kg_m3
    norm = _norm(m, j, a)
    q, s_n, o = _cavity_radial(m, j, norm, a)
    g_self, _ = _g_static(q, d2.body.depth_m)
    m_int = rho0 * np.sum(o * o * (g_self / s_n)[:, None], axis=0)
    m_ext = np.diag(external_mass(m, j, norm, a, rho0))
    mass = head.sigma_kg_m2 + m_int + m_ext
    omega = np.sqrt(head.tension_n_m * (j / a) ** 2 / mass)
    v = np.diag(1.0 / np.sqrt(mass))
    none = np.zeros((0, j.size))
    vb, vr = (none, v) if resonant else (v, none)
    jb, jr = (np.zeros(0), j) if resonant else (j, np.zeros(0))
    return Block(m, omega, vb, vr, jb, jr, 0)


@dataclass(frozen=True)
class Prepared2:
    d2: Drum2
    m: np.ndarray  # each normal mode's order
    omega: np.ndarray
    decay: np.ndarray
    decay_radiation: np.ndarray
    face: np.ndarray  # the batter's inward displacement at the beater per unit eta
    mic: np.ndarray  # complex, Pa per m/s^2 of eta''
    gamma: np.ndarray  # (2, modes): sum_k lambda_k v_hk^2 per head
    beta: np.ndarray  # (2, modes): each head's share of the mode's stiffness
    batter_share: np.ndarray  # the batter's share of the mode's kinetic energy (heads only)
    n_cavity: int
    # per head, G = V_h^T diag(lambda) V_h: eta^T G eta is the head's integral of
    # |grad w|^2, and dT G eta the force its extra tension puts on the normal modes
    g_heads: tuple[sparse.csr_matrix, sparse.csr_matrix]


def _far_field(blk: Block, d2: Drum2, theta: np.ndarray) -> np.ndarray:
    """A(theta) per normal mode (modes, thetas): sum over heads of e^{i k z_h cos theta}
    times N_k 2 pi integral J_m(j r / a) J_m(k r sin theta) r dr, weighted by the mode."""
    a = d2.drum.head.radius_m
    k = blk.omega / d2.drum.sound_speed_m_s
    half = 0.5 * d2.body.depth_m
    out = np.zeros((blk.omega.size, theta.size), dtype=complex)
    for vh, jh, z in ((blk.vb, blk.jb, -half), (blk.vr, blk.jr, half)):
        if jh.size == 0:
            continue
        norm = np.sqrt(
            2.0 / ((2.0 if blk.m == 0 else 1.0) * np.pi * a * a * special.jv(blk.m + 1, jh) ** 2)
        )
        for t_i, th in enumerate(theta):
            h = hankel(blk.m, jh, norm, a, k * np.sin(th))  # (head modes, normal modes)
            amp = 2 * np.pi * np.einsum("kn,kn->n", vh, h)
            out[:, t_i] += np.exp(1j * k * z * np.cos(th)) * amp
    return out


def _blocks(d2: Drum2, m: int, jb: np.ndarray, jr: np.ndarray, f_coupled_hz: float):
    """Order m: the heads' modes below f_coupled_hz (in vacuo) as one coupled system with
    the air (its dynamic cavity modes below f_coupled_hz too), each head's modes above it
    on their own."""
    fb = jb * np.sqrt(d2.drum.head.tension_n_m / d2.drum.head.sigma_kg_m2)
    fr = jr * np.sqrt(d2.resonant.tension_n_m / d2.resonant.sigma_kg_m2)
    two_pi_a = 2 * np.pi * d2.drum.head.radius_m
    nb = int(np.sum(fb / two_pi_a <= f_coupled_hz))
    nr = int(np.sum(fr / two_pi_a <= f_coupled_hz))
    out = []
    if nb or nr:
        out.append(block(d2, m, jb[:nb], jr[:nr], f_coupled_hz))
    if nb < jb.size:
        out.append(local_block(d2, m, jb[nb:], resonant=False))
    if nr < jr.size:
        out.append(local_block(d2, m, jr[nr:], resonant=True))
    return out


def prepare(d2: Drum2, f_coupled_hz: float | None = None) -> Prepared2:
    """The drum's normal modes and everything the run needs. f_coupled_hz (default the
    drum's `f_coupled_hz`, else f_max): the top of the coupled range (`_blocks`)."""
    drum = d2.drum
    a = drum.head.radius_m
    rho0, c0 = drum.air_density_kg_m3, drum.sound_speed_m_s
    f_c = f_coupled_hz or d2.body.f_coupled_hz or drum.f_max_hz
    mdb = mb.modes(drum.head, drum.f_max_hz)
    mdr = mb.modes(d2.resonant, drum.f_max_hz)
    face_all = mb.face_average(mdb, a, drum.strike_radius_m, drum.beater.face_radius_m)
    x, w = np.polynomial.legendre.leggauss(96)
    theta = 0.5 * np.pi * (x + 1)
    w_theta = 0.5 * np.pi * w * np.sin(theta)
    th_mic = np.radians(d2.body.mic_angle_deg)
    parts = []
    n_cav = 0
    offset = 0
    stretch_g = ([], [], []), ([], [], [])  # per head: rows, cols, values
    blocks = []
    for m in range(int(max(mdb.m.max(), mdr.m.max())) + 1):
        jb_m, jr_m = mdb.j[mdb.m == m], mdr.j[mdr.m == m]
        face_m = dict(zip(jb_m.tolist(), face_all[mdb.m == m].tolist(), strict=True))
        blocks += [(blk, face_m) for blk in _blocks(d2, m, jb_m, jr_m, f_c)]
    for blk, face_m in blocks:
        m, jb, jr = blk.m, blk.jb, blk.jr
        n_cav += blk.n_cavity
        lam_b, lam_r = (jb / a) ** 2, (jr / a) ** 2
        gamma = np.stack([lam_b @ blk.vb**2, lam_r @ blk.vr**2])
        for (rows, cols, vals), vh, lam in zip(
            stretch_g, (blk.vb, blk.vr), (lam_b, lam_r), strict=True
        ):
            g = (vh.T * lam) @ vh
            d = np.sqrt(np.abs(np.diag(g)))
            r, c = np.nonzero(np.abs(g) > G_TOL * np.outer(d, d))
            rows.append(r + offset)
            cols.append(c + offset)
            vals.append(g[r, c])
        offset += blk.omega.size
        w2 = np.maximum(blk.omega**2, 1e-30)
        beta = np.stack(
            [drum.head.tension_n_m * gamma[0] / w2, d2.resonant.tension_n_m * gamma[1] / w2]
        )
        far = _far_field(blk, d2, theta)
        s_rad = rho0 * blk.omega**2 * _eps(m) / (32 * np.pi**2 * c0) * (np.abs(far) ** 2 @ w_theta)
        s_mat = (
            0.5 * blk.omega * (drum.head.loss_factor * beta[0] + d2.resonant.loss_factor * beta[1])
        )
        mic_far = _far_field(blk, d2, np.array([th_mic]))[:, 0]
        mic = rho0 / (4 * np.pi * drum.mic_distance_m) * (1j**m) * mic_far
        kin_b = drum.head.sigma_kg_m2 * np.sum(blk.vb**2, axis=0)
        kin_r = d2.resonant.sigma_kg_m2 * np.sum(blk.vr**2, axis=0)
        parts.append(
            dict(
                m=np.full(blk.omega.size, m),
                omega=blk.omega,
                decay=s_rad + s_mat,
                decay_radiation=s_rad,
                face=-(np.array([face_m[j] for j in jb.tolist()]) @ blk.vb),
                mic=mic,
                gamma=gamma,
                beta=beta,
                batter_share=kin_b / np.maximum(kin_b + kin_r, 1e-300),
            )
        )
    cat = {k: np.concatenate([p[k] for p in parts], axis=-1) for k in parts[0]}
    g_heads = tuple(
        sparse.csr_matrix(
            (np.concatenate(v), (np.concatenate(r), np.concatenate(c))), shape=(offset, offset)
        )
        for r, c, v in stretch_g
    )
    return Prepared2(d2=d2, n_cavity=n_cav, g_heads=g_heads, **cat)


def fundamental(prep: Prepared2) -> int:
    """The normal mode that sounds the drum's pitch: of the modes below 2.5x the lowest
    batter-led one, the strongest at the mic for a strike (|mic| |face| / decay)."""
    led = np.flatnonzero((prep.batter_share > 0.2) & (prep.omega > 0))
    lowest = prep.omega[led].min()
    cand = np.flatnonzero((prep.omega < 2.5 * lowest) & (prep.omega > 0))
    score = np.abs(prep.mic[cand]) * np.abs(prep.face[cand]) / prep.decay[cand]
    return int(cand[np.argmax(score)])


@dataclass(frozen=True)
class Hit2:
    fs: float
    pressure_pa: np.ndarray
    force_n: np.ndarray
    tension_n_m: np.ndarray  # (2, samples): batter, resonant
    f_fund_hz: np.ndarray  # the fundamental's frequency over time


def run(
    prep: Prepared2,
    *,
    fs: float,
    seconds: float,
    velocity_m_s: float,
    tension_modulation: bool = True,
) -> Hit2:
    d2 = prep.d2
    drum = d2.drum
    h = 1.0 / fs
    om = prep.omega
    if not np.all(om > 0):
        raise ValueError("a normal mode at 0 Hz: the drum isn't held")
    om2h2 = 2.0 - 2.0 * np.cos(om * h)
    sh = prep.decay * h
    a_plus = 1.0 / (1.0 + sh)
    a_minus = 1.0 - sh
    face = prep.face
    drive_a = face * h * h * a_plus  # the beater's force is inward: face is inward per eta
    gain_acc = prep.mic.real / (h * h)
    gain_vel = prep.mic.imag * om / (2 * h)
    t0b, t0r = drum.head.tension_n_m, d2.resonant.tension_n_m
    sb, sr = (drum.head.stretch_n_m, d2.resonant.stretch_n_m) if tension_modulation else (0, 0)
    gb_mat, gr_mat = prep.g_heads
    fund = fundamental(prep)
    gb_ff, gr_ff = gb_mat[fund, fund], gr_mat[fund, fund]
    bt = drum.beater
    compliance = h * h / bt.mass_kg + (face * face * h * h * a_plus).sum()

    def law(d: float, d_now: float) -> float:
        if d <= 0.0:
            return 0.0
        rate = bt.hysteresis_s_m * (d - d_now) * fs
        return max(bt.stiffness * d**bt.exponent * (1.0 + rate), 0.0)

    n_steps = int(round(seconds * fs))
    pressure = np.zeros(n_steps)
    force = np.zeros(n_steps)
    tension = np.zeros((2, n_steps))
    f_fund = np.zeros(n_steps)
    q = np.zeros(om.size)
    qp = q.copy()
    y, yp = 0.0, -velocity_m_s * h
    for i in range(n_steps):
        dtb = dtr = 0.0
        push = 0.0
        if sb:
            gb, gr = gb_mat @ q, gr_mat @ q
            dtb, dtr = sb * (q @ gb), sr * (q @ gr)
            push = h * h * (dtb * gb + dtr * gr)
        qn = (2.0 * q - a_minus * qp - om2h2 * q - push) * a_plus
        y_free = 2.0 * y - yp
        # the batter's inward displacement under the beater is face . q
        d_free = y_free - face @ qn
        f = 0.0
        if d_free > 0.0:
            f = mb._contact_force(law, d_free, compliance, y - face @ q)
            qn += drive_a * f
        y, yp = y_free - h * h * f / bt.mass_kg, y
        pressure[i] = gain_acc @ (qn - 2.0 * q + qp) - gain_vel @ (qn - qp)
        force[i] = f
        tension[:, i] = t0b + dtb, t0r + dtr
        f_fund[i] = np.sqrt(om[fund] ** 2 + dtb * gb_ff + dtr * gr_ff) / (2 * np.pi)
        qp, q = q, qn
    return Hit2(fs, pressure, force, tension, f_fund)

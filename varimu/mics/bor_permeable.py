"""A body of revolution with a sound-permeable sheet (docs/SM57_PLAN.md SM8: the SM58's ball
grille): two acoustic domains, the air outside and the air the sheet encloses, joined
through the sheet.

The sheet has a specific transfer impedance Z_s (Pa s/m): the normal velocity v is continuous
through it and p_in - p_out = Z_s v (the flow from high to low pressure; varimu.mics.
permeable has the exact series of a spherical shell, the check case). Order 0 only, as
varimu.mics.bor (whose kernels this uses), e^{+j w t}, G = e^{-jkR} / (4 pi R).

The mesh: panels of three kinds, each with its normal n: RIGID_OUT (a rigid surface facing the
outside air, n into it), RIGID_IN (a rigid surface facing the enclosed air, n into it), SHEET
(n from the enclosed air to the outside). The unknowns: p on the rigid panels, and on the
sheet p_out and v (p_in = p_out + Z_s v). Each domain's boundary is closed (the outside: the
RIGID_OUT panels and the sheet; the inside: the sheet and the RIGID_IN panels), so each takes
bor.py's treatment of the static double layer (Gauss: its integral over a closed surface is
-1/2 at a smooth point, n out of the enclosed region). With dp/dn = -j w rho v:

    outside, at x on its boundary:  p / 2 - PV int p dG/dn - j w rho int_sheet G v = p_inc
    inside, at x on its boundary:   p / 2 + PV int p dG/dn' + j w rho int_sheet G v = 0

n' the inside domain's outward normal (n on the sheet, -n on RIGID_IN). CHIEF rows: the outside
equation at points enclosed by its boundary gives 0 = p_inc + int p dG/dn + j w rho int G v
(least squares). The single layer: int G over a ring, its static part 4 K(m) / sqrt(A + B) /
(4 pi) (complete elliptic K: a log singularity on the curve, integrated on graded
sub-panels), its dynamic part (e^{-jkR} - 1) / R smooth.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import ellipk

from varimu.devices.capsule import C_AIR, RHO_AIR
from varimu.mics import bor

RIGID_OUT, RIGID_IN, SHEET = 0, 1, 2


@dataclass(frozen=True)
class PermeableMesh:
    p0: np.ndarray  # (N, 2) r, z: each panel's start; n = (-dz, dr) / ds of p0 -> p1
    p1: np.ndarray
    kind: np.ndarray  # (N,): RIGID_OUT, RIGID_IN, SHEET
    chief_out: np.ndarray  # (M, 2): points enclosed by the outside domain's boundary

    @property
    def n(self) -> int:
        return len(self.p0)

    @property
    def mid(self) -> np.ndarray:
        return 0.5 * (self.p0 + self.p1)

    @property
    def length(self) -> np.ndarray:
        return np.hypot(*(self.p1 - self.p0).T)

    @property
    def normal(self) -> np.ndarray:
        d = (self.p1 - self.p0) / self.length[:, None]
        return np.stack([-d[:, 1], d[:, 0]], axis=1)


def polyline(corners, kinds, panel_m: float, chief_out=None) -> PermeableMesh:
    """Panels along a generating curve's segments (each segment's kind; the normal on the
    curve's right, as bor.polyline_mesh), about panel_m each."""
    p0, p1, kind = [], [], []
    for (a, b), kd in zip(zip(corners[:-1], corners[1:], strict=True), kinds, strict=True):
        n = max(2, int(np.ceil(np.hypot(b[0] - a[0], b[1] - a[1]) / panel_m)))
        pts = bor._segment(a, b, n, 2.0)
        p0.append(pts[:-1])
        p1.append(pts[1:])
        kind += [kd] * n
    chief = np.zeros((0, 2)) if chief_out is None else np.asarray(chief_out, float)
    return PermeableMesh(np.vstack(p0), np.vstack(p1), np.array(kind), chief)


def sphere_shell(radius_m: float, panels: int = 120) -> PermeableMesh:
    """A spherical sheet alone (the check case): the arc from the front pole to the rear,
    n outward; CHIEF points inside it."""
    beta = np.linspace(0.0, np.pi, panels + 1)
    pts = radius_m * np.c_[np.sin(beta), np.cos(beta)]
    chief = radius_m * np.array([[0.2, 0.3], [0.5, -0.1], [0.3, -0.55], [0.6, 0.4], [0.1, -0.2]])
    return PermeableMesh(pts[:-1], pts[1:], np.full(panels, SHEET), chief)


def _quad(m: PermeableMesh, j: int, sub: int, graded_about: float | None = None):
    """Gauss points on panel j (positions (q, 2), weights per unit length times r'): `sub`
    equal pieces, or (graded_about = the collocation's parameter t on the panel) pieces graded
    geometrically toward it from both sides."""
    x, w = bor._GL
    if graded_about is None:
        edges = np.linspace(0.0, 1.0, sub + 1)
    else:
        g = 0.5 ** np.arange(sub)[::-1]  # 1/2^(sub-1) .. 1
        left = graded_about * (1 - g)
        right = graded_about + (1 - graded_about) * g
        edges = np.unique(np.r_[0.0, left, graded_about, right, 1.0])
    t = (edges[:-1, None] + (edges[1:] - edges[:-1])[:, None] * 0.5 * (x[None, :] + 1)).ravel()
    ww = ((edges[1:] - edges[:-1])[:, None] * 0.5 * w[None, :]).ravel()
    a, b = m.p0[j], m.p1[j]
    pts = a[None, :] + t[:, None] * (b - a)[None, :]
    return pts, ww * m.length[j] * pts[:, 0]


def _single_static(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """The phi-integral of G0 = 1 / (4 pi R) over the ring through y, at x (per r' dphi)."""
    r, z = x[..., 0], x[..., 1]
    rp, zp = y[..., 0], y[..., 1]
    a_ = r * r + rp * rp + (zp - z) ** 2
    b_ = 2 * r * rp
    mpar = np.clip(2 * b_ / (a_ + b_), 0.0, 1.0 - 1e-16)
    return 4 * ellipk(mpar) / np.sqrt(a_ + b_) / (4 * np.pi)


def _single_dynamic(x: np.ndarray, y: np.ndarray, k: float) -> np.ndarray:
    """The phi-integral of (e^{-jkR} - 1) / (4 pi R) over the ring (bounded: -jk / 4 pi at R
    = 0)."""
    phi = np.linspace(0.0, np.pi, bor._PHI + 1)
    c = np.cos(phi)
    r, z = x[..., 0, None], x[..., 1, None]
    rp, zp = y[..., 0, None], y[..., 1, None]
    rr = np.sqrt(np.maximum(r * r + rp * rp - 2 * r * rp * c + (zp - z) ** 2, 1e-300))
    f = np.expm1(-1j * k * rr) / (4 * np.pi * rr)
    return f @ bor._PHI_W


@dataclass
class Operator:
    mesh: PermeableMesh
    xs: np.ndarray  # collocation points: panel midpoints, then CHIEF points
    d0_out: np.ndarray  # (N + M, N) static double layer with the outside normals n
    d0_in: np.ndarray  # (N, N) with the inside's normals n'
    s0: np.ndarray  # (N + M, N) static single layer
    pts: list  # per panel: Gauss points and weights (the far quadrature)
    n_in: np.ndarray  # (N, 2) the inside domain's outward normals


def operator(m: PermeableMesh, near_sub: int = 12, graded: int = 10) -> Operator:
    xs = np.vstack([m.mid, m.chief_out])
    nrm = m.normal
    n_in = np.where((m.kind == RIGID_IN)[:, None], -nrm, nrm)
    nr = len(xs)
    d0o = np.zeros((nr, m.n))
    d0i = np.zeros((m.n, m.n))
    s0 = np.zeros((nr, m.n))
    pts = [_quad(m, j, 1) for j in range(m.n)]
    for j in range(m.n):
        p, w = pts[j]
        dist = np.min(np.hypot(*(xs[:, None, :] - p[None]).transpose(2, 0, 1)), axis=1)
        near = dist < 2.0 * m.length[j]
        far = ~near
        d0o[far, j] = bor._static_ring(xs[far, None, :], p[None], nrm[j]) @ w
        s0[far, j] = _single_static(xs[far, None, :], p[None]) @ w
        fi = far[: m.n]
        d0i[fi, j] = bor._static_ring(xs[: m.n][fi, None, :], p[None], n_in[j]) @ w
        for i in np.nonzero(near)[0]:
            if i == j:
                pg, wg = _quad(m, j, graded, graded_about=0.5)
                s0[i, j] = _single_static(xs[i], pg) @ wg
                continue
            pn, wn = _quad(m, j, near_sub)
            d0o[i, j] = bor._static_ring(xs[i], pn, nrm[j]) @ wn
            s0[i, j] = _single_static(xs[i], pn) @ wn
            if i < m.n:
                d0i[i, j] = bor._static_ring(xs[i], pn, n_in[j]) @ wn
    return Operator(m, xs, d0o, d0i, s0, pts, n_in)


def _dynamic_matrices(op: Operator, k: float):
    """The dynamic double layers (outside and inside normals) and single layer on the far
    quadrature (all smooth)."""
    m = op.mesh
    nr = len(op.xs)
    ddo = np.zeros((nr, m.n), complex)
    ddi = np.zeros((m.n, m.n), complex)
    sd = np.zeros((nr, m.n), complex)
    nrm = m.normal
    for j, (p, w) in enumerate(op.pts):
        r_, dr_ = bor._geometry(op.xs[:, None, :], p[None], np.broadcast_to(nrm[j], p.shape)[None])
        ddo[:, j] = bor._dynamic(r_, dr_, k) @ w
        r2, dr2 = bor._geometry(
            op.xs[: m.n, None, :], p[None], np.broadcast_to(op.n_in[j], p.shape)[None]
        )
        ddi[:, j] = bor._dynamic(r2, dr2, k) @ w
        sd[:, j] = _single_dynamic(op.xs[:, None, :], p[None], k) @ w
    return ddo, ddi, sd


def solve(op: Operator, f_hz: float, z_s: complex, p_inc: np.ndarray):
    """The surface fields for incident fields `p_inc` at the collocation points (N + M,
    cases): (p, v), p (N, cases) the pressure on each panel's own side (p_out on the sheet),
    v (N, cases) the sheet's normal velocity (0 elsewhere); p_in on the sheet is p + z_s v."""
    m = op.mesh
    n = m.n
    w = 2 * np.pi * f_hz
    k = w / C_AIR
    ddo, ddi, sd = _dynamic_matrices(op, k)
    s = op.s0 + sd
    sheet = np.nonzero(m.kind == SHEET)[0]
    ns = len(sheet)
    out_rows = np.nonzero(m.kind != RIGID_IN)[0]
    in_rows = np.nonzero(m.kind != RIGID_OUT)[0]
    # unknowns: p (N: p_out on the sheet, p on the rigid panels), then v on the sheet (ns)
    nu = n + ns
    jwr = 1j * w * RHO_AIR
    rows = []
    rhs = []
    on_out = np.isin(np.arange(n), out_rows)
    on_in = np.isin(np.arange(n), in_rows)
    # outside equation: p_i (1 + sum_{j != i, j out} D0_ij)
    #   - sum_{j out} (D0_ij [j != i] + dD_ij) p_j - j w rho sum_sheet S_ij v_j = p_inc,i
    for i in list(out_rows) + list(range(n, len(op.xs))):
        a = np.zeros(nu, complex)
        d0 = np.where(on_out, op.d0_out[i], 0.0)
        if i < n:
            d0[i] = 0.0
            a[i] += 1.0 + d0.sum()
        a[:n] -= d0 + np.where(on_out, ddo[i], 0.0)
        a[n:] -= jwr * s[i, sheet]
        if i >= n:  # CHIEF: 0 = p_inc + int p dG/dn + j w rho int G v
            a = -a
            rows.append(a)
            rhs.append(-p_inc[i])
            continue
        rows.append(a)
        rhs.append(p_inc[i])
    # inside equation: sum_{j != i, j in} D0'_ij (p'_j - p'_i) + sum_j dD'_ij p'_j
    #                  + j w rho sum_sheet S_ij v_j = 0, p' = p + z_s v on the sheet
    zs_col = {int(j): n + t for t, j in enumerate(sheet)}
    for i in in_rows:
        a = np.zeros(nu, complex)
        d0 = np.where(on_in, op.d0_in[i], 0.0)
        d0[i] = 0.0
        coef = d0 + np.where(on_in, ddi[i], 0.0)
        coef[i] -= d0.sum()
        a[:n] += coef  # on p (p_out on the sheet)
        for j, col in zs_col.items():  # p' = p_out + z_s v on the sheet
            a[col] += coef[j] * z_s
        a[n:] += jwr * s[i, sheet]
        rows.append(a)
        rhs.append(np.zeros(p_inc.shape[1:], complex) if p_inc.ndim > 1 else 0.0)
    amat = np.array(rows)
    b = np.array(rhs)
    x = np.linalg.lstsq(amat, b, rcond=None)[0]
    p = x[:n]
    v = np.zeros_like(p)
    v[sheet] = x[n:]
    return p, v


def plane_wave_fields(op: Operator, f_hz: float, z_s: complex, theta_rad: np.ndarray):
    """`solve` for unit plane waves from theta (bor.plane_wave)."""
    k = 2 * np.pi * f_hz / C_AIR
    return solve(op, f_hz, z_s, bor.plane_wave(op.xs, k, theta_rad))

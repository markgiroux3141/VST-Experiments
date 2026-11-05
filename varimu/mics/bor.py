"""Sound pressure on a rigid body of revolution (MIC_ROOM_PLAN.md A3; K47_THEORY.md 5.3,
stages 2-3): a boundary-element solve of the scattered field, for a capsule's entries.

Only the azimuthal order 0 is needed. A diaphragm on the body's axis is averaged with an
axisymmetric weight (its mode shape, w = 1 - r^2 / a^2), and that average picks out the
order-0 part of the surface pressure, whatever the incidence: p = sum_m p_m(r, z) e^{j m
phi} and the integral of e^{j m phi} over phi vanishes for m != 0. So one 1-D integral
equation along the body's generating curve gives the entries exactly, at any angle and
for a point source at any distance. The order-0 part of the incident field is a phi-average
(a plane wave from theta: J0(k r sin theta) e^{j k z cos theta}).

The equation (e^{+j w t}, G = e^{-jkR} / (4 pi R), n out of the body; derived in the
docstring of `_system`): on the surface p / 2 = p_inc + PV int p dG/dn dS (the body rigid:
dp/dn = 0), and at points inside the body 0 = p_inc + int p dG/dn dS (CHIEF, Schenck 1968:
the extra rows remove the interior Dirichlet frequencies where the surface equation alone
isn't unique; least squares). Constant pressure per panel, collocation at the panel
midpoints; the panels are cones (straight segments of the generating curve revolved).

The kernel split: the static part dG0/dn (G0 = 1 / (4 pi R)) integrated over phi in
closed form (complete elliptic integrals K, E), the rest d(G - G0)/dn bounded and smooth
(-k^2 / (8 pi) at R = 0), integrated over phi by the trapezoid rule. The static part's
singularity is subtracted with Gauss's identity, the integral of dG0/dn over a closed
surface being -1/2 at a smooth surface point: so the self panel needs only the smooth
part (Guiggiani & Casalini's singularity subtraction, a standard BEM device).

The reference case is the rigid sphere's exact series (varimu.mics.free_field:
`sphere_entry_factors`, the point source's `sphere_point_factors`), tests/test_bor.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import ellipe, ellipk, j0

from varimu.devices.capsule import C_AIR

FRONT, REAR = 1, 2  # panel tags: the front / rear diaphragm


@dataclass(frozen=True)
class Mesh:
    """Panels of a body of revolution about z: the generating curve from the front pole
    (r = 0, z > 0) round to the rear pole, the body on the curve's right (so n = (-dz,
    dr) / ds points out). `tag` marks the diaphragms' panels (FRONT, REAR, else 0);
    `diaphragm_radius_m` is their mode shape's radius; `interior` are CHIEF points (r, z)
    inside the body."""

    p0: np.ndarray  # (N, 2) r, z
    p1: np.ndarray
    tag: np.ndarray  # (N,)
    diaphragm_radius_m: float
    interior: np.ndarray  # (M, 2)

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

    def face_weights(self, tag: int) -> np.ndarray:
        """Per panel, the diaphragm's mode shape 1 - r^2 / a^2 integrated over the
        panel's area (r ds), normalized: the entry pressure is weights @ p."""
        x, w = np.polynomial.legendre.leggauss(8)
        t = 0.5 * (x + 1)
        r = self.p0[:, 0, None] + t[None, :] * (self.p1[:, 0] - self.p0[:, 0])[:, None]
        a = self.diaphragm_radius_m
        shape = np.clip(1 - (r / a) ** 2, 0.0, None) * r
        out = 0.5 * self.length * (shape @ w)
        out = np.where(self.tag == tag, out, 0.0)
        total = out.sum()
        return out / total if total > 0 else out  # no such diaphragm: no entry


def _segment(a, b, n: int, grade: float = 1.0) -> np.ndarray:
    """n panels from a to b (endpoints, (n + 1, 2)); `grade` > 1 crowds them toward both
    ends (the edges of a body, where the field varies fastest)."""
    s = np.linspace(0.0, 1.0, n + 1)
    if grade != 1.0:
        s = 0.5 * (1 - np.cos(np.pi * s)) * (1 - 1 / grade) + s / grade
    return np.asarray(a, float) + s[:, None] * (np.asarray(b, float) - np.asarray(a, float))


def polyline_mesh(
    corners: list[tuple[float, float]],
    tags: list[int],
    panel_m: float,
    diaphragm_radius_m: float,
    interior: np.ndarray | None = None,
    grade: float = 2.0,
    segment_panel_m: list[float] | None = None,
) -> Mesh:
    """A mesh from the generating curve's corners (front pole first, rear pole last, both
    at r = 0), each segment tagged, about `panel_m` per panel (graded toward corners;
    `segment_panel_m` per segment in its place)."""
    p0, p1, tag = [], [], []
    sizes = segment_panel_m or [panel_m] * len(tags)
    for (a, b), t, size in zip(
        zip(corners[:-1], corners[1:], strict=True), tags, sizes, strict=True
    ):
        n = max(2, int(np.ceil(np.hypot(b[0] - a[0], b[1] - a[1]) / size)))
        pts = _segment(a, b, n, grade)
        p0.append(pts[:-1])
        p1.append(pts[1:])
        tag += [t] * n
    if interior is None:
        interior = _interior_points(np.array(corners))
    return Mesh(np.vstack(p0), np.vstack(p1), np.array(tag), diaphragm_radius_m, interior)


def _inside(poly: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Ray casting in the (r, z) half plane, the polygon closed along the axis."""
    x, y = pts[:, 0], pts[:, 1]
    inside = np.zeros(len(pts), bool)
    for (x0, y0), (x1, y1) in zip(poly, np.roll(poly, -1, axis=0), strict=True):
        cross = (y0 > y) != (y1 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= cross & (x < xc)
    return inside


def _interior_points(poly: np.ndarray, n: int = 12, seed: int = 0) -> np.ndarray:
    """CHIEF points: spread inside the body, away from its surface and the axis (a
    deterministic draw)."""
    rng = np.random.default_rng(seed)
    rmax, (zmin, zmax) = poly[:, 0].max(), (poly[:, 1].min(), poly[:, 1].max())
    out = []
    while len(out) < n:
        c = np.c_[
            rng.uniform(0.15, 0.85, 64) * rmax, zmin + rng.uniform(0.2, 0.8, 64) * (zmax - zmin)
        ]
        out += list(c[_inside(poly, c)])
    return np.array(out[:n])


def sphere_mesh(radius_m: float, cap_radius_m: float, panels: int = 160) -> Mesh:
    """The rigid sphere (the verification case), its polar caps (the area of a disk of
    `cap_radius_m`, as `free_field.sphere_entry_factors`) tagged as the diaphragms,
    whose mode shape there is 1 - (rho / rho_cap)^2 on rho = a sin(beta)."""
    alpha = np.arccos(1.0 - 0.5 * (cap_radius_m / radius_m) ** 2)
    n_cap = max(8, int(panels * alpha / np.pi))
    beta = np.r_[
        np.linspace(0, alpha, n_cap + 1),
        np.linspace(alpha, np.pi - alpha, panels - 2 * n_cap + 1)[1:],
        np.linspace(np.pi - alpha, np.pi, n_cap + 1)[1:],
    ]
    pts = radius_m * np.c_[np.sin(beta), np.cos(beta)]
    tag = np.zeros(len(beta) - 1, int)
    tag[:n_cap], tag[-n_cap:] = FRONT, REAR
    interior = radius_m * np.array([[0.2, 0.3], [0.5, -0.1], [0.3, -0.55], [0.6, 0.4], [0.1, -0.2]])
    # the caps' mode shape is in rho = r (the panels' r), its radius the cap's rim
    return Mesh(pts[:-1], pts[1:], tag, radius_m * np.sin(alpha), interior)


BODY_FIELDS = (
    "radius_m",  # the body behind the clamping rings
    "rim_radius_m",  # the middle rim (a flange round the backplate's edge)
    "rim_thickness_m",
    "spacing_m",  # diaphragm to diaphragm
    "ring_proud_m",  # the clamping rings' faces ahead of the diaphragms
)


def capsule_mesh(body: dict, diaphragm_radius_m: float, panel_m: float = 0.5e-3) -> Mesh:
    """A dual-diaphragm capsule as a rigid body of revolution (`body`: BODY_FIELDS): the
    diaphragms (radius `diaphragm_radius_m`) on its two faces `spacing_m` apart, each
    framed by a clamping ring `ring_proud_m` proud of it out to `radius_m`, a middle rim
    out to `rim_radius_m`. The diaphragms are rigid here: their motion's own radiation is
    the network's (its radiation mass), the BEM gives the blocked pressure."""
    a = diaphragm_radius_m
    zd = 0.5 * body["spacing_m"]
    zr = zd + body["ring_proud_m"]
    rb, rr, tr = body["radius_m"], body["rim_radius_m"], 0.5 * body["rim_thickness_m"]
    if not (a < rb <= rr and tr < zr):
        raise ValueError(
            f"capsule body: need diaphragm < radius <= rim, rim inside the faces ({body})"
        )
    c = [(0.0, zd), (a, zd)]
    t = [FRONT]
    if zr > zd:
        c.append((a, zr))
        t.append(0)
    c += [(rb, zr), (rb, tr)]
    t += [0, 0]
    if rr > rb:
        c += [(rr, tr), (rr, -tr), (rb, -tr)]
        t += [0, 0, 0]
    else:
        c.append((rb, -tr))
        t.append(0)
    c.append((rb, -zr))
    t.append(0)
    if zr > zd:
        c.append((a, -zr))
        t.append(0)
    c += [(a, -zd), (0.0, -zd)]
    t += [0, REAR]
    return polyline_mesh(c, t, panel_m, a)


PRESSURE_BODY_FIELDS = (
    "radius_m",  # the housing (capsule and preamplifier) behind the diaphragm's face
    "length_m",  # from the diaphragm's face to the housing's back end
)


def pressure_mesh(body: dict, diaphragm_radius_m: float, panel_m: float = 0.5e-3) -> Mesh:
    """A pressure capsule on its housing (`body`: form `cylinder`, PRESSURE_BODY_FIELDS):
    the diaphragm (radius `diaphragm_radius_m`) at the origin facing +z, flush with the
    housing's face out to `radius_m`, the housing a cylinder `length_m` long. Panels grow
    to 4 panel_m along the housing's side, away from the diaphragm."""
    a, rb, length = diaphragm_radius_m, body["radius_m"], body["length_m"]
    if not (a < rb and length > rb):
        raise ValueError(f"pressure body: need diaphragm < radius < length ({body})")
    c = [(0.0, 0.0), (a, 0.0), (rb, 0.0), (rb, -length), (0.0, -length)]
    t = [FRONT, 0, 0, 0]
    return polyline_mesh(
        c, t, panel_m, a, segment_panel_m=[panel_m, panel_m, 4 * panel_m, 2 * panel_m]
    )


def body_mesh(body: dict, diaphragm_radius_m: float) -> Mesh:
    """The mesh of a capsule's `body` by its `form`: `cylinder` (a pressure capsule on its
    housing, `pressure_mesh`), else the dual-diaphragm capsule (`capsule_mesh`)."""
    if body.get("form") == "cylinder":
        return pressure_mesh(body, diaphragm_radius_m)
    return capsule_mesh(body, diaphragm_radius_m)


# --- the kernels ---

_GL = np.polynomial.legendre.leggauss(8)
_GL_NEAR = np.polynomial.legendre.leggauss(8)
_NEAR_SUB = 12  # sub-panels for a panel near the collocation point
_PHI = 48  # trapezoid points in phi on [0, pi] (the integrand is even)


def _quad_points(m: Mesh, idx: np.ndarray, sub: int, gl) -> tuple[np.ndarray, np.ndarray]:
    """Gauss points on panels `idx` (each cut into `sub` pieces): positions (len, q, 2)
    and weights per unit generating length times r' (the ring's circumference / 2 pi)."""
    x, w = gl
    t = ((np.arange(sub)[:, None] + 0.5 * (x[None, :] + 1)) / sub).ravel()
    ww = np.tile(w / (2 * sub), sub)
    a, b = m.p0[idx], m.p1[idx]
    pts = a[:, None, :] + t[None, :, None] * (b - a)[:, None, :]
    wt = ww[None, :] * m.length[idx][:, None] * pts[..., 0]
    return pts, wt


def _static_ring(x: np.ndarray, y: np.ndarray, n: np.ndarray) -> np.ndarray:
    """The phi-integral of dG0/dn_y over the ring through y (per r' dphi: the caller's
    weight carries r'), at points x (..., 2), ring points y (..., 2), normals n (..., 2).
    dG0/dn_y = -(y - x).n / (4 pi R^3), R^2 = A - B cos(phi), A = r^2 + r'^2 + dz^2,
    B = 2 r r': with I1 = int dphi / R = 4 K(m) / sqrt(A + B), I3 = int dphi / R^3 =
    4 E(m) / ((A - B) sqrt(A + B)), m = 2B / (A + B), and int cos(phi) / R^3 = (A I3 - I1)
    / B (a series in B / A where that cancels)."""
    r, z = x[..., 0], x[..., 1]
    rp, zp = y[..., 0], y[..., 1]
    dz = zp - z
    A = r * r + rp * rp + dz * dz
    B = 2 * r * rp
    mpar = np.clip(2 * B / (A + B), 0.0, 1.0 - 1e-16)
    s = np.sqrt(A + B)
    i1 = 4 * ellipk(mpar) / s
    i3 = 4 * ellipe(mpar) / ((A - B) * s)
    q = B / A
    with np.errstate(divide="ignore", invalid="ignore"):
        ic3 = np.where(
            q > 1e-3,
            (A * i3 - i1) / np.where(B > 0, B, 1.0),
            # int cos(phi) (A - B cos phi)^(-3/2): 3 pi q / 2 (1 + 5 q^2 / 8) A^(-3/2)
            1.5 * np.pi * q * (1 + 0.625 * q * q) / A**1.5,
        )
    return -((rp * n[..., 0] + dz * n[..., 1]) * i3 - r * n[..., 0] * ic3) / (4 * np.pi)


def _geometry(x: np.ndarray, y: np.ndarray, n: np.ndarray):
    """R and dR/dn_y on the phi grid (x (..., 2), y (..., 2) -> (..., PHI))."""
    phi = np.linspace(0.0, np.pi, _PHI + 1)
    c = np.cos(phi)
    r, z = x[..., 0, None], x[..., 1, None]
    rp, zp = y[..., 0, None], y[..., 1, None]
    R = np.sqrt(np.maximum(r * r + rp * rp - 2 * r * rp * c + (zp - z) ** 2, 1e-300))
    dRdn = ((rp - r * c) * n[..., 0, None] + (zp - z) * n[..., 1, None]) / R
    return R, dRdn


_PHI_W = np.full(_PHI + 1, np.pi / _PHI)
_PHI_W[[0, -1]] *= 0.5
_PHI_W *= 2.0  # [0, pi] -> the whole ring


def _dynamic(R: np.ndarray, dRdn: np.ndarray, k: float) -> np.ndarray:
    """The phi-integral of d(G - G0)/dn_y: [1 - (1 + jkR) e^{-jkR}] / (4 pi R^2) dR/dn
    (bounded: -k^2 / (8 pi) at R = 0)."""
    x = 1j * k * R
    em = np.expm1(-x)
    f = (-(1 + x) * em - x) / (4 * np.pi * R * R)
    return (f * dRdn) @ _PHI_W


@dataclass
class Operator:
    """A mesh's frequency-independent parts: the static matrix (off-diagonal) and the
    geometry on the Gauss x phi grid, for the surface rows and the CHIEF rows."""

    mesh: Mesh
    d0: np.ndarray  # (N + M, N): static kernel, the surface rows' diagonal 0
    R: np.ndarray  # (N + M, N, q, PHI + 1)
    dRdn: np.ndarray
    wt: np.ndarray  # (N, q)


def operator(m: Mesh) -> Operator:
    pts, wt = _quad_points(m, np.arange(m.n), 1, _GL)
    nrm = m.normal
    xs = np.vstack([m.mid, m.interior])
    nr = len(xs)
    d0 = np.einsum(
        "ijq,jq->ij", _static_ring(xs[:, None, None, :], pts[None], nrm[None, :, None, :]), wt
    )
    # near panels: subdivided Gauss (the static kernel has a log singularity on the curve)
    dist = np.min(np.hypot(*(xs[:, None, None, :] - pts[None]).transpose(3, 0, 1, 2)), axis=2)
    near = (dist < 2.0 * m.length[None, :]) & (np.arange(nr)[:, None] != np.arange(m.n)[None, :])
    for i, j in zip(*np.nonzero(near), strict=True):
        p, w = _quad_points(m, np.array([j]), _NEAR_SUB, _GL_NEAR)
        d0[i, j] = np.sum(_static_ring(xs[i], p[0], nrm[j]) * w[0])
    d0[np.arange(m.n), np.arange(m.n)] = 0.0
    R, dRdn = _geometry(xs[:, None, None, :], pts[None], nrm[None, :, None, :])
    return Operator(m, d0, R, dRdn, wt)


def _system(op: Operator, k: float) -> np.ndarray:
    """The (N + M) x N system matrix at wavenumber k: surface rows
    p_i (1 + sum_{j != i} D0_ij) - sum_{j != i} D0_ij p_j - sum_j dD_ij p_j = p_inc,i
    (the surface equation p / 2 = p_inc + PV int p dG/dn with int dG0/dn = -1/2 used to
    subtract the static singularity), CHIEF rows -sum_j D_cj p_j = p_inc(c)."""
    n = op.mesh.n
    dd = np.einsum("ijq,jq->ij", _dynamic(op.R, op.dRdn, k), op.wt)
    a = -(op.d0 + dd)
    a[np.arange(n), np.arange(n)] += 1.0 + op.d0[:n].sum(axis=1)
    return a


def plane_wave(rz: np.ndarray, k: float, theta_rad: np.ndarray) -> np.ndarray:
    """The order-0 part of a unit plane wave from theta (0: from +z), (points, angles)."""
    r, z = rz[:, 0, None], rz[:, 1, None]
    th = np.atleast_1d(theta_rad)[None, :]
    return j0(k * r * np.sin(th)) * np.exp(1j * k * z * np.cos(th))


def point_source(rz: np.ndarray, k: float, theta_rad: np.ndarray, distance_m: float) -> np.ndarray:
    """The order-0 part of a point source `distance_m` from the origin toward theta, its
    free-field pressure 1 at the origin: r_s e^{-jk(|x - x_s| - r_s)} / |x - x_s|, averaged
    over the azimuth (trapezoid, 128 points)."""
    phi = np.linspace(0, 2 * np.pi, 128, endpoint=False)
    r, z = rz[:, 0, None, None], rz[:, 1, None, None]
    th = np.atleast_1d(theta_rad)[None, :, None]
    xs, zs = distance_m * np.sin(th), distance_m * np.cos(th)
    d = np.sqrt((r * np.cos(phi) - xs) ** 2 + (r * np.sin(phi)) ** 2 + (z - zs) ** 2)
    return np.mean(distance_m / d * np.exp(-1j * k * (d - distance_m)), axis=2)


def surface_pressure(
    op: Operator, f_hz: float, theta_rad: np.ndarray, distance_m: float = np.inf
) -> np.ndarray:
    """The order-0 surface pressure per panel (N, angles) per unit incident pressure at
    the origin."""
    k = 2 * np.pi * f_hz / C_AIR
    xs = np.vstack([op.mesh.mid, op.mesh.interior])
    if np.isinf(distance_m):
        rhs = plane_wave(xs, k, theta_rad)
    else:
        rhs = point_source(xs, k, theta_rad, distance_m)
    return np.linalg.lstsq(_system(op, k), rhs, rcond=None)[0]


def entry_factors(
    op: Operator, f_hz: np.ndarray, theta_rad: np.ndarray, distance_m: float = np.inf
) -> tuple[np.ndarray, np.ndarray]:
    """The front and rear diaphragms' mode-weighted pressures (freqs, angles) per unit
    incident pressure at the origin (the capsule's centre)."""
    wf, wr = op.mesh.face_weights(FRONT), op.mesh.face_weights(REAR)
    out_f, out_r = [], []
    for f in np.atleast_1d(f_hz):
        p = surface_pressure(op, float(f), theta_rad, distance_m)
        out_f.append(wf @ p)
        out_r.append(wr @ p)
    return np.array(out_f), np.array(out_r)


def entry_table(
    op: Operator, f_hz: np.ndarray, theta_rad: np.ndarray, distances_m: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """`entry_factors` over a grid, (freqs, distances, angles) each: one system per
    frequency, solved for every incidence at once (a distance np.inf is a plane wave)."""
    wf, wr = op.mesh.face_weights(FRONT), op.mesh.face_weights(REAR)
    xs = np.vstack([op.mesh.mid, op.mesh.interior])
    th = np.atleast_1d(theta_rad)
    nd, na = len(distances_m), len(th)
    out_f = np.zeros((len(f_hz), nd, na), complex)
    out_r = np.zeros_like(out_f)
    for i, f in enumerate(np.atleast_1d(f_hz)):
        k = 2 * np.pi * float(f) / C_AIR
        rhs = np.hstack(
            [plane_wave(xs, k, th) if np.isinf(d) else point_source(xs, k, th, float(d))
             for d in distances_m]
        )  # fmt: skip
        p = np.linalg.lstsq(_system(op, k), rhs, rcond=None)[0]
        out_f[i] = (wf @ p).reshape(nd, na)
        out_r[i] = (wr @ p).reshape(nd, na)
    return out_f, out_r

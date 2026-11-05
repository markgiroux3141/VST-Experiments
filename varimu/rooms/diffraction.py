"""Edge diffraction for the geometric model (docs/ROOM_LOOP_PLAN.md R11): first-order
Biot-Tolstoy-Medwin, as Svensson, Fred and Vanderkooy, "An analytic secondary source model
of edge diffraction impulse responses", JASA 106(5), 1999 (their eq. 10, the "BTM" impulse
response of a finite wedge).

Without it an object's shadow is total at every frequency: a gobo would block the bass as
well as the highs, and a source round an L-shaped room's corner would be heard only by
reflections. With it, the edge radiates into the shadow, more for long wavelengths, and the
sound is continuous across the shadow boundary (the diffracted wave jumps by half the direct
sound there, the direct sound by the other half).

**The edge.** A straight edge of length L from `a` along unit `e`, the wedge's faces meeting
there; in the plane across the edge, angles run from face 1 (direction `t1`, theta = 0)
through the air (toward `y1`, face 1's air side) to face 2 at theta_w, the wedge's open angle
in the air. nu = pi / theta_w. A point is (r, theta, z) round the edge.

**The impulse response** from a point source (free-field pressure 1 / r at r, the room's
normalization) at S to a receiver at R:

  h(t) = -(nu / 4 pi) sum_i int_0^L delta(t - (m + l) / c) beta_i / (m l) dz,
  beta_i = sin(nu phi_i) / (cosh(nu eta) - cos(nu phi_i)),
  phi = pi +- theta_S +- theta_R,  eta = acosh((m l + (z - z_S)(z - z_R)) / (r_S r_R)),

m and l the distances from S and R to the edge point z. The integral is sampled on the
project's grid (the edge cut so each piece's delay moves by under half a sample, much finer
near the apex where the shortest path touches the edge: near a shadow or reflection boundary
the integrand peaks there) and each piece added to the impulse response at its delay
(linear between samples).

**Which edges.** Objects' edges (varimu.rooms.polyroom: a box's 12, each a right-angled wedge,
nu = 2 / 3; a thin panel's 4 round its outline, each a plate's edge, nu = 1 / 2: its two
right angles closer than the wavelengths that matter) and a floor plan's reflex corners
(their vertical edges, theta_w the corner's angle in the room). Paths with at most one
reflection, before the edge or after it (the source's and the mic's first-order images: so a
source and a mic swapped hear the same), checked for visibility along the edge (each leg clear
of every face but the wedge's own; an image's leg through its face).
**Second order** (`paths2`): over two edges of one thick object that share a face (a
cabinet's front and back top edges), from the source to the mic directly: the edges' secondary
sources chained (Svensson & Calamia's double integral, both edges' BTM terms over the three
distances), times 1/2 for the path along the shared face. Checked in the limit: a thick
screen's two top edges as its thickness goes to 0 give the knife edge's first-order response
within 4% (0.35 dB). Thin panels need none (their edges are plates); between objects and with
reflections it is left out.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from varimu.separation.room import SPEED_OF_SOUND_M_S

VIS_POINTS = 24  # visibility checked at this many points along an edge (and the apex)


@dataclass
class Edge:
    a: np.ndarray
    e: np.ndarray
    length: float
    t1: np.ndarray
    y1: np.ndarray
    theta_w: float
    skip: tuple[int, ...]

    @property
    def nu(self) -> float:
        return np.pi / self.theta_w

    def coords(self, p: np.ndarray) -> tuple[float, float, float]:
        """(r, theta, z) of a point round the edge."""
        q = np.asarray(p, float) - self.a
        z = float(q @ self.e)
        qp = q - z * self.e
        th = float(np.arctan2(qp @ self.y1, qp @ self.t1)) % (2 * np.pi)
        return float(np.linalg.norm(qp)), th, z

    def point(self, z):
        return self.a[None, :] + np.asarray(z, float)[:, None] * self.e[None, :]


def edges(room) -> list[Edge]:
    """Every diffracting edge of a PolyRoom (the module docstring)."""
    out = []
    n_room = room.n_room_faces
    for bi, b in enumerate(room.boxes):
        f0 = n_room + 6 * bi
        u, half = b.axes, 0.5 * b.size_m
        if b.thin:
            at = int(np.argmin(b.size_m))  # the thickness
            others = [a for a in range(3) if a != at]
            for ae in others:  # the edge lies at +-half along ae, runs along ar
                ar = [a for a in others if a != ae][0]
                for s in (1, -1):
                    a0 = b.center_m + s * half[ae] * u[:, ae] - half[ar] * u[:, ar]
                    out.append(Edge(a0, u[:, ar], float(b.size_m[ar]), -s * u[:, ae],
                                    u[:, at], 2 * np.pi, tuple(range(f0, f0 + 6))))  # fmt: skip
            continue
        for a3 in range(3):  # edges along axis a3
            a1, a2 = [a for a in range(3) if a != a3]
            for s1 in (1, -1):
                for s2 in (1, -1):
                    n1, n2 = s1 * u[:, a1], s2 * u[:, a2]
                    a0 = b.center_m + s1 * half[a1] * u[:, a1] + s2 * half[a2] * u[:, a2]
                    a0 = a0 - half[a3] * u[:, a3]
                    k1 = f0 + 2 * a1 + (0 if s1 > 0 else 1)
                    k2 = f0 + 2 * a2 + (0 if s2 > 0 else 1)
                    out.append(Edge(a0, u[:, a3], float(b.size_m[a3]), -n2, n1, 1.5 * np.pi,
                                    (k1, k2)))  # fmt: skip
    fl = room.floor
    n = len(fl)
    for i in range(n):
        vp, v, vn = fl[i - 1], fl[i], fl[(i + 1) % n]
        d1, d2 = v - vp, vn - v
        if d1[0] * d2[1] - d1[1] * d2[0] >= -1e-12:
            continue  # convex (or straight): no edge into the air
        t1 = np.r_[(vp - v) / np.linalg.norm(vp - v), 0.0]
        y1 = np.r_[-d1[1], d1[0], 0.0] / np.linalg.norm(d1)  # wall i - 1's inward normal
        t2 = np.r_[(vn - v) / np.linalg.norm(vn - v), 0.0]
        th_w = float(np.arctan2(t2 @ y1, t2 @ t1)) % (2 * np.pi)
        h = float(room.height_at(v))
        wall_prev, wall = 1 + (i - 1) % n, 1 + i
        out.append(Edge(np.r_[v, 0.0], np.array([0.0, 0.0, 1.0]), h, t1, y1, th_w,
                        (wall_prev, wall)))  # fmt: skip
    return out


def btm(edge: Edge, s: np.ndarray, r: np.ndarray, fs: float, mask=None, c=SPEED_OF_SOUND_M_S):
    """The edge's impulse response from s to r (the module docstring): (first sample, h), or
    None when nothing is left. `mask(z)` (optional) says which edge points both see."""
    rs, ths, zs = edge.coords(s)
    rr, thr, zr = edge.coords(r)
    if rs < 1e-6 or rr < 1e-6:
        return None
    if ths > edge.theta_w + 1e-9 or thr > edge.theta_w + 1e-9:
        return None  # inside the wedge
    big_l = edge.length
    dz = 0.5 * c / fs / 2.0  # half a sample of path, the delay moving by up to 2 dz
    apex = float(np.clip(zs + (zr - zs) * rs / (rs + rr), 0.0, big_l))
    coarse = np.linspace(0.0, big_l, max(int(np.ceil(big_l / dz)), 2) + 1)
    fine = np.geomspace(1e-7, 4 * dz, 160)
    zz = np.unique(np.clip(np.r_[coarse, apex, apex - fine, apex + fine], 0.0, big_l))
    zm = 0.5 * (zz[1:] + zz[:-1])
    w = np.diff(zz)
    if mask is not None:
        keep = mask(zm)
        zm, w = zm[keep], w[keep]
        if len(zm) == 0:
            return None
    ds_, dr_ = zm - zs, zm - zr
    m = np.sqrt(rs**2 + ds_**2)
    ll = np.sqrt(rr**2 + dr_**2)
    # eta = acosh(1 + x) with x computed without cancellation near the apex:
    # (m l)^2 - (rs rr - ds dr)^2 = (rs dr + rr ds)^2
    x = (rs * dr_ + rr * ds_) ** 2 / (rs * rr * (m * ll + rs * rr - ds_ * dr_))
    eta = 2 * np.arcsinh(np.sqrt(0.5 * x))
    nu = edge.nu
    acc = np.zeros_like(zm)
    sh2 = np.sinh(0.5 * nu * eta) ** 2
    for phi in (np.pi + ths + thr, np.pi + ths - thr, np.pi - ths + thr, np.pi - ths - thr):
        # cosh(nu eta) - cos(nu phi) as 2 (sinh^2(nu eta / 2) + sin^2(nu phi / 2)): >= 0, no
        # cancellation (on a shadow or reflection boundary at the apex both terms vanish)
        den = 2 * (sh2 + np.sin(0.5 * nu * phi) ** 2)
        acc += np.sin(nu * phi) / np.maximum(den, 1e-30)
    g = -(nu / (4 * np.pi)) * acc / (m * ll) * w
    t = (m + ll) / c * fs
    n0 = int(np.floor(t.min()))
    nlen = int(np.ceil(t.max())) - n0 + 2
    h = np.zeros(nlen)
    i0 = np.floor(t).astype(int) - n0
    fr = t - np.floor(t)
    np.add.at(h, i0, g * (1 - fr))
    np.add.at(h, i0 + 1, g * fr)
    return n0, h


@dataclass
class DiffractionPath:
    n0: int  # the first sample
    h: np.ndarray  # the edge's response from there
    apex_m: np.ndarray  # where the shortest path touches the edge
    log_beta: np.ndarray  # (bands,) the image's walls, log of their product
    path_m: float  # the shortest path's length (air absorption)
    start_m: np.ndarray = None  # the source or its image the path starts from
    start_face: int = -1  # the source image's face (-1: the source itself)
    arrive_m: np.ndarray = None  # where the sound reaches the mic from (apex, or a reflection)


def _leg(room, real, img, fi, pv, skip_m):
    """Which edge points pv a leg from `real` reaches: straight (fi < 0, img = real) or by a
    reflection off face fi (img the mirror image): the crossing on the face, both parts clear.
    Returns (ok, the reflection points or None)."""
    n = len(pv)
    if fi < 0:
        return room.segment_clear(np.repeat(real[None, :], n, 0), pv, skip_m), None
    f = room.faces[fi]
    d = pv - img
    nd = d @ f.normal
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (f.d - img @ f.normal) / nd
        q = np.nan_to_num(img[None, :] + t[:, None] * d)
    on = (np.abs(nd) > 1e-12) & (t > 1e-9) & (t < 1 - 1e-9)
    on &= room.on_face(f, q)
    if not np.any(on):
        return on, q
    sk_f = np.tile(np.array((fi,) + (-1,) * 6)[None, :], (n, 1))
    leg1 = room.segment_clear(np.repeat(real[None, :], n, 0), q, sk_f)
    sk2 = skip_m.copy()
    sk2[:, -1] = fi
    leg2 = room.segment_clear(q, pv, sk2)
    return on & leg1 & leg2, q


def paths(room, source: np.ndarray, mic: np.ndarray, fs: float, beta: np.ndarray):
    """Every first-order diffraction path from a source to a mic in a PolyRoom, with at most one
    reflection before or after the edge (the source's or the mic's first-order images: the
    paths are reciprocal, a source and a mic swapped hear the same); `beta` the faces'
    reflection amplitudes per band (faces, bands)."""
    from varimu.rooms import polyroom

    src = np.asarray(source, float)
    mic = np.asarray(mic, float)
    eds = edges(room)
    if not eds:
        return []

    def images_of(p):
        out = [(p, -1)]
        for fi, f in enumerate(room.faces):
            if (p @ f.normal - f.d) > 1e-9:
                out.append((polyroom._mirror(p, f), fi))
        return out

    starts, ends = images_of(src), images_of(mic)
    out = []
    nb = beta.shape[1]
    for ed in eds:
        zv = np.linspace(0.0, ed.length, VIS_POINTS)
        pv = ed.point(zv)
        skip_m = np.tile(np.array(ed.skip + (-1,) * (7 - len(ed.skip)))[None, :], (len(pv), 1))
        legs_s = {fi: _leg(room, src, s_pos, fi, pv, skip_m) for s_pos, fi in starts}
        legs_r = {fi: _leg(room, mic, r_pos, fi, pv, skip_m) for r_pos, fi in ends}
        for s_pos, fs_ in starts:
            ok_s = legs_s[fs_][0]
            if not np.any(ok_s):
                continue
            for r_pos, fr_ in ends:
                if fs_ >= 0 and fr_ >= 0:
                    continue  # first order: one reflection at most
                ok = ok_s & legs_r[fr_][0]
                if not np.any(ok):
                    continue

                def mask(z, ok=ok, zv=zv):
                    j = np.round(z / max(zv[1] - zv[0], 1e-12)).astype(int)
                    return ok[np.clip(j, 0, len(ok) - 1)]

                res = btm(ed, s_pos, r_pos, fs, mask=mask)
                if res is None:
                    continue
                n0, h = res
                if not np.any(h):
                    continue
                rs, ths, zs = ed.coords(s_pos)
                rr, thr, zr = ed.coords(r_pos)
                apex_z = float(np.clip(zs + (zr - zs) * rs / (rs + rr), 0.0, ed.length))
                apex = ed.point([apex_z])[0]
                plen = float(np.linalg.norm(apex - s_pos) + np.linalg.norm(r_pos - apex))
                face = fs_ if fs_ >= 0 else fr_
                lb = np.log(np.maximum(beta[face], 1e-300)) if face >= 0 else np.zeros(nb)
                arrive = apex
                if fr_ >= 0:  # the sound reaches the mic from its reflection off face fr_
                    f = room.faces[fr_]
                    d = apex - r_pos
                    nd = d @ f.normal
                    if abs(nd) > 1e-12:
                        arrive = r_pos + ((f.d - r_pos @ f.normal) / nd) * d
                out.append(DiffractionPath(n0, h, apex, lb, plen, s_pos, fs_, arrive))
    return out


def _coords_many(ed: Edge, p: np.ndarray):
    q = p - ed.a
    z = q @ ed.e
    qp = q - z[:, None] * ed.e
    th = np.arctan2(qp @ ed.y1, qp @ ed.t1) % (2 * np.pi)
    return np.linalg.norm(qp, axis=1), th, z


def _beta(nu, eta, ths, thr):
    sh2 = np.sinh(0.5 * nu * eta) ** 2
    acc = 0.0
    for phi in (np.pi + ths + thr, np.pi + ths - thr, np.pi - ths + thr, np.pi - ths - thr):
        acc = acc + np.sin(nu * phi) / np.maximum(2 * (sh2 + np.sin(0.5 * nu * phi) ** 2), 1e-30)
    return acc


def _eta(rs, zs, rr, zr, z):
    ds, dr = z - zs, z - zr
    m = np.sqrt(rs**2 + ds**2)
    ll = np.sqrt(rr**2 + dr**2)
    x = (rs * dr + rr * ds) ** 2 / (rs * rr * (m * ll + rs * rr - ds * dr))
    return 2 * np.arcsinh(np.sqrt(0.5 * x))


def btm2(e1: Edge, e2: Edge, s, r, fs: float, mask1=None, mask2=None, factor: float = 0.5,
         c=SPEED_OF_SOUND_M_S, max_points: int = 500):  # fmt: skip
    """Second-order diffraction, edge 1 then edge 2 (the module docstring): (first sample, h,
    the shortest path's points on each edge), or None. `factor` 1/2 for edges sharing a face.
    Each edge is sampled at a quarter of a sample's path, at most `max_points` along it (a
    second-order path carries little above a few kHz)."""
    dz1 = max(0.25 * c / fs, e1.length / max_points)
    dz2 = max(0.25 * c / fs, e2.length / max_points)
    if abs(e1.e @ e2.e) > 0.99:  # parallel edges: resolve the 1 / n peak between them
        w = e2.a - e1.a
        gap = float(np.linalg.norm(w - (w @ e1.e) * e1.e))
        dz1 = max(min(dz1, 0.5 * gap), 0.25 * c / fs)
        dz2 = max(min(dz2, 0.5 * gap), 0.25 * c / fs)
    z1 = np.arange(0.5 * dz1, e1.length, dz1)
    z2 = np.arange(0.5 * dz2, e2.length, dz2)
    if mask1 is not None:
        z1 = z1[mask1(z1)]
    if mask2 is not None:
        z2 = z2[mask2(z2)]
    if len(z1) == 0 or len(z2) == 0:
        return None
    s, r = np.asarray(s, float), np.asarray(r, float)
    p1 = e1.a + z1[:, None] * e1.e
    p2 = e2.a + z2[:, None] * e2.e
    rs, ths, zs = _coords_many(e1, s[None, :])
    rq, thq, zq = _coords_many(e1, p2)  # edge 2's points round edge 1: its receivers
    rp, thp, zp = _coords_many(e2, p1)  # edge 1's points round edge 2: its sources
    rr, thr, zr = _coords_many(e2, r[None, :])
    if rs[0] < 1e-6 or rr[0] < 1e-6 or np.any(rq < 1e-9) or np.any(rp < 1e-9):
        return None
    if ths[0] > e1.theta_w + 1e-9 or thr[0] > e2.theta_w + 1e-9:
        return None
    b1 = _beta(e1.nu, _eta(rs[0], zs[0], rq[None, :], zq[None, :], z1[:, None]), ths[0],
               thq[None, :])  # fmt: skip
    b2 = _beta(e2.nu, _eta(rp[:, None], zp[:, None], rr[0], zr[0], z2[None, :]), thp[:, None],
               thr[0])  # fmt: skip
    m = np.sqrt(rs[0] ** 2 + (z1 - zs[0]) ** 2)[:, None]
    n = np.linalg.norm(p1[:, None, :] - p2[None, :, :], axis=2)
    ll = np.sqrt(rr[0] ** 2 + (z2 - zr[0]) ** 2)[None, :]
    g = factor * (e1.nu * e2.nu / (16 * np.pi**2)) * b1 * b2 / (m * n * ll) * dz1 * dz2
    t = (m + n + ll) / c * fs
    n0 = int(np.floor(t.min()))
    h = np.zeros(int(np.ceil(t.max())) - n0 + 2)
    i0 = (np.floor(t).astype(int) - n0).ravel()
    fr = (t - np.floor(t)).ravel()
    np.add.at(h, i0, g.ravel() * (1 - fr))
    np.add.at(h, i0 + 1, g.ravel() * fr)
    k = np.unravel_index(np.argmin(t), t.shape)
    return n0, h, p1[k[0]], p2[k[1]]


def paths2(room, source: np.ndarray, mic: np.ndarray, fs: float, nb: int):
    """Second-order diffraction paths (the module docstring): over two edges of one thick
    object sharing a face, from the source to the mic directly; only where the source doesn't
    see the mic (in the shadows they fill; where the direct sound arrives they are far
    weaker than it and its first-order neighbours, and cost the most)."""
    src = np.asarray(source, float)
    mic = np.asarray(mic, float)
    if room.segment_clear(src[None, :], mic[None, :], np.full((1, 1), -1))[0]:
        return []
    eds = [e for e in edges(room) if len(e.skip) == 2 and e.skip[0] >= room.n_room_faces]
    out = []
    vis_s, vis_r = {}, {}
    for i, ed in enumerate(eds):
        zv = np.linspace(0.0, ed.length, VIS_POINTS)
        pv = ed.point(zv)
        sk = np.tile(np.array(ed.skip + (-1,) * 5)[None, :], (len(pv), 1))
        vis_s[i] = (zv, room.segment_clear(np.repeat(src[None, :], len(pv), 0), pv, sk))
        vis_r[i] = (zv, room.segment_clear(pv, np.repeat(mic[None, :], len(pv), 0), sk))

    def mask_of(zv, ok):
        def mask(z):
            j = np.round(z / max(zv[1] - zv[0], 1e-12)).astype(int)
            return ok[np.clip(j, 0, len(ok) - 1)]

        return mask

    for i, e1 in enumerate(eds):
        if not np.any(vis_s[i][1]):
            continue
        for j, e2 in enumerate(eds):
            if i == j or not set(e1.skip) & set(e2.skip) or not np.any(vis_r[j][1]):
                continue
            res = btm2(e1, e2, src, mic, fs, mask_of(*vis_s[i]), mask_of(*vis_r[j]))
            if res is None or not np.any(res[1]):
                continue
            n0, h, a1, a2 = res
            legs = (a1 - src, a2 - a1, mic - a2)
            plen = float(sum(np.linalg.norm(v) for v in legs))
            out.append(DiffractionPath(n0, h, a1, np.zeros(nb), plen, src, -1, a2))
    return out

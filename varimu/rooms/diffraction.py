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
(their vertical edges, theta_w the corner's angle in the room). Paths from the source and
its first-order images (a reflection then the edge), checked for visibility along the edge
(each leg clear of every face but the wedge's own; an image's leg through its face).
Second-order diffraction (over a box's two edges) is left out: deep shadows behind thick
objects come out too dark.
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
    m = np.sqrt(rs**2 + (zm - zs) ** 2)
    ll = np.sqrt(rr**2 + (zm - zr) ** 2)
    arg = np.maximum((m * ll + (zm - zs) * (zm - zr)) / (rs * rr), 1.0)
    eta = np.arccosh(arg)
    nu = edge.nu
    acc = np.zeros_like(zm)
    ch = np.cosh(nu * eta)
    for phi in (np.pi + ths + thr, np.pi + ths - thr, np.pi - ths + thr, np.pi - ths - thr):
        den = ch - np.cos(nu * phi)
        acc += np.sin(nu * phi) / np.where(np.abs(den) < 1e-300, 1e-300, den)
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
    apex_m: np.ndarray  # where the shortest path touches the edge (the arrival's direction)
    log_beta: np.ndarray  # (bands,) the image's walls, log of their product
    path_m: float  # the shortest path's length (air absorption)
    start_m: np.ndarray = None  # the source or its image the path starts from
    start_face: int = -1  # the image's face (-1: the source itself)


def paths(room, source: np.ndarray, mic: np.ndarray, fs: float, beta: np.ndarray):
    """Every first-order diffraction path from a source (and its first-order images) to a mic
    in a PolyRoom; `beta` the faces' reflection amplitudes per band (faces, bands)."""
    from varimu.rooms import polyroom

    src = np.asarray(source, float)
    mic = np.asarray(mic, float)
    eds = edges(room)
    if not eds:
        return []
    starts = [(src, -1)]
    for fi, f in enumerate(room.faces):
        if (src @ f.normal - f.d) > 1e-9:
            starts.append((polyroom._mirror(src, f), fi))
    out = []
    nb = beta.shape[1]
    for ed in eds:
        zv = np.linspace(0.0, ed.length, VIS_POINTS)
        pv = ed.point(zv)
        # the leg to the mic, along the edge
        skip_m = np.tile(np.array(ed.skip + (-1,) * (7 - len(ed.skip)))[None, :], (len(pv), 1))
        to_mic = room.segment_clear(pv, np.repeat(mic[None, :], len(pv), 0), skip_m)
        if not np.any(to_mic):
            continue
        for s_pos, fi in starts:
            if fi < 0:
                leg = room.segment_clear(np.repeat(s_pos[None, :], len(pv), 0), pv, skip_m)
                ok = leg & to_mic
                lb = np.zeros(nb)
            else:
                f = room.faces[fi]
                d = pv - s_pos
                nd = d @ f.normal
                with np.errstate(divide="ignore", invalid="ignore"):
                    t = (f.d - s_pos @ f.normal) / nd
                q = s_pos[None, :] + t[:, None] * d
                on = (np.abs(nd) > 1e-12) & (t > 1e-9) & (t < 1 - 1e-9)
                on &= room.on_face(f, np.nan_to_num(q))
                if not np.any(on):
                    continue
                sk_f = np.tile(np.array((fi,) + (-1,) * 5)[None, :], (len(pv), 1))
                leg1 = room.segment_clear(np.repeat(src[None, :], len(pv), 0),
                                          np.nan_to_num(q), sk_f)  # fmt: skip
                sk2 = skip_m.copy()
                sk2[:, -1] = fi
                leg2 = room.segment_clear(np.nan_to_num(q), pv, sk2)
                ok = on & leg1 & leg2 & to_mic
                lb = np.log(np.maximum(beta[fi], 1e-300))
            if not np.any(ok):
                continue

            def mask(z, ok=ok, zv=zv):
                j = np.clip(np.round(z / max(zv[1] - zv[0], 1e-12)).astype(int), 0, len(ok) - 1)
                return ok[j]

            res = btm(ed, s_pos, mic, fs, mask=mask)
            if res is None:
                continue
            n0, h = res
            if not np.any(h):
                continue
            rs, ths, zs = ed.coords(s_pos)
            rr, thr, zr = ed.coords(mic)
            apex_z = float(np.clip(zs + (zr - zs) * rs / (rs + rr), 0.0, ed.length))
            apex = ed.point([apex_z])[0]
            plen = float(np.linalg.norm(apex - s_pos) + np.linalg.norm(mic - apex))
            out.append(DiffractionPath(n0, h, apex, lb, plen, s_pos, fi))
    return out

"""Rooms of any floor plan with sloped ceilings (docs/ROOM_LOOP_PLAN.md R6: "the square room
reflects a lot"): the geometric half of MIC_ROOM_PLAN.md A5's hybrid, on the CPU.

**Geometry.** A floor polygon (any simple polygon, convex or not, counterclockwise from
above; metres) at z = 0, vertical walls on its edges, and a ceiling z = h(u) that varies
along one direction u in the floor plane (`axis_deg`, counterclockwise from +x): `flat`
(h = height_m), `shed` (height_m at the low side to peak_m at the high side), `gable` (eaves
height_m on both sides, the ridge peak_m along the middle), `vault` (a barrel vault, an
elliptic arc from height_m at the sides to peak_m, as `facets` planes). Every surface is a
planar face: the floor, one face per wall (its top following the ceiling), one per ceiling
facet. A face carries its material (the room's walls / floor / ceiling).

**Early part: image sources** (Allen and Berkley for the shoebox; Borish, JASA 75(6), 1984
for arbitrary polyhedra): every sequence of up to `max_order` reflections is mirrored, the
source must lie in front of each face it is mirrored in, and a path is kept only when,
traced back from the mic, each reflection point lies inside its face and no segment leaves
the room (a non-convex room hides paths: an L-shaped room's other leg). The direct sound is
such a path too: a source round a corner is heard only by its reflections and the tail
(edge diffraction isn't modelled: A5's wave solver or Svensson's edge sources are where it
goes). Amplitudes as the shoebox's: per band sqrt(1 - alpha) per reflection, 1 / r, air.

**Late part: ray tracing for the decay.** Rays from the source (Fibonacci directions) bounce
specularly, or diffusely (Lambert) with the material's scattering coefficient, losing alpha
per band at each hit; the fraction of the emitted energy still travelling at time t, e_b(t)
(air included), is the room's energy decay: in a diffuse field the squared impulse response
at any point is <h^2(t)> = 4 pi c e_b(t) / V per second for a source whose free-field
pressure is 1 / r (the image-source density of a shoebox gives this exactly). So the tail's
level and its decay come from the shape: no Eyring, no hand-over matching. The tail is the
shoebox's shared plane-wave field (varimu.rooms.shoebox) with this envelope.

Scattering coefficients per material are provisional (model knowledge: ISO 17497-1 style
values for flat, furnished and treated surfaces).

**Objects** (ROOM_LOOP_PLAN.md R11): boxes in the room, each turned about the vertical
(`yaw_deg`) and tilted about its own width axis (`tilt_deg`): a gobo is a thin one, a riser a
low one, a piano's lid a tilted panel. Their six faces (outward normals, into the room's air)
follow the room's faces, so a room's own faces keep their indices. They reflect in the image
sources up to `OBJECT_MAX_ORDER` (the candidates grow with the faces to the power of the
order), occlude every path, take part in the rays and the wave solver's grid. Their edges
diffract (varimu.rooms.diffraction); without that an object would block the bass too.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from varimu.rooms.materials import TREATMENT_SCATTERING
from varimu.separation.room import BANDS_HZ, SPEED_OF_SOUND_M_S, air_absorption_db_per_m

SCATTERING_SOURCE = (
    "provisional: model knowledge (random-incidence scattering coefficients: flat hard "
    "surfaces ~0.05-0.1, furnished walls ~0.3, porous / treated ~0.2-0.5; ISO 17497-1 values "
    "as tabulated in Vorlander, Auralization, 2008)"
)
SCATTERING = {
    "furnished_wall": 0.3,
    "gypsum_on_studs": 0.1,
    "plaster": 0.05,
    "wood_floor": 0.1,
    "carpet_on_pad": 0.2,
    "heavy_drapes": 0.4,
    "acoustic_tile": 0.3,
    "anechoic": 0.0,
    "rigid": 0.0,
    **TREATMENT_SCATTERING,
}
CEILINGS = ("flat", "shed", "gable", "vault")
OBJECT_MAX_ORDER = 2  # reflections off objects: paths with an object face up to this order
THIN_M = 0.12  # an object this thin (its least size) is a panel: its edges diffract as a plate
RECEIVER_RADIUS_M = 0.35  # rays counted at a mic within this sphere (the late part's envelope)
RECEIVER_RAYS = 50_000


@dataclass
class Face:
    """A planar face: unit normal pointing into the room, offset (n . x = d on the plane),
    its kind (floor / wall / ceiling / object) and index (a wall's edge, a ceiling's facet,
    an object's 6 i + k). An object's face is a rectangle: its centre, two in-plane unit axes
    and their half extents (`rect`)."""

    normal: np.ndarray
    d: float
    kind: str
    index: int
    rect: tuple | None = None


@dataclass
class Box:
    """An object: a box of `size_m` (width, depth, height) about `center_m`, its axes the
    columns of `axes` (width, depth, height after yaw and tilt), its material."""

    center_m: np.ndarray
    size_m: np.ndarray
    axes: np.ndarray
    material: str
    name: str = ""

    @property
    def thin(self) -> bool:
        return float(self.size_m.min()) <= THIN_M

    def contains(self, p: np.ndarray, grow_m: float = 0.0) -> np.ndarray:
        q = (np.asarray(p, float) - self.center_m) @ self.axes  # local coordinates
        return np.all(np.abs(q) < 0.5 * self.size_m + grow_m, axis=-1)


def box_from_spec(o: dict) -> Box:
    """An object from the scene's `{center_m, size_m, yaw_deg?, tilt_deg?, material, name?}`."""
    from varimu.rooms.shoebox import ROOM_MATERIALS

    yaw, tilt = np.radians(float(o.get("yaw_deg", 0.0))), np.radians(float(o.get("tilt_deg", 0.0)))
    rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(tilt), -np.sin(tilt)], [0, np.sin(tilt), np.cos(tilt)]])
    size = np.array(o["size_m"], float)
    if size.shape != (3,) or np.any(size <= 0):
        raise ValueError(f"object {o.get('name', '')}: size_m is 3 positive lengths")
    mat = o.get("material", "furnished_wall")
    if mat not in ROOM_MATERIALS:
        raise ValueError(f"object {o.get('name', '')}: unknown material {mat!r}")
    return Box(np.array(o["center_m"], float), size, rz @ rx, mat, str(o.get("name", "")))


@dataclass
class PolyRoom:
    floor: np.ndarray  # (n, 2), counterclockwise
    ceiling: str = "flat"
    height_m: float = 3.0
    peak_m: float | None = None
    axis_deg: float = 0.0
    facets: int = 8
    walls: str = "furnished_wall"
    floor_material: str = "wood_floor"
    ceiling_material: str = "gypsum_on_studs"
    temp_c: float = 20.0
    rh_percent: float = 50.0
    face_materials: dict[str, str] = field(default_factory=dict)
    objects: list[dict] = field(default_factory=list)
    faces: list[Face] = field(init=False)

    def __post_init__(self):
        self.floor = np.asarray(self.floor, float)
        n = len(self.floor)
        self._reversed = _signed_area(self.floor) < 0
        if self._reversed:
            self.floor = self.floor[::-1].copy()
        if self.ceiling not in CEILINGS:
            raise ValueError(f"ceiling {self.ceiling!r}: one of {CEILINGS}")
        if self.peak_m is None or self.ceiling == "flat":
            self.peak_m = self.height_m
        a = np.radians(self.axis_deg)
        self.u_dir = np.array([np.cos(a), np.sin(a)])
        u = self.floor @ self.u_dir
        self.u_lo, self.u_hi = float(u.min()), float(u.max())
        self._knots_u, self._knots_h = self._profile()
        self.boxes = [box_from_spec(o) for o in self.objects]
        self.faces = self._faces()
        self.n_room_faces = len(self.faces)
        for bi, b in enumerate(self.boxes):
            for k in range(6):
                ax, sgn = k // 2, 1 - 2 * (k % 2)
                nrm = sgn * b.axes[:, ax]
                c = b.center_m + 0.5 * b.size_m[ax] * nrm
                o1, o2 = [a for a in range(3) if a != ax]
                rect = (c, b.axes[:, o1], b.axes[:, o2], 0.5 * b.size_m[o1], 0.5 * b.size_m[o2])
                self.faces.append(Face(nrm, float(nrm @ c), "object", 6 * bi + k, rect))
        self._overrides = self._face_overrides(n)

    def _face_overrides(self, n: int) -> dict[tuple[str, int], str]:
        """`face_materials` by (kind, index) of our faces: a wall's number is its edge in
        the plan as given (reversed into counterclockwise order: edge i -> n - 2 - i)."""
        from varimu.rooms.shoebox import ROOM_MATERIALS

        out = {}
        n_facets = len(self._knots_u) - 1
        for key, mat in self.face_materials.items():
            if mat not in ROOM_MATERIALS:
                raise ValueError(f"face {key!r}: unknown material {mat!r}")
            parts = str(key).split()
            if parts == ["floor"]:
                out[("floor", 0)] = mat
                continue
            if len(parts) != 2 or parts[0] not in ("wall", "ceiling") or not parts[1].isdigit():
                raise ValueError(f"face {key!r}: 'floor', 'wall N' or 'ceiling N'")
            i = int(parts[1])
            if parts[0] == "wall":
                if i >= n:
                    raise ValueError(f"face {key!r}: the plan has {n} walls")
                out[("wall", (n - 2 - i) % n if self._reversed else i)] = mat
            else:
                if i >= n_facets:
                    raise ValueError(f"face {key!r}: the ceiling has {n_facets} facets")
                out[("ceiling", i)] = mat
        return out

    # --- the ceiling -------------------------------------------------------------------

    def _profile(self) -> tuple[np.ndarray, np.ndarray]:
        """The ceiling's height along u as a piecewise-linear profile (knots)."""
        lo, hi, h, p = self.u_lo, self.u_hi, self.height_m, self.peak_m
        if self.ceiling == "flat":
            return np.array([lo, hi]), np.array([h, h])
        if self.ceiling == "shed":
            return np.array([lo, hi]), np.array([h, p])
        if self.ceiling == "gable":
            return np.array([lo, 0.5 * (lo + hi), hi]), np.array([h, p, h])
        n = max(2, int(self.facets))
        t = np.linspace(-1.0, 1.0, n + 1)
        return lo + 0.5 * (t + 1) * (hi - lo), h + (p - h) * np.sqrt(np.clip(1 - t**2, 0, 1))

    def height_at(self, xy: np.ndarray) -> np.ndarray:
        """The ceiling's height over floor points (..., 2)."""
        return np.interp(np.asarray(xy) @ self.u_dir, self._knots_u, self._knots_h)

    def volume_m3(self) -> float:
        """The floor's area times the mean ceiling height over it (sampled)."""
        xs = np.linspace(*self._bbox()[0], 200)
        ys = np.linspace(*self._bbox()[1], 200)
        g = np.stack(np.meshgrid(xs, ys), -1).reshape(-1, 2)
        inside = self.inside_floor(g)
        v = float(_signed_area(self.floor) * self.height_at(g[inside]).mean())
        return v - sum(float(np.prod(b.size_m)) for b in self.boxes)

    def _bbox(self):
        return (self.floor[:, 0].min(), self.floor[:, 0].max()), (
            self.floor[:, 1].min(),
            self.floor[:, 1].max(),
        )

    # --- faces -------------------------------------------------------------------------

    def _faces(self) -> list[Face]:
        faces = [Face(np.array([0.0, 0.0, 1.0]), 0.0, "floor", 0)]
        n = len(self.floor)
        for i in range(n):
            p0, p1 = self.floor[i], self.floor[(i + 1) % n]
            t = (p1 - p0) / np.linalg.norm(p1 - p0)
            nrm = np.array([-t[1], t[0], 0.0])  # left of a counterclockwise edge: inside
            faces.append(Face(nrm, float(nrm[:2] @ p0), "wall", i))
        ku, kh = self._knots_u, self._knots_h
        for k in range(len(ku) - 1):
            slope = (kh[k + 1] - kh[k]) / (ku[k + 1] - ku[k])
            # z = kh[k] + slope (u - ku[k]); inward normal points down
            nrm = np.array([slope * self.u_dir[0], slope * self.u_dir[1], -1.0])
            d = slope * ku[k] - kh[k]
            s = np.linalg.norm(nrm)
            faces.append(Face(nrm / s, float(d / s), "ceiling", k))
        return faces

    def inside_floor(self, xy: np.ndarray) -> np.ndarray:
        return _in_polygon(self.floor, np.asarray(xy))

    def inside(self, p: np.ndarray, tol: float = 1e-9) -> np.ndarray:
        """Points (..., 3) inside the room."""
        p = np.asarray(p, float)
        xy = p[..., :2]
        ok = self.inside_floor(xy) & (p[..., 2] > tol) & (p[..., 2] < self.height_at(xy) - tol)
        for b in self.boxes:
            ok &= ~b.contains(p)
        return ok

    def on_face(self, f: Face, p: np.ndarray, tol: float = 1e-7) -> np.ndarray:
        """Whether points p (m, 3) on f's plane lie within the face."""
        if f.kind == "object":
            c, u, v, hu, hv = f.rect
            q = np.nan_to_num(p - c, nan=np.inf)
            with np.errstate(invalid="ignore"):
                return (np.abs(q @ u) <= hu + tol) & (np.abs(q @ v) <= hv + tol)
        xy = p[:, :2]
        if f.kind == "floor":
            return self.inside_floor(xy)
        if f.kind == "ceiling":
            u = xy @ self.u_dir
            k = f.index
            lo, hi = self._knots_u[k] - tol, self._knots_u[k + 1] + tol
            return self.inside_floor(xy) & (u >= lo) & (u <= hi)
        n = len(self.floor)
        p0, p1 = self.floor[f.index], self.floor[(f.index + 1) % n]
        e = p1 - p0
        t = ((xy - p0) @ e) / (e @ e)
        z = p[:, 2]
        return (t >= -tol) & (t <= 1 + tol) & (z >= -tol) & (z <= self.height_at(xy) + tol)

    def material(self, f: Face) -> str:
        if f.kind == "object":
            return self.boxes[f.index // 6].material
        own = self._overrides.get((f.kind, f.index))
        if own is not None:
            return own
        return {"floor": self.floor_material, "wall": self.walls, "ceiling": self.ceiling_material}[
            f.kind
        ]

    def materials(self) -> list[str]:
        return [self.material(f) for f in self.faces]

    def rt60_eyring_s(self) -> np.ndarray:
        """Eyring's reverberation time per band from the faces' area-weighted absorption,
        air included (a check on the ray tracing; the renders don't use it)."""
        from varimu.rooms.shoebox import ROOM_MATERIALS

        s = np.array(self.areas_m2())
        alphas = np.stack([np.array(ROOM_MATERIALS[m]) for m in self.materials()])
        a_mean = (s[:, None] * alphas).sum(0) / s.sum()
        m = air_absorption_db_per_m(BANDS_HZ, self.temp_c, self.rh_percent) / (10 * np.log10(np.e))
        v = self.volume_m3()
        with np.errstate(divide="ignore"):
            loss = -s.sum() * np.log(np.maximum(1 - a_mean, 0.0)) + 4 * m * v
        return 24 * np.log(10) * v / (SPEED_OF_SOUND_M_S * loss)

    def areas_m2(self) -> list[float]:
        """Each face's area (sampled for the walls under a sloped ceiling)."""
        out = []
        n = len(self.floor)
        for f in self.faces:
            if f.kind == "object":
                out.append(4.0 * f.rect[3] * f.rect[4])
            elif f.kind == "floor":
                out.append(_signed_area(self.floor))
            elif f.kind == "wall":
                p0, p1 = self.floor[f.index], self.floor[(f.index + 1) % n]
                s = np.linspace(0, 1, 64)
                h = self.height_at(p0[None, :] + s[:, None] * (p1 - p0)[None, :])
                out.append(float(np.linalg.norm(p1 - p0) * h.mean()))
            else:
                k = f.index
                xs = np.linspace(*self._bbox()[0], 200)
                ys = np.linspace(*self._bbox()[1], 200)
                g = np.stack(np.meshgrid(xs, ys), -1).reshape(-1, 2)
                u = g @ self.u_dir
                sel = self.inside_floor(g) & (u >= self._knots_u[k]) & (u < self._knots_u[k + 1])
                cell = (xs[1] - xs[0]) * (ys[1] - ys[0])
                cos = abs(f.normal[2])
                out.append(float(sel.sum() * cell / cos))
        return out

    # --- triangles (the GPU's ray tracer, varimu.rooms.gpu) ------------------------------

    def triangles(self) -> tuple[np.ndarray, np.ndarray]:
        """Every face as triangles: vertices (T, 3, 3) and each one's face index (T,). The
        floor by ear clipping; each wall as trapezoids between the ceiling's knots along it;
        each ceiling facet as the floor's triangles clipped to its strip of u, lifted."""
        tris, owner = [], []
        floor_tris = _ear_clip(self.floor)
        for fi, f in enumerate(self.faces):
            if f.kind == "object":
                c, u, v, hu, hv = f.rect
                q = [c + a * hu * u + b * hv * v for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                tris += [np.array([q[0], q[1], q[2]]), np.array([q[0], q[2], q[3]])]
                owner += [fi, fi]
            elif f.kind == "floor":
                for t in floor_tris:
                    tris.append(np.c_[t, np.zeros(3)])
                    owner.append(fi)
            elif f.kind == "wall":
                n = len(self.floor)
                p0, p1 = self.floor[f.index], self.floor[(f.index + 1) % n]
                u0, u1 = p0 @ self.u_dir, p1 @ self.u_dir
                ss = [0.0, 1.0]
                if abs(u1 - u0) > 1e-12:
                    for ku in self._knots_u[1:-1]:
                        t = (ku - u0) / (u1 - u0)
                        if 1e-9 < t < 1 - 1e-9:
                            ss.append(float(t))
                ss = sorted(ss)
                for a, b in zip(ss[:-1], ss[1:], strict=True):
                    pa, pb = p0 + a * (p1 - p0), p0 + b * (p1 - p0)
                    ha, hb = float(self.height_at(pa)), float(self.height_at(pb))
                    qa0, qb0 = np.r_[pa, 0.0], np.r_[pb, 0.0]
                    qb1, qa1 = np.r_[pb, hb], np.r_[pa, ha]
                    tris += [np.array([qa0, qb0, qb1]), np.array([qa0, qb1, qa1])]
                    owner += [fi, fi]
            else:
                k = f.index
                lo, hi = self._knots_u[k], self._knots_u[k + 1]
                for t in floor_tris:
                    poly = _clip_halfplane(t, self.u_dir, lo, +1)
                    poly = _clip_halfplane(poly, self.u_dir, hi, -1)
                    if len(poly) < 3:
                        continue
                    z = self.height_at(poly)
                    pts = np.c_[poly, z]
                    for j in range(1, len(pts) - 1):
                        tri = np.array([pts[0], pts[j], pts[j + 1]])
                        if np.linalg.norm(np.cross(tri[1] - tri[0], tri[2] - tri[0])) > 1e-12:
                            tris.append(tri)
                            owner.append(fi)
        return np.array(tris, float), np.array(owner, np.int64)

    # --- paths -------------------------------------------------------------------------

    def segment_clear(self, a: np.ndarray, b: np.ndarray, skip=()) -> np.ndarray:
        """Whether segments a -> b (m, 3) stay inside the room: they cross no face (except
        at the faces in `skip`, a set of indices per segment given as an (m, 2) array of
        face indices or -1)."""
        m = len(a)
        ok = np.ones(m, bool)
        d = b - a
        for fi, f in enumerate(self.faces):
            nd = d @ f.normal
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (f.d - a @ f.normal) / nd
            hit = (np.abs(nd) > 1e-12) & (t > 1e-6) & (t < 1 - 1e-6)
            if len(skip):
                hit &= ~np.any(np.asarray(skip) == fi, axis=1)
            if not np.any(hit):
                continue
            idx = np.nonzero(hit)[0]
            p = a[idx] + t[idx, None] * d[idx]
            ok[idx[self.on_face(f, p)]] = False
        return ok


def _signed_area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _in_polygon(poly: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Even-odd ray casting; points on the boundary count as inside within ~1e-9."""
    x, y = pts[..., 0], pts[..., 1]
    inside = np.zeros(np.shape(x), bool)
    on_edge = np.zeros(np.shape(x), bool)
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cross = (y0 > y) != (y1 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= cross & (x < xc)
        ex, ey = x1 - x0, y1 - y0
        ll = ex * ex + ey * ey
        t = np.clip(((x - x0) * ex + (y - y0) * ey) / ll, 0, 1)
        on_edge |= np.hypot(x - (x0 + t * ex), y - (y0 + t * ey)) < 1e-9
    return inside | on_edge


def _ear_clip(poly: np.ndarray) -> list[np.ndarray]:
    """A simple counterclockwise polygon as triangles (ear clipping)."""
    idx = list(range(len(poly)))
    out = []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    guard = 0
    while len(idx) > 3 and guard < 10_000:
        guard += 1
        m = len(idx)
        for j in range(m):
            i0, i1, i2 = idx[(j - 1) % m], idx[j], idx[(j + 1) % m]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if cross(a, b, c) <= 1e-12:
                continue  # reflex or degenerate
            inside = False
            for q in idx:
                if q in (i0, i1, i2):
                    continue
                p = poly[q]
                if (
                    cross(a, b, p) >= -1e-12
                    and cross(b, c, p) >= -1e-12
                    and (cross(c, a, p) >= -1e-12)
                ):
                    inside = True
                    break
            if inside:
                continue
            out.append(np.array([a, b, c]))
            del idx[j]
            break
        else:
            raise ValueError("the floor polygon can't be triangulated (is it simple?)")
    out.append(poly[idx])
    return out


def _clip_halfplane(poly: np.ndarray, u: np.ndarray, c: float, sign: int) -> np.ndarray:
    """A convex polygon (k, 2) clipped to sign (x . u - c) >= 0 (Sutherland-Hodgman)."""
    if len(poly) == 0:
        return poly
    out = []
    v = sign * (poly @ u - c)
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        va, vb = v[i], v[(i + 1) % n]
        if va >= 0:
            out.append(a)
        if (va >= 0) != (vb >= 0):
            t = va / (va - vb)
            out.append(a + t * (b - a))
    return np.array(out).reshape(-1, 2)


def _mirror(p: np.ndarray, f: Face) -> np.ndarray:
    return p - 2 * ((p @ f.normal) - f.d)[..., None] * f.normal


def image_sources(room: PolyRoom, source: np.ndarray, max_order: int):
    """Candidate images: positions (k, 3) and their face sequences (k, max_order; -1 pad),
    the source mirrored only in faces it lies in front of (Borish's validity)."""
    pos = [np.asarray(source, float)[None, :]]
    seq = [np.full((1, max_order), -1)]
    cur_p, cur_s = pos[0], seq[0]
    n_room = getattr(room, "n_room_faces", len(room.faces))
    for order in range(1, max_order + 1):
        nps, nss = [], []
        has_obj = np.any(cur_s >= n_room, axis=1)
        for fi, f in enumerate(room.faces):
            last = cur_s[:, order - 2] if order > 1 else np.full(len(cur_s), -1)
            front = (cur_p @ f.normal - f.d) > 1e-9  # the parent is on the room side
            keep = front & (last != fi)
            if order > OBJECT_MAX_ORDER:  # paths touching an object stop at its order
                keep &= ~has_obj
                if fi >= n_room:
                    continue
            if not np.any(keep):
                continue
            nps.append(_mirror(cur_p[keep], f))
            s = cur_s[keep].copy()
            s[:, order - 1] = fi
            nss.append(s)
        if not nps:
            break
        cur_p, cur_s = np.vstack(nps), np.vstack(nss)
        pos.append(cur_p)
        seq.append(cur_s)
    return np.vstack(pos), np.vstack(seq)


def valid_paths(room: PolyRoom, images: np.ndarray, seqs: np.ndarray, mic: np.ndarray):
    """Which images reach the mic by a valid path (traced back from the mic)."""
    k = len(images)
    ok = np.ones(k, bool)
    order = (seqs >= 0).sum(1)
    rx = np.repeat(np.asarray(mic, float)[None, :], k, axis=0)  # the current point
    target = images.copy()
    prev_face = np.full(k, -1)
    for step in range(seqs.shape[1]):
        j = order - 1 - step  # the reflection traced back now (last first)
        act = ok & (j >= 0)
        if not np.any(act):
            break
        idx = np.nonzero(act)[0]
        fis = seqs[idx, j[idx]]
        hit_pts = np.zeros((len(idx), 3))
        good = np.zeros(len(idx), bool)
        for fi in np.unique(fis):
            f = room.faces[fi]
            sel = fis == fi
            a, b = rx[idx[sel]], target[idx[sel]]
            dvec = b - a
            nd = dvec @ f.normal
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (f.d - a @ f.normal) / nd
                p = a + t[:, None] * dvec
            g = (np.abs(nd) > 1e-12) & (t > 1e-9) & (t < 1 - 1e-9)
            g &= room.on_face(f, p)
            hit_pts[sel] = p
            good[sel] = g
        # the segment from the current point to the reflection point stays in the room
        skip = np.stack([prev_face[idx], fis], axis=1)
        clear = room.segment_clear(rx[idx], hit_pts, skip)
        good &= clear
        ok[idx[~good]] = False
        # next: from the reflection point toward the parent image
        kk = idx[good]
        rx[kk] = hit_pts[good]
        prev_face[kk] = fis[good]
        # the parent image: un-mirror the last face from the target
        for fi in np.unique(fis[good]):
            sel = kk[fis[good] == fi]
            target[sel] = _mirror(target[sel], room.faces[fi])
    # the final segment to the source itself
    last = np.nonzero(ok)[0]
    if len(last):
        skip = np.stack([prev_face[last], np.full(len(last), -1)], axis=1)
        ok[last[~room.segment_clear(rx[last], target[last], skip)]] = False
    return ok


def ray_decay(
    room: PolyRoom,
    source: np.ndarray,
    t_max_s: float,
    fs_env: float = 1000.0,
    n_rays: int = 20000,
    seed: int = 0,
    receivers: list[np.ndarray] | None = None,
    radius_m: float = RECEIVER_RADIUS_M,
    backend: str | None = None,
    weights: np.ndarray | None = None,
):
    """The fraction of emitted energy still travelling, per band, on a grid of 1 / fs_env:
    (t (T,), e (bands, T)), from ray tracing (the module docstring). With `receivers`, also
    the energy density at each (a sphere of `radius_m`: every ray segment crossing it adds
    its energy times the time it spends inside), as a fraction of the emitted energy per m^3
    averaged over each bin, (receivers, bands, T): the room's sound at that point, flutter
    and a hidden corner's shadow included (returned third).

    `backend` (varimu.rooms.gpu; default its `backend()`): "numpy" is this function's own
    loop below, "gpu" / "cpu" crates/roomsim's port (the same physics, its own random
    numbers: the results agree in their statistics, ROOM_LOOP_PLAN.md R9). `weights` (rays,
    bands): each ray's starting energy (a directional source; default 1)."""
    from varimu.rooms import gpu
    from varimu.rooms.shoebox import ROOM_MATERIALS, fibonacci_sphere

    c = SPEED_OF_SOUND_M_S
    dirs = fibonacci_sphere(n_rays)
    b = gpu.resolve(backend)
    if b != "numpy":
        rx = np.zeros((0, 3)) if receivers is None else receivers
        trav, dens = gpu.ray_trace(
            room, source, dirs, rx, t_max_s, fs_env, radius_m, c, seed, b, weights
        )
        nt = trav.shape[1]
        t = np.arange(nt) / fs_env
        air = air_absorption_db_per_m(BANDS_HZ, room.temp_c, room.rh_percent)
        air_t = 10 ** (-air[:, None] * c * t[None, :] / 10)
        remaining = trav / n_rays * air_t
        if receivers is None:
            return t, np.clip(remaining, 0, 1)
        v_rec = 4.0 / 3.0 * np.pi * radius_m**3
        return t, np.clip(remaining, 0, 1), dens * fs_env / (v_rec * n_rays) * air_t[None]
    rng = np.random.default_rng([seed, 17])
    p = np.repeat(np.asarray(source, float)[None, :], n_rays, axis=0)
    alpha = np.array([ROOM_MATERIALS[room.material(f)] for f in room.faces])  # (F, B)
    scat = np.array([SCATTERING.get(room.material(f), 0.1) for f in room.faces])
    nb = len(BANDS_HZ)
    energy = np.ones((n_rays, nb)) if weights is None else np.array(weights, float)
    t_now = np.zeros(n_rays)
    nt = int(t_max_s * fs_env) + 1
    acc = np.zeros((nb, nt + 1))  # energy leaving at each time (a step down)
    alive = np.ones(n_rays, bool)
    normals = np.array([f.normal for f in room.faces])
    ds = np.array([f.d for f in room.faces])
    rx = np.array(receivers, float).reshape(-1, 3) if receivers is not None else np.zeros((0, 3))
    dens = np.zeros((len(rx), nb, nt + 1))
    for _ in range(10_000):
        idx = np.nonzero(alive)[0]
        if len(idx) == 0:
            break
        pp, dd = p[idx], dirs[idx]
        nd = dd @ normals.T  # (m, F)
        with np.errstate(divide="ignore", invalid="ignore"):
            tt = (ds[None, :] - pp @ normals.T) / nd
        tt[~((nd < -1e-12) & (tt > 1e-9))] = np.inf  # only faces ahead, approached from inside
        # nearest face whose hit point lies on it
        best = np.full(len(idx), np.inf)
        bf = np.full(len(idx), -1)
        for fi, f in enumerate(room.faces):
            cand = np.isfinite(tt[:, fi]) & (tt[:, fi] < best)
            if not np.any(cand):
                continue
            ci = np.nonzero(cand)[0]
            hp = pp[ci] + tt[ci, fi, None] * dd[ci]
            on = room.on_face(f, hp, tol=1e-6)
            best[ci[on]] = tt[ci[on], fi]
            bf[ci[on]] = fi
        lost = bf < 0
        if np.any(lost):  # numerical escape: drop the ray's energy now
            li = idx[lost]
            k = np.minimum((t_now[li] * fs_env).astype(int), nt)
            np.add.at(acc, (slice(None), k), energy[li].T)
            alive[li] = False
            energy[li] = 0
        g = ~lost
        idx, best, bf = idx[g], best[g], bf[g]
        t_new = t_now[idx] + best / c
        for ri, rc in enumerate(rx):  # the segment's time inside each receiver's sphere
            v = rc[None, :] - p[idx]
            proj = (v * dirs[idx]).sum(1)
            d2 = (v * v).sum(1) - proj**2
            inside = d2 < radius_m**2
            if not np.any(inside):
                continue
            half = np.sqrt(np.maximum(radius_m**2 - d2[inside], 0.0))
            s0 = np.clip(proj[inside] - half, 0.0, best[inside])
            s1 = np.clip(proj[inside] + half, 0.0, best[inside])
            ln = s1 - s0
            ii = idx[inside]
            k = np.minimum((t_now[ii] + 0.5 * (s0 + s1) / c) * fs_env, nt).astype(int)
            np.add.at(dens[ri], (slice(None), k), (energy[ii] * (ln / c)[:, None]).T)
        p[idx] = p[idx] + best[:, None] * dirs[idx]
        # energy lost at the wall: alpha of what arrives (air applies analytically below)
        loss = energy[idx] * alpha[bf]
        k = np.minimum((t_new * fs_env).astype(int), nt)
        np.add.at(acc, (slice(None), k), loss.T)
        energy[idx] -= loss
        # reflect: specular, or Lambert with the face's scattering coefficient
        n_in = normals[bf]
        d_old = dirs[idx]
        spec = d_old - 2 * (d_old * n_in).sum(1)[:, None] * n_in
        diffuse = rng.random(len(idx)) < scat[bf]
        if np.any(diffuse):
            m = int(diffuse.sum())
            v = rng.standard_normal((m, 3))
            v /= np.linalg.norm(v, axis=1)[:, None]
            nn = n_in[diffuse]
            v = np.where(((v * nn).sum(1) < 0)[:, None], -v, v)
            # Lambert: cosine-weighted, by the normal plus a unit vector
            v = nn + v
            v /= np.linalg.norm(v, axis=1)[:, None]
            spec[diffuse] = v
        dirs[idx] = spec
        p[idx] += 1e-7 * n_in  # off the face
        t_now[idx] = t_new
        done = (t_new >= t_max_s) | (energy[idx].max(1) < 1e-7)
        if np.any(done):
            di = idx[done]
            k = np.minimum((t_now[di] * fs_env).astype(int), nt)
            np.add.at(acc, (slice(None), k), energy[di].T)
            alive[di] = False
    t = np.arange(nt) / fs_env
    remaining = 1.0 - np.cumsum(acc[:, :nt], axis=1) / n_rays
    air = air_absorption_db_per_m(BANDS_HZ, room.temp_c, room.rh_percent)  # dB/m
    air_t = 10 ** (-air[:, None] * c * t[None, :] / 10)
    remaining *= air_t
    if receivers is None:
        return t, np.clip(remaining, 0, 1)
    v_rec = 4.0 / 3.0 * np.pi * radius_m**3
    w = dens[:, :, :nt] * fs_env / (v_rec * n_rays) * air_t[None]
    return t, np.clip(remaining, 0, 1), w


def rt60_from_decay(t: np.ndarray, e: np.ndarray) -> np.ndarray:
    """T30-style reverberation time per band from an energy decay: the slope between -5
    and -35 dB, extrapolated to 60 dB."""
    out = []
    for eb in e:
        db = 10 * np.log10(np.maximum(eb, 1e-30))
        sel = (db <= -5) & (db >= -35)
        if sel.sum() < 3:
            out.append(float("nan"))
            continue
        slope = np.polyfit(t[sel], db[sel], 1)[0]
        out.append(float(-60 / slope))
    return np.array(out)

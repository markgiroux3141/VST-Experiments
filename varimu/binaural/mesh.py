"""Head meshes (docs/BINAURAL_PLAN.md): reading, checking and voxelizing a closed triangle
mesh for the body-in-free-field solver (crates/roomsim `fdtd::head`).

Meshes are in metres, x forward, y left, z up, the origin at the interaural centre (the
HUTUBS convention, which Mesh2HRTF shares). `Mesh` holds float64 vertices (V x 3) and
int32 triangles (T x 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Mesh:
    vertices: np.ndarray
    faces: np.ndarray

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def open_edges(self) -> int:
        """Edges not shared by exactly two triangles (0 for a closed, manifold mesh)."""
        e = np.concatenate([self.faces[:, [0, 1]], self.faces[:, [1, 2]], self.faces[:, [2, 0]]])
        e.sort(axis=1)
        _, counts = np.unique(e, axis=0, return_counts=True)
        return int(np.count_nonzero(counts != 2))

    def volume_m3(self) -> float:
        v = self.vertices[self.faces]
        return float(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6.0)

    def area_m2(self) -> float:
        v = self.vertices[self.faces]
        return float(
            0.5 * np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1).sum()
        )


_PLY_TYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}


def read_ply(path: Path) -> Mesh:
    """A binary little-endian PLY of vertices (x, y, z, maybe more) and triangles."""
    data = Path(path).read_bytes()
    end = data.index(b"end_header") + len(b"end_header")
    end = data.index(b"\n", end) + 1
    header = data[:end].decode("ascii").splitlines()
    ascii_ply = "format ascii 1.0" in header
    if not ascii_ply and "format binary_little_endian 1.0" not in header:
        raise ValueError(f"{path}: only binary little-endian or ASCII PLY is read")
    elements: list[tuple[str, int, list]] = []
    for line in header:
        w = line.split()
        if not w:
            continue
        if w[0] == "element":
            elements.append((w[1], int(w[2]), []))
        elif w[0] == "property":
            elements[-1][2].append(w[1:])
    if ascii_ply:
        return _ascii_body(path, data[end:], elements)
    pos = end
    verts = faces = None
    for name, count, props in elements:
        if all(p[0] != "list" for p in props):
            dt = np.dtype([(p[1], "<" + _PLY_TYPES[p[0]]) for p in props])
            arr = np.frombuffer(data, dt, count, pos)
            pos += count * dt.itemsize
            if name == "vertex":
                verts = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(float)
        else:
            if len(props) != 1 or name != "face":
                raise ValueError(f"{path}: element {name!r} not understood")
            _, ct, it, _ = props[0]
            ct, it = np.dtype("<" + _PLY_TYPES[ct]), np.dtype("<" + _PLY_TYPES[it])
            # triangles: fixed-size records, checked
            dt = np.dtype([("n", ct), ("v", it, (3,))])
            arr = np.frombuffer(data, dt, count, pos)
            if np.any(arr["n"] != 3):
                raise ValueError(f"{path}: faces that aren't triangles")
            faces = arr["v"].astype(np.int32)
            pos += count * dt.itemsize
    if verts is None or faces is None:
        raise ValueError(f"{path}: no vertices or faces")
    return Mesh(verts, faces)


def _ascii_body(path, body: bytes, elements) -> Mesh:
    """An ASCII PLY's vertices then triangles (the element order checked)."""
    names = [e[0] for e in elements]
    if names != ["vertex", "face"]:
        raise ValueError(f"{path}: elements {names}, expected vertex then face")
    (_, nv, vprops), (_, nf, _) = elements
    tok = np.array(body.split(), dtype=float)
    k = len(vprops)
    v = tok[: nv * k].reshape(nv, k)
    cols = [i for i, p in enumerate(vprops) if p[1] in ("x", "y", "z")]
    f = tok[nv * k : nv * k + nf * 4].reshape(nf, 4)
    if np.any(f[:, 0] != 3):
        raise ValueError(f"{path}: faces that aren't triangles")
    return Mesh(v[:, cols].astype(float), f[:, 1:].astype(np.int32))


def sphere_mesh(radius_m: float, subdivisions: int = 5, centre=(0.0, 0.0, 0.0)) -> Mesh:
    """An icosphere (closed), for the solver's analytic check."""
    t = (1 + 5**0.5) / 2
    v = [
        (-1, t, 0),
        (1, t, 0),
        (-1, -t, 0),
        (1, -t, 0),
        (0, -1, t),
        (0, 1, t),
        (0, -1, -t),
        (0, 1, -t),
        (t, 0, -1),
        (t, 0, 1),
        (-t, 0, -1),
        (-t, 0, 1),
    ]
    f = [
        (0, 11, 5),
        (0, 5, 1),
        (0, 1, 7),
        (0, 7, 10),
        (0, 10, 11),
        (1, 5, 9),
        (5, 11, 4),
        (11, 10, 2),
        (10, 7, 6),
        (7, 1, 8),
        (3, 9, 4),
        (3, 4, 2),
        (3, 2, 6),
        (3, 6, 8),
        (3, 8, 9),
        (4, 9, 5),
        (2, 4, 11),
        (6, 2, 10),
        (8, 6, 7),
        (9, 8, 1),
    ]
    verts = [np.array(p, float) / np.linalg.norm(p) for p in v]
    faces = f
    for _ in range(subdivisions):
        cache: dict = {}

        def mid(a, b, cache=cache):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = verts[a] + verts[b]
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]

        nf = []
        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = nf
    return Mesh(np.array(verts) * radius_m + np.asarray(centre, float), np.array(faces, np.int32))


def ray_hit(mesh: Mesh, origin, direction) -> tuple[float, np.ndarray]:
    """The nearest intersection t > 0 of origin + t direction with the mesh (Moller-Trumbore
    over every triangle) and that triangle's unit normal (as wound)."""
    o = np.asarray(origin, float)
    d = np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    v = mesh.vertices[mesh.faces]
    e1 = v[:, 1] - v[:, 0]
    e2 = v[:, 2] - v[:, 0]
    p = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-18
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = o - v[:, 0]
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, e1)
    w = (q @ d) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = ok & (u >= 0) & (w >= 0) & (u + w <= 1) & (t > 1e-9)
    if not hit.any():
        raise ValueError("the ray misses the mesh")
    i = int(np.flatnonzero(hit)[np.argmin(t[hit])])
    n = np.cross(e1[i], e2[i])
    return float(t[i]), n / np.linalg.norm(n)


def voxelize(mesh: Mesh, x0, dx: float, shape: tuple[int, int, int]) -> np.ndarray:
    """Solid cells: a boolean array of `shape` (nz, ny, nx) whose cell (k, j, i) has its
    centre at x0 + (i, j, k) dx; a cell is solid when its centre is inside the closed mesh
    (crossings of a ray along +x counted per (j, k) column: odd = inside). The columns are
    nudged by a fraction of a cell no grid shares, so no ray passes through an edge or
    vertex exactly."""
    nz, ny, nx = shape
    x0 = np.asarray(x0, float)
    jit = np.array([0.0, 1.2345e-4, 2.7183e-4]) * dx
    v = (mesh.vertices - x0 - jit) / dx  # grid units, columns at integer (j, k)
    tri = v[mesh.faces]  # T x 3 x 3
    y, z = tri[:, :, 1], tri[:, :, 2]
    jlo = np.ceil(y.min(axis=1)).astype(int)
    jhi = np.floor(y.max(axis=1)).astype(int)
    klo = np.ceil(z.min(axis=1)).astype(int)
    khi = np.floor(z.max(axis=1)).astype(int)
    span_j = int(max(0, (jhi - jlo).max())) + 1
    span_k = int(max(0, (khi - klo).max())) + 1
    hits_j, hits_k, hits_x = [], [], []
    for dj in range(span_j):
        for dk in range(span_k):
            j = jlo + dj
            k = klo + dk
            m = (j <= jhi) & (k <= khi)
            if not m.any():
                continue
            t = tri[m]
            jj, kk = j[m].astype(float), k[m].astype(float)
            # barycentric in the yz plane
            ay, az = t[:, 0, 1], t[:, 0, 2]
            by, bz = t[:, 1, 1], t[:, 1, 2]
            cy, cz = t[:, 2, 1], t[:, 2, 2]
            den = (by - ay) * (cz - az) - (cy - ay) * (bz - az)
            good = np.abs(den) > 1e-14
            den = np.where(good, den, 1.0)
            l1 = ((jj - ay) * (cz - az) - (cy - ay) * (kk - az)) / den
            l2 = ((by - ay) * (kk - az) - (jj - ay) * (bz - az)) / den
            l0 = 1.0 - l1 - l2
            inside = good & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
            if not inside.any():
                continue
            xs = l0 * t[:, 0, 0] + l1 * t[:, 1, 0] + l2 * t[:, 2, 0]
            hits_j.append(jj[inside].astype(int))
            hits_k.append(kk[inside].astype(int))
            hits_x.append(xs[inside])
    solid = np.zeros(shape, bool)
    if not hits_j:
        return solid
    hj = np.concatenate(hits_j)
    hk = np.concatenate(hits_k)
    hx = np.concatenate(hits_x)
    keep = (hj >= 0) & (hj < ny) & (hk >= 0) & (hk < nz)
    hj, hk, hx = hj[keep], hk[keep], hx[keep]
    i0 = np.clip(np.ceil(hx).astype(int), 0, nx)  # the first cell centre past the crossing
    tog = np.zeros((nz, ny, nx + 1), np.uint8)
    np.add.at(tog, (hk, hj, i0), 1)
    tog &= 1
    np.bitwise_xor.accumulate(tog, axis=2, out=tog)
    solid[:] = tog[:, :, :nx].astype(bool)
    return solid

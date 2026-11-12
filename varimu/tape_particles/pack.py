"""Non-overlapping needles at the coating's packing: random centres and axes, then the
overlaps relaxed away. Needles are spherocylinders of their width; each overlapping pair is
pushed apart at its closest points (a translation of both centres and a rotation of both
axes about their centres, the axes renormalized), until no pair is closer than `contact`
times the mean of their widths. Random placement at 35% packing overlaps heavily, and
overlapping needles' end charges put fields of ~1000 Oe on each other; random sequential
addition jams well below 35% for 5:1 needles, so the relaxation is what reaches it (random
close packing of 5:1 spherocylinders is ~50%). The rotations leave the axes' distribution
nearly isotropic (`order` measures it).
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def segment_distance(r, d1, d2):
    """Closest points of segments s d1 and r' + t d2 (s, t in [-1/2, 1/2]), vectorized: r is
    centre1 - centre2 (N x 3), d1, d2 the full segment vectors (N x 3). Returns (the vector
    between the closest points, from 2 to 1, its length, s, t)."""
    a = np.einsum("ij,ij->i", d1, d1)
    e = np.einsum("ij,ij->i", d2, d2)
    b = np.einsum("ij,ij->i", d1, d2)
    c = np.einsum("ij,ij->i", r, d1)
    f = np.einsum("ij,ij->i", r, d2)
    den = a * e - b * b
    ok = den > 1e-12 * a * e
    s = np.where(ok, (b * f - c * e) / np.where(ok, den, 1.0), 0.0)
    s = np.clip(s, -0.5, 0.5)
    t = np.clip((b * s + f) / e, -0.5, 0.5)
    s = np.clip((b * t - c) / a, -0.5, 0.5)
    v = r + s[:, None] * d1 - t[:, None] * d2
    return v, np.sqrt(np.einsum("ij,ij->i", v, v)), s, t


def order(n) -> float:
    """The nematic order parameter (largest eigenvalue of <3/2 n n - 1/2>): 0 isotropic."""
    q = 1.5 * np.einsum("ij,ik->jk", n, n) / len(n) - 0.5 * np.eye(3)
    return float(np.linalg.eigvalsh(q).max())


def relax(r, n, l, w, side, contact=0.8, max_iter=6000, rng=None, log=None):  # noqa: E741 (l: the needles' lengths)
    """Move centres r and turn axes n (N x 3, periodic cube `side`) until no two needles
    (lengths l, widths w) are closer than contact x the mean of their widths. Returns (r, n,
    iterations, overlapping pairs left)."""
    g = rng if rng is not None else np.random.default_rng(0)
    r = np.mod(np.array(r, float), side)
    n = np.array(n, float)
    reach = float(l.max() + w.max())
    left = -1
    for it in range(max_iter):
        d = n * l[:, None]
        tree = cKDTree(r, boxsize=side)
        pairs = tree.query_pairs(reach, output_type="ndarray")
        if len(pairs) == 0:
            return r, n, it, 0
        i, j = pairs[:, 0], pairs[:, 1]
        dr = r[i] - r[j]
        dr -= side * np.round(dr / side)
        v, dist, s, t = segment_distance(dr, d[i], d[j])
        need = 0.5 * (w[i] + w[j])
        over = dist < contact * need
        left = int(over.sum())
        if log is not None and it % 100 == 0:
            log(it, left)
        if not over.any():
            return r, n, it, 0
        i, j, v, dist, need, s, t = (x[over] for x in (i, j, v, dist, need, s, t))
        tiny = dist < 1e-9 * need
        if tiny.any():
            v[tiny] = g.standard_normal((int(tiny.sum()), 3))
            dist[tiny] = np.linalg.norm(v[tiny], axis=1)
        push = ((need - dist) * 0.5 * 1.1 / dist)[:, None] * v
        mv = np.zeros_like(r)
        np.add.at(mv, i, push)
        np.add.at(mv, j, -push)
        # Turn each axis so that its closest point moves with the push (s, t: where along).
        dn = np.zeros_like(n)
        for idx, sv, pv in ((i, s, push), (j, t, -push)):
            nn = n[idx]
            perp = pv - np.einsum("ij,ij->i", pv, nn)[:, None] * nn
            np.add.at(dn, idx, (sv / l[idx])[:, None] * perp)
        n = n + dn
        n /= np.linalg.norm(n, axis=1, keepdims=True)
        # A small jiggle against stalls.
        if it % 200 == 199:
            k = np.unique(np.concatenate([i, j]))
            r[k] += 0.05 * w[k, None] * g.standard_normal((len(k), 3))
        r = np.mod(r + mv, side)
    return r, n, max_iter, left

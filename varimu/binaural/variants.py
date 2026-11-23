"""Variations of a head (docs/BINAURAL_PLAN.md B5) and a measure of its front / back cues.

`scale_pinnae`: space scaled about each ear canal point by `scale` within `r_in`, blended
smoothly back to 1 by `r_out` (a radial map d -> d (1 + (s - 1) w(d)) with w a smoothstep):
the pinna, the concha and the skin round them grow or shrink together, the canal point
stays. The map is checked to be monotonic in d, so it is a bijection of space and the mesh
can't come to cross itself.

`front_back_contrast`: how different a head's ears hear a source 30 deg off the front from
its mirror 30 deg off the back (the same ITD and ILD, only the ear's shape differs), the rms
over ERB bands from 4 to 16 kHz of the level difference, both ears, both sides. A head with
none (the sphere) can't tell front from back; a big contrast is a candidate for a head
whose back sounds behind you. Not a perceptual model: listening decides (B3).
"""

from __future__ import annotations

import numpy as np

from varimu.binaural.mesh import Mesh


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def scale_pinnae(
    mesh: Mesh, ears: dict, scale: float, r_in: float = 0.045, r_out: float = 0.075
) -> Mesh:
    d = np.linspace(0, r_out * 1.2, 4001)
    w = 1 - _smoothstep((d - r_in) / (r_out - r_in))
    g = d * (1 + (scale - 1) * w)
    if np.any(np.diff(g) <= 0):
        raise ValueError(f"scale {scale}: the map folds; widen r_out - r_in")
    v = mesh.vertices.copy()
    for e in ears.values():
        e = np.asarray(e, float)
        r = np.linalg.norm(v - e, axis=1)
        ww = 1 - _smoothstep((r - r_in) / (r_out - r_in))
        v = e + (v - e) * (1 + (scale - 1) * ww)[:, None]
    return Mesh(v, mesh.faces)


def erb_edges(lo=4000.0, hi=16000.0, n=12) -> np.ndarray:
    e = 21.4 * np.log10(1 + 0.00437 * np.array([lo, hi]))
    x = np.linspace(e[0], e[1], n + 1)
    return (10 ** (x / 21.4) - 1) / 0.00437


def front_back_contrast(head) -> float:
    f = np.asarray(head.f_hz)
    edges = erb_edges()
    H = head.tf([30.0, 150.0, 330.0, 210.0], [0.0] * 4)  # (2, 4, F)
    b = []
    for a, c in zip(edges[:-1], edges[1:], strict=True):
        s = (f >= a) & (f < c)
        b.append(10 * np.log10(np.mean(np.abs(H[..., s]) ** 2, axis=-1) + 1e-20))
    B = np.stack(b, axis=-1)  # (2, 4, bands)
    d = np.concatenate([B[:, 0] - B[:, 1], B[:, 2] - B[:, 3]])
    return float(np.sqrt(np.mean(d**2)))

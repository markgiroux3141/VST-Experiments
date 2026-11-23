"""Exact references for the solver (docs/BINAURAL_PLAN.md): a rigid sphere.

`sphere_hrtf`: the pressure at a point at radius r_e >= a outside a rigid sphere of radius a
(centred at the origin), from a plane wave arriving from direction u, per pascal of the
plane wave at the centre (e^{+jwt}: the wave ~ e^{+jk u . x}), the classic series

    p = sum_n (2n+1) j^n [j_n(k r_e) - j_n'(ka) / h_n'(ka) h_n(k r_e)] P_n(cos g)

with g the angle between the point and u, h_n = h_n^(2). At r_e = a it is (1 / (ka)^2) sum
j^(n-1) (2n+1) P_n / h_n'(ka) (the Wronskian; varimu.mics.free_field.sphere_entry_factors).
By reciprocity it is also the far field of a point source at that point, normalized as the
HRTF is (varimu.binaural.solve).
"""

from __future__ import annotations

import numpy as np
from scipy.special import spherical_jn, spherical_yn


def _legendre(n_max: int, x: np.ndarray) -> np.ndarray:
    p = np.zeros((n_max + 1, *np.shape(x)))
    p[0] = 1.0
    if n_max >= 1:
        p[1] = x
    for n in range(1, n_max):
        p[n + 1] = ((2 * n + 1) * x * p[n] - n * p[n - 1]) / (n + 1)
    return p


def sphere_hrtf(f_hz, cos_g, a_m: float, r_e_m: float, c_m_s: float) -> np.ndarray:
    """(points, F) for cos_g (points,) and f_hz (F,)."""
    f = np.atleast_1d(np.asarray(f_hz, float))
    cg = np.atleast_1d(np.asarray(cos_g, float))
    out = np.ones((len(cg), len(f)), complex)
    for i, fi in enumerate(f):
        if fi == 0:
            continue
        k = 2 * np.pi * fi / c_m_s
        n_max = int(k * max(a_m, r_e_m)) + 25
        n = np.arange(n_max + 1)
        jd = spherical_jn(n, k * a_m, derivative=True)
        hd = jd - 1j * spherical_yn(n, k * a_m, derivative=True)
        jr = spherical_jn(n, k * r_e_m)
        hr = jr - 1j * spherical_yn(n, k * r_e_m)
        coef = (2 * n + 1) * (1j) ** n * (jr - jd / hd * hr)
        out[:, i] = coef @ _legendre(n_max, cg)
    return out

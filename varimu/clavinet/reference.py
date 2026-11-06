"""An independent check of `strings.py`: the whole string as plain finite elements
(docs/CLAVINET_PLAN.md, CL1's reference).

Hermite cubic elements (w, w' per node) along the whole string, pin to tailpiece, with a node
at the anvil. Each element has:
- the consistent mass (mu, plus the yarn's mass where it lies);
- the bending stiffness EI;
- the geometric stiffness of the tension T;
- the yarn's dashpot, consistent like the mass.

The points are the same as the substructure model's:
- the tailpiece's spring and dashpot;
- held, the pinch at the anvil node and the tangent on its rubber.

Both planes are modelled. Unlike `strings.py`, the slope is continuous through the anvil
(no hinge), and nothing is reduced. The distributed modal losses (air, the steel's bending
loss) aren't in this model, so comparisons set them to zero in both.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from scipy import linalg

from varimu.clavinet import strings


def _element(h: float, ei: float, t: float, rho: float) -> tuple[np.ndarray, np.ndarray]:
    k_b = (
        ei
        / h**3
        * np.array(
            [
                [12, 6 * h, -12, 6 * h],
                [6 * h, 4 * h * h, -6 * h, 2 * h * h],
                [-12, -6 * h, 12, -6 * h],
                [6 * h, 2 * h * h, -6 * h, 4 * h * h],
            ]
        )
    )
    k_g = (
        t
        / (30 * h)
        * np.array(
            [
                [36, 3 * h, -36, 3 * h],
                [3 * h, 4 * h * h, -3 * h, -h * h],
                [-36, -3 * h, 36, -3 * h],
                [3 * h, -h * h, -3 * h, 4 * h * h],
            ]
        )
    )
    m = (
        rho
        * h
        / 420
        * np.array(
            [
                [156, 22 * h, 54, -13 * h],
                [22 * h, 4 * h * h, 13 * h, -3 * h * h],
                [54, 13 * h, 156, -22 * h],
                [-13 * h, -3 * h * h, -22 * h, 4 * h * h],
            ]
        )
    )
    return k_b + k_g, m


def lossless(p: strings.Params) -> strings.Params:
    """p without the distributed modal losses (for a like-for-like comparison)."""
    return replace(p, air_viscosity_pa_s=0.0, eta_bend=0.0)


def eigenvalues(p: strings.Params, held: bool, max_el_m: float = 1.5e-3) -> np.ndarray:
    g = p.geom
    ln, big_l = p.nonspeaking_m, g.length_m
    n1 = max(int(np.ceil(ln / max_el_m)), 4)
    n2 = max(int(np.ceil(big_l / max_el_m)), 8)
    x = np.concatenate([np.linspace(0, ln, n1 + 1), ln + np.linspace(0, big_l, n2 + 1)[1:]])
    nn = x.size
    nd = 2 * nn  # per plane
    tension = p.tension_held_n if held else p.tension_rest_n
    yarn_end = min(p.yarn_length_m, ln)
    k1 = np.zeros((nd, nd))
    m1 = np.zeros((nd, nd))
    c1 = np.zeros((nd, nd))
    for e in range(nn - 1):
        h = x[e + 1] - x[e]
        idx = np.arange(2 * e, 2 * e + 4)
        mid = 0.5 * (x[e] + x[e + 1])
        yarn = mid < yarn_end
        ke, me = _element(h, g.ei_n_m2, tension, g.mu_kg_m + (p.yarn_mass_kg_m if yarn else 0.0))
        k1[np.ix_(idx, idx)] += ke
        m1[np.ix_(idx, idx)] += me
        if yarn:
            _, ce = _element(h, 0.0, 0.0, p.yarn_damping_ns_m2)
            c1[np.ix_(idx, idx)] += ce
    tail = 2 * (nn - 1)
    k1[tail, tail] += p.tailpiece_k_n_m
    c1[tail, tail] += p.tailpiece_c_ns_m
    anvil = 2 * n1
    # both planes, the pin's w removed
    free = np.setdiff1d(np.arange(nd), [0])
    nf = free.size
    n = 2 * nf + (1 if held else 0)
    m = np.zeros((n, n))
    c = np.zeros((n, n))
    k = np.zeros((n, n))
    for pl in (0, 1):
        s = slice(pl * nf, (pl + 1) * nf)
        m[s, s] = m1[np.ix_(free, free)]
        c[s, s] = c1[np.ix_(free, free)]
        k[s, s] = k1[np.ix_(free, free)]
    a_y = int(np.flatnonzero(free == anvil)[0])
    a_x = nf + a_y
    if held:
        nrm = np.array([np.cos(p.tilt_rad), np.sin(p.tilt_rad)])
        tan = np.array([-np.sin(p.tilt_rad), np.cos(p.tilt_rad)])
        ii = np.array([a_y, a_x])
        k[np.ix_(ii, ii)] += p.anvil_k_n_m * np.outer(nrm, nrm) + p.grip_k_n_m * np.outer(tan, tan)
        c[np.ix_(ii, ii)] += p.anvil_c_ns_m * np.outer(nrm, nrm) + p.grip_c_ns_m * np.outer(
            tan, tan
        )
        z = n - 1
        _, kr, cr = p.rubber_static()
        m[z, z] = p.tangent_mass_kg
        for i, j, sg in ((a_y, a_y, 1), (z, z, 1), (a_y, z, -1), (z, a_y, -1)):
            k[i, j] += sg * kr
            c[i, j] += sg * cr
    minv = np.linalg.inv(m)
    a = np.zeros((2 * n, 2 * n))
    a[:n, n:] = np.eye(n)
    a[n:, :n] = -minv @ k
    a[n:, n:] = -minv @ c
    return linalg.eigvals(a)


def compare(
    p: strings.Params, held: bool, f_max_hz: float = 4000.0
) -> list[tuple[float, float, float, float]]:
    """(f_ref, f_cb, sigma_ref, sigma_cb) for every reference mode below f_max_hz, paired
    one to one with the substructure eigenvalues (the assignment minimizing the summed
    distance in the complex plane; both lossless)."""
    from scipy.optimize import linear_sum_assignment

    q = lossless(p)
    ref = eigenvalues(q, held)
    cb = strings.system(q, held).lam
    ref = ref[(ref.imag > 0) & (ref.imag < 2 * np.pi * f_max_hz)]
    cb = cb[(cb.imag > 0) & (cb.imag < 2 * np.pi * f_max_hz * 1.2)]
    cost = np.abs(ref[:, None] - cb[None, :])
    i, j = linear_sum_assignment(cost)
    order = np.argsort(ref[i].imag)
    return [
        (ref[a].imag / (2 * np.pi), cb[b].imag / (2 * np.pi), -ref[a].real, -cb[b].real)
        for a, b in zip(i[order], j[order], strict=True)
    ]

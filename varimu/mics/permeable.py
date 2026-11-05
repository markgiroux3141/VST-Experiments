"""A sound-permeable spherical shell in a plane wave: the exact series (docs/SM57_PLAN.md SM8,
"checked on the textbook cases first: a permeable sphere against its series solution").

The SM58's ball grille is a wire mesh (and foam) through which sound passes: in the model a
thin sheet of specific transfer impedance Z_s (Pa s/m): the normal velocity is continuous
through it and the pressure jumps by Z_s v_n. The permeable boundary-element surface SM8
adds to varimu.mics.bor is checked against this case: a shell of radius a in free field, a
unit plane wave from theta = 0 (e^{+j w t}, as bor.py and free_field.py).

Per order n (Legendre P_n(cos theta)): outside p = (2n+1) j^n [j_n(kr) + B_n h_n(kr)] (the
incident wave from +z, e^{+jkz} = sum (2n+1) j^n j_n P_n as bor.plane_wave; h_n = h_n^(2),
outgoing for e^{+j w t}), inside p = (2n+1) j^n A_n j_n(kr). At r = a the radial velocity
v = -(1 / (j w rho)) dp/dr is continuous, and the sheet passes flow from high to low
pressure: p_in - p_out = Z_s v. With x = ka and zeta = Z_s / (rho c) (v = -(k / (j w rho))
dp/dx, k / w rho = 1 / rho c):
    A j_n'(x) - B h_n'(x) = j_n'(x)                                   (velocity)
    (1 - A) j_n(x) + B h_n(x) + j zeta A j_n'(x) = 0                  (the jump)
Limits (tests/test_permeable.py): zeta -> 0 is the free field (A = 1, B = 0); zeta ->
infinity a rigid sphere outside (B = -j_n' / h_n') and silence inside; at low frequency the
inside is the shell's air filled through the sheet, A_0 = 1 / (1 + j zeta ka / 3) (the
compliance 4 pi a^3 / (3 rho c^2) behind the resistance Z_s / (4 pi a^2)).

With a rigid core of radius b inside (the check case for a cartridge in the ball), the inside
field is A_n g_n(kr), g_n = j_n + c_n y_n with c_n = -j_n'(kb) / y_n'(kb) (no flow into the
core), and g_n takes j_n's place in the two equations.
"""

from __future__ import annotations

import numpy as np
from scipy.special import spherical_jn, spherical_yn

from varimu.devices.capsule import C_AIR, RHO_AIR


def _h2(n, x, derivative=False):
    return spherical_jn(n, x, derivative=derivative) - 1j * spherical_yn(
        n, x, derivative=derivative
    )


def _core(n, kb: float) -> np.ndarray:
    """c_n: the inside's y_n share with a rigid core of radius b (0 without one)."""
    if kb <= 0:
        return np.zeros(len(n))
    return -spherical_jn(n, kb, derivative=True) / spherical_yn(n, kb, derivative=True)


def shell_coefficients(
    ka: float, zeta: complex, n_max: int, kb: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """(A_n, B_n), n = 0..n_max: the inside's and the scattered wave's coefficients for a
    shell of radius a (ka) and transfer impedance ratio zeta = Z_s / (rho c), a rigid core
    of radius b (kb) inside when kb > 0."""
    n = np.arange(n_max + 1)
    c = _core(n, kb)
    j, jd = spherical_jn(n, ka), spherical_jn(n, ka, derivative=True)
    g = j + c * spherical_yn(n, ka)
    gd = jd + c * spherical_yn(n, ka, derivative=True)
    h, hd = _h2(n, ka), _h2(n, ka, derivative=True)
    # [gd, -hd] [A, B] = jd ;  [-g + j zeta gd, h] [A, B] = -j  (the module docstring)
    a11, a12, b1 = gd, -hd, jd
    a21, a22, b2 = -g + 1j * zeta * gd, h, -j
    det = a11 * a22 - a12 * a21
    a_n = (b1 * a22 - a12 * b2) / det
    b_n = (a11 * b2 - b1 * a21) / det
    return a_n, b_n


def field(
    f_hz: float,
    radius_m: float,
    z_s: complex,
    r_m: np.ndarray,
    theta_rad: np.ndarray,
    core_radius_m: float = 0.0,
) -> np.ndarray:
    """The pressure at (r, theta) per unit incident plane wave (pressure 1 at the origin in
    free field), a shell of radius `radius_m` and transfer impedance `z_s` (Pa s/m), a rigid
    core of `core_radius_m` inside (0: none)."""
    k = 2 * np.pi * f_hz / C_AIR
    ka = k * radius_m
    zeta = z_s / (RHO_AIR * C_AIR)
    n_max = int(ka + 4 * ka ** (1 / 3) + 12)
    a_n, b_n = shell_coefficients(ka, zeta, n_max, k * core_radius_m)
    c_n = _core(np.arange(n_max + 1), k * core_radius_m)
    r = np.atleast_1d(np.asarray(r_m, float))
    th = np.atleast_1d(np.asarray(theta_rad, float))
    out = np.zeros(np.broadcast(r, th).shape, complex)
    rr, tt = np.broadcast_arrays(r, th)
    from varimu.mics.free_field import _legendre

    p = _legendre(n_max, np.cos(tt))
    n = np.arange(n_max + 1)
    for i, (rv, pv) in enumerate(zip(rr.ravel(), p.reshape(n_max + 1, -1).T, strict=True)):
        x = k * rv
        jn = spherical_jn(n, x)
        if rv < radius_m:
            terms = a_n * (jn + c_n * spherical_yn(n, x)) if core_radius_m > 0 else a_n * jn
        else:
            terms = jn + b_n * _h2(n, x)
        out.ravel()[i] = np.sum((2 * n + 1) * (1j) ** n * terms * pv)
    return out

"""A capsule in free field, driven by a plane wave from an angle (MIC_ROOM_PLAN.md: "free
field first"): the pressures at its front and rear entries.

A plane wave from angle theta (0: on axis, from the front) reaches the front entry and,
`path_m` cos(theta) later, the rear entry: the pressure-gradient capsule's drive. The
phase reference is the capsule's centre (front leads by half the delay, rear lags by
half). `path_m` is the capsule's effective front-to-rear path (around the capsule and
its head basket: a fitted, bounded value). Diffraction by the body and basket (the
pressure build-up on the front face at high frequencies) is a later fidelity item
(MIC_ROOM_PLAN.md); here both entries see the free-field pressure.

For renders: `entry_pressures(p, theta, path_m, fs)` gives the two pressure signals
(the rear the front delayed by a fractional number of samples, an FFT delay on the
whole signal).
"""

from __future__ import annotations

import numpy as np

from varimu.devices.capsule import C_AIR


def entry_factors(
    f_hz: np.ndarray, theta_rad: float, path_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """Complex pressure at the front and rear entries per pascal of the plane wave at
    the capsule's centre."""
    w = 2 * np.pi * np.asarray(f_hz, float)
    tau = path_m * np.cos(theta_rad) / C_AIR
    return np.exp(0.5j * w * tau), np.exp(-0.5j * w * tau)


def _delay(x: np.ndarray, delay_s: float, fs: int) -> np.ndarray:
    n = len(x)
    m = 1 << int(np.ceil(np.log2(2 * n)))
    f = np.fft.rfftfreq(m, 1.0 / fs)
    y = np.fft.irfft(np.fft.rfft(x, m) * np.exp(-2j * np.pi * f * delay_s), m)
    return y[:n]


def entry_pressures(
    p: np.ndarray, theta_rad: float, path_m: float, fs: int
) -> tuple[np.ndarray, np.ndarray]:
    """The front and rear entries' pressure signals for a plane wave whose pressure at
    the capsule's centre is `p` (pascals at fs)."""
    tau = path_m * np.cos(theta_rad) / C_AIR
    return _delay(p, -0.5 * tau, fs), _delay(p, 0.5 * tau, fs)


def _legendre(n_max: int, x: np.ndarray) -> np.ndarray:
    """P_0..P_n_max at x (rows), by the three-term recursion."""
    p = np.zeros((n_max + 1, *np.shape(x)))
    p[0] = 1.0
    if n_max >= 1:
        p[1] = x
    for n in range(1, n_max):
        p[n + 1] = ((2 * n + 1) * x * p[n] - n * p[n - 1]) / (n + 1)
    return p


def sphere_entry_factors(
    f_hz: np.ndarray, theta_rad: float, radius_m: float, cap_radius_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """Complex pressure at the front and rear entries per pascal of a plane wave at the
    centre, the capsule a rigid sphere of `radius_m` whose entries are the caps at its
    poles (+z faces theta = 0) with the diaphragm's area (`cap_radius_m`), each averaged
    with the parabolic mode shape: the exact series (data/schematics/neumann_u47/
    K47_THEORY.md: p(a, g) / p0 = (1 / (ka)^2) sum_n j^(n-1) (2n+1) P_n(cos g) / h_n^(2)'(ka),
    e^{+j w t}; Duda & Martens, JASA 1998), the azimuth averaged by the addition theorem.
    At low frequency the entries are 3a apart (1 + (3/2) j ka cos g); the face toward the
    source builds up to +6 dB, the far one is shadowed: a dual-diaphragm capsule's omni sum
    doesn't notch where a free-field path would."""
    from scipy.special import spherical_jn, spherical_yn

    f = np.atleast_1d(np.asarray(f_hz, float))
    ka = 2 * np.pi * f * radius_m / C_AIR
    n_max = int(np.max(ka)) + 15
    n = np.arange(n_max + 1)
    # The cap: half-angle alpha with the diaphragm's area; the mode w = 1 - (rho / c)^2 on
    # rho = a sin(beta) (the cap's radius from its axis), weighted by the area element.
    alpha = np.arccos(1.0 - 0.5 * (cap_radius_m / radius_m) ** 2)
    beta = np.linspace(0.0, alpha, 201)
    rho = radius_m * np.sin(beta)
    w = np.clip(1.0 - (rho / (radius_m * np.sin(alpha))) ** 2, 0.0, None) * np.sin(beta)
    pb = _legendre(n_max, np.cos(beta))
    cap = np.trapezoid(pb * w, beta, axis=1) / np.trapezoid(w, beta)  # per n
    out = []
    for g in (theta_rad, np.pi - theta_rad):
        pn = _legendre(n_max, np.array(np.cos(g)))
        terms = []
        for x in ka:
            h2d = spherical_jn(n, x, derivative=True) - 1j * spherical_yn(n, x, derivative=True)
            terms.append(np.sum((1j) ** (n - 1) * (2 * n + 1) * pn * cap / h2d) / x**2)
        out.append(np.array(terms))
    return out[0], out[1]


def sphere_entry_pressures(
    p: np.ndarray, theta_rad: float, radius_m: float, cap_radius_m: float, fs: int
) -> tuple[np.ndarray, np.ndarray]:
    """The front and rear entries' pressure signals on the rigid sphere
    (`sphere_entry_factors`) for a plane wave whose pressure at the centre is `p`
    (pascals at fs): each entry's response applied to the whole signal by FFT."""
    n = len(p)
    m = 1 << int(np.ceil(np.log2(2 * n)))
    f = np.fft.rfftfreq(m, 1.0 / fs)
    # The series on a coarse grid, interpolated (it is smooth); DC is 1 exactly.
    grid = np.unique(np.r_[np.geomspace(1.0, fs / 2, 400), fs / 2])
    front, rear = sphere_entry_factors(grid, theta_rad, radius_m, cap_radius_m)
    spec = np.fft.rfft(p, m)
    out = []
    for h in (front, rear):
        mag = np.interp(f, np.r_[0.0, grid], np.r_[1.0, np.abs(h)])
        ph = np.interp(f, np.r_[0.0, grid], np.r_[0.0, np.unwrap(np.angle(h))])
        out.append(np.fft.irfft(spec * mag * np.exp(1j * ph), m)[:n])
    return out[0], out[1]

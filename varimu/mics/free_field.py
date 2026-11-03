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


def capsule_entry_pressures(
    geometry: dict, p: np.ndarray, theta_rad: float, fs: int, distance_m: float = np.inf
) -> tuple[np.ndarray, np.ndarray, str]:
    """A capsule component's entries for a wave whose free-field pressure at its centre is
    `p`, by what its geometry gives: a `body` (the BEM, `body_entry_pressures`; a point
    source when `distance_m` is finite), a `sphere_radius_m` (K47@2), else `path_m` apart
    in free field (0: a pressure capsule). The third value says which."""
    a = geometry.get("diaphragm", {}).get("radius_m")
    if "body" in geometry:
        front, rear = body_entry_pressures(p, theta_rad, geometry["body"], a, fs, distance_m)
        return front, rear, f"body {geometry['body']}, distance {distance_m} m"
    if not np.isinf(distance_m):
        raise ValueError("a source distance needs a capsule body (varimu.mics.bor)")
    if "sphere_radius_m" in geometry:
        sph = (geometry["sphere_radius_m"], a)
        return (*sphere_entry_pressures(p, theta_rad, *sph, fs), f"sphere {sph}")
    path = float(geometry.get("path_m", 0.0) or 0.0)
    return (*entry_pressures(p, theta_rad, path, fs), f"path {path}")


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


def sphere_point_factors(
    f_hz: np.ndarray,
    theta_rad: float,
    radius_m: float,
    cap_radius_m: float,
    distance_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """As `sphere_entry_factors` for a point source `distance_m` from the centre toward
    theta, per pascal of its free-field pressure at the centre (Duda & Martens, JASA 1998,
    the range-dependent series; derived from e^{-jkR} / R = -jk sum (2n+1) j_n(kr)
    h_n(k r_s) P_n and the Wronskian): p / p0 = -(k r_s e^{jk r_s} / (ka)^2) sum_n (2n+1)
    P_n(cos g) h_n^{(2)}(k r_s) / h_n^{(2)}'(ka). It tends to the plane wave's series as
    r_s -> infinity (k r_s e^{jk r_s} h_n(k r_s) -> j^(n+1))."""
    from scipy.special import spherical_jn, spherical_yn

    f = np.atleast_1d(np.asarray(f_hz, float))
    k = 2 * np.pi * f / C_AIR
    ka = k * radius_m
    n_max = int(np.max(ka)) + 15
    n = np.arange(n_max + 1)
    alpha = np.arccos(1.0 - 0.5 * (cap_radius_m / radius_m) ** 2)
    beta = np.linspace(0.0, alpha, 201)
    rho = radius_m * np.sin(beta)
    w = np.clip(1.0 - (rho / (radius_m * np.sin(alpha))) ** 2, 0.0, None) * np.sin(beta)
    cap = np.trapezoid(_legendre(n_max, np.cos(beta)) * w, beta, axis=1) / np.trapezoid(w, beta)
    out = []
    for g in (theta_rad, np.pi - theta_rad):
        pn = _legendre(n_max, np.array(np.cos(g)))
        terms = []
        for kk, x in zip(k, ka, strict=True):
            xs = kk * distance_m
            hs = spherical_jn(n, xs) - 1j * spherical_yn(n, xs)
            h2d = spherical_jn(n, x, derivative=True) - 1j * spherical_yn(n, x, derivative=True)
            s = np.sum((2 * n + 1) * pn * cap * (hs / h2d))
            terms.append(-xs * np.exp(1j * xs) * s / x**2)
        out.append(np.array(terms))
    return out[0], out[1]


def body_entry_factors(
    f_hz: np.ndarray,
    theta_rad: np.ndarray,
    body: dict,
    diaphragm_radius_m: float,
    distance_m: float = np.inf,
) -> tuple[np.ndarray, np.ndarray]:
    """The front and rear entries (freqs, angles) on the capsule's real body
    (varimu.mics.bor: a rigid body of revolution, `bor.BODY_FIELDS`), per pascal of the
    incident wave's free-field pressure at the centre: a plane wave from theta, or a point
    source `distance_m` away. Each call solves the BEM (~0.2 s per frequency); see
    `body_entry_grid` for a cached grid."""
    from varimu.mics import bor

    op = bor.operator(bor.capsule_mesh(body, diaphragm_radius_m))
    return bor.entry_factors(op, np.atleast_1d(f_hz), np.atleast_1d(theta_rad), distance_m)


def body_entry_grid(
    theta_rad: float, body: dict, diaphragm_radius_m: float, distance_m: float, f_max_hz: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(f, front, rear) on a log grid to f_max_hz for one angle, cached in
    cache/diffraction/ by the inputs and bor.py's source (the BEM takes a minute)."""
    import hashlib
    import json
    from pathlib import Path

    from varimu.config import REPO_ROOT

    src = (Path(__file__).parent / "bor.py").read_bytes()
    key = json.dumps(
        [theta_rad, body, diaphragm_radius_m, str(distance_m), f_max_hz], sort_keys=True
    )
    h = hashlib.sha256(src + key.encode()).hexdigest()[:24]
    path = REPO_ROOT / "cache" / "diffraction" / f"{h}.npz"
    if path.exists():
        d = np.load(path)
        return d["f"], d["front"], d["rear"]
    f = np.unique(np.r_[np.geomspace(5.0, f_max_hz, 240), f_max_hz])
    front, rear = body_entry_factors(f, [theta_rad], body, diaphragm_radius_m, distance_m)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, f=f, front=front[:, 0], rear=rear[:, 0])
    return f, front[:, 0], rear[:, 0]


def _apply(p: np.ndarray, fs: int, grid: np.ndarray, responses) -> list[np.ndarray]:
    """Each response (complex, on `grid`, 1 at DC) applied to the whole signal by FFT,
    interpolated in magnitude and unwrapped phase."""
    n = len(p)
    m = 1 << int(np.ceil(np.log2(2 * n)))
    f = np.fft.rfftfreq(m, 1.0 / fs)
    spec = np.fft.rfft(p, m)
    out = []
    for h in responses:
        mag = np.interp(f, np.r_[0.0, grid], np.r_[1.0, np.abs(h)])
        ph = np.interp(f, np.r_[0.0, grid], np.r_[0.0, np.unwrap(np.angle(h))])
        out.append(np.fft.irfft(spec * mag * np.exp(1j * ph), m)[:n])
    return out


def body_entry_pressures(
    p: np.ndarray,
    theta_rad: float,
    body: dict,
    diaphragm_radius_m: float,
    fs: int,
    distance_m: float = np.inf,
) -> tuple[np.ndarray, np.ndarray]:
    """The front and rear entries' pressure signals on the capsule's body
    (`body_entry_grid`) for a wave whose free-field pressure at the centre is `p`
    (pascals at fs)."""
    grid, front, rear = body_entry_grid(theta_rad, body, diaphragm_radius_m, distance_m, fs / 2)
    return tuple(_apply(p, fs, grid, (front, rear)))


def sphere_entry_pressures(
    p: np.ndarray, theta_rad: float, radius_m: float, cap_radius_m: float, fs: int
) -> tuple[np.ndarray, np.ndarray]:
    """The front and rear entries' pressure signals on the rigid sphere
    (`sphere_entry_factors`) for a plane wave whose pressure at the centre is `p`
    (pascals at fs): each entry's response applied to the whole signal by FFT."""
    # The series on a coarse grid, interpolated (it is smooth); DC is 1 exactly.
    grid = np.unique(np.r_[np.geomspace(1.0, fs / 2, 400), fs / 2])
    front, rear = sphere_entry_factors(grid, theta_rad, radius_m, cap_radius_m)
    return tuple(_apply(p, fs, grid, (front, rear)))

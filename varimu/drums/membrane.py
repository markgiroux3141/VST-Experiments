"""A struck drumhead (docs/DRUM_PLAN.md, D1's first test): one circular membrane, a beater,
the pressure it radiates. Offline, Python only.

**Modes.** An ideal membrane of radius a, tension T0 (N/m) and mass per area sigma = rho h,
fixed at the rim: `Phi_mn(r, phi) = N_mn J_m(j_mn r / a) cos(m phi)`, `omega_mn = j_mn c / a`
with `c = sqrt(T0 / sigma)` and j_mn the n-th zero of J_m, normalized so the integral of
Phi^2 over the head is 1 (`N_mn^2 = 2 / (eps_m pi a^2 J_{m+1}(j_mn)^2)`, eps_0 = 2, else 1).
The strike and the mic lie on the line phi = 0, so the sin(m phi) twins are never excited
and are left out. The head's bending stiffness is neglected (a 10 mil Mylar head is a
membrane well into the kHz range) and so is the air's mass load: the modes are the head's
in vacuo, without a shell or a second head (DRUM_PLAN.md's next step).

**Tension modulation** (the pitch glide). A deflection w stretches the head by
`dA / A = (1 / 2A) integral |grad w|^2`; taken as a uniform biaxial strain (the rim held:
Berger's averaging, provisional: model knowledge), `eps = dA / 2A` and the tension rises by
`dT = E h eps / (1 - nu) = E h / (4 A (1 - nu)) integral |grad w|^2`. With orthonormal
modes `integral |grad w|^2 = sum lambda_k q_k^2`, lambda_k = (j_k / a)^2, so every mode's
stiffness is `T(t) lambda_k` with one shared T(t): a hard hit raises all frequencies by
the same factor sqrt(T / T0), which falls back as the head rings down.

**The beater** is a mass on a power-law contact (Hunt-Crossley: `F = K d^p (1 + alpha
d')` while the compression d > 0, the felt hammer law of piano models), pressing over
its face: the head's deflection under it and the force's share per mode are Phi averaged
over the face's disk (the face's size low-passes the strike).

**Losses** per mode, as amplitude decay rates: radiation into the half space in front of
a baffled head (the Rayleigh integral's far field, integrated over the hemisphere) plus
the film's own loss, `eta omega / 2`.

**The pressure** at the mic (distance R, angle theta off the axis, in the strike's
plane): the Rayleigh integral's far field, `p = rho0 / (2 pi R) sum D_k a_k`, with D_k =
`N_k 2 pi i^m integral_0^a J_m(j_k r / a) J_m(k r sin theta) r dr` taken at each mode's own
frequency (a mode is narrow-band: exact once the strike is over) and the factor i^m (a
90-degree lead per m) applied to the mode's acceleration as `-omega_k v_k`.

**Numerics.** Central differences at the project's rate per mode, each mode's stiffness
scaled by (2 - 2 cos(omega h)) / (omega h)^2 so its frequency is exact at T0; the beater's
contact is explicit (its stiffness is far below the step's limit).

`load(name)` reads `config/drums/<name>.yaml`, every value `{value, source}`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy import special

from varimu.config import CONFIG_DIR

DRUMS_DIR = CONFIG_DIR / "drums"


@dataclass(frozen=True)
class Head:
    radius_m: float
    thickness_m: float
    density_kg_m3: float
    youngs_pa: float
    poisson: float
    loss_factor: float
    f01_hz: float  # the tuning: the (0,1) mode in vacuo, sets the tension

    @property
    def sigma_kg_m2(self) -> float:
        return self.density_kg_m3 * self.thickness_m

    @property
    def tension_n_m(self) -> float:
        j01 = special.jn_zeros(0, 1)[0]
        c = 2 * np.pi * self.radius_m * self.f01_hz / j01
        return self.sigma_kg_m2 * c * c

    @property
    def stretch_n_m(self) -> float:
        """E h / (4 A (1 - nu)), N/m^3: the tension's rise per m^2 of the integral of
        |grad w|^2 over the head."""
        area = np.pi * self.radius_m**2
        return self.youngs_pa * self.thickness_m / (4 * area * (1 - self.poisson))


@dataclass(frozen=True)
class Beater:
    mass_kg: float
    face_radius_m: float
    stiffness: float  # K, N / m^p
    exponent: float  # p
    hysteresis_s_m: float  # alpha


@dataclass(frozen=True)
class Drum:
    name: str
    head: Head
    beater: Beater
    strike_radius_m: float
    mic_distance_m: float
    mic_angle_deg: float
    air_density_kg_m3: float
    sound_speed_m_s: float
    f_max_hz: float
    full_scale_pa: float


def _values(block: dict[str, Any], where: str) -> dict[str, float]:
    out = {}
    for key, entry in block.items():
        if not (isinstance(entry, dict) and "value" in entry and entry.get("source")):
            raise ValueError(f"{where}.{key}: needs {{value, source}}, got {entry!r}")
        out[key] = float(entry["value"])
    return out


def load(name: str, path: Path | None = None) -> Drum:
    """The drum `config/drums/<name>.yaml` (or `path`)."""
    path = path or DRUMS_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    head = Head(**_values(data["head"], "head"))
    beater = Beater(**_values(data["beater"], "beater"))
    rest = {}
    for block in ("strike", "mic", "air", "numerics"):
        rest.update(_values(data[block], block))
    drum = Drum(name=name, head=head, beater=beater, **rest)
    if drum.strike_radius_m + beater.face_radius_m >= head.radius_m:
        raise ValueError(f"{path}: the beater's face reaches past the rim")
    return drum


@dataclass(frozen=True)
class Modes:
    """The excited modes below f_max (m outer, n inner)."""

    m: np.ndarray  # int
    n: np.ndarray  # int, 1-based
    j: np.ndarray  # the Bessel zeros
    norm: np.ndarray  # N_mn
    lam: np.ndarray  # (j / a)^2, 1/m^2
    omega0: np.ndarray  # rad/s at T0

    @property
    def f0_hz(self) -> np.ndarray:
        return self.omega0 / (2 * np.pi)


def modes(head: Head, f_max_hz: float) -> Modes:
    a = head.radius_m
    c = np.sqrt(head.tension_n_m / head.sigma_kg_m2)
    x_max = 2 * np.pi * f_max_hz * a / c
    ms, ns, js = [], [], []
    m = 0
    while True:
        n = max(1, int(x_max / np.pi - m / 2 + 3))
        zeros = special.jn_zeros(m, n)
        while zeros[-1] <= x_max:
            n *= 2
            zeros = special.jn_zeros(m, n)
        zeros = zeros[zeros <= x_max]
        if zeros.size == 0:  # j_m1 rises with m: no higher m has one either
            break
        ms += [m] * zeros.size
        ns += list(range(1, zeros.size + 1))
        js += list(zeros)
        m += 1
    m_arr = np.array(ms)
    j = np.array(js)
    eps = np.where(m_arr == 0, 2.0, 1.0)
    norm = np.sqrt(2.0 / (eps * np.pi * a * a * special.jv(m_arr + 1, j) ** 2))
    return Modes(
        m=m_arr,
        n=np.array(ns),
        j=j,
        norm=norm,
        lam=(j / a) ** 2,
        omega0=j * c / a,
    )


def shape(md: Modes, a: float, r: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """Phi_k at points (r, phi): shape (modes, points)."""
    r = np.asarray(r, dtype=float).ravel()
    phi = np.asarray(phi, dtype=float).ravel()
    jm = special.jv(md.m[:, None], md.j[:, None] * r[None, :] / a)
    return md.norm[:, None] * jm * np.cos(md.m[:, None] * phi[None, :])


def face_average(md: Modes, a: float, r0: float, b: float) -> np.ndarray:
    """Phi_k averaged over the disk of radius b centred at (r0, phi = 0)."""
    if b <= 0.0:
        return shape(md, a, np.array([r0]), np.array([0.0]))[:, 0]
    x, w = np.polynomial.legendre.leggauss(16)
    rho = 0.5 * b * (x + 1)
    w_rho = 0.5 * b * w * rho
    n_psi = 48
    psi = 2 * np.pi * (np.arange(n_psi) + 0.5) / n_psi
    rr, pp = np.meshgrid(rho, psi, indexing="ij")
    px = r0 + rr * np.cos(pp)
    py = rr * np.sin(pp)
    weights = (w_rho[:, None] * np.full(n_psi, 2 * np.pi / n_psi)[None, :]).ravel()
    phi_k = shape(md, a, np.hypot(px, py).ravel(), np.arctan2(py, px).ravel())
    return phi_k @ weights / (np.pi * b * b)


def _radial_integral(md: Modes, a: float, k_air: np.ndarray, sin_theta: np.ndarray) -> np.ndarray:
    """integral_0^a J_m(j_k r / a) J_m(k_k r sin theta) r dr: shape (modes, thetas)."""
    x, w = np.polynomial.legendre.leggauss(192)
    r = 0.5 * a * (x + 1)
    wr = 0.5 * a * w * r
    out = np.empty((md.m.size, sin_theta.size))
    for lo in range(0, md.m.size, 256):
        sl = slice(lo, lo + 256)
        m = md.m[sl, None, None]
        head = special.jv(m, md.j[sl, None, None] * r[None, None, :] / a)
        air = special.jv(m, k_air[sl, None, None] * sin_theta[None, :, None] * r[None, None, :])
        out[sl] = (head * air) @ wr
    return out


def directivity(md: Modes, drum: Drum) -> np.ndarray:
    """D_k at the mic (complex, m^1), at each mode's own frequency."""
    k_air = md.omega0 / drum.sound_speed_m_s
    s = np.array([np.sin(np.radians(drum.mic_angle_deg))])
    radial = _radial_integral(md, drum.head.radius_m, k_air, s)[:, 0]
    return md.norm * 2 * np.pi * (1j**md.m) * radial


def radiation_decay(md: Modes, drum: Drum) -> np.ndarray:
    """Each mode's amplitude decay rate (1/s) from radiating into the front half space
    of a baffled head: s = rho0 omega^2 integral |D|^2 dOmega / (8 pi^2 c sigma)."""
    k_air = md.omega0 / drum.sound_speed_m_s
    x, w = np.polynomial.legendre.leggauss(64)
    theta = 0.25 * np.pi * (x + 1)
    w_theta = 0.25 * np.pi * w * np.sin(theta)
    radial = _radial_integral(md, drum.head.radius_m, k_air, np.sin(theta))
    azimuth = np.where(md.m == 0, 2 * np.pi, np.pi)  # integral of cos^2(m phi)
    d2 = (md.norm * 2 * np.pi) ** 2 * azimuth * (radial**2 @ w_theta)
    rho0, c0 = drum.air_density_kg_m3, drum.sound_speed_m_s
    return rho0 * md.omega0**2 * d2 / (8 * np.pi**2 * c0 * drum.head.sigma_kg_m2)


@dataclass(frozen=True)
class Prepared:
    drum: Drum
    modes: Modes
    face: np.ndarray  # Phi_k averaged over the beater's face
    decay: np.ndarray  # amplitude decay rate, 1/s
    decay_radiation: np.ndarray
    mic: np.ndarray  # D_k, complex


def prepare(drum: Drum) -> Prepared:
    md = modes(drum.head, drum.f_max_hz)
    face = face_average(md, drum.head.radius_m, drum.strike_radius_m, drum.beater.face_radius_m)
    s_rad = radiation_decay(md, drum)
    s = s_rad + 0.5 * drum.head.loss_factor * md.omega0
    return Prepared(drum, md, face, s, s_rad, directivity(md, drum))


@dataclass(frozen=True)
class Hit:
    fs: float
    pressure_pa: np.ndarray
    force_n: np.ndarray
    tension_n_m: np.ndarray
    f01_hz: np.ndarray  # the (0,1) mode's frequency, sqrt(T / T0) f01

    @property
    def contact_s(self) -> float:
        on = np.flatnonzero(self.force_n > 0)
        return 0.0 if on.size == 0 else (on[-1] - on[0] + 1) / self.fs


def run(
    prep: Prepared,
    *,
    fs: float,
    seconds: float,
    velocity_m_s: float = 0.0,
    q0: np.ndarray | None = None,
    tension_modulation: bool = True,
) -> Hit:
    """The head struck by the beater at `velocity_m_s` (or released from modal
    displacements `q0` with no beater), for `seconds` at `fs`."""
    drum, md = prep.drum, prep.modes
    h = 1.0 / fs
    sigma = drum.head.sigma_kg_m2
    t0 = drum.head.tension_n_m
    stretch = drum.head.stretch_n_m if tension_modulation else 0.0
    wh = md.omega0 * h
    om2h2 = 2.0 - 2.0 * np.cos(wh)  # omega^2 h^2, warped to be exact at T0
    sh = prep.decay * h
    a_plus = 1.0 / (1.0 + sh)
    a_minus = 1.0 - sh
    drive = prep.face * h * h / sigma
    gain = drum.air_density_kg_m3 / (2 * np.pi * drum.mic_distance_m)
    g_acc = gain * prep.mic.real / (h * h)
    g_vel = gain * prep.mic.imag * md.omega0 / (2 * h)
    lam = md.lam
    bt = drum.beater
    n_steps = int(round(seconds * fs))
    pressure = np.zeros(n_steps)
    force = np.zeros(n_steps)
    tension = np.zeros(n_steps)

    # The contact is implicit: the step's force is the law at the next step's compression,
    # which is linear in the force (d = d_free - compliance F), a scalar root per step.
    # Explicitly, a small face (a stick's tip) sees so little of the head's mass that the
    # contact's frequency is far past the step's limit.
    drive_a = drive * a_plus
    compliance = h * h / bt.mass_kg + prep.face @ drive_a

    def law(d: float, d_now: float) -> float:
        if d <= 0.0:
            return 0.0
        return max(
            bt.stiffness * d**bt.exponent * (1.0 + bt.hysteresis_s_m * (d - d_now) * fs), 0.0
        )

    q = np.zeros(md.m.size) if q0 is None else np.asarray(q0, dtype=float).copy()
    qp = q.copy()
    striking = velocity_m_s > 0.0
    y = 0.0
    yp = -velocity_m_s * h
    for i in range(n_steps):
        t = t0 + stretch * (lam @ (q * q))
        ratio = t / t0
        qn = (2.0 * q - a_minus * qp - ratio * om2h2 * q) * a_plus
        f = 0.0
        if striking:
            y_free = 2.0 * y - yp
            d_free = y_free - prep.face @ qn
            if d_free > 0.0:
                f = _contact_force(law, d_free, compliance, y - prep.face @ q)
                qn += drive_a * f
            y, yp = y_free - h * h * f / bt.mass_kg, y
        pressure[i] = g_acc @ (qn - 2.0 * q + qp) - np.sqrt(ratio) * (g_vel @ (qn - qp))
        force[i] = f
        tension[i] = t
        qp, q = q, qn
    f01 = md.f0_hz[0] * np.sqrt(tension / t0)
    return Hit(fs, pressure, force, tension, f01)


def _contact_force(law, d_free: float, compliance: float, d_now: float) -> float:
    """The root F of F = law(d_free - compliance F) in [0, law(d_free)] (the law rises
    with d, so the root is unique): regula falsi, Illinois variant."""
    lo, hi = 0.0, law(d_free, d_now)
    if hi == 0.0:
        return 0.0
    g_lo = -hi
    g_hi = hi - law(d_free - compliance * hi, d_now)
    if g_hi <= 0.0:
        return hi
    side = 0
    f = hi
    for _ in range(200):
        f = (lo * g_hi - hi * g_lo) / (g_hi - g_lo)
        g = f - law(d_free - compliance * f, d_now)
        if abs(g) <= 1e-12 * f or hi - lo <= 1e-13 * hi:
            break
        if g < 0.0:
            lo, g_lo = f, g
            if side == -1:
                g_hi *= 0.5
            side = -1
        else:
            hi, g_hi = f, g
            if side == 1:
                g_lo *= 0.5
            side = 1
    return f

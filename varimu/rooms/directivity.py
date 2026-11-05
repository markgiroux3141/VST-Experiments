"""Sources that radiate more one way than another (docs/ROOM_LOOP_PLAN.md "Later": a source's
directivity): a cap vibrating on a rigid sphere, the classical model of a loudspeaker in its
cabinet and of the mouth in the head (Morse and Ingard, Theoretical Acoustics, 1968, sec.
7.2: the sphere's radiation as spherical harmonics; Flanagan, "Analog measurements of sound
radiation from the mouth", JASA 32(12), 1960, compared the mouth with a piston on a sphere).

A sphere of radius a whose surface moves with normal velocity 1 on the cap theta < alpha (its
radius on the sphere a sin alpha) and 0 elsewhere: u(theta) = sum_n U_n P_n(cos theta) with
U_0 = (1 - cos alpha) / 2 and U_n = (P_{n-1}(cos alpha) - P_{n+1}(cos alpha)) / 2. Its far field
(outgoing e^{-jkr}, the project's e^{jwt} convention) is

  p(theta) ~ sum_n U_n j^n P_n(cos theta) / h_n'(ka),   h_n = j_n - j y_n,

normalized here on the axis: D(f, 0) = 1, so a source's level is its on-axis level 1 m out (a
scene's `spl_db`) and a directional source puts less power into the room than an omni of the
same on-axis level, as a real one does. Small against the wavelength (ka << 1) every source is
omni.

**Where it radiates from.** The series is the field about the sphere's centre; the source's
position in a scene is the cap (the cone, the mouth), a radius ahead of it on its aim. Paths
traced from the cap take `cap(f, cos)`, the far field moved there (D times e^{-jka(cos - 1)}:
the rear's sound arrives 2a / c after the front's). The wave solver (varimu.rooms.wave) puts
the sphere itself in its grid, rigid, and drives its cap: the body's own diffraction and near
field come out of the grid; `onaxis_correction(f)` turns its response (a cap of the right
volume flow, the low frequencies a monopole at the centre) into the on-axis normalization
here.

Presets (`PRESETS`; provisional: model knowledge of typical sizes): a voice (a 9 cm head, a
2 cm mouth), a 1x12 combo amp (a 25 cm sphere for its cabinet, the 15 cm cone), a 2x12 (35 cm,
22 cm), a 15-inch bass cabinet (40 cm, 19 cm).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np

from varimu.separation.room import SPEED_OF_SOUND_M_S

PRESETS_SOURCE = (
    "provisional: model knowledge (a head ~9 cm in radius with a ~2 cm mouth; combo cabinets "
    "~0.5-0.7 m across with 12-inch (15 cm) cones; a 15-inch (19 cm) bass cabinet)"
)
PRESETS: dict[str, tuple[float, float] | None] = {
    "omni": None,
    "voice": (0.09, 0.02),
    "amp_1x12": (0.25, 0.15),
    "amp_2x12": (0.35, 0.22),
    "bass_1x15": (0.40, 0.19),
}
N_FREQ = 200
N_THETA = 181


def cap_on_sphere(f_hz, cos_theta, sphere_radius_m: float, cap_radius_m: float) -> np.ndarray:
    """The far-field directivity D(f, theta), (freqs, angles) complex, D(f, 0) = 1."""
    from scipy.special import eval_legendre, spherical_jn, spherical_yn

    f = np.atleast_1d(np.asarray(f_hz, float))
    x = np.atleast_1d(np.asarray(cos_theta, float))
    a = float(sphere_radius_m)
    if not 0 < cap_radius_m <= a:
        raise ValueError("the cap's radius: in (0, the sphere's]")
    x0 = np.cos(np.arcsin(cap_radius_m / a))
    ka = 2 * np.pi * np.maximum(f, 1e-3) * a / SPEED_OF_SOUND_M_S
    n_max = int(np.ceil(ka.max() + 4 * ka.max() ** (1 / 3) + 12))
    n = np.arange(n_max + 1)
    u = np.empty(n_max + 1)
    u[0] = (1 - x0) / 2
    u[1:] = 0.5 * (eval_legendre(n[1:] - 1, x0) - eval_legendre(n[1:] + 1, x0))
    pn = np.stack([eval_legendre(k, x) for k in n])  # (n, angles)
    pn0 = eval_legendre(n, 1.0)
    out = np.empty((len(f), len(x)), complex)
    for i, z in enumerate(ka):
        # the terms past ~ka die off (h_n' grows like (n / z)^n); stop before y_n overflows
        k = int(min(n_max, np.ceil(z + 4 * z ** (1 / 3) + 12)))
        nn = n[: k + 1]
        hp = spherical_jn(nn, z, derivative=True) - 1j * spherical_yn(nn, z, derivative=True)
        c = u[: k + 1] * (1j**nn) / hp
        out[i] = (c @ pn[: k + 1]) / (c @ pn0[: k + 1])
    return out


@dataclass
class Directivity:
    """A cap on a sphere tabulated over log frequency and angle to the source's aim."""

    f_grid: np.ndarray
    theta: np.ndarray
    table: np.ndarray  # (freqs, angles) complex
    centre_offset_m: float = 0.0  # the sphere's centre behind the cap (its radius)
    cap_radius_m: float = 0.0

    def at(self, f_hz, cos_theta) -> np.ndarray:
        """D at each (frequency, direction): (len(cos), len(f)) complex, linear in angle and
        log frequency."""
        th = np.arccos(np.clip(np.atleast_1d(cos_theta), -1, 1))
        lf = np.log(np.maximum(np.atleast_1d(f_hz), self.f_grid[0]))
        lg = np.log(self.f_grid)
        fi = np.clip(np.searchsorted(lg, lf) - 1, 0, len(lg) - 2)
        fw = np.clip((lf - lg[fi]) / (lg[fi + 1] - lg[fi]), 0, 1)
        dth = self.theta[1] - self.theta[0]
        ti = np.clip((th / dth).astype(int), 0, len(self.theta) - 2)
        tw = np.clip(th / dth - ti, 0, 1)
        lo = self.table[fi] * (1 - fw)[:, None] + self.table[fi + 1] * fw[:, None]  # (f, angles)
        return (lo[:, ti] * (1 - tw) + lo[:, ti + 1] * tw).T

    def _shift(self, f_hz, cos_theta, sign: float) -> np.ndarray:
        k = 2 * np.pi * np.atleast_1d(np.asarray(f_hz, float)) / SPEED_OF_SOUND_M_S
        c = np.atleast_1d(np.asarray(cos_theta, float))
        a = self.centre_offset_m
        if sign < 0:  # to the cap: e^{-jka(cos - 1)}
            return np.exp(-1j * np.outer(c - 1, k) * a)
        return np.broadcast_to(np.exp(1j * k * a)[None, :], (len(c), len(k)))

    def cap(self, f_hz, cos_theta) -> np.ndarray:
        """D for paths traced from the cap (the source's position): (len(cos), len(f))."""
        return self.at(f_hz, cos_theta) * self._shift(f_hz, cos_theta, -1)

    def centre(self, f_hz, cos_theta) -> np.ndarray:
        """D for a source at the sphere's centre, the on-axis level the cap's."""
        return self.at(f_hz, cos_theta) * self._shift(f_hz, cos_theta, 1)

    def onaxis_correction(self, f_hz) -> np.ndarray:
        """K(f): a field computed with the physical cap whose low frequencies are a unit
        monopole at the sphere's centre, times K, has this table's normalization (on axis
        D = 1 with the cap's delay): K = S_0(f) / S(f, 0) e^{jka}, S the series' sum on axis
        and S_0 its monopole term's low-frequency limit, U_0 j (ka)^2."""
        from scipy.special import eval_legendre, spherical_jn, spherical_yn

        f = np.atleast_1d(np.asarray(f_hz, float))
        a = self.centre_offset_m
        x0 = np.cos(np.arcsin(self.cap_radius_m / a))
        ka = 2 * np.pi * np.maximum(f, 1e-3) * a / SPEED_OF_SOUND_M_S
        out = np.empty(len(f), complex)
        for i, z in enumerate(ka):
            k = int(np.ceil(z + 4 * z ** (1 / 3) + 12))
            n = np.arange(k + 1)
            u = np.empty(k + 1)
            u[0] = (1 - x0) / 2
            u[1:] = 0.5 * (eval_legendre(n[1:] - 1, x0) - eval_legendre(n[1:] + 1, x0))
            hp = spherical_jn(n, z, derivative=True) - 1j * spherical_yn(n, z, derivative=True)
            s = np.sum(u * (1j**n) / hp)
            out[i] = (u[0] * 1j * z**2) / s * np.exp(1j * z)
        return out

    def power_factor(self, f_hz) -> np.ndarray:
        """The power radiated relative to an omni of the same on-axis level, per frequency:
        the mean of |D|^2 over the sphere."""
        d = self.at(f_hz, np.cos(self.theta))  # (angles, f)
        w = np.sin(self.theta)
        return (np.abs(d) ** 2 * w[:, None]).sum(0) / w.sum()

    def first_order(self, f_hz) -> tuple[np.ndarray, np.ndarray]:
        """centre(f, cos) ~ A(f) + B(f) cos theta (least squares over the sphere): the wave
        solver's monopole and dipole weights for a source at the sphere's centre."""
        d = self.centre(f_hz, np.cos(self.theta))  # (angles, f)
        w = np.sqrt(np.sin(self.theta) + 1e-3)[:, None]
        m = np.stack([np.ones_like(self.theta), np.cos(self.theta)], 1) * w
        coef = np.linalg.pinv(m) @ (d * w)
        return coef[0], coef[1]


@cache
def directivity(sphere_radius_m: float, cap_radius_m: float) -> Directivity:
    f = np.geomspace(10.0, 48000.0, N_FREQ)
    th = np.linspace(0, np.pi, N_THETA)
    table = cap_on_sphere(f, np.cos(th), sphere_radius_m, cap_radius_m)
    return Directivity(f, th, table, float(sphere_radius_m), float(cap_radius_m))


def from_spec(spec) -> Directivity | None:
    """A scene's `directivity`: a preset's name, {sphere_radius_m, cap_radius_m}, or None /
    "omni"."""
    if spec is None:
        return None
    if isinstance(spec, str):
        if spec not in PRESETS:
            raise ValueError(f"directivity {spec!r}: one of {sorted(PRESETS)} or the sizes")
        p = PRESETS[spec]
        return None if p is None else directivity(*p)
    return directivity(float(spec["sphere_radius_m"]), float(spec["cap_radius_m"]))

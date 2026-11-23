"""The receivers' sphere and the field outside it (docs/BINAURAL_PLAN.md).

The solver records the pressure on a sphere of radius R round the body. Outside R the field
is a sum of outgoing spherical waves, so its spherical-harmonic coefficients on R give it at
every distance r >= R and direction (theta, phi):

    p(r, theta, phi) = sum_nm a_nm h_n(kr) / h_n(kR) Y_nm(theta, phi)

with h_n the outgoing spherical Hankel function (the project's e^{+j w t} convention, numpy's
forward FFT: h_n^(2) = j_n - j y_n, ~ j^(n+1) e^{-jkr} / (kr) far out). The receivers sit on a
Gauss grid (N + 1 Gauss-Legendre nodes in cos theta, 2N + 2 azimuths), on which the transform
to order N is a quadrature, exact for a field of order <= N.

Angles: theta from +z (colatitude), phi from +x toward +y (azimuth, counter-clockwise seen
from above; +x the nose, +y the left ear: the HUTUBS / SOFA convention, azimuth 90 = left).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np
from scipy.special import sph_harm_y, spherical_jn, spherical_yn


@dataclass(frozen=True)
class GaussGrid:
    order: int
    theta: np.ndarray  # (Q,)
    phi: np.ndarray  # (Q,)
    weight: np.ndarray  # (Q,), summing to 4 pi

    @property
    def n(self) -> int:
        return len(self.theta)

    def unit(self) -> np.ndarray:
        return unit_vectors(self.theta, self.phi)


@cache
def gauss_grid(order: int) -> GaussGrid:
    x, w = np.polynomial.legendre.leggauss(order + 1)
    n_phi = 2 * order + 2
    phi = 2 * np.pi * np.arange(n_phi) / n_phi
    th = np.arccos(x)
    T, P = np.meshgrid(th, phi, indexing="ij")
    W = np.repeat(w[:, None] * (2 * np.pi / n_phi), n_phi, axis=1)
    return GaussGrid(order, T.ravel(), P.ravel(), W.ravel())


def unit_vectors(theta, phi) -> np.ndarray:
    theta = np.asarray(theta, float)
    phi = np.asarray(phi, float)
    return np.stack(
        [np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)], axis=-1
    )


def sph_from_azel(az_deg, el_deg) -> tuple[np.ndarray, np.ndarray]:
    """(theta, phi) from SOFA azimuth (deg, 90 = left) and elevation (deg, 90 = up)."""
    return np.radians(90.0 - np.asarray(el_deg, float)), np.radians(np.asarray(az_deg, float))


def nm_list(order: int) -> tuple[np.ndarray, np.ndarray]:
    n = np.concatenate([np.full(2 * k + 1, k) for k in range(order + 1)])
    m = np.concatenate([np.arange(-k, k + 1) for k in range(order + 1)])
    return n, m


def ylm(order: int, theta, phi) -> np.ndarray:
    """Complex orthonormal spherical harmonics, (points, (order + 1)^2)."""
    n, m = nm_list(order)
    th = np.asarray(theta, float).ravel()[:, None]
    ph = np.asarray(phi, float).ravel()[:, None]
    return sph_harm_y(n[None, :], m[None, :], th, ph)


def hankel2(n: np.ndarray, x: float) -> np.ndarray:
    return spherical_jn(n, x) - 1j * spherical_yn(n, x)


def order_for(k: float, radius_m: float, margin: int = 8) -> int:
    return int(np.ceil(k * radius_m)) + margin


@dataclass
class ShField:
    """A field's SH coefficients per frequency on a sphere of `radius_m`: `coeffs[f]` holds
    orders 0..order_f[f] (padded with zeros to the largest order)."""

    f_hz: np.ndarray
    radius_m: float
    order: int
    coeffs: np.ndarray  # (F, (order + 1)^2) complex
    c_m_s: float

    def at(self, theta, phi, distance_m: float | None = None) -> np.ndarray:
        """The field normalized by a point source's free field from the centre, at
        directions (theta, phi): (points, F). distance_m None: the far field
        (r e^{jkr} p as r -> infinity); else p(r) r e^{jkr} at r = distance_m >= radius."""
        Y = ylm(self.order, theta, phi)  # (P, Nc)
        return Y @ (self.coeffs * self.radial_matrix(distance_m)).T

    def radial_matrix(self, distance_m: float | None) -> np.ndarray:
        """(F, Nc): `radial` per frequency, the static limit at 0 Hz (only the monopole
        survives r p as r grows: p_0 ~ R / r). Cached per distance."""
        cache = self.__dict__.setdefault("_radial", {})
        if distance_m in cache:
            return cache[distance_m]
        n, _ = nm_list(self.order)
        nn = np.arange(self.order + 1)
        k = 2 * np.pi * np.asarray(self.f_hz, float) / self.c_m_s
        kk = np.where(k > 0, k, 1.0)[:, None]
        hR = hankel2(nn[None, :], kk * self.radius_m)
        if distance_m is None:
            fac = (1j) ** (nn[None, :] + 1) / (kk * hR)
        else:
            r = distance_m
            fac = hankel2(nn[None, :], kk * r) / hR * r * np.exp(1j * kk * r)
        fac[k == 0] = 0.0
        fac[k == 0, 0] = self.radius_m
        out = fac[:, n]
        cache[distance_m] = out
        return out


def radial(n: np.ndarray, k: float, radius_m: float, distance_m: float | None) -> np.ndarray:
    """The factor taking a coefficient on R to the normalized field at r (or far)."""
    nn = np.unique(n)
    hR = hankel2(nn, k * radius_m)
    if distance_m is None:
        fac = (1j) ** (nn + 1) / (k * hR)
    else:
        r = distance_m
        fac = hankel2(nn, k * r) / hR * r * np.exp(1j * k * r)
    lut = dict(zip(nn.tolist(), fac, strict=True))
    return np.array([lut[v] for v in n.tolist()])


def transform(
    grid: GaussGrid,
    p: np.ndarray,
    f_hz: np.ndarray,
    radius_m: float,
    c_m_s: float,
    max_order: int | None = None,
) -> ShField:
    """SH coefficients of pressures p (F, Q) on the grid, each frequency to its own order
    (kR + 8, at most the grid's). Separable: an FFT round each ring of latitude, then the
    Gauss-Legendre sum per (n, m)."""
    top = grid.order if max_order is None else min(max_order, grid.order)
    n_th = grid.order + 1
    n_ph = 2 * grid.order + 2
    th = grid.theta[::n_ph]
    w_th = grid.weight[::n_ph]  # Gauss weight x 2 pi / n_ph
    n, m = nm_list(top)
    leg = np.real(sph_harm_y(n[None, :], m[None, :], th[:, None], 0.0))  # (n_th, Nc)
    lw = leg * w_th[:, None]
    col = m % n_ph
    pr = np.asarray(p).reshape(len(f_hz), n_th, n_ph)
    coeffs = np.zeros((len(f_hz), len(n)), complex)
    for lo in range(0, len(f_hz), 16):
        G = np.fft.fft(pr[lo : lo + 16], axis=2)  # sum_j p e^{-i m phi_j}
        coeffs[lo : lo + 16] = np.einsum("fic,ic->fc", G[:, :, col], lw)
    for i, f in enumerate(f_hz):
        k = 2 * np.pi * f / c_m_s
        coeffs[i, n > min(top, order_for(k, radius_m))] = 0.0
    return ShField(np.asarray(f_hz, float), radius_m, top, coeffs, c_m_s)

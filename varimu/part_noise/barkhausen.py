"""Barkhausen noise: domain walls in a magnetic core jump between pinning sites in avalanches,
so the magnetization changes in bursts and a winding's EMF crackles around its smooth value.

**ABBM** (Alessandro, Beatrice, Bertotti, Montorsi, J. Appl. Phys. 68, 2901 and 2908, 1990;
review: G. Durin and S. Zapperi, "The Barkhausen effect", arXiv cond-mat/0404512): a wall in a
Brownian pinning landscape under a slowly rising field. Its velocity v (the rate dM/dt) is a
square-root diffusion, dv = kappa (theta - v) dt + sigma sqrt(v) dW, a Cox-Ingersoll-Ross
process: theta the mean rate the drive imposes, 1 / kappa the demagnetizing relaxation time (it
cuts the avalanches off), sigma the pinning's strength. Its dimensionless drive c = 2 kappa
theta / sigma^2 sets the character: the stationary std / mean of v is 1 / sqrt(c), so a slow
sweep (c < 1) crackles in isolated avalanches and a fast one (c >> 1) is nearly smooth.
Independent walls add into one such process with their thetas summed (squared Bessel processes
are additive), so a core is one process.

The transition over a step is exact (a scaled noncentral chi-square), so any step is accurate.
Here theta follows a smooth magnetization rate |dM/dt| (the material's curve under the drive),
held over each sample, and the sign follows the drive's direction.
"""

from __future__ import annotations

import numpy as np

ABBM_SOURCE = (
    "ABBM model, web: https://arxiv.org/abs/cond-mat/0404512 (Durin & Zapperi, The Barkhausen "
    "effect: the velocity's square-root diffusion; avalanches power-law distributed in the "
    "intermittent regime c < 1, a Lorentzian-like spectrum cut off by the demagnetizing factor)"
)
PARAMS_SOURCE = (
    "provisional: model knowledge (kappa: avalanche durations up to ~1 ms in soft FeSi / NiFe "
    "cores, a cutoff near 1 kHz; c_per_ms: a sweep through the loop in ~1 s crackles (c ~0.1-1, "
    "the review's quasi-static experiments), so c per unit rate (saturation magnetizations per "
    "second) ~0.25 s; nothing fitted)"
)


def cir_path(theta, kappa_per_s: float, c_per_rate_s: float, rate_hz: float, rng):
    """v at each sample for mean rates theta (>= 0, per sample) with c = c_per_rate_s theta.

    With c proportional to theta, sigma^2 = 2 kappa / c_per_rate_s is a constant of the
    material. Starts at theta[0]."""
    theta = np.maximum(np.asarray(theta, dtype=float), 0.0)
    sigma2 = 2.0 * kappa_per_s / c_per_rate_s
    dt = 1.0 / rate_hz
    e = np.exp(-kappa_per_s * dt)
    scale = sigma2 * (1.0 - e) / (4.0 * kappa_per_s)
    df = np.maximum(4.0 * kappa_per_s * theta / sigma2, 1e-12)
    out = np.empty(theta.size)
    v = theta[0]
    # Noncentral chi-square as a Poisson mixture of chi-squares (the same law, vectorizable
    # draws): Y = chi2(df + 2 N), N ~ Poisson(nonc / 2).
    for k in range(theta.size):
        nonc = v * e / scale
        m = rng.poisson(0.5 * nonc) if nonc > 0.0 else 0
        v = scale * rng.chisquare(df[k] + 2.0 * m)
        out[k] = v
    return out


def tanh_loop_rate(h, dh_dt, h_coercive: float, h_scale: float) -> np.ndarray:
    """|dM/dt| (saturation magnetizations per second) on a simple loop: M = tanh((H -+ Hc) /
    Hs), the branch picked by the drive's direction. A stand-in for the material's curve."""
    h = np.asarray(h, float)
    up = np.asarray(dh_dt, float) >= 0.0
    shifted = np.where(up, h - h_coercive, h + h_coercive)
    dm_dh = (1.0 - np.tanh(shifted / h_scale) ** 2) / h_scale
    return np.abs(dm_dh * dh_dt)


def mean_path(theta, kappa_per_s: float, rate_hz: float) -> np.ndarray:
    """E[v] at each sample: dm/dt = kappa (theta - m), exact for theta held over a sample, the
    same start as `cir_path`. Under a fast drive it lags theta by ~1 / kappa (a periodic,
    deterministic part, not Barkhausen noise)."""
    theta = np.maximum(np.asarray(theta, dtype=float), 0.0)
    e = np.exp(-kappa_per_s / rate_hz)
    from scipy.signal import lfilter

    m, _ = lfilter([1.0 - e], [1.0, -e], theta, zi=[e * theta[0]])
    return m


def crackle(h, rate_hz: float, kappa_per_s: float, c_per_rate_s: float, rng, hc=0.3, hs=0.25):
    """(mean rate, Barkhausen rate) for a field waveform h (units of the loop's field): the
    expected dM/dt and the avalanche process around it, both signed; their difference is the
    crackle alone."""
    h = np.asarray(h, float)
    dh_dt = np.gradient(h) * rate_hz
    theta = tanh_loop_rate(h, dh_dt, hc, hs)
    sign = np.where(dh_dt >= 0.0, 1.0, -1.0)
    v = cir_path(theta, kappa_per_s, c_per_rate_s, rate_hz, rng)
    return sign * mean_path(theta, kappa_per_s, rate_hz), sign * v

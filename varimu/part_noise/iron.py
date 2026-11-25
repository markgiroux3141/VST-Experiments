"""Barkhausen avalanches in a circuit's iron (docs/PART_NOISE_PLAN.md, the tube synth's
spike), put back into the coupled simulation at the core node.

**What moves.** Only irreversible magnetization jumps (reversible wall bowing jumps nothing).
In the Jiles-Atherton model (`varimu.devices.core`), M = Mrev + Mirr with Mrev = c (Man - Mirr),
so Mirr = (M - c Man) / (1 - c): replaying a run's B path through the core's own model gives
Mirr per sample, and the irreversible rate theta = |dMirr/dt| (for the plots).

**The landscape (the default).** A core's pinning is fixed: its walls jump at the same places
every time they pass them. So the avalanches are a function of position along Mirr, a seeded
"barcode" of sites: Poisson along Mirr, each with a size drawn from a power law of exponent
3/2 (ABBM's, Durin & Zapperi's review: web: https://arxiv.org/abs/cond-mat/0404512) between
`S_MIN` and the largest jump s_max, the density set so the jumps add up to the irreversible
change (all of it goes by jumps). The deviation from the smooth model is the staircase minus
the ramp, dM = S(Mirr) - Mirr: a minor loop (each audio cycle) retraces the same jumps (return-
point memory, a steady grit that changes as the loop moves), a sweep (an envelope, an LFO on
the cutoff) scans new ones (crackle). STRESS (the pinning) sets s_max: larger, sparser jumps.
Each jump takes ~1 / AVALANCHE_HZ (a one-pole; the core's eddy capacitance in the circuit damps
it further); dM is high-passed (the demagnetizing field keeps the mean on the loop).

**No memory (`abbm`, the alternative).** ABBM in time (`varimu.part_noise.barkhausen`): new
random avalanches whatever the path, as the bench's files.

**Into the circuit.** An avalanche is a jump of M at a fixed field: B = mu0 (H + M + dM), so the
core device's port current path H(B) becomes ~ path H(B) - path (dH/dB) mu0 dM: the same as a
current path (dH/dB) mu0 Ms dM (dM in Ms) fed into the core node. Every winding on the core sees
the flux jump, the eddy capacitance damps it and a gap dilutes it, as they would a real one.
Two passes, as the excess noise (`varimu.part_noise.aging`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal

from varimu.devices.core import MU0, TESLA_PER_V, CoreState, MagneticCore, langevin
from varimu.part_noise import barkhausen

S_MIN = 1e-9  # the smallest jump, in Ms (smaller ones are inaudible and only cost memory)
S_MAX_REALISTIC = 1e-6  # the largest at STRESS 1, in Ms
TAU = 1.5
AVALANCHE_HZ = 2000.0
HIGHPASS_HZ = 5.0
ABBM_KAPPA_PER_S = 2 * math.pi * 1000.0
ABBM_C_PER_RATE_S = 100.0  # at STRESS 1
SOURCE = (
    "provisional: model knowledge (a macroscopic soft core's Barkhausen jumps: up to ~1e-6 of "
    "its saturation flux at STRESS 1 (sub-uT in a 1 cm2 mumetall core), down to ~1e-9 here; "
    "avalanche durations ~0.1-1 ms; the size law's exponent 3/2 is ABBM's, web: "
    "https://arxiv.org/abs/cond-mat/0404512; nothing fitted to a measured core)"
)


@dataclass
class Replay:
    m_irr: np.ndarray  # irreversible magnetization, in Ms
    theta: np.ndarray  # |dMirr/dt|, Ms per second
    sign: np.ndarray  # direction of dMirr
    dh_db: np.ndarray  # A/m per T, the core's differential slope on its path


def replay(core: MagneticCore, b_t: np.ndarray, rate_hz: float) -> Replay:
    """Replay B (T, per sample) through the core's model, from its initial curve at the first
    point (a demagnetized core brought to the operating point, as the engine's DC point)."""
    n = b_t.size
    m_irr = np.zeros(n)
    dh_db = np.zeros(n)
    h, _ = core.h_of_b(float(b_t[0]), CoreState())
    state = CoreState(float(b_t[0]), h, 1.0)
    ms, a, c, alpha = core.ms_a_per_m, core.a_a_per_m, core.c, core.alpha
    for i in range(n):
        b = float(b_t[i])
        h, slope = core.h_of_b(b, state)
        delta = state.delta if b == state.b else (1.0 if b > state.b else -1.0)
        state = CoreState(b, h, delta)
        m = b / MU0 - h
        man = ms * langevin((h + alpha * m) / a)
        m_irr[i] = (m - c * man) / (1 - c) / ms
        dh_db[i] = slope
    d = np.diff(m_irr, prepend=m_irr[0]) * rate_hz
    return Replay(m_irr, np.abs(d), np.where(d >= 0, 1.0, -1.0), dh_db)


def landscape(lo: float, hi: float, s_max: float, rng) -> tuple[np.ndarray, np.ndarray]:
    """Sites (sorted positions in Ms) and their jump sizes over [lo, hi]."""
    # Power law p(s) ~ s^-TAU on [S_MIN, s_max]: inverse CDF.
    e = 1.0 - TAU
    lo_e, hi_e = S_MIN**e, s_max**e
    mean = (S_MIN ** (2 - TAU) - s_max ** (2 - TAU)) / (TAU - 2) / ((hi_e - lo_e) / e)
    span = hi - lo
    count = rng.poisson(span / mean)
    pos = np.sort(rng.uniform(lo, hi, count))
    sizes = (lo_e + rng.random(count) * (hi_e - lo_e)) ** (1 / e)
    sizes *= span / max(sizes.sum(), 1e-300)  # all of the irreversible change goes by jumps
    return pos, sizes


def avalanches(r: Replay, rate_hz: float, stress: float, rng, model: str = "landscape"):
    """The magnetization deviation dM(t), in Ms."""
    if model == "landscape":
        margin = 1e-3
        lo, hi = float(r.m_irr.min()) - margin, float(r.m_irr.max()) + margin
        pos, sizes = landscape(lo, hi, S_MAX_REALISTIC * stress, rng)
        stair = np.concatenate([[0.0], np.cumsum(sizes)])
        dm = stair[np.searchsorted(pos, r.m_irr)] - (r.m_irr - lo)
        # Each jump takes time (the wall's motion, eddy-damped).
        sos = signal.butter(1, AVALANCHE_HZ, "lowpass", fs=rate_hz, output="sos")
        dm = signal.sosfilt(sos, dm - dm[0])
    elif model == "abbm":
        v = barkhausen.cir_path(r.theta, ABBM_KAPPA_PER_S, ABBM_C_PER_RATE_S / stress, rate_hz, rng)
        mean = barkhausen.mean_path(r.theta, ABBM_KAPPA_PER_S, rate_hz)
        dm = np.cumsum(r.sign * (v - mean)) / rate_hz
    else:
        raise ValueError(model)
    sos = signal.butter(1, HIGHPASS_HZ, "highpass", fs=rate_hz, output="sos")
    return signal.sosfilt(sos, dm)


def injection_current(core: MagneticCore, dm_ms: np.ndarray, dh_db: np.ndarray) -> np.ndarray:
    """The current (A) into the core node equivalent to a jump dM (in Ms) at a fixed field."""
    return core.path_m * dh_db * MU0 * dm_ms * core.ms_a_per_m


def core_b(vectors: dict, node: str) -> np.ndarray:
    """A core node's flux density (T) from a run's probes."""
    return vectors[f"v({node})"] * TESLA_PER_V

"""Wow and flutter of one tape record pass, as a time-varying delay.

A track printed on tape carries the speed errors of the pass it was recorded on. Two
overdubs recorded on different passes carry independent errors, so their partials don't
move together: the ear's "common fate" cue (SEPARATION_PLAN.md). This is a stand-in for
TAPE_PLAN.md's transport (TM3: the capstan's motor, the rollers, the reels and scrape
flutter as physics); the components below are its sources of speed error, sized by
assumption, and the total is scaled to the Ampex 351's specification.

The tape's speed while recording is v(t) = v0 (1 + s(t)). Played back at v0, the signal
comes out as x(t - d(t)), d(t) = integral of s: a pitch deviation of -s(t) (a pass running
fast records the signal stretched, so it plays back flat). The total is scaled to the
specification exactly.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

TOTAL_RMS = 0.0011
TOTAL_RMS_SOURCE = (
    "web: Ampex 351 specification, wow and flutter 0.11% rms at 15 ips "
    "(docs/TAPE_PLAN.md's sources)"
)


@dataclass(frozen=True)
class Component:
    """One source of speed error: a rotation (a sine and its 2nd harmonic at a random
    phase, its rate wandering slightly) or a random narrow band (`periodic` False)."""

    name: str
    center_hz: float
    share: float  # of the total variance
    periodic: bool
    rel_bandwidth: float  # random bands: bandwidth / center; rotations: rate wander
    source: str


# The Ampex 351 at 15 ips. Shares of the variance are assumed; TM3 replaces all of it.
COMPONENTS: tuple[Component, ...] = (
    Component(
        "capstan",
        30.0,
        0.30,
        True,
        0.002,
        (
            "provisional: model knowledge (a direct-drive capstan on a 1800 rpm synchronous motor: "
            "once per turn, eccentricity)"
        ),
    ),
    Component(
        "pinch_roller",
        4.8,
        0.20,
        True,
        0.004,
        "provisional: model knowledge (a ~1 in pinch roller at 15 ips turns ~4.8 times a second)",
    ),
    Component(
        "reel",
        0.7,
        0.15,
        True,
        0.02,
        (
            "provisional: model knowledge (a 10.5 in reel at 15 ips turns 0.45-1.06 times a "
            "second, hub to full)"
        ),
    ),
    Component(
        "motor_hunting",
        8.0,
        0.15,
        False,
        0.5,
        (
            "provisional: model knowledge (a synchronous motor hunting around its locked speed, "
            "a few Hz)"
        ),
    ),
    Component(
        "random_lf",
        3.0,
        0.15,
        False,
        2.0,
        "provisional: model knowledge (tension and friction wandering, broadband below ~10 Hz)",
    ),
    Component(
        "scrape",
        2500.0,
        0.05,
        False,
        0.8,
        (
            "provisional: model knowledge (scrape flutter: the tape span between guides vibrating "
            "under stick-slip friction, 1-5 kHz)"
        ),
    ),
)


def _rng(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(name.encode())])


def _band_noise(
    rng: np.random.Generator, n: int, fs: float, center_hz: float, rel_bw: float
) -> np.ndarray:
    """Gaussian noise with a Gaussian band around `center_hz` (on log frequency), unit rms."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / fs)
    with np.errstate(divide="ignore"):
        octaves = np.log2(np.where(f > 0, f, np.nan) / center_hz)
    width = np.log2(1.0 + rel_bw)
    spec *= np.nan_to_num(np.exp(-0.5 * (octaves / width) ** 2))
    y = np.fft.irfft(spec, n)
    return y / np.sqrt(np.mean(y**2))


def speed_error(n: int, fs: float, seed: int, total_rms: float = TOTAL_RMS) -> np.ndarray:
    """s(t) for one record pass: the components at their shares of `total_rms`."""
    s = np.zeros(n)
    for c in COMPONENTS:
        rng = _rng(seed, c.name)
        if c.periodic:
            # The rate wanders a little (load, mains): integrate a slowly varying rate.
            wander = _band_noise(rng, n, fs, 0.2, 1.0) * c.rel_bandwidth
            phase = 2 * np.pi * np.cumsum(c.center_hz * (1 + wander)) / fs + rng.uniform(
                0, 2 * np.pi
            )
            y = np.sin(phase) + 0.3 * np.sin(2 * phase + rng.uniform(0, 2 * np.pi))
            y /= np.sqrt(np.mean(y**2))
        else:
            y = _band_noise(rng, n, fs, c.center_hz, c.rel_bandwidth)
        s += y * np.sqrt(c.share)
    return s * total_rms / np.std(s)


def read_at(x: np.ndarray, pos: np.ndarray, taps: int = 32, beta: float = 8.0) -> np.ndarray:
    """`x` read at fractional sample positions `pos` (Kaiser-windowed sinc, `taps` taps;
    outside `x` reads 0)."""
    x = np.asarray(x, float)
    out = np.empty(len(pos))
    half = taps // 2
    k = np.arange(-half + 1, half + 1)
    xp = np.concatenate([np.zeros(taps), x, np.zeros(taps)])
    for a in range(0, len(pos), 1 << 15):
        p = pos[a : a + (1 << 15)]
        i0 = np.floor(p).astype(np.int64)
        frac = p - i0
        idx = i0[:, None] + k[None, :]
        u = k[None, :] - frac[:, None]
        w = np.sinc(u) * _kaiser(u, half, beta)
        idx = np.clip(idx + taps, 0, len(xp) - 1)
        out[a : a + len(p)] = np.sum(xp[idx] * w, axis=1)
    return out


def _kaiser(u: np.ndarray, half: int, beta: float) -> np.ndarray:
    r = np.clip(u / half, -1.0, 1.0)
    return np.i0(beta * np.sqrt(1 - r**2)) / np.i0(beta)


def apply(x: np.ndarray, fs: float, seed: int, total_rms: float = TOTAL_RMS) -> np.ndarray:
    """`x` as recorded on a pass with seed `seed` and played back at the nominal speed.
    The delay's mean is removed, so the track stays in time with the others."""
    s = speed_error(len(x), fs, seed, total_rms)
    d = np.cumsum(s) / fs
    d -= d.mean()
    return read_at(x, np.arange(len(x)) - d * fs)

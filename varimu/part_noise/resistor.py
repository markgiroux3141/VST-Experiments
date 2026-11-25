"""A resistor's noise: Johnson noise (every resistor of a value alike) and excess, or current,
noise (the material's: carbon composition worst, metal film near none).

**Excess noise.** The resistance fluctuates, dR/R = delta(t) with one-sided density K / f, so a
current I(t) through it gives a voltage I(t) R delta(t): with DC, a 1/f hiss proportional to the
DC; with a signal current, the same fluctuation riding each tone (1/f skirts around it), silent
when no current flows. The noise index (IEC 60195, MIL-STD-202 Method 308) is the rms noise in
uV per volt of DC across the part, in one decade: integral over a decade of K / f is K ln 10, so
K = (10^(NI/20) 1e-6)^2 / ln 10. delta is B5's unit flicker (`varimu.devices.noise`, density
1 / f, flat below 1 mHz) times sqrt(K): the generator PB2 will put into the engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from varimu.devices import noise

NOISE_INDEX_SOURCE = (
    "provisional: model knowledge (the ranges usually quoted from Motchenbacher & Connelly, "
    "Low-Noise Electronic System Design, Wiley 1993, resistor excess noise: carbon composition "
    "0.1-3 uV/V per decade (-20..+10 dB), carbon film 0.05-0.3, metal film 0.02-0.2, wirewound "
    "0.01-0.2; to be checked against the book. The definition: IEC 60195 / MIL-STD-202 Method "
    "308, web: https://epci.eu/resistors-noise-and-corrosion/ (rms uV per V of DC per decade, "
    "measured around 1 kHz; grows with the resistance value; carbon composition and thick film "
    "the worst, metal film and wirewound negligible))"
)
AGED_SOURCE = (
    "provisional: model knowledge (carbon composition's noise rises with moisture, overload and "
    "drift: the aged part at the top of the published range, +10 dB; no quantified aging law "
    "found yet, EPCI names corrosion at the contact spots as the mechanism)"
)


@dataclass(frozen=True)
class Material:
    name: str
    noise_index_db: float
    source: str


CARBON_COMP = Material("carbon composition", 0.0, NOISE_INDEX_SOURCE)
CARBON_COMP_AGED = Material("carbon composition, aged", 10.0, AGED_SOURCE)
METAL_FILM = Material("metal film", -25.0, NOISE_INDEX_SOURCE)


def excess_k(noise_index_db: float) -> float:
    """K of dR/R's density K / f from a noise index in dB (re 1 uV/V per decade)."""
    return (10.0 ** (noise_index_db / 20.0) * 1e-6) ** 2 / math.log(10.0)


def johnson_v(r_ohm: float, temperature_k: float, n: int, rate_hz: float, seed: int, name: str):
    """A resistor's open-circuit Johnson noise voltage, density 4 k T R (V^2/Hz), n samples."""
    sigma = noise.white_sigma(4.0 * noise.K_B * temperature_k * r_ohm, rate_hz)
    return sigma * noise.normals(noise.key(seed, name, noise.STREAM_MAIN), 0, n)


def fluctuation(noise_index_db: float, n: int, rate_hz: float, seed: int, name: str):
    """dR / R: unit flicker (B5's) scaled to the noise index."""
    unit = noise.unit_stream(seed, name, noise.STREAM_FLICKER, True, rate_hz, n)
    return math.sqrt(excess_k(noise_index_db)) * unit


def excess_v(current_a, r_ohm: float, noise_index_db: float, rate_hz: float, seed: int, name: str):
    """The excess noise voltage I(t) R dR/R(t) for a current waveform (or a constant)."""
    i = np.asarray(current_a, dtype=float)
    n = i.size if i.ndim else None
    if n is None:
        raise ValueError("current_a must be a waveform; use np.full(n, I) for DC")
    return i * r_ohm * fluctuation(noise_index_db, n, rate_hz, seed, name)

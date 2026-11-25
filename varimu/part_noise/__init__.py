"""Parts heard up close (docs/PART_NOISE_PLAN.md): the noise mechanisms of single components,
their aged and exaggerated versions, as offline Python references.

PB0, the bench: each mechanism alone, as a voltage at the part, with every value's source.
- `resistor`: Johnson noise and excess (current) noise from a noise index;
- `popcorn`: burst noise as superposed random telegraph signals, exact per sample;
- `barkhausen`: ABBM's domain-wall avalanches, the square-root diffusion simulated exactly;
- `contact`: a pot's wiper on a worn track into a grid's capacitance.

Outside the render cache key (not under varimu/{sim,circuit,devices}). Randomness: B5's Philox
streams (`varimu.devices.noise`) where the engine will use them, else
`np.random.default_rng([seed, crc32(name)])` (CLAUDE.md, Reproducibility).
"""

from __future__ import annotations

import zlib

import numpy as np


def rng_for(seed: int, name: str) -> np.random.Generator:
    """The seeded generator of one item: adding an item moves no other."""
    return np.random.default_rng([seed, zlib.crc32(name.encode())])

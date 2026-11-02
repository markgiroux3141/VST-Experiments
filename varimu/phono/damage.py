"""What happens to a cylinder after it is cut (docs/PHONO_PLAN.md §1 "The surface", G6):
dust in the groove, mould's pitting, cracks. Each is geometry added to the groove along
arc length, so the click, the crackle and the tick come out of the player (the tip's
dilation, the Hertz contact, the stylus thrown off and landing, the diaphragm and the horn
ringing), not from a noise sample. Every draw is seeded per kind:
`default_rng([seed, crc32(kind)])`.

- **Dust**: hard particles lying in the groove, a Poisson process along it with diameters
  from a power law between `dust_min_m` and `dust_max_m` (many small, few large), each a
  sphere resting on the groove's bottom and partly pressed into the wax (`dust_embed`: the
  fraction of its diameter below the bottom). The tip rides over it: a 10 um grain under a
  190 um tip is a smooth bump ~0.12 mm long, a fraction of a millisecond at 0.47 m/s.
- **Mould**: colonies along the groove (Poisson), each `mould_length_m` long, pitted
  inside (pits Poisson at `mould_pits_per_m`, depths and widths uniform in their ranges),
  where the growth ate into the metallic soap. A pit narrower than the tip only lets it
  drop w^2 / 8R: grit rather than clicks.
- **Cracks**: a crack across the cylinder (along its axis) meets the groove once a turn,
  every circumference of arc length: a gap `crack_gap_m` wide and a step `crack_step_m`
  between its edges (the cylinder sprung open), the radius returning linearly around the
  turn. A tick at the rotation rate (2.67 Hz at 160 rpm).
"""

from __future__ import annotations

import zlib

import numpy as np

from varimu.phono.groove import Groove


def _rng(seed: int, kind: str) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(kind.encode())])


def _power_law(rng: np.random.Generator, n: int, lo: float, hi: float, exponent: float):
    """n draws with density ~ d^-exponent on [lo, hi] (inverse CDF)."""
    a = 1.0 - exponent
    u = rng.uniform(size=n)
    return (lo**a + u * (hi**a - lo**a)) ** (1.0 / a)


def dust(g: Groove, d: dict, seed: int) -> int:
    """Lays dust in the groove (in place). Returns the number of grains."""
    rng = _rng(seed, "dust")
    n = rng.poisson(d["dust_per_m"] * g.length_m)
    if n == 0:
        return 0
    pos = rng.uniform(0, g.length_m, n)
    dia = _power_law(rng, n, d["dust_min_m"], d["dust_max_m"], d["dust_exponent"])
    for s0, di in zip(pos, dia, strict=True):
        r = di / 2
        i0, i1 = int((s0 - r) / g.ds_m), int((s0 + r) / g.ds_m) + 1
        i0, i1 = max(i0, 0), min(i1, len(g.h_m))
        if i1 <= i0:
            continue
        u = np.arange(i0, i1) * g.ds_m - s0
        cap = np.sqrt(np.maximum(r * r - u * u, 0.0))
        base = g.h_m[int(np.clip(s0 / g.ds_m, 0, len(g.h_m) - 1))]
        top = base - d["dust_embed"] * di + r + cap  # its centre above the pressed bottom
        np.maximum(g.h_m[i0:i1], np.where(cap > 0, top, -np.inf), out=g.h_m[i0:i1])
    return int(n)


def mould(g: Groove, d: dict, seed: int) -> int:
    """Pits the groove where mould grew (in place). Returns the number of pits."""
    rng = _rng(seed, "mould")
    colonies = rng.poisson(d["mould_colonies_per_m"] * g.length_m)
    total = 0
    for _ in range(colonies):
        start = rng.uniform(0, g.length_m)
        length = d["mould_length_m"]
        k = rng.poisson(d["mould_pits_per_m"] * length)
        pos = start + rng.uniform(0, length, k)
        depth = rng.uniform(*sorted((d["mould_depth_min_m"], d["mould_depth_max_m"])), k)
        width = rng.uniform(*sorted((d["mould_width_min_m"], d["mould_width_max_m"])), k)
        for s0, dep, w in zip(pos, depth, width, strict=True):
            i0, i1 = int((s0 - w / 2) / g.ds_m), int((s0 + w / 2) / g.ds_m) + 1
            i0, i1 = max(i0, 0), min(i1, len(g.h_m))
            if i1 <= i0:
                continue
            u = (np.arange(i0, i1) * g.ds_m - s0) / (w / 2)
            g.h_m[i0:i1] -= dep * np.maximum(1.0 - u * u, 0.0)
        total += k
    return total


def cracks(g: Groove, d: dict, seed: int, circumference_m: float) -> int:
    """Cracks across the cylinder (in place): a gap and a step once per turn each."""
    rng = _rng(seed, "cracks")
    count = int(d["cracks"])
    s = g.s_m()
    for _ in range(count):
        offset = rng.uniform(0, circumference_m)
        frac = ((s - offset) % circumference_m) / circumference_m  # 0 just past the crack
        g.h_m += d["crack_step_m"] * (frac - 0.5)  # sprung open: a step back at the crack
        half = int(d["crack_gap_m"] / 2 / g.ds_m)
        for c in np.arange(offset, g.length_m, circumference_m):
            i = int(c / g.ds_m)
            g.h_m[max(i - half, 0) : i + half + 1] -= d["crack_gap_depth_m"]
    return count


def age(g: Groove, d: dict, seed: int, circumference_m: float) -> dict:
    """Everything above, in place. Returns the counts."""
    return {
        "dust": dust(g, d, seed),
        "mould_pits": mould(g, d, seed),
        "cracks": cracks(g, d, seed, circumference_m),
    }

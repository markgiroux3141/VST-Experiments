"""The interacting-particle bench (docs/TAPE_PARTICLES.md, "The bench"): a periodic box of
Stoner-Wohlfarth needles with explicit dipolar interactions, all driven by one applied
field history, switching by kinetic Monte Carlo. This module is the Python reference
(small boxes); `crates/tapeparticles` runs the same algorithm in f64 on the CPU and f32 on
the GPU.

**The particles** are needles (length l, width l / aspect; volume pi/4 w^2 l), centres
uniform in a cube of side L (periodic), easy axes along the needles. Their volume fraction
is the coating's packing. Needles may overlap (random placement at 35% packing can't avoid
it); the softening below keeps those pairs finite.

**The interactions.** A particle's moment mu = Ms_p V m (m its unit moment, `sw`) is split
into the part along its axis, carried as two magnetic charges +-(mu . n) / l at its ends
(the needle's own far and near field: a uniformly magnetized needle is its end charges),
and the part across it as a point dipole at its centre. The field on a particle is averaged
over `target_points` points along its length (a macrospin's energy is its moment against
the field averaged over its volume) and is
the sum over every other particle's charges and dipole at their minimum images in the
periodic box, each softened over `soften_m` (r^2 -> r^2 + a^2: the charge's spread over
the end face), plus the field of the magnetization outside the cube: for a sample that is
long along the tape and thin in depth (the B-H meter's strip, and a volume inside the
coating whose long-wavelength demagnetization the medium computes separately) that is the
cavity's M/3 minus the sample's demagnetization (0, 1, 0) . M (`mean_field`).

The interaction is dynamic: every step's field follows every particle's state. Variants
for the bench's question: `interactions="none"` (only the applied field) and "frozen" (the
field each particle saw in the erased state, held: a static interaction field per
particle, the Preisach picture).

**Switching** is the kinetic Monte Carlo of `sw` (states +-1, the two-state chain over each
step sampled with a counter-based uniform), from the AC-erased state (random signs).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from varimu.tape_particles import ensemble as ens
from varimu.tape_particles import sw

OE = ens.OE
FOUR_PI = 4.0 * math.pi


@dataclass(frozen=True)
class BenchSpec:
    ms_p_a_m: float = 3.6e5
    packing: float = 0.35
    length_median_m: float = 0.5e-6
    sigma_ln_length: float = 0.3
    aspect: float = 5.0
    hk_median_a_m: float = 1000.0 * OE
    sigma_ln_hk: float = 0.3
    kv_kt_median: float = 150.0
    kappa: float = 0.0
    f0_hz: float = 1e9
    temp_k: float = 293.0
    soften_m: float = 0.05e-6
    sample_demag: tuple = (0.0, 1.0, 0.0)
    interactions: str = "dynamic"  # "dynamic" | "frozen" | "none"
    #: a scale on the interaction field (1: the physics; a study knob only)
    interaction_scale: float = 1.0
    #: needles relaxed apart (no overlaps: `pack`); False: centres uniform, overlapping
    packed: bool = True
    #: the closest two needles may come, in units of their mean width (`pack.relax`)
    contact: float = 0.8
    #: points along a needle its interaction field is averaged over
    target_points: int = 5
    sources: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def kt_j(self) -> float:
        return sw.KB * self.temp_k

    def with_(self, **kw) -> BenchSpec:
        return replace(self, **kw)


#: Every value's source (Hard rules); the research is VST-chirp's
#: docs/TAPE_PARTICLE_RESEARCH.md (2026-11-12), cited by section.
SOURCES = {
    "ms_p_a_m": "TAPE_PARTICLE_RESEARCH.md 1.2: 360-389 kA/m (74 emu/g x 4.86 g/cm^3 = 360, the "
    "figure quoted for tape oxide)",
    "packing": "TAPE_PARTICLE_RESEARCH.md 1.1 / 1.5 [derived]: p S = 0.18-0.20 from Eilers' 900 G, "
    "p = 0.28-0.40; 0.35 as SCOTCH111@3 (provisional)",
    "length_median_m": "TAPE_PARTICLE_RESEARCH.md 1.3: Westmijze 1956's micrograph, gamma-Fe2O3 "
    "tape particles 'about 0.5 x 0.1 u'",
    "aspect": "TAPE_PARTICLE_RESEARCH.md 1.3: Westmijze's ~5:1",
    "sigma_ln_length": "TAPE_PARTICLE_RESEARCH.md 1.3: provisional: model knowledge, 0.3-0.5",
    "hk_median_a_m": "fit: Sound Talk No. 20 + Eilers' Hc (varimu.tape_particles.bench_fit); an "
    "effective field (the ideal SW field is ~5x harder: TAPE_PARTICLE_RESEARCH.md 1.4)",
    "sigma_ln_hk": "fit: Sound Talk No. 20 + Eilers' Hc (varimu.tape_particles.bench_fit)",
    "kv_kt_median": "TAPE_PARTICLE_RESEARCH.md 1.6: not found for period oxide; bracket 60-2000, "
    "150 as the middle (provisional: model knowledge)",
    "kappa": "TAPE_PARTICLE_RESEARCH.md 1.5: #111 predates deliberate orientation; unoriented "
    "(provisional: model knowledge)",
    "f0_hz": "TAPE_PARTICLE_RESEARCH.md 1.6: 1e9-1e10 Hz, 1e9 usual for oxide (provisional)",
    "temp_k": "room temperature (TAPE_PARTICLE_RESEARCH.md: kT at 293 K)",
    "soften_m": "provisional: model knowledge (a charge spread over the needle's end face: half "
    "the 0.1 um width)",
}


@dataclass
class Box:
    """Particles in a periodic cube of side side_m: centres r (N x 3), axes n (N x 3), lengths
    l, volumes v, H_K hk, e0_kt (mu0 Ms_p H_K V_act / kT)."""

    side_m: float
    r: np.ndarray
    n: np.ndarray
    l: np.ndarray
    v: np.ndarray
    hk: np.ndarray
    e0_kt: np.ndarray

    def __len__(self) -> int:
        return len(self.l)

    def particles(self) -> ens.Particles:
        z = np.zeros((len(self), 3))
        return ens.Particles(self.n, self.hk, self.v, self.e0_kt, z)


def make_box(spec: BenchSpec, count: int, seed: int = 1, name: str = "bench") -> Box:
    g = {k: ens.rng_for(seed, f"{name}.{k}") for k in ("l", "hk", "axis", "phi", "r")}
    l = spec.length_median_m * np.exp(spec.sigma_ln_length * g["l"].standard_normal(count))
    w = l / spec.aspect
    v = 0.25 * math.pi * w * w * l
    side = (v.sum() / spec.packing) ** (1.0 / 3.0)
    hk = spec.hk_median_a_m * np.exp(spec.sigma_ln_hk * g["hk"].standard_normal(count))
    t = ens.watson_cos(spec.kappa, g["axis"].random(count))
    phi = 2.0 * math.pi * g["phi"].random(count)
    st = np.sqrt(np.maximum(0.0, 1.0 - t * t))
    n = np.stack([t, st * np.cos(phi), st * np.sin(phi)], axis=1)
    r = side * g["r"].random((count, 3))
    if spec.packed:
        from varimu.tape_particles import pack

        r, n, _, left = pack.relax(
            r, n, l, w, side, spec.contact, rng=ens.rng_for(seed, f"{name}.pack")
        )
        if left:
            raise RuntimeError(f"{left} needle overlaps left after relaxing")
    # V_act = c V, the median K V_act / kT = kv_kt_median.
    v_med = 0.25 * math.pi * (spec.length_median_m / spec.aspect) ** 2 * spec.length_median_m
    c = 2.0 * spec.kv_kt_median * spec.kt_j / (sw.MU0 * spec.ms_p_a_m * spec.hk_median_a_m * v_med)
    e0 = sw.MU0 * spec.ms_p_a_m * hk * c * v / spec.kt_j
    return Box(side, r, n, l, v, hk, e0)


def _wrap(d: np.ndarray, side: float) -> np.ndarray:
    return d - side * np.round(d / side)


def target_offsets(k: int) -> np.ndarray:
    """Where along a needle its field is sampled, in units of its length (k points)."""
    return (np.arange(k) + 0.5) / k - 0.5


def interaction_field(box: Box, spec: BenchSpec, m: np.ndarray) -> np.ndarray:
    """The field (A/m, N x 3) on each particle from the others (charges and dipoles,
    minimum image, softened), averaged over `target_points` points along its length, plus
    the outside's mean field."""
    mu = spec.ms_p_a_m * box.v[:, None] * m  # A m^2
    ax = np.einsum("ij,ij->i", mu, box.n)
    q = ax / box.l  # A m
    perp = mu - ax[:, None] * box.n
    a2 = spec.soften_m**2
    h = np.zeros_like(m)
    ends = [(box.r + 0.5 * box.l[:, None] * box.n, q), (box.r - 0.5 * box.l[:, None] * box.n, -q)]
    offs = target_offsets(spec.target_points)
    for i in range(len(box)):
        acc = np.zeros(3)
        for o in offs:
            ri = box.r[i] + o * box.l[i] * box.n[i]
            for pos, qq in ends:
                d = _wrap(ri - pos, box.side_m)
                r2 = np.einsum("ij,ij->i", d, d) + a2
                w = qq / (FOUR_PI * r2 * np.sqrt(r2))
                w[i] = 0.0
                acc += w @ d
            d = _wrap(ri - box.r, box.side_m)
            r2 = np.einsum("ij,ij->i", d, d) + a2
            md = np.einsum("ij,ij->i", perp, d)
            inv = 1.0 / (FOUR_PI * r2 * np.sqrt(r2))
            f = (3.0 * md / r2)[:, None] * d - perp
            f[i] = 0.0
            acc += (inv[:, None] * f).sum(axis=0)
        h[i] = acc / len(offs)
    return h + mean_field(box, spec, m)


def mean_field(box: Box, spec: BenchSpec, m: np.ndarray) -> np.ndarray:
    mbar = spec.ms_p_a_m * (box.v[:, None] * m).sum(axis=0) / box.side_m**3
    return (mbar / 3.0 - np.asarray(spec.sample_demag) * mbar)[None, :]


def erased_state(count: int, seed: int, name: str = "bench.erase") -> np.ndarray:
    """Random signs (p in {0, 1})."""
    return (ens.rng_for(seed, name).random(count) < 0.5).astype(float)


def run(
    box: Box,
    spec: BenchSpec,
    h_app: np.ndarray,
    dt_s: float,
    seed: int = 1,
    p0: np.ndarray | None = None,
    grid: int = 32,
    trace: bool = False,
):
    """The applied field history h_app (steps x 3, A/m, the same on every particle): the
    final (p, m) and, if trace, the box's M / Ms (sum V m / sum V, 3 components) after
    every step."""
    nb = len(box)
    parts = box.particles()
    p = erased_state(nb, seed) if p0 is None else p0.copy()
    m = (2.0 * p - 1.0)[:, None] * box.n
    hint0 = None
    out = []
    idx = np.arange(nb)
    for j in range(len(h_app)):
        if spec.interactions == "none":
            hint = np.zeros((nb, 3))
        elif spec.interactions == "frozen":
            if hint0 is None:
                hint0 = interaction_field(box, spec, m)
            hint = hint0
        else:
            hint = interaction_field(box, spec, m)
        hint = spec.interaction_scale * hint
        u = ens.hash_uniform(seed, idx, j)
        p, m = ens.step(parts, h_app[j][None, :] + hint, p, dt_s, spec, grid, True, u)
        if trace:
            out.append((box.v[:, None] * m).sum(axis=0) / box.v.sum())
    return p, m, (np.array(out) if trace else None)


def magnetization(box: Box, m: np.ndarray) -> np.ndarray:
    """sum V m / sum V (M over the particles' saturation, 3 components)."""
    return (box.v[:, None] * m).sum(axis=0) / box.v.sum()

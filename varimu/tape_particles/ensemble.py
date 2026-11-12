"""An ensemble of Stoner-Wohlfarth particles drawn from physical distributions, and its
response to a field history (the master equation of `sw`, per particle).

**The particles** (`ParticleSpec`, every value with its source in `SOURCES`):
- the moment volume V lognormal (median, log spread);
- the anisotropy field H_K lognormal (an *effective* field: real gamma-Fe2O3 needles
  reverse incoherently at about a third of their coherent-rotation field, so H_K is what a
  coherent particle would need to switch as they do, the SW angular law kept);
- the barrier K V_act at zero field: V_act = c V with c set by the median K V_act / kT
  (`kv_kt_median`): incoherent reversal activates a smaller volume than the particle's;
- easy axes from a Watson distribution exp(kappa (n . x)^2) on the sphere (kappa = 0:
  unoriented);
- a quenched local interaction field per particle, isotropic Gaussian (sigma per
  component): what the neighbours' dipolar near fields put on it beyond the cell-averaged
  field the medium computes;
- Ms_p of the oxide and the packing fraction (the coating's Ms = packing x Ms_p).

All randomness: np.random.default_rng([seed, crc32(name)]), one stream per quantity.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field, replace

import numpy as np

from varimu.tape_particles import sw

OE = 1000.0 / (4.0 * math.pi)  # one oersted in A/m


@dataclass(frozen=True)
class ParticleSpec:
    ms_p_a_m: float = 3.6e5
    packing: float = 0.35
    v_median_m3: float = 1.62e-21
    sigma_ln_v: float = 0.5
    hk_median_a_m: float = 600.0 * OE
    sigma_ln_hk: float = 0.3
    kv_kt_median: float = 150.0
    sigma_int_a_m: float = 40.0 * OE
    kappa: float = 0.0
    f0_hz: float = 1e9
    temp_k: float = 293.0
    #: Where each value comes from (Hard rules: no unsourced value).
    sources: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def kt_j(self) -> float:
        return sw.KB * self.temp_k

    @property
    def ms_coating_a_m(self) -> float:
        return self.packing * self.ms_p_a_m

    def with_(self, **kw) -> ParticleSpec:
        return replace(self, **kw)


#: Provisional until docs/TAPE_PARTICLES.md's literature values replace them (each entry is
#: overwritten by `literature_spec` where a cited value exists).
PROVISIONAL_SOURCES = {
    "ms_p_a_m": "provisional: model knowledge (gamma-Fe2O3 bulk ~74 emu/g at 4.9 g/cm^3; the "
    "value scripts/tape_switching_study.py uses)",
    "packing": "provisional: model knowledge (1950s acicular gamma-Fe2O3 coatings, 30-40% by "
    "volume; SCOTCH111@3's noise block)",
    "v_median_m3": "fit: SCOTCH111@3 noise block (Sound Talk No. 34; ~0.4 x 0.07 um needles)",
    "sigma_ln_v": "provisional: model knowledge (acicular oxide size distributions, log spread "
    "~0.3-0.6)",
    "hk_median_a_m": "fit: Sound Talk No. 20 + Eilers' Hc (varimu.tape_particles.static)",
    "sigma_ln_hk": "fit: Sound Talk No. 20 + Eilers' Hc (varimu.tape_particles.static)",
    "kv_kt_median": "provisional: model knowledge (incoherent reversal: activation volumes well "
    "below the particle's; K V_act / kT ~100-300 for audio oxides)",
    "sigma_int_a_m": "fit: Sound Talk No. 20 + Eilers' Hc (varimu.tape_particles.static)",
    "kappa": "provisional: model knowledge (Scotch 111, 1948: an unoriented coating)",
    "f0_hz": "provisional: model knowledge (Neel-Brown attempt frequency 1e9-1e10 Hz)",
    "temp_k": "provisional: room temperature",
}


@dataclass
class Particles:
    """Per particle: easy axis n (N x 3), H_K (A/m), moment volume v (m^3), e0_kt =
    mu0 Ms_p H_K V_act / kT (the reduced energy's scale), hloc (N x 3, A/m); positions x
    (along the tape) and y (depth) when placed in a medium."""

    n: np.ndarray
    hk: np.ndarray
    v: np.ndarray
    e0_kt: np.ndarray
    hloc: np.ndarray
    x: np.ndarray | None = None
    y: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.hk)

    def take(self, idx) -> Particles:
        return Particles(
            self.n[idx],
            self.hk[idx],
            self.v[idx],
            self.e0_kt[idx],
            self.hloc[idx],
            None if self.x is None else self.x[idx],
            None if self.y is None else self.y[idx],
        )


def rng_for(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(name.encode())])


def watson_cos(kappa: float, u: np.ndarray) -> np.ndarray:
    """t = n . x for uniforms u, from the Watson density exp(kappa t^2) on [-1, 1]."""
    if kappa == 0.0:
        return 2.0 * u - 1.0
    t = np.linspace(-1.0, 1.0, 4001)
    w = np.exp(kappa * (t * t - (1.0 if kappa > 0 else 0.0)))
    cdf = np.concatenate([[0.0], np.cumsum(0.5 * (w[1:] + w[:-1]) * np.diff(t))])
    cdf /= cdf[-1]
    return np.interp(u, cdf, t)


def draw(spec: ParticleSpec, count: int, seed: int = 1, name: str = "particles") -> Particles:
    """`count` particles (no positions)."""
    g = {k: rng_for(seed, f"{name}.{k}") for k in ("v", "hk", "axis", "phi", "hloc")}
    v = spec.v_median_m3 * np.exp(spec.sigma_ln_v * g["v"].standard_normal(count))
    hk = spec.hk_median_a_m * np.exp(spec.sigma_ln_hk * g["hk"].standard_normal(count))
    t = watson_cos(spec.kappa, g["axis"].random(count))
    phi = 2.0 * math.pi * g["phi"].random(count)
    st = np.sqrt(np.maximum(0.0, 1.0 - t * t))
    n = np.stack([t, st * np.cos(phi), st * np.sin(phi)], axis=1)
    # V_act = c V: the median K V_act / kT is kv_kt_median.
    c = (
        2.0
        * spec.kv_kt_median
        * spec.kt_j
        / (sw.MU0 * spec.ms_p_a_m * spec.hk_median_a_m * spec.v_median_m3)
    )
    e0 = sw.MU0 * spec.ms_p_a_m * hk * (c * v) / spec.kt_j
    hloc = spec.sigma_int_a_m * g["hloc"].standard_normal((count, 3))
    return Particles(n, hk, v, e0, hloc)


def erased(count: int, stochastic: bool = False, seed: int = 1, name: str = "erase"):
    """The AC-erased state: p = 1/2 (the master equation's expectation), or a random sign
    per particle (stochastic: p in {0, 1})."""
    if not stochastic:
        return np.full(count, 0.5)
    return (rng_for(seed, name).random(count) < 0.5).astype(float)


def hash_uniform(seed: int, idx: np.ndarray, step: int) -> np.ndarray:
    """A counter-based uniform in [0, 1) per (seed, particle, step): a 32-bit integer hash
    (lowbias32 rounds) the WGSL kernel computes the same way."""
    x = (np.asarray(idx, np.uint64) * np.uint64(0x9E3779B1)) & np.uint64(0xFFFFFFFF)
    x ^= np.uint64((seed * 0x85EBCA77 + step * 0xC2B2AE3D) & 0xFFFFFFFF)
    for _ in range(2):
        x ^= x >> np.uint64(16)
        x = (x * np.uint64(0x7FEB352D)) & np.uint64(0xFFFFFFFF)
        x ^= x >> np.uint64(15)
        x = (x * np.uint64(0x846CA68B)) & np.uint64(0xFFFFFFFF)
        x ^= x >> np.uint64(16)
    return (x >> np.uint64(8)).astype(float) / float(1 << 24)


def step(
    parts: Particles,
    h_a_m: np.ndarray,
    p: np.ndarray,
    dt_s: float,
    spec: ParticleSpec,
    grid: int = 32,
    stochastic: bool = False,
    u: np.ndarray | None = None,
):
    """One step of dt with the applied field h_a_m (N x 3, A/m; hloc is added here):
    (the new p, the expected moment per particle N x 3, unit). stochastic: p is 0 / 1 and u
    (uniforms per particle) samples the transition."""
    h = (h_a_m + parts.hloc) / parts.hk[:, None]
    a, b, uu = sw.frame(parts.n, h)
    dp, dm, t1, t2, two = sw.barriers(a, b, grid)
    qp, qm = sw.transition(dp, dm, two, a, parts.e0_kt, spec.f0_hz, dt_s)
    if stochastic:
        up = p > 0.5
        flip = np.where(up, u < qp, u < qm)
        p = np.where(flip, 1.0 - p, p)
    else:
        p = p * (1.0 - qp) + (1.0 - p) * qm
    mp, mm = sw.moments(parts.n, uu, t1, t2)
    return p, p[:, None] * mp + (1.0 - p)[:, None] * mm


def run_uniform(
    parts: Particles,
    spec: ParticleSpec,
    h_x: np.ndarray,
    dt_s: float,
    p0: np.ndarray | None = None,
    grid: int = 32,
    chunk: int = 200_000,
    record: bool = False,
):
    """A uniform applied field along x over time (h_x: steps, A/m, or steps x R for R
    histories run on the same particles at once): the final (p, M_x / Ms) per history,
    M_x / Ms = sum V m_x / sum V (the ensemble's x magnetization over its saturation).
    record: also M_x / Ms after every step (steps x R)."""
    h_x = np.asarray(h_x, float)
    if h_x.ndim == 1:
        h_x = h_x[:, None]
    steps, reps = h_x.shape
    n = len(parts)
    wv = parts.v / parts.v.sum()
    p = np.tile(p0 if p0 is not None else erased(n), (reps, 1))
    trace = np.zeros((steps, reps)) if record else None
    big = parts.take(np.tile(np.arange(n), reps))
    pf = p.reshape(-1)
    mx = np.zeros(n * reps)
    for k in range(steps):
        hx = np.repeat(h_x[k], n)
        for c0 in range(0, n * reps, chunk):
            sl = slice(c0, min(c0 + chunk, n * reps))
            hv = np.zeros((sl.stop - sl.start, 3))
            hv[:, 0] = hx[sl]
            pf[sl], m = step(big.take(sl), hv, pf[sl], dt_s, spec, grid)
            mx[sl] = m[:, 0]
        if record:
            trace[k] = (mx.reshape(reps, n) * wv).sum(axis=1)
    final = (mx.reshape(reps, n) * wv).sum(axis=1)
    return pf.reshape(reps, n), final, trace

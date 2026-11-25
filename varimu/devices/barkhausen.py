"""Barkhausen avalanches in a transformer core: the Python reference of circuitsim's
`barkhausen.rs` (docs/PART_NOISE_PLAN.md; the offline study, varimu.part_noise.iron).

A medium beside the circuit (as a plate or tape): it senses a core node (its voltage is B,
1 V = 1 mT) after every step and drives its output node at the next; a Vccs from that node
feeds the core node the current equal to a jump of magnetization at a fixed field
(varimu.circuit.parts.barkhausen wires it). Like the core itself, it has no SPICE
implementation (ngspice sees the output held at 0 V).

**The core's irreversible magnetization.** The engine hands the medium its core device's
accepted state after each sample, (B, H, B's direction) (`push_state`); where a circuit has
no core device (a linear-core build) the medium replays the sensed B through its own copy of
the core's Jiles-Atherton model (varimu.devices.core: the same material and path), one point
per step (`push`). From the state: dH/dB, M = B / mu0 - H, Man = Ms L((H + alpha M)
/ a), and Mirr = (M - c Man) / (1 - c), in saturation magnetizations (Ms). Only Mirr jumps.

**The landscape.** The core's pinning is fixed: along Mirr its walls jump at the same places
every time (return-point memory). Mirr is cut into bins of width W = BIN_FACTOR s_max; bin j
(the floor of Mirr / W) holds n jumps (n = round(W / mean + sqrt(W / mean) z), at least one; z a
unit normal of the stream `<name>:count`, stream j mod 2^32), at uniform positions (stream
`<name>:pos`) sorted, with sizes from a power law p(s) ~ s^-TAU on [s_min, s_max] (stream
`<name>:size`, by inverse CDF), scaled so the bin's jumps add up to W (all the irreversible
change goes by jumps). s_max = s_unit x STRESS. The bins don't depend on the path taken: any
run, any order of visits, sees the same barcode. Its deviation from the smooth model, at r =
Mirr - jW inside the bin, is C(r) - r, C the sum of the sizes of the jumps below r.

**To the circuit.** dM = deviation - its value at the first step (the run starts on its own
operating point), through a one-pole low-pass at `avalanche_hz` (a jump takes time) and a one-
pole high-pass at `highpass_hz` (the demagnetizing field holds the mean on the loop), both
exact for a held input (factor 1 - exp(-2 pi f dt)). The current path (dH/dB) mu0 Ms dM is the
jump of M at a fixed field (the core device's path H(B - mu0 dM)); the output is that current
times `out_v_per_a` (1 / the Vccs's gm).

STRESS 0 is off: no work, output 0; turning it on starts from the core's point then (the
replay restarts on the initial curve, dM from zero). A new STRESS scales the same barcode
(the same uniforms: the same sites, stronger pinning).

**Uniform draws.** Draw k of a stream is word k % 4 of Philox4x64-10's block at counter
k // 4 + 1 under the stream's key (varimu.devices.noise's keys), u = ((w >> 11) + 0.5) 2^-53.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from varimu.devices import noise
from varimu.devices.core import MU0, TESLA_PER_V, CoreState, MagneticCore, langevin

# Constants of the part (varimu.circuit.parts.barkhausen writes them into the IR element).
S_MIN = 1e-8  # the smallest jump, in Ms (smaller ones are inaudible)
S_UNIT = 1e-6  # the largest jump at STRESS 1, in Ms
TAU = 1.5
BIN_FACTOR = 100.0
AVALANCHE_HZ = 2000.0
HIGHPASS_HZ = 5.0
SOURCE = (
    "provisional: model knowledge (a macroscopic soft core's Barkhausen jumps: up to ~1e-6 of "
    "its saturation flux at STRESS 1, down to 1e-8 here; avalanche durations ~0.1-1 ms; the size "
    "law's exponent 3/2 is ABBM's, web: https://arxiv.org/abs/cond-mat/0404512 (Durin & "
    "Zapperi, The Barkhausen effect); return-point memory as Sethna et al. find it in driven "
    "disordered magnets; nothing fitted to a measured core)"
)

_TWO_M53 = 2.0**-53


def uniforms(key: tuple[int, int], start: int, n: int) -> np.ndarray:
    """Draws start .. start + n of the stream with key `key`, in (0, 1)."""
    if n <= 0:
        return np.zeros(0)
    b0, b1 = start // 4, (start + n - 1) // 4 + 1
    w = noise._words(key, b0, b1 - b0).reshape(-1)
    u = ((w >> np.uint64(11)).astype(float) + 0.5) * _TWO_M53
    o = start - 4 * b0
    return u[o : o + n]


def _stream(j: int) -> int:
    return j % (1 << 32)


def mean_size(s_min: float, s_max: float, tau: float) -> float:
    """The mean of p(s) ~ s^-tau on [s_min, s_max]."""
    e = 1.0 - tau
    lo_e, hi_e = s_min**e, s_max**e
    return (s_min ** (2.0 - tau) - s_max ** (2.0 - tau)) / (tau - 2.0) / ((hi_e - lo_e) / e)


@dataclass
class Bin:
    pos: np.ndarray  # sorted positions inside the bin, 0 .. W
    cum: np.ndarray  # cum[i]: the sizes of the jumps below pos[i] (cum[0] = 0), cum[-1] = W


def make_bin(seed: int, name: str, j: int, s_min: float, s_max: float, tau: float, w: float):
    """Bin j's jumps (the module docstring), in plain loops (the Rust port's order)."""
    mean = mean_size(s_min, s_max, tau)
    m = w / mean
    z = noise.normals(noise.key(seed, f"{name}:count", _stream(j)), 0, 1)[0]
    count = max(1, int(math.floor(m + math.sqrt(m) * z + 0.5)))
    pos = np.sort(uniforms(noise.key(seed, f"{name}:pos", _stream(j)), 0, count) * w)
    u = uniforms(noise.key(seed, f"{name}:size", _stream(j)), 0, count)
    e = 1.0 - tau
    lo_e, hi_e = s_min**e, s_max**e
    sizes = [(lo_e + float(x) * (hi_e - lo_e)) ** (1.0 / e) for x in u]
    total = 0.0
    for s in sizes:
        total += s
    scale = w / total
    cum = np.empty(count + 1)
    acc = 0.0
    cum[0] = 0.0
    for i, s in enumerate(sizes):
        acc += s * scale
        cum[i + 1] = acc
    return Bin(pos, cum)


@dataclass
class Barkhausen:
    """The medium (circuitsim's `barkhausen::Medium`): push the sensed core voltage after a
    step of `dt_s`, get the output for the next."""

    core: MagneticCore
    name: str
    seed: int
    stress: float
    out_v_per_a: float
    s_min: float = S_MIN
    s_unit: float = S_UNIT
    tau: float = TAU
    bin_factor: float = BIN_FACTOR
    avalanche_hz: float = AVALANCHE_HZ
    highpass_hz: float = HIGHPASS_HZ
    state: CoreState | None = None
    dev0: float = 0.0
    lp: float = 0.0
    lp2: float = 0.0
    bins: dict = field(default_factory=dict)

    def s_max(self) -> float:
        return self.s_unit * self.stress

    def width(self) -> float:
        return self.bin_factor * self.s_max()

    def deviation(self, m_irr: float) -> float:
        w = self.width()
        j = math.floor(m_irr / w)
        b = self.bins.get(j)
        if b is None:
            b = make_bin(self.seed, self.name, j, self.s_min, self.s_max(), self.tau, w)
            self.bins[j] = b
        r = m_irr - j * w
        i = int(np.searchsorted(b.pos, r, side="left"))
        return float(b.cum[i]) - r

    def set_stress(self, stress: float) -> None:
        """A new STRESS: the same barcode, scaled (off: the replay stops; on again: restarts)."""
        if stress != self.stress:
            self.bins = {}
            if stress == 0.0:
                self.state = None
            self.stress = stress

    def push(self, v_core: float, dt_s: float) -> float:
        """The sensed core voltage after a step: the core's state by replaying B through the
        medium's own copy of its model (the fallback where a circuit has no core device; the
        engine hands a core's accepted state to `push_state`)."""
        if self.stress == 0.0:
            return 0.0
        b = v_core * TESLA_PER_V
        st = self.state
        if st is None:
            h0, _ = self.core.h_of_b(b, CoreState())
            st = CoreState(b, h0, 1.0)
        h, _ = self.core.h_of_b(b, st)
        delta = st.delta if b == st.b else (1.0 if b > st.b else -1.0)
        return self.push_state(b, h, delta, dt_s)

    def push_state(self, b: float, h: float, delta: float, dt_s: float) -> float:
        """The core's accepted state after a step (B in T, H in A/m, B's direction); the
        output for the next."""
        if self.stress == 0.0:
            return 0.0
        core = self.core
        first = self.state is None
        self.state = CoreState(b, h, delta)
        slope = core.dh_db(b, h, delta)
        m = b / MU0 - h
        man = core.ms_a_per_m * langevin((h + core.alpha * m) / core.a_a_per_m)
        m_irr = (m - core.c * man) / (1.0 - core.c) / core.ms_a_per_m
        dev = self.deviation(m_irr)
        if first:
            self.dev0, self.lp, self.lp2 = dev, 0.0, 0.0
        x = dev - self.dev0
        self.lp += (x - self.lp) * (1.0 - math.exp(-2.0 * math.pi * self.avalanche_hz * dt_s))
        self.lp2 += (self.lp - self.lp2) * (
            1.0 - math.exp(-2.0 * math.pi * self.highpass_hz * dt_s)
        )
        dm = self.lp - self.lp2
        current = core.path_m * slope * MU0 * core.ms_a_per_m * dm
        return current * self.out_v_per_a

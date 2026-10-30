"""Noise sources (device builder B5): Johnson noise of resistors, shot and flicker noise of
tubes, and the seeded streams behind them. The Python reference; circuitsim's
`src/noise.rs` is the compiled port (crates/circuitsim/tests/noise.rs checks it against
fixtures from this module).

**Streams.** Every noise source draws unit normals from a counter-based generator,
Philox4x64-10 (Salmon et al., SC 2011), numpy's `np.random.Philox`: a source's key is
(seed, crc32(name) << 32 | stream), and sample k is a pure function of (key, k). So any
block, a render in chunks, a partition on its own thread and a re-render at another quality
all see the same samples, and adding a source moves no other (CLAUDE.md, Reproducibility:
the per-item key from (seed, crc32(name)), through np.random.Generator's Philox). Sample k
is word pair (k % 4) // 2 of the block numpy's fresh `Philox(key)` emits (k // 4)-th, by
Box-Muller: u1 = ((w0 >> 11) + 1) 2^-53 in (0, 1], u2 = (w1 >> 11) 2^-53,
r = sqrt(-2 ln u1), samples 2p, 2p + 1 = r cos(2 pi u2), r sin(2 pi u2).

**The grid.** Samples sit on the project's sample grid (sim_settings' sample_rate; the IR's
`noise.rate_hz`), sample 0 at the run's start (t = 0, the settle included: renders and the
native app settle for the same `settle_s`, so a take's noise lines up across qualities),
linear between samples, as control inputs are. The DC operating point is noise-free. A white
stream of one-sided density S then has sample variance S fs / 2, and the linear
interpolation (a triangle pulse per sample, sinc^2 in amplitude) shapes its density by
sinc^4(f / fs) (`interp_gain`: -0.3 dB at 10 kHz, -1.3 dB at 20 kHz at
96 kHz), which the tests count in.

**Flicker** (1/f) is the unit stream through `FlickerFilter`: 15 first-order pole-zero
sections, two per decade from `F_LO_HZ`, in parallel form (all residues positive: an RC
immittance), within +-0.03 dB of 1/f from 0.01 Hz to 10 kHz, flat below F_LO_HZ; it starts
in its stationary state at sample 0 (the state drawn from its own stream), so no warm-up.

**Densities** (one-sided, per hertz): `johnson_a2` (4kT/R), `shot_a2` (a tube's plate
current: 4 k T0 beta gm, beta 2.5 at T0 290 K, i.e. R_eq = 2.5 / gm; a pentode's partition
noise (Ib / Ik)(4 k T0 beta)(gm + 8 Ic2)), `grid_shot_a2` (2 q |Ig|), and flicker as a
voltage in series with the grid, K_f / f. The engines put flicker in as the plate current
gm e_f, which is that voltage to first order: e_f is microvolts, so the rest is ~1e-6 of it.
Shot noise and gm e_f take the tube's gm and currents at the last accepted step.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np

# CODATA 2018 (exact in the SI since 2019).
K_B = 1.380649e-23  # J/K
Q_E = 1.602176634e-19  # C

# Tube shot noise as an equivalent grid noise resistance R_eq = BETA / gm at T0.
SHOT_BETA = 2.5
SHOT_T0_K = 290.0
# Pentode partition noise: R_eq = (Ib / Ik)(BETA / gm)(1 + PARTITION Ic2 / gm).
PARTITION = 8.0
SHOT_SOURCE = (
    "K. R. Spangenberg, Vacuum Tubes (McGraw-Hill, 1948), noise: R_eq = 2.5 / gm for a "
    "triode, (Ip / Ik)(2.5 / gm)(1 + 8 I2 / gm) for a pentode (after Thompson, North & Harris, "
    "RCA Review 1940-41); web: https://n5296s.blogspot.com/2025/09/"
    "tubes-201-how-vacuum-tubes-really-work_90.html (the same forms)"
)

# Defaults of a circuit's `noise` block (varimu.circuit.spec).
RESISTOR_T_K = 313.0
RESISTOR_T_SOURCE = (
    "provisional: model knowledge (resistors inside a warm tube chassis, ~40 C; Johnson noise "
    "goes as sqrt(T): 313 K is 0.3 dB above 290 K)"
)
# Flicker: one-sided density K_f / f of a voltage in series with the grid.
FLICKER_V2 = 2.5e-14
FLICKER_SOURCE = (
    "provisional: model knowledge (estimate, device builder B5: space-charge-limited, a "
    "relative emission fluctuation dJ/J moves the potential minimum by (kTc/q) dJ/J, a "
    "grid-referred voltage independent of the operating point, K_f = (kTc/q)^2 A with "
    "kTc/q ~0.09 V (1050 K) and A ~3e-12, the order of oxide cathodes' emission flicker in "
    "temperature-limited diodes (Johnson 1925, Schottky 1926); a corner ~1 kHz for a 12AX7 "
    "at gm 1.6 mA/V, the user's pick 2026-10-30; bounds 2.5e-15..2.5e-13, corners "
    "100 Hz..10 kHz)"
)
F_LO_HZ = 1e-3  # flat below: ~17 minutes
FLICKER_SECTIONS = 15

# Streams of a source (the low word of the key's second half).
STREAM_MAIN = 0  # a resistor's current, a tube's plate shot noise
STREAM_GRID = 1  # a tube's grid-current shot noise
STREAM_FLICKER = 2  # the flicker filter's input
STREAM_FLICKER_START = 3  # its stationary start


def key(seed: int, name: str, stream: int) -> tuple[int, int]:
    """The Philox key of `name`'s `stream` under `seed`."""
    if not 0 <= seed < 2**64:
        raise ValueError(f"noise seed {seed} must fit 64 bits unsigned")
    if not 0 <= stream < 2**32:
        raise ValueError(f"stream {stream}")
    return seed, (zlib.crc32(name.encode()) << 32) | stream


def _words(k: tuple[int, int], first_block: int, blocks: int) -> np.ndarray:
    bg = np.random.Philox(key=np.array(k, dtype=np.uint64))
    if first_block:
        bg.advance(first_block)
    return bg.random_raw(4 * blocks).reshape(blocks, 4)


def normals(k: tuple[int, int], start: int, n: int) -> np.ndarray:
    """Unit normals start .. start + n of the stream with key `k`."""
    if n <= 0:
        return np.zeros(0)
    b0, b1 = start // 4, (start + n - 1) // 4 + 1
    w = _words(k, b0, b1 - b0)
    u1 = ((w[:, 0::2] >> np.uint64(11)) + np.uint64(1)).astype(float) * 2.0**-53
    u2 = (w[:, 1::2] >> np.uint64(11)).astype(float) * 2.0**-53
    r = np.sqrt(-2.0 * np.log(u1))
    t = 2.0 * math.pi * u2
    z = np.empty((b1 - b0, 4))
    z[:, 0::2] = r * np.cos(t)
    z[:, 1::2] = r * np.sin(t)
    flat = z.reshape(-1)
    o = start - 4 * b0
    return flat[o : o + n]


def white_sigma(psd: float, rate_hz: float) -> float:
    """Sample standard deviation of a white stream of one-sided density `psd` on a grid of
    `rate_hz`."""
    return math.sqrt(psd * rate_hz / 2.0)


def interp_gain(f_hz, rate_hz: float):
    """The density's gain from linear interpolation between grid samples: each sample is a
    triangle pulse, sinc^2(f / fs) in amplitude, sinc^4 in power."""
    return np.sinc(np.asarray(f_hz, float) / rate_hz) ** 4


# --- Densities ---------------------------------------------------------------------------


def johnson_a2(r_ohm: float, temperature_k: float) -> float:
    """A resistor's Norton noise current, A^2/Hz."""
    return 4.0 * K_B * temperature_k / r_ohm


def shot_k() -> float:
    """4 k T0 beta: a triode's plate noise density per siemens of gm (A^2/Hz/S)."""
    return 4.0 * K_B * SHOT_T0_K * SHOT_BETA


def shot_a2(gm_s: float, ib_a: float = 0.0, ic2_a: float = 0.0, partition: float = 0.0) -> float:
    """A tube's plate noise current, A^2/Hz: shot_k gm for a triode (partition 0); with a
    screen, (Ib / Ik) shot_k (gm + partition Ic2). Zero where gm <= 0 (cut off)."""
    gm = max(gm_s, 0.0)
    if partition == 0.0:
        return shot_k() * gm
    ib, ic2 = max(ib_a, 0.0), max(ic2_a, 0.0)
    ik = ib + ic2
    if ik <= 0.0:
        return 0.0
    return ib / ik * shot_k() * (gm + partition * ic2)


def grid_shot_a2(ig_a: float) -> float:
    """Full shot noise of grid current, 2 q |Ig| (no space-charge smoothing at the grid)."""
    return 2.0 * Q_E * abs(ig_a)


# --- Flicker ------------------------------------------------------------------------------


@dataclass(frozen=True)
class FlickerFilter:
    """Unit white noise -> 1/f: y = gain (d n[k] + sum_i s_i[k]), s_i[k] = p_i s_i[k-1] + r_i n[k].

    Poles at F_LO_HZ 10^(i/2), zeros a quarter decade above each, bilinear with prewarped
    corners; the pole and zero distances from 1 (`eps`) are kept exactly, so the residues
    don't lose digits near z = 1. `gain` scales to one-sided density 1/f (V^2/Hz per V^2 of
    K_f), from the continuous prototype's geometric-mean level over one period (a half
    decade) around 1 Hz.
    """

    poles: np.ndarray
    residues: np.ndarray
    direct: float
    gain: float
    start_chol: np.ndarray  # lower Cholesky factor of the stationary state covariance

    @classmethod
    def design(cls, rate_hz: float, f_lo_hz: float = F_LO_HZ, n: int = FLICKER_SECTIONS):
        r = 10.0**0.25
        fp = [f_lo_hz * r ** (2 * i) for i in range(n)]
        fz = [f * r for f in fp]
        wp = [math.tan(math.pi * f / rate_hz) for f in fp]
        wz = [math.tan(math.pi * f / rate_hz) for f in fz]
        ep = [2 * w / (1 + w) for w in wp]
        ez = [2 * w / (1 + w) for w in wz]
        g = 1.0
        for a, b in zip(wp, wz, strict=True):
            g *= (a / b) * (b + 1) / (a + 1)
        d = g
        for a, b in zip(ep, ez, strict=True):
            d *= (1 - b) / (1 - a)
        res = []
        for i in range(n):
            num, den = g, 1 - ep[i]
            for j in range(n):
                num *= ez[j] - ep[i]
                if j != i:
                    den *= ep[j] - ep[i]
            res.append(num / den)
        # The prototype's level f |H(j 2 pi f)|^2, geometric mean over 64 points of a half decade.
        acc = 0.0
        for k in range(64):
            f = 10.0 ** (k / 128.0)
            h2 = 1.0
            for a, b in zip(fp, fz, strict=True):
                h2 *= (1 + (f / b) ** 2) / (1 + (f / a) ** 2)
            acc += math.log(f * h2)
        level = math.exp(acc / 64)
        # Unit normals have one-sided density 2 / fs.
        gain = math.sqrt(rate_hz / (2.0 * level))
        p = np.array([1 - e for e in ep])
        rr = np.array(res)
        e = np.array(ep)
        cov = np.outer(rr, rr) / (e[:, None] + e[None, :] - e[:, None] * e[None, :])
        return cls(p, rr, d, gain, _cholesky(cov))

    def run(self, k: tuple[int, int], k_start: tuple[int, int], n: int) -> np.ndarray:
        """Samples 0 .. n of unit flicker (one-sided density 1 / f): the input stream `k`,
        the stationary start from `k_start`. Plain loop, the Rust port's order of operations."""
        z0 = normals(k_start, 0, len(self.poles))
        lo = self.start_chol
        s = [float(sum(lo[i, j] * z0[j] for j in range(i + 1))) for i in range(len(z0))]
        u = normals(k, 0, n)
        p, r = self.poles.tolist(), self.residues.tolist()
        out = np.empty(n)
        for t in range(n):
            x = float(u[t])
            y = self.direct * x
            for i in range(len(s)):
                s[i] = p[i] * s[i] + r[i] * x
                y += s[i]
            out[t] = self.gain * y
        return out


def flicker_samples(
    f: FlickerFilter, k: tuple[int, int], k_start: tuple[int, int], n: int
) -> np.ndarray:
    """`FlickerFilter.run`'s samples, vectorized (scipy's lfilter per section; the same to
    rounding): for long streams, such as ngspice's noise files."""
    from scipy.signal import lfilter

    z0 = normals(k_start, 0, len(f.poles))
    s0 = f.start_chol @ z0
    u = normals(k, 0, n)
    y = f.direct * u
    for p, r, s in zip(f.poles, f.residues, s0, strict=True):
        y = y + lfilter([r], [1.0, -p], u, zi=[p * s])[0]
    return f.gain * y


def unit_stream(seed: int, name: str, stream: int, flicker: bool, rate_hz: float, n: int):
    """Samples 0 .. n of a source's unit stream (white, or unit flicker: density 1 / f)."""
    if not flicker:
        return normals(key(seed, name, stream), 0, n)
    f = FlickerFilter.design(rate_hz)
    return flicker_samples(f, key(seed, name, stream), key(seed, name, STREAM_FLICKER_START), n)


def noise_fixtures_json(rate_hz: float = 96000.0) -> str:
    """Fixtures for crates/circuitsim/tests/noise.rs: raw Philox words, normals from several
    starts, the flicker filter's design and its first samples (written by
    scripts/export_circuit_fixtures.py; tests/test_noise.py checks the file is current)."""
    import json

    keys = [(0, "IN_R1", STREAM_MAIN), (12345, "BN_XV1A", STREAM_FLICKER), (2**64 - 1, "x", 7)]
    streams = []
    for seed, name, stream in keys:
        k = key(seed, name, stream)
        streams.append(
            {
                "seed": seed,
                "name": name,
                "stream": stream,
                "key": [str(k[0]), str(k[1])],  # u64s as text: JSON floats can't hold them
                "words": [[str(int(w)) for w in row] for row in _words(k, 0, 3)],
                "starts": {str(s): normals(k, s, 9).tolist() for s in (0, 3, 1000003)},
            }
        )
    f = FlickerFilter.design(rate_hz)
    fk = key(3, "BN_XV1A", STREAM_FLICKER)
    fs = key(3, "BN_XV1A", STREAM_FLICKER_START)
    d = {
        "rate_hz": rate_hz,
        "streams": streams,
        "flicker": {
            "poles": f.poles.tolist(),
            "residues": f.residues.tolist(),
            "direct": f.direct,
            "gain": f.gain,
            "start_chol": f.start_chol.reshape(-1).tolist(),
            "seed": 3,
            "name": "BN_XV1A",
            "samples": f.run(fk, fs, 2000).tolist(),
        },
    }
    return json.dumps(d, indent=1) + "\n"


def _cholesky(a: np.ndarray) -> np.ndarray:
    """Plain Cholesky, row by row (the Rust port's order)."""
    n = len(a)
    lo = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1):
            s = float(a[i, j])
            for k in range(j):
                s -= lo[i, k] * lo[j, k]
            if i == j:
                lo[i, i] = math.sqrt(s) if s > 0 else 0.0
            else:
                lo[i, j] = s / lo[j, j] if lo[j, j] > 0 else 0.0
    return lo

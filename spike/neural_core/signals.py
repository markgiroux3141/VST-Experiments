"""Excitations for the bench: source EMF in volts at the project's rate.

Every item has a name and its own generator, `default_rng([seed, crc32(name)])`, so adding
an item leaves the others alone. Training items are all TRAIN_S long (no padding when
batched); levels are in dBu of the source's EMF (0 dBu = 0.7746 V rms).

Training families (random draws): single sines, bursts with silences between them
(remanence and recoil), two tones (a loud LF tone with a quiet HF one riding on it: biased
minor loops), multisines, program-like noise with a slow level envelope, level sweeps
(one tone through 50+ dB up and back down) and frequency sweeps. The test set is the
same families from another seed namespace, plus fixed items: the THD grid (20 Hz, 50 Hz,
1 kHz from -40 to +20 dBu), a remanence probe (a loud LF burst, silence, a quiet tone)
and 10 s of idle after a loud burst.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from zlib import crc32

import numpy as np

from spike.neural_core.bench import DBU_V_RMS

TRAIN_S = 0.5
FAMILIES = ("sine", "burst", "twotone", "multisine", "noise", "levelsweep", "chirp")


@dataclass
class Item:
    name: str
    v: np.ndarray
    meta: dict = field(default_factory=dict)


def amp(dbu: float) -> float:
    """Peak volts of a sine at `dbu`."""
    return DBU_V_RMS * math.sqrt(2) * 10 ** (dbu / 20)


def fade(n: int, fs: int, in_s: float, rng_out_at: float | None = None, out_s: float = 0.0):
    """A raised-cosine fade-in envelope (and fade-out ending at `rng_out_at` s)."""
    t = np.arange(n) / fs
    env = np.ones(n)
    if in_s > 0:
        k = t < in_s
        env[k] = 0.5 - 0.5 * np.cos(np.pi * t[k] / in_s)
    if rng_out_at is not None:
        start = rng_out_at - out_s
        k = t >= start
        env[k] *= 0.5 + 0.5 * np.cos(np.pi * np.clip((t[k] - start) / max(out_s, 1e-9), 0, 1))
        env[t >= rng_out_at] = 0
    return env


def log_uniform(rng, lo, hi):
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def _sine(rng, n, fs):
    f = log_uniform(rng, 20, 20000)
    dbu = rng.uniform(-45, 22)
    t = np.arange(n) / fs
    out_at = rng.uniform(0.3, 0.5) * n / fs if rng.random() < 0.4 else None
    env = fade(n, fs, rng.uniform(0.002, 0.05), out_at, rng.uniform(0.001, 0.03))
    return amp(dbu) * env * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)), dict(
        f_hz=f, dbu=dbu
    )


def _burst(rng, n, fs):
    f = log_uniform(rng, 20, 5000)
    t = np.arange(n) / fs
    env = np.zeros(n)
    pos = 0.0
    while pos < n / fs:
        on = rng.uniform(0.02, 0.15)
        gap = rng.uniform(0.005, 0.12)
        dbu = rng.uniform(-40, 22)
        k = (t >= pos) & (t < pos + on)
        ramp = rng.uniform(0.0005, 0.01)
        x = t[k] - pos
        env[k] = 10 ** ((dbu - 22) / 20) * np.minimum(1, np.minimum(x, on - x) / ramp)
        pos += on + gap
    return amp(22) * env * np.sin(2 * np.pi * f * t), dict(f_hz=f)


def _twotone(rng, n, fs):
    f1, f2 = log_uniform(rng, 20, 200), log_uniform(rng, 500, 15000)
    d1 = rng.uniform(-10, 20)
    d2 = d1 - rng.uniform(10, 40)
    t = np.arange(n) / fs
    env = fade(n, fs, rng.uniform(0.01, 0.05))
    x = amp(d1) * np.sin(2 * np.pi * f1 * t) + amp(d2) * np.sin(2 * np.pi * f2 * t)
    return env * x, dict(f1_hz=f1, f2_hz=f2, dbu1=d1, dbu2=d2)


def _multisine(rng, n, fs):
    k = int(rng.integers(3, 13))
    t = np.arange(n) / fs
    x = sum(
        np.sin(2 * np.pi * log_uniform(rng, 20, 20000) * t + rng.uniform(0, 2 * np.pi))
        for _ in range(k)
    )
    dbu = rng.uniform(-40, 15)
    x *= DBU_V_RMS * 10 ** (dbu / 20) / np.sqrt(np.mean(x**2))
    return fade(n, fs, rng.uniform(0.01, 0.05)) * x, dict(tones=k, dbu_rms=dbu)


def _noise(rng, n, fs):
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / fs)
    tilt = rng.uniform(0, 1.5)  # 0 white, 1 pink, 1.5 darker than pink
    shape = np.where((f >= 20) & (f <= 20000), 1 / np.maximum(f, 20) ** (tilt / 2), 0)
    x = np.fft.irfft(spec * shape, n)
    # slow level envelope: a smoothed random walk in dB
    steps = rng.standard_normal(n // 960 + 2) * rng.uniform(1, 4)
    walk = np.cumsum(steps)
    env_db = np.interp(np.arange(n) / 960, np.arange(len(walk)), walk - walk.mean())
    dbu = rng.uniform(-40, 12)
    x *= DBU_V_RMS * 10 ** (dbu / 20) / np.sqrt(np.mean(x**2))
    return fade(n, fs, 0.01) * x * 10 ** (np.clip(env_db, -30, 15) / 20), dict(dbu_rms=dbu)


def _levelsweep(rng, n, fs):
    f = log_uniform(rng, 20, 2000)
    top = rng.uniform(0, 22)
    t = np.arange(n) / fs
    tri = 1 - np.abs(2 * t / t[-1] - 1)  # 0 -> 1 -> 0
    dbu = -50 + (top + 50) * tri
    return amp(0) * 10 ** (dbu / 20) * np.sin(2 * np.pi * f * t), dict(f_hz=f, top_dbu=top)


def _chirp(rng, n, fs):
    f0, f1 = (20.0, 20000.0) if rng.random() < 0.5 else (20000.0, 20.0)
    dbu = rng.uniform(-30, 15)
    t = np.arange(n) / fs
    dur = n / fs
    k = math.log(f1 / f0)
    phase = 2 * np.pi * f0 * dur / k * (np.exp(t / dur * k) - 1)
    return amp(dbu) * fade(n, fs, 0.01) * np.sin(phase), dict(dbu=dbu, up=f0 < f1)


GENERATORS: dict[str, Callable] = {
    "sine": _sine,
    "burst": _burst,
    "twotone": _twotone,
    "multisine": _multisine,
    "noise": _noise,
    "levelsweep": _levelsweep,
    "chirp": _chirp,
}


PEAK_MAX_DBU = 24.0  # no item peaks above a +24 dBu sine's peak (T101 is behind the pad)


def random_items(seed: int, split: str, per_family: int, fs: int) -> list[Item]:
    n = int(round(TRAIN_S * fs))
    items = []
    for fam in FAMILIES:
        for k in range(per_family):
            name = f"{split}/{fam}/{k:03d}"
            rng = np.random.default_rng([seed, crc32(name.encode())])
            v, meta = GENERATORS[fam](rng, n, fs)
            v *= min(1.0, amp(PEAK_MAX_DBU) / np.abs(v).max())
            items.append(Item(name, v, dict(meta, family=fam)))
    return items


THD_FREQS_HZ = (20, 50, 1000)
THD_LEVELS_DBU = tuple(range(-40, 21, 10))
THD_SETTLE_S = 0.5  # before the measured cycles (the 17.7 H / 620 ohm corner is ~6 Hz)
THD_CYCLES = 10


def thd_items(fs: int) -> list[Item]:
    items = []
    for f in THD_FREQS_HZ:
        dur = THD_SETTLE_S + THD_CYCLES / f
        n = int(round(dur * fs))
        t = np.arange(n) / fs
        for dbu in THD_LEVELS_DBU:
            v = amp(dbu) * fade(n, fs, 0.1) * np.sin(2 * np.pi * f * t)
            items.append(Item(f"thd/{f}hz/{dbu:+d}dbu", v, dict(f_hz=f, dbu=dbu)))
    return items


def remanence_item(fs: int) -> Item:
    """A +20 dBu 20 Hz burst (0.25 s, cut where the EMF crosses zero and B is at its
    extreme: the core relaxes to its remanence), 0.1 s of silence, then 1 kHz at -20 dBu
    for 0.2 s."""
    t = np.arange(int(0.55 * fs)) / fs
    burst = amp(20) * np.sin(2 * np.pi * 20 * t) * fade(len(t), fs, 0.02) * (t < 0.25)
    tone = amp(-20) * np.sin(2 * np.pi * 1000 * t) * fade(len(t), fs, 0.0) * (t >= 0.35)
    return Item("remanence", burst + tone, dict(tone_from_s=0.35))


def idle_item(fs: int) -> Item:
    """A loud LF burst, then 10 s of silence: must stay silent (no drift, no oscillation)."""
    t = np.arange(int(10.3 * fs)) / fs
    v = amp(18) * np.sin(2 * np.pi * 40 * t) * fade(len(t), fs, 0.02, 0.3, 0.02)
    return Item("idle", v, dict(silent_from_s=0.3))


def test_items(seed: int, per_family: int, fs: int) -> list[Item]:
    return [
        *random_items(seed, "test", per_family, fs),
        *thd_items(fs),
        remanence_item(fs),
        idle_item(fs),
    ]

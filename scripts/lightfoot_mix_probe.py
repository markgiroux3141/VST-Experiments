"""Knob-setting probes for the Lightfoot mix (scratch tool, reports/lightfoot_mix/NOTES.md).

Usage:
  uv run python scripts/lightfoot_mix_probe.py gr IN_REF OUT_REF REF_TRIM IN OUT TRIM
      gain reduction over time: OUT_REF is IN through the device at REF_TRIM (low enough
      that it doesn't compress), OUT at TRIM; prints GR percentiles while the input sounds.
  uv run python scripts/lightfoot_mix_probe.py eq IN OUT
      third-octave change OUT re IN (each normalized at 1 kHz).
"""

from __future__ import annotations

import sys

import numpy as np
import soundfile as sf
from lightfoot_mix_analyze import THIRDS
from scipy import signal


def mono(path: str) -> tuple[np.ndarray, int]:
    x, fs = sf.read(path)
    return (x if x.ndim == 1 else x.mean(axis=1)), fs


def env_db(x: np.ndarray, fs: int, win_s: float = 0.05) -> np.ndarray:
    n = int(win_s * fs)
    m = len(x) // n
    return 10 * np.log10(np.mean(x[: m * n].reshape(m, n) ** 2, axis=1) + 1e-20)


def gr(in_ref, out_ref, ref_trim, inp, out, trim) -> None:
    x, fs = mono(inp)
    a, _ = mono(out_ref)
    b, _ = mono(out)
    n = min(len(x), len(a), len(b))
    ex, ea, eb = env_db(x[:n], fs), env_db(a[:n], fs), env_db(b[:n], fs)
    # the device's latency is under a window; GR = (b - trim) - (a - ref_trim)
    g = (eb - float(trim)) - (ea - float(ref_trim))
    sounding = ex > ex.max() - 25
    print(
        f"GR while sounding: median {-np.median(g[sounding]):.1f} dB, "
        f"p90 {-np.percentile(g[sounding], 10):.1f}, max {-g[sounding].min():.1f}; "
        f"out peak {20 * np.log10(np.abs(b).max()):.1f} dBFS"
    )


def thirds_db(x: np.ndarray, fs: int) -> np.ndarray:
    f, p = signal.welch(x, fs, nperseg=1 << 14)
    out = []
    for fc in THIRDS:
        m = (f >= fc / 2 ** (1 / 6)) & (f < fc * 2 ** (1 / 6))
        out.append(10 * np.log10(np.sum(p[m]) + 1e-30))
    return np.array(out)


def eq(inp, out) -> None:
    x, fs = mono(inp)
    y, _ = mono(out)
    n = min(len(x), len(y))
    d = thirds_db(y[:n], fs) - thirds_db(x[:n], fs)
    d -= d[THIRDS.index(1000)]
    print({f: round(float(v), 1) for f, v in zip(THIRDS, d, strict=False)})


if __name__ == "__main__":
    if sys.argv[1] == "gr":
        gr(*sys.argv[2:8])
    else:
        eq(*sys.argv[2:4])

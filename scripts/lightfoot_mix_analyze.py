"""Measure the four lanes of the Did She Mention My Name tape session before mixing.

Usage: uv run python scripts/lightfoot_mix_analyze.py [DIR ...]

Prints per track: peak, integrated loudness (BS.1770), the sounding rms, the long-term
third-octave spectrum (relative to its maximum) and the share of 400 ms blocks that sound.
With DIR arguments, measures tape1..tape4.wav there instead (the deck's print).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "did she mention my name (tape)"
NAMES = ["bass", "guitar", "lead vocal", "harmonies"]
THIRDS = [31.5, 63, 100, 160, 250, 400, 630, 1000, 1600, 2500, 4000, 6300, 10000, 16000]


def k_weight(x: np.ndarray, fs: int) -> np.ndarray:
    """BS.1770's K filter (the two biquads, re-derived for fs)."""
    # High shelf
    f0, g, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * f0 / fs)
    vh = 10 ** (g / 20)
    vb = vh**0.4996667741545416
    a0 = 1 + k / q + k * k
    b = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]
    a = [1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    y = signal.lfilter(b, a, x)
    # High pass
    f0, q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * f0 / fs)
    a0 = 1 + k / q + k * k
    a = [1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    return signal.lfilter([1, -2, 1], a, y)


def lufs(x: np.ndarray, fs: int) -> float:
    """Integrated loudness, gated (BS.1770-4), of a mono or stereo signal."""
    chans = x.T if x.ndim == 2 else [x]
    z = sum(
        np.array(
            [
                np.mean(c[i : i + int(0.4 * fs)] ** 2)
                for i in range(0, len(c) - int(0.4 * fs), int(0.1 * fs))
            ]
        )
        for c in (k_weight(c, fs) for c in chans)
    )
    lk = -0.691 + 10 * np.log10(z + 1e-30)
    z = z[lk > -70]
    if len(z) == 0:
        return -np.inf
    rel = -0.691 + 10 * np.log10(np.mean(z)) - 10
    z = z[-0.691 + 10 * np.log10(z) > rel]
    return float(-0.691 + 10 * np.log10(np.mean(z)))


def thirds(x: np.ndarray, fs: int) -> list[float]:
    f, p = signal.welch(x, fs, nperseg=1 << 14)
    out = []
    for fc in THIRDS:
        m = (f >= fc / 2 ** (1 / 6)) & (f < fc * 2 ** (1 / 6))
        out.append(10 * np.log10(np.sum(p[m]) + 1e-30))
    top = max(out)
    return [round(v - top, 1) for v in out]


def describe(name: str, x: np.ndarray, fs: int) -> None:
    peak = 20 * np.log10(np.max(np.abs(x)) + 1e-30)
    blk = int(0.4 * fs)
    r = np.array([np.sqrt(np.mean(x[i : i + blk] ** 2)) for i in range(0, len(x) - blk, blk)])
    rdb = 20 * np.log10(r + 1e-12)
    sounding = rdb > rdb.max() - 30
    print(
        f"{name:11s} peak {peak:6.1f} dBFS  {lufs(x, fs):6.1f} LUFS  "
        f"sounding rms {10 * np.log10(np.mean(r[sounding] ** 2)):6.1f} dBFS  "
        f"sounding {100 * sounding.mean():4.0f} %  "
        f"loud-block p95 {np.percentile(rdb[sounding], 95):6.1f} "
        f"p10 {np.percentile(rdb[sounding], 10):6.1f}"
    )
    print("            thirds", dict(zip(THIRDS, thirds(x, fs), strict=False)))


def main() -> None:
    if len(sys.argv) > 1:
        for d in sys.argv[1:]:
            for k, n in enumerate(NAMES):
                x, fs = sf.read(Path(d) / f"tape{k + 1}.wav")
                describe(n, x if x.ndim == 1 else x.mean(axis=1), fs)
        return
    for k, n in enumerate(NAMES):
        x, fs = sf.read(SESSION / "takes" / f"t000{k + 1}" / "draft.wav")
        describe(n, x if x.ndim == 1 else x.mean(axis=1), fs)


if __name__ == "__main__":
    main()

# ruff: noqa: E501
"""Band energy of Suitcase renders against the reference recording (docs/RHODES_PLAN.md "The
Suitcase", the band table): each band's power (a Welch spectrum of both channels, summed) in
dB re the power in 200-2000 Hz.

    uv run --extra fast --with soundfile --with scipy python scripts/suitcase_bands.py
        [FILE.wav ...]     (default: the preamp-only demo and the whole Suitcase's)

The recording is `real instrument samples/Rhodes Mk I 1978 - with Suitcase preamp by Tines
and reeds.mp3` (untracked); the renders are scripts/rhodes_render.py's. Different notes: the
table is coarse (the same caveat as the plan's).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = (
    ROOT
    / "real instrument samples"
    / "Rhodes Mk I 1978 - with Suitcase preamp by Tines and reeds.mp3"
)
BANDS = [
    (80, 200),
    (200, 500),
    (500, 1000),
    (1000, 2000),
    (2000, 4000),
    (4000, 8000),
    (8000, 16000),
]
RENDERS = ROOT / "reports" / "rhodes" / "renders"


def bands_db(path: Path) -> list[float]:
    y, fs = sf.read(path, always_2d=True)
    p = 0.0
    for c in range(y.shape[1]):
        f, pxx = signal.welch(y[:, c], fs=fs, nperseg=8192)
        p = p + pxx
    df = f[1] - f[0]

    def power(lo, hi):
        return float(np.sum(p[(f >= lo) & (f < hi)]) * df)

    ref = power(200, 2000)
    return [10 * np.log10(max(power(lo, hi), 1e-30) / ref) for lo, hi in BANDS]


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]] or [
        RENDERS / "suitcase_demo.wav",
        RENDERS / "suitcase_100w_demo.wav",
    ]
    print("band (Hz)".ljust(34) + "".join(f"{lo}-{hi}".rjust(10) for lo, hi in BANDS))
    rows = [("recording", REFERENCE)] + [(f.stem, f) for f in files if f.exists()]
    for label, path in rows:
        print(label.ljust(34) + "".join(f"{x:10.1f}" for x in bands_db(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

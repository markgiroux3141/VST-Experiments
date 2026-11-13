"""A lossy codec's round trip (ffmpeg), so audio compared with a YouTube-sourced reference has
the same codec on both sides (ANALOG_MAGIC_FABLE.md AM1 / AM3)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf


def round_trip(x: np.ndarray, fs: int, codec: str = "opus160") -> np.ndarray:
    """x (mono or (n, 2)) through libopus at the named bit rate and back, at fs."""
    kbps = int(codec.removeprefix("opus"))
    with tempfile.TemporaryDirectory() as d:
        src, enc, dec = Path(d) / "x.wav", Path(d) / "x.opus", Path(d) / "y.wav"
        sf.write(src, np.asarray(x, np.float32), fs, subtype="FLOAT")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:a", "libopus",
                        "-b:a", f"{kbps}k", str(enc)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(enc), "-ar", str(fs),
                        "-c:a", "pcm_f32le", str(dec)], check=True)
        y, _ = sf.read(dec, dtype="float64", always_2d=x.ndim == 2)
    # Opus adds a pre-skip delay: line the output up with the input (whole samples).
    from varimu.magic.null import lag_of

    a = x if x.ndim == 1 else x.mean(axis=1)
    b = y if y.ndim == 1 else y.mean(axis=1)
    d, _ = lag_of(a, b, int(0.05 * fs))
    s = int(round(d))
    y = np.roll(y, -s, axis=0)
    return y[: len(x)]

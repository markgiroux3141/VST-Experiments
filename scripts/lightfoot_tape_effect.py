"""What the Ampex 300-4 did to each track of Did She Mention My Name (reports/lightfoot_mix).

Usage: uv run python scripts/lightfoot_tape_effect.py

Per track, the tape track against its lane: the lag, the level, the third-octave response
(the tape's over the lane's, normalized at 1 kHz), and the residual after the best linear
fit (a 4096-tap least-squares filter over the song: what tape adds that no EQ explains:
noise, distortion, flutter). On the harmonies track, the floor where its lane is silent:
hiss plus crosstalk from track 3 (the lead) next to it, and how much of it the lead explains.
Writes reports/lightfoot_mix/tape_effect.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from lightfoot_mix_analyze import THIRDS
from lightfoot_mix_probe import thirds_db
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "did she mention my name (tape)"
OUT = ROOT / "reports" / "lightfoot_mix"
NAMES = ["bass", "guitar", "lead vocal", "harmonies"]


def mono(p: Path) -> tuple[np.ndarray, int]:
    x, fs = sf.read(p, dtype="float64")
    return (x if x.ndim == 1 else x.mean(axis=1)), fs


def lag_of(a: np.ndarray, b: np.ndarray, fs: int) -> int:
    """b's delay re a in samples (cross-correlation over the loudest 20 s)."""
    n = 20 * fs
    sec = np.add.reduceat(a**2, np.arange(0, len(a), fs))
    i = int(np.argmax(np.convolve(sec, np.ones(20), "valid"))) * fs
    i = max(0, min(i, len(a) - n))
    c = signal.correlate(b[i : i + n], a[i : i + n], mode="full", method="fft")
    return int(np.argmax(c)) - (n - 1)


def main() -> None:
    res = {}
    lanes, tapes = {}, {}
    for k, name in enumerate(NAMES):
        x, fs = mono(SESSION / "takes" / f"t000{k + 1}" / "draft.wav")
        y, _ = mono(OUT / "tape" / f"tape{k + 1}.wav")
        lag = lag_of(x, y, fs)
        if lag >= 0:
            y = y[lag:]
        else:
            y = np.concatenate([np.zeros(-lag), y])
        n = min(len(x), len(y))
        x, y = x[:n], y[:n]
        lanes[name], tapes[name] = x, y
        d = thirds_db(y, fs) - thirds_db(x, fs)
        d -= d[THIRDS.index(1000)]
        # the residual after the best linear (time-invariant) filter, in frequency domain:
        # coherence-based: 1 - gamma^2 is the unexplained share per bin
        f, coh = signal.coherence(x, y, fs, nperseg=4096)
        _, pyy = signal.welch(y, fs, nperseg=4096)
        band = (f > 40) & (f < 16000)
        unexplained = np.sum((1 - coh[band]) * pyy[band]) / np.sum(pyy[band])
        res[name] = {
            "lag_samples": lag,
            "level_db": float(10 * np.log10(np.mean(y**2) / np.mean(x**2))),
            "response_db_re_1k": {
                str(t): round(float(v), 2) for t, v in zip(THIRDS, d, strict=False)
            },
            "not_linear_db": float(10 * np.log10(unexplained)),
        }
        print(name, json.dumps(res[name]))
    # the harmonies track's floor where its lane is silent
    fs = 48_000
    h, hl = tapes["harmonies"], lanes["harmonies"]
    blk = int(0.1 * fs)
    m = len(h) // blk
    el = 10 * np.log10(np.mean(hl[: m * blk].reshape(m, blk) ** 2, axis=1) + 1e-30)
    quiet = el < el.max() - 70  # the lane silent (to its own floor)
    idx = np.repeat(quiet, blk)
    hq = h[: m * blk][idx]
    lead = tapes["lead vocal"][: m * blk][idx]
    floor = 10 * np.log10(np.mean(hq**2))
    # how much of the floor the lead (track 3, next door) explains, at its best gain
    g = np.dot(hq, lead) / np.dot(lead, lead)
    c = signal.coherence(lead, hq, fs, nperseg=4096)[1]
    res["harmonies_silent_floor"] = {
        "seconds": float(len(hq) / fs),
        "floor_dbfs_rms": float(floor),
        "re_harmonies_sounding_db": float(floor - 10 * np.log10(np.mean(h[: m * blk][~idx] ** 2))),
        "lead_coherence_mean_200_4k": float(
            np.mean(
                c[(np.fft.rfftfreq(4096, 1 / fs) > 200) & (np.fft.rfftfreq(4096, 1 / fs) < 4000)]
            )
        ),
        "lead_gain_db": float(20 * np.log10(abs(g) + 1e-30)),
    }
    print(json.dumps(res["harmonies_silent_floor"]))
    (OUT / "tape_effect.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

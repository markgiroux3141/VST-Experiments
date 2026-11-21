"""What the sketches share: the rate, notes, seeded randomness, placing notes in a score,
and writing a loudness-matched pair (dry, and through the EMT 140 plate) with a
spectrogram."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from zlib import crc32

import numpy as np
from scipy import signal

FS = 48_000
"""The sketches' rate. Offline sketches, not the engine: 48 kHz keeps the per-sample Python
loops affordable (the project's 96 kHz is for circuits)."""

LUFS_TARGET = -20.0
"""Every sample is matched to this integrated loudness (the Hard rules' "loudness lies")."""

PLATE_WET = 0.3
"""The plate's share in <name>_plate.wav (its response energy-normalized)."""

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "reports" / "invented"


def hz(midi: float) -> float:
    """Equal temperament, A4 = 440 Hz."""
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note(name: str) -> int:
    """'C4', 'F#3', 'Bb2' -> MIDI number."""
    letter, rest = name[0], name[1:]
    n = NAMES[letter]
    while rest and rest[0] in "#b":
        n += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    return 12 * (int(rest) + 1) + n


def rng(seed: int, name: str) -> np.random.Generator:
    """A per-item stream (the Hard rules' seeding)."""
    return np.random.default_rng([seed, crc32(name.encode())])


def smooth_noise(g: np.random.Generator, n: int, cutoff_hz: float, fs: float = FS) -> np.ndarray:
    """Unit-rms noise low-passed at cutoff_hz (2nd-order Butterworth)."""
    w = g.standard_normal(n + 4096)
    sos = signal.butter(2, cutoff_hz / (fs / 2), output="sos")
    y = signal.sosfilt(sos, w)[4096:]
    return y / max(np.sqrt(np.mean(y * y)), 1e-30)


def envelope(n: int, on_s: float, off_s: float, attack_s: float, release_s: float) -> np.ndarray:
    """0..1: a raised-cosine rise at on_s over attack_s, a fall at off_s over release_s."""
    t = np.arange(n) / FS
    up = np.clip((t - on_s) / max(attack_s, 1e-9), 0.0, 1.0)
    down = np.clip(1.0 - (t - off_s) / max(release_s, 1e-9), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * np.minimum(up, down))


@dataclass(frozen=True)
class Note:
    start_s: float
    dur_s: float
    midi: float
    vel: float = 0.7  # 0..1


def place(
    score: Sequence[Note], render: Callable[[Note, int], np.ndarray], tail_s: float
) -> np.ndarray:
    """Independent voices: render(note, i) returns the note's audio from its start (any
    length); summed at their starts."""
    end = max(n.start_s + n.dur_s for n in score) + tail_s
    out = np.zeros(int(end * FS))
    for i, n in enumerate(score):
        y = render(n, i)
        k = int(round(n.start_s * FS))
        m = min(y.size, out.size - k)
        out[k : k + m] += y[:m]
    return out


def plate_response() -> np.ndarray:
    """The EMT 140 response scripts/drum_study.py caches (EMT140@1, 2.5 s at 500 Hz), at FS,
    energy-normalized. Empty when the cache is missing (run drum_study.py once)."""
    src = REPO / "cache" / "drums" / "emt140_t2.5_96000.npy"
    dst = REPO / "cache" / "invented" / f"emt140_t2.5_{FS}.npy"
    if dst.exists():
        return np.load(dst)
    if not src.exists():
        return np.zeros(0)
    h = signal.resample_poly(np.load(src), FS, 96_000)
    h /= np.sqrt(np.sum(h * h))
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.save(dst, h)
    return h


def loudness_gain(x: np.ndarray) -> float:
    import pyloudnorm

    lufs = pyloudnorm.Meter(FS).integrated_loudness(x)
    return 10.0 ** ((LUFS_TARGET - lufs) / 20.0)


def finish(name: str, take: str, x: np.ndarray, notes: dict | None = None) -> dict:
    """Writes reports/invented/<name>/<take>.wav (dry) and <take>_plate.wav, both at
    LUFS_TARGET, plus <take>.png (a spectrogram). Returns a summary."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import soundfile as sf

    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    x = np.asarray(x, dtype=float)
    if not np.all(np.isfinite(x)):
        raise ValueError(f"{name}/{take}: non-finite samples")
    x = signal.sosfilt(signal.butter(2, 20 / (FS / 2), "highpass", output="sos"), x)
    fade = int(0.02 * FS)
    x[-fade:] *= np.linspace(1, 0, fade)
    dry = x * loudness_gain(x)
    summary = {"take": take, "seconds": x.size / FS, "peak_dbfs_dry": 0.0}
    files = {"": dry}
    h = plate_response()
    if h.size:
        wet = signal.fftconvolve(x, h)[: x.size + int(2.5 * FS)]
        mix = np.pad(x, (0, wet.size - x.size)) + PLATE_WET * wet * np.sqrt(
            np.sum(x * x) / max(np.sum(wet * wet), 1e-30)
        )
        files["_plate"] = mix * loudness_gain(mix)
    for suffix, y in files.items():
        peak = float(np.max(np.abs(y)))
        summary[f"peak_dbfs{suffix or '_dry'}"] = 20 * np.log10(max(peak, 1e-12))
        if peak > 0.99:  # never clip a file: lower it and say so
            y = y * (0.99 / peak)
            summary[f"lowered{suffix or '_dry'}_db"] = 20 * np.log10(0.99 / peak)
        sf.write(out / f"{take}{suffix}.wav", y.astype(np.float32), FS, subtype="FLOAT")
    f, t, s = signal.spectrogram(dry, FS, nperseg=2048, noverlap=1536)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.pcolormesh(t, f, 10 * np.log10(s + 1e-14), vmin=-130, vmax=-40, shading="auto")
    ax.set_ylim(0, 8000)
    ax.set_xlabel("s")
    ax.set_ylabel("Hz")
    ax.set_title(f"{name}: {take}")
    fig.tight_layout()
    fig.savefig(out / f"{take}.png", dpi=90)
    plt.close(fig)
    if notes:
        summary.update(notes)
    return summary


def write_summary(name: str, takes: list[dict], seconds: float) -> None:
    out = OUT / name
    (out / "summary.json").write_text(
        json.dumps({"compute_s": round(seconds, 1), "takes": takes}, indent=2) + "\n"
    )


class Timer:
    def __enter__(self) -> Timer:
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *a: object) -> None:
        self.s = time.perf_counter() - self.t0

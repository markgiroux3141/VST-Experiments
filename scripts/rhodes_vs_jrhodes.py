"""The harp's single notes against a real Mk I's: jRhodes3d (docs/RHODES_PLAN.md, "Single notes:
jRhodes3d").

    uv run --extra fast --extra listen python scripts/rhodes_vs_jrhodes.py
        [--samples DIR] [--harps MK1_HARP@2 MK1_HARP@1] [--seconds 6]

jRhodes3d (Jeff Learman's 1977 Mark I Stage 73, recorded from the harp connector, its samples
CC-BY-NC-4.0, web: https://github.com/sfzinstruments/jlearman.jRhodes3d) is not in the repo:
download it into `real instrument samples/jrhodes3d_download/` (untracked) or pass --samples
(its mono folder of A_<midi>__<note>_<layer>.flac). Its caveats (its README): recorded through
an EQ (a treble boost and a low-mid scoop), noise removed, the layers level-normalized. So the
comparison trusts what an EQ can't change: decays, partial frequencies, pitch, and how the
harmonic balance changes from layer to layer.

Per note and layer, our harps play the same key at the velocity at the centre of that layer's
range in jRhodes3d's mapping (L5 1-47, L4 48-72, L3 73-95, L2 96-111, L1 112-127) through
circuitsim's medium (the harp's open-circuit EMF, no amp). Writes reports/rhodes/jrhodes/:
- summary.json: per note and layer, harmonics 1-8 re the strongest (0.05-0.35 s) and the
  fundamental's decay (dB/s, its band-pass envelope from 0.3 s), real and each harp's;
- audio/<note>_L<n>.wav: the real sample, then each harp's note, 0.6 s apart, each matched
  to -23 LUFS on its own (loudness lies), 44.1 kHz mono float32.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import circuitsim
import numpy as np
import soundfile as sf
from scipy import signal

from varimu.rhodes import compile as hc
from varimu.separation.metrics import match_loudness

ROOT = Path(__file__).parents[1]
SAMPLES = (
    ROOT
    / "real instrument samples"
    / "jrhodes3d_download"
    / "jlearman.jRhodes3d-master"
    / "jRhodes3d-mono"
)
OUT = ROOT / "reports" / "rhodes" / "jrhodes"
FS = 96000.0
OUT_FS = 44100
LAYER_VELOCITY = {1: 120, 2: 104, 3: 84, 4: 60, 5: 24}  # the centres of jRhodes3d's ranges
NH = 8


def note_hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12)


def from_onset(y: np.ndarray) -> np.ndarray:
    i0 = int(np.argmax(np.abs(y) > 0.05 * np.max(np.abs(y))))
    return y[i0:]


def harmonics_db(y: np.ndarray, fs: float, f0: float) -> list[float]:
    """Harmonics 1-8 re the strongest, over 0.05-0.35 s after the onset."""
    s = from_onset(y)[int(0.05 * fs) : int(0.35 * fs)]
    n = 1 << 20
    mag = np.abs(np.fft.rfft(s * np.hanning(s.size), n))
    fr = np.fft.rfftfreq(n, 1 / fs)
    h = np.array(
        [
            20 * np.log10(mag[(fr > k * f0 * 0.985) & (fr < k * f0 * 1.015)].max() + 1e-15)
            for k in range(1, NH + 1)
        ]
    )
    return (h - h.max()).round(1).tolist()


def decay_db_s(y: np.ndarray, fs: float, f0: float) -> float:
    """The fundamental's band-pass envelope's slope from 0.3 s to 45 dB below its peak."""
    y = from_onset(y)
    bw = min(0.25 * f0, 60.0)
    sos = signal.butter(2, [f0 - bw, f0 + bw], "bp", fs=fs, output="sos")
    e = np.abs(signal.hilbert(signal.sosfiltfilt(sos, y)))
    hop = int(0.01 * fs)
    n = e.size // hop * hop
    ed = 20 * np.log10(np.add.reduceat(e[:n], np.arange(0, n, hop)) / hop + 1e-12)
    t = np.arange(ed.size) * hop / fs
    floor = np.median(ed[-50:]) if ed.size > 100 else ed.min()
    peak = ed[t > 0.3].max()
    use = (t > 0.3) & (ed > max(floor + 10, peak - 45))
    return float(np.polyfit(t[use], ed[use], 1)[0]) if use.sum() >= 20 else float("nan")


def matched(x: np.ndarray, fs: float) -> np.ndarray:
    """Matched to -23 LUFS; a note too short for BS.1770's gates (the top keys die in a
    fraction of a second) is matched by its rms over its first 0.4 s to -23 dBFS instead."""
    with np.errstate(invalid="ignore"):
        y = match_loudness(x, fs)
    if np.all(np.isfinite(y)):
        return y
    rms = np.sqrt(np.mean(x[: int(0.4 * fs)] ** 2))
    return x * 10 ** (-23 / 20) / max(rms, 1e-15)


def harp_note(model: dict, midi: int, velocity: int, seconds: float) -> np.ndarray:
    el = {"name": "VHARP", "out": "h", "rate_hz": FS, "contact_rate_hz": 4 * FS, "model": model}
    n = int(seconds * FS) + 1
    steps = [(int(0.01 * FS), "on", midi, velocity), (n - int(0.3 * FS), "off", midi, 0)]
    emf, _, _ = circuitsim.harp_render(json.dumps(el), FS, n, steps)
    return np.asarray(emf)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", type=Path, default=SAMPLES)
    ap.add_argument("--harps", nargs="+", default=["MK1_HARP@2", "MK1_HARP@1"])
    ap.add_argument("--seconds", type=float, default=6.0)
    args = ap.parse_args()
    files = sorted(args.samples.glob("A_*.flac"))
    if not files:
        raise SystemExit(f"no jRhodes3d samples in {args.samples} (see this script's docstring)")
    models = {h: hc.load_data(h) for h in args.harps}
    (OUT / "audio").mkdir(parents=True, exist_ok=True)
    summary: dict = {"harps": args.harps, "layer_velocity": LAYER_VELOCITY, "notes": {}}
    gap = np.zeros(int(0.6 * OUT_FS))
    for path in files:
        m = re.match(r"A_(\d+)__(\w+?)_(\d)$", path.stem)
        midi, name, layer = int(m.group(1)), m.group(2), int(m.group(3))
        f0 = note_hz(midi)
        real, fs_r = sf.read(path)
        real = real if real.ndim == 1 else real.mean(axis=1)
        real = from_onset(real)[: int(args.seconds * fs_r)]
        row = {
            "real": {
                "harmonics_db": harmonics_db(real, fs_r, f0),
                "decay_db_s": decay_db_s(real, fs_r, f0),
            }
        }
        seq = [matched(signal.resample_poly(real, OUT_FS, int(fs_r)), OUT_FS), gap]
        vel = LAYER_VELOCITY[layer]
        for h, model in models.items():
            y = harp_note(model, midi, vel, args.seconds)
            row[h] = {
                "velocity": vel,
                "peak_v": float(np.max(np.abs(y))),
                "harmonics_db": harmonics_db(y, FS, f0),
                "decay_db_s": decay_db_s(y, FS, f0),
            }
            seq += [matched(signal.resample_poly(from_onset(y), OUT_FS, int(FS)), OUT_FS), gap]
        audio = np.concatenate(seq)
        audio *= min(1.0, 0.89 / np.max(np.abs(audio)))
        wav = OUT / "audio" / f"{midi:03d}_{name}_L{layer}.wav"
        sf.write(wav, audio.astype(np.float32), OUT_FS, subtype="FLOAT")
        summary["notes"].setdefault(f"{midi} {name}", {})[f"L{layer}"] = row
        cols = [
            f"{k}: " + " ".join(f"{x:.0f}" for x in v["harmonics_db"][:6]) for k, v in row.items()
        ]
        print(f"{name} L{layer} (v{vel}): " + " | ".join(cols), flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

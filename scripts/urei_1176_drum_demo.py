"""Drums through the 1176 (DEVICE_BUILDER_PLAN.md B12's done-when: a drum loop printed):
a bar sequenced from the user's sample kit, looped, through config/circuits/urei_1176.yaml at
a few classic settings.

    uv run --extra fast --extra listen python scripts/urei_1176_drum_demo.py
        [--seconds 8] [--bpm 96] [--loop FILE] [--quality draft|production]

writes reports/urei_1176/drums/: drums_dry.wav, one print per preset (drums_<preset>.wav, the
1176's output) and its loudness-matched copy (drums_<preset>_matched.wav, at the dry's
integrated loudness: "loudness lies"), and drums.json (the samples used, the settings, the
gain reduction per preset, the render's speed). Mono float32 at 96 kHz on the circuit's full
scale (17.36 V peak = 0 dBFS in and out).

The kit: the first file (sorted by name) of samples/drums/{kick, snare, hihat_closed}
(samples/README.md; git-ignored, the user's library), a funk bar: kick on 1, the "and" of
2 and on 3, snare on 2 and 4, closed hats in eighths. Without samples/ a synthetic kit
stands in (a swept sine kick, a noise-and-tone snare, a high-passed noise hat). --loop FILE
plays that file instead (any WAV, looped to --seconds).

Gain reduction per preset is measured against the unit's own gain below threshold (the
same drums 40 dB quieter): the envelope ratio in 5 ms blocks.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, resample_poly, sosfilt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varimu.circuit import builder  # noqa: E402
from varimu.circuit.spec import load_circuit, resolve  # noqa: E402
from varimu.sim import fast, io  # noqa: E402

OUT = ROOT / "reports" / "urei_1176" / "drums"
SAMPLES = ROOT / "samples" / "drums"
FS = 96000
FULL_SCALE_V = 17.36
DRUMS_PEAK_DBFS = -12.0
# name: panel (the circuit file's controls): a moderate 4:1, and 20:1 with everything fast.
PRESETS = {
    "4to1": {"ratio": 4, "attack": 0.6, "release": 0.7, "input_atten_db": 20.0, "output": 0.25},
    "20to1_fast": {
        "ratio": 20,
        "attack": 1.0,
        "release": 1.0,
        "input_atten_db": 12.0,
        "output": 0.5,
    },  # fmt: skip
}


def read_mono(path: Path) -> np.ndarray:
    import soundfile

    x, fs = soundfile.read(str(path), always_2d=True)
    x = x.mean(axis=1)
    if fs != FS:
        g = np.gcd(int(fs), FS)
        x = resample_poly(x, FS // g, int(fs) // g)
    return x


def first(category: str) -> Path | None:
    d = SAMPLES / category
    files = sorted(d.glob("*.wav")) if d.is_dir() else []
    return files[0] if files else None


def synthetic_kit(rng: np.random.Generator) -> dict[str, np.ndarray]:
    t = np.arange(int(0.4 * FS)) / FS
    f = 50.0 + 110.0 * np.exp(-t / 0.03)
    kick = np.sin(2 * np.pi * np.cumsum(f) / FS) * np.exp(-t / 0.15)
    hp = butter(4, 7000, "highpass", fs=FS, output="sos")
    bp = butter(2, [1500, 6000], "bandpass", fs=FS, output="sos")
    snare = 0.6 * sosfilt(bp, rng.standard_normal(len(t))) * np.exp(-t / 0.08)
    snare += 0.5 * np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)
    hat = 0.4 * sosfilt(hp, rng.standard_normal(len(t))) * np.exp(-t / 0.025)
    return {"kick": kick, "snare": snare, "hihat_closed": hat}


def sequence(kit: dict[str, np.ndarray], bpm: float, n: int) -> np.ndarray:
    step = 60.0 / bpm / 2  # eighths
    hits = {"kick": [0, 3, 4], "snare": [2, 6], "hihat_closed": list(range(8))}
    gains = {"kick": 1.0, "snare": 0.9, "hihat_closed": 0.35}
    bar = int(round(8 * step * FS))
    y = np.zeros(n)
    for start in range(0, n, bar):
        for name, steps in hits.items():
            s = kit[name] / np.max(np.abs(kit[name])) * gains[name]
            for k in steps:
                a = start + int(round(k * step * FS))
                m = min(len(s), n - a)
                if m > 0:
                    y[a : a + m] += s[:m]
    return y


def env_db(y: np.ndarray, block: int = int(0.005 * FS)) -> np.ndarray:
    m = len(y) // block
    return 20 * np.log10(np.sqrt(np.mean(y[: m * block].reshape(m, block) ** 2, axis=1)) + 1e-12)


def write(name: str, volts: np.ndarray) -> None:
    wavfile.write(OUT / name, FS, (volts / FULL_SCALE_V).astype(np.float32))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--bpm", type=float, default=96.0)
    ap.add_argument("--loop", type=Path, default=None, help="a drum loop WAV to play instead")
    ap.add_argument("--quality", default="draft", choices=("draft", "production"))
    a = ap.parse_args()
    from varimu.separation.metrics import loudness_lufs

    OUT.mkdir(parents=True, exist_ok=True)
    n = int(FS * a.seconds)
    used: dict[str, str] = {}
    if a.loop is not None:
        one = read_mono(a.loop)
        x = np.tile(one, n // len(one) + 1)[:n]
        used["loop"] = str(a.loop)
    else:
        kit = {}
        for cat in ("kick", "snare", "hihat_closed"):
            p = first(cat)
            if p is not None:
                kit[cat] = read_mono(p)
                used[cat] = p.relative_to(ROOT).as_posix()
        if len(kit) < 3:
            kit = synthetic_kit(np.random.default_rng(1176))
            used = {"kit": "synthetic (no samples/drums)"}
        x = sequence(kit, a.bpm, n)
    x *= FULL_SCALE_V * 10 ** (DRUMS_PEAK_DBFS / 20) / np.max(np.abs(x))
    write("drums_dry.wav", x)
    dry_lufs = loudness_lufs(x / FULL_SCALE_V, FS)

    spec = load_circuit(ROOT / "config" / "circuits" / "urei_1176.yaml")
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality=a.quality)
    if a.quality == "draft":
        st = dataclasses.replace(st, newton_reltol=1e-5, newton_vntol=1e-5)
    info: dict = {"samples": used, "bpm": a.bpm, "quality": a.quality, "presets": {}}
    for name, panel in PRESETS.items():
        q = dict(resolve(spec))
        q.update(panel)
        ir = builder.build(spec, q).ir
        t0 = time.time()
        y = np.asarray(fast.run_transient(ir, x, settings=st).vectors["v(out)"])
        took = time.time() - t0
        ref = np.asarray(fast.run_transient(ir, x * 0.01, settings=st).vectors["v(out)"]) * 100
        gr = env_db(ref) - env_db(y)
        loud = env_db(ref) > np.max(env_db(ref)) - 30
        write(f"drums_{name}.wav", y)
        out_lufs = loudness_lufs(y / FULL_SCALE_V, FS)
        write(f"drums_{name}_matched.wav", y * 10 ** ((dry_lufs - out_lufs) / 20))
        info["presets"][name] = {
            "panel": panel,
            "gain_reduction_db": {
                "peak": round(float(np.max(gr[loud])), 2),
                "mean_while_playing": round(float(np.mean(gr[loud])), 2),
            },
            "lufs": {"dry": round(dry_lufs, 2), "out": round(out_lufs, 2)},
            "out_peak_dbfs": round(float(20 * np.log10(np.max(np.abs(y)) / FULL_SCALE_V)), 2),
            "render_s": round(took, 1),
            "audio_s": a.seconds,
        }
        print(name, json.dumps(info["presets"][name]))
    (OUT / "drums.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

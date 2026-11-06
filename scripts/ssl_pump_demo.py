"""The keyed SSL bus compressor pumping (DEVICE_BUILDER_PLAN.md B11's done-when: the user
hears the pump): a held sawtooth riff keyed by a four-on-the-floor kick, KEY EXT.

    uv run --extra fast python scripts/ssl_pump_demo.py [--seconds 8] [--ratio 10]
        [--release 0] [--threshold 0.5]

writes reports/ssl_bus_comp/pump/: saw_dry.wav, kick.wav, saw_ducked.wav (the SSL's
output), mix_dry.wav and mix_pumped.wav (the kick added back), and pump.json (settings,
the gain reduction's depth per beat, the render's speed). Mono float32 at 96 kHz, the
project's full scale (13.8 V peak = 0 dBFS). Rendered at the draft with Newton at 1e-5
(the app's for this device). Synthetic material only (no samples): a 128 BPM sawtooth
riff and a pitch-swept sine kick.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varimu.circuit import builder  # noqa: E402
from varimu.circuit.spec import load_circuit, resolve  # noqa: E402
from varimu.sim import fast, io  # noqa: E402

OUT = ROOT / "reports" / "ssl_bus_comp" / "pump"
FS = 96000
FULL_SCALE_V = 13.8
BPM = 128.0


def saw_riff(n: int) -> np.ndarray:
    """A held two-note sawtooth riff (A2 / C3, an eighth each), band-limited by summing
    harmonics below 12 kHz, 1.4 V peak."""
    t = np.arange(n) / FS
    eighth = 60.0 / BPM / 2
    f = np.where((t // eighth) % 2 == 0, 110.0, 130.81)
    phase = 2 * np.pi * np.cumsum(f) / FS
    y = np.zeros(n)
    for k in range(1, 109):
        y += np.where(f * k < 12000, np.sin(k * phase) / k, 0.0)
    return 1.4 * y / np.max(np.abs(y))


def kick(n: int) -> np.ndarray:
    """A four-on-the-floor sine kick: 150 -> 48 Hz in 40 ms, 180 ms decay, 4 V peak."""
    t = np.arange(n) / FS
    beat = 60.0 / BPM
    tb = t % beat
    f = 48.0 + 102.0 * np.exp(-tb / 0.04)
    ph = 2 * np.pi * np.cumsum(f) / FS
    ph -= ph[(t // beat * beat * FS).astype(int).clip(0, n - 1)]
    return 4.0 * np.sin(ph) * np.exp(-tb / 0.18) * np.clip(tb / 0.002, 0, 1)


def write(name: str, volts: np.ndarray) -> None:
    wavfile.write(OUT / name, FS, (volts / FULL_SCALE_V).astype(np.float32))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--ratio", type=int, default=10, choices=(2, 4, 10))
    ap.add_argument("--attack", type=int, default=0, help="position 0-5 (0.1 .. 30 ms)")
    ap.add_argument("--release", type=int, default=0, help="position 0-4 (0.1 .. 1.2 s, AUTO)")
    ap.add_argument("--threshold", type=float, default=0.5)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    n = int(FS * a.seconds)
    saw, kk = saw_riff(n), kick(n)
    spec = load_circuit(ROOT / "config" / "circuits" / "ssl_bus_comp.yaml")
    q = dict(resolve(spec))
    q.update(key_mode=1, ratio=a.ratio, attack=a.attack, release=a.release, threshold=a.threshold)
    c = builder.build(spec, q)
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    st = dataclasses.replace(st, newton_reltol=1e-5, newton_vntol=1e-5)
    t0 = time.time()
    r = fast.run_transient(c.ir, saw, controls={"key": kk}, settings=st)
    took = time.time() - t0
    y = np.asarray(r.vectors["v(out)"])
    gr_db = np.asarray(r.vectors["v(vb)"]) * 8.46  # the program VCA's law here (tests)
    write("saw_dry.wav", saw)
    write("kick.wav", kk)
    write("saw_ducked.wav", y)
    write("mix_dry.wav", 0.5 * (saw + kk))
    write("mix_pumped.wav", 0.5 * (y + kk))
    beat = int(FS * 60 / BPM)
    depths = [float(gr_db[i : i + beat].max()) for i in range(beat, n - beat, beat)]
    info = {
        "settings": {
            "ratio": a.ratio,
            "attack_position": a.attack,
            "release_position": a.release,
            "threshold": a.threshold,
            "key_mode": "EXT",
            "quality": "draft, Newton 1e-5",
        },  # fmt: skip
        "bpm": BPM,
        "gain_reduction_peak_db_per_beat": [round(d, 2) for d in depths],
        "render_s": round(took, 1),
        "audio_s": a.seconds,
    }
    (OUT / "pump.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(info, indent=1))
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

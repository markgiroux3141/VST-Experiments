"""The reverbs' STEREO (docs/REVERB_PLAN.md, "Stereo") -> reports/reverb/stereo/.

    uv run --extra fast --extra listen python scripts/stereo_reverb_report.py
        [--only plate_reverb foil_reverb fender_6g15] [--quality draft-1x]

Per device, a short noise burst (60 ms, -12 dBFS, faded) at the input, fully wet (the
6G15's MIXER at 1), rendered with STEREO off and on:
- the two sides' levels and correlation over the tail, broadband and per octave band (the
  EMT 140 TS's brochure: its two pickups' outputs "entirely uncorrelated");
- the left side against the mono unit's output (the same pickup and amplifier; they differ
  only by the second amplifier's load on the shared supply);
- the render's speed with STEREO off and on;
and the stereo output as a WAV (`<device>.wav`, 2 channels) beside summary.json.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt

from varimu.circuit import builder, spec
from varimu.sim import fast
from varimu.sim.io import TransientSettings, full_scale

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "reverb" / "stereo"
DEVICES = {
    "plate_reverb": {},
    "foil_reverb": {},
    "fender_6g15": {"mixer": 1.0},
}
BANDS_HZ = (125, 250, 500, 1000, 2000, 4000, 8000)


def burst(fs: int, seconds: float) -> np.ndarray:
    rng = np.random.default_rng([1, 6015])
    n = int(0.06 * fs)
    x = np.zeros(int(seconds * fs))
    x[:n] = rng.standard_normal(n) * np.hanning(n) * 10 ** (-12 / 20)
    return x


def corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / math.sqrt(float(np.dot(a, a) * np.dot(b, b)) + 1e-300))


def db(a: np.ndarray) -> float:
    return 10 * math.log10(float(np.mean(a * a)) + 1e-300)


def measure(name: str, wet: dict, quality: str, seconds: float) -> dict:
    c = spec.load_circuit(spec.circuit_path(name))
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    fs = st.sample_rate
    x = burst(fs, seconds)
    v_in = full_scale(st, c)[0]
    runs = {}
    for label, on in (("mono", 0), ("stereo", 1)):
        ir = builder.build(c, {**wet, "stereo": on}).ir
        t0 = time.perf_counter()
        r = fast.run_transient(ir, x * v_in, settings=st)
        runs[label] = (r, time.perf_counter() - t0)
    rs, wall_s = runs["stereo"]
    left, right = (np.asarray(rs.vectors[k]) for k in ("v(out)", "v(out_r)"))
    mono = np.asarray(runs["mono"][0].vectors["v(out)"])
    # The tail: from the burst's end on, the outputs' DC removed (their coupling settles).
    hp = butter(2, 20.0, "highpass", fs=fs, output="sos")
    left, right, mono = (sosfiltfilt(hp, v)[int(0.1 * fs) :] for v in (left, right, mono))
    bands = {}
    for f in BANDS_HZ:
        sos = butter(
            4, [f / math.sqrt(2), min(f * math.sqrt(2), 0.45 * fs)], "bandpass", fs=fs, output="sos"
        )
        lb, rb = sosfiltfilt(sos, left), sosfiltfilt(sos, right)
        bands[str(f)] = {
            "right_re_left_db": round(db(rb) - db(lb), 2),
            "corr": round(corr(lb, rb), 3),
        }
    peak = max(np.max(np.abs(left)), np.max(np.abs(right)), 1e-12)
    stereo = (np.stack([left, right], axis=1) / peak * 0.5).astype("<f4")
    sf.write(OUT / f"{name}.wav", stereo, fs, subtype="FLOAT")
    return {
        "right_re_left_db": round(db(right) - db(left), 2),
        "corr": round(corr(left, right), 3),
        "left_vs_mono_db": round(db(left - mono) - db(mono), 1),
        "bands": bands,
        "wall_s_mono": round(runs["mono"][1], 2),
        "wall_s_stereo": round(wall_s, 2),
        "seconds": seconds,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=list(DEVICES))
    ap.add_argument("--quality", default="production", help="a sim_settings quality")
    ap.add_argument("--seconds", type=float, default=3.0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "summary.json"
    summary = json.loads(path.read_text()) if path.is_file() else {}
    for name in args.only:
        res = measure(name, DEVICES[name], args.quality, args.seconds)
        summary[name] = {**res, "quality": args.quality}
        print(name, json.dumps(res, indent=1))
    path.write_text(json.dumps(summary, indent=1) + "\n")


if __name__ == "__main__":
    main()

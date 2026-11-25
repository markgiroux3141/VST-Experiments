"""The tube synth's STRESS control through the engine (docs/PART_NOISE_PLAN.md): the
scenarios of scripts/synth_iron.py rendered in one pass with the circuit's own Barkhausen
parts (circuitsim's barkhausen.rs reading each filter core's accepted state), at the draft
quality Play plays, with the app's partition.

    uv run --extra listen --extra fast python scripts/synth_iron_engine.py [--only riff ...]
        [--stress 0 1 10 100 300 1000]

-> reports/part_noise/synth_iron/engine/: audio/<scenario>/stress_<N>.wav (loudness-matched,
-23 LUFS), audio/crackle_only/<scenario>_stress_<N>.wav (STRESS N minus STRESS 0, one gain per
scenario), summary.json (the crackle re the note, to compare with the offline prototype's).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth_iron as proto  # noqa: E402  (the scenarios, keys and settings)

from varimu.circuit import builder, spec  # noqa: E402
from varimu.sim import fast, io  # noqa: E402

OUT = proto.OUT_ROOT / "engine"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=list(proto.SCENARIOS))
    ap.add_argument("--stress", nargs="*", type=float, default=[0, 1, 10, 100, 300, 1000])
    args = ap.parse_args()
    import pyloudnorm
    import soundfile as sf

    fs = io.load_sim_settings().sample_rate
    st = proto.settings()
    s = spec.load_circuit(proto.SYNTH)
    t0 = time.perf_counter()

    def run(item):
        name, stress = item
        panel, notes, legato, dur, _ = proto.SCENARIOS[name]
        n = int(dur * fs)
        t = np.arange(n) / fs
        gate, pitch = proto.keys(t, notes, legato)
        ctl = {"gate": gate, "pitch": pitch, "key": np.zeros(n), "pressure": np.zeros(n),
               "pitch2": np.zeros(n)}  # fmt: skip
        ir = builder.build_ir(s, spec.resolve(s, {**panel, "stress": stress}), cores="ja")
        return item, fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl).vectors

    items = [(nm, x) for nm in args.only for x in sorted(set([0.0, *args.stress]))]
    with ThreadPoolExecutor(2) as pool:
        res = dict(pool.map(run, items))
    print(f"renders: {time.perf_counter() - t0:.0f} s", flush=True)

    meter = pyloudnorm.Meter(fs)

    def write(path: Path, y: np.ndarray) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        peak = float(np.max(np.abs(y)))
        if peak > 0.99:
            y = y * (0.99 / peak)
        sf.write(path, y.astype(np.float32), fs, subtype="FLOAT")

    summary = {"scenarios": {}}
    for name in args.only:
        prog = res[(name, 0.0)]["v(out)"]
        rms = float(np.sqrt(np.mean(prog**2)))
        stresses = [x for x in sorted(set(args.stress)) if x > 0]
        diffs = {x: res[(name, x)]["v(out)"] - prog for x in stresses}
        gain = 10 ** (-1 / 20) / max(max(float(np.max(np.abs(d))) for d in diffs.values()), 1e-30)
        entry = {}
        for x in sorted(set([0.0, *args.stress])):
            y = res[(name, x)]["v(out)"] / proto.FULL_SCALE_V
            write(OUT / "audio" / name / f"stress_{x:g}.wav",
                  y * 10 ** ((proto.LUFS_TARGET - meter.integrated_loudness(y)) / 20))  # fmt: skip
            if x > 0:
                d = diffs[x]
                write(OUT / "audio" / "crackle_only" / f"{name}_stress_{x:g}.wav", d * gain)
                entry[f"{x:g}"] = 20 * math.log10(max(float(np.sqrt(np.mean(d**2))), 1e-30) / rms)
        summary["scenarios"][name] = {"crackle_re_note_db": entry}
        print(name, {k: round(v, 1) for k, v in entry.items()})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

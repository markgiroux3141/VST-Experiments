"""The Minimoog voice with its circuit noise on (MINIMOOG_BACKLOG.md "Authenticity first", item 5):
what the parts' own noise (B5's Johnson noise, NH2's transistor shot and channel noise; no flicker:
config/device_noise.yaml has no sourced KF yet) does to oscillator 1's period, and what it costs.

The voice at draft-1x, partitioned as the app plays it (oscillator 1 an island at 96 kHz on its
event kernels), a key held from 0.2 s; oscillator 1's ramp probed and its falling crossings of 2.5 V
interpolated: each period's deviation from the run's mean in cents (rms: the cycle-to-cycle
jitter), and the slow wander (the 50 ms means' spread). Off against on, at a low, a middle and a
high key, with the wall time of each run.

    uv run --extra fast python scripts/minimoog_noise_jitter.py [--notes 33 57 81] [--seconds 2]

Writes reports/minimoog/units/noise_jitter.json.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import minimoog_gate_check as gc  # noqa: E402
import minimoog_vcf_study as vs  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.circuit.ir import VoltageProbe  # noqa: E402
from varimu.config import CONFIG_DIR  # noqa: E402
from varimu.sim import fast  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = CONFIG_DIR / "circuits" / "minimoog_voice.yaml"
OUT = ROOT / "reports" / "minimoog" / "units"


def crossings(x: np.ndarray, level: float) -> np.ndarray:
    k = np.nonzero((x[:-1] >= level) & (x[1:] < level))[0]
    return k + (x[k] - level) / (x[k] - x[k + 1])


def run(note: int, seconds: float, noise) -> dict:
    s = spec.load_circuit(SRC)
    ir = builder.build_ir(s, spec.resolve(s, {}), "linear", events=True, noise=noise)
    ir = dataclasses.replace(ir, probes=(VoltageProbe("o1_ramp"), VoltageProbe("out")))
    st = dataclasses.replace(
        vs.settings("draft-1x"),
        newton_reltol=gc.VOICE_NEWTON,
        newton_vntol=gc.VOICE_NEWTON,
        partition=gc.VOICE_PARTITION,
        partition_coupling="hold",
        hard_step_iterations=gc.VOICE_HARD_STEP,
    )
    fs = st.sample_rate
    n = int(seconds * fs)
    off, on = gc.gate_levels(s, "gate")
    gate = np.full(n, off)
    gate[int(0.2 * fs) :] = on
    key = np.full(n, gc.key_volts(s, note))
    t0 = time.time()
    r = fast.run_transient(ir, np.zeros(n), settings=st, controls={"key": key, "gate": gate})
    wall = time.time() - t0
    ramp = np.asarray(r.vectors["v(o1_ramp)"])
    t = crossings(ramp[int(0.4 * fs) :], 2.5)
    per = np.diff(t)
    c = 1200 * np.log2(per / per.mean())
    # the slow wander: periods averaged over 50 ms windows
    w = max(1, int(round(0.05 * fs / per.mean())))
    means = [per[i : i + w].mean() for i in range(0, len(per) - w + 1, w)]
    wander = 1200 * np.log2(np.array(means) / per.mean())
    out = np.asarray(r.vectors["v(out)"])[int(0.6 * fs) :]
    return {
        "hz": float(fs / per.mean()),
        "periods": len(per),
        "jitter_cents_rms": float(np.sqrt(np.mean(c**2))),
        "wander_cents_pp": float(np.ptp(wander)) if len(wander) > 1 else 0.0,
        "out_rms_v": float(np.sqrt(np.mean(out**2))),
        "wall_s": wall,
        "realtime_factor": wall / seconds,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--notes", type=int, nargs="+", default=[33, 57, 81])
    ap.add_argument("--seconds", type=float, default=2.0)
    a = ap.parse_args()
    rep: dict = {"seconds": a.seconds, "notes": {}}
    for note in a.notes:
        row = {"off": run(note, a.seconds, False), "on": run(note, a.seconds, 1)}
        rep["notes"][note] = row
        print(note, json.dumps(row), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "noise_jitter.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"wrote {OUT / 'noise_jitter.json'}")


if __name__ == "__main__":
    main()

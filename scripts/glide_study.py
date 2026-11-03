"""Tube synth, SYNTH_IDEAS.md #1: GLIDE measured (config/circuits/tube_synth.yaml).

Pitch steps up and down with a key held, at draft with the native app's partition, at a
few GLIDE settings. Each step reports the time until the pitch (the per-cycle pitch
averaged over vco_study's 50 ms) is halfway to the new note in cents, and the time until
it stays within 10 cents of it (vco_study's glide measure). Without `glide` in the
circuit (before #1) only GLIDE 0 runs: the baseline.

    uv run --extra fast python scripts/glide_study.py [--glide 0 0.5 1] [--out FILE]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io
from varimu.synth import vco

CIRCUIT = CONFIG_DIR / "circuits" / "tube_synth.yaml"
PARTITION = (
    "resonance",
    "|",
    "input",
    "filter",
    "cutoff",
    "|",
    "envelope",
    "|",
    "ring",
    "|",
    "oscillator",
    "pitch",
    "|",
    "lfo",
    "|",
    "power supply",
    "bias supply",
)  # the native app's (panel.rs)
KEY_DOWN_V = -1.0
STEPS = {  # (from, to) pitch volts: an octave-ish up and down, and big jumps
    "up": (-20.0, -15.0),
    "down": (-15.0, -20.0),
    "big_up": (-23.0, -5.0),
    "big_down": (-5.0, -23.0),
}
STEP_AT_S = 0.4
DUR_S = 2.4
SMOOTH_S = 0.05


def run(sets: dict, step: tuple[float, float]) -> dict:
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("o_t"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(DUR_S * fs)
    pitch = np.full(n, step[0])
    pitch[int(STEP_AT_S * fs) :] = step[1]
    v = fast.run_transient(
        ir,
        np.zeros(n),
        settings=st,
        controls={
            "gate": np.full(n, KEY_DOWN_V),
            "pitch": pitch,
            "key": np.zeros(n),
            "pressure": np.zeros(n),
            "pitch2": np.zeros(n),
        },
    ).vectors["v(o_t)"]
    ts, fc = vco.cycle_frequencies(v, fs)
    sm = vco.smoothed(ts, fc, SMOOTH_S)
    f0 = float(np.median(fc[(ts > 0.1) & (ts < STEP_AT_S - 0.02)]))
    f1 = float(np.median(fc[ts > DUR_S - 0.4]))
    after = ts > STEP_AT_S
    gone = vco.cents(sm, f0) / vco.cents(f1, f0)  # 0 at the old note, 1 at the new
    half = after & (gone >= 0.5)
    off = after & (np.abs(vco.cents(sm, f1)) > 10.0)
    return {
        "from_hz": round(f0, 2),
        "to_hz": round(f1, 2),
        "half_s": round(float(ts[half].min() - STEP_AT_S), 3) if half.any() else None,
        "within_10_cents_s": round(float(ts[off].max() - STEP_AT_S), 3) if off.any() else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--glide", nargs="*", type=float, default=[0.0, 0.25, 0.5, 0.75, 1.0])
    ap.add_argument("--out", type=Path, default=Path("reports/tube_synth/glide.json"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    has_glide = "glide" in spec.load_circuit(CIRCUIT).controls
    glides = a.glide if has_glide else [0.0]
    jobs = [(g, k) for g in glides for k in STEPS]

    def one(job):
        g, k = job
        return run({"glide": g} if has_glide else {}, STEPS[k])

    with ThreadPoolExecutor(a.workers) as ex:
        got = list(ex.map(one, jobs))
    res: dict = {"has_glide": has_glide, "steps_v": STEPS, "glide": {}}
    for (g, k), r in zip(jobs, got, strict=True):
        res["glide"].setdefault(str(g), {})[k] = r
        print(f"glide {g:4.2f} {k:8s} {r}", flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

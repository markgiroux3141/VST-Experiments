"""Tube synth, SYNTH_IDEAS.md #2: KEY TRACK measured (config/circuits/tube_synth.yaml).

The filter's law: with a key held and the oscillator cut from the mixer (`r_mix_osc_ohm`
1e12), a multitone at the external input (tones of 3 mV at 30 + 120 k Hz, random phases:
off every harmonic of the 60 Hz mains, so a lock-in over whole 30 Hz periods rejects the
supply ripple) is read at the filter node `f` with RESONANCE 0. "Cutoff" is the -10 dB
frequency against the gain below 300 Hz (S5's measure: the -3 dB point is confused by a
shelf at the top). Per CUTOFF setting (or `--set` overrides) it reports V4's grid (`g4`)
and the cutoff at each key (`--notes`, MIDI: the key string's volts from the circuit file's
`key_*` values, as varimu-app's panel::KeyString; the pitch held at -15 V, the oscillator
being cut). Before KEY TRACK the circuit had no key string: its law alone.

    uv run --extra fast python scripts/keytrack_study.py [--cutoff 0 0.5 1]
        [--set key_track=1] [--notes 36 48 60 72 84] [--pressure-v 15] [--out FILE]
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
TONE_V = 3e-3
TONES_HZ = 30.0 + 120.0 * np.arange(0, 84)  # 30 Hz to 9.99 kHz
DUR_S = 1.5
READ_S = 1.0  # the lock-in's window, the run's last second (30 periods of 30 Hz)


def key_v(s: spec.CircuitSpec, note: int) -> float:
    """The key string's volts at MIDI `note` (panel::KeyString)."""
    val = {
        k: float(s.values[f"key_{k}"]["value"])
        for k in ("v_per_semitone", "ref_note", "min_v", "max_v")
    }
    v = (note - val["ref_note"]) * val["v_per_semitone"]
    return min(max(v, val["min_v"]), val["max_v"])


def run(sets: dict, note: int, pressure_v: float = 0.0) -> dict:
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(
        s, spec.resolve(s, {"resonance": 0.0, "r_mix_osc_ohm": 1e12, **sets}), cores="ja"
    )
    ir = dataclasses.replace(ir, probes=(VoltageProbe("f"), VoltageProbe("g4")))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(DUR_S * fs)
    t = np.arange(n) / fs
    ph = np.random.default_rng(1).uniform(0, 2 * np.pi, len(TONES_HZ))
    x = TONE_V * np.sin(2 * np.pi * TONES_HZ[:, None] * t[None, :] + ph[:, None]).sum(0)
    # Faded in over 0.1 s (the run starts at the DC point with its first sample).
    x *= np.clip(t / 0.1, 0, 1)
    v = fast.run_transient(
        ir,
        x,
        settings=st,
        controls={
            "gate": np.full(n, KEY_DOWN_V),
            "pitch": np.full(n, -15.0),
            **({"key": np.full(n, key_v(s, note))} if "key" in dict(s.cv_inputs) else {}),
            **({"pressure": np.full(n, pressure_v)} if "pressure" in dict(s.cv_inputs) else {}),
            **({"pitch2": np.zeros(n)} if "pitch2" in dict(s.cv_inputs) else {}),
        },
    ).vectors
    k = slice(n - int(READ_S * fs), n)
    tt = t[k]
    basis = np.exp(-2j * np.pi * TONES_HZ[:, None] * tt[None, :])
    hf = (basis @ (v["v(f)"][k] - v["v(f)"][k].mean())) / (basis @ x[k])
    db = 20 * np.log10(np.abs(hf))
    ref = db[TONES_HZ < 300].max()
    below = np.nonzero(db < ref - 10.0)[0]
    below = below[TONES_HZ[below] > 100]
    if len(below):
        i = below[0]
        # Interpolated in log frequency between the tones either side of -10 dB.
        f0, f1, d0, d1 = TONES_HZ[i - 1], TONES_HZ[i], db[i - 1] - ref, db[i] - ref
        cut = float(np.exp(np.log(f0) + (-10 - d0) / (d1 - d0) * np.log(f1 / f0)))
    else:
        cut = float("nan")
    return {
        "g4_v": round(float(np.mean(v["v(g4)"][k])), 3),
        "cutoff_hz": round(cut, 1),
        "response_db": [round(float(d - ref), 2) for d in db],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cutoff", nargs="*", type=float, default=list(np.linspace(0, 1, 11)))
    ap.add_argument("--notes", nargs="*", type=int, default=[60])
    ap.add_argument("--pressure-v", type=float, default=0.0, help="the aftertouch strip's volts")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    ap.add_argument("--out", type=Path, default=Path("reports/tube_synth/keytrack/law.json"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    sets = {k: float(v) for k, v in (kv.split("=", 1) for kv in a.set)}
    jobs = [(round(c, 4), m) for c in a.cutoff for m in a.notes]
    with ThreadPoolExecutor(a.workers) as ex:
        got = list(ex.map(lambda j: run({**sets, "cutoff": j[0]}, j[1], a.pressure_v), jobs))
    rows = []
    for (c, p), r in zip(jobs, got, strict=True):
        rows.append({"cutoff": c, "note": p, **r})
        print(f"cutoff {c:5.2f} note {p:3d}: g4 {r['g4_v']:8.3f} V  {r['cutoff_hz']:8.1f} Hz")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(
        json.dumps({"sets": sets, "tones_hz": TONES_HZ.tolist(), "rows": rows}, indent=1)
    )


if __name__ == "__main__":
    main()

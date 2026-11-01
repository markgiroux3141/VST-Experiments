"""Tube synth, SYNTH_IDEAS.md #3: velocity measured (config/circuits/tube_synth.yaml).

Velocity sets the keyboard bus's key-down volts (the gate control input): the envelope
charges toward it, so a softer key opens the push-pull 6386 VCA less (its grids' common
bias). Per key-down voltage, with a key held at the panel's defaults (pitch -15 V, draft
with the native app's partition, noise off), this reports the output's level (rms dBFS
of the held note against the circuit's full scale) and the envelope node's volts, plus
the harmonics' share (THD of the out against its fundamental), to see whether a soft key
is only quieter or also cleaner. `--table` prints the velocity table varimu-app
interpolates (panel.rs): key-down volts against level in dB re -1 V's.

    uv run --extra fast python scripts/velocity_study.py [--down -1 -5 -10] [--set k=v ...]
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
    "envelope",
    "|",
    "oscillator",
    "pitch",
    "|",
    "power supply",
    "bias supply",
)  # the native app's (panel.rs)
FULL_SCALE_V = 3.5  # the circuit file's full_scale output
DOWN_V = (-1, -2, -3, -4, -5, -6, -8, -10, -12, -14, -16, -18, -20, -23, -26, -30, -35, -40)
DUR_S = 1.2


def run(sets: dict, down_v: float) -> dict:
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets), cores="ja", noise=False)
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"), VoltageProbe("env")))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(DUR_S * fs)
    t = np.arange(n) / fs
    gate = np.where(t >= 0.1, float(down_v), -110.0)
    v = fast.run_transient(
        ir,
        np.zeros(n),
        settings=st,
        controls={
            "gate": gate,
            "pitch": np.full(n, -15.0),
            "key": np.zeros(n),
            "pressure": np.zeros(n),
        },
    ).vectors
    k = slice(int(0.7 * fs), n)
    y = v["v(out)"][k] - np.mean(v["v(out)"][k])
    f0 = vco.frequency(y, fs)
    spec_ = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1 / fs)

    def peak(f):
        i = np.argmin(np.abs(freqs - f))
        return np.sqrt(np.sum(spec_[max(i - 3, 0) : i + 4] ** 2))

    h = [peak(f0 * m) for m in range(1, 11)]
    return {
        "down_v": down_v,
        "out_dbfs": round(float(20 * np.log10(np.sqrt(np.mean(y**2)) / FULL_SCALE_V)), 2),
        "env_v": round(float(np.mean(v["v(env)"][k])), 2),
        "thd_pct": round(float(100 * np.sqrt(np.sum(np.square(h[1:]))) / h[0]), 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--down", nargs="*", type=float, default=list(DOWN_V))
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    ap.add_argument("--out", type=Path, default=Path("reports/tube_synth/velocity.json"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--table", action="store_true", help="print the Rust velocity table")
    a = ap.parse_args()
    sets = {k: float(v) for k, v in (kv.split("=", 1) for kv in a.set)}
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(lambda d: run(sets, d), a.down))
    for r in rows:
        print(r, flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"sets": sets, "rows": rows}, indent=1))
    if a.table:
        top = max(rows, key=lambda r: r["down_v"])["out_dbfs"]
        pts = sorted((round(r["out_dbfs"] - top, 2), r["down_v"]) for r in rows)
        print("&[" + ", ".join(f"({d!r}, {v!r})" for d, v in pts) + "]")


if __name__ == "__main__":
    main()

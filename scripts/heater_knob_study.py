"""Tube synth, SYNTH_IDEAS.md #4: the HEATER control measured (config/circuits/tube_synth.yaml).

HEATER is the heaters' volts over their rating (the circuit file's `heater`, the `heaters`
block's tap). Per setting, warm (the cathodes at the temperature that heater holds), a key
held at pitch -15 V at the panel's defaults, draft with the native app's partition, noise
off: the note's pitch (cents re HEATER 1), its level (rms dBFS against the circuit's full
scale), its harmonics (THD of the out), its crest factor (peak over rms: softened peaks
lower it) and B+ at the small stages (b3: the 6X4 rectifier is heated too).

    uv run --extra fast python scripts/heater_knob_study.py [--heater 0.6 0.8 1.0] [--out FILE]
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
HEATERS = (0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1)
DUR_S = 1.2


def run(heater: float) -> dict:
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {"heater": heater}), cores="ja", noise=False)
    ir = dataclasses.replace(
        ir, probes=(VoltageProbe("out"), VoltageProbe("o_t"), VoltageProbe("b3"))
    )
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(DUR_S * fs)
    t = np.arange(n) / fs
    controls = {
        "gate": np.where(t >= 0.1, -1.0, -110.0),
        "pitch": np.full(n, -15.0),
        "key": np.zeros(n),
        "pressure": np.zeros(n),
    }
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls=controls).vectors
    k = slice(int(0.7 * fs), n)
    y = v["v(out)"][k] - np.mean(v["v(out)"][k])
    f_osc = vco.frequency(v["v(o_t)"][k], fs)
    sp = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1 / fs)

    def peak(f):
        i = np.argmin(np.abs(freqs - f))
        return np.sqrt(np.sum(sp[max(i - 3, 0) : i + 4] ** 2))

    h = [peak(f_osc * m) for m in range(1, 11)]
    rms = np.sqrt(np.mean(y**2))
    return {
        "heater": heater,
        "hz": round(float(f_osc), 2),
        "out_dbfs": round(float(20 * np.log10(rms / FULL_SCALE_V)), 2),
        "thd_pct": round(float(100 * np.sqrt(np.sum(np.square(h[1:]))) / h[0]), 2),
        "crest_db": round(float(20 * np.log10(np.max(np.abs(y)) / rms)), 2),
        "b3_v": round(float(np.mean(v["v(b3)"][k])), 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--heater", nargs="*", type=float, default=list(HEATERS))
    ap.add_argument("--out", type=Path, default=Path("reports/tube_synth/heater_knob.json"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(run, a.heater))
    ref = next((r for r in rows if r["heater"] == 1.0), rows[-1])
    for r in rows:
        r["cents_re_1"] = round(float(vco.cents(r["hz"], ref["hz"])), 1)
        r["db_re_1"] = round(r["out_dbfs"] - ref["out_dbfs"], 2)
        print(r, flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"rows": rows}, indent=1))


if __name__ == "__main__":
    main()

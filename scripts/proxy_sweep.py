"""Measurements for tube_synth's proxy (docs/MIDI_TAKES_PLAN.md N2) that no study had:
the level of a held key across the keyboard (the oscillator's amplitude, the filter and the
VCA together, at the panel's defaults).

Each key is held at velocity 127 (the keyboard bus at -1 V) from 0.1 s at its pitch volts
(the app's tuning: reports/tube_synth/vco/synth_tuning_{high,low}.json, the range switch as
AUTO sets it: LOW below 330 Hz), rendered at draft with the app's partition, and its rms
over the last 0.5 s taken re the circuit's full scale (as `velocity_study.py`).

    uv run --extra fast python scripts/proxy_sweep.py [--notes 24 36 48 ...] [--set k=v ...]

Writes reports/tube_synth/proxy/key_level.json; `scripts/proxy_tables.py` reads it.
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

ROOT = Path(__file__).resolve().parents[1]
CIRCUIT = CONFIG_DIR / "circuits" / "tube_synth.yaml"
TUNING = ROOT / "reports" / "tube_synth" / "vco"
OUT = ROOT / "reports" / "tube_synth" / "proxy" / "key_level.json"
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
FULL_SCALE_V = 3.5  # the circuit file's full_scale output
SPLIT_HZ = 330.0  # panel.rs TUBE_SYNTH_SPLIT_HZ
DUR_S = 1.4
NOTES = tuple(range(24, 97))  # every key: the tuning error varies key to key


def pitch_volts(hz: float) -> tuple[float, int]:
    """The pitch input's volts for `hz` and the range switch's position, as the app plays
    it (its tuning tables, interpolated in log2 Hz)."""
    rng = 0 if hz < SPLIT_HZ else 1
    name = "synth_tuning_low.json" if rng == 0 else "synth_tuning_high.json"
    pts = sorted(json.loads((TUNING / name).read_text())["hz_v"])
    f = np.array([p[0] for p in pts])
    v = np.array([p[1] for p in pts])
    return float(np.interp(np.log2(hz), np.log2(f), v)), rng


def run(sets: dict, note: int) -> dict:
    fs = io.load_sim_settings().sample_rate
    hz = 440.0 * 2 ** ((note - 69) / 12)
    pv, rng = pitch_volts(hz)
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {**sets, "range": rng}), cores="ja", noise=False)
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(DUR_S * fs)
    t = np.arange(n) / fs
    key = np.clip((note - 60) * 0.75, -27.0, 27.0)
    out = fast.run_transient(
        ir,
        np.zeros(n),
        settings=st,
        controls={
            "gate": np.where(t >= 0.1, -1.0, -110.0),
            "pitch": np.full(n, pv),
            "key": np.full(n, key),
            "pressure": np.zeros(n),
            "pitch2": np.zeros(n),
        },
    ).vectors["v(out)"]
    y = out[int((DUR_S - 0.5) * fs) :]
    y = y - np.mean(y)
    return {
        "note": note,
        "hz": round(hz, 3),
        "range": rng,
        "pitch_v": round(pv, 4),
        "f_measured_hz": round(float(vco.frequency(y, fs)), 3),
        "out_dbfs": round(float(20 * np.log10(np.sqrt(np.mean(y**2)) / FULL_SCALE_V)), 3),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--notes", nargs="*", type=int, default=list(NOTES))
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    sets = {k: float(v) for k, v in (x.split("=", 1) for x in a.set)}
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(lambda n: run(sets, n), a.notes))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"sets": sets, "rows": rows}, indent=1) + "\n", encoding="utf-8")
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()

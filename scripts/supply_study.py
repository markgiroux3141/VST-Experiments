"""Tube synth, SYNTH_IDEAS.md #6 (SUPPLY) measured before building (tube_synth.yaml).

Per rectifier (the 6X4 the synth has; a silicon rectifier standing in for the stiff end: a
selenium stack sits between, a few volts more drop than silicon, far stiffer than the 6X4;
a copy of the circuit file with the rectifier parts named D-, as junction diodes must be)
and reservoir (`reservoir`, the RESERVOIR switch), a key held 1.2 s at pitch -15 V with a
fast attack, draft with the native app's partition, noise off:
- the note's level per 25 ms window: the bloom (the first 100 ms against the last 300 ms, dB);
- B+ at b1 and b3 before the key and held (the sag, V);
- the supply ripple's sidebands: the power at the harmonics' +-120 Hz (and +-240) against
  the harmonics' (dB), held;
- the pitch, early (50-250 ms) against late (last 300 ms), cents, and its cycle-to-cycle
  spread held (2.5-97.5 percentiles, cents: the ripple's FM);
- the 6X4's steady-state peak plate current per section, held (GE ET-T865A: 245 mA max).
-> reports/tube_synth/supply.json

    uv run --extra fast python scripts/supply_study.py [--reservoir 8e-6 20e-6 40e-6]
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
    "lfo",
    "|",
    "power supply",
    "bias supply",
)  # the native app's (panel.rs)
FULL_SCALE_V = 3.5
RECTIFIERS = {"6x4": "6X4@1", "silicon": "SI_RECTIFIER@1"}
ON_S, DUR_S = 0.2, 1.6
PANEL = {"attack": 0.05, "release": 0.3}


def circuit(rect: str, where: Path) -> Path:
    """The circuit file, or for a junction-diode rectifier a copy with its parts renamed."""
    if rect == "6x4":
        return CIRCUIT
    src = CIRCUIT.read_text(encoding="utf-8")
    for a in ("XVRA", "XVRB"):
        assert src.count(f"      {a}: ") == 1
        src = src.replace(f"      {a}: ", f"      D{a[1:]}: ")
    path = where / f"tube_synth_{rect}.yaml"
    path.write_text(src, encoding="utf-8")
    return path


def run(rect: str, c_res: float, path: Path) -> dict:
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(path)
    sets = {**PANEL, "rectifier_tube": RECTIFIERS[rect], "reservoir": c_res}
    ir = builder.build_ir(s, spec.resolve(s, sets), cores="ja", noise=False)
    probes = ("out", "o_t", "b1", "b3", "hv_a", "hv_ar")
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(DUR_S * fs)
    t = np.arange(n) / fs
    controls = {
        "gate": np.where(t >= ON_S, -1.0, -110.0),
        "pitch": np.full(n, -15.0),
        "key": np.zeros(n),
        "pressure": np.zeros(n),
    }
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls=controls).vectors
    out = v["v(out)"] - np.mean(v["v(out)"][int(1.2 * fs) :])
    w = int(0.025 * fs)
    k0 = int(ON_S * fs)
    lev = [
        float(20 * np.log10(np.sqrt(np.mean(out[a : a + w] ** 2)) / FULL_SCALE_V + 1e-12))
        for a in range(k0, n - w + 1, w)
    ]
    early = float(np.max(lev[:4]))  # the first 100 ms's loudest window
    late = float(np.mean(lev[-12:]))  # the last 300 ms
    held = slice(n - int(0.4 * fs), n)
    f0 = vco.frequency(v["v(o_t)"][held], fs)
    f, p = vco._spectrum(out[held], fs)
    df = f[1]

    def band(fc):
        j = int(round(fc / df))
        return p[max(j - 4, 0) : j + 5].sum() if 0 < fc < fs / 2 else 0.0

    harm = sum(band(f0 * m) for m in range(1, 20))
    side = {d: sum(band(f0 * m + s * d) for m in range(1, 20) for s in (-1, 1)) for d in (120, 240)}
    tt, fc = vco.cycle_frequencies(v["v(o_t)"], fs)
    fe = np.median(fc[(tt > ON_S + 0.05) & (tt < ON_S + 0.25)])
    fl = np.median(fc[tt > DUR_S - 0.3])
    late_fc = fc[tt > DUR_S - 0.4]
    spread = float(vco.cents(np.percentile(late_fc, 97.5), np.percentile(late_fc, 2.5)))
    r_half = float(s.values["pt_r_half_ohm"]["value"])
    i_plate = (v["v(hv_a)"] - v["v(hv_ar)"]) / r_half
    return {
        "rectifier": rect,
        "c_reservoir_uf": round(c_res * 1e6, 1),
        "bloom_db": round(late - early, 2),
        "level_early_dbfs": round(early, 2),
        "level_late_dbfs": round(late, 2),
        "level_25ms_dbfs": [round(x, 2) for x in lev],
        "b1_v": [
            round(float(np.mean(v["v(b1)"][k0 - w : k0])), 1),
            round(float(np.mean(v["v(b1)"][held])), 1),
        ],
        "b3_v": [
            round(float(np.mean(v["v(b3)"][k0 - w : k0])), 1),
            round(float(np.mean(v["v(b3)"][held])), 1),
        ],
        "ripple_sidebands_db": {
            str(d): round(float(10 * np.log10(side[d] / harm)), 1) for d in side
        },
        "pitch_drift_cents": round(float(vco.cents(fl, fe)), 1),
        "pitch_spread_cents": round(spread, 1),
        "plate_peak_ma": round(float(1e3 * np.max(i_plate[held])), 1),
        "hz": round(float(f0), 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reservoir", nargs="*", type=float, default=[8e-6, 20e-6, 40e-6])
    ap.add_argument("--rectifier", nargs="*", default=list(RECTIFIERS), choices=list(RECTIFIERS))
    ap.add_argument("--out", type=Path, default=Path("reports/tube_synth/supply.json"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    jobs = [(r, c) for r in a.rectifier for c in a.reservoir]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    paths = {r: circuit(r, a.out.parent) for r in a.rectifier}
    with ThreadPoolExecutor(a.workers) as ex:

        def one(j):
            try:
                return run(*j, paths[j[0]])
            except Exception as e:  # a run that stops: reported, not fatal
                return {
                    "rectifier": j[0],
                    "c_reservoir_uf": round(j[1] * 1e6, 1),
                    "failed": str(e)[:200],
                }

        rows = list(ex.map(one, jobs))
    for r in rows:
        print({k: v for k, v in r.items() if k != "level_25ms_dbfs"}, flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"panel": PANEL, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()

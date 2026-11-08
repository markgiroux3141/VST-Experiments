"""Speed lever 2 for the literal Ampex 351 (docs/TAPE_PLAN.md, "Speed: the GPU"): each
candidate a setting measured against production on the same excerpt.

The harness: 0.5 s of the drums at +6 dB drive through the aligned machine at production
(JA cores, the circuit's noise off so runs compare sample by sample), one job alone, the
1 s settle counted. The candidates:
- `subN`: the record side (every section with substeps, and the tape's bias_substeps) at
  N steps per sample instead of 20 (sub10: 1.92 MHz; sub40, 7.68 MHz, measures how far 20
  itself is from converged);
- `tables`: the triodes from tables of the same model (the draft's `tube_tables`, ~1e-7 of
  the exact sections), everywhere;
- both together;
- `kick`: the oscillator started from a slightly different state (the phase test);
- `noctl`: no local error control (`error_abstol` 0, every part): its subdivisions, set by
  where the oscillator's peaks fall in a step, beat against it (TAPE_PLAN.md "Speed");
- `lagN`: the record side reads the rest (its supply's reservoirs) N samples late and runs
  ahead of it (the multi-rate sections' `lag_samples`; TAPE_SPEED_PLAN.md P2), `lag0`
  lockstep whatever the circuit file says.
- `ttN`: the tape's recording kernel on N threads (CIRCUITSIM_TAPE_THREADS; the output
  doesn't depend on it); each row reports the process's CPU seconds beside the wall time;
- `mtrbdf2` (any method name after `m`), `mtables` / `mnotables`: the record side's own
  method or tube tables (its sections' `method` / `tube_tables`; TAPE_SPEED_PLAN.md P4: the
  circuit file has trbdf2 with tables since P4, so `mesdirk4_mnotables` is the old record
  side);
- `gpu`: the tape's recording kernel on the GPU in f32 (`TransientSettings.tape_gpu`;
  TAPE_SPEED_PLAN.md P5).
`--floor` measures each variant on the noiseless machine with no input instead (the plan's
rule: judge the record side's numerics on its floor): the strongest line 1-15 kHz (the bias
residue near 96 kHz - f_osc) and the band noise 50 Hz-15 kHz, as tape_snr_study.py --cells;
results in floor.json.
`--alignment FILE` takes the panel from a cached alignment (cache/tape/align_351_*.json)
instead of `tape_align.aligned()`, which re-aligns (~32 min) after any change to the code it
hashes: timings and comparisons between variants only need the same panel.
With `CIRCUITSIM_PART_TIMING=1` circuitsim prints each part's busy and waiting time.
Each run's output is kept (cache/tape/speed/), and the difference from `ref` reported in
dB re the reference's rms, with its time per second of audio.

    uv run --extra fast python scripts/speed_351.py ref sub10 tables sub10_tables tables_sub40
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
from scipy import signal as sps

from varimu.circuit import builder, spec
from varimu.circuit import ir as irm
from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta
from varimu.measure import tape_suite as ts
from varimu.sim import fast
from varimu.sim.io import TransientSettings, load_audio

CACHE = REPO_ROOT / "cache" / "tape" / "speed"
TAIL_S = 0.1


def with_substeps(ir: irm.CircuitIR, m: int) -> irm.CircuitIR:
    """Every multi-rate section, and the tape's literal bias, at m steps per sample."""
    secs = []
    for s in ir.sections:
        els = tuple(
            dataclasses.replace(e, medium=dataclasses.replace(e.medium, bias_substeps=m))
            if isinstance(e, irm.Tape) and e.medium.bias_substeps
            else e
            for e in s.elements
        )
        secs.append(dataclasses.replace(s, elements=els, substeps=m if s.substeps else None))
    return dataclasses.replace(ir, sections=tuple(secs))


def with_lag(ir: irm.CircuitIR, lag: int) -> irm.CircuitIR:
    """Every multi-rate section reading the rest `lag` samples late (0: lockstep)."""
    secs = tuple(
        dataclasses.replace(s, lag_samples=lag or None) if s.substeps else s for s in ir.sections
    )
    return dataclasses.replace(ir, sections=secs)


def with_record_side(ir: irm.CircuitIR, method: str | None, tables: bool | None) -> irm.CircuitIR:
    """Every multi-rate section with its own method and / or tube tables (None: as is)."""
    secs = []
    for s in ir.sections:
        if s.substeps:
            if method is not None:
                s = dataclasses.replace(s, method=method)
            if tables is not None:
                s = dataclasses.replace(s, tube_tables=tables)
        secs.append(s)
    return dataclasses.replace(ir, sections=tuple(secs))


def band_diff(y: np.ndarray, yr: np.ndarray, fs: int) -> float:
    """The largest difference of third-octave band levels, 50 Hz-15 kHz (dB): what the
    record side's step changes beyond the free oscillator's phase (which moves the bias
    pattern against the signal, so waveforms differ ~-46 dB between any two step sizes)."""
    f = np.fft.rfftfreq(len(y), 1.0 / fs)
    py, pr = np.abs(np.fft.rfft(y)) ** 2, np.abs(np.fft.rfft(yr)) ** 2
    worst = 0.0
    for fc in 1000.0 * 2.0 ** (np.arange(-13, 12) / 3.0):
        b = (f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6))
        worst = max(worst, abs(10 * math.log10(py[b].sum() / pr[b].sum())))
    return worst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("variants", nargs="+")
    ap.add_argument("--clip", default="drums_setmefree.wav")
    ap.add_argument("--seconds", type=float, default=0.5)
    ap.add_argument("--drive-db", type=float, default=6.0)
    ap.add_argument("--floor", action="store_true", help="the noiseless floor instead")
    ap.add_argument("--alignment", type=Path, help="a cached alignment's JSON (its panel)")
    a = ap.parse_args()

    al = ta.Alignment(**json.loads(a.alignment.read_text())) if a.alignment else ta.aligned()
    st0 = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st0.sample_rate
    c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
    v_in, v_out = c.full_scale
    p = spec.resolve(c, al.overrides)
    delay = int(round(p["head_distance_m"] / p["speed_m_s"] * fs))
    ir0 = builder.build(c, al.overrides, cores="ja", noise=False).ir
    # `kick`: the oscillator's start state 10% off (0.1 -> 0.11 V on 1C36): the same circuit,
    # the bias's phase against the signal moved, to tell that phase from a step's error.
    ir_kick = builder.build(c, {**al.overrides, "osc_kick_v": 0.11}, cores="ja", noise=False).ir
    x = load_audio(REPO_ROOT / "data" / "clips" / a.clip, fs)[: int(a.seconds * fs)]
    u = np.concatenate([x, np.zeros(delay + int(TAIL_S * fs))]) * v_in * 10 ** (a.drive_db / 20)
    if a.floor:
        u = np.zeros(int((ts.MEASURE_FROM_S + ts.NOISE_S) * fs))
    CACHE.mkdir(parents=True, exist_ok=True)
    log = CACHE / ("floor.json" if a.floor else "results.json")
    res = json.loads(log.read_text()) if log.exists() else {}
    for v in a.variants:
        ir, st = (ir_kick if "kick" in v else ir0), st0
        if m := re.search(r"sub(\d+)", v):
            ir = with_substeps(ir, int(m.group(1)))
        if m := re.search(r"lag(\d+)", v):
            ir = with_lag(ir, int(m.group(1)))
        if re.search(r"(^|_)tables", v):
            st = dataclasses.replace(st, tube_tables=True)
        if re.search(r"(^|_)gpu", v):
            st = dataclasses.replace(st, tape_gpu=True)
        if "noctl" in v:
            st = dataclasses.replace(st, error_abstol=0.0)
        m = re.search(r"m(trap|trbdf2|sdirk3|esdirk4|euler)", v)
        tables = False if "mnotables" in v else (True if "mtables" in v else None)
        ir = with_record_side(ir, m.group(1) if m else None, tables)
        os.environ.pop("CIRCUITSIM_TAPE_THREADS", None)
        if m := re.search(r"tt(\d+)", v):
            os.environ["CIRCUITSIM_TAPE_THREADS"] = m.group(1)
        t0, c0 = time.time(), time.process_time()
        r = fast.run_transient(ir, u, settings=st)
        el, cpu = time.time() - t0, time.process_time() - c0
        if a.floor:
            y = r.vectors["v(out)"][int(ts.MEASURE_FROM_S * fs) :] / v_out
            y = y - np.mean(y)
            f, pw = sps.periodogram(y * np.hanning(len(y)), fs)
            band = (f > 1000) & (f < 15000)
            i = int(np.argmax(np.where(band, pw, 0)))
            line = 10 * math.log10(pw[max(i - 3, 0) : i + 4].sum() * (f[1] - f[0]) / 0.375 + 1e-30)
            row = {
                "line_hz": float(f[i]),
                "line_dbfs": line,
                "noise_dbfs_rms": 20 * math.log10(ts.band_rms(y, fs, ts.NOISE_BAND_HZ) + 1e-30),
                "x_real_time": el / (len(u) / fs + st.settle_s),
            }
            res[v] = row
            log.write_text(json.dumps(res, indent=1))
            print(v, json.dumps(row), flush=True)
            continue
        y = r.vectors["v(out)"][delay:] / v_out
        np.save(CACHE / f"{v}.npy", y)
        row = {"x_real_time": el / (len(u) / fs + st.settle_s), "seconds": el, "cpu_s": cpu}
        for other in sorted(CACHE.glob("*.npy")):
            if other.stem == v:
                continue
            yr = np.load(other)
            n = min(len(y), len(yr))
            d = y[:n] - yr[:n]
            rms = np.sqrt(np.mean(yr[:n] ** 2))
            row[f"vs_{other.stem}_db"] = 20 * math.log10(np.sqrt(np.mean(d**2)) / rms + 1e-300)
            row[f"bands_vs_{other.stem}_db"] = band_diff(y[:n], yr[:n], fs)
        res[v] = row
        log.write_text(json.dumps(res, indent=1))
        print(v, json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

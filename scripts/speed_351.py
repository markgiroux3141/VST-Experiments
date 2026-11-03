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
  where the oscillator's peaks fall in a step, beat against it (TAPE_PLAN.md "Speed").
Each run's output is kept (cache/tape/speed/), and the difference from `ref` reported in
dB re the reference's rms, with its time per second of audio.

    uv run --extra fast python scripts/speed_351.py ref sub10 tables sub10_tables tables_sub40
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import re
import sys
import time

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit import ir as irm
from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta
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
    a = ap.parse_args()

    al = ta.aligned()
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
    CACHE.mkdir(parents=True, exist_ok=True)
    log = CACHE / "results.json"
    res = json.loads(log.read_text()) if log.exists() else {}
    for v in a.variants:
        ir, st = (ir_kick if "kick" in v else ir0), st0
        if m := re.search(r"sub(\d+)", v):
            ir = with_substeps(ir, int(m.group(1)))
        if "tables" in v:
            st = dataclasses.replace(st, tube_tables=True)
        if "noctl" in v:
            st = dataclasses.replace(st, error_abstol=0.0)
        t0 = time.time()
        r = fast.run_transient(ir, u, settings=st)
        el = time.time() - t0
        y = r.vectors["v(out)"][delay:] / v_out
        np.save(CACHE / f"{v}.npy", y)
        row = {"x_real_time": el / (len(u) / fs + st.settle_s), "seconds": el}
        for other in sorted(CACHE.glob("*.npy")):
            if other.stem == v:
                continue
            yr = np.load(other)
            n = min(len(y), len(yr))
            d = y[:n] - yr[:n]
            rms = np.sqrt(np.mean(yr[:n] ** 2))
            row[f"vs_{other.stem}_db"] = 20 * math.log10(np.sqrt(np.mean(d**2)) / rms)
            row[f"bands_vs_{other.stem}_db"] = band_diff(y[:n], yr[:n], fs)
        res[v] = row
        log.write_text(json.dumps(res, indent=1))
        print(v, json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

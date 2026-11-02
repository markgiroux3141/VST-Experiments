"""Tube synth, SYNTH_IDEAS.md #7 and #8's start: the lamp-stabilized Wien-bridge LFO measured
(config/circuits/tube_synth.yaml), with VIBRATO and WOBBLE.

A key held at -15 V (~480 Hz), at draft with the native app's partition, at a few RATE
settings, from the start of a run (the circuit's DC point, the bridge kicked by CW2's start
voltage). Per RATE:
- the LFO's frequency, its settled amplitude and DC (the last quarter of the run), its THD
  (harmonics 2-9 over whole cycles of the last quarter) and the time its peak amplitude
  stays within 5% of the settled one (the lamp's bloom from the start);
- the lamp's temperature: its mean and its swing within a cycle (the last cycle);
- with VIBRATO and WOBBLE at 1: the vibrato (the per-cycle pitch of o_t over whole LFO
  cycles of the last quarter, its component at the LFO's frequency: +- cents) and V4's grid
  swing (V, peak to peak);
- with both at 0: the same component (what reaches the pitch through the shared supplies),
  and the pitch's per-cycle spread for scale (the oscillator's own jitter, noise on).

    uv run --extra fast python scripts/lfo_study.py [--rates 0.25 0.5 0.7 1] [--out FILE]
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
from varimu.circuit.ir import VoltageProbe, element_nodes
from varimu.config import CONFIG_DIR, REPO_ROOT
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
PITCH_V = -15.0
T_AMB_K = 300.0
# (RATE, seconds): long enough for the slow end's bloom to settle.
RUNS = {0.25: 40.0, 0.5: 16.0, 0.7: 10.0, 1.0: 8.0}
OUT = REPO_ROOT / "reports" / "tube_synth" / "lfo.json"


def run(sets: dict, dur_s: float) -> dict[str, np.ndarray]:
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets), cores="ja")
    nodes = {n for e in ir.elements() for n in element_nodes(e)}
    # (lf_t, the lamp's temperature, isn't there with the LFO off)
    probes = tuple(VoltageProbe(p) for p in ("lfo", "lf_t", "o_t", "g4") if p in nodes)
    ir = dataclasses.replace(ir, probes=probes)
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(dur_s * fs)
    v = fast.run_transient(
        ir,
        np.zeros(n),
        settings=st,
        controls={
            "gate": np.full(n, KEY_DOWN_V),
            "pitch": np.full(n, PITCH_V),
            "key": np.zeros(n),
            "pressure": np.zeros(n),
        },
    ).vectors
    return {k[2:-1]: x for k, x in v.items()}


def crossings(x: np.ndarray, fs: float) -> np.ndarray:
    """Upward zero crossings of x minus its mean (s, interpolated), with hysteresis: a
    crossing counts once x has been below -20% of its swing since the last one (on a slow
    sine the circuit's noise crosses zero many times per crossing)."""
    y = x - np.mean(x)
    h = 0.2 * 0.5 * np.ptp(y)
    out, armed = [], False
    for i in np.nonzero((y[:-1] < 0) & (y[1:] >= 0) | (y[:-1] < -h))[0]:
        if y[i] < -h:
            armed = True
        elif armed:
            out.append((i + y[i] / (y[i] - y[i + 1])) / fs)
            armed = False
    return np.array(out)


def lfo_measures(v: dict[str, np.ndarray], fs: float) -> dict:
    x = v["lfo"]
    last = x[3 * len(x) // 4 :]
    tc = crossings(last, fs)
    f = (len(tc) - 1) / (tc[-1] - tc[0]) if len(tc) > 2 else float("nan")
    out = {"f_hz": f}
    if not np.isfinite(f):
        return out
    per = int(round(fs / f))
    # Peak amplitude per cycle over the whole run, and when it settles.
    m = len(x) // per
    seg = x[: m * per].reshape(m, per)
    amp = 0.5 * (seg.max(axis=1) - seg.min(axis=1))
    settled = float(np.median(amp[3 * m // 4 :]))
    off = np.nonzero(np.abs(amp - settled) > 0.05 * settled)[0]
    settle_s = float((off[-1] + 1) * per / fs) if len(off) else 0.0
    # THD over whole cycles of the last quarter: harmonics 1-9 fitted by least squares
    # (at the slow end only two or three cycles fit, too few for an FFT's bins).
    i0, i1 = int(tc[0] * fs), int(tc[-1] * fs)
    y = last[i0:i1:8]
    ph = 2 * np.pi * f * np.arange(len(y)) * 8 / fs
    cols = [np.ones_like(ph)]
    for k in range(1, 10):
        cols += [np.sin(k * ph), np.cos(k * ph)]
    c = np.linalg.lstsq(np.stack(cols, axis=1), y, rcond=None)[0]
    h = np.hypot(c[1::2], c[2::2])
    thd = float(np.sqrt(np.sum(np.square(h[1:]))) / h[0])
    t = v["lf_t"] + T_AMB_K
    out.update(
        amp_peak_v=settled,
        dc_v=float(np.mean(last)),
        thd_pct=100 * thd,
        settle_s=settle_s,
        lamp_k=float(np.mean(t[3 * len(t) // 4 :])),
        lamp_swing_k=float(np.ptp(t[-per:])),
        amp_first_cycles_v=[round(float(a), 2) for a in amp[: min(8, m)]],
    )
    return out


def pitch_swing_cents(v: dict[str, np.ndarray], fs: float) -> float:
    """The per-cycle pitch's spread (1-99th percentiles) over the last quarter, cents."""
    t, fc = vco.cycle_frequencies(v["o_t"], fs)
    keep = t > 0.75 * len(v["o_t"]) / fs
    c = vco.cents(fc[keep], float(np.median(fc[keep])))
    return float(np.percentile(c, 99) - np.percentile(c, 1))


def vibrato_cents(v: dict[str, np.ndarray], fs: float, f_lfo: float) -> float:
    """The per-cycle pitch's component at the LFO's frequency over whole LFO cycles of the
    last quarter (a lock-in: the oscillator's jitter averages out), +- cents."""
    t, fc = vco.cycle_frequencies(v["o_t"], fs)
    t_end = len(v["o_t"]) / fs
    n_cyc = int(np.floor(0.25 * t_end * f_lfo))
    if n_cyc < 1:
        return float("nan")
    keep = t > t_end - n_cyc / f_lfo
    c = vco.cents(fc[keep], float(np.median(fc[keep])))
    ph = np.exp(-2j * np.pi * f_lfo * t[keep])
    return float(2 * np.abs(np.mean((c - np.mean(c)) * ph)))


def measure(rate: float, dur_s: float) -> dict:
    fs = io.load_sim_settings().sample_rate
    on = run({"lfo_rate": rate, "vibrato": 1.0, "wobble": 1.0}, dur_s)
    off = run({"lfo_rate": rate, "vibrato": 0.0, "wobble": 0.0}, dur_s)
    q = len(on["g4"]) // 4
    res = {
        "rate": rate,
        "duration_s": dur_s,
        "on": lfo_measures(on, fs),
        "off": lfo_measures(off, fs),
        "vibrato_cents": vibrato_cents(on, fs, on_f := lfo_measures(on, fs)["f_hz"]),
        "lfo_in_pitch_cents_depth0": vibrato_cents(off, fs, on_f),
        "wobble_g4_pp_v": float(np.ptp(on["g4"][-q:])),
        "g4_mean_v": float(np.mean(on["g4"][-q:])),
        "g4_mean_v_wobble0": float(np.mean(off["g4"][-q:])),
        "pitch_jitter_pp_cents_depth0": pitch_swing_cents(off, fs),
        "pitch_hz_depth0": float(vco.frequency(off["o_t"][-q:], fs)),
    }
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rates", nargs="*", type=float, default=list(RUNS))
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 6))
    a = ap.parse_args()
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda r: measure(r, RUNS.get(r, 10.0)), a.rates))
    for r in res:
        print(json.dumps(r))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"pitch_v": PITCH_V, "runs": res}, indent=1) + "\n")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()

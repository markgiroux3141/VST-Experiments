"""Tube synth, SYNTH_IDEAS.md #5 (PULSE), the prototype: a variant of tube_synth.yaml with a
peaking transformer (a 12AU7 follower off the tank driving a small ungapped mumetall core
through a resistor; a 1:1 secondary through a PULSE pot and 1M into the WAVE wiper; a bias winding
from a PULSE WIDTH pot centred on 0 V), measured at draft with the app's partition (the
pulse network on the oscillator's thread) or production. Not built into the synth: see
SYNTH_IDEAS.md #5's status. Writes the variant and its results to reports/tube_synth/pulse/.

    uv run --extra fast python scripts/pulse_prototype.py [--n1 150] [--area 1.0e-5]
        [--path 0.03] [--rdrive 2200] [--width 0.2 0.5 0.8] [--quality draft] [--tag NAME]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io
from varimu.synth import vco

HERE = Path(__file__).parents[1] / "reports" / "tube_synth" / "pulse"
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
)


def variant(a) -> Path:
    src = (CONFIG_DIR / "circuits" / "tube_synth.yaml").read_text(encoding="utf-8")

    def rep(x, y):
        nonlocal src
        assert src.count(x) == 1, x
        src = src.replace(x, y)

    P = 'source: "provisional: prototype"'
    rep(
        "  wave: {value: 0.5,",
        f"  pulse: {{value: 1.0, min: 0.0, max: 1.0, unit: rotation, {P}}}\n"
        f"  pulse_width: {{value: 0.5, min: 0.0, max: 1.0, unit: rotation, {P}}}\n"
        "  wave: {value: 0.5,",
    )
    rep(
        "  osc_r_buffer_cathode_ohm:",
        f"  pl_r_grid_ohm: {{value: 1.0e+6, {P}}}\n"
        f"  pl_r_cathode_ohm: {{value: {a.rk:.6e}, {P}}}\n"
        f"  pl_c_couple_f: {{value: 1.0e-6, {P}}}\n"
        f"  pl_r_drive_ohm: {{value: {a.rdrive:.6e}, {P}}}\n"
        f"  pl_r_winding_ohm: {{value: {a.rw:.6e}, {P}}}\n"
        f"  pl_c_winding_f: {{value: {a.cw:.6e}, {P}}}\n"
        f"  pl_turns: {{value: {a.n1:.6e}, {P}}}\n"
        f"  pl_bias_ratio: {{value: {a.nb_ratio:.6e}, {P}}}\n"
        f"  pl_r_bias_ohm: {{value: {a.rbias:.6e}, {P}}}\n"
        f"  pl_r_bias_pot_ohm: {{value: 100.0e+3, {P}}}\n"
        f"  pl_r_bias_top_ohm: {{value: 150.0e+3, {P}}}\n"
        f"  pl_c_bias_f: {{value: 10.0e-6, {P}}}\n"
        f"  pl_core_area_m2: {{value: {a.area:.6e}, {P}}}\n"
        f"  pl_core_path_m: {{value: {a.path:.6e}, {P}}}\n"
        f"  pl_core_gap_m: {{value: 0.0, {P}}}\n"
        f"  pl_leakage_h: {{value: 0.0, {P}}}\n"
        f"  pl_r_pot_ohm: {{value: 100.0e+3, {P}}}\n"
        f"  pl_r_sum_ohm: {{value: {a.rsum:.6e}, {P}}}\n"
        "  osc_r_buffer_cathode_ohm:",
    )
    rep("  OV4: {device: 6V6GT@1}", "  OV4: {device: 6V6GT@1}\n  PLV: {device: 12AU7@1}")
    rep(
        "      ROK3: {R: [o_buf, neg], r: osc_r_buffer_cathode_ohm}\n",
        "      ROK3: {R: [o_buf, neg], r: osc_r_buffer_cathode_ohm}\n"
        "      RPLG: {R: [o_t, pl_g], r: pl_r_grid_ohm}\n"
        "      XPLV: {device: [b3, pl_g, pl_k], model: PLV}\n"
        "      RPLK: {R: [pl_k, neg], r: pl_r_cathode_ohm}\n"
        "      CPLC: {C: [pl_k, pl_c], c: pl_c_couple_f}\n"
        "      RPLD: {R: [pl_c, pl_p], r: pl_r_drive_ohm}\n"
        "      PLT:\n"
        "        transformer:\n"
        '          pri: {nodes: [pl_p, "0"], r: pl_r_winding_ohm, c: pl_c_winding_f}\n'
        '          sec: {nodes: [pl_s, "0"], r: pl_r_winding_ohm, c: pl_c_winding_f}\n'
        '          bias: {nodes: [pl_b, "0"], ratio: pl_bias_ratio, r: pl_r_winding_ohm}\n'
        "        core: {material: mumetall, area_m2: pl_core_area_m2, path_m: pl_core_path_m,"
        " gap_m: pl_core_gap_m}\n"
        "        turns: pl_turns\n"
        "        leakage_h: pl_leakage_h\n"
        "      RPLTOP: {R: [b3, pl_bt], r: pl_r_bias_top_ohm}\n"
        "      RPLW: {pot: [neg, pl_bw, pl_bt], r: pl_r_bias_pot_ohm, at: pulse_width}\n"
        '      CPLB: {C: [pl_bw, "0"], c: pl_c_bias_f}\n'
        "      RPLB: {R: [pl_bw, pl_b], r: pl_r_bias_ohm}\n"
        '      RPLP: {pot: ["0", pl_w, pl_s], r: pl_r_pot_ohm, at: pulse}\n'
        "      RPLS: {R: [pl_w, o_out], r: pl_r_sum_ohm}\n",
    )
    out = HERE / "pulse_proto.yaml"
    out.write_text(src, encoding="utf-8")
    return out


def run(path, sets, pitch_v, quality, dur_s=0.8, part=None):
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(path)
    ir = builder.build_ir(s, spec.resolve(s, sets), cores="ja", noise=False)
    names = [p for p in ("pl_s", "o_out", "out", "o_t") if p != "pl_s" or "pulse" in s.controls]
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in names))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    if quality != "production":
        st = dataclasses.replace(st, partition=part or PARTITION)
    n = int(dur_s * fs)
    ctl = {
        "gate": np.full(n, -1.0),
        "pitch": np.full(n, pitch_v),
        "key": np.zeros(n),
        "pressure": np.zeros(n),
        "pitch2": np.zeros(n),
    }
    t0 = time.perf_counter()
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl).vectors
    wall = time.perf_counter() - t0
    k = slice(int(0.4 * fs), n)
    return {p: v[f"v({p})"][k] for p in names}, wall, fs


def describe(r, fs):
    f0 = vco.frequency(r["o_t"], fs)
    ps = r["pl_s"]
    pk_pos, pk_neg = float(ps.max()), float(ps.min())
    # Pulse width: time above half the positive peak per cycle (mean), and below half the negative.
    wpos = float(np.mean(ps > 0.5 * pk_pos) / f0 * 1e6) if pk_pos > 0 else 0.0
    wneg = float(np.mean(ps < 0.5 * pk_neg) / f0 * 1e6) if pk_neg < 0 else 0.0
    # Positive pulse's phase against the negative's (0.5: evenly spaced).
    h = vco.harmonics_db(ps, fs, f0, 12)
    return {
        "f0": round(f0, 1),
        "sec_pk": [round(pk_pos, 2), round(pk_neg, 2)],
        "width_us": [round(wpos, 1), round(wneg, 1)],
        "sec_h_db": [round(float(x), 1) for x in h],
        "sec_inharm_db": round(float(vco.inharmonic_db(ps, fs, f0, sidebands_hz=(120, 240))), 1),
        "out_h_db": [round(float(x), 1) for x in vco.harmonics_db(r["out"], fs, f0, 12)],
        "o_out_pp": round(float(np.ptp(r["o_out"])), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n1", type=float, default=150)
    ap.add_argument("--rdrive", type=float, default=2200)
    ap.add_argument("--rk", type=float, default=10000)
    ap.add_argument("--rw", type=float, default=5.0)
    ap.add_argument("--cw", type=float, default=50e-12)
    ap.add_argument("--area", type=float, default=1e-5)
    ap.add_argument("--path", type=float, default=0.03)
    ap.add_argument("--nb-ratio", type=float, default=5.0)
    ap.add_argument("--rbias", type=float, default=100e3)
    ap.add_argument("--rsum", type=float, default=1.0e6)
    ap.add_argument("--pitch", nargs="*", type=float, default=[-20.0, -15.0, -5.0])
    ap.add_argument("--width", nargs="*", type=float, default=[0.5])
    ap.add_argument("--quality", default="draft")
    ap.add_argument("--tag", default="proto")
    a = ap.parse_args()
    HERE.mkdir(parents=True, exist_ok=True)
    path = variant(a)
    jobs = [(p, w) for p in a.pitch for w in a.width]
    with ThreadPoolExecutor(6) as ex:
        got = list(ex.map(lambda j: run(path, {"pulse_width": j[1]}, j[0], a.quality), jobs))
    res = []
    for (p, w), (r, _, fs) in zip(jobs, got, strict=True):
        d = {"pitch_v": p, "width": w, **describe(r, fs)}
        res.append(d)
        print(d, flush=True)
    # Speed: one alone, the base circuit and the variant.
    _, w_var, _ = run(path, {}, -15.0, a.quality, 1.0)
    _, w_one, _ = run(path, {}, -15.0, a.quality, 1.0, PARTITION)
    print(f"variant on the oscillator thread: {w_one:.2f} s")
    _, w_base, _ = run(CONFIG_DIR / "circuits" / "tube_synth.yaml", {}, -15.0, a.quality, 1.0)
    print(f"wall per 1 s (+1 s settle): variant {w_var:.2f} s, base {w_base:.2f} s")
    (HERE / f"pulse_{a.tag}.json").write_text(
        json.dumps({"args": vars(a), "rows": res, "wall": [w_var, w_base]}, indent=1)
    )


if __name__ == "__main__":
    main()

"""Tube synth, SYNTH_IDEAS.md #14 (the ring modulator): the prototypes and the built ring.

`core`: the diode ring alone (a test circuit written to reports/tube_synth/ring/): a signal
and a carrier from ~600 ohm sources (cathode followers), two small mumetall transformers
(1 : 1+1, centre-tapped), four diodes in a ring, the carrier between the centre taps, a
10k load. Per diode type and carrier level: the product (f_s +- f_c) re the signal in, the
carrier's and the signal's bleed and everything else (3 f_c +- f_s, squares...) re the
product, and the wall time per second at draft.

`synth`: the options brought to the user (what the ring multiplies), as variants of the
synth before the ring (PROTOTYPE_BASE): (a) a second reactor VCO, (b) the external input,
(c) the LFO with 10 nF Wien capacitors. Per pitch: both frequencies, the product and the
bleeds; `--wav` takes. scripts/ring_cpu.py times them.

`measure`: the built ring in tube_synth.yaml: the LFO's AUDIO range (rate, level, THD), the
ring's product and bleeds against the oscillator alone, and what RING ON moves (the pitch,
the LFO, its supply) -> built.json; `--wav` takes under audio/ (built_*).

    uv run --extra fast python scripts/ring_study.py core [--carrier 0.3 1 3 10]
    uv run --extra fast python scripts/ring_study.py synth --option vco2|in|lfo --osc-off
        --ring-alone [--wav]
    uv run --extra fast python scripts/ring_study.py measure [--wav]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.sim import fast, io

CORES = ["ja"]
HERE = Path(__file__).parents[1] / "reports" / "tube_synth" / "ring"
P = 'source: "provisional: model knowledge (design: the ring prototype)"'

DIODES = {
    # name: (component, area or None)
    "selenium": ("SELENIUM@1", 0.25),
    "silicon": ("SI_RECTIFIER@1", None),
}


def core_circuit(diode: str, area: float | None, turns: float, sec_ratio: float) -> Path:
    area_line = f", area: {{value: {area}, {P}}}" if area is not None else ""
    src = f"""title: "Diode ring (prototype)"
input: in
probes: [out, ct1, r1, r2, q1, q2]
controls:
  carrier_v: {{value: 1.0, min: 0.0, max: 20.0, unit: V, {P}}}
  carrier_hz: {{value: 620.0, min: 1.0, max: 20000.0, unit: Hz, {P}}}
values:
  r_src_ohm: {{value: 600.0, {P}}}
  c_couple_f: {{value: 10.0e-6, {P}}}
  r_wind_ohm: {{value: 50.0, {P}}}
  c_wind_f: {{value: 100.0e-12, {P}}}
  turns: {{value: {turns}, {P}}}
  sec_ratio: {{value: {sec_ratio}, {P}}}
  leak_h: {{value: 1.0e-3, {P}}}
  area_m2: {{value: 0.5e-4, {P}}}
  path_m: {{value: 0.06, {P}}}
  gap_m: {{value: 0.0, {P}}}
  r_load_ohm: {{value: 10.0e+3, {P}}}
  c_node_f: {{value: 100.0e-12, {P}}}
  diode: {{value: "{diode}", {P}}}
devices:
  D: {{device: diode{area_line}}}
sections:
  - title: ring
    parts:
      RS: {{R: [in, sp], r: r_src_ohm}}
      CS: {{C: [sp, spc], c: c_couple_f}}
      T1:
        transformer:
          pri: {{nodes: [spc, "0"], r: r_wind_ohm, c: c_wind_f}}
          sa: {{nodes: [r1, ct1], ratio: sec_ratio, r: r_wind_ohm}}
          sb: {{nodes: [ct1, r2], ratio: sec_ratio, r: r_wind_ohm}}
        core: {{material: mumetall, area_m2: area_m2, path_m: path_m, gap_m: gap_m}}
        turns: turns
        leakage_h: leak_h
      VC: {{sine: [cv, "0"], amplitude_v: carrier_v, freq_hz: carrier_hz}}
      RC: {{R: [cv, ct1], r: r_src_ohm}}
      CR1: {{C: [r1, "0"], c: c_node_f}}
      CR2: {{C: [r2, "0"], c: c_node_f}}
      CQ1: {{C: [q1, "0"], c: c_node_f}}
      CQ2: {{C: [q2, "0"], c: c_node_f}}
      D1: {{device: [r1, q1], model: D}}
      D2: {{device: [q1, r2], model: D}}
      D3: {{device: [r2, q2], model: D}}
      D4: {{device: [q2, r1], model: D}}
      T2:
        transformer:
          pri: {{nodes: [out, "0"], r: r_wind_ohm, c: c_wind_f}}
          sa: {{nodes: [q1, ct2], ratio: sec_ratio, r: r_wind_ohm}}
          sb: {{nodes: [ct2, q2], ratio: sec_ratio, r: r_wind_ohm}}
        core: {{material: mumetall, area_m2: area_m2, path_m: path_m, gap_m: gap_m}}
        turns: turns
        leakage_h: leak_h
      RCT2: {{R: [ct2, "0"], r: r_wind_ohm}}
      RLD: {{R: [out, "0"], r: r_load_ohm}}
"""
    HERE.mkdir(parents=True, exist_ok=True)
    out = HERE / f"ring_core_{diode.split('@')[0].lower()}.yaml"
    out.write_text(src, encoding="utf-8")
    return out


def tone_db(y: np.ndarray, fs: float, f: float) -> float:
    """Peak amplitude (dB re 1 V) of the tone at f, by lock-in in a Hann window."""
    n = len(y)
    w = np.hanning(n)
    t = np.arange(n) / fs
    a = 2.0 * abs(np.sum(y * w * np.exp(-2j * np.pi * f * t))) / np.sum(w)
    return 20.0 * np.log10(max(a, 1e-12))


def others_db(y: np.ndarray, fs: float, keep: list[float], ref_db: float) -> float:
    """The power not within +-3 Hz of the `keep` tones, re a tone at ref_db (peak)."""
    n = len(y)
    w = np.hanning(n)
    s = np.fft.rfft(y * w)
    f = np.fft.rfftfreq(n, 1.0 / fs)
    m = np.ones_like(f, bool)
    m[f < 20.0] = False
    for k in keep:
        m[np.abs(f - k) < 3.0] = False
    # Hann's power gain is 3/8 of the window's length; peak^2 / 2 is a sine's power.
    p = 2.0 * np.sum(np.abs(s[m]) ** 2) / (n * np.sum(w**2))
    ref = 10.0 ** (ref_db / 10.0) / 2.0
    return 10.0 * np.log10(max(p, 1e-30) / ref)


def run_core(path: Path, carrier_v: float, fs_hz: float, fc_hz: float, sig_v: float, dur_s: float):
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(path)
    ir = builder.build_ir(
        s,
        spec.resolve(s, {"carrier_v": carrier_v, "carrier_hz": fc_hz}),
        cores=CORES[0],
        noise=False,
    )
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        settle_s=0.2,
    )
    n = int(dur_s * fs)
    x = sig_v * np.sin(2 * np.pi * fs_hz * np.arange(n) / fs)
    t0 = time.perf_counter()
    v = fast.run_transient(ir, x, settings=st).vectors
    wall = time.perf_counter() - t0
    k = slice(int(0.25 * fs), n)
    return v["v(out)"][k], wall, fs


def core(a):
    fs_hz, fc_hz = a.signal_hz, a.carrier_hz
    rows = []
    for name, (comp, area) in DIODES.items():
        path = core_circuit(comp, area, a.turns, a.sec_ratio)
        for cv in a.carrier:
            y, wall, fs = run_core(path, cv, fs_hz, fc_hz, a.signal_v, a.seconds)
            sig_in_db = 20 * np.log10(a.signal_v)
            lo, hi = abs(fs_hz - fc_hz), fs_hz + fc_hz
            prod = max(tone_db(y, fs, lo), tone_db(y, fs, hi))
            row = {
                "diode": name,
                "carrier_v": cv,
                "product_db_re_signal": round(prod - sig_in_db, 1),
                "sum_diff_db": [
                    round(tone_db(y, fs, lo) - prod, 1),
                    round(tone_db(y, fs, hi) - prod, 1),
                ],
                "carrier_bleed_db": round(tone_db(y, fs, fc_hz) - prod, 1),
                "signal_bleed_db": round(tone_db(y, fs, fs_hz) - prod, 1),
                "3fc_db": round(
                    max(tone_db(y, fs, 3 * fc_hz - fs_hz), tone_db(y, fs, 3 * fc_hz + fs_hz))
                    - prod,
                    1,
                ),
                "others_db": round(others_db(y, fs, [lo, hi], prod), 1),
                "out_pk_v": round(float(np.max(np.abs(y))), 3),
                "wall_per_s": round(wall / (a.seconds + 0.2), 3),
            }
            rows.append(row)
            print(row, flush=True)
    out = HERE / f"core{a.tag}.json"
    out.write_text(json.dumps({"args": vars(a), "rows": rows}, indent=1))
    print(f"-> {out}")


# --- The ring in the synth ---------------------------------------------------------------------

SYNTH = Path(__file__).parents[1] / "config" / "circuits" / "tube_synth.yaml"
# The prototypes (`synth`, ring_cpu.py) are variants of the synth before the ring was built.
PROTOTYPE_BASE = "0ec7a5a"
BASE_PARTITION = [
    "resonance", "|", "input", "filter", "cutoff", "envelope", "|", "oscillator", "pitch",
    "|", "lfo", "|", "power supply", "bias supply",
]  # fmt: skip
# The app's (varimu-app panel.rs), with the ring built.
PARTITION = [
    "resonance", "|", "input", "filter", "cutoff", "|", "envelope", "|", "ring", "|", "oscillator",
    "pitch", "|", "lfo", "|", "power supply", "bias supply",
]  # fmt: skip


def prototype_base() -> str:
    import subprocess

    return subprocess.run(
        ["git", "show", f"{PROTOTYPE_BASE}:config/circuits/tube_synth.yaml"],
        capture_output=True, text=True, check=True, cwd=SYNTH.parents[2], encoding="utf-8",
    ).stdout  # fmt: skip


def prototype_path() -> Path:
    """The synth before the ring, as a file (the prototypes' baseline)."""
    HERE.mkdir(parents=True, exist_ok=True)
    out = HERE / "synth_base.yaml"
    out.write_text(prototype_base(), encoding="utf-8")
    return out


def _section(src: str, title: str) -> str:
    i = src.index(f"  - title: {title}\n")
    j = src.find("\n  - title: ", i + 1)
    return src[i : (len(src) if j < 0 else j + 1)]


def ring_parts(carrier_node: str) -> str:
    """The ring section: the oscillator's buffer into T1, the carrier into T1's centre tap,
    T2's output through the RING pot into the mixer."""
    return f"""  - title: ring
    parts:
      # The ring's drivers: a 12AU7 follower per input, each grid through 0.1 uF
      # (no load on the oscillator's buffer, the partition's coupling node)
      CRGIA: {{C: [o_buf, rg_ga], c: rg_c_grid_f}}
      RRGGA: {{R: [rg_ga, "0"], r: rg_r_grid_ohm}}
      XRVA: {{device: [b3, rg_ga, rg_ka], model: RVA}}
      RRGKA: {{R: [rg_ka, neg], r: rg_r_follower_ohm}}
      CRGIB: {{C: [{carrier_node}, rg_gb], c: rg_c_grid_f}}
      RRGGB: {{R: [rg_gb, "0"], r: rg_r_grid_ohm}}
      XRVB: {{device: [b3, rg_gb, rg_kb], model: RVB}}
      RRGKB: {{R: [rg_kb, neg], r: rg_r_follower_ohm}}
      CRGS: {{C: [rg_ka, rg_sc], c: rg_c_couple_f}}
      RRGS: {{R: [rg_sc, rg_sp], r: rg_r_src_ohm}}
      RGT1:
        transformer:
          pri: {{nodes: [rg_sp, "0"], r: rg_r_wind_ohm, c: rg_c_wind_f}}
          sa: {{nodes: [rg_r1, rg_ct1], ratio: rg_sec_ratio, r: rg_r_wind_ohm}}
          sb: {{nodes: [rg_ct1, rg_r2], ratio: rg_sec_ratio, r: rg_r_wind_ohm}}
        core: {{material: mumetall, area_m2: rg_area_m2, path_m: rg_path_m, gap_m: rg_gap_m}}
        turns: rg_turns
        leakage_h: rg_leak_h
      CRGC: {{C: [rg_kb, rg_cc], c: rg_c_couple_f}}
      RRGC: {{R: [rg_cc, rg_ct1], r: rg_r_carrier_ohm}}
      RRGCL: {{R: [rg_ct1, "0"], r: rg_r_ct_return_ohm}}
      CRR1: {{C: [rg_r1, "0"], c: rg_c_node_f}}
      CRR2: {{C: [rg_r2, "0"], c: rg_c_node_f}}
      CRQ1: {{C: [rg_q1, "0"], c: rg_c_node_f}}
      CRQ2: {{C: [rg_q2, "0"], c: rg_c_node_f}}
      DRG1: {{device: [rg_r1, rg_q1], model: DRG}}
      DRG2: {{device: [rg_q1, rg_r2], model: DRG}}
      DRG3: {{device: [rg_r2, rg_q2], model: DRG}}
      DRG4: {{device: [rg_q2, rg_r1], model: DRG}}
      RGT2:
        transformer:
          pri: {{nodes: [rg_out, "0"], ratio: rg_out_ratio, r: rg_r_wind_ohm, c: rg_c_wind_f}}
          sa: {{nodes: [rg_q1, rg_ct2], ratio: rg_sec_ratio, r: rg_r_wind_ohm}}
          sb: {{nodes: [rg_ct2, rg_q2], ratio: rg_sec_ratio, r: rg_r_wind_ohm}}
        core: {{material: mumetall, area_m2: rg_area_m2, path_m: rg_path_m, gap_m: rg_gap_m}}
        turns: rg_turns
        leakage_h: rg_leak_h
      RRGCT: {{R: [rg_ct2, "0"], r: rg_r_wind_ohm}}
      RRGLD: {{R: [rg_out, "0"], r: rg_r_load_ohm}}
      RRGP: {{pot: ["0", rg_w, rg_out], r: rg_r_pot_ohm, at: ring}}
      RRGX: {{R: [rg_w, rg_x], r: rg_r_x_ohm}}
      CRGX: {{C: [rg_x, "0"], c: rg_c_x_f}}
"""


def synth_variant(a, option: str) -> Path:
    src = prototype_base()

    def rep(x, y, count=1):
        nonlocal src
        assert src.count(x) == count, (x, src.count(x))
        src = src.replace(x, y)

    comp, area = DIODES[a.diode]
    area_line = f", area: {{value: {area}, {P}}}" if area is not None else ""
    rep(
        "  wave: {value: 0.5,",
        f"  ring: {{value: {a.ring}, min: 0.0, max: 1.0, unit: rotation, {P}}}\n"
        f"  wave2: {{value: {a.wave2}, min: 0.0, max: 1.0, unit: rotation, {P}}}\n"
        "  wave: {value: 0.5,",
    )
    rep(
        "  osc_r_buffer_cathode_ohm:",
        f"  rg_c_couple_f: {{value: 1.0e-6, {P}}}\n"
        f"  rg_r_src_ohm: {{value: 2.2e+3, {P}}}\n"
        f"  rg_r_carrier_ohm: {{value: {a.r_carrier:.6e}, {P}}}\n"
        f"  rg_r_wind_ohm: {{value: 50.0, {P}}}\n"
        f"  rg_r_ct_return_ohm: {{value: {a.r_ct_return:.6e}, {P}}}\n"
        f"  rg_c_wind_f: {{value: 100.0e-12, {P}}}\n"
        f"  rg_turns: {{value: 1000.0, {P}}}\n"
        f"  rg_sec_ratio: {{value: 1.0, {P}}}\n"
        f"  rg_out_ratio: {{value: 2.0, {P}}}\n"
        f"  rg_leak_h: {{value: 1.0e-3, {P}}}\n"
        f"  rg_area_m2: {{value: 0.5e-4, {P}}}\n"
        f"  rg_path_m: {{value: 0.06, {P}}}\n"
        f"  rg_gap_m: {{value: 0.0, {P}}}\n"
        f"  rg_c_node_f: {{value: 100.0e-12, {P}}}\n"
        f"  rg_r_pot_ohm: {{value: 100.0e+3, {P}}}\n"
        f"  rg_r_x_ohm: {{value: 4.7e+3, {P}}}\n"
        f"  rg_c_grid_f: {{value: 0.1e-6, {P}}}\n"
        f"  rg_r_grid_ohm: {{value: 1.0e+6, {P}}}\n"
        f"  rg_r_follower_ohm: {{value: 22.0e+3, {P}}}\n"
        f"  rg_r_load_ohm: {{value: {a.r_load:.6e}, {P}}}\n"
        f"  rg_c_x_f: {{value: 2.2e-9, {P}}}\n"
        f"  rg_r_mix_ohm: {{value: 1.0e+6, {P}}}\n"
        f"  osc2_c_tank_f: {{value: {a.c_tank2:.6e}, {P}}}\n"
        f'  ring_diode: {{value: "{comp}", {P}}}\n'
        "  osc_r_buffer_cathode_ohm:",
    )
    if not getattr(a, "no_ring", False):
        rep(
            "  DLR: {device: lfo_rectifier}",
            f"  DLR: {{device: lfo_rectifier}}\n  DRG: {{device: ring_diode{area_line}}}\n"
            "  RVA: {device: 12AU7@1}\n  RVB: {device: 12AU7@1}",
        )
    # The ring's output into the mixer (the mixer's input section, with the oscillator's).
    rep(
        '      CMIX: {C: [mix, "0"], c: c_mix_stray_f}\n',
        '      CMIX: {C: [mix, "0"], c: c_mix_stray_f}\n'
        "      RMXR: {R: [rg_x, mix], r: rg_r_mix_ohm}\n",
    )
    if a.osc_off:
        rep("  r_mix_osc_ohm: {value: 1.0e+6,", "  r_mix_osc_ohm: {value: 1.0e+12,")
    carrier = {"vco2": "o2_buf", "in": "in", "lfo": "lfo"}[option]
    if option == "vco2":
        osc = _section(src, "oscillator") + _section(src, "pitch")
        osc = osc.replace("title: oscillator", "title: oscillator 2").replace(
            "title: pitch", "title: pitch 2"
        )
        import re

        osc = re.sub(r"\bo_", "o2_", osc)
        osc = re.sub(r"^(      [A-Z][A-Z0-9]*):", r"\g<1>2:", osc, flags=re.M)
        osc = osc.replace("model: OV", "model: OW").replace("at: wave}", "at: wave2}")
        osc = osc.replace("c: osc_c_tank_f}", "c: osc2_c_tank_f}")
        rep("  LV1A: {device: 12AX7@1}", "  OW1A: {device: 12AU7@1}\n  OW1B: {device: 12AU7@1}\n"
            "  OW2: {device: 12AX7@1}\n  OW3: {device: 12AX7@1}\n  OW4: {device: 6V6GT@1}\n"
            "  LV1A: {device: 12AX7@1}")  # fmt: skip
        # Its pitch driver's grid from the glide node, a stopper of its own (the first thread).
        rep(
            "      ROPS: {R: [o_pg, o_g4], r: osc_r_pitch_stop_ohm}\n",
            "      ROPS: {R: [o_pg, o_g4], r: osc_r_pitch_stop_ohm}\n"
            "      ROPS2: {R: [o_pg, o2_g4], r: osc_r_pitch_stop_ohm}\n",
        )
        src = src.rstrip("\n") + "\n" + osc
    if option == "lfo":
        rep("  lfo_c_wien_f: {value: 1.0e-6,", f"  lfo_c_wien_f: {{value: {a.c_wien:.6e},")
        rep("  lfo_c_comp_f: {value: 1.0e-9,", f"  lfo_c_comp_f: {{value: {a.c_comp:.6e},")
    if getattr(a, "no_ring", False):
        # The ring's parts out (its output's mixer resistor to ground instead).
        rep("RMXR: {R: [rg_x, mix]", 'RMXR: {R: ["0", mix]')
    else:
        src = src.rstrip("\n") + "\n" + ring_parts(carrier)
    out = HERE / f"synth_{option}_{a.diode}{'_noring' if getattr(a, 'no_ring', False) else ''}.yaml"
    out.write_text(src, encoding="utf-8")
    return out


def partition_for(option: str, ring_alone: bool | str, ring: bool = True) -> list[str]:
    p = list(BASE_PARTITION)
    if not ring:
        if option == "vco2":
            i = p.index("lfo")
            p[i:i] = ["oscillator 2", "pitch 2", "|"]
        return p
    if option == "vco2":
        i = p.index("lfo")
        p[i:i] = ["oscillator 2", "pitch 2", "|"]
    if ring_alone == "osc":
        p.insert(p.index("pitch") + 1, "ring")
    elif ring_alone == "osc2":
        p.insert(p.index("pitch 2") + 1, "ring")
    elif ring_alone:
        # Ahead of the oscillators: a shared node's owner is the highest-numbered group.
        i = p.index("oscillator")
        p[i:i] = ["ring", "|"]
    else:
        p.insert(p.index("envelope") + 1, "ring")
    return p


def run_synth(path, sets, pitch_v, dur_s, partition, probes, carrier_in=None, keep_s=None):
    from varimu.circuit.ir import VoltageProbe

    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(path)
    ir = builder.build_ir(s, spec.resolve(s, sets), cores="ja", noise=False)
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=tuple(partition) if partition else (),
    )
    n = int(dur_s * fs)
    ctl = {
        "gate": np.full(n, -1.0),
        "pitch": np.full(n, pitch_v),
        "key": np.zeros(n),
        "pressure": np.zeros(n),
    }
    x = np.zeros(n) if carrier_in is None else carrier_in(np.arange(n) / fs)
    t0 = time.perf_counter()
    v = fast.run_transient(ir, x, settings=st, controls=ctl).vectors
    wall = time.perf_counter() - t0
    k = slice(int(0.5 * fs) if keep_s is None else n - int(keep_s * fs), n)
    return {p: v[f"v({p})"][k] for p in probes}, wall, fs


def synth(a):
    from varimu.synth import vco

    rows = []
    path = synth_variant(a, a.option)
    probes = ["out", "o_t", "rg_out", "b1"]
    if a.option == "vco2":
        probes.append("o2_t")
    if a.option == "lfo":
        probes.append("lfo")
    carrier_in = None
    if a.option == "in":
        carrier_in = lambda t: a.in_v * np.sin(2 * np.pi * a.in_hz * t)  # noqa: E731
    sets = {"lfo_rate": a.lfo_rate} if a.option == "lfo" else {}
    for pv in a.pitch:
        part = None if a.one_solve else partition_for(a.option, a.ring_alone)
        r, wall, fs = run_synth(path, sets, pv, a.seconds, part, probes, carrier_in)
        f1 = vco.frequency(r["o_t"], fs)
        carrier = {"vco2": "o2_t", "lfo": "lfo"}.get(a.option)
        f2 = a.in_hz if carrier is None else vco.frequency(r[carrier], fs)
        y = r["out"]
        lo, hi = abs(f1 - f2), f1 + f2
        prod = max(tone_db(y, fs, lo), tone_db(y, fs, hi))
        row = {
            "option": a.option,
            "diode": a.diode,
            "pitch_v": pv,
            "f1": round(f1, 2),
            "f2": round(f2, 2),
            "ratio": round(f2 / f1, 4),
            "out_pk": round(float(np.max(np.abs(y))), 3),
            "ring_out_pk": round(float(np.max(np.abs(r["rg_out"]))), 3),
            "out_f1_db_re_product": round(tone_db(y, fs, f1) - prod, 1),
            "out_f2_db_re_product": round(tone_db(y, fs, f2) - prod, 1),
            "b1_mean": round(float(np.mean(r["b1"])), 2),
            "wall_s": round(wall, 2),
            "dur_s": a.seconds,
        }
        rows.append(row)
        print(row, flush=True)
        if a.wav:
            import soundfile as sf

            (HERE / "audio").mkdir(parents=True, exist_ok=True)
            w = y / max(1e-9, np.max(np.abs(y))) * 0.5
            sf.write(
                HERE / "audio" / f"{a.option}_{a.diode}_{a.tag}_{pv:g}V.wav",
                w.astype(np.float32),
                int(fs),
            )
    out = HERE / f"synth_{a.option}_{a.diode}{a.tag}.json"
    out.write_text(json.dumps({"args": vars(a), "rows": rows}, indent=1))
    print(f"-> {out}")


def baseline(a):
    """The synth unchanged, for the wall time (the same partition and run)."""
    _, wall, _ = run_synth(prototype_path(), {}, -15.0, a.seconds, BASE_PARTITION, ["out", "b1"])
    print({"baseline_wall_s": round(wall, 2), "dur_s": a.seconds})


# --- The built ring (tube_synth.yaml's `ring` section and the LFO's AUDIO range) -----------------


def _lfo_row(r, fs, sets) -> dict:
    from varimu.synth import vco

    y = r["lfo"]
    f = vco.frequency(y, fs)
    h = vco.harmonics_db(y, fs, f, 6)
    thd = 100.0 * float(np.sqrt(np.sum(10.0 ** (np.asarray(h[1:]) / 10.0))))
    return {
        **sets,
        "lfo_hz": round(f, 2),
        "lfo_pk_v": round(float(0.5 * np.ptp(y)), 2),
        "lfo_dc_v": round(float(y.mean()), 2),
        "lfo_thd_pct": round(thd, 2),
    }


def measure(a):
    """The LFO's AUDIO range, the ring's product and bleeds with a key held, and what turning
    the ring on moves (the pitch, the LFO's rate, its supply) -> reports/tube_synth/ring/."""
    from varimu.synth import vco

    out = {}
    # 1. The LFO's rate law, LOW (as before) and AUDIO, no key, the last second of 4.
    path = HERE / "built.json"
    if a.skip_lfo and path.exists():
        out = {k: v for k, v in json.loads(path.read_text()).items() if k == "lfo"}
    rows = []
    for audio, rates in () if a.skip_lfo else ((0, [0.7]), (1, [0.0, 0.25, 0.5, 0.75, 1.0])):
        for rate in rates:
            sets = {"lfo_audio": audio, "lfo_rate": rate}
            r, _, fs = run_synth(SYNTH, sets, -15.0, 4.0, PARTITION, ["lfo"], keep_s=1.0)
            rows.append(_lfo_row(r, fs, sets))
            print(rows[-1], flush=True)
    if not a.skip_lfo:
        out["lfo"] = rows
    # 2. The ring alone (OSC 0) against the oscillator alone (RING off), a key held.
    rows = []
    pr = ["out", "o_t", "lfo"]
    for pv in a.pitch:
        r0, _, fs = run_synth(SYNTH, {}, pv, 2.0, PARTITION, pr, keep_s=1.0)
        osc_pk = float(np.max(np.abs(r0["out"])))
        for audio, rate in ((1, 0.5), (1, 0.75), (1, 0.9), (0, 0.85)):
            sets = {"ring_on": 1, "osc_level": 0.0, "lfo_audio": audio, "lfo_rate": rate}
            r, _, fs = run_synth(SYNTH, sets, pv, 3.0, PARTITION, pr, keep_s=1.0)
            y = r["out"]
            f1, f2 = vco.frequency(r["o_t"], fs), vco.frequency(r["lfo"], fs)
            prod = max(tone_db(y, fs, abs(f1 - f2)), tone_db(y, fs, f1 + f2))
            rows.append({
                "pitch_v": pv, **sets, "f1": round(f1, 1), "f2": round(f2, 2),
                "ring_pk_db_re_osc": round(20 * np.log10(np.max(np.abs(y)) / osc_pk), 1),
                "osc_bleed_db": round(tone_db(y, fs, f1) - prod, 1),
                "carrier_bleed_db": round(tone_db(y, fs, f2) - prod, 1),
            })  # fmt: skip
            print(rows[-1], flush=True)
            if a.wav:
                import soundfile as sf

                (HERE / "audio").mkdir(parents=True, exist_ok=True)
                w = (y / max(1e-9, np.max(np.abs(y))) * 0.5).astype(np.float32)
                tag = f"{'audio' if audio else 'low'}{rate}"
                sf.write(HERE / "audio" / f"built_{tag}_{pv:g}V.wav", w, int(fs))
    out["ring"] = rows
    # 3. What the ring's switch moves: the pitch, the LFO, its supply (key held, LOW 0.7).
    rows = []
    pr = ["o_t", "lfo", "lf_n", "lf_nr", "lf_br", "lf_bp", "b1"]
    for on in (0, 1):
        r, _, fs = run_synth(SYNTH, {"ring_on": on}, -15.0, 6.0, PARTITION, pr, keep_s=2.0)
        rows.append({
            "ring_on": on,
            "pitch_hz": round(vco.frequency(r["o_t"], fs), 3),
            **_lfo_row(r, fs, {}),
            **{f"{p}_mean_v": round(float(r[p].mean()), 2) for p in pr[2:]},
            "lf_n_ripple_pp_v": round(float(np.ptp(r["lf_n"])), 2),
        })  # fmt: skip
        print(rows[-1], flush=True)
    out["switch"] = rows
    path = HERE / "built.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"-> {path}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("core")
    c.add_argument("--carrier", nargs="*", type=float, default=[0.3, 1.0, 3.0, 10.0])
    c.add_argument("--signal-v", type=float, default=1.0)
    c.add_argument("--signal-hz", type=float, default=440.0)
    c.add_argument("--carrier-hz", type=float, default=620.0)
    c.add_argument("--turns", type=float, default=1000.0)
    c.add_argument("--sec-ratio", type=float, default=1.0)
    c.add_argument("--seconds", type=float, default=1.0)
    c.add_argument("--cores", default="ja")
    c.add_argument("--tag", default="")
    s = sub.add_parser("synth")
    s.add_argument("--option", choices=["vco2", "in", "lfo"], required=True)
    s.add_argument("--diode", choices=list(DIODES), default="silicon")
    s.add_argument("--pitch", nargs="*", type=float, default=[-20.0, -15.0, -10.0])
    s.add_argument("--seconds", type=float, default=1.5)
    s.add_argument("--ring", type=float, default=1.0)
    s.add_argument("--wave2", type=float, default=0.0)
    s.add_argument("--c-tank2", type=float, default=28.0e-9)
    s.add_argument("--r-carrier", type=float, default=2.2e3)
    s.add_argument("--r-ct-return", type=float, default=22.0e3)
    s.add_argument("--r-load", type=float, default=2.4e3)
    s.add_argument("--c-wien", type=float, default=10.0e-9)
    s.add_argument("--c-comp", type=float, default=100.0e-12)
    s.add_argument("--lfo-rate", type=float, default=0.5)
    s.add_argument("--in-v", type=float, default=1.0)
    s.add_argument("--in-hz", type=float, default=620.0)
    s.add_argument("--osc-off", action="store_true")
    s.add_argument("--ring-alone", nargs="?", const=True, default=False)
    s.add_argument("--one-solve", action="store_true")
    s.add_argument("--wav", action="store_true")
    s.add_argument("--tag", default="")
    m = sub.add_parser("measure")
    m.add_argument("--pitch", nargs="*", type=float, default=[-20.0, -15.0, -10.0])
    m.add_argument("--wav", action="store_true")
    m.add_argument("--skip-lfo", action="store_true")
    b = sub.add_parser("baseline")
    b.add_argument("--seconds", type=float, default=1.5)
    a = ap.parse_args()
    CORES[0] = getattr(a, "cores", "ja")
    {"core": core, "synth": synth, "baseline": baseline, "measure": measure}[a.cmd](a)


if __name__ == "__main__":
    main()

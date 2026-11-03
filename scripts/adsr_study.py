"""Tube synth, SYNTH_IDEAS.md #15 (ADSR): the prototype, its bench and the built envelope.

The attack can't just charge from the keyboard bus while the key is down (that was the AR
envelope: it holds the top): it has to end at the peak. The design (tube_synth.yaml's
envelope section, its header):
  ESA   12AU7 section, the attack follower: plate ~+43 V through ATTACK, grid clamped to the
        bus by a 6AL5, cathode the envelope: it charges toward the bus (the peak follows
        velocity) and cuts off within a volt or two of it
  ECMP  12AX7 section, the comparator: grid the envelope (22M), cathode the bus: it conducts
        once the envelope nears the top
  EINV  12AU7 section, inverting the comparator's plate; its plate's divider is the latch
        node, fed back into the comparator's grid through a 6AL5 (it holds the comparator on
        until the next key down, when the comparator's cathode jumps with the bus and lets
        go) and, through its own divider and an RC, the decay switch's grid
  EINV2 12AU7 section, inverting again for the attack follower's grid: the attack is cut only
        after the latch has engaged (driven from the comparator's plate, a slow attack
        stalled in the comparator's linear region)
  EDS   12AU7 section, the decay switch: the envelope through DECAY into its plate, its
        cathode the SUSTAIN pot's wiper
  RELEASE as before (a 6X4 section to the bus, conducting only with the key up)
A -340 V rail (a silicon diode off the HV winding, an RC) sits under the dividers.

Modes:
  (default)  a variant of the synth before the ADSR (PROTOTYPE_BASE) with the prototype's
             envelope, `--case ...`, `--wav`; the resistor ratios are arguments
  --bench    the envelope alone on ideal rails (`--rails b1=270 ...`), every case scored:
             the sweeps that set the ratios and found the fragile corners
  --built    the cases on tube_synth.yaml itself (-> proto.json, takes under audio/)

    uv run --extra fast python scripts/adsr_study.py --built [--case pluck ...] [--wav]
    uv run --extra fast python scripts/adsr_study.py --bench [--rails b1=270 nn=-320]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io

HERE = Path(__file__).parents[1] / "reports" / "tube_synth" / "adsr"
SYNTH = CONFIG_DIR / "circuits" / "tube_synth.yaml"
# The prototype is a variant of the synth before the ADSR was built.
PROTOTYPE_BASE = "933ecf1"
PARTITION = (
    "resonance", "|", "input", "filter", "cutoff", "|", "envelope", "|", "ring", "|", "oscillator",
    "pitch", "|", "lfo", "|", "power supply", "bias supply",
)  # fmt: skip
P = 'source: "provisional: model knowledge (design: the ADSR prototype)"'
KEY_UP_V, KEY_DOWN_V = -110.0, -1.0

OLD_ENV = """      RATT: {rheostat: [ba, bd], r: r_attack_ohm, at: attack, taper_mid: env_taper_mid}
      XVDA: {device: [bd, env], model: VDA}
"""

NEW_ENV = """      RSVT: {R: [b3, sv], r: ad_r_sv_top_ohm}
      RSVB: {R: [sv, "0"], r: ad_r_sv_bot_ohm}
      CSV: {C: [sv, "0"], c: ad_c_sv_f}
      RATT: {rheostat: [sv, sa_p], r: r_attack_ohm, at: attack, taper_mid: env_taper_mid}
      XESA: {device: [sa_p, sa_g, env], model: ESA}
      RESAG: {R: [ep, sa_g], r: ad_r_sa_grid_ohm}
      XEDA: {device: [sa_g, ba], model: EDA}
      RINV2T: {R: [inv_p, inv2_g], r: ad_r_inv2_top_ohm}
      RINV2B: {R: [inv2_g, nn], r: ad_r_inv2_bot_ohm}
      XEINV2: {device: [inv2_p, inv2_g, "0"], model: EINV2}
      RINV2P: {R: [b1, inv2_p], r: ad_r_inv_plate_ohm}
      RECP: {R: [inv2_p, ep], r: ad_r_div_top_ohm}
      RECN: {R: [ep, nn], r: ad_r_div_bot_ohm}
      RECG: {R: [env, cmp_g], r: ad_r_cmp_grid_ohm}
      XECMP: {device: [cmp_p, cmp_g, ba], model: ECMP}
      RECPL: {R: [b1, cmp_p], r: ad_r_cmp_plate_ohm}
      RINVT: {R: [cmp_p, inv_g], r: ad_r_inv_top_ohm}
      RINVB: {R: [inv_g, nn], r: ad_r_inv_bot_ohm}
      XEINV: {device: [inv_p, inv_g, "0"], model: EINV}
      RINVP: {R: [b1, inv_p], r: ad_r_inv_plate_ohm}
      RDST: {R: [inv_p, ds_d], r: ad_r_ds_top_ohm}
      RDSB: {R: [ds_d, nn], r: ad_r_ds_bot_ohm}
      RDGT: {R: [inv_p, ds_e], r: ad_r_ds_top_ohm}
      RDGB: {R: [ds_e, nn], r: ad_r_dsg_bot_ohm}
      XEDE: {device: [ds_e, ba], model: EDE}
      RDSF: {R: [ds_e, ds_g], r: ad_r_ds_delay_ohm}
      CDSF: {C: [ds_g, "0"], c: ad_c_ds_delay_f}
      XEDB: {device: [ds_d, ba], model: EDB}
      CDSD: {C: [ds_d, "0"], c: ad_c_latch_f}
      XEDD: {device: [ds_d, cmp_g], model: EDD}
      RDECMIN: {R: [env, ds_q], r: ad_r_decay_min_ohm}
      RDEC: {rheostat: [ds_q, ds_p], r: ad_r_decay_ohm, at: decay, taper_mid: env_taper_mid}
      XEDS: {device: [ds_p, ds_g, sw], model: EDS}
      RSUSL: {R: [neg2, s_lo], r: ad_r_sus_low_ohm}
      RSUS: {pot: [s_lo, sw, s_hi], r: ad_r_sus_pot_ohm, at: sustain}
      RSUSH: {R: [s_hi, "0"], r: ad_r_sus_high_ohm}
      CSW: {C: [sw, "0"], c: ad_c_sustain_f}
"""


def variant(a) -> Path:
    import subprocess

    src = subprocess.run(
        ["git", "show", f"{PROTOTYPE_BASE}:config/circuits/tube_synth.yaml"],
        capture_output=True, text=True, check=True, cwd=SYNTH.parents[2], encoding="utf-8",
    ).stdout.replace("\r\n", "\n")  # fmt: skip

    def rep(x, y):
        nonlocal src
        assert src.count(x) == 1, x
        src = src.replace(x, y)

    rep(OLD_ENV, NEW_ENV)
    rep(
        "  release: {value: 0.4,",
        f"  decay: {{value: 0.3, min: 0.0, max: 1.0, unit: rotation, {P}}}\n"
        f"  sustain: {{value: 1.0, min: 0.0, max: 1.0, unit: rotation, {P}}}\n"
        "  release: {value: 0.4,",
    )
    vals = {
        "ad_r_sa_grid_ohm": 1.0e6,
        "ad_r_sv_top_ohm": 220.0e3,
        "ad_r_sv_bot_ohm": a.sv_bot,
        "ad_c_sv_f": 47.0e-6,
        "ad_r_div_top_ohm": a.div_top,
        "ad_r_div_bot_ohm": a.div_bot,
        "ad_r_cmp_grid_ohm": a.r_cmp_g,
        "ad_r_cmp_plate_ohm": a.r_cmp_p,
        "ad_r_inv_top_ohm": a.inv_top,
        "ad_r_inv_bot_ohm": a.inv_bot,
        "ad_r_inv_plate_ohm": a.inv_plate,
        "ad_r_inv2_top_ohm": a.inv2_top,
        "ad_r_inv2_bot_ohm": a.inv2_bot,
        "ad_r_ds_top_ohm": a.ds_top,
        "ad_r_ds_bot_ohm": a.ds_bot,
        "ad_r_dsg_bot_ohm": a.dsg_bot,
        "ad_r_ds_delay_ohm": 10.0e6,
        "ad_c_latch_f": a.c_latch,
        "ad_c_ds_delay_f": a.c_delay,
        "ad_r_decay_min_ohm": a.decay_min,
        "ad_r_decay_ohm": 4.7e6,
        "ad_r_sus_low_ohm": a.sus_low,
        "ad_r_sus_pot_ohm": 100.0e3,
        "ad_r_sus_high_ohm": 2.0e3,
        "ad_c_sustain_f": 1.0e-6,
        "nn_r_filter_ohm": 47.0e3,
        "nn_c_f": 4.7e-6,
    }
    lines = "".join(f"  {k}: {{value: {v:.6e}, {P}}}\n" for k, v in vals.items())
    rep("  # --- cutoff\n", lines + f'  adsr_diode: {{value: "6AL5@1", {P}}}\n  # --- cutoff\n')
    rep(
        "  VDR: {device: envelope_diode}\n",
        "  VDR: {device: envelope_diode}\n"
        "  ESA: {device: 12AU7@1}\n  EDS: {device: 12AU7@1}\n  ECMP: {device: 12AX7@1}\n"
        "  EINV: {device: 12AU7@1}\n"
        "  EDA: {device: adsr_diode}\n  EDB: {device: adsr_diode}\n  EDD: {device: adsr_diode}\n"
        "  DNN: {device: lfo_rectifier}\n",
    )
    rep("  VDA: {device: envelope_diode}\n", "")
    # The -300 V rail: a silicon diode off the HV winding's first half, an RC.
    rep(
        '      CB4: {C: [b4, "0"], c: c_decouple_f}\n',
        '      CB4: {C: [b4, "0"], c: c_decouple_f}\n'
        "      DNNA: {device: [nn_r, hva], model: DNN}\n"
        '      CNNR: {C: [nn_r, "0"], c: nn_c_f}\n'
        "      RNN: {R: [nn_r, nn], r: nn_r_filter_ohm}\n"
        '      CNN: {C: [nn, "0"], c: nn_c_f}\n',
    )
    HERE.mkdir(parents=True, exist_ok=True)
    out = HERE / "adsr_proto.yaml"
    out.write_text(src, encoding="utf-8")
    return out


BENCH_RAILS = {"b1": 297.0, "b3": 205.0, "neg2": -105.0, "nn": -344.0}


def bench_circuit(a) -> Path:
    """The envelope alone on ideal rails (the synth's measured ones), for fast sweeps."""
    proto = variant(a).read_text(encoding="utf-8")
    vals = proto[proto.index("  ad_r_sa_grid_ohm") : proto.index("  # --- cutoff\n")]
    env = proto[proto.index("  - title: envelope\n") : proto.index("  - title: keyboard bus\n")]
    rails = "".join(f'      V{k.upper()}: {{V: [{k}, "0"], v: rail_{k}}}\n' for k in BENCH_RAILS)
    rail_vals = "".join(f"  rail_{k}: {{value: {v}, {P}}}\n" for k, v in BENCH_RAILS.items())
    src = f"""title: "ADSR bench"
input: in
cv_inputs:
  gate: bus
controls:
  attack: {{value: 0.0, min: 0.0, max: 1.0, unit: rotation, {P}}}
  decay: {{value: 0.3, min: 0.0, max: 1.0, unit: rotation, {P}}}
  sustain: {{value: 0.0, min: 0.0, max: 1.0, unit: rotation, {P}}}
  release: {{value: 0.2, min: 0.0, max: 1.0, unit: rotation, {P}}}
values:
  r_bus_ohm: {{value: 1.0e+3, {P}}}
  c_ba_f: {{value: 0.1e-6, {P}}}
  r_ba_leak_ohm: {{value: 1.0e+8, {P}}}
  r_attack_ohm: {{value: {a.r_attack:.6e}, {P}}}
  env_taper_mid: {{value: 0.1, {P}}}
  c_env_f: {{value: 0.47e-6, {P}}}
  r_env_leak_ohm: {{value: 1.0e+8, {P}}}
  r_release_min_ohm: {{value: 4.7e+3, {P}}}
  r_release_ohm: {{value: 4.7e+6, {P}}}
  r_in_ohm: {{value: 1.0e+6, {P}}}
  envelope_diode: {{value: "6X4@1", {P}}}
{rail_vals}{vals}  adsr_diode: {{value: "6AL5@1", {P}}}
devices:
  VDR: {{device: envelope_diode}}
  ESA: {{device: 12AU7@1}}
  EDS: {{device: 12AU7@1}}
  ECMP: {{device: 12AX7@1}}
  EINV: {{device: 12AU7@1}}
  EINV2: {{device: 12AU7@1}}
  EDA: {{device: adsr_diode}}
  EDB: {{device: adsr_diode}}
  EDD: {{device: adsr_diode}}
  EDE: {{device: adsr_diode}}
sections:
  - title: rails
    parts:
      RIN: {{R: [in, "0"], r: r_in_ohm}}
{rails}      RBUS: {{R: [bus, ba], r: r_bus_ohm}}
{env}"""
    out = HERE / "adsr_bench.yaml"
    out.write_text(src, encoding="utf-8")
    return out


def bench_run(path, sets, gate, dur_s):
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(path)
    ir = builder.build_ir(s, spec.resolve(s, sets), cores="ja", noise=False)
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in BENCH_PROBES))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        settle_s=0.2,
    )
    n = int(dur_s * fs)
    t = np.arange(n) / fs
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls={"gate": gate(t)}).vectors
    return {p: v[f"v({p})"] for p in BENCH_PROBES}, fs


BENCH_PROBES = ["env", "sw", "cmp_p", "sa_g", "ds_g", "ba", "inv_p", "inv2_p", "cmp_g", "ds_d"]


def bench_score(a, verbose=False) -> dict:
    """Each case: the peak, the envelope just before key up against the sustain node, the
    comparator's plate then (latched low), and the envelope after release."""
    path = bench_circuit(a)
    out = {}
    for name, (sets, on, off, dur, down) in CASES.items():
        r, fs = bench_run(path, sets, key(on, off, down), dur)
        np.savez(HERE / f"bench_{name}.npz", **r)
        t = np.arange(len(r["env"])) / fs
        held = (t >= on) & (t < off)
        j = int(off * fs) - 1
        pk = float(np.max(np.where(held, r["env"], -1e9)))
        out[name] = {
            "peak_v": round(pk, 2),
            "peak_ms": round(float(t[np.argmax(np.where(held, r["env"], -1e9))] - on) * 1e3, 1),
            "held_v": round(float(r["env"][j]), 2),
            "sw_v": round(float(r["sw"][j]), 2),
            "cmp_p_held": round(float(r["cmp_p"][j]), 1),
            "end_v": round(float(r["env"][-1]), 2),
        }
        if verbose:
            print(name, out[name], flush=True)
    sets, dur = RETRIGGER
    r, fs = bench_run(path, sets, retrigger_gate, dur)
    np.savez(HERE / "bench_retrigger.npz", **r)
    t = np.arange(len(r["env"])) / fs
    second = (t >= 0.17) & (t < 0.25)
    out["retrigger"] = {
        "first_peak_v": round(float(np.max(np.where(t < 0.15, r["env"], -1e9))), 2),
        "env_at_repress_v": round(float(r["env"][int(0.17 * fs)]), 2),
        "second_peak_v": round(float(np.max(np.where(second, r["env"], -1e9))), 2),
        "second_peak_ms": round(
            float(t[np.argmax(np.where(second, r["env"], -1e9))] - 0.17) * 1e3, 1
        ),
    }
    if verbose:
        print("retrigger", out["retrigger"], flush=True)
    # Legato: a second key at 0.4 s while the first is held (to 0.8 s), the keyboard's
    # bus lifted for `legato_gap_ms` there (0: single trigger, the bus stays down).
    gap = getattr(a, "legato_gap_ms", None)
    if gap is not None:
        for name, sets in (
            ("legato_pluck", {"attack": 0.0, "decay": 0.3, "sustain": 0.0, "release": 0.2}),
            ("legato_brass", {"attack": 0.5, "decay": 0.5, "sustain": 0.6, "release": 0.4}),
            ("legato_fast_release", {"attack": 0.0, "decay": 0.3, "sustain": 0.6, "release": 0.0}),
        ):
            g = gap * 1e-3

            def gate(t, g=g):
                down = (t >= 0.1) & (t < 0.8) & ~((t >= 0.4) & (t < 0.4 + g))
                return np.where(down, KEY_DOWN_V, KEY_UP_V)

            r, fs = bench_run(path, sets, gate, 1.0)
            t = np.arange(len(r["env"])) / fs
            second = (t >= 0.4) & (t < 0.7)
            out[name] = {
                "gap_ms": gap,
                "env_before_v": round(float(r["env"][int(0.399 * fs)]), 2),
                "dip_v": round(float(np.min(np.where((t >= 0.4) & (t < 0.41), r["env"], 1e9))), 2),
                "second_peak_v": round(float(np.max(np.where(second, r["env"], -1e9))), 2),
                "second_peak_ms": round(
                    float(t[np.argmax(np.where(second, r["env"], -1e9))] - 0.4) * 1e3, 1
                ),
                "held_v": round(float(r["env"][int(0.799 * fs)]), 2),
            }
            if verbose:
                print(name, out[name], flush=True)
    return out


PROBES = [
    "o_t",
    "sv",
    "ds_d",
    "ds_p",
    "ds_q",
    "sa_p",
    "env",
    "cmp_g",
    "cmp_p",
    "inv_g",
    "inv_p",
    "ds_g",
    "sa_g",
    "ep",
    "sw",
    "ba",
    "out",
    "nn",
    "b1",
]


def run(path, sets, gate, dur_s, probes=PROBES, pitch_v=-15.0):
    fs = io.load_sim_settings().sample_rate
    s = spec.load_circuit(path)
    ir = builder.build_ir(s, spec.resolve(s, sets), cores="ja", noise=False)
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(dur_s * fs)
    t = np.arange(n) / fs
    ctl = {
        "gate": gate(t),
        "pitch": np.full(n, pitch_v),
        "key": np.zeros(n),
        "pressure": np.zeros(n),
        "pitch2": np.zeros(n),
    }
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl).vectors
    return {p: v[f"v({p})"] for p in probes}, fs


def key(on_s, off_s, down_v=KEY_DOWN_V):
    return lambda t: np.where((t >= on_s) & (t < off_s), down_v, KEY_UP_V)


CASES = {
    # name: (settings, key down, key up, run length, key-down volts)
    "pluck": ({"attack": 0.0, "decay": 0.3, "sustain": 0.0, "release": 0.2}, 0.1, 0.6, 1.0, -1.0),
    "brass": ({"attack": 0.5, "decay": 0.5, "sustain": 0.6, "release": 0.4}, 0.1, 1.2, 2.0, -1.0),
    "organ": ({"attack": 0.0, "decay": 0.3, "sustain": 1.0, "release": 0.2}, 0.1, 0.6, 1.0, -1.0),
    "soft": ({"attack": 0.0, "decay": 0.3, "sustain": 0.0, "release": 0.2}, 0.1, 0.6, 1.0, -20.0),
    "slow": ({"attack": 1.0, "decay": 0.5, "sustain": 0.5, "release": 0.4}, 0.1, 2.6, 3.0, -1.0),
    "fast_decay": (
        {"attack": 0.0, "decay": 0.0, "sustain": 0.0, "release": 0.0},
        0.1,
        0.3,
        0.5,
        -1.0,
    ),
}

# Retrigger: a pluck, key up mid-decay, down again 20 ms later.
RETRIGGER = ({"attack": 0.0, "decay": 0.5, "sustain": 0.0, "release": 0.6}, 0.6)


def retrigger_gate(t):
    return np.where(((t >= 0.1) & (t < 0.15)) | (t >= 0.17), KEY_DOWN_V, KEY_UP_V)


def envelope_stats(r, fs, on_s, off_s):
    env, out = r["env"], r["out"]
    t = np.arange(len(env)) / fs
    held = (t >= on_s) & (t < off_s)
    i_pk = int(np.argmax(np.where(held, env, -1e9)))
    pk = float(env[i_pk])
    # The VCA's level, in 5 ms windows (rms re the loudest).
    w = int(0.005 * fs)
    rms = np.sqrt(np.convolve(out**2, np.ones(w) / w, mode="same"))
    db = 20 * np.log10(rms / rms.max() + 1e-12)
    j = int(off_s * fs)

    def first(mask):
        k = np.nonzero(mask)[0]
        return round(float(t[k[0]] - on_s) * 1e3, 1) if len(k) else None

    return {
        "peak_v": round(pk, 2),
        "peak_ms": round((t[i_pk] - on_s) * 1e3, 1),
        "env_at_key_up_v": round(float(env[j - 1]), 2),
        "env_end_v": round(float(env[-1]), 2),
        "level_minus20db_ms": first(held & (t > t[i_pk]) & (db < -20)),
        "level_minus40db_ms": first(held & (t > t[i_pk]) & (db < -40)),
        "ds_g_held_v": round(float(r["ds_g"][j - 1]), 2),
        "inv_g_v": [
            round(float(r["inv_g"][int(on_s * fs) + int(0.002 * fs)]), 1),
            round(float(r["inv_g"][j - 1]), 1),
        ],
        "inv_p_v": [
            round(float(r["inv_p"][int(on_s * fs) + int(0.002 * fs)]), 1),
            round(float(r["inv_p"][j - 1]), 1),
        ],
        "sw_v": round(float(r["sw"][j - 1]), 2),
        "sa_g_held_v": round(float(r["sa_g"][j - 1]), 2),
        "cmp_p_v": [
            round(float(r["cmp_p"][int(on_s * fs) + int(0.002 * fs)]), 1),
            round(float(r["cmp_p"][j - 1]), 1),
        ],
        "sa_g_attack_v": round(float(r["sa_g"][int(on_s * fs) + int(0.002 * fs)]), 2),
        "nn_v": round(float(r["nn"][-1]), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", nargs="*", default=list(CASES))
    ap.add_argument("--div-top", type=float, default=10.0e6)
    ap.add_argument("--div-bot", type=float, default=14.3e6)
    ap.add_argument("--r-cmp-p", type=float, default=1.0e6)
    ap.add_argument("--inv-top", type=float, default=12.0e6)
    ap.add_argument("--inv-bot", type=float, default=18.0e6)
    ap.add_argument("--ds-top", type=float, default=5.0e6)
    ap.add_argument("--ds-bot", type=float, default=9.31e6)
    ap.add_argument("--c-delay", type=float, default=220.0e-12)
    ap.add_argument("--inv-plate", type=float, default=330.0e3)
    ap.add_argument("--sv-bot", type=float, default=56.0e3)
    ap.add_argument("--c-latch", type=float, default=220.0e-12)
    ap.add_argument("--r-cmp-g", type=float, default=22.0e6)
    ap.add_argument("--wav", action="store_true")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--legato-gap-ms", type=float)
    ap.add_argument("--built", action="store_true")
    ap.add_argument("--rails", nargs="*", default=[])
    ap.add_argument("--slow-attack", type=float)
    ap.add_argument("--r-attack", type=float, default=1.5e6)
    ap.add_argument("--decay-min", type=float, default=39.0e3)
    ap.add_argument("--fast-decay", type=float)
    ap.add_argument("--inv2-top", type=float, default=12.0e6)
    ap.add_argument("--sus-low", type=float, default=100.0)
    ap.add_argument("--dsg-bot", type=float, default=7.87e6)
    ap.add_argument("--inv2-bot", type=float, default=20.0e6)
    a = ap.parse_args()
    if a.rails:
        for kv in a.rails:
            k, v = kv.split("=")
            BENCH_RAILS[k] = float(v)
    if a.slow_attack is not None:
        CASES["slow"][0]["attack"] = a.slow_attack
    if a.fast_decay is not None:
        CASES["fast_decay"][0]["decay"] = a.fast_decay
    if a.bench:
        res = bench_score(a, verbose=True)
        tag = "_".join(a.rails).replace("=", "") or "nominal"
        (HERE / f"bench_{tag}.json").write_text(
            json.dumps({"rails": BENCH_RAILS, "rows": res}, indent=1)
        )
        return
    path = SYNTH if a.built else variant(a)
    rows = {}
    for name in a.case:
        sets, on, off, dur, down = CASES[name]
        r, fs = run(path, sets, key(on, off, down), dur)
        rows[name] = {**sets, "down_v": down, **envelope_stats(r, fs, on, off)}
        print(name, rows[name], flush=True)
        np.savez(HERE / f"{name}.npz", **r)
        if a.wav:
            import soundfile as sf

            (HERE / "audio").mkdir(parents=True, exist_ok=True)
            y = r["out"] / max(1e-9, np.max(np.abs(r["out"]))) * 0.5
            sf.write(HERE / "audio" / f"{name}.wav", y.astype(np.float32), int(fs))
    (HERE / "proto.json").write_text(json.dumps({"args": vars(a), "rows": rows}, indent=1))


if __name__ == "__main__":
    main()

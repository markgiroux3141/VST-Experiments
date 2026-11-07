"""The Model D's keyboard circuit alone (config/circuits/minimoog_keyboard.yaml;
docs/MINIMOOG_PLAN.md
MM4): the current source's current (the string's volts a key), tracking through the sample-and-hold
and the glide follower, glide times over the GLIDE knob, the hold after key-up.

    uv run --extra fast python scripts/minimoog_keyboard_study.py [--only current track glide hold]
        [--write] [--quality production|draft-1x]

--write puts 10 ohm times the measured current into the circuit file's key_v_per_semitone (and
key_max_v, 43 steps), the volts the app's keys then put on the pitch bar. Writes
reports/minimoog/keyboard/summary.json."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.sim import fast
from varimu.sim.io import TransientSettings

FS = 96000.0
CIRCUIT = CONFIG_DIR / "circuits" / "minimoog_keyboard.yaml"
OUT = Path(__file__).resolve().parents[1] / "reports" / "minimoog" / "keyboard"
STEP_OHM = 10.0  # one key: Fig 9-7's 10 ohm 1% string resistor
KEYS = 43  # string steps from the low F to the top C


def load():
    return spec.load_circuit(CIRCUIT)


def value(s, key: str) -> float:
    return float(s.values[key]["value"])


def build(s, overrides: dict | None = None):
    return builder.build_ir(s, spec.resolve(s, overrides or {}), "ja")


def key_volts(s, note: int) -> float:
    v = (note - value(s, "key_ref_note")) * value(s, "key_v_per_semitone")
    return float(np.clip(v, value(s, "key_min_v"), value(s, "key_max_v")))


def run(ir, key, gate, quality="production", settle_s=0.2):
    """`key`, `gate`: arrays (volts at the pitch bar, on the trigger contact)."""
    st = dataclasses.replace(
        TransientSettings.from_sim_settings(engine="circuitsim", quality=quality), settle_s=settle_s
    )
    if quality != "production":
        st = dataclasses.replace(st, newton_reltol=1e-5, newton_vntol=1e-5)
    r = fast.run_transient(ir, np.zeros(len(key)), settings=st, controls={"key": key, "gate": gate})
    return {k[2:-1]: np.asarray(v) for k, v in r.vectors.items() if k.startswith("v(")}


def current(s) -> dict:
    """The string's current: V(top) / 430 ohm, and its volts a key."""
    n = int(0.05 * FS)
    v = run(build(s), np.zeros(n), np.full(n, value(s, "gate_on_v")))
    top = float(np.mean(v["top"][-480:]))
    i_a = top / value(s, "r_string_ohm")
    return {
        "string_top_v": top,
        "current_ma": 1e3 * i_a,
        "v_per_key": i_a * STEP_OHM,
        "q11_emitter_v": float(np.mean(v["b9"][-480:])),
        "q9_emitter_v": float(np.mean(v["e9"][-480:])),
    }


def track(s, quality="production") -> dict:
    """A key held at each A (MIDI 45, 57, 69, 81) and both ends: the output against the bar."""
    notes = [41, 45, 57, 69, 81, 84]
    rows = []
    ir = build(s)
    for note in notes:
        n = int(0.1 * FS)
        kv = key_volts(s, note)
        v = run(ir, np.full(n, kv), np.full(n, value(s, "gate_on_v")), quality)
        out = float(np.mean(v["out"][-480:]))
        rows.append({"note": note, "key_v": kv, "out_v": out, "offset_mv": 1e3 * (out - kv)})
        print(
            f"  note {note}: bar {kv:.4f} V -> out {out:.4f} V ({1e3 * (out - kv):+.2f} mV)",
            flush=True,
        )
    k = np.array([r["key_v"] for r in rows])
    o = np.array([r["out_v"] for r in rows])
    gain = float(np.polyfit(k, o, 1)[0])
    return {"rows": rows, "gain": gain, "cents_per_octave_from_gain": 1200 * (gain - 1.0)}


def glide_time(s, knob: float, on: int = 1, quality="production", up: bool = True) -> dict:
    """An octave step (low A -> the next A, or back) with the key held: 10-90 % and 1/e times."""
    lo, hi = key_volts(s, 45), key_volts(s, 57)
    a, b = (lo, hi) if up else (hi, lo)
    tau_guess = (330.0 + knob * 5e6) * 1e-6
    total = 0.15 + max(0.05, 8 * tau_guess)
    n = int(total * FS)
    i0 = int(0.1 * FS)
    key = np.full(n, a)
    key[i0:] = b
    gate = np.full(n, value(s, "gate_on_v"))
    v = run(build(s, {"glide": knob, "glide_on": on}), key, gate, quality)
    out = v["out"]
    o0, o1 = float(np.mean(out[i0 - 200 : i0])), float(out[-1])
    frac = (out[i0:] - o0) / (o1 - o0)
    t10 = np.argmax(frac > 0.1) / FS
    t90 = np.argmax(frac > 0.9) / FS
    te = np.argmax(frac > 1 - 1 / np.e) / FS
    return {
        "knob": knob,
        "on": on,
        "up": up,
        "t10_90_ms": 1e3 * (t90 - t10),
        "t_1e_ms": 1e3 * te,
        "start_v": o0,
        "end_v": o1,
    }


def glide(s, quality="production") -> dict:
    rows = [glide_time(s, 0.0, 0, quality)]
    for k in (0.0, 0.25, 0.5, 0.75, 1.0):
        rows.append(glide_time(s, k, 1, quality))
    rows.append(glide_time(s, 0.5, 1, quality, up=False))
    for r in rows:
        print(
            f"  GLIDE {'on ' if r['on'] else 'off'} {r['knob']:.2f} "
            f"{'up  ' if r['up'] else 'down'}: "
            f"1/e {r['t_1e_ms']:9.2f} ms, 10-90 % {r['t10_90_ms']:9.2f} ms "
            f"({r['start_v']:.3f} -> {r['end_v']:.3f} V)",
            flush=True,
        )
    return {"rows": rows}


def hold(s, quality="production") -> dict:
    """A key held 0.2 s then released (the bar keeps the last key, as the app does): the output's
    drift over the next 2 s, and a second key after 1 s of rest."""
    n = int(2.5 * FS)
    kv = key_volts(s, 69)
    key = np.full(n, kv)
    gate = np.full(n, value(s, "gate_off_v"))
    gate[int(0.1 * FS) : int(0.3 * FS)] = value(s, "gate_on_v")
    v = run(build(s, {"glide": 0.5, "glide_on": 1}), key, gate, quality)
    out = v["out"]
    at = {t: float(out[int(t * FS)]) for t in (0.05, 0.29, 0.32, 0.5, 1.0, 2.4)}
    print("  " + ", ".join(f"t {t:.2f} s: {o:.4f} V" for t, o in at.items()), flush=True)
    return {"key_v": kv, "out_at_s": at, "droop_mv_per_s": 1e3 * (at[2.4] - at[0.32]) / 2.08}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="*", default=["current", "track", "glide", "hold"])
    p.add_argument("--write", action="store_true")
    p.add_argument("--quality", default="production")
    a = p.parse_args()
    s = load()
    out: dict = {}
    if "current" in a.only or a.write:
        out["current"] = c = current(s)
        print(
            f"current source: {c['current_ma']:.4f} mA ({1e3 * c['v_per_key']:.3f} mV a key; "
            "Fig 9-7 8.33 mA, "
            f"Fig 9-17 8.48 mA); string top {c['string_top_v']:.4f} V",
            flush=True,
        )
        if a.write:
            text = CIRCUIT.read_text(encoding="utf-8")
            vk = round(c["v_per_key"], 6)
            for key, val in (("key_v_per_semitone", vk), ("key_max_v", round(KEYS * vk, 4))):
                text, nsub = re.subn(
                    rf"(\n  {key}: \{{value: )[0-9.eE+-]+", rf"\g<1>{val}", text, count=1
                )
                assert nsub == 1, key
            text = re.sub(
                r"current as this circuit measures it \([0-9.]+ mA",
                f"current as this circuit measures it ({c['current_ma']:.3f} mA",
                text,
            )
            CIRCUIT.write_text(text, encoding="utf-8")
            print(f"wrote key_v_per_semitone {vk} into {CIRCUIT}")
            s = load()
    if "track" in a.only:
        print("tracking (key held):")
        out["track"] = t = track(s, a.quality)
        print(f"  gain {t['gain']:.5f} ({t['cents_per_octave_from_gain']:+.2f} cents / octave)")
    if "glide" in a.only:
        print("glide (an octave, key held):")
        out["glide"] = glide(s, a.quality)
    if "hold" in a.only:
        print("hold (key released at 0.3 s, GLIDE on at 0.5):")
        out["hold"] = hold(s, a.quality)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The proxy's tables (docs/MIDI_TAKES_PLAN.md N2): what a cheap digital stand-in for
tube_synth follows the panel through, gathered from measurements of the real circuit.

The proxy (varimu-app's `proxy`) plays while the user records a take whose real render
comes later. It follows the panel through these tables, each with its source line:

- the filter: one law from V4's grid volts (`g4_v`) to a 2-pole low-pass (f0, Q), fitted
  row by row to the measured responses of `scripts/keytrack_study.py`
  (reports/tube_synth/keytrack/*.json: every row records g4 beside the response), and how
  each knob moves g4 (CUTOFF from its law rows, KEY TRACK and PRESSURE from their rows,
  WOBBLE from `lfo.json`);
- the VCA: the envelope's volts to the output's level (`velocity.json`: the keyboard bus's
  key-down volts against the level), and the absolute level at the panel's defaults;
- GLIDE's time constants from `glide.json` (the time to within 10 cents of a step);
- the LFO's rate per RATE (both ranges: `lfo.json`, `ring/built.json`), VIBRATO's depth,
  WOBBLE's swing;
- the ring modulator's level and bleeds (`ring/built.json`);
- the oscillator's harmonics per WAVE (`vco/lc.json`: the reactor-tuned LC measured on its
  own circuit, `vco_lc.yaml`, the synth's oscillator);
- the pots' tapers (the circuit file's `*_taper_mid` values: `varimu.circuit.parts.taper`).

Not measured yet, so provisional (each says so, with its design source): the envelope's
times per ATTACK / DECAY / RELEASE and SUSTAIN's level (the circuit file's design
comments), RESONANCE (the standalone tube filter's numbers, TUBE_SYNTH_PLAN.md S2), ENV
AMOUNT (TUBE_SYNTH_PLAN.md S5's measurement before the ADSR), the saw's level and shape
(HYBRID_PHYSICS_PLAN.md H4), the ring's band limits. A sweep for them is owed (N2's
done-when compares the proxy with the device).

    uv run python scripts/proxy_tables.py [--check]

Writes config/proxy/tube_synth.json (with the circuit file's sha256: the app warns when
the circuit has changed since). `--check` exits 1 when the file would change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "tube_synth"
CIRCUIT = ROOT / "config" / "circuits" / "tube_synth.yaml"
OUT = ROOT / "config" / "proxy" / "tube_synth.json"


def load(rel: str) -> dict:
    return json.loads((REPORTS / rel).read_text(encoding="utf-8"))


def lowpass_db(f: np.ndarray, f0: float, q: float) -> np.ndarray:
    """A 2-pole low-pass's magnitude (dB) at `f`."""
    w = f / f0
    return -10.0 * np.log10((1.0 - w**2) ** 2 + (w / q) ** 2)


def fit_lowpass(tones: np.ndarray, resp_db: np.ndarray) -> tuple[float, float, float]:
    """(f0, Q, rms error dB) of the 2-pole low-pass nearest a measured response (its gain
    below 300 Hz the reference), over the tones down to -30 dB."""
    ref = float(np.mean(resp_db[tones < 300.0]))
    r = resp_db - ref
    use = r > -30.0
    best = (0.0, 0.0, math.inf)
    for f0 in np.geomspace(100.0, 20_000.0, 400):
        for q in np.geomspace(0.2, 4.0, 60):
            e = float(np.sqrt(np.mean((lowpass_db(tones[use], f0, q) - r[use]) ** 2)))
            if e < best[2]:
                best = (float(f0), float(q), e)
    # Refine around the best.
    f0, q, _ = best
    for f in np.geomspace(f0 / 1.03, f0 * 1.03, 41):
        for qq in np.geomspace(q / 1.08, q * 1.08, 41):
            e = float(np.sqrt(np.mean((lowpass_db(tones[use], f, qq) - r[use]) ** 2)))
            if e < best[2]:
                best = (float(f), float(qq), e)
    return best


def filter_tables() -> dict:
    files = [
        "keytrack/law_before.json",
        "keytrack/track_0.5.json",
        "keytrack/track_1.json",
        "keytrack/pressure_0.json",
        "keytrack/pressure_7.5.json",
        "keytrack/pressure_15.json",
    ]
    points = []
    for name in files:
        d = load(name)
        tones = np.asarray(d["tones_hz"], float)
        for row in d["rows"]:
            f0, q, err = fit_lowpass(tones, np.asarray(row["response_db"], float))
            points.append((row["g4_v"], f0, q, err, row["cutoff_hz"]))
    points.sort()
    g4 = np.array([p[0] for p in points])
    f0 = np.array([p[1] for p in points])
    q = np.array([p[2] for p in points])
    err = np.array([p[3] for p in points])
    # One law: f0 and Q against g4, smoothed onto a grid (rows at nearby g4 from different
    # files scatter a little: the oscillator's level and the key held differ).
    grid = np.linspace(math.floor(g4.min()), math.ceil(g4.max()), 25)
    lf = np.interp(grid, g4, np.log(f0))
    qq = np.interp(grid, g4, q)
    k = np.ones(3) / 3.0
    lf_s = np.convolve(np.pad(lf, 1, mode="edge"), k, mode="valid")
    q_s = np.convolve(np.pad(qq, 1, mode="edge"), k, mode="valid")
    law = load("keytrack/law_before.json")
    pots = [r["cutoff"] for r in law["rows"]]
    pot_g4 = [r["g4_v"] for r in law["rows"]]
    # CUTOFF's law has g4 only at some rows: the others from their cutoff through the
    # g4 -> Hz relation of the rows that have both.
    have = [(r["g4_v"], r["cutoff_hz"]) for r in law["rows"] if r.get("g4_v") is not None]
    fill = []
    for r in law["rows"]:
        if r.get("g4_v") is not None:
            fill.append(r["g4_v"])
        else:
            hz = np.array([h for _, h in sorted(have, key=lambda x: x[1])])
            gv = np.array([g for g, _ in sorted(have, key=lambda x: x[1])])
            fill.append(float(np.interp(math.log(r["cutoff_hz"]), np.log(hz), gv)))
    pot_g4 = fill

    # KEY TRACK: g4 per semitone at KEY TRACK 1 (and 0.5), from the rows' slopes.
    def slope(name: str) -> float:
        d = load(name)
        s = []
        for c in sorted({r["cutoff"] for r in d["rows"]}):
            rows = sorted((r["note"], r["g4_v"]) for r in d["rows"] if r["cutoff"] == c)
            n = np.array([x for x, _ in rows], float)
            g = np.array([y for _, y in rows], float)
            # The middle of the keyboard (the ends clip at the string's limits).
            m = (n >= 48) & (n <= 84)
            s.append(np.polyfit(n[m], g[m], 1)[0])
        return float(np.median(s))

    kt1, kt05 = slope("keytrack/track_1.json"), slope("keytrack/track_0.5.json")
    # PRESSURE (pot 1): g4 per volt of the strip (0 / 7.5 / 15 V).
    pv = []
    for v, name in ((0.0, "pressure_0"), (7.5, "pressure_7.5"), (15.0, "pressure_15")):
        for r in load(f"keytrack/{name}.json")["rows"]:
            pv.append((r["cutoff"], v, r["g4_v"]))
    per_v = []
    for c in sorted({x[0] for x in pv}):
        rows = sorted((v, g) for cc, v, g in pv if cc == c)
        per_v.append(np.polyfit([v for v, _ in rows], [g for _, g in rows], 1)[0])
    pressure_g4_per_v = float(np.median(per_v))
    return {
        "law": {
            "g4_v": [round(float(x), 4) for x in grid],
            "f0_hz": [round(float(math.exp(x)), 2) for x in lf_s],
            "q": [round(float(x), 4) for x in q_s],
            "fit_rms_db": round(float(np.median(err)), 3),
            "rows": len(points),
            "source": "measured: scripts/keytrack_study.py (reports/tube_synth/keytrack/"
            "{law_before,track_0.5,track_1,pressure_0,pressure_7.5,pressure_15}.json): each "
            "row's response fitted with a 2-pole low-pass (f0, Q) down to -30 dB, against "
            "the row's V4 grid volts; RESONANCE 0. law_before predates the ADSR and the LFO.",
        },
        "cutoff_g4": {
            "pot": pots,
            "g4_v": [round(float(x), 4) for x in pot_g4],
            "source": "measured: reports/tube_synth/keytrack/law_before.json (CUTOFF against "
            "V4's grid, KEY TRACK 0; rows without g4 placed through the rows' g4 -> Hz)",
        },
        "key_track_g4_per_semitone": {
            "at_1": round(kt1, 5),
            "at_0_5": round(kt05, 5),
            "source": "measured: reports/tube_synth/keytrack/track_{1,0.5}.json (V4's grid "
            "against the key, notes 48-84, median over CUTOFF)",
        },
        "pressure_g4_per_v": {
            "value": round(pressure_g4_per_v, 5),
            "full_v": 15.0,
            "source": "measured: reports/tube_synth/keytrack/pressure_{0,7.5,15}.json (V4's "
            "grid against the strip's volts, PRESSURE 1, median over CUTOFF)",
        },
    }


def taper_mid(name: str) -> float:
    for line in CIRCUIT.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(f"{name}:"):
            return float(s.split("value:")[1].split(",")[0])
    raise SystemExit(f"{CIRCUIT}: no {name}")


def tables() -> dict:
    out: dict = {
        "device": "tube_synth",
        "circuit": "config/circuits/tube_synth.yaml",
        "circuit_sha256": hashlib.sha256(CIRCUIT.read_bytes()).hexdigest(),
        "generated_by": "scripts/proxy_tables.py",
    }
    out["filter"] = filter_tables()
    # The VCA: the envelope's volts (a key held at each key-down voltage) to the level.
    # The ADSR circuit's measurement when there is one (the older velocity.json predates it).
    adsr = REPORTS / "proxy" / "velocity_adsr.json"
    name = "proxy/velocity_adsr.json" if adsr.is_file() else "velocity.json"
    vel = load(name)
    rows = sorted((r["env_v"], r["out_dbfs"]) for r in vel["rows"])
    ref = next(r["out_dbfs"] for r in vel["rows"] if r["down_v"] == -1)
    out["vca"] = {
        "env_v": [v for v, _ in rows],
        "db": [round(db - ref, 3) for _, db in rows],
        "level_dbfs_at_minus_1v": ref,
        "reference": {
            "pitch_v": -15.0,
            "panel": "defaults",
            "hz": 497.5,
            "level": "rms re full scale",
        },
        "source": f"measured: scripts/velocity_study.py (reports/tube_synth/{name}: a key held "
        "at each key-down voltage, the panel's defaults, pitch -15 V; the envelope node's "
        "volts against the out's rms re full scale)"
        + ("" if adsr.is_file() else "; before the ADSR (not re-measured since)"),
    }
    # GLIDE: one-pole time constants, from the time to within 10 cents of the up step.
    g = load("glide.json")
    up = g["glide"]
    pots, taus = [], []
    for k in sorted(up, key=float):
        st = up[k]["up"]
        cents = 1200 * math.log2(st["to_hz"] / st["from_hz"])
        pots.append(float(k))
        taus.append(round(st["within_10_cents_s"] / math.log(cents / 10.0), 5))
    out["glide"] = {
        "pot": pots,
        "tau_s": taus,
        "source": "measured: scripts/glide_study.py (reports/tube_synth/glide.json: the "
        "-20 -> -15 V step's time to within 10 cents, as a one-pole tau = t / ln(step / 10 "
        "cents)); before VIBRATO's RPSUM (GLIDE 0 is ~4.7 ms since, its 50 ms smoothing "
        "limits it anyway); GLIDE 1's 2 s window was short",
    }
    # The LFO.
    lfo = load("lfo.json")
    ring = load("ring/built.json")
    low = {0.0: 0.08}
    for r in lfo["runs"]:
        low[r["rate"]] = r["on"]["f_hz"]
    for r in ring["lfo"]:
        if r["lfo_audio"] == 0:
            low.setdefault(r["lfo_rate"], r["lfo_hz"])
    audio = {r["lfo_rate"]: r["lfo_hz"] for r in ring["lfo"] if r["lfo_audio"] == 1}
    amp = float(np.mean([r["on"]["amp_peak_v"] for r in lfo["runs"]]))
    out["lfo"] = {
        "low": {"pot": sorted(low), "hz": [round(low[k], 4) for k in sorted(low)]},
        "audio": {"pot": sorted(audio), "hz": [round(audio[k], 3) for k in sorted(audio)]},
        "amp_peak_v": round(amp, 3),
        "vibrato_cents_at_1": round(float(np.mean([r["vibrato_cents"] for r in lfo["runs"]])), 2),
        "wobble_g4_pp_v_at_1": round(float(np.mean([r["wobble_g4_pp_v"] for r in lfo["runs"]])), 3),
        "source": "measured: scripts/lfo_study.py (reports/tube_synth/lfo.json: LOW range at "
        "0.25 / 0.5 / 0.7 / 1, VIBRATO and WOBBLE at 1) and scripts/ring_study.py "
        "(reports/tube_synth/ring/built.json: both ranges); RATE 0 LOW is the design's 0.08 "
        "Hz (tube_synth.yaml); VIBRATO and WOBBLE linear in their pots (the design's)",
    }
    rr = ring["ring"]
    out["ring"] = {
        "level_db_re_osc": round(float(np.mean([r["ring_pk_db_re_osc"] for r in rr])), 2),
        "osc_bleed_db": round(float(np.mean([r["osc_bleed_db"] for r in rr])), 2),
        "carrier_bleed_db": round(float(np.mean([r["carrier_bleed_db"] for r in rr])), 2),
        "source": "measured: scripts/ring_study.py (reports/tube_synth/ring/built.json: RING "
        "1, OSC 0, three pitches by four carriers; means). Its band limits aren't measured",
    }
    vco = load("vco/lc.json")["qualities"]["production"]["outputs"]
    tank = vco["-25.0"]["t"]["harmonics_db"][:12]
    mid = vco["-25.0"]["out"]["harmonics_db"][:12]
    square = [round(20 * math.log10(1.0 / n), 2) if n % 2 else -60.0 for n in range(1, 13)]
    out["oscillator"] = {
        "wave": [0.0, 0.5, 1.0],
        "harmonics_db": [tank, mid, square],
        "source": "measured: scripts/vco_study.py (reports/tube_synth/vco/lc.json, production, "
        "-25 V: the tank (WAVE 0's) and the out at WAVE 0.5, 12 harmonics re the fundamental, "
        "on vco_lc.yaml, the synth's oscillator on its own); WAVE 1 provisional: a square "
        "(the design: tank to square). Sine phases (not measured: single cycles owed)",
    }
    kl = REPORTS / "proxy" / "key_level.json"
    if kl.is_file():
        rows = json.loads(kl.read_text(encoding="utf-8"))["rows"]
        out["key_level"] = {
            "note": [r["note"] for r in rows],
            "dbfs": [r["out_dbfs"] for r in rows],
            "cents": [round(1200 * math.log2(r["f_measured_hz"] / r["hz"]), 2) for r in rows],
            "source": "measured: scripts/proxy_sweep.py (reports/tube_synth/proxy/key_level.json: "
            "a key held at velocity 127, the panel's defaults, each at the app's tuning and "
            "AUTO's range; rms re full scale; the key's frequency against equal temperament, "
            "cents: where the device's tuning puts it)",
        }
    out["saw"] = {
        "db_re_osc": -2.0,
        "source": "measured: HYBRID_PHYSICS_PLAN.md H4 (the saw alone -9.3 dBV, the LC alone "
        "-7.3 dBV at full levels); its shape provisional: a sawtooth (single cycles owed)",
    }
    out["tapers"] = {
        "mix_mid": taper_mid("mix_taper_mid"),
        "env_mid": taper_mid("env_taper_mid"),
        "glide_mid": taper_mid("osc_glide_taper_mid"),
        "source": "the circuit file's *_taper_mid values (varimu.circuit.parts.taper)",
    }
    out["envelope"] = {
        "attack_s": [0.005, 0.7],
        "decay_s": [0.018, 2.0],
        "release_s": [0.010, 2.0],
        "sustain_v": [-105.0, -2.0],
        "rest_v": -110.0,
        "source": "provisional: the circuit file's design comments (tube_synth.yaml: ATTACK "
        "~5 ms to ~0.7 s, DECAY ~18 ms to ~2 s, RELEASE ~10 ms to ~2 s, time constants, "
        "audio taper; SUSTAIN from the -105 V rail to ~-2 V, linear; the bus at rest "
        "-110 V); a sweep per pot is owed",
    }
    out["resonance"] = {
        "q_at_1": 6.0,
        "fade_cutoff": [0.0, 0.75, 1.0],
        "fade": [1.0, 0.25, 0.08],
        "source": "provisional: the standalone tube filter (TUBE_SYNTH_PLAN.md S2: ~+8 dB "
        "at the cutoff at low CUTOFF, +2 dB at 0.75, +0.7 dB at 1; self-oscillation from "
        "~0.8 at low CUTOFF); not measured on tube_synth: a sweep is owed",
    }
    out["env_amount"] = {
        "g4_v_at_1": 27.0,
        "source": "provisional: TUBE_SYNTH_PLAN.md S5 (before the ADSR: at CUTOFF 0.15, ENV "
        "AMOUNT 1 held the cutoff at ~4.7 kHz, near the CUTOFF pot's top: about the pot's "
        "27 V of V4's grid at full envelope); a sweep is owed",
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the file would change")
    a = ap.parse_args()
    text = json.dumps(tables(), indent=1) + "\n"
    old = OUT.read_text(encoding="utf-8") if OUT.is_file() else None
    if a.check:
        sys.exit(0 if old == text else 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    t = json.loads(text)
    law = t["filter"]["law"]
    print(f"{OUT}: filter law over {law['rows']} rows, median fit {law['fit_rms_db']} dB rms")
    print("  g4 -> f0:", list(zip(law["g4_v"][::4], law["f0_hz"][::4], law["q"][::4], strict=True)))
    print("  key track g4/semitone:", t["filter"]["key_track_g4_per_semitone"])
    print("  pressure g4/V:", t["filter"]["pressure_g4_per_v"]["value"])
    print("  glide tau:", list(zip(t["glide"]["pot"], t["glide"]["tau_s"], strict=True)))


if __name__ == "__main__":
    main()

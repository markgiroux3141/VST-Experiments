"""Render an invented instrument's demo phrase through its live circuit
(docs/INVENTED_LIVE_PLAN.md): the circuit file built as the app builds it, the keys played
by note events through circuitsim (`fast.run_transient(notes=)`), the output at the
circuit's full scale (unnormalized, so the level is the device's)
-> reports/invented/<name>/live_<take>.wav.

A gated device (GATED: the Arc Organ, whose keys work a gate and set the key's condenser in
place), and a take that turns knobs off their defaults (the Rosin Wheel's EVEN), render through
the app's own take renderer (varimu-app's `midi_render` example: the
Performer, the keyed value landing a block after its key, as Play), at the device's host rate.

    uv run --extra fast python scripts/invented_live_render.py [--only NAME] [--quality draft]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from varimu.invented.common import note  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "reports" / "invented"

# (circuit, take, [(start_s, dur_s, note name, velocity)], seconds[, [(pedal down_s, up_s)]])
MELODY = "C4:1 Db4:1 E4:2 F4:1 G4:2 Ab4:1 G4:1 F4:1 E4:2 Db4:1 C4:3"  # the sketch's (I14)


def beats(text: str, start: float, beat_s: float, vel: int, gap_s: float = 0.02) -> list:
    out, t = [], start
    for tok in text.split():
        nm, n = tok.split(":")
        out.append((t, int(n) * beat_s - gap_s, nm, vel))
        t += int(n) * beat_s
    return out


DEMOS = {
    "rosin_wheel": (
        "melody_and_chord",
        [
            (0.00, 1.04, "D4", 70),
            (1.10, 0.49, "F4", 70),
            (1.65, 0.49, "A4", 70),
            (2.20, 1.04, "G4", 70),
            (3.30, 0.49, "E4", 70),
            (3.85, 0.49, "C4", 70),
            (4.40, 1.59, "D4", 70),
            (6.60, 4.00, "D3", 60),
            (6.60, 4.00, "A3", 60),
            (6.60, 4.00, "F4", 60),
            (6.60, 4.00, "C5", 60),
        ],
        12.0,
    ),
    # the sketch's melody over a D3 drone (legato: each note overlaps the next by 0.3 s)
    "rijke_organ": (
        "melody_over_drone",
        [(0.0, 9.0, "D3", 80)]
        + beats("D4:2 E4:1 F#4:1 A4:3 G4:1 F#4:2 E4:2 D4:4", 1.0, 0.5, 90, -0.3),
        13.0,
    ),
    # the sketch's melody over an A2 + E3 drone, at the nominal wind
    "aeolian_keyboard": (
        "melody_over_drone",
        [(0.0, 10.0, "A2", 90), (0.0, 10.0, "E3", 90)]
        + beats("A3:2 C4:1 E4:1 D4:2 C4:1 B3:1 A3:2 E4:2 A4:4", 1.0, 0.6, 100, -0.15),
        12.0,
    ),
    # STRUCK (the default): the sketch's tune of single bubbles, then four chords
    "bubble_organ": (
        "single_bubbles",
        beats("G4:1 E4:1 G4:1 C5:2 A4:1 G4:1 E4:1 D4:1 E4:1 C4:3", 0.5, 0.3, 80)
        + [
            (4.6 + 0.9 * j + 0.025 * k, 0.1, nm, 90)
            for j, ch in enumerate(
                (("C3", "G3", "E4"), ("A2", "E3", "C4"), ("F2", "C3", "A3"), ("G2", "D3", "B3"))
            )
            for k, nm in enumerate(ch)
        ],
        9.0,
    ),
    # the sketch's harmonic melody (16 18 20 24 27 28 ... holes: A3 B3 C#4 E4 F#4 G4, the G the
    # 7th harmonic), then its 4:5:6:7 chord entering a key at a time (the shaft and wind sag)
    "siren_organ": (
        "harmonic_melody_and_chord",
        beats(
            "A3:1 B3:1 C#4:1 E4:2 F#4:1 G4:1 F#4:1 E4:1 C#4:2 D4:1 C#4:1 B3:1 A3:3", 0.3, 0.42, 100
        )
        + [
            (7.5 + 1.3 * j, 6.5 - 1.3 * j, nm, 100)
            for j, nm in enumerate(("A3", "C#4", "E4", "G4"))
        ],
        15.0,
    ),
    # the tanpura's cam on the pedal (DRONE TONIC 0: Sa = C3), the sketch's melody over it
    "buzz_zither": (
        "melody_over_tanpura",
        beats(MELODY, 4.0, 0.38, 90),
        14.0,
        [(0.0, 12.5)],
    ),
}


# Through the app: (take, [(start_s, dur_s, note name, velocity)], seconds, {knob: value})
ARC_TUNE = "E4:1 G4:1 A4:2 G4:1 E4:1 D4:2 C4:1 D4:1 E4:3"  # the sketch's (I13)
ARC_MELODY = beats(ARC_TUNE, 0.5, 0.45, 100, 0.06)
ARC_COMPASS = "E2:1 B2:1 E3:1 A3:1 E4:1 A4:1 E5:1 A5:1 C6:2"
ARC_PHRASE = beats("A3:1 C4:1 E4:2 D4:1 C4:1 A3:2", 0.4, 0.4, 100, 0.06)
GATED = {
    # EVEN (the control `limit`) on: every note at one level from ~0.1 s, the rosin's scratch
    # kept (the melody_and_chord demo above is the free, swelling bar)
    "rosin_wheel": [
        ("melody_and_chord_even_0.5", DEMOS["rosin_wheel"][1], 12.0, {"limit": 0.5}),
        ("melody_and_chord_even_1", DEMOS["rosin_wheel"][1], 12.0, {"limit": 1.0}),
    ],
    "arc_organ": [
        # the sketch's melody at the panel's defaults (5 A, SPEAK full, 2 mm)
        ("melody", ARC_MELODY, 7.0, {}),
        # the same melody legato (each key overlapping the next: the condensers switched on
        # the singing arc)
        ("melody_legato", beats(ARC_TUNE, 0.5, 0.45, 100, -0.05), 7.0, {}),
        # the sketch's phrase at three currents (CURRENT 0, 0.5, 1: ~3.3, 5, 9 A) and HISS up
        ("phrase_3A", ARC_PHRASE, 4.2, {"current": 0.0}),
        ("phrase_5A", ARC_PHRASE, 4.2, {}),
        ("phrase_9A_hissing", ARC_PHRASE, 4.2, {"current": 1.0, "hiss": 0.9}),
        # SPEAK near the arc's threshold: notes build slowly as pure sines
        ("phrase_speak_low", ARC_PHRASE, 4.2, {"speak": 0.25}),
        # down the compass, E2 to C6 by fifths and fourths
        ("compass", beats(ARC_COMPASS, 0.3, 0.5, 100, 0.08), 6.5, {}),
    ],
}


def render_gated(name: str, quality: str) -> None:
    """GATED's takes through varimu-app's midi_render example."""
    import json
    import subprocess
    import tempfile

    import soundfile as sf

    root = Path(__file__).resolve().parents[1]
    q = {"draft": "draft-2x", "production": "production"}.get(quality, quality)
    for take, phrase, seconds, sets in GATED[name]:
        notes = sorted((s, s + d, note(nm), v) for s, d, nm, v in phrase)
        with tempfile.TemporaryDirectory() as tmp:
            part = Path(tmp) / "part.json"
            part.write_text(json.dumps({"notes": notes, "end_s": seconds}))
            OUT.joinpath(name).mkdir(parents=True, exist_ok=True)
            path = OUT / name / f"live_{take}.wav"
            cmd = [
                "cargo",
                "run",
                "--release",
                "-q",
                "-p",
                "varimu-app",
                "--example",
                "midi_render",
                "--",
                "--device",
                name,
                "--notes",
                str(part),
                "--out",
                str(path),
                "--quality",
                q,
            ]
            for k, x in sets.items():
                cmd += ["--set", f"{k}={x}"]
            subprocess.run(cmd, check=True, cwd=root)
        y, _ = sf.read(path)
        peak = 20 * np.log10(max(np.max(np.abs(y)), 1e-12))
        print(f"{name}: {path.name}, peak {peak:+.1f} dBFS ({q})")


def main() -> None:
    import dataclasses

    import soundfile as sf

    from varimu.circuit import builder, spec
    from varimu.circuit.ir import VoltageProbe
    from varimu.sim import fast, io

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--quality", default="production")
    args = ap.parse_args()
    for name in GATED:
        if not args.only or name in args.only:
            render_gated(name, args.quality)
    for name, (take, phrase, seconds, *rest) in DEMOS.items():
        if args.only and name not in args.only:
            continue
        sp = spec.load_circuit(spec.circuit_path(name))
        ir = builder.build_ir(sp, spec.resolve(sp, {}))
        ir = dataclasses.replace(ir, probes=(VoltageProbe("out"),))
        st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality=args.quality)
        fs_out = io.full_scale(st, sp)[1]
        st = dataclasses.replace(st, full_scale_volts_peak=1.0)
        fs = st.sample_rate
        notes = []
        for start, dur, nm, vel in phrase:
            notes.append((start, "on", note(nm), vel))
            notes.append((start + dur, "off", note(nm), 0))
        for down, up in rest[0] if rest else []:
            notes.append((down, "pedal", 0, 1))
            notes.append((up, "pedal", 0, 0))
        notes.sort(key=lambda e: e[0])
        x = np.zeros(int(seconds * fs))
        res = fast.run_transient(ir, x, settings=st, notes=notes)
        y = np.asarray(res.vectors["v(out)"]) / fs_out
        peak = 20 * np.log10(max(np.max(np.abs(y)), 1e-12))
        OUT.joinpath(name).mkdir(parents=True, exist_ok=True)
        path = OUT / name / f"live_{take}.wav"
        sf.write(path, y.astype(np.float32), fs, subtype="FLOAT")
        print(f"{name}: {path.name}, peak {peak:+.1f} dBFS ({args.quality})")


if __name__ == "__main__":
    main()

"""Render an invented instrument's demo phrase through its live circuit
(docs/INVENTED_LIVE_PLAN.md): the circuit file built as the app builds it, the keys played
by note events through circuitsim (`fast.run_transient(notes=)`), the output at the
circuit's full scale (unnormalized, so the level is the device's)
-> reports/invented/<name>/live_<take>.wav.

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
    # the tanpura's cam on the pedal (DRONE TONIC 0: Sa = C3), the sketch's melody over it
    "buzz_zither": (
        "melody_over_tanpura",
        beats(MELODY, 4.0, 0.38, 90),
        14.0,
        [(0.0, 12.5)],
    ),
}


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

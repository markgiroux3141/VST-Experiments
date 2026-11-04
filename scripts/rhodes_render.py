"""The Rhodes played from MIDI through the Stage's controls into the 5E3 (docs/RHODES_PLAN.md,
RH2): the harp's open-circuit EMF (varimu/rhodes/harp.py) drives
config/circuits/rhodes_stage_5e3.yaml (scripts/derive_rhodes_5e3.py), whose output is the
sound pressure 1 m in front of the 5E3's speaker.

    uv run --extra fast python scripts/rhodes_render.py (--midi FILE | --demo)
        [--seconds S] [--tail 3] [--quality production|draft|draft-1x]
        [--set stage_volume=1 stage_bass=1 volume_bright=0.5 ...] [--out NAME]

Writes reports/rhodes/renders/<name>.wav (the amp, 0 dBFS = the circuit's 50 Pa) and
<name>_harp.wav (the harp's EMF straight, 0 dBFS = 0.5 V), and prints the harp's and the
amp's times. `--demo` plays a phrase of its own (soft and hard chords, a bass line, the
pedal; the MIDI written beside the WAVs).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.rhodes import harp, midi
from varimu.rhodes import spec as rspec
from varimu.sim import fast
from varimu.sim.io import TransientSettings, full_scale, write_audio

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "rhodes" / "renders"
CIRCUIT = "rhodes_stage_5e3"


def demo_events() -> list[midi.Event]:
    """Four bars at 90 bpm: a bass note, then a voiced chord, soft to hard, with the pedal
    caught after each chord; a run up the middle; a low E1 at full velocity."""
    beat = 60 / 90
    ev: list[midi.Event] = []

    def note(t, n, vel, dur):
        ev.append(midi.Event(t, "on", n, vel))
        ev.append(midi.Event(t + dur, "off", n, 0))

    chords = [  # (bass, chord), MIDI notes
        (41, [57, 60, 64, 67]),  # F2 | A3 C4 E4 G4
        (43, [59, 62, 65, 69]),  # G2 | B3 D4 F4 A4
        (40, [55, 59, 62, 64]),  # E2 | G3 B3 D4 E4
        (45, [60, 64, 67, 71]),  # A2 | C4 E4 G4 B4
    ]
    for bar, (bass, chord) in enumerate(chords):
        t0 = bar * 4 * beat
        vel = 40 + 25 * bar  # soft to hard
        ev.append(midi.Event(t0 + 0.02, "pedal", value=0))
        note(t0, bass, vel + 10, 3.5 * beat)
        for i, n in enumerate(chord):
            note(t0 + beat + 0.012 * i, n, vel, 2.5 * beat)
        ev.append(midi.Event(t0 + beat + 0.1, "pedal", value=1))
    t = 16 * beat
    ev.append(midi.Event(t, "pedal", value=0))
    for i, n in enumerate([64, 67, 69, 72, 74, 76, 79, 81]):
        note(t + i * beat / 2, n, 70 + 4 * i, beat / 2)
    note(t + 5 * beat, 28, 127, 2 * beat)  # E1, the lowest key
    return ev


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--midi", type=Path)
    src.add_argument("--demo", action="store_true")
    ap.add_argument("--seconds", type=float, help="cut the MIDI there")
    ap.add_argument("--tail", type=float, default=3.0, help="seconds after the last event")
    ap.add_argument("--quality", default="production", choices=["production", "draft", "draft-1x"])
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    ap.add_argument("--out", help="the WAVs' name")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if args.demo:
        events = demo_events()
        name = args.out or "demo"
        midi.write(OUT / f"{name}.mid", events)
    else:
        events = midi.read(args.midi)
        name = args.out or args.midi.stem
    if args.seconds:
        events = [e for e in events if e.t_s < args.seconds]
    duration = max(e.t_s for e in events) + args.tail

    t0 = time.perf_counter()
    r = harp.render(events, duration, progress=True)
    t_harp = time.perf_counter() - t0
    fs_v = rspec.load()["numerics"]["full_scale_v"]
    write_audio(OUT / f"{name}_harp.wav", (r.emf_v / fs_v).astype(np.float32), int(r.fs_hz))
    print(
        f"harp: {len(r.voices)} keys, {r.skipped} notes off the 73 keys, peak "
        f"{np.max(np.abs(r.emf_v)):.3f} V, {t_harp:.0f} s for {duration:.1f} s "
        f"({t_harp / duration:.1f}x real time)",
        flush=True,
    )

    c = spec.load_circuit(spec.circuit_path(CIRCUIT))
    over = {}
    for kv in args.set:
        k, v = kv.split("=", 1)
        over[k] = float(v)
    s = TransientSettings.from_sim_settings(
        engine="circuitsim", quality=None if args.quality == "production" else args.quality
    )
    if s.sample_rate != r.fs_hz:
        raise SystemExit(f"the harp renders at {r.fs_hz} Hz, the circuit at {s.sample_rate}")
    ir = builder.build(c, over).ir
    t0 = time.perf_counter()
    v = fast.run_transient(ir, r.emf_v, settings=s).vectors["v(out)"]
    t_amp = time.perf_counter() - t0
    y = v / full_scale(s, c)[1]
    write_audio(OUT / f"{name}.wav", y.astype(np.float32), int(s.sample_rate))
    print(
        f"5E3 ({args.quality}): peak {np.max(np.abs(y)):.3f} FS, {t_amp:.0f} s "
        f"({t_amp / duration:.1f}x real time) -> {OUT / name}.wav"
    )


if __name__ == "__main__":
    main()

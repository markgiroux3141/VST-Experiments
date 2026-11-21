"""The Wurlitzer 200A played from MIDI (docs/WURLITZER_PLAN.md, WZ3): the Python keyboard
(`varimu/wurlitzer/keyboard.py`: every reed, the hammers, the dampers and the pedal) into the
200A's electronics (`config/circuits/wurlitzer_200a.yaml`), both outputs.

    uv run --extra fast python scripts/wurlitzer_render.py (--midi FILE | --demo)
        [--seconds S] [--tail 3] [--quality production|draft-1x]
        [--set volume=0.8 vibrato=1 ...] [--out NAME]

Writes to reports/wurlitzer/renders/:
- <name>_aux.wav: the AUX OUTPUT jack (`out`, into a 10 kOhm line input), 0 dBFS = 1 V peak
  (the circuit's output full scale; the drawing's maximum is ~0.57 V peak);
- <name>_speakers.wav: the power amplifier's terminals (`spk`) across the two 16 ohm
  resistors standing in for the speakers until WZ5: a voltage, not the sound in the room,
  0 dBFS = 20 V peak (~25 W into 8 ohm; the amplifier clips near 20 W);
- <name>_reeds.wav: the reeds' input to the circuit (`in` = -V0 dC / C_reeds), 0 dBFS = 4 V
  (a chord's reeds reach ~3 V);
and prints the times. `--demo` plays a phrase of its own (chords soft to hard with the
pedal, a run up the middle, a hard bass), its MIDI written beside the WAVs. MIDI notes 33-96
are the 64 keys (A1-C7); others are skipped.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from varimu.rhodes import midi
from varimu.sim.io import write_audio
from varimu.wurlitzer import circuit, keyboard

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "wurlitzer" / "renders"
FS = circuit.TRANSFER_FS  # the project's rate (sim_settings.yaml: 96 kHz)
AUX_FULL_SCALE_V = 1.0
SPEAKER_FULL_SCALE_V = 20.0
REEDS_FULL_SCALE_V = 4.0


def demo_events() -> list[midi.Event]:
    """Four bars at 92 bpm of Wurly comping: a bass note, then a voiced chord, soft to hard,
    the pedal caught after each chord; a run up the middle at a firm touch; a hard low A."""
    beat = 60 / 92
    ev: list[midi.Event] = []

    def note(t, n, vel, dur):
        ev.append(midi.Event(t, "on", n, vel))
        ev.append(midi.Event(t + dur, "off", n, 0))

    chords = [  # (bass, chord), MIDI notes
        (45, [57, 60, 64, 67]),  # A2 | A3 C4 E4 G4   (Am7)
        (50, [57, 60, 62, 66]),  # D3 | A3 C4 D4 F#4  (D9)
        (43, [59, 62, 65, 69]),  # G2 | B3 D4 F4 A4   (G9)
        (48, [59, 64, 67, 71]),  # C3 | B3 E4 G4 B4   (Cmaj7)
    ]
    for bar, (bass, chord) in enumerate(chords):
        t0 = 0.3 + bar * 4 * beat
        vel = 45 + 22 * bar  # soft to hard
        ev.append(midi.Event(t0 + 0.02, "pedal", value=0))
        note(t0, bass, vel + 10, 3.5 * beat)
        for i, n in enumerate(chord):
            note(t0 + beat + 0.01 * i, n, vel, 1.5 * beat)
            note(t0 + 2.5 * beat + 0.01 * i, n, vel - 8, 1.0 * beat)
        ev.append(midi.Event(t0 + beat + 0.1, "pedal", value=1))
    t = 0.3 + 16 * beat
    ev.append(midi.Event(t, "pedal", value=0))
    for i, n in enumerate([69, 72, 74, 76, 79, 81, 84, 86]):
        note(t + i * beat / 2, n, 85 + 4 * i, 0.45 * beat)
    note(t + 4.5 * beat, 33, 127, 2.5 * beat)  # A1, the lowest key
    note(t + 4.5 * beat, 45, 120, 2.5 * beat)
    return ev


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--midi", type=Path)
    src.add_argument("--demo", action="store_true")
    ap.add_argument("--seconds", type=float, help="cut the MIDI there")
    ap.add_argument("--tail", type=float, default=3.0, help="seconds after the last event")
    ap.add_argument("--quality", default="production", choices=["production", "draft-1x"])
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
    sets = {}
    for kv in args.set:
        k, v = kv.split("=", 1)
        sets[k] = float(v)

    t0 = time.perf_counter()
    kb = keyboard.render(events, duration, fs_hz=float(FS))
    t_kb = time.perf_counter() - t0
    x = circuit.plate_input_v(kb.dc_f)
    write_audio(OUT / f"{name}_reeds.wav", (x / REEDS_FULL_SCALE_V).astype(np.float32), FS)
    print(
        f"keyboard: {len(kb.voices)} keys ({kb.skipped} notes outside A1-C7 skipped), reeds' "
        f"input peak {np.max(np.abs(x)):.2f} V, {t_kb:.1f} s for {duration:.1f} s "
        f"({t_kb / duration:.2f}x real time)",
        flush=True,
    )

    t0 = time.perf_counter()
    v = circuit.render(x, sets, quality=args.quality)
    t_c = time.perf_counter() - t0
    aux, spk = v["out"] / AUX_FULL_SCALE_V, v["spk"] / SPEAKER_FULL_SCALE_V
    write_audio(OUT / f"{name}_aux.wav", aux.astype(np.float32), FS)
    write_audio(OUT / f"{name}_speakers.wav", spk.astype(np.float32), FS)
    print(
        f"circuit ({args.quality}): AUX peak {np.max(np.abs(v['out'])):.3f} V, speakers peak "
        f"{np.max(np.abs(v['spk'])):.2f} V, {t_c:.0f} s ({t_c / duration:.1f}x real time) "
        f"-> {OUT / name}_{{aux,speakers,reeds}}.wav"
    )


if __name__ == "__main__":
    main()

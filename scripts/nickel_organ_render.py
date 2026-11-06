"""The Nickel Organ played: a MIDI file or the demo through every key's bar and loop
(docs/NICKEL_ORGAN_PLAN.md) -> reports/nickel_organ/renders/NAME.wav (+ .json, and the
demo's .mid). Offline Python, ~10x slower than real time per sounding key.

    uv run python scripts/nickel_organ_render.py --demo
    uv run python scripts/nickel_organ_render.py --midi song.mid [--sustain 0.7] [--polarize 0.35]
        [--seconds 20]

The WAV is the summed line out normalized to -1 dBFS peak (the .json gives the volts); mono
float32 at 96 kHz. The demo walks the panel: struck bells (SUSTAIN low), chords that bloom
into organ tones (SUSTAIN past the onset, the lamp catching the level), POLARIZE swept down
toward zero under a held chord and back, then a bass note with a melody just past the onset
(the slow bloom).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.nickel import organ
from varimu.nickel import spec as nspec
from varimu.rhodes import midi

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "nickel_organ" / "renders"


def demo_events() -> tuple[list, float]:
    """(events, the panel's SUSTAIN at the start). 80 bpm."""
    beat = 0.75
    ev: list = []

    def note(t, n, vel, dur):
        ev.append(midi.Event(t, "on", n, vel))
        ev.append(midi.Event(t + dur, "off", n, 0))

    # A: struck bells, SUSTAIN low (0-6 s)
    arp = [60, 64, 67, 71, 74, 71, 67, 64, 57, 60, 64, 67, 71, 67, 64, 60]
    for i, n in enumerate(arp):
        note(i * beat / 2, n, 50 + (i % 4) * 18, 0.6)
    # B: chords that bloom (SUSTAIN past the onset from 6 s)
    ev.append((6.2, "sustain", 0.8))
    t = 6.5
    for chord, dur in (([53, 57, 60, 64], 2.5), ([55, 59, 62, 65], 2.5), ([48, 52, 55, 60], 3.5)):
        for i, n in enumerate(chord):
            note(t + 0.015 * i, n, 72, dur)
        t += dur
    # C: POLARIZE down toward zero under the last chord, and back (12.4-15 s)
    for k in range(21):
        ev.append((12.4 + 0.07 * k, "polarize", 0.35 - 0.32 * k / 20))
    for k in range(11):
        ev.append((13.9 + 0.1 * k, "polarize", 0.03 + 0.32 * k / 10))
    # D: a bass note held, a melody just past the onset (15.5-22 s)
    ev.append((15.3, "sustain", 0.66))
    note(15.5, 36, 90, 6.0)
    t = 15.6
    for n, vel, dur in ((76, 70, 1.0), (74, 55, 0.5), (72, 64, 0.5), (67, 80, 1.5), (69, 60, 0.75),
                        (72, 96, 1.5)):  # fmt: skip
        note(t, n, vel, 0.95 * dur)
        t += dur
    return ev, 0.35


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--midi", type=Path)
    src.add_argument("--demo", action="store_true")
    ap.add_argument("--sustain", type=float, help="SUSTAIN (default: the panel's, or the demo's)")
    ap.add_argument("--polarize", type=float, help="POLARIZE (default: the panel's)")
    ap.add_argument("--seconds", type=float, help="cut the MIDI there")
    ap.add_argument("--tail", type=float, default=1.5, help="seconds after the last event")
    ap.add_argument("--oversample", type=int, default=2)
    ap.add_argument("--out", help="the files' name")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    d = nspec.load()
    sustain = args.sustain
    if args.demo:
        events, demo_sustain = demo_events()
        sustain = demo_sustain if sustain is None else sustain
        name = args.out or "demo"
        midi.write(OUT / f"{name}.mid", [e for e in events if not isinstance(e, tuple)])
    else:
        events = midi.read(args.midi)
        name = args.out or args.midi.stem
    if args.seconds:
        events = [e for e in events if (e[0] if isinstance(e, tuple) else e.t_s) < args.seconds]
    if sustain is None:
        sustain = nspec.v(d, "panel.sustain")
    polarize = nspec.v(d, "panel.polarize") if args.polarize is None else args.polarize
    duration = max(e[0] if isinstance(e, tuple) else e.t_s for e in events) + args.tail

    t0 = time.perf_counter()
    r = organ.render(events, duration, sustain=sustain, polarize=polarize,
                     oversample=args.oversample, progress=True)  # fmt: skip
    wall = time.perf_counter() - t0
    peak = float(np.abs(r.audio).max())
    gain = 10 ** (-1 / 20) / peak
    sf.write(OUT / f"{name}.wav", (r.audio * gain).astype(np.float32), organ.FS, subtype="FLOAT")
    meta = {
        "source": "demo" if args.demo else str(args.midi),
        "sustain": sustain,
        "polarize": polarize,
        "oversample": args.oversample,
        "duration_s": duration,
        "peak_v": peak,
        "wav_gain": gain,
        "compute_s": wall,
        "x_real_time": wall / duration,
        "peak_stress_mpa": {str(k): v / 1e6 for k, v in sorted(r.per_key_peak_stress_pa.items())},
        "lamp_peak_k": {str(k): v for k, v in sorted(r.lamp_peak_k.items())},
    }
    (OUT / f"{name}.json").write_text(json.dumps(meta, indent=1))
    print(f"-> {OUT / f'{name}.wav'} ({duration:.1f} s in {wall:.0f} s, peak {peak:.2f} V)")


if __name__ == "__main__":
    main()

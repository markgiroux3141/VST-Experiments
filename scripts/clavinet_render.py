"""CL2: MIDI through the D6, strings and electronics, offline (docs/CLAVINET_PLAN.md)
-> reports/clavinet/renders/<name>_{out,emf}.wav.

The strings (varimu/clavinet: each note a key struck, held, released) give each pickup's
EMF; those drive config/circuits/clavinet_d6.yaml's control inputs (the bridge pickup's
reversed connection gets the negated EMF), and its `out` (the volume pot's wiper) is saved
at the circuit's full scale. `_emf.wav` is the two pickups' EMFs summed in phase, before
the electronics.

    uv run --extra fast python scripts/clavinet_render.py (--midi FILE | --demo)
        [--pickups 0-3] [--tone soft,medium,treble,brilliant] [--mute 0-1] [--volume V]
        [--quality production|draft] [--out NAME]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.clavinet import keyboard
from varimu.config import CONFIG_DIR
from varimu.rhodes import midi
from varimu.sim import fast, io

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "clavinet" / "renders"
CIRCUIT = CONFIG_DIR / "circuits" / "clavinet_d6.yaml"
FS = 96000


def demo_events() -> list[midi.Event]:
    """An original funk phrase at 98 bpm: a staccato sixteenth line in E minor pentatonic
    with ghost notes, off-beat chord stabs, a longer held note to hear the sustain and a
    release, twice."""
    ev: list[midi.Event] = []
    s16 = 60 / 98 / 4

    def note(step: float, n: int, vel: int, dur16: float) -> None:
        t = step * s16
        ev.append(midi.Event(t, "on", n, vel))
        ev.append(midi.Event(t + dur16 * s16 * 0.9, "off", n, 0))

    E3, G3, A3, B3, D4, E4, G4, B4 = 52, 55, 57, 59, 62, 64, 67, 71
    line = [
        (0, E3, 110, 0.6),
        (1, E3, 50, 0.4),
        (2, G3, 96, 0.6),
        (3, E3, 70, 0.5),
        (4, A3, 112, 0.7),
        (6, G3, 90, 0.5),
        (7, E3, 60, 0.4),
        (8, D4, 115, 0.6),
        (9, D4, 45, 0.3),
        (10, B3, 92, 0.6),
        (11, A3, 80, 0.5),
        (12, G3, 105, 0.6),
        (13, E3, 55, 0.4),
        (14, G3, 85, 0.5),
        (15, A3, 95, 0.5),
    ]
    for rep in range(2):
        base = rep * 32
        for st, n, v, d in line:
            note(base + st, n, v, d)
            note(base + 16 + st, n, v, d)
        for st in (2, 6, 10, 14, 18, 22, 26):
            for n in (E4, G4, B4):
                note(base + st + 0.02 * (n - E4), n, 88, 0.5)
    # a held chord and a held bass note at the end: the sustain, then the release's drop
    for n in (E3, B3, E4, G4):
        note(64, n, 100, 12)
    note(64, 40, 110, 12)  # E2
    return sorted(ev, key=lambda e: (e.t_s, e.kind != "off"))


def main() -> None:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--midi", type=Path)
    src.add_argument("--demo", action="store_true")
    ap.add_argument(
        "--pickups",
        type=int,
        default=3,
        help="0 A+C centre, 1 B+C bridge, 2 A+D anti-phase, 3 B+D in phase",
    )
    ap.add_argument("--tone", default="medium,treble", help="the tone rockers on (the others off)")
    ap.add_argument("--mute", type=float, default=0.0)
    ap.add_argument("--volume", type=float, default=0.8)
    ap.add_argument("--quality", default="production")
    ap.add_argument("--out")
    args = ap.parse_args()
    events = demo_events() if args.demo else midi.read(args.midi)
    name = args.out or ("demo" if args.demo else args.midi.stem)
    OUT.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    emf, stats = keyboard.render(events, FS, mute=args.mute)
    t_strings = time.time() - t0

    on = set(args.tone.split(",")) if args.tone else set()
    sets = {k: int(k in on) for k in ("soft", "medium", "treble", "brilliant")}
    sets.update(pickup_select=args.pickups, volume=args.volume)
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets))
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=args.quality),
        full_scale_volts_peak=1.0,
    )
    c, b = emf["centre"], emf["bridge"]
    t1 = time.time()
    v = fast.run_transient(
        ir, np.zeros_like(c), settings=st, controls={"centre": c, "bridge": b, "bridge_neg": -b}
    ).vectors
    t_circuit = time.time() - t1
    out = np.asarray(v["v(out)"])
    fs_out = s.full_scale[1] if s.full_scale else 2.0
    sf.write(OUT / f"{name}_out.wav", (out / fs_out).astype(np.float32), FS, subtype="FLOAT")
    sf.write(OUT / f"{name}_emf.wav", ((c + b) / 0.8).astype(np.float32), FS, subtype="FLOAT")
    dur = c.size / FS
    meta = {
        "source": "demo" if args.demo else str(args.midi),
        "settings": sets,
        "mute": args.mute,
        "quality": args.quality,
        "duration_s": dur,
        "strings_s": t_strings,
        "circuit_s": t_circuit,
        "emf_peak_v": float(np.max(np.abs(c + b))),
        "out_peak_v": float(np.max(np.abs(out))),
        "out_full_scale_v": fs_out,
        **stats,
    }
    (OUT / f"{name}.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()

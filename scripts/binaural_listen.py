"""A blind front / back test on headphones (docs/BINAURAL_PLAN.md): which virtual heads make
a sound behind you sound behind you?

Each trial plays a sound from one of four directions, 30 deg either side of straight ahead
or of straight behind (front-left 30, back-left 150, back-right 210, front-right 330: pairs
with the same time and level difference between the ears, told apart only by the ear's
shape), through one of the heads, in random order. You press F (front) or B (back); R plays
it again, Q stops (the answers so far are kept). At the end: per head, how often the
answer was right (50% = chance: the sphere should land there), and the reversals each way.
Answers go to data/judgments/binaural/<time>.json (never committed).

    uv run --extra binaural --extra listen --with sounddevice python scripts/binaural_listen.py \\
        [--heads sphere pp1 pp1_measured ...] [--stimulus noise|clap|voice|guitar] [--repeats 4]

Before it starts it plays a short level check; set a comfortable volume there.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from binaural_demo import FS, load_head, normalize, stimuli  # noqa: E402

from varimu.binaural.render import Binaural  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DIRS = {30: "front", 150: "back", 210: "back", 330: "front"}


def key() -> str:
    try:
        import msvcrt

        while True:
            c = msvcrt.getwch().lower()
            if c in "fbrq":
                return c
    except ImportError:
        return (input("> ").strip().lower() or "r")[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--heads", nargs="*", default=["sphere", "pp1", "pp1_measured"])
    ap.add_argument("--stimulus", default="noise")
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    import sounddevice as sd
    from scipy.signal import resample_poly

    out_fs = int(sd.query_devices(kind="output")["default_samplerate"])
    x = stimuli()[args.stimulus]
    print("rendering...")
    sounds = {}
    for h in args.heads:
        b = Binaural(load_head(h))
        for az in DIRS:
            y = normalize(b.place(x, az, 0.0))
            if out_fs != FS:
                from fractions import Fraction

                q = Fraction(out_fs, FS).limit_denominator(1000)
                y = resample_poly(y, q.numerator, q.denominator, axis=1)
            sounds[h, az] = y.T.astype(np.float32)
    trials = [(h, az) for h in args.heads for az in DIRS for _ in range(args.repeats)]
    seed = args.seed if args.seed is not None else int(time.time())
    rng = np.random.default_rng(seed)
    rng.shuffle(trials)
    print(
        f"\nlevel check (a sound straight to your left through the first head); output {out_fs} Hz"
    )
    b0 = Binaural(load_head(args.heads[0]))
    y = normalize(b0.place(x, 90, 0.0))
    if out_fs != FS:
        from fractions import Fraction

        q = Fraction(out_fs, FS).limit_denominator(1000)
        y = resample_poly(y, q.numerator, q.denominator, axis=1)
    sd.play(y.T.astype(np.float32), out_fs, blocking=True)
    print(f"\n{len(trials)} trials. F = front, B = back, R = again, Q = stop.\n")
    answers = []
    for i, (h, az) in enumerate(trials):
        while True:
            print(f"[{i + 1}/{len(trials)}] ", end="", flush=True)
            sd.play(sounds[h, az], out_fs, blocking=True)
            c = key()
            if c != "r":
                break
            print("again")
        if c == "q":
            print("stopped")
            break
        print("front" if c == "f" else "back")
        answers.append(
            {"head": h, "az_deg": az, "truth": DIRS[az], "answer": "front" if c == "f" else "back"}
        )
    out = ROOT / "data" / "judgments" / "binaural"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(
        json.dumps(
            {"seed": seed, "stimulus": args.stimulus, "heads": args.heads, "answers": answers},
            indent=1,
        )
    )
    print(f"\nsaved {path}\n")
    print(f"{'head':16s} right  front->back  back->front  (n)")
    for h in args.heads:
        a = [r for r in answers if r["head"] == h]
        if not a:
            continue
        right = np.mean([r["truth"] == r["answer"] for r in a])
        fb = sum(r["truth"] == "front" and r["answer"] == "back" for r in a)
        bf = sum(r["truth"] == "back" and r["answer"] == "front" for r in a)
        nf = sum(r["truth"] == "front" for r in a)
        nb = len(a) - nf
        print(f"{h:16s} {right:5.0%}  {fb:2d}/{nf:<2d}        {bf:2d}/{nb:<2d}        ({len(a)})")


if __name__ == "__main__":
    main()

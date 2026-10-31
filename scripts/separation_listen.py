"""The separation staircase (docs/SEPARATION_PLAN.md): how far the target track can drop
under the masker before you can no longer hear which of three plays a changed note.

    uv run --extra listen --with sounddevice python scripts/separation_listen.py [CONDITION ...]
        [--device NAME] [--seed N] [--list]

Reads scripts/separation_study.py's tracks (cache/separation/conditions/<name>/, each at
-23 LUFS). Each trial plays three mixes of an excerpt around the changed note; one has the
target's changed note. Type which (1 / 2 / 3), r to replay, s to hear the target alone
(original, then changed), q to stop. Two right in a row lower the target, one wrong raises
it (2-down 1-up: 70.7% correct); steps 6, then 4, then 2 dB; it ends after 8 reversals, the
threshold the mean of the last 6. A lower threshold = the pair is more separated. Conditions
run in a random order. Results -> data/judgments/separation/ (never committed).
"""

from __future__ import annotations

import argparse
import json
import time
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "cache" / "separation" / "conditions"
OUT_DIR = ROOT / "data" / "judgments" / "separation"

# The pre-screen's picks (reports/separation/summary.json): a sanity check (the 5E3), the
# cues it can't see (flutter, distance), their controls.
DEFAULT = [
    "dry",
    "T670_Meqp1a",
    "T5e3_M670",
    "flutter_shared",
    "flutter_independent",
    "flutter_independent_x4",
    "room_both_near",
    "room_Tnear_Mfar",
]
EXCERPT_S = (1.15, 4.0)  # around the changed note (beat 4 at 100 bpm: 2.4-2.67 s)
FADE_S = 0.02
GAP_S = 0.45
START_DB, MIN_DB, MAX_DB = 0.0, -40.0, 8.0
PLAY_GAIN_DB = 10.0  # -23 LUFS tracks -> about -13 LUFS mixes
REVERSALS, AVERAGE_LAST = 8, 6
MAX_TRIALS = 60


def load(name: str) -> tuple[dict[str, np.ndarray], int]:
    d = AUDIO_DIR / name
    out, fs = {}, 0
    for k in ("target", "target_changed", "masker"):
        x, fs = sf.read(d / f"{k}.wav", dtype="float64")
        a, b = (int(t * fs) for t in EXCERPT_S)
        x = x[a:b].copy()
        f = int(FADE_S * fs)
        ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(f) / f)
        x[:f] *= ramp
        x[-f:] *= ramp[::-1]
        out[k] = x
    return out, fs


def player(fs: int, device: str | None):
    import sounddevice as sd

    rate = fs
    try:
        sd.check_output_settings(device=device, samplerate=fs, channels=1)
    except Exception:
        rate = int(sd.query_devices(device, kind="output")["default_samplerate"])

    def play(x: np.ndarray) -> None:
        if rate != fs:
            from scipy.signal import resample_poly

            x = resample_poly(x, rate, fs)
        peak = np.abs(x).max()
        if peak > 0.99:
            x = x * 0.99 / peak
            print(f"  (limited: peak {20 * np.log10(peak):+.1f} dBFS)")
        sd.play(x.astype(np.float32), rate, device=device, blocking=True)

    return play


def staircase(
    name: str, tracks: dict[str, np.ndarray], fs: int, play, rng: np.random.Generator
) -> dict:
    gain = 10 ** (PLAY_GAIN_DB / 20)
    gap = np.zeros(int(GAP_S * fs))
    level, step_i, run, last_dir = START_DB, 0, 0, 0
    steps = (6.0, 4.0, 2.0)
    reversals: list[float] = []
    trials = []
    print(f"\n=== {name} ===  (s: hear the target alone, r: replay, q: stop)")
    while len(reversals) < REVERSALS and len(trials) < MAX_TRIALS:
        odd = int(rng.integers(3))
        g = 10 ** (level / 20)
        mixes = [
            gain * (g * tracks["target_changed" if i == odd else "target"] + tracks["masker"])
            for i in range(3)
        ]
        seq = np.concatenate([mixes[0], gap, mixes[1], gap, mixes[2]])
        play(seq)
        t0 = time.time()
        while True:
            prompt = (
                f"  trial {len(trials) + 1}, target {level:+.0f} dB: which is odd? [1/2/3 r s q] "
            )
            ans = input(prompt).strip().lower()
            if ans == "r":
                play(seq)
            elif ans == "s":
                play(
                    np.concatenate([gain * tracks["target"], gap, gain * tracks["target_changed"]])
                )
            elif ans == "q":
                return {
                    "condition": name,
                    "stopped": True,
                    "trials": trials,
                    "reversals": reversals,
                }
            elif ans in ("1", "2", "3"):
                break
        correct = int(ans) - 1 == odd
        trials.append(
            {
                "level_db": level,
                "odd": odd + 1,
                "answer": int(ans),
                "correct": correct,
                "rt_s": round(time.time() - t0, 2),
            }
        )
        if correct:
            run += 1
            move = -1 if run == 2 else 0
            if run == 2:
                run = 0
        else:
            run = 0
            move = 1
        if move:
            if last_dir and move != last_dir:
                reversals.append(level)
                step_i = min(step_i + 1, len(steps) - 1)
            last_dir = move
            level = float(np.clip(level + move * steps[step_i], MIN_DB, MAX_DB))
        print("   right" if correct else "   wrong")
    used = reversals[-AVERAGE_LAST:]
    thr = float(np.mean(used)) if used else float("nan")
    print(f"  threshold {thr:+.1f} dB (target re masker, both at equal loudness)")
    return {"condition": name, "threshold_db": thr, "reversals": reversals, "trials": trials}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("conditions", nargs="*", default=DEFAULT)
    ap.add_argument(
        "--device", default=None, help="output device (name or index; default: the system's)"
    )
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--list", action="store_true", help="list the conditions the study rendered")
    a = ap.parse_args()
    if a.list:
        print("\n".join(sorted(p.name for p in AUDIO_DIR.iterdir() if p.is_dir())))
        return
    seed = a.seed if a.seed is not None else int(time.time())
    order = list(a.conditions)
    np.random.default_rng([seed, 0]).shuffle(order)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = []
    play = None
    for name in order:
        tracks, fs = load(name)
        play = play or player(fs, a.device)
        rng = np.random.default_rng([seed, zlib.crc32(name.encode())])
        r = staircase(name, tracks, fs, play, rng)
        results.append(r)
        (OUT_DIR / f"{stamp}.json").write_text(
            json.dumps(
                {
                    "seed": seed,
                    "excerpt_s": EXCERPT_S,
                    "play_gain_db": PLAY_GAIN_DB,
                    "results": results,
                },
                indent=1,
            )
        )
        if r.get("stopped"):
            break
    print("\nthresholds (lower = more separated):")
    for r in sorted(results, key=lambda r: r.get("threshold_db", 99)):
        print(f"  {r['condition']:24s} {r.get('threshold_db', float('nan')):+6.1f} dB")
    print(f"-> {OUT_DIR / f'{stamp}.json'}")


if __name__ == "__main__":
    main()

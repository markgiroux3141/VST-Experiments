"""Terminal listening tests for the magic packages (ANALOG_MAGIC_FABLE.md AM0), after
scripts/separation_listen.py: a sounddevice player, a 2-down 1-up three-interval staircase,
ABX, and results saved as JSON under data/judgments/magic/<test>/ (git-ignored). Every pair
passed here is loudness-matched by the caller (CLAUDE.md: loudness lies)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from math import comb
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT

JUDGMENTS = REPO_ROOT / "data" / "judgments" / "magic"
GAP_S = 0.4
STEPS_DB = (6.0, 4.0, 2.0)
REVERSALS = 8
AVERAGE_LAST = 6
MAX_TRIALS = 60


def player(fs: int, device: str | None = None, channels: int = 1):
    """A play(x) closure on sounddevice; resamples to the device's rate when it refuses fs,
    and limits a peak over 0.99."""
    import sounddevice as sd

    rate = fs
    try:
        sd.check_output_settings(device=device, samplerate=fs, channels=channels)
    except Exception:
        rate = int(sd.query_devices(device, kind="output")["default_samplerate"])

    def play(x: np.ndarray) -> None:
        if rate != fs:
            from scipy.signal import resample_poly

            x = resample_poly(x, rate, fs, axis=0)
        peak = float(np.abs(x).max()) if len(x) else 0.0
        if peak > 0.99:
            x = x * 0.99 / peak
            print(f"  (limited: peak {20 * np.log10(peak):+.1f} dBFS)")
        sd.play(np.asarray(x, np.float32), rate, device=device, blocking=True)

    return play


def _ask(prompt: str, valid: tuple[str, ...]) -> str:
    while True:
        a = input(prompt).strip().lower()
        if a in valid:
            return a


def staircase(
    make_trial: Callable[[float, int], list[np.ndarray]],
    start_db: float,
    min_db: float,
    max_db: float,
    rng: np.random.Generator,
    play,
    fs: int,
    name: str = "",
) -> dict:
    """2-down 1-up odd-one-out in three intervals; `make_trial(level_db, odd)` returns the
    three intervals with the odd one at index `odd`. Steps 6 / 4 / 2 dB, 8 reversals, the
    threshold the mean of the last 6. Answers 1 / 2 / 3, r replays, q stops."""
    level, step_i, run, last_dir = float(start_db), 0, 0, 0
    reversals: list[float] = []
    trials: list[dict] = []
    gap = np.zeros(int(GAP_S * fs))
    print(f"\n=== {name} ===  (r: replay, q: stop)")
    while len(reversals) < REVERSALS and len(trials) < MAX_TRIALS:
        odd = int(rng.integers(3))
        iv = make_trial(level, odd)
        seq = np.concatenate([iv[0], gap, iv[1], gap, iv[2]])
        play(seq)
        t0 = time.time()
        while True:
            ans = _ask(
                f"  trial {len(trials) + 1}: which is odd? [1/2/3 r q] ", ("1", "2", "3", "r", "q")
            )
            if ans == "r":
                play(seq)
                continue
            break
        if ans == "q":
            return {"condition": name, "stopped": True, "trials": trials, "reversals": reversals}
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
            run, move = 0, 1
        if move:
            if last_dir and move != last_dir:
                reversals.append(level)
                step_i = min(step_i + 1, len(STEPS_DB) - 1)
            last_dir = move
            level = float(np.clip(level + move * STEPS_DB[step_i], min_db, max_db))
        print("   right" if correct else "   wrong")
    used = reversals[-AVERAGE_LAST:]
    thr = float(np.mean(used)) if used else float("nan")
    print(f"  threshold {thr:+.1f} dB")
    return {"condition": name, "threshold_db": thr, "reversals": reversals, "trials": trials}


def binomial_p(correct: int, trials: int) -> float:
    """One-sided P(X >= correct) for X ~ Binomial(trials, 1/2)."""
    return float(sum(comb(trials, k) for k in range(correct, trials + 1)) / 2**trials)


def abx(
    a: np.ndarray,
    b: np.ndarray,
    trials: int,
    rng: np.random.Generator,
    play,
    fs: int,
    name: str = "",
) -> dict:
    """Each trial plays A, B, then X (A or B at random); the answer is a / b (r replays,
    q stops). Returns the count correct and the one-sided binomial p-value."""
    gap = np.zeros(int(GAP_S * fs))
    log = []
    print(f"\n=== ABX {name} ===  (a / b, r: replay, q: stop)")
    for t in range(trials):
        x_is_b = bool(rng.integers(2))
        seq = np.concatenate([a, gap, b, gap, b if x_is_b else a])
        play(seq)
        while True:
            ans = _ask(f"  trial {t + 1}/{trials}: X is? [a/b r q] ", ("a", "b", "r", "q"))
            if ans == "r":
                play(seq)
                continue
            break
        if ans == "q":
            break
        log.append({"x": "b" if x_is_b else "a", "answer": ans, "correct": (ans == "b") == x_is_b})
    n = len(log)
    k = sum(t["correct"] for t in log)
    p = binomial_p(k, n) if n else 1.0
    print(f"  {k} of {n} correct, p = {p:.3f}")
    return {"condition": name, "correct": k, "trials": n, "p": p, "log": log}


def save(test: str, stamp: str, data: dict) -> Path:
    """data/judgments/magic/<test>/<stamp>.json (rewritten by the caller after each condition)."""
    path = JUDGMENTS / test / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=float))
    return path

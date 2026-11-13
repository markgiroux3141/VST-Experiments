"""AM7's listening (docs/ANALOG_MAGIC_FABLE.md), on the stimuli of fusing_noise_study.py.

Task 1, detection: per carrier and noise kind, a three-interval staircase; two intervals are
y0, one is y0 + g n; g adapts (start +20 dB re the tape's own level, floor -30). The
threshold is the noise level (dB re its physical level) at which it is just heard.
Task 2, which is noisier: at 10 dB above the higher of a carrier's thresholds, y0 + n_stat
against y0 + n_phys / n_env / n_band (equal noise power, loudness-matched, order random),
12 trials per pair: "which is noisier? 1 / 2".

  uv run --extra listen --with sounddevice python scripts/fusing_noise_listen.py
      [--carriers synth bass] [--kinds n_stat n_phys n_env n_band] [--device NAME]

Results to data/judgments/magic/fusing/<stamp>.json after every condition.
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import soundfile as sf

from varimu.config import REPO_ROOT
from varimu.listen.matching import match_loudness
from varimu.magic import listen

STIM = REPO_ROOT / "cache" / "magic" / "fusing"
PLAY_LUFS = -23.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--carriers", nargs="+", default=["synth", "bass"])
    ap.add_argument("--kinds", nargs="+", default=["n_stat", "n_phys", "n_env", "n_band"])
    ap.add_argument("--device", default=None)
    ap.add_argument("--seed", type=int, default=int(time.time()))
    a = ap.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    rng = np.random.default_rng(a.seed)
    data = {"seed": a.seed, "task1": [], "task2": []}
    for c in a.carriers:
        y0, fs = sf.read(STIM / c / "y0.wav", dtype="float64")
        play = listen.player(fs, a.device)
        ns = {k: sf.read(STIM / c / f"{k}.wav", dtype="float64")[0] for k in a.kinds}
        # One playback gain per carrier: y0 at PLAY_LUFS.
        (_,), m = match_loudness([y0], fs, target=PLAY_LUFS)
        gain = 10 ** (m.gains_db[0] / 20)
        thresholds = {}
        for k in rng.permutation(a.kinds):
            n = ns[k]

            def trial(level_db, odd, n=n, gain=gain, y0=y0):
                g = 10 ** (level_db / 20)
                return [gain * (y0 + (g * n if i == odd else 0.0)) for i in range(3)]

            r = listen.staircase(trial, 20.0, -30.0, 40.0, rng, play, fs, name=f"{c} {k}")
            r["carrier"], r["kind"] = c, str(k)
            data["task1"].append(r)
            thresholds[k] = r.get("threshold_db", float("nan"))
            listen.save("fusing", stamp, data)
        top = np.nanmax(list(thresholds.values())) + 10.0
        g = 10 ** (top / 20)
        for k in [q for q in a.kinds if q != "n_stat"]:
            right = 0
            for _ in range(12):
                a_mix, b_mix = y0 + g * ns["n_stat"], y0 + g * ns[k]
                (ma, mb), _ = match_loudness([a_mix, b_mix], fs, target=PLAY_LUFS)
                flip = bool(rng.integers(2))
                first, second = (mb, ma) if flip else (ma, mb)
                play(np.concatenate([first, np.zeros(int(0.4 * fs)), second]))
                ans = input(f"  {c}: n_stat vs {k}: which is noisier? [1/2] ").strip()
                stat_said = (ans == "1") != flip  # n_stat was first when not flipped
                right += int(stat_said)
                data["task2"].append(
                    {
                        "carrier": c,
                        "kind": k,
                        "level_db": top,
                        "n_stat_first": not flip,
                        "answer": ans,
                        "n_stat_judged_noisier": stat_said,
                    }
                )
            print(f"  n_stat judged noisier than {k} in {right} of 12")
            listen.save("fusing", stamp, data)
    print(f"saved to {listen.JUDGMENTS / 'fusing' / (stamp + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

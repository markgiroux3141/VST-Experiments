"""AM14, interactions between mechanisms (docs/ANALOG_MAGIC_FABLE.md): every combination of
switches that exist on a device, main effects and two-factor interactions as signals, and
Shapley values of the character score (varimu.magic.factorial).

Studies:
  5e3   fender_5e3_mods, Dry Guitar 8 s, volume_bright 0.7: sag (rectifier 3 silicon / 1
        5Y3GT), iron (cores linear / ja), heaters (off / on), noise (off / seed 1)
  tape  the tape machine (print_audio), drums 8 s, drive +6 dB: grain (none / seed 1),
        transport (flutter off / on)
  670   fairchild_670, drums 8 s: iron (linear / ja), noise (off / seed 1)

-> reports/magic/factorial/<study>/ (summary.json, the flagged pairs' WAVs loudness-matched).

  uv run --extra fast --extra listen python scripts/mechanism_factorial.py --study 5e3 [tape 670]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np

from varimu.config import REPO_ROOT
from varimu.magic import factorial, render
from varimu.sim.io import load_audio, write_audio

OUT = REPO_ROOT / "reports" / "magic" / "factorial"
SCREEN_DB = -40.0  # a screening level for listening candidates, not a threshold of hearing


def program(clip: str, seconds: float, fs: int) -> np.ndarray:
    x = load_audio(REPO_ROOT / "data" / "clips" / clip, fs)[: int(seconds * fs)]
    x = x * 10 ** (-18 / 20) / (np.std(x) + 1e-30)
    f = int(0.02 * fs)
    x[:f] *= np.linspace(0, 1, f)
    return x


def study_jobs(name: str, fs: int):
    """(factors, {subset: job})."""
    if name == "5e3":
        x = program("Dry Guitar.wav", 8.0, fs)
        factors = ["sag", "iron", "heaters", "noise"]
        jobs = {}
        for s in factorial.subsets(factors):
            jobs[s] = {
                "circuit": "fender_5e3_mods",
                "x": x,
                "overrides": {"volume_bright": 0.7, "rectifier": 1 if "sag" in s else 3},
                "cores": "ja" if "iron" in s else "linear",
                "heaters": True if "heaters" in s else False,
                "noise": 1 if "noise" in s else False,
            }
        return factors, jobs
    if name == "tape":
        x = program("drums_setmefree.wav", 8.0, fs)
        factors = ["grain", "transport"]
        jobs = {
            s: {
                "fn": render.tape_print,
                "x": x,
                "drive_db": 6.0,
                "noise_seed": 1 if "grain" in s else None,
                "flutter": "transport" in s,
            }
            for s in factorial.subsets(factors)
        }
        return factors, jobs
    if name == "670":
        x = program("drums_setmefree.wav", 8.0, fs)
        factors = ["iron", "noise"]
        jobs = {
            s: {
                "circuit": "fairchild_670",
                "x": x,
                "cores": "ja" if "iron" in s else "linear",
                "noise": 1 if "noise" in s else False,
            }
            for s in factorial.subsets(factors)
        }
        return factors, jobs
    raise SystemExit(f"unknown study {name}")


def run_study(name: str, fs: int) -> dict:
    factors, jobs = study_jobs(name, fs)
    keys = list(jobs)
    t0 = time.time()
    print(f"{name}: {len(keys)} renders", flush=True)
    outs = render.through_many([jobs[k] for k in keys])
    y = {k: o["out"] for k, o in zip(keys, outs, strict=True)}
    print(f"  rendered in {(time.time() - t0) / 60:.1f} min", flush=True)
    res = factorial.analyse(y, factors, score=factorial.character_power(y))
    res["score_all_db"] = 10 * np.log10(res["score_all"]) if res["score_all"] > 0 else None
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    # Listening candidates: flagged pairs above the screen; their signals and the outputs
    # with each factor pair on / off, loudness-matched.
    from varimu.listen.matching import match_loudness

    for pair, r in res["interactions"].items():
        if r["not_separable"] and r["level_db"] > SCREEN_DB:
            a, b = pair.split(" x ")
            sig = factorial.interaction(y, factors, a, b)
            write_audio(
                out / f"interaction_{a}_{b}.wav", sig / (np.abs(sig).max() + 1e-30) * 0.5, fs
            )
            others = frozenset(f for f in factors if f not in (a, b))
            four = [y[others], y[others | {a}], y[others | {b}], y[others | {a, b}]]
            n = min(len(v) for v in four)
            m, _ = match_loudness([v[:n] for v in four], fs)
            for tag, v in zip(["none", a, b, f"{a}+{b}"], m, strict=True):
                write_audio(out / f"pair_{a}_{b}__{tag}.wav", v, fs)
    (out / "summary.json").write_text(json.dumps(res, indent=1, default=float))
    print(
        json.dumps(
            {k: res[k] for k in ("main", "interactions", "shapley")},
            indent=1,
            default=lambda v: round(float(v), 2),
        ),
        flush=True,
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--study", nargs="+", default=["5e3", "tape", "670"])
    a = ap.parse_args()
    fs = render.sample_rate()
    for s in a.study:
        run_study(s, fs)
    return 0


if __name__ == "__main__":
    sys.exit(main())

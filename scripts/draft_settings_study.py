"""How much cheaper settings cost in sound and save in time: a first look at a fast
"draft" mode for real time (CIRCUIT_SIM_PLAN.md M8), with no engine changes.

    uv run --extra fast python scripts/draft_settings_study.py [--only eqp1a|670] [--seconds 3]

Each excerpt renders at production settings (config/sim_settings.yaml, untouched) and
at a ladder of draft settings, each adding one lever: local error control off, the
host rate at 48 kHz, a cheaper method (TR-BDF2 / trapezoidal), looser Newton
tolerances, 1x oversampling. Every draft is compared with the production render at
48 kHz (the production output decimated): the null (rms of the difference, dB re the
signal), the largest octave-band level difference from 31 Hz to 16 kHz (a tilt or a
lost top octave), and on the 670 the control voltage (rms and largest difference, V).
Speed is the wall time per second of audio, the 1 s of supply settling included, and
per simulated second (settling counted as audio: in real time it is a one-time cost).
Renders run one at a time through the render cache (varimu.sim.runner); --fresh
bypasses it and times every render (--repeat N: the best of N). Timings taken while
other renders run are inflated. Results -> reports/realtime/draft_study.json.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time

import numpy as np
from scipy.signal import resample_poly, welch

from varimu.config import REPO_ROOT
from varimu.sim import runner
from varimu.sim.io import TransientSettings, load_audio
from varimu.sim.ngspice import SimulationFailed

OUT = REPO_ROOT / "reports" / "realtime"
CLIPS = REPO_ROOT / "data" / "clips"
FADE_S = 0.02  # fade the excerpt in (DC on T101's primary at the start saturates it)
TRIM_S = 0.02  # compared without each end (the decimation filter's edges)
EQ_PANEL = {"lf_boost": 0.6, "lf_freq_hz": 60, "hf_boost": 0.5, "hf_boost_freq_khz": 10}
COMP_PANEL = {"input_atten_db": 0.0, "ac_threshold": 0.8, "time_constant": 2}  # the slice's

# (name, circuit or None for the 670, front panel, clip, start s)
CASES = {
    "eqp1a": [
        ("eqp1a drums", "pultec_eqp1a", EQ_PANEL, "drums_setmefree.wav", 1.0),
        ("eqp1a mix", "pultec_eqp1a", EQ_PANEL, "mix_longwayhome.wav", 10.0),
    ],
    "670": [
        ("670 arpeggio", None, COMP_PANEL, "Arpeggio04b_120_m_D#_16b.WAV", 0.0),
        ("670 mix", None, COMP_PANEL, "mix_longwayhome.wav", 10.0),
    ],
}

NO_EC = {"error_abstol": 0.0, "error_reltol": 0.0}
R48 = {**NO_EC, "sample_rate": 48000}
LOOSE = {"newton_reltol": 1e-3, "newton_vntol": 1e-2}
LADDER = [
    ("error control off", NO_EC),
    ("+ 48 kHz", R48),
    ("+ 48 kHz trbdf2", {**R48, "method": "trbdf2"}),
    ("+ 48 kHz trap", {**R48, "method": "trap"}),
    ("+ 48 kHz trap, loose Newton", {**R48, "method": "trap", **LOOSE}),
    ("+ 48 kHz trap 1x, loose Newton", {**R48, "method": "trap", "oversample": 1, **LOOSE}),
]


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-12)))


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x**2)))


def _half(x: np.ndarray) -> np.ndarray:
    """96 -> 48 kHz, padded with the edge values (a CV sits at tens of volts)."""
    return resample_poly(x, 1, 2, padtype="edge")


def _bands(x: np.ndarray, rate: int) -> np.ndarray:
    """Levels (dB) of the octave bands centred 31.5 Hz .. 16 kHz."""
    f, p = welch(x, rate, nperseg=8192)
    centres = 31.5 * 2.0 ** np.arange(10)
    return np.array([10 * np.log10(p[(f >= c / 2**0.5) & (f < c * 2**0.5)].sum() + 1e-30)
                     for c in centres])  # fmt: skip


def excerpt(clip: str, start_s: float, seconds: float, rate: int) -> np.ndarray:
    x = load_audio(CLIPS / clip, rate)
    i = int(start_s * rate)
    x = x[i : i + int(seconds * rate)].copy()
    n = int(FADE_S * rate)
    x[:n] *= np.linspace(0.0, 1.0, n)
    return x


def _speed(r: runner.Render, wall: float, settle_s: float) -> dict:
    audio = r.meta["duration_s"]
    return {"x_realtime": wall / audio, "x_realtime_steady": wall / (audio + settle_s)}


def _render(job: runner.RenderJob, s: TransientSettings, fresh: bool, repeat: int):
    """The render, and the best wall time of `repeat` runs (fresh: bypassing the cache,
    so every run is timed; else a cached render reports the wall time it was made in)."""
    walls, r = [], None
    for _ in range(repeat if fresh else 1):
        r = runner.render(job, settings=s, use_cache=not fresh)
        walls.append(r.meta["wall_s"])
    return r, min(walls)


def run_case(name, circuit, panel, clip, start_s, seconds, base: TransientSettings,
             fresh: bool = False, repeat: int = 1) -> dict:  # fmt: skip
    x96 = excerpt(clip, start_s, seconds, base.sample_rate)
    x48 = resample_poly(x96, 1, 2)  # the input: zero-padded, as rendered
    label = f"draft-study:{name}"
    hq, wall = _render(runner.RenderJob(x96, panel, label, circuit), base, fresh, repeat)
    ref = _half(hq.output)
    ref_cv = _half(hq.vectors["v(cv)"]) if "v(cv)" in hq.vectors else None
    e0 = int(TRIM_S * 48000)
    ref_bands = _bands(ref[e0 : len(ref) - e0], 48000)
    rows = [{"setting": "production", **_speed(hq, wall, base.settle_s), "cached": hq.cached}]
    for setting, change in LADDER:
        s = dataclasses.replace(base, **change)
        x = x48 if s.sample_rate == 48000 else x96
        try:
            r, wall = _render(runner.RenderJob(x, panel, label, circuit), s, fresh, repeat)
        except SimulationFailed as e:
            rows.append({"setting": setting, "failed": str(e)[:200]})
            continue
        y = r.output if s.sample_rate == 48000 else _half(r.output)
        n = min(len(y), len(ref))
        e = int(TRIM_S * 48000)
        y, ref_n = y[e : n - e], ref[e : n - e]
        row = {
            "setting": setting,
            **_speed(r, wall, s.settle_s),
            "cached": r.cached,
            "null_db": _db(_rms(y - ref_n) / _rms(ref_n)),
            "band_max_db": float(np.max(np.abs(_bands(y, 48000) - ref_bands))),
        }
        if ref_cv is not None:
            cv = r.vectors["v(cv)"]
            cv = cv if s.sample_rate == 48000 else _half(cv)
            d = cv[e : n - e] - ref_cv[e : n - e]
            row.update(cv_rms_v=_rms(d), cv_max_v=float(np.max(np.abs(d))),
                       cv_mean_v=float(np.mean(ref_cv[e : n - e])))  # fmt: skip
        rows.append(row)
    return {"case": name, "circuit": circuit or "fairchild_670", "panel": panel, "clip": clip,
            "start_s": start_s, "seconds": seconds, "fresh": fresh, "repeat": repeat,
            "rows": rows}  # fmt: skip


def _cell(row: dict, key: str, fmt: str) -> str:
    return format(row[key], fmt) if key in row else " " * int(fmt.split(".")[0])


def table(case: dict) -> str:
    lines = [
        f"\n{case['case']} ({case['clip']} from {case['start_s']} s, {case['seconds']} s)",
        f"  {'setting':32s} {'x RT':>6s} {'x RT*':>6s} {'null dB':>8s} {'band dB':>8s}"
        f" {'CV rms':>7s} {'CV max':>7s}",
    ]
    cols = [("x_realtime", "6.1f"), ("x_realtime_steady", "6.1f"), ("null_db", "8.1f"),
            ("band_max_db", "8.2f"), ("cv_rms_v", "7.3f"), ("cv_max_v", "7.3f")]  # fmt: skip
    for r in case["rows"]:
        if "failed" in r:
            lines.append(f"  {r['setting']:32s} failed: {r['failed']}")
        else:
            lines.append(f"  {r['setting']:32s} " + " ".join(_cell(r, k, f) for k, f in cols))
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=sorted(CASES), action="append")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--fresh", action="store_true", help="bypass the cache: time every render")
    ap.add_argument("--repeat", type=int, default=1, help="with --fresh: best of N runs")
    args = ap.parse_args()
    base = TransientSettings.from_sim_settings(engine="configured")
    if base.engine != "circuitsim":
        sys.exit("the study is about circuitsim (simulator.engine)")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "draft_study.json"
    results = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    t0 = time.perf_counter()
    for group in args.only or sorted(CASES):
        for case in CASES[group]:
            res = run_case(*case, args.seconds, base, args.fresh, args.repeat)
            results[res["case"]] = res
            print(table(res), flush=True)
            path.write_text(json.dumps(results, indent=1), encoding="utf-8", newline="\n")
    print(
        f"\n(x RT: wall / audio; x RT*: wall / (audio + settling), the steady cost per "
        f"simulated second; {time.perf_counter() - t0:.0f} s in all) -> {path}"
    )


if __name__ == "__main__":
    main()

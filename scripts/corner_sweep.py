"""Phase 3's "done when": the circuit simulates across the corners of the genome bounds,
and gain reduction rises with input level.

    uv run --extra fast python scripts/corner_sweep.py [--random 16] [--seed 0] [--quick]

Genomes (every circuit value linked to config/genome_bounds.yaml, plus the 6386 banks'
emission / mu / grid contact; a choice's corners are its first and last option):

- nominal; all at their minimum; all at their maximum;
- each parameter alone at its minimum and at its maximum (the rest nominal);
- `--random` corners: every parameter at its minimum or maximum, drawn from
  default_rng([seed, i]), with part tolerances on (passive_spread 1, a seed each).

Each runs set up as a technician would (varimu.sim.setup: B+ ADJ, BALANCE, ZERO);
the all-min / all-max / random corners also run as built (the trims at their
defaults). The signal: 0.1 s of silence, then 1 kHz at -30, -20, -10 and 0 dBFS
(0.06 s each), at the hottest front panel (pad 0 dB, threshold 1, TC1). Recorded
per genome: whether it simulated, the gain reduction per step and whether it rises,
the idle output (over the silence; oscillation shows there), the rails, and wall
time. Results: reports/corners/summary.json and the table printed at the end.
`--quick` runs the tests' subset (all-min, all-max, two random corners).
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import numpy as np

from varimu.circuit import netlist as nl
from varimu.config import REPO_ROOT, load_genome_bounds
from varimu.measure import metrics
from varimu.measure.signals import stepped_sine
from varimu.sim import fast, runner, setup
from varimu.sim.io import TransientSettings
from varimu.sim.ngspice import SimulationFailed

OUT = REPO_ROOT / "reports" / "corners"
FS = 96000
HOT = {"input_atten_db": 0.0, "ac_threshold": 1.0, "time_constant": 1}
SILENCE_S = 0.1
# Idle is measured over this part of the silence: the decimation filter (linear phase)
# rings ahead of the first step, so the window ends well before it.
IDLE_WINDOW_S = (0.01, 0.07)
IDLE_LIMIT_DBFS = -80.0  # idle output above this: oscillating (or hum, recorded either way)
GR_STEP_DB = 0.5  # gain reduction must rise by more than this per 10 dB step


def genome_space() -> dict[str, Any]:
    """Circuit key -> its bound (min/max or choices), for every genome-linked value."""
    bounds = load_genome_bounds()
    space = {k: bounds[path] for k, path in nl.genome_links().items()}
    for key in nl.TUBE_PARAMS:
        b = bounds.get(f"tubes.{key}")
        if b is not None and b.resolved:
            space[key] = b
    return space


def _corner(b, high: bool):
    if b.choices is not None:
        return b.choices[-1] if high else b.choices[0]
    v = b.max if high else b.min
    return int(v) if isinstance(b.min, int) and isinstance(b.max, int) else float(v)


def genomes(n_random: int, seed: int, quick: bool) -> list[tuple[str, dict, bool]]:
    """(label, overrides, also run untrimmed)."""
    space = genome_space()
    # The seed is an index, not a magnitude: corners take spread, not seed, to extremes.
    ranged = {k: b for k, b in space.items() if k != "passive_seed"}
    out = [
        ("all-min", {k: _corner(b, False) for k, b in ranged.items()}, True),
        ("all-max", {k: _corner(b, True) for k, b in ranged.items()}, True),
    ]
    for i in range(2 if quick else n_random):
        rng = np.random.default_rng([seed, i])
        g = {k: _corner(b, bool(rng.integers(2))) for k, b in ranged.items()}
        g |= {"passive_spread": 1.0, "passive_seed": int(rng.integers(2**31))}
        out.append((f"random-{i}", g, True))
    if quick:
        return out
    out.insert(0, ("nominal", {}, False))
    for k, b in ranged.items():
        for high in (False, True):
            out.append((f"{k}={_corner(b, high)}", {k: _corner(b, high)}, False))
    return out


def signal() -> tuple[np.ndarray, list[dict]]:
    sig = stepped_sine(
        freq_hz=1000, start_dbfs=-30, stop_dbfs=0, step_db=10, hold_s=0.06, sample_rate=FS
    )
    n0 = int(SILENCE_S * FS)
    segs = [dict(s, start=s["start"] + n0, stop=s["stop"] + n0) for s in sig.meta["segments"]]
    return np.concatenate([np.zeros(n0), sig.samples]), segs


def run_one(label: str, genome: dict, trimmed: bool) -> dict:
    x, segs = signal()
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    res: dict[str, Any] = {"label": label, "trimmed": trimmed, "genome": genome}
    t0 = time.perf_counter()
    try:
        ov = {**genome, **HOT}
        if trimmed:
            ov = setup.adjust(ov)
            res["trims"] = {k: ov[k] for k in setup.TRIMS}
        c = nl.build(ov)
        r = fast.run_transient(c.ir, x * s.full_scale_volts_peak, settings=s)
    except (SimulationFailed, ValueError, RuntimeError) as e:
        res |= {"simulated": False, "error": str(e)[:500], "wall_s": time.perf_counter() - t0}
        return res
    v = r.vectors
    y = v["v(out)"] / s.full_scale_volts_peak
    gains = np.array([g for _, g in metrics.segment_gains(x, y, segs)])
    gr = gains[0] - gains
    n0 = int(SILENCE_S * FS)
    quiet = y[int(IDLE_WINDOW_S[0] * FS) : int(IDLE_WINDOW_S[1] * FS)]
    idle = float(20 * np.log10(np.max(np.abs(quiet)) + 1e-30))
    spec = np.abs(np.fft.rfft((quiet - quiet.mean()) * np.hanning(len(quiet))))
    idle_hz = float(np.fft.rfftfreq(len(quiet), 1 / FS)[np.argmax(spec)])
    res |= {
        "simulated": True,
        "gr_db": [round(float(g), 2) for g in gr],
        "gr_rises": bool(np.all(np.diff(gr) > GR_STEP_DB)),
        "idle_out_dbfs": round(idle, 1),
        "idle_quiet": idle < IDLE_LIMIT_DBFS,
        "idle_peak_hz": round(idle_hz),
        "cv_min_v": round(float(np.min(v["v(cv)"])), 2),
        "rails_idle_v": {
            k: round(float(np.mean(v[f"v({k})"][:n0])), 2) for k in ("ur", "bp", "nb2", "nb4")
        },
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--random", type=int, default=16)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=runner.default_jobs())
    args = ap.parse_args()
    fast.check_build()
    todo = []
    for label, g, untrimmed_too in genomes(args.random, args.seed, args.quick):
        todo.append((label, g, True))
        if untrimmed_too:
            todo.append((label, g, False))
    print(f"{len(todo)} runs, {args.jobs} in parallel")
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(run_one, *t) for t in todo]
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            ok = r["simulated"] and r["gr_rises"] and r["idle_quiet"]
            how = "set up" if r["trimmed"] else "as built"
            gr = r.get("gr_db", r.get("error", ""))
            idle = r.get("idle_out_dbfs", "-")
            print(
                f"  {'ok  ' if ok else 'FLAG'} {r['label']:42s} {how:8s}  {gr}  "
                f"idle {idle} dBFS  {r['wall_s']:.0f} s",
                flush=True,
            )
    results.sort(key=lambda r: (r["label"], not r["trimmed"]))
    summary = {
        "runs": len(results),
        "simulated": sum(r["simulated"] for r in results),
        "gr_rises": sum(r.get("gr_rises", False) for r in results),
        "idle_quiet": sum(r.get("idle_quiet", False) for r in results),
        "flagged": [
            {
                k: r.get(k)
                for k in ("label", "trimmed", "error", "gr_db", "idle_out_dbfs", "idle_peak_hz")
            }
            for r in results
            if not (r["simulated"] and r["gr_rises"] and r["idle_quiet"])
        ],
        "results": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(
        f"\n{summary['simulated']}/{len(results)} simulated, {summary['gr_rises']} with gain "
        f"reduction rising, {summary['idle_quiet']} quiet at idle -> "
        f"{(OUT / 'summary.json').relative_to(REPO_ROOT)}"
    )
    for r in summary["flagged"]:
        print(f"  flagged: {r}")


if __name__ == "__main__":
    main()

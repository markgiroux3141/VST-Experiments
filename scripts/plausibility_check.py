"""Phase 4's "done when", second half: the plausibility checks catch broken genomes.

    uv run --extra fast python scripts/plausibility_check.py [--only NAME ...]

Genomes (varimu.measure.plausibility):

- nominal: must pass;
- Phase 3's flagged corner runs as recorded in reports/corners/summary.json
  (`phase3_flagged`: HF oscillators, low-frequency wander in weak-supply corners,
  gain reduction folding back), each in the state it was flagged in (set up or
  as built): must be rejected;
- deliberately broken genomes (`BROKEN`, values outside the bounds on purpose, one
  per failure the plan names): must be rejected by the checks expected of them.

Each runs `plausibility.screen`; "slow_release" runs the full suite's TC2 burst
and the timing checks instead. Results: reports/plausibility/summary.json and a
table; the exit status is 1 if a genome isn't judged as expected.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from varimu.config import REPO_ROOT
from varimu.measure import plausibility, suite
from varimu.sim import fast, runner

OUT = REPO_ROOT / "reports" / "plausibility"


def cases() -> dict[str, dict]:
    out = {"nominal": {"genome": {}, "adjust": True, "stage": "screen", "expect": "pass"}}
    for name, (g, adjust) in plausibility.phase3_flagged().items():
        out[name] = {"genome": g, "adjust": adjust, "stage": "screen", "expect": "reject"}
    for name, (g, expected, stage) in plausibility.BROKEN.items():
        out[f"broken:{name}"] = {
            "genome": g,
            "adjust": True,
            "stage": stage,
            "expect": sorted(expected),
        }
    return out


def judged_right(case: dict, res: dict) -> bool:
    if case["expect"] == "pass":
        return res["passes"]
    if case["expect"] == "reject":
        return not res["passes"]
    return not res["passes"] and bool(set(case["expect"]) & set(res["failed"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="+", metavar="NAME")
    ap.add_argument("--parallel", type=int, default=6, help="genomes screened at once")
    args = ap.parse_args()
    fast.check_build()
    todo = {k: v for k, v in cases().items() if not args.only or k in args.only}
    print(f"{len(todo)} genomes")
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {
            k: ex.submit(suite.judge, k, c["genome"], adjust=c["adjust"], stage=c["stage"])
            for k, c in todo.items()
        }
        results = {k: f.result() for k, f in futs.items()}
    rows, ok_all = {}, True
    print()
    for k, c in todo.items():
        res = results[k]
        ok = judged_right(c, res)
        ok_all &= ok
        verdict = "passes" if res["passes"] else f"rejected by {res['failed']}"
        want = c["expect"] if isinstance(c["expect"], str) else f"reject by one of {c['expect']}"
        print(f"  {'ok  ' if ok else 'MISS'} {k:42s} {verdict}  (expected: {want})")
        rows[k] = {**c, "result": res, "judged_right": ok}
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"code": runner.code_version(), "all_judged_right": ok_all, "genomes": rows}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str), "utf-8")
    path = (OUT / "summary.json").relative_to(REPO_ROOT)
    print(f"\n{'ALL RIGHT' if ok_all else 'MISSES'} -> {path}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()

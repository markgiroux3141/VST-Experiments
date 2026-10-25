"""How different can plausible units sound? A survey across the genome bounds (Phase 5 ->
Phase 6 decision, 2026-10-25).

    uv run --extra listen --extra fast python scripts/diversity_survey.py [--n 20] [--seed 0]

Phase 5 found units with realistic values (nominal, a unit built in tolerance, a
core swap) too close to choose between by preference. Phases 6-8 need units that
sound clearly different. This samples the genome's whole bounded space and
measures how different the plausible ones are:

- **Genomes** (`sample`): a Latin hypercube over every genome-linked circuit value
  and the 6386 banks' emission / mu / grid contact (corner_sweep.genome_space):
  for parameter p and unit i, the stratum perm_p[i] of n, jittered, each drawn from
  default_rng([seed, crc32(p)]) so a parameter added later moves no other; ranges
  wider than 4:1 log-spaced; choices (core materials, R115B) drawn evenly. Every
  unit is built with part tolerances on (passive_spread 1, its own seed).
- **Screened** by the plausibility checks (varimu.measure.plausibility, in
  parallel); rejected units are listed with their failing checks.
- **Matched** like the listening pool (varimu.listen.prepare: set up as the
  factory would, AC THRESHOLD solved for 6 dB of average GR) on the pool's bass and
  drum clips, EXCERPT_S excerpts, against nominal. Its own database
  (data/judgments/survey.sqlite) keeps the A/B page's pool clean.
- **Measured** (varimu.listen.difference.levels): each unit's difference from
  nominal, split into character (what no fixed filter explains) and tone, dB re
  nominal; the largest character difference between any two plausible units; and,
  as a hint only (n units against ~65 parameters), the parameters whose values rank
  with character (Spearman).

Writes reports/listening/diversity.json and prints a table.
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import corner_sweep  # noqa: E402

from varimu.config import DATA_DIR, REPO_ROOT  # noqa: E402
from varimu.listen import difference, prepare, store  # noqa: E402
from varimu.listen.candidates import Candidate, load_pool  # noqa: E402

OUT = REPO_ROOT / "reports" / "listening" / "diversity.json"
DB_FILE = DATA_DIR / "judgments" / "survey.sqlite"
CLIPS = ("bass_areasontoleave.wav", "drums_setmefree.wav")
TARGET_DB = 6.0
EXCERPT_S = 4.0
LOG_RATIO = 4.0  # a range wider than this (max / min, both > 0) is sampled log-spaced
SCREEN_JOBS = 6


def _value(b, u: float):
    """Bound b at fraction u in [0, 1)."""
    if b.choices is not None:
        return b.choices[min(int(u * len(b.choices)), len(b.choices) - 1)]
    lo, hi = float(b.min), float(b.max)
    if lo > 0 and hi / lo > LOG_RATIO:
        v = lo * (hi / lo) ** u
    else:
        v = lo + (hi - lo) * u
    return int(round(v)) if isinstance(b.min, int) and isinstance(b.max, int) else float(v)


def sample(n: int, seed: int) -> list[dict[str, Any]]:
    """n genomes, a Latin hypercube over the genome space (see the module docstring)."""
    space = {k: b for k, b in corner_sweep.genome_space().items()
             if k not in ("passive_seed", "passive_spread")}  # fmt: skip
    cols = {}
    for k, b in space.items():
        rng = np.random.default_rng([seed, zlib.crc32(k.encode())])
        u = (rng.permutation(n) + rng.random(n)) / n
        cols[k] = [_value(b, float(x)) for x in u]
    out = []
    for i in range(n):
        g = {k: cols[k][i] for k in space}
        g |= {"passive_spread": 1.0,
              "passive_seed": int(np.random.default_rng([seed, i, 7]).integers(2**31))}  # fmt: skip
        out.append(g)
    return out


def _spearman(x, y) -> float:
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    if rx.std() == 0 or ry.std() == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    pool = load_pool()
    pool = dataclasses.replace(pool, excerpt_s=EXCERPT_S)
    units = [Candidate(f"survey-{i:02d}", g, f"diversity survey, seed {args.seed}")
             for i, g in enumerate(sample(args.n, args.seed))]  # fmt: skip
    nominal = pool.candidates["nominal"]

    from varimu.measure import plausibility

    def screen_one(c: Candidate) -> dict:
        try:
            return plausibility.screen(dict(c.genome), log=lambda m: None)
        except Exception as e:  # noqa: BLE001 (a genome that doesn't simulate is a finding)
            return {"passes": False, "checks": {"simulates": {"passes": False}},
                    "error": f"{type(e).__name__}: {e}"[:300]}  # fmt: skip

    print(f"screening {len(units)} sampled units ({SCREEN_JOBS} at once) ...", flush=True)
    with ThreadPoolExecutor(SCREEN_JOBS) as ex:
        screens = dict(zip([c.id for c in units], ex.map(screen_one, units), strict=True))
    screens[nominal.id] = {"passes": True, "checks": {}}
    for c in units:
        s = screens[c.id]
        bad = [k for k, v in s["checks"].items() if not v["passes"]]
        print(f"  {c.name}: {'passes' if s['passes'] else f'rejected {bad}'}", flush=True)

    db = store.connect(DB_FILE)
    prepare.REPORT = OUT.with_name("diversity_matching.json")
    rep = prepare.prepare(pool, candidates=["nominal"], extra=units, clips=list(CLIPS),
                          targets=[TARGET_DB], db=db, screen=lambda c: screens[c.id],
                          log=lambda m: print(m, flush=True))  # fmt: skip
    version = prepare.code_version()
    rows = store.stimuli(db, version, solved_only=False, clips=CLIPS)
    rows = [r for r in rows if r["seconds"] <= EXCERPT_S + 1e-9 and r["gr_target_db"] == TARGET_DB]
    by = {(r["candidate"], r["clip"]): r for r in rows}

    def audio(r):
        return prepare._render_audio(r["render_key"])

    result: dict[str, Any] = {"seed": args.seed, "n": args.n, "clips": list(CLIPS),
                              "target_db": TARGET_DB, "excerpt_s": EXCERPT_S, "code": version,
                              "units": [], "between_units": {}}  # fmt: skip
    for c in units:
        entry = {"name": c.name, "genome": c.genome, "screen": screens[c.id]["passes"],
                 "rejected_by": [k for k, v in screens[c.id]["checks"].items() if not v["passes"]],
                 "per_clip": {}}  # fmt: skip
        for clip in CLIPS:
            r, r0 = by.get((c.name, clip)), by.get(("nominal", clip))
            if r is None or r0 is None:
                continue
            e = {"solved": bool(r["solved"]), "ac_threshold": r["ac_threshold"],
                 "gr_db": r["gr_db"]}  # fmt: skip
            if r["solved"] and r0["solved"]:
                e["vs_nominal_db"] = difference.levels(audio(r0), audio(r))
            entry["per_clip"][clip] = e
        result["units"].append(entry)

    # The largest character difference between any two plausible, solved units.
    for clip in CLIPS:
        ok = [c for c in [nominal, *units]
              if (c.name, clip) in by and by[(c.name, clip)]["solved"]]  # fmt: skip
        best = None
        for a, b in itertools.combinations(ok, 2):
            lv = difference.levels(audio(by[(a.name, clip)]), audio(by[(b.name, clip)]))
            if best is None or lv["character"] > best["levels_db"]["character"]:
                best = {"pair": [a.name, b.name], "levels_db": lv}
        result["between_units"][clip] = {"plausible_solved": len(ok), "most_character": best}

    # Hint: which parameters rank with character (n is small: read as a lead, not a law).
    hints = {}
    for clip in CLIPS:
        measured = [u for u in result["units"] if "vs_nominal_db" in u["per_clip"].get(clip, {})]
        pts = [(u["genome"], u["per_clip"][clip]["vs_nominal_db"]["character"]) for u in measured]
        if len(pts) < 6:
            continue
        rho = {}
        for k in pts[0][0]:
            vals = [g[k] for g, _ in pts]
            if isinstance(vals[0], str):
                cats = sorted(set(vals))
                vals = [cats.index(v) for v in vals]
            rho[k] = round(_spearman(np.array(vals, float), np.array([c for _, c in pts])), 2)
        hints[clip] = dict(sorted(rho.items(), key=lambda kv: -abs(kv[1]))[:6])
    result["character_rank_correlation_hint"] = hints
    result["matching"] = rep.get("summary", {})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, default=str), "utf-8")

    print(f"\n{'unit':12s} " + "  ".join(f"{c[:5]}: char / tone (AC)" for c in CLIPS))
    for u in result["units"]:
        cells = []
        for clip in CLIPS:
            e = u["per_clip"].get(clip)
            if not u["screen"]:
                cells.append("rejected".ljust(26))
            elif e is None or "vs_nominal_db" not in e:
                cells.append(("unsolved" if e else "-").ljust(26))
            else:
                lv = e["vs_nominal_db"]
                cells.append(f"{lv['character']:6.1f} / {lv['tone']:6.1f} ({e['ac_threshold']:.2f})"
                             .ljust(26))  # fmt: skip
        print(f"{u['name']:12s} " + "  ".join(cells))
    for clip, b in result["between_units"].items():
        m = b["most_character"]
        if m:
            print(
                f"{clip}: most character between plausible units {m['levels_db']['character']}"
                f" dB ({m['pair'][0]} vs {m['pair'][1]}; {b['plausible_solved']} units)"
            )
    for clip, h in hints.items():
        print(f"{clip}: ranks with character (hint, n={args.n}): {h}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()

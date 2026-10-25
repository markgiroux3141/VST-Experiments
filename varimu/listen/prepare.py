"""Prepare a listening pool (Phase 5): match every stimulus, store it, verify the matching.

    uv run --extra listen --extra fast varimu ab-prepare [--candidates NAME ...] [--targets 3 6]

For every program clip in data/clips (the user's material; skipped cleanly when
there is none), every candidate of the pool (config/listening.yaml, or the parts
sandbox's swaps) and every gain-reduction target: the matched stimulus
(varimu.listen.stimuli.match), stored in the judgments database. Then the
verification by measurement, reports/listening/matching.json:

- gain reduction: each stimulus's average GR, re-measured from its renders,
  against its target (solved within GR_TOL_DB, or flagged unreachable);
- candidates the plausibility screen rejects (varimu.measure.plausibility) are left
  out and listed;
- loudness: every pair a session can present, loudness-matched as playback does
  it (stimuli.verify_pair), its two integrated LUFS after the gains.
"""

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from varimu.config import REPO_ROOT, load_sim_settings
from varimu.listen import stimuli, store
from varimu.listen.candidates import Candidate, Pool, load_pool

REPORT = REPO_ROOT / "reports" / "listening" / "matching.json"
LUFS_TOL = 0.1  # LU, the pair after matching
PARALLEL_MATCHES = 4  # (candidate, clip) groups at once; each renders its grid in parallel


def code_version() -> str:
    """What a stored stimulus is valid for: the code (runner.code_version) and every
    config file that defines the circuit (a material refit changes renders without
    touching code). The pool file is left out: adding a candidate keeps the others."""
    import hashlib

    from varimu.config import CONFIG_DIR
    from varimu.sim import runner

    h = hashlib.sha256()
    for p in sorted(CONFIG_DIR.rglob("*.yaml")):
        if p.name != "listening.yaml":
            h.update(p.relative_to(CONFIG_DIR).as_posix().encode() + p.read_bytes())
    return f"{runner.code_version()}+cfg{h.hexdigest()[:10]}"


def prepare(
    pool: Pool | None = None,
    *,
    candidates: Sequence[str] | None = None,
    extra: Sequence[Candidate] = (),
    targets: Sequence[float] | None = None,
    clips: Sequence[str] | None = None,
    db=None,
    render: stimuli.RenderFn | None = None,
    render_audio: Callable[[str], np.ndarray] | None = None,
    screen: Callable[[Candidate], dict] | None = None,
    log: Callable[[str], Any] = print,
) -> dict[str, Any]:
    """Screen, match, store and verify (`render`, `render_audio`, `screen`: stand-ins
    for the circuit renderer, the render cache and the plausibility screen, for tests).
    A candidate the screen rejects is left out: a broken unit isn't listened to."""
    pool = pool or load_pool()
    names = list(candidates or pool.candidates)
    cands = [pool.candidates[n] for n in names] + list(extra)
    screen = screen or _screen
    rejected = {}
    for c in cands:
        res = screen(c)
        if not res["passes"]:
            rejected[c.name] = [k for k, v in res["checks"].items() if not v["passes"]]
            log(f"{c.name}: rejected by the plausibility screen {rejected[c.name]}: left out")
    cands = [c for c in cands if c.name not in rejected]
    targets = list(targets or pool.gr_targets_db)
    available = stimuli.clip_names()
    if clips is None and pool.pool_clips:
        missing = [c for c in pool.pool_clips if c not in available]
        if missing:
            log(
                f"pool clips not in data/clips (scripts/build_clips.py builds the mixes): "
                f"{missing}: left out"
            )
        clips = [c for c in pool.pool_clips if c in available]
    clips = list(clips or available)
    db = db or store.connect()
    version = code_version()
    if not clips:
        log("no program clips in data/clips: nothing to prepare (the user's material only)")
        return {"stimuli": [], "clips": []}
    for c in cands:
        store.put_candidate(db, c.id, c.name, c.genome, c.note)
    excerpts = {}
    for name in clips:
        cfg = pool.clips.get(name, {})
        ex = stimuli.default_excerpt(name, pool.excerpt_s)
        if "start_s" in cfg or "seconds" in cfg:
            ex = stimuli.Excerpt(name, float(cfg.get("start_s", 0.0)),
                                 float(cfg.get("seconds", pool.excerpt_s)))  # fmt: skip
        excerpts[name] = (ex, stimuli.excerpt_audio(ex), str(cfg.get("category", "unknown")))
    setups = {c.id: stimuli.unit_overrides(c) for c in cands}
    todo = [(c, clip) for c in cands for clip in clips]
    log(f"{len(todo) * len(targets)} stimuli: {len(cands)} candidates x {len(clips)} clips x "
        f"{targets} dB")  # fmt: skip

    def one(item):
        # One (candidate, clip)'s targets in turn: they share the reference and the grid,
        # which the first renders and the rest find cached (at once, both would render
        # them).
        c, clip = item
        ex, x, _ = excerpts[clip]
        return [
            stimuli.match(
                c, ex, t, pool.time_constant, render=render, base=setups[c.id], x=x, log=log
            )
            for t in targets
        ]

    with ThreadPoolExecutor(PARALLEL_MATCHES) as pex:
        done = [s for group in pex.map(one, todo) for s in group]
    for s in done:
        store.put_stimulus(db, s.public(), excerpts[s.clip][2], version)
    report = verify(db, version, render_audio, clips=clips)
    report["summary"]["rejected_candidates"] = rejected
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1, default=str), "utf-8")
    log(f"matching: {report['summary']} -> {REPORT}")
    return report


def _screen(c: Candidate) -> dict:
    from varimu.measure import plausibility

    return plausibility.screen(dict(c.genome), log=lambda m: None)


def _render_audio(key: str) -> np.ndarray:
    from varimu.sim import runner

    return runner.load_render(runner.RENDER_DIR / key).output


def verify(db, version: str, render_audio=None, clips=None) -> dict[str, Any]:
    """Re-measure every stored stimulus's GR (of `clips`, default all) from its renders
    and every pair's loudness after matching (render_audio: render key -> output
    samples)."""
    render_audio = render_audio or _render_audio
    fs = load_sim_settings().sample_rate
    rows = store.stimuli(db, version, solved_only=False, clips=clips)
    out_stim, by_cond = [], defaultdict(list)
    for r in rows:
        y = render_audio(r["render_key"])
        gr = stimuli.average_gr_db(render_audio(r["reference_key"]), y, fs)
        out_stim.append(
            {
                "candidate": r["candidate"],
                "clip": r["clip"],
                "gr_target_db": r["gr_target_db"],
                "solved": bool(r["solved"]),
                "ac_threshold": r["ac_threshold"],
                "gr_db": round(gr, 3),
                "gr_error_db": round(gr - r["gr_target_db"], 3),
            }
        )
        if r["solved"]:
            by_cond[(r["clip"], r["start_s"], r["seconds"], r["time_constant"],
                     r["gr_target_db"])].append((r, y))  # fmt: skip
    pairs = []
    for cond, group in by_cond.items():
        for (ra, ya), (rb, yb) in itertools.combinations(group, 2):
            v = stimuli.verify_pair(ya, yb, fs)
            pairs.append(
                {
                    "clip": cond[0],
                    "gr_target_db": cond[4],
                    "candidates": [ra["candidate"], rb["candidate"]],
                    "lufs_before": v["lufs_before"],
                    "lufs_after": v["lufs_after"],
                    "lufs_diff": v["lufs_diff"],
                }
            )
    solved = [s for s in out_stim if s["solved"]]
    worst_gr = max((abs(s["gr_error_db"]) for s in solved), default=None)
    worst_lufs = max((p["lufs_diff"] for p in pairs), default=None)
    return {
        "code": version,
        "summary": {
            "stimuli": len(out_stim),
            "solved": len(solved),
            "unreachable": [
                f"{s['candidate']} {s['clip']} {s['gr_target_db']:g} dB"
                for s in out_stim
                if not s["solved"]
            ],  # fmt: skip
            "worst_gr_error_db": worst_gr,
            "gr_tolerance_db": stimuli.GR_TOL_DB,
            "pairs": len(pairs),
            "worst_lufs_diff": worst_lufs,
            "lufs_tolerance": LUFS_TOL,
            "verified": bool(solved)
            and worst_gr <= stimuli.GR_TOL_DB + 1e-9
            and (worst_lufs is None or worst_lufs <= LUFS_TOL),
        },
        "stimuli": out_stim,
        "pairs": pairs,
    }

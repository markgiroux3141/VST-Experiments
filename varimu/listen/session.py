"""A blind A/B session (Phase 5): which pairs, in which order, which side is A.

- Pairs: every two candidates matched on the same condition (clip excerpt, Time
  Constant, gain-reduction target), in a random order.
- Blind and randomized: which stimulus plays as A is drawn per trial; the page
  never sees candidate names.
- Repeats: after REPEAT_AFTER trials, each next trial is, with REPEAT_P, a repeat
  of an answered trial at least REPEAT_GAP back (sides drawn again), so the
  listener's own consistency can be measured (`consistency`).
- Breaks: the page suggests one after BREAK_AFTER_S of session time.

All randomness is one `np.random.Generator` seeded from the session's seed.
"""

from __future__ import annotations

import itertools
import secrets
import sqlite3
import time
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np

from varimu.listen import store

REPEAT_P = 0.15
REPEAT_AFTER = 4
REPEAT_GAP = 3
BREAK_AFTER_S = 25 * 60


def condition(s: sqlite3.Row | dict) -> tuple:
    return (s["clip"], s["start_s"], s["seconds"], s["time_constant"], s["gr_target_db"])


def plan(stims: Sequence[sqlite3.Row | dict], rng: np.random.Generator) -> list[dict[str, Any]]:
    """The session's first-pass trials: every pair of candidates per condition, shuffled,
    sides random."""
    by_cond: dict[tuple, list] = defaultdict(list)
    for s in stims:
        by_cond[condition(s)].append(s)
    pairs = []
    for cond in sorted(by_cond, key=str):
        group = sorted(by_cond[cond], key=lambda s: s["candidate_id"])
        pairs += [(a, b) for a, b in itertools.combinations(group, 2)]
    order = rng.permutation(len(pairs))
    out = []
    for idx, i in enumerate(order):
        a, b = pairs[i]
        if rng.random() < 0.5:
            a, b = b, a
        out.append(
            {
                "idx": idx,
                "stimulus_a": a["id"],
                "stimulus_b": b["id"],
                "candidate_a": a["candidate_id"],
                "candidate_b": b["candidate_id"],
                "clip": a["clip"],
                "clip_category": a["clip_category"],
                "gr_target_db": a["gr_target_db"],
            }
        )
    return out


def start(db, stims, *, listener: str = "", code_version: str, seed: int | None = None) -> str:
    seed = int(secrets.randbits(31)) if seed is None else int(seed)
    sid = time.strftime("%Y%m%d-%H%M%S") + f"-{seed:08x}"
    store.new_session(db, sid, seed, listener, code_version)
    store.add_trials(db, sid, plan(stims, np.random.default_rng([seed, 1])))
    return sid


def _rng(db, sid: str, n_answered: int) -> np.random.Generator:
    seed = db.execute("SELECT seed FROM sessions WHERE id = ?", (sid,)).fetchone()["seed"]
    return np.random.default_rng([seed, 2, n_answered])


def next_trial(db, sid: str) -> sqlite3.Row | None:
    """The trial to present: an unanswered one already presented (a reload), else a
    repeat (by chance), else the next planned one; None when the plan is done."""
    open_ = db.execute(
        "SELECT * FROM trials WHERE session_id = ? AND answered_at IS NULL AND presented_at "
        "IS NOT NULL ORDER BY idx LIMIT 1",
        (sid,),
    ).fetchone()
    if open_ is not None:
        return open_
    answered = db.execute(
        "SELECT * FROM trials WHERE session_id = ? AND answered_at IS NOT NULL ORDER BY idx",
        (sid,),
    ).fetchall()
    pending = db.execute(
        "SELECT * FROM trials WHERE session_id = ? AND presented_at IS NULL AND repeat_of IS NULL "
        "ORDER BY idx LIMIT 1",
        (sid,),
    ).fetchone()
    if pending is None:
        return None
    rng = _rng(db, sid, len(answered))
    repeated = {r["repeat_of"] for r in answered if r["repeat_of"] is not None}
    pool = [
        r for r in answered[: max(0, len(answered) - REPEAT_GAP)]
        if r["repeat_of"] is None and r["id"] not in repeated
    ]  # fmt: skip
    if pool and len(answered) >= REPEAT_AFTER and rng.random() < REPEAT_P:
        orig = pool[int(rng.integers(len(pool)))]
        a, b = (orig["stimulus_a"], orig["stimulus_b"])
        ca, cb = orig["candidate_a"], orig["candidate_b"]
        if rng.random() < 0.5:
            a, b, ca, cb = b, a, cb, ca
        idx = db.execute(
            "SELECT MAX(idx) AS m FROM trials WHERE session_id = ?", (sid,)
        ).fetchone()["m"]
        db.execute(
            "INSERT INTO trials (session_id, idx, stimulus_a, stimulus_b, candidate_a, "
            "candidate_b, clip, clip_category, gr_target_db, repeat_of) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, idx + 1, a, b, ca, cb, orig["clip"], orig["clip_category"],
             orig["gr_target_db"], orig["id"]),
        )  # fmt: skip
        db.commit()
        return db.execute(
            "SELECT * FROM trials WHERE session_id = ? AND idx = ?", (sid, idx + 1)
        ).fetchone()
    return pending


def consistency(db, sid: str | None = None) -> dict[str, Any]:
    """Repeats answered the same way as their originals (the preferred candidate, or
    'none' both times): the listener's own consistency, the realistic ceiling for a
    preference model (plan, Phase 6)."""
    q = (
        "SELECT r.preferred AS p2, r.choice AS c2, o.preferred AS p1, o.choice AS c1 "
        "FROM trials r JOIN trials o ON o.id = r.repeat_of WHERE r.answered_at IS NOT NULL "
        "AND o.answered_at IS NOT NULL"
    )
    rows = db.execute(
        q + (" AND r.session_id = ?" if sid else ""), (sid,) if sid else ()
    ).fetchall()
    same = sum((r["p1"] == r["p2"]) if r["c1"] != "none" else (r["c2"] == "none") for r in rows)
    return {"repeats": len(rows), "same": same, "rate": same / len(rows) if rows else None}


def progress(db, sid: str) -> dict[str, Any]:
    s = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if s is None:
        raise KeyError(sid)
    n = db.execute(
        "SELECT COUNT(*) AS n, SUM(answered_at IS NOT NULL) AS done, "
        "SUM(repeat_of IS NULL) AS planned FROM trials WHERE session_id = ?",
        (sid,),
    ).fetchone()
    elapsed = time.time() - s["started_at"]
    return {
        "session": sid,
        "answered": n["done"] or 0,
        "planned": n["planned"] or 0,
        "elapsed_s": round(elapsed, 1),
        "break_suggested": elapsed >= BREAK_AFTER_S,
        "consistency": consistency(db, sid),
    }

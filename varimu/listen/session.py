"""A blind A/B session (Phase 5): which pairs, in which order, which side is A.

- Pairs: every two candidates matched on the same condition (clip excerpt, Time
  Constant, gain-reduction target), in a random order.
- Blind and randomized: which stimulus plays as A is drawn per trial; the page
  never sees candidate names.
- Repeats: a fixed number per session (N_REPEATS, fewer only when the plan is
  too short), at seeded positions after the first REPEAT_AFTER answers
  (`repeat_schedule`): each repeats an answered trial at least REPEAT_GAP back
  (sides drawn again), so the listener's own consistency can be measured
  (`consistency`). (Until 2026-10-24 they were a 15% chance per trial: a
  12-trial session got none ~27% of the time.)
- Position bias: the share of A among the A / B answers (`store.share_a`), in
  the progress and stored with the session at its end.
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

N_REPEATS = 3
REPEAT_AFTER = 4
REPEAT_GAP = 3
BREAK_AFTER_S = 25 * 60


def condition(s: sqlite3.Row | dict) -> tuple:
    return (s["clip"], s["start_s"], s["seconds"], s["time_constant"], s["gr_target_db"])


def pairs(stims: Sequence[sqlite3.Row | dict]) -> list[tuple[Any, Any]]:
    """Every pair of candidates per condition, in a fixed order."""
    by_cond: dict[tuple, list] = defaultdict(list)
    for s in stims:
        by_cond[condition(s)].append(s)
    out = []
    for cond in sorted(by_cond, key=str):
        group = sorted(by_cond[cond], key=lambda s: s["candidate_id"])
        out += [(a, b) for a, b in itertools.combinations(group, 2)]
    return out


def plan(stims: Sequence[sqlite3.Row | dict], rng: np.random.Generator) -> list[dict[str, Any]]:
    """The session's first-pass trials: every pair of candidates per condition, shuffled,
    sides random."""
    every = pairs(stims)
    order = rng.permutation(len(every))
    out = []
    for idx, i in enumerate(order):
        a, b = every[i]
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


def n_repeats(n_planned: int) -> int:
    """Repeats a session of n_planned first-pass trials gets."""
    return max(0, min(N_REPEATS, n_planned - REPEAT_AFTER + 1))


def repeat_schedule(seed: int, n_planned: int, n_rep: int) -> list[int]:
    """Answer counts at which a repeat is presented: n_rep distinct, seeded positions
    from REPEAT_AFTER to the end of the session (n_planned + n_rep trials)."""
    slots = np.arange(REPEAT_AFTER, n_planned + n_rep)
    if n_rep <= 0 or len(slots) < n_rep:
        return []
    rng = np.random.default_rng([seed, 4])
    return sorted(int(v) for v in rng.choice(slots, n_rep, replace=False))


def start(db, stims, *, listener: str = "", code_version: str, seed: int | None = None) -> str:
    seed = int(secrets.randbits(31)) if seed is None else int(seed)
    sid = time.strftime("%Y%m%d-%H%M%S") + f"-{seed:08x}"
    trials = plan(stims, np.random.default_rng([seed, 1]))
    store.new_session(db, sid, seed, listener, code_version, repeats=n_repeats(len(trials)))
    store.add_trials(db, sid, trials)
    return sid


def _rng(db, sid: str, n_answered: int) -> np.random.Generator:
    seed = db.execute("SELECT seed FROM sessions WHERE id = ?", (sid,)).fetchone()["seed"]
    return np.random.default_rng([seed, 2, n_answered])


def next_trial(db, sid: str) -> sqlite3.Row | None:
    """The trial to present: an unanswered one already presented (a reload), else a
    repeat (when the schedule has one at this point), else the next planned one;
    None when the plan and its repeats are done."""
    open_ = db.execute(
        "SELECT * FROM trials WHERE session_id = ? AND answered_at IS NULL AND (presented_at "
        "IS NOT NULL OR repeat_of IS NOT NULL) ORDER BY idx LIMIT 1",
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
    s = db.execute("SELECT seed, repeats FROM sessions WHERE id = ?", (sid,)).fetchone()
    n_planned = db.execute(
        "SELECT COUNT(*) AS n FROM trials WHERE session_id = ? AND repeat_of IS NULL", (sid,)
    ).fetchone()["n"]
    schedule = repeat_schedule(s["seed"], n_planned, s["repeats"] or 0)
    rng = _rng(db, sid, len(answered))
    repeated = {r["repeat_of"] for r in answered if r["repeat_of"] is not None}
    pool = [
        r for r in answered[: max(0, len(answered) - REPEAT_GAP)]
        if r["repeat_of"] is None and r["id"] not in repeated
    ]  # fmt: skip
    due = len(answered) in schedule and len(repeated) <= schedule.index(len(answered))
    if pool and due:
        orig = pool[int(rng.integers(len(pool)))]
        a, b = (orig["stimulus_a"], orig["stimulus_b"])
        ca, cb = orig["candidate_a"], orig["candidate_b"]
        if rng.random() < 0.5:
            a, b, ca, cb = b, a, cb, ca
        # In at the current position, the trials still to come one further on, so idx
        # stays the order of presentation (what "REPEAT_GAP back" counts in).
        # (Via negative values: UNIQUE (session_id, idx) holds after every row.)
        idx = len(answered)
        db.execute("UPDATE trials SET idx = -idx - 1 WHERE session_id = ? AND idx >= ?",
                   (sid, idx))  # fmt: skip
        db.execute("UPDATE trials SET idx = -idx WHERE session_id = ? AND idx < 0", (sid,))
        db.execute(
            "INSERT INTO trials (session_id, idx, stimulus_a, stimulus_b, candidate_a, "
            "candidate_b, clip, clip_category, gr_target_db, repeat_of) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, idx, a, b, ca, cb, orig["clip"], orig["clip_category"],
             orig["gr_target_db"], orig["id"]),
        )  # fmt: skip
        db.commit()
        return db.execute(
            "SELECT * FROM trials WHERE session_id = ? AND idx = ?", (sid, idx)
        ).fetchone()
    return pending  # None: the plan is done (a repeat the pool couldn't fill is dropped)


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
        "repeats_planned": s["repeats"] or 0,
        "share_a": store.share_a(db, sid),
        "elapsed_s": round(elapsed, 1),
        "break_suggested": elapsed >= BREAK_AFTER_S,
        "consistency": consistency(db, sid),
    }

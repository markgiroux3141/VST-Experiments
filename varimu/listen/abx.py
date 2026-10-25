"""ABX discrimination with an adaptive exaggeration staircase (Phase 5's listening aids).

Can the listener tell a matched pair apart at all, and by how much would the
difference have to grow to be heard? Per trial, A and B are a pair's two
stimuli, B possibly exaggerated (A + k (B - A), varimu.listen.difference), and
X is secretly one of them (seeded); the listener says which.

- **Staircase per pair** (`Staircase`), in log k: it starts large (K_START),
  steps down after each hit and up after each miss. With equal steps that rule
  would settle where half the answers are right, which in ABX is guessing, so
  the up step is 3x the down step (Kaernbach's weighted up-down, 1991): it
  settles at 75% correct, halfway between chance and certainty. The estimate
  (`Staircase.jnd_k`) is the geometric mean of k at the reversals, the first
  two left out once there are four. k ~ 1.5: the real difference is just
  audible; k ~ 6: preference answers on the pair are mostly noise.
- **Hits and a binomial p-value** per pair (`binomial_p`: one-sided, chance 1/2),
  over all its trials and over those at k <= 1 (the real difference or less).
- **An anchor** (`ANCHOR_TRIALS`): the prepared pair with the largest residual
  at K_ANCHOR, interleaved; missing it says the setup or the attention is off,
  not the units.
- **Position bias** per session: the share of "X is A" answers.
- Mode "fixed": every trial at one k (1: plain ABX on the real pairs).
- Part (`difference.PARTS`): B is exaggerated by the pair's whole difference
  ("all"), its character (what no fixed filter explains) or its tone (what one
  does), per session.

Judgments here are discrimination, never preference data: they live in their
own tables (varimu.listen.store, `abx_*`), and every trial that isn't the real pair
(k != 1, or a part other than "all") is flagged `exaggerated`. Everything played
is loudness matched and its GR measured (`difference.exaggerated_pair`). All
randomness: one generator per draw, seeded from the session's seed.
"""

from __future__ import annotations

import itertools
import json
import math
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from varimu.listen import difference, store

K_START = 8.0
K_MIN = 0.25
K_MAX = 16.0
STEP_DOWN_OCT = 0.25  # after a hit (log2 k)
UP_DOWN_RATIO = 3.0  # Kaernbach: settles at 3 / (3 + 1) = 75% correct
FIRST_STEP_OCT = 0.5  # down steps before the first miss: get to the region quickly
TRIALS_PER_PAIR = 12
ANCHOR_TRIALS = 3
K_ANCHOR = 8.0


def binomial_p(hits: int, n: int) -> float | None:
    """One-sided P(at least `hits` of `n` right by guessing, p = 1/2)."""
    if n <= 0:
        return None
    return sum(math.comb(n, i) for i in range(hits, n + 1)) / 2**n


@dataclass
class Staircase:
    """A weighted up-down staircase on log2 k (see the module docstring)."""

    k: float = K_START
    history: list[tuple[float, bool]] = field(default_factory=list)  # (k, hit)

    @classmethod
    def replay(cls, history: Sequence[tuple[float, bool]], k_start: float = K_START):
        s = cls(k_start)
        for _, hit in history:
            s.update(hit)
        return s

    def update(self, hit: bool) -> float:
        missed = any(not h for _, h in self.history) or not hit
        self.history.append((self.k, bool(hit)))
        lk = math.log2(self.k)
        if hit:
            lk -= STEP_DOWN_OCT if missed else FIRST_STEP_OCT
        else:
            lk += UP_DOWN_RATIO * STEP_DOWN_OCT
        self.k = float(2 ** np.clip(lk, math.log2(K_MIN), math.log2(K_MAX)))
        return self.k

    def reversals(self) -> list[float]:
        """k at each change of direction (a hit after a miss or the reverse)."""
        out = []
        for (_, h0), (k1, h1) in itertools.pairwise(self.history):
            if h0 != h1:
                out.append(k1)
        return out

    def jnd_k(self) -> float | None:
        r = self.reversals()
        if len(r) >= 4:
            r = r[2:]
        if not r:
            return None
        return float(2 ** np.mean(np.log2(r)))


def pairs(stims: Sequence[Any]) -> list[tuple[Any, Any]]:
    """Every two stimuli of one condition (as varimu.listen.session pairs them)."""
    from varimu.listen import session

    return session.pairs(stims)


def pair_key(sa: int, sb: int) -> str:
    return f"{min(sa, sb)}-{max(sa, sb)}"


def start(
    db,
    stims: Sequence[Any],
    *,
    residual_db,
    code_version: str,
    listener: str = "",
    seed: int | None = None,
    chosen: Sequence[tuple[int, int]] | None = None,
    mode: str = "staircase",
    k_fixed: float = 1.0,
    trials_per_pair: int = TRIALS_PER_PAIR,
    anchor_trials: int = ANCHOR_TRIALS,
    part: str = "all",
) -> str:
    """A new ABX session over the condition pairs of `stims` (or the `chosen` stimulus
    id pairs). `residual_db(stim_a, stim_b)`: the level of the pair's `part` (dB re A),
    which picks the anchor (the largest). `part`: what B is exaggerated by (A + k d,
    d the pair's whole difference, its character or its tone: difference.PARTS)."""
    if mode not in ("staircase", "fixed"):
        raise ValueError(f"mode must be staircase or fixed, not {mode!r}")
    if not 1 <= trials_per_pair <= 100:
        raise ValueError(f"trials per pair must be 1-100, not {trials_per_pair}")
    if part not in difference.PARTS:
        raise ValueError(f"part must be one of {difference.PARTS}, not {part!r}")
    if not K_MIN <= k_fixed <= K_MAX:
        raise ValueError(f"k must be within {K_MIN}-{K_MAX}, not {k_fixed}")
    seed = int(secrets.randbits(31)) if seed is None else int(seed)
    rng = np.random.default_rng([seed, 11])
    every = pairs(stims)
    if not every:
        raise LookupError("no pairs: prepare at least two candidates on one condition")
    sel = every
    if chosen:
        want = {pair_key(a, b) for a, b in chosen}
        sel = [p for p in every if pair_key(p[0]["id"], p[1]["id"]) in want]
        if not sel:
            raise LookupError("none of the chosen pairs is prepared")
    anchor = max(every, key=lambda p: residual_db(p[0], p[1]))
    sid = time.strftime("%Y%m%d-%H%M%S") + f"-x{seed:08x}"
    n = 1
    while db.execute("SELECT 1 FROM abx_sessions WHERE id = ?", (sid,)).fetchone():
        n += 1  # the same seed again within a second
        sid = sid.split("~")[0] + f"~{n}"
    store.new_abx_session(db, sid, seed, listener, code_version, {
        "mode": mode, "k_fixed": k_fixed, "trials_per_pair": trials_per_pair,
        "anchor_trials": anchor_trials, "k_start": K_START, "k_anchor": K_ANCHOR,
        "step_down_oct": STEP_DOWN_OCT, "up_down_ratio": UP_DOWN_RATIO, "part": part,
    })  # fmt: skip
    rows = []
    for a, b in sel:
        # Which side is the base of the extrapolation (A + k (B - A)): drawn per pair.
        if rng.random() < 0.5:
            a, b = b, a
        rows.append({"base": a["id"], "other": b["id"], "anchor": False,
                     "residual_db": round(float(residual_db(a, b)), 2)})  # fmt: skip
    a, b = anchor
    rows.append({"base": a["id"], "other": b["id"], "anchor": True,
                 "residual_db": round(float(residual_db(a, b)), 2)})  # fmt: skip
    store.add_abx_pairs(db, sid, rows)
    return sid


def _settings(db, sid: str) -> dict[str, Any]:
    s = db.execute("SELECT * FROM abx_sessions WHERE id = ?", (sid,)).fetchone()
    if s is None:
        raise KeyError(sid)
    return {"seed": s["seed"], "part": "all", **json.loads(s["settings"])}


def session_part(db, sid: str) -> str:
    """What the session exaggerates (sessions from before parts existed: "all")."""
    return _settings(db, sid)["part"]


def _k_for(db, pair, st: dict[str, Any]) -> float:
    if pair["anchor"]:
        return st["k_anchor"]
    if st["mode"] == "fixed":
        return float(st["k_fixed"])
    hist = db.execute(
        "SELECT k, hit FROM abx_trials WHERE pair_id = ? AND answered_at IS NOT NULL ORDER BY idx",
        (pair["id"],),
    ).fetchall()
    return Staircase.replay([(r["k"], bool(r["hit"])) for r in hist], st["k_start"]).k


def next_trial(db, sid: str):
    """The trial to present: an unanswered one already drawn (a reload), else a new one
    for a pair with trials left (drawn at random, the anchor's spread through the
    session), None when every pair is done."""
    st = _settings(db, sid)
    open_ = db.execute(
        "SELECT * FROM abx_trials WHERE session_id = ? AND answered_at IS NULL", (sid,)
    ).fetchone()
    if open_ is not None:
        return open_
    prs = db.execute("SELECT * FROM abx_pairs WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    done = {
        r["pair_id"]: r["n"]
        for r in db.execute(
            "SELECT pair_id, COUNT(*) AS n FROM abx_trials WHERE session_id = ? GROUP BY pair_id",
            (sid,),
        )
    }
    left = []
    for p in prs:
        n = st["anchor_trials"] if p["anchor"] else st["trials_per_pair"]
        left += [p] * max(0, n - done.get(p["id"], 0))
    if not left:
        return None
    idx = sum(done.values())
    rng = np.random.default_rng([st["seed"], 12, idx])
    p = left[int(rng.integers(len(left)))]
    k = _k_for(db, p, st)
    a_is_base = bool(rng.random() < 0.5)  # which of the two is labelled A
    x_is = "A" if rng.random() < 0.5 else "B"
    db.execute(
        "INSERT INTO abx_trials (session_id, pair_id, idx, k, exaggerated, anchor, a_is_base, "
        "x_is) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sid,
            p["id"],
            idx,
            k,
            int(k != 1.0 or st["part"] != "all"),
            p["anchor"],
            int(a_is_base),
            x_is,
        ),
    )
    db.commit()
    return db.execute(
        "SELECT * FROM abx_trials WHERE session_id = ? AND idx = ?", (sid, idx)
    ).fetchone()


def answer(db, trial_id: int, said: str, response_ms: float, plays: dict[str, int]) -> bool:
    """Store the answer ("A" or "B": what X is); whether it was right."""
    if said not in ("A", "B"):
        raise ValueError(f"answer must be A or B, not {said!r}")
    t = db.execute("SELECT * FROM abx_trials WHERE id = ?", (trial_id,)).fetchone()
    if t is None:
        raise KeyError(trial_id)
    if t["answered_at"] is not None:
        raise ValueError(f"trial {trial_id} already answered")
    if t["presented_at"] is None:
        raise ValueError(f"trial {trial_id} was not presented")
    hit = said == t["x_is"]
    db.execute(
        "UPDATE abx_trials SET answered_at = ?, answer = ?, hit = ?, response_ms = ?, plays = ? "
        "WHERE id = ?",
        (time.time(), said, int(hit), response_ms, json.dumps(plays), trial_id),
    )
    db.commit()
    return hit


def summary(db, sid: str) -> dict[str, Any]:
    """Per pair: trials, hits, p (all trials, and those at k <= 1), the staircase's k
    track and estimate; the anchor's hits; the session's position bias."""
    st = _settings(db, sid)
    out = []
    for p in db.execute("SELECT * FROM abx_pairs WHERE session_id = ? ORDER BY id", (sid,)):
        rows = db.execute(
            "SELECT k, hit FROM abx_trials WHERE pair_id = ? AND answered_at IS NOT NULL "
            "ORDER BY idx",
            (p["id"],),
        ).fetchall()
        n, hits = len(rows), sum(r["hit"] for r in rows)
        real = [r for r in rows if r["k"] <= 1.0]
        sc = Staircase.replay([(r["k"], bool(r["hit"])) for r in rows], st["k_start"])
        out.append({
            "pair": pair_key(p["base"], p["other"]), "base": p["base"], "other": p["other"],
            "anchor": bool(p["anchor"]), "residual_db": p["residual_db"],
            "trials": n, "hits": hits, "p": binomial_p(hits, n),
            "trials_k_le_1": len(real), "hits_k_le_1": sum(r["hit"] for r in real),
            "p_k_le_1": binomial_p(sum(r["hit"] for r in real), len(real)),
            "k_track": [round(r["k"], 3) for r in rows],
            "jnd_k": None if st["mode"] == "fixed" or p["anchor"] else sc.jnd_k(),
        })  # fmt: skip
    said = db.execute(
        "SELECT answer FROM abx_trials WHERE session_id = ? AND answered_at IS NOT NULL", (sid,)
    ).fetchall()
    n = len(said)
    return {
        "session": sid,
        "mode": st["mode"],
        "part": st["part"],
        "answered": n,
        "planned": sum(st["anchor_trials"] if p["anchor"] else st["trials_per_pair"] for p in out),
        "share_x_is_a": sum(r["answer"] == "A" for r in said) / n if n else None,
        "pairs": out,
    }

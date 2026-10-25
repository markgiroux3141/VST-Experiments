"""Listening results in SQLite (Phase 5): data/judgments/judgments.sqlite, never committed.

Tables:

- `candidates`: id (the genome's content address), name, genome (JSON), note;
- `stimuli`: one matched render per (candidate, clip excerpt, Time Constant, GR
  target): the solved AC THRESHOLD, the measured GR, the render keys (the cache
  holds the audio), the clip's category;
- `sessions`: id, seed, listener, start and end, the code version, the number of
  repeated pairs planned (NULL: a session from before 2026-10-24, when repeats
  were a chance draw) and the position bias (share of A among the A / B
  answers, stored at the end);
- `trials`: one presentation of a pair in a session: which stimulus played as A
  and as B (randomized), whether it repeats an earlier trial, the loudness
  match applied and measured, and the answer: A / B / none, the preferred
  candidate, response time, how often each side was played.

Discrimination (varimu.listen.abx), kept apart from the preference tables and
never preference data:

- `abx_sessions`: id, seed, listener, code version, start and end, its settings
  (JSON: mode, staircase steps, trials per pair) and position bias (share of
  "X is A" answers, at the end);
- `abx_pairs`: the session's pairs: the base stimulus of the extrapolation
  (A + k (B - A)) and the other, whether it is the anchor, its residual level;
- `abx_trials`: one ABX trial: the pair, k and the `exaggerated` flag (k != 1),
  which of the two was labelled A, what X was, the loudness match and GRs as
  played and any artifacts, the answer, hit, response time, plays per side.

Times are Unix seconds (UTC).
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from varimu.config import DATA_DIR

DB_FILE = DATA_DIR / "judgments" / "judgments.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    genome TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stimuli (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    clip TEXT NOT NULL,
    clip_category TEXT NOT NULL,
    start_s REAL NOT NULL,
    seconds REAL NOT NULL,
    time_constant INTEGER NOT NULL,
    gr_target_db REAL NOT NULL,
    solved INTEGER NOT NULL,
    ac_threshold REAL NOT NULL,
    gr_db REAL NOT NULL,
    render_key TEXT NOT NULL,
    reference_key TEXT NOT NULL,
    overrides TEXT NOT NULL,
    code_version TEXT NOT NULL,
    matched_at REAL NOT NULL,
    UNIQUE (candidate_id, clip, start_s, seconds, time_constant, gr_target_db, code_version)
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    seed INTEGER NOT NULL,
    listener TEXT NOT NULL DEFAULT '',
    code_version TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    repeats INTEGER,
    share_a REAL
);
CREATE TABLE IF NOT EXISTS trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    idx INTEGER NOT NULL,
    stimulus_a INTEGER NOT NULL REFERENCES stimuli(id),
    stimulus_b INTEGER NOT NULL REFERENCES stimuli(id),
    candidate_a TEXT NOT NULL,
    candidate_b TEXT NOT NULL,
    clip TEXT NOT NULL,
    clip_category TEXT NOT NULL,
    gr_target_db REAL NOT NULL,
    repeat_of INTEGER REFERENCES trials(id),
    gains_db TEXT,
    lufs_after TEXT,
    presented_at REAL,
    answered_at REAL,
    choice TEXT CHECK (choice IN ('A', 'B', 'none')),
    preferred TEXT,
    response_ms REAL,
    plays_a INTEGER,
    plays_b INTEGER,
    UNIQUE (session_id, idx)
);
CREATE TABLE IF NOT EXISTS abx_sessions (
    id TEXT PRIMARY KEY,
    seed INTEGER NOT NULL,
    listener TEXT NOT NULL DEFAULT '',
    code_version TEXT NOT NULL,
    settings TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    share_x_is_a REAL
);
CREATE TABLE IF NOT EXISTS abx_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES abx_sessions(id),
    base INTEGER NOT NULL REFERENCES stimuli(id),
    other INTEGER NOT NULL REFERENCES stimuli(id),
    anchor INTEGER NOT NULL,
    residual_db REAL
);
CREATE TABLE IF NOT EXISTS abx_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES abx_sessions(id),
    pair_id INTEGER NOT NULL REFERENCES abx_pairs(id),
    idx INTEGER NOT NULL,
    k REAL NOT NULL,
    exaggerated INTEGER NOT NULL,
    anchor INTEGER NOT NULL,
    a_is_base INTEGER NOT NULL,
    x_is TEXT NOT NULL CHECK (x_is IN ('A', 'B')),
    gains_db TEXT,
    lufs_after TEXT,
    gr_db TEXT,
    artifacts TEXT,
    presented_at REAL,
    answered_at REAL,
    answer TEXT CHECK (answer IN ('A', 'B')),
    hit INTEGER,
    response_ms REAL,
    plays TEXT,
    UNIQUE (session_id, idx)
);
"""

# Columns added after a table was first created: (table, column, declaration).
ADDED_COLUMNS = (("sessions", "repeats", "INTEGER"), ("sessions", "share_a", "REAL"))


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or DB_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    for table, col, decl in ADDED_COLUMNS:
        if col not in {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    db.commit()
    return db


def put_candidate(db, cid: str, name: str, genome: Mapping[str, Any], note: str = "") -> None:
    db.execute(
        "INSERT INTO candidates (id, name, genome, note) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET name = excluded.name, note = excluded.note",
        (cid, name, json.dumps(dict(genome), sort_keys=True, default=str), note),
    )
    db.commit()


def put_stimulus(db, s: Mapping[str, Any], category: str, code_version: str) -> int:
    """Store a matched stimulus (varimu.listen.stimuli.Stimulus.public()); its row id."""
    cols = (
        "candidate_id", "clip", "start_s", "seconds", "time_constant", "gr_target_db",
        "solved", "ac_threshold", "gr_db", "render_key", "reference_key",
    )  # fmt: skip
    vals = [s[c] for c in cols]
    vals[cols.index("solved")] = int(bool(s["solved"]))
    db.execute(
        f"INSERT INTO stimuli ({', '.join(cols)}, clip_category, overrides, code_version, "
        f"matched_at) VALUES ({', '.join('?' * len(cols))}, ?, ?, ?, ?) "
        "ON CONFLICT DO UPDATE SET solved = excluded.solved, ac_threshold = "
        "excluded.ac_threshold, gr_db = excluded.gr_db, render_key = excluded.render_key, "
        "reference_key = excluded.reference_key, overrides = excluded.overrides, "
        "clip_category = excluded.clip_category, matched_at = excluded.matched_at",
        (*vals, category, json.dumps(s["overrides"], sort_keys=True), code_version, time.time()),
    )
    db.commit()
    row = db.execute(
        "SELECT id FROM stimuli WHERE candidate_id = ? AND clip = ? AND start_s = ? AND "
        "seconds = ? AND time_constant = ? AND gr_target_db = ? AND code_version = ?",
        (s["candidate_id"], s["clip"], s["start_s"], s["seconds"], s["time_constant"],
         s["gr_target_db"], code_version),
    ).fetchone()  # fmt: skip
    return int(row["id"])


def stimuli(
    db, code_version: str, solved_only: bool = True, clips: Iterable[str] | None = None
) -> list[sqlite3.Row]:
    """The stored stimuli of a code version (of `clips` only, if given)."""
    q = "SELECT s.*, c.name AS candidate FROM stimuli s JOIN candidates c ON c.id = s.candidate_id"
    q += " WHERE s.code_version = ?" + (" AND s.solved = 1" if solved_only else "")
    rows = db.execute(q + " ORDER BY s.id", (code_version,)).fetchall()
    if clips is not None:
        keep = set(clips)
        rows = [r for r in rows if r["clip"] in keep]
    return rows


def new_session(
    db, sid: str, seed: int, listener: str, code_version: str, repeats: int | None = None
) -> None:
    db.execute(
        "INSERT INTO sessions (id, seed, listener, code_version, started_at, repeats) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sid, seed, listener, code_version, time.time(), repeats),
    )
    db.commit()


def add_trials(db, sid: str, rows: Iterable[Mapping[str, Any]]) -> None:
    db.executemany(
        "INSERT INTO trials (session_id, idx, stimulus_a, stimulus_b, candidate_a, candidate_b, "
        "clip, clip_category, gr_target_db) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                sid,
                r["idx"],
                r["stimulus_a"],
                r["stimulus_b"],
                r["candidate_a"],
                r["candidate_b"],
                r["clip"],
                r["clip_category"],
                r["gr_target_db"],
            )
            for r in rows
        ],  # fmt: skip
    )
    db.commit()


def presented(db, trial_id: int, gains_db, lufs_after) -> None:
    db.execute(
        "UPDATE trials SET presented_at = COALESCE(presented_at, ?), gains_db = ?, "
        "lufs_after = ? WHERE id = ?",
        (time.time(), json.dumps(gains_db), json.dumps(lufs_after), trial_id),
    )
    db.commit()


def answer(db, trial_id: int, choice: str, response_ms: float, plays_a: int, plays_b: int):
    t = db.execute("SELECT * FROM trials WHERE id = ?", (trial_id,)).fetchone()
    if t is None:
        raise KeyError(trial_id)
    if t["answered_at"] is not None:
        raise ValueError(f"trial {trial_id} already answered")
    preferred = {"A": t["candidate_a"], "B": t["candidate_b"]}.get(choice)
    db.execute(
        "UPDATE trials SET answered_at = ?, choice = ?, preferred = ?, response_ms = ?, "
        "plays_a = ?, plays_b = ? WHERE id = ?",
        (time.time(), choice, preferred, response_ms, plays_a, plays_b, trial_id),
    )
    db.commit()


def share_a(db, sid: str) -> float | None:
    """Position bias: the share of A among the session's A / B answers."""
    r = db.execute(
        "SELECT SUM(choice = 'A') AS a, SUM(choice IN ('A', 'B')) AS n FROM trials "
        "WHERE session_id = ? AND answered_at IS NOT NULL",
        (sid,),
    ).fetchone()
    return r["a"] / r["n"] if r["n"] else None


def end_session(db, sid: str) -> None:
    db.execute("UPDATE sessions SET ended_at = ?, share_a = ? WHERE id = ? AND ended_at IS NULL",
               (time.time(), share_a(db, sid), sid))  # fmt: skip
    db.commit()


# --- Discrimination (varimu.listen.abx) ---


def new_abx_session(
    db, sid: str, seed: int, listener: str, code_version: str, settings: Mapping[str, Any]
) -> None:
    db.execute(
        "INSERT INTO abx_sessions (id, seed, listener, code_version, settings, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sid, seed, listener, code_version, json.dumps(dict(settings), sort_keys=True),
         time.time()),
    )  # fmt: skip
    db.commit()


def add_abx_pairs(db, sid: str, rows: Iterable[Mapping[str, Any]]) -> None:
    db.executemany(
        "INSERT INTO abx_pairs (session_id, base, other, anchor, residual_db) "
        "VALUES (?, ?, ?, ?, ?)",
        [(sid, r["base"], r["other"], int(r["anchor"]), r["residual_db"]) for r in rows],
    )
    db.commit()


def abx_presented(db, trial_id: int, gains_db, lufs_after, gr_db, artifacts) -> None:
    db.execute(
        "UPDATE abx_trials SET presented_at = COALESCE(presented_at, ?), gains_db = ?, "
        "lufs_after = ?, gr_db = ?, artifacts = ? WHERE id = ?",
        (time.time(), json.dumps(gains_db), json.dumps(lufs_after), json.dumps(gr_db),
         json.dumps(list(artifacts)), trial_id),
    )  # fmt: skip
    db.commit()


def end_abx_session(db, sid: str, share_x_is_a: float | None) -> None:
    db.execute(
        "UPDATE abx_sessions SET ended_at = ?, share_x_is_a = ? WHERE id = ? AND ended_at IS NULL",
        (time.time(), share_x_is_a, sid),
    )
    db.commit()

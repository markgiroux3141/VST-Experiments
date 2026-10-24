"""Listening results in SQLite (Phase 5): data/judgments/judgments.sqlite, never committed.

Tables:

- `candidates`: id (the genome's content address), name, genome (JSON), note;
- `stimuli`: one matched render per (candidate, clip excerpt, Time Constant, GR
  target): the solved AC THRESHOLD, the measured GR, the render keys (the cache
  holds the audio), the clip's category;
- `sessions`: id, seed, listener, start and end, the code version;
- `trials`: one presentation of a pair in a session: which stimulus played as A
  and as B (randomized), whether it repeats an earlier trial, the loudness
  match applied and measured, and the answer: A / B / none, the preferred
  candidate, response time, how often each side was played.

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
    ended_at REAL
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
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or DB_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
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


def stimuli(db, code_version: str, solved_only: bool = True) -> list[sqlite3.Row]:
    q = "SELECT s.*, c.name AS candidate FROM stimuli s JOIN candidates c ON c.id = s.candidate_id"
    q += " WHERE s.code_version = ?" + (" AND s.solved = 1" if solved_only else "")
    return db.execute(q + " ORDER BY s.id", (code_version,)).fetchall()


def new_session(db, sid: str, seed: int, listener: str, code_version: str) -> None:
    db.execute(
        "INSERT INTO sessions (id, seed, listener, code_version, started_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (sid, seed, listener, code_version, time.time()),
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


def end_session(db, sid: str) -> None:
    db.execute("UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
               (time.time(), sid))  # fmt: skip
    db.commit()

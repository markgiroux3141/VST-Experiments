"""Blind A/B (Phase 5) without renders: the GR measure and solve on a synthetic
compressor, session planning, and a whole session through the app into SQLite.

The matching on real renders is tests/test_ab_matching.py.
"""

import hashlib
import json

import numpy as np
import pytest

pytest.importorskip("pyloudnorm")

from varimu.listen import candidates, prepare, session, stimuli, store  # noqa: E402

FS = 96000


def _program(seconds=3.0, seed=0):
    """Noise bursts at varying level: something with a level to compress."""
    rng = np.random.default_rng([seed, 7])
    n = int(seconds * FS)
    env = np.repeat(rng.uniform(0.05, 0.5, int(seconds * 10)), n // int(seconds * 10))
    return env[:n] * rng.standard_normal(n)[: len(env[:n])]


class Fake:
    """A stand-in compressor: gain reduction k * AC THRESHOLD^2 dB on every sample (k per
    candidate), unity at AC 0. Keeps every output for render_audio."""

    def __init__(self):
        self.audio: dict[str, np.ndarray] = {}

    def k(self, ov):
        return 6.0 + 4.0 * float(ov.get("passive_seed", 0)) + (2.0 if "t101_core_material" in ov
                                                                else 0.0)  # fmt: skip

    def __call__(self, jobs):
        out = []
        for x, ov in jobs:
            y = x * 10 ** (-self.k(ov) * ov["ac_threshold"] ** 2 / 20) * 0.9
            key = hashlib.sha256(json.dumps(ov, sort_keys=True).encode() + x.tobytes()).hexdigest()
            self.audio[key] = y
            out.append((y, key))
        return out


def test_average_gr_reads_a_known_reduction_and_gates_silence():
    x = np.concatenate([_program(2.0), np.zeros(FS)])
    assert stimuli.average_gr_db(x, x * 10 ** (-4.5 / 20), FS) == pytest.approx(4.5, abs=1e-9)


@pytest.mark.parametrize("target", [3.0, 6.0, 0.4])
def test_match_solves_ac_threshold_for_the_target(target):
    fake = Fake()
    c = candidates.Candidate("x", {})
    ex = stimuli.Excerpt("fake.wav", 0.0, 3.0)
    s = stimuli.match(c, ex, target, 2, render=fake, base={}, x=_program())
    assert s.solved
    assert abs(s.gr_db - target) <= stimuli.GR_TOL_DB
    assert s.ac_threshold == pytest.approx(np.sqrt(target / 6.0), abs=0.02)
    assert s.overrides["time_constant"] == 2 and s.renders <= len(stimuli.GRID) + 10


def test_match_refines_a_curved_threshold_law_in_several_steps():
    """A sharply curved GR(AC) (a knee): the first interpolation misses, and every
    refinement renders the same excerpt (not a stray variable)."""

    class Knee(Fake):
        def __call__(self, jobs):
            for x, _ in jobs:
                assert isinstance(x, np.ndarray) and len(x) > 1000
            return super().__call__(jobs)

        def k(self, ov):
            return 0.0

    knee = Knee()
    seen = []

    def render(jobs):
        out = []
        for x, ov in jobs:
            a = ov["ac_threshold"]
            seen.append(a)
            gr = 12.0 * max(0.0, a - 0.6) ** 0.5
            out.append((x * 10 ** (-gr / 20), f"k{a}"))
        knee(jobs)
        return out

    s = stimuli.match(candidates.Candidate("x", {}), stimuli.Excerpt("f", 0, 3), 0.5, 2,
                      render=render, base={}, x=_program())  # fmt: skip
    assert s.solved and abs(s.gr_db - 0.5) <= stimuli.GR_TOL_DB
    assert len(seen) > len(stimuli.GRID) + 4  # it took more than one refinement


def test_an_unreachable_target_is_flagged_not_faked():
    s = stimuli.match(candidates.Candidate("x", {}), stimuli.Excerpt("f", 0, 3), 20.0, 2,
                      render=Fake(), base={}, x=_program())  # fmt: skip
    assert not s.solved and s.ac_threshold == 1.0


def test_candidates_are_physical_and_the_sandbox_swaps_within_bounds():
    pool = candidates.load_pool()
    assert {"nominal", "t101_permalloy"} <= set(pool.candidates)
    with pytest.raises(ValueError):
        candidates.Candidate("bad", {"ac_threshold": 0.5}).validate()
    nom = pool.candidates["nominal"]
    c = candidates.swap(nom, "t102_core_material", "mumetall")
    assert c.genome == {"t102_core_material": "mumetall"} and c.id != nom.id
    with pytest.raises(ValueError):
        candidates.swap(nom, "t101_leakage_h", 10.0)  # outside its bounds
    parts = {p["key"]: p for p in candidates.catalog()}
    assert "grain_oriented_si_steel" in parts["t102_core_material"]["choices"]
    assert all(p["source"] for p in parts.values())


def _stims(n_cand=3, clips=("a.wav", "b.wav"), targets=(3.0, 6.0)):
    rows, i = [], 0
    for clip in clips:
        for t in targets:
            for c in range(n_cand):
                i += 1
                rows.append({"id": i, "candidate_id": f"c{c}", "clip": clip, "start_s": 0.0,
                             "seconds": 3.0, "time_constant": 2, "gr_target_db": t,
                             "clip_category": "test"})  # fmt: skip
    return rows


def test_plan_pairs_every_candidate_per_condition_with_seeded_sides():
    p1 = session.plan(_stims(), np.random.default_rng([5, 1]))
    p2 = session.plan(_stims(), np.random.default_rng([5, 1]))
    assert p1 == p2  # reproducible from the seed
    assert len(p1) == 4 * 3  # 4 conditions x 3 pairs
    for t in p1:
        assert t["candidate_a"] != t["candidate_b"]
    pairs = {(t["clip"], t["gr_target_db"], frozenset((t["candidate_a"], t["candidate_b"])))
             for t in p1}  # fmt: skip
    assert len(pairs) == 12
    firsts = [t["candidate_a"] < t["candidate_b"] for t in p1]
    assert 0 < sum(firsts) < len(firsts)  # sides are drawn, not fixed


@pytest.fixture()
def prepared(tmp_path, monkeypatch):
    """Two fake clips, the pool's candidates plus a sandbox swap, matched with the fake
    compressor into a temporary database."""
    fake = Fake()
    clips = {"one.wav": _program(3.0, 1), "two.wav": _program(4.0, 2)}
    monkeypatch.setattr(stimuli, "_clip", lambda name: clips[name])
    monkeypatch.setattr(stimuli, "unit_overrides", lambda c: dict(c.genome))
    monkeypatch.setattr(prepare, "REPORT", tmp_path / "matching.json")
    db = store.connect(tmp_path / "j.sqlite")
    pool = candidates.load_pool()
    swap = candidates.swap(pool.candidates["nominal"], "passive_seed", 1, "seed1")
    rep = prepare.prepare(pool, candidates=["nominal", "t101_permalloy"], extra=[swap],
                          clips=list(clips), db=db, render=fake, render_audio=fake.audio.get,
                          screen=lambda c: {"passes": True, "checks": {}},
                          log=lambda m: None)  # fmt: skip
    return db, fake, rep


def test_prepare_verifies_the_matching_by_measurement(prepared):
    db, _, rep = prepared
    s = rep["summary"]
    assert s["verified"], s
    assert s["stimuli"] == 3 * 2 * 2 and s["solved"] == 12
    assert s["worst_gr_error_db"] <= stimuli.GR_TOL_DB
    assert s["pairs"] == 2 * 2 * 3 and s["worst_lufs_diff"] <= prepare.LUFS_TOL
    assert json.loads((prepare.REPORT).read_text())["summary"] == s


def _run_session(start, next_, audio, answer):
    """Answer every trial of a session (choices cycling A, B, none); the trial count."""
    sid = start()
    answered, choices = 0, ["A", "B", "none"]
    while True:
        n = next_(sid)
        if n["done"]:
            return sid, answered
        assert n["first"] in ("A", "B") and "candidate" not in json.dumps(n)  # blind
        for side in ("A", "B"):
            assert audio(n["trial_id"], side)[:4] == b"RIFF"
        answer(n["trial_id"], choices[answered % 3])
        answered += 1


def _check_session(db, sid, answered):
    rows = db.execute("SELECT * FROM trials WHERE session_id = ?", (sid,)).fetchall()
    assert len(rows) == answered >= 12
    assert all(r["answered_at"] and r["response_ms"] == 1234.0 for r in rows)
    for r in rows:  # the pair was loudness matched as presented
        assert abs(np.diff(json.loads(r["lufs_after"]))[0]) <= prepare.LUFS_TOL
        assert (r["preferred"] is None) == (r["choice"] == "none")
    assert db.execute("SELECT ended_at FROM sessions WHERE id = ?", (sid,)).fetchone()[0]
    return rows


def test_prepare_leaves_out_what_the_screen_rejects(tmp_path, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(stimuli, "_clip", lambda name: _program(3.0, 1))
    monkeypatch.setattr(stimuli, "unit_overrides", lambda c: dict(c.genome))
    monkeypatch.setattr(prepare, "REPORT", tmp_path / "matching.json")
    bad = {"passes": False, "checks": {"idle_quiet": {"passes": False}}}
    rep = prepare.prepare(
        candidates.load_pool(), candidates=["nominal", "t101_permalloy"], clips=["one.wav"],
        targets=[3.0], db=store.connect(tmp_path / "j.sqlite"), render=fake,
        render_audio=fake.audio.get, log=lambda m: None,
        screen=lambda c: bad if c.name == "t101_permalloy" else {"passes": True, "checks": {}},
    )  # fmt: skip
    assert rep["summary"]["rejected_candidates"] == {"t101_permalloy": ["idle_quiet"]}
    assert {s["candidate"] for s in rep["stimuli"]} == {"nominal"}


def test_a_session_runs_end_to_end_into_sqlite(prepared):
    pytest.importorskip("fastapi")
    from varimu.listen import app as listen_app

    db, fake, _ = prepared
    ab = listen_app.AB(db=db, version=prepare.code_version(), render_audio=fake.audio.get)
    st = ab.status()
    assert st["ready"] and st["candidates"] == 3 and st["conditions"] == 4

    def answer(tid, choice):
        ab.answer(listen_app.AnswerRequest(trial_id=tid, choice=choice, response_ms=1234.0,
                                           plays_a=2, plays_b=1))  # fmt: skip

    sid, n = _run_session(
        lambda: ab.start("test", 11)["session"],
        ab.next,
        lambda tid, side: ab.audio[tid][0 if side == "A" else 1],
        answer,
    )
    rows = _check_session(db, sid, n)
    with pytest.raises(ValueError):  # an answer can't be changed afterwards
        answer(rows[0]["id"], "A")


def test_the_session_api_over_http(prepared):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from varimu.listen import app as listen_app

    db, fake, _ = prepared
    ab = listen_app.AB(db=db, version=prepare.code_version(), render_audio=fake.audio.get)
    client = TestClient(listen_app.create_app(workers=1, ab=ab))
    assert client.get("/ab").status_code == 200
    assert client.get("/api/ab/status").json()["ready"]

    def answer(tid, choice):
        r = client.post("/api/ab/answer", json={"trial_id": tid, "choice": choice,
                                                "response_ms": 1234.0})  # fmt: skip
        assert r.status_code == 200

    sid, n = _run_session(
        lambda: client.post("/api/ab/session", json={"seed": 12}).json()["session"],
        lambda sid: client.get("/api/ab/next", params={"session": sid}).json(),
        lambda tid, side: client.get(f"/api/ab/audio/{tid}/{side}.wav").content,
        answer,
    )
    rows = _check_session(db, sid, n)
    again = client.post("/api/ab/answer", json={"trial_id": rows[0]["id"], "choice": "A",
                                                 "response_ms": 1.0})  # fmt: skip
    assert again.status_code == 400


def test_repeats_measure_the_listeners_consistency(tmp_path):
    db = store.connect(tmp_path / "j.sqlite")
    for c in ("c0", "c1", "c2"):
        store.put_candidate(db, c, c, {})
    stims = []
    for s in _stims(clips=("a.wav", "b.wav", "c.wav")):
        sid_ = store.put_stimulus(db, {**s, "solved": True, "ac_threshold": 0.5, "gr_db": 3.0,
                                       "render_key": "k", "reference_key": "r",
                                       "overrides": {}}, "test", "v")  # fmt: skip
        stims.append({**s, "id": sid_})
    sid = session.start(db, stims, code_version="v", seed=3)
    prefs = {}
    while (t := session.next_trial(db, sid)) is not None:
        store.presented(db, t["id"], [0, 0], [-23, -23])
        # A consistent listener: always the lower candidate id.
        win = min(t["candidate_a"], t["candidate_b"])
        store.answer(db, t["id"], "A" if t["candidate_a"] == win else "B", 900.0, 1, 1)
        prefs[t["id"]] = win
    c = session.consistency(db, sid)
    assert c["repeats"] >= 1 and c["rate"] == 1.0

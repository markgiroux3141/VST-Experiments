"""Phase 5's listening aids without renders: difference listening and exaggeration
(varimu.listen.difference), the ABX staircase and its sessions (varimu.listen.abx),
the preference sessions' fixed repeats and position bias.

On real renders: tests/test_ab_matching.py (the exaggerated pair of a matched pair).
"""

import json

import numpy as np
import pytest

pytest.importorskip("pyloudnorm")

from test_ab import Fake, _program  # noqa: E402

from varimu.listen import (  # noqa: E402
    abx,
    candidates,
    difference,
    matching,
    prepare,
    session,
    stimuli,
    store,
)

FS = 96000


class Coloured(Fake):
    """The fake compressor plus a candidate-dependent odd harmonic: matched pairs that
    differ in more than gain, so they have a residual to listen to."""

    def __call__(self, jobs):
        out = []
        for (y, key), (_, ov) in zip(super().__call__(jobs), jobs, strict=True):
            h = 0.3 * (1 + float(ov.get("passive_seed", 0))) + (
                0.6 if "t101_core_material" in ov else 0.0
            )
            y = y + h * y**3
            self.audio[key] = y
            out.append((y, key))
        return out


# --- Difference listening and exaggeration ------------------------------------------------


def _pair(seed=0, colour=0.05):
    """A and B: the same program, B with a little cubic colour; references unlimited."""
    x = _program(2.0, seed)
    ref_a, ref_b = 1.2 * x, 1.1 * x
    a = 0.7 * x
    b = 0.6 * (x + colour * x**3)
    return a, b, ref_a, ref_b


def test_the_residual_is_what_a_gain_cannot_align():
    a, b, *_ = _pair()
    assert difference.align_gain(a, 0.5 * a) == pytest.approx(2.0)
    assert difference.residual_db(a, 0.5 * a) == float("-inf")
    g = difference.align_gain(a, b)
    r = a - g * b
    assert abs(np.dot(r, b)) < 1e-9 * np.dot(b, b)  # least squares: r is orthogonal to B
    assert -60 < difference.residual_db(a, b) < -10


def test_streams_are_a_b_and_their_extrapolations_at_one_loudness():
    a, b, ra, rb = _pair()
    res = difference.streams(a, b, ra, rb, FS)
    by = {s["name"]: s for s in res["streams"]}
    assert list(by) == ["A", "B", "A+2(B-A)", "A+4(B-A)", "A+8(B-A)"]
    lufs = [matching.integrated_lufs(s["audio"], FS) for s in res["streams"]]
    assert max(lufs) - min(lufs) <= prepare.LUFS_TOL
    # k = 0 and 1 are A and B (aligned): the same waveform up to the loudness gain.
    for name, y in (("A", a), ("B", b)):
        s = by[name]["audio"]
        assert np.corrcoef(s, y)[0, 1] > 1 - 1e-12 and not by[name]["exaggerated"]
    # The extrapolated unit's GR is exactly A's at k = 0 and B's at k = 1.
    assert by["A"]["gr_db"] == pytest.approx(stimuli.average_gr_db(ra, a, FS), abs=1e-3)
    assert by["B"]["gr_db"] == pytest.approx(stimuli.average_gr_db(rb, b, FS), abs=1e-3)
    assert all(by[n]["exaggerated"] for n in ("A+2(B-A)", "A+4(B-A)", "A+8(B-A)"))
    # The residual is turned up to the listening loudness, and says by how much.
    r = res["residual"]
    assert matching.integrated_lufs(r["audio"], FS) == pytest.approx(r["target_lufs"], abs=0.1)
    assert r["level_db"] == pytest.approx(difference.residual_db(a, b), abs=0.01)
    assert r["level_db"] < -10 and r["gain_db"] > by["A"]["gain_db"] + 10
    # The k = 8 stream's peaks lowered the shared loudness: said, not hidden.
    assert res["peak_limited"] == (res["target_lufs"] < matching.TARGET_LUFS)


def _noise(seconds=3.0, seed=11):
    """Broadband program (noise bursts at varying level): every frequency excited."""
    return 0.5 * _program(seconds, seed)


def test_the_parts_add_up_to_the_difference():
    a, b, *_ = _pair()
    dec = difference.decompose(a, b)
    np.testing.assert_allclose(dec.tone + dec.character, dec.g * b - a, atol=1e-12)
    np.testing.assert_allclose(dec.part("all"), dec.g * b - a, atol=1e-12)
    with pytest.raises(ValueError):
        dec.part("colour")


def test_a_filter_is_tone_not_character():
    """B = A through an EQ bump and a 2-sample delay (an LTI filter): the difference is
    all tone; the character part is the fit's own error, far below it."""
    from scipy.signal import lfilter

    a = _noise()
    w0, q, gain = 2 * np.pi * 2000 / FS, 1.0, 10 ** (3 / 40)  # +3 dB peaking at 2 kHz
    alpha = np.sin(w0) / (2 * q)
    num = [1 + alpha * gain, -2 * np.cos(w0), 1 - alpha * gain]
    den = [1 + alpha / gain, -2 * np.cos(w0), 1 - alpha / gain]
    b = np.concatenate([[0.0, 0.0], lfilter(num, den, a)[:-2]])
    lv = difference.levels(a, b)
    assert lv["tone"] == pytest.approx(lv["all"], abs=0.1), lv
    assert lv["character"] < lv["tone"] - 35, lv


def test_distortion_and_pumping_are_character_not_tone():
    """B = A plus a cubic term, or A with a 3 Hz gain modulation (+-0.5 dB): what no
    fixed filter explains. The character part is the distortion less its share that a
    filter can take (its correlation with A), within 1 dB; the tone part is far below."""
    a = _noise()
    d = 0.05 * a**3
    d_perp = d - np.dot(d, a) / np.dot(a, a) * a  # what a gain can't take
    lv = difference.levels(a, a + d)
    assert lv["character"] == pytest.approx(difference._rms_db(d_perp, a), abs=1.0), lv
    assert lv["tone"] < lv["character"] - 20, lv
    t = np.arange(len(a)) / FS
    pumped = a * 10 ** (0.5 * np.sin(2 * np.pi * 3 * t) / 20)
    lv = difference.levels(a, pumped)
    assert lv["tone"] < lv["character"] - 20, lv


def test_part_streams_and_their_k_1_hybrids():
    """Character at k = 1 is H B' (B's character in A's tone), tone at k = 1 is A + T;
    every part's streams are at one loudness and flagged exaggerated."""
    a, b, ra, rb = _pair(colour=0.08)
    dec = difference.decompose(a, b)
    hb = difference.apply_linear(dec.h, dec.g * b)
    one = difference.exaggerated_pair(a, b, ra, rb, 1.0, FS, part="character")
    assert np.corrcoef(one["audio"][1], hb)[0, 1] > 1 - 1e-9
    one = difference.exaggerated_pair(a, b, ra, rb, 1.0, FS, part="tone")
    assert np.corrcoef(one["audio"][1], a + dec.tone)[0, 1] > 1 - 1e-9
    for part in difference.PARTS:
        res = difference.streams(a, b, ra, rb, FS, part=part)
        assert res["part"] == part and set(res["levels_db"]) == set(difference.PARTS)
        lufs = [matching.integrated_lufs(s["audio"], FS) for s in res["streams"]]
        assert max(lufs) - min(lufs) <= prepare.LUFS_TOL
        assert [s["exaggerated"] for s in res["streams"]] == [False, False, True, True, True]
        assert res["residual"]["level_db"] == res["levels_db"][part]
    with pytest.raises(ValueError):
        difference.streams(a, b, ra, rb, FS, part="colour")


def test_envelope_differences_grow_with_k_and_are_reported():
    """Two units whose gain envelopes differ (B pumps 2 dB in alternate 0.1 s): at k = 8
    the extrapolation's envelope is far off A's, flagged as an artifact."""
    x = _program(2.0, 3)
    pump = np.repeat(np.tile([1.0, 10 ** (-2 / 20)], 10), len(x) // 20)[: len(x)]
    a, b = 0.7 * x, 0.7 * x * pump
    res = difference.streams(a, b, x, x, FS)
    env = {s["k"]: s["envelope"]["worst_db"] for s in res["streams"]}
    assert env[0.0] == 0.0 and 0.5 < env[1.0] < env[2.0] < env[4.0] < env[8.0]
    k8 = next(s for s in res["streams"] if s["k"] == 8.0)
    assert any("envelope" in w for w in k8["artifacts"])
    assert not next(s for s in res["streams"] if s["k"] == 1.0)["artifacts"]  # real pair


def test_the_exaggerated_pair_is_loudness_matched_and_measured():
    a, b, ra, rb = _pair()
    v = difference.exaggerated_pair(a, b, ra, rb, 4.0, FS)
    assert abs(v["lufs_after"][0] - v["lufs_after"][1]) <= prepare.LUFS_TOL
    assert v["gr_db"][0] == pytest.approx(stimuli.average_gr_db(ra, a, FS), abs=1e-3)
    one = difference.exaggerated_pair(a, b, ra, rb, 1.0, FS)
    assert one["gr_db"][1] == pytest.approx(stimuli.average_gr_db(rb, b, FS), abs=1e-3)


# --- The staircase -------------------------------------------------------------------------


def test_binomial_p():
    assert abx.binomial_p(12, 12) == pytest.approx(1 / 4096)
    assert abx.binomial_p(9, 12) == pytest.approx((220 + 66 + 12 + 1) / 4096)
    assert abx.binomial_p(0, 5) == 1.0 and abx.binomial_p(0, 0) is None


def test_the_staircase_steps_down_on_a_hit_and_up_on_a_miss():
    s = abx.Staircase()
    assert s.k == abx.K_START
    s.update(True)  # before the first miss: the big step
    assert s.k == pytest.approx(abx.K_START * 2**-abx.FIRST_STEP_OCT)
    k = s.k
    s.update(False)
    assert s.k == pytest.approx(k * 2 ** (abx.UP_DOWN_RATIO * abx.STEP_DOWN_OCT))
    k = s.k
    s.update(True)
    assert s.k == pytest.approx(k * 2**-abx.STEP_DOWN_OCT)
    for _ in range(40):
        s.update(True)
    assert s.k == pytest.approx(abx.K_MIN)  # clamped
    for _ in range(40):
        s.update(False)
    assert s.k == pytest.approx(abx.K_MAX)
    assert abx.Staircase.replay(s.history).k == s.k


def _listener(k75: float, seed: int):
    """A simulated listener: P(correct) rises from chance (1/2) with log k, 75% at k75."""
    rng = np.random.default_rng([seed, 99])

    def hit(k):
        p = 0.5 + 0.5 / (1 + (k75 / k) ** 3)
        return bool(rng.random() < p)

    return hit


@pytest.mark.parametrize("k75", [0.7, 1.5, 6.0])
def test_the_staircase_converges_on_the_75_percent_point(k75):
    """Kaernbach's weighted up-down (3:1) settles where P(correct) = 75%; over a long
    run the reversal estimate lands within a factor 1.4 of the simulated listener's."""
    ests = []
    for seed in range(4):
        hit, s = _listener(k75, seed), abx.Staircase()
        for _ in range(300):
            s.update(hit(s.k))
        ests.append(s.jnd_k())
    est = float(2 ** np.mean(np.log2(ests)))
    assert k75 / 1.4 < est < k75 * 1.4, (k75, ests)


def test_a_guessing_listener_is_not_called_a_discriminator():
    rng = np.random.default_rng([4, 1])
    hits = int(sum(rng.random(14) < 0.5))
    assert abx.binomial_p(hits, 14) > 0.05


# --- ABX sessions through the app ----------------------------------------------------------


@pytest.fixture()
def coloured(tmp_path, monkeypatch):
    """The pool's candidates plus a sandbox swap matched with the coloured fake, as in
    test_ab's `prepared`."""
    fake = Coloured()
    clips = {"one.wav": _program(3.0, 1), "two.wav": _program(3.0, 2)}
    monkeypatch.setattr(stimuli, "_clip", lambda name: clips[name])
    monkeypatch.setattr(stimuli, "unit_overrides", lambda c: dict(c.genome))
    monkeypatch.setattr(prepare, "REPORT", tmp_path / "matching.json")
    db = store.connect(tmp_path / "j.sqlite")
    pool = candidates.load_pool()
    swap = candidates.swap(pool.candidates["nominal"], "passive_seed", 1, "seed1")
    prepare.prepare(pool, candidates=["nominal", "t101_permalloy"], extra=[swap],
                    clips=list(clips), targets=[3.0], db=db, render=fake,
                    render_audio=fake.audio.get, screen=lambda c: {"passes": True, "checks": {}},
                    log=lambda m: None)  # fmt: skip
    return db, fake


def _ab(db, fake):
    pytest.importorskip("fastapi")
    from varimu.listen import app as listen_app

    return listen_app, listen_app.AB(db=db, version=prepare.code_version(),
                                     render_audio=fake.audio.get)  # fmt: skip


def _run_abx(ab, listen_app, sid, correct_from_k=None):
    """Answer every trial: right when k >= correct_from_k (None: always wrong A)."""
    ks = []
    while True:
        n = ab.abx_next(sid)
        if n["done"]:
            return n["summary"], ks
        text = json.dumps(n)
        assert "candidate" not in text and "nominal" not in text  # blind
        clips = ab.abx_audio[n["trial_id"]]
        assert all(clips[s][:4] == b"RIFF" for s in "ABX")
        t = ab.db.execute("SELECT * FROM abx_trials WHERE id = ?", (n["trial_id"],)).fetchone()
        assert clips["X"] == clips[t["x_is"]]  # the same file (WAVs carry a write time)
        right = correct_from_k is not None and t["k"] >= correct_from_k
        said = t["x_is"] if right else ("B" if t["x_is"] == "A" else "A")
        req = listen_app.AbxAnswerRequest(
            trial_id=n["trial_id"], answer=said, response_ms=800.0, plays={"X": 2}
        )
        r = ab.abx_answer(req)
        assert r["correct"] == right
        ks.append(r["k"])


def test_an_abx_session_runs_end_to_end_apart_from_the_preference_data(coloured):
    db, fake = coloured
    listen_app, ab = _ab(db, fake)
    pairs = ab.pairs()
    assert len(pairs) == 2 * 3 and all(np.isfinite(p["residual_db"]) for p in pairs)
    start = ab.abx_start(listen_app.AbxSessionRequest(seed=21, trials_per_pair=6))
    sid = start["session"]
    assert start["planned"] == 6 * 6 + abx.ANCHOR_TRIALS
    summary, ks = _run_abx(ab, listen_app, sid, correct_from_k=2.0)
    assert summary["answered"] == start["planned"] == len(ks)
    # Stored as discrimination, never in the preference trials.
    assert db.execute("SELECT COUNT(*) FROM trials").fetchone()[0] == 0
    rows = db.execute("SELECT * FROM abx_trials WHERE session_id = ?", (sid,)).fetchall()
    assert len(rows) == len(ks)
    for r in rows:
        assert bool(r["exaggerated"]) == (r["k"] != 1.0)
        assert abs(np.diff(json.loads(r["lufs_after"]))[0]) <= prepare.LUFS_TOL
        assert r["presented_at"] and r["answered_at"] and r["x_is"] in "AB"
    # The anchor: the largest residual, at K_ANCHOR, spread through the session.
    anchor = next(p for p in summary["pairs"] if p["anchor"])
    assert anchor["residual_db"] == pytest.approx(max(p["residual_db"] for p in pairs))
    assert anchor["k_track"] == [abx.K_ANCHOR] * abx.ANCHOR_TRIALS and anchor["hits"] == 3
    # Each staircase walked down from K_START to where this listener starts missing.
    for p in summary["pairs"]:
        if not p["anchor"]:
            assert p["k_track"][0] == abx.K_START and min(p["k_track"]) < 2.0
            assert p["trials"] == 6 and 0 <= p["hits"] <= 6 and p["p"] is not None
    s = db.execute("SELECT * FROM abx_sessions WHERE id = ?", (sid,)).fetchone()
    assert s["ended_at"] and s["share_x_is_a"] == summary["share_x_is_a"]
    assert summary["share_x_is_a"] is not None and 0 <= summary["share_x_is_a"] <= 1


def test_abx_sessions_are_reproducible_from_the_seed(coloured):
    db, fake = coloured
    listen_app, ab = _ab(db, fake)
    tracks = []
    for _ in range(2):
        sid = ab.abx_start(listen_app.AbxSessionRequest(seed=5, trials_per_pair=4))["session"]
        _run_abx(ab, listen_app, sid, correct_from_k=3.0)
        tracks.append([tuple(r) for r in db.execute(
            "SELECT p.base, p.other, t.k, t.a_is_base, t.x_is FROM abx_trials t JOIN abx_pairs p "
            "ON p.id = t.pair_id WHERE t.session_id = ? ORDER BY t.idx", (sid,))])  # fmt: skip
    assert tracks[0] == tracks[1]


def test_fixed_mode_plays_the_real_pairs(coloured):
    db, fake = coloured
    listen_app, ab = _ab(db, fake)
    pairs = ab.pairs()[:2]
    req = listen_app.AbxSessionRequest(seed=8, mode="fixed", k=1.0, trials_per_pair=5,
                                       pairs=[(p["a"], p["b"]) for p in pairs])  # fmt: skip
    sid = ab.abx_start(req)["session"]
    summary, ks = _run_abx(ab, listen_app, sid, correct_from_k=None)
    real = [p for p in summary["pairs"] if not p["anchor"]]
    assert len(real) == 2 and all(p["k_track"] == [1.0] * 5 for p in real)
    assert all(p["hits"] == 0 and p["p"] == 1.0 and p["jnd_k"] is None for p in real)
    flags = db.execute("SELECT exaggerated, anchor FROM abx_trials WHERE session_id = ?",
                       (sid,)).fetchall()  # fmt: skip
    assert all(bool(f["exaggerated"]) == bool(f["anchor"]) for f in flags)
    with pytest.raises(ValueError):
        ab.abx_start(listen_app.AbxSessionRequest(mode="sideways"))


def test_difference_listening_and_abx_over_http(coloured):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    db, fake = coloured
    listen_app, ab = _ab(db, fake)
    client = TestClient(listen_app.create_app(workers=1, ab=ab))
    pairs = client.get("/api/ab/pairs").json()
    a, b = pairs[0]["a"], pairs[0]["b"]
    ex = client.get("/api/ab/explore", params={"a": a, "b": b}).json()
    urls = [s["audio"] for s in ex["streams"]] + [ex["residual"]["audio"]]
    assert len(urls) == 6
    assert all(client.get(u).content[:4] == b"RIFF" for u in urls)
    assert client.get("/api/ab/explore", params={"a": 999, "b": b}).status_code == 404
    sid = client.post("/api/ab/abx/session", json={"seed": 3, "trials_per_pair": 2}).json()[
        "session"
    ]
    n = client.get("/api/ab/abx/next", params={"session": sid}).json()
    for s in "ABX":
        assert client.get(n["audio"][s]).content[:4] == b"RIFF"
    r = client.post("/api/ab/abx/answer", json={"trial_id": n["trial_id"], "answer": "A",
                                                 "response_ms": 500.0}).json()  # fmt: skip
    assert r["progress"]["answered"] == 1 and "k" in r
    again = client.post("/api/ab/abx/answer", json={"trial_id": n["trial_id"], "answer": "B",
                                                     "response_ms": 1.0})  # fmt: skip
    assert again.status_code == 400
    assert client.get("/api/ab/abx/summary", params={"session": sid}).json()["answered"] == 1


# --- Preference sessions: fixed repeats, position bias -------------------------------------


def test_preference_sessions_get_a_fixed_number_of_repeats(tmp_path):
    db = store.connect(tmp_path / "j.sqlite")
    for c in ("c0", "c1", "c2"):
        store.put_candidate(db, c, c, {})
    from test_ab import _stims

    stims = []
    for s in _stims():  # 12 first-pass trials
        i = store.put_stimulus(db, {**s, "solved": True, "ac_threshold": 0.5, "gr_db": 3.0,
                                    "render_key": "k", "reference_key": "r",
                                    "overrides": {}}, "test", "v")  # fmt: skip
        stims.append({**s, "id": i})
    for seed in range(8):  # every seed, not by chance
        sid = session.start(db, stims, code_version="v", seed=seed)
        while (t := session.next_trial(db, sid)) is not None:
            store.presented(db, t["id"], [0, 0], [-23, -23])
            store.answer(db, t["id"], "A", 900.0, 1, 1)
        rows = db.execute("SELECT * FROM trials WHERE session_id = ?", (sid,)).fetchall()
        reps = [r for r in rows if r["repeat_of"] is not None]
        assert len(rows) == 12 + session.N_REPEATS and len(reps) == session.N_REPEATS
        idx = {r["id"]: r["idx"] for r in rows}
        assert all(idx[r["id"]] - idx[r["repeat_of"]] > session.REPEAT_GAP for r in reps)
        assert len({r["repeat_of"] for r in reps}) == session.N_REPEATS
        store.end_session(db, sid)
        s = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        assert s["repeats"] == session.N_REPEATS and s["share_a"] == 1.0  # always "A"
        assert session.progress(db, sid)["share_a"] == 1.0


def test_an_old_database_gains_the_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, seed INTEGER NOT NULL, listener TEXT NOT "
        "NULL DEFAULT '', code_version TEXT NOT NULL, started_at REAL NOT NULL, ended_at REAL);"
        "INSERT INTO sessions VALUES ('pilot', 1, '', 'v', 0, 1);"
    )
    old.commit()
    old.close()
    db = store.connect(path)
    s = db.execute("SELECT * FROM sessions").fetchone()
    assert s["id"] == "pilot" and s["repeats"] is None and s["share_a"] is None


def test_the_pool_plays_its_clips_only(tmp_path, monkeypatch):
    """`pool_clips` (config/listening.yaml): prepare matches only those clips in data/clips
    (a listed clip that is missing is left out, said so), and the page's AB, given the
    list, offers no stimulus of another clip."""
    import dataclasses

    fake = Coloured()
    clips = {"one.wav": _program(3.0, 1), "two.wav": _program(3.0, 2)}
    monkeypatch.setattr(stimuli, "_clip", lambda name: clips[name])
    monkeypatch.setattr(stimuli, "clip_names", lambda: sorted(clips))
    monkeypatch.setattr(stimuli, "unit_overrides", lambda c: dict(c.genome))
    monkeypatch.setattr(prepare, "REPORT", tmp_path / "matching.json")
    db = store.connect(tmp_path / "j.sqlite")
    pool = dataclasses.replace(candidates.load_pool(), pool_clips=("two.wav", "gone.wav"))
    said = []
    rep = prepare.prepare(pool, candidates=["nominal", "t101_permalloy"], targets=[3.0], db=db,
                          render=fake, render_audio=fake.audio.get, log=said.append,
                          screen=lambda c: {"passes": True, "checks": {}})  # fmt: skip
    assert {s["clip"] for s in rep["stimuli"]} == {"two.wav"}
    assert any("gone.wav" in m for m in said)
    ok = {"passes": True, "checks": {}}
    prepare.prepare(pool, candidates=["nominal", "t101_permalloy"], targets=[3.0], db=db,
                    clips=["one.wav"], render=fake, render_audio=fake.audio.get,
                    log=lambda m: None, screen=lambda c: ok)  # fmt: skip
    listen_app, _ = _ab(db, fake)
    ab = listen_app.AB(db=db, version=prepare.code_version(), render_audio=fake.audio.get,
                       clips=pool.pool_clips)  # fmt: skip
    assert {p["clip"] for p in ab.pairs()} == {"two.wav"} and ab.status()["stimuli"] == 2
    everything = listen_app.AB(db=db, version=prepare.code_version(), render_audio=fake.audio.get)
    assert everything.status()["stimuli"] == 4


def test_abx_and_explore_by_part(coloured):
    """A session exaggerating the character: every trial flagged exaggerated, even at
    k = 1 (H B' alone isn't a unit); the part is in the summary; the anchor is the pair
    with the most character. Explore takes the part too, and refuses an unknown one."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    db, fake = coloured
    listen_app, ab = _ab(db, fake)
    req = listen_app.AbxSessionRequest(seed=4, mode="fixed", k=1.0, trials_per_pair=2,
                                       part="character")  # fmt: skip
    sid = ab.abx_start(req)["session"]
    summary, _ = _run_abx(ab, listen_app, sid, correct_from_k=0.5)
    assert summary["part"] == "character"
    flags = db.execute("SELECT exaggerated FROM abx_trials WHERE session_id = ?", (sid,))
    assert all(f["exaggerated"] for f in flags)
    pairs = ab.pairs()
    anchor = next(p for p in summary["pairs"] if p["anchor"])
    assert anchor["residual_db"] == max(p["levels_db"]["character"] for p in pairs)
    with pytest.raises(ValueError):
        ab.abx_start(listen_app.AbxSessionRequest(part="colour"))
    client = TestClient(listen_app.create_app(workers=1, ab=ab))
    a, b = pairs[0]["a"], pairs[0]["b"]
    r = client.get("/api/ab/explore", params={"a": a, "b": b, "part": "tone"})
    assert r.status_code == 200 and r.json()["part"] == "tone"
    assert r.json()["residual"]["name"] == "T" and len(r.json()["streams"]) == 5
    bad = client.get("/api/ab/explore", params={"a": a, "b": b, "part": "colour"})
    assert bad.status_code == 400

"""Phase 5's matching verified by measurement on real renders (main plan Phase 5, "done
when"): two candidates of the pool, solved for 3 dB of average gain reduction on a
short program-like excerpt (seeded noise bursts, not the user's clips, which may be
missing), then loudness matched as a session plays them.

About 20 renders of 1.5 s (~3-5 min on this desktop, cached afterwards).
"""

import numpy as np
import pytest

pytest.importorskip("pyloudnorm")

from varimu.config import load_sim_settings  # noqa: E402
from varimu.listen import candidates, prepare, stimuli  # noqa: E402
from varimu.sim import fast, runner  # noqa: E402

pytestmark = pytest.mark.skipif(not fast.available(), reason="needs `uv sync --extra fast`")

TARGET_DB = 3.0


def program(seconds=1.5, seed=0) -> np.ndarray:
    """Bursts of band-limited noise at levels around the factory threshold, faded."""
    fs = load_sim_settings().sample_rate
    rng = np.random.default_rng([seed, 5150])
    n = int(seconds * fs)
    k = int(fs * 0.1)
    env = np.repeat(rng.uniform(0.1, 0.6, n // k + 1), k)[:n]
    noise = np.convolve(rng.standard_normal(n), np.ones(24) / 24, "same") * 4.0
    x = env * noise
    f = int(0.05 * fs)
    ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(f) + 0.5) / f)
    x[:f] *= ramp
    x[-f:] *= ramp[::-1]
    return x


@pytest.fixture(scope="module")
def matched():
    pool = candidates.load_pool()
    x = program()
    ex = stimuli.Excerpt("synthetic", 0.0, 1.5)
    out = {}
    for name in ("nominal", "t101_permalloy"):
        c = pool.candidates[name]
        out[name] = stimuli.match(c, ex, TARGET_DB, pool.time_constant, x=x)
    return out


def test_each_candidate_is_solved_to_the_target_gain_reduction(matched):
    fs = load_sim_settings().sample_rate
    for s in matched.values():
        assert s.solved, s
        out = runner.load_render(runner.RENDER_DIR / s.render_key).output
        ref = runner.load_render(runner.RENDER_DIR / s.reference_key).output
        gr = stimuli.average_gr_db(ref, out, fs)  # re-measured from the cached renders
        assert abs(gr - TARGET_DB) <= stimuli.GR_TOL_DB, (s.candidate, gr)
    # A different core material is a different unit: its threshold differs.
    assert matched["nominal"].render_key != matched["t101_permalloy"].render_key


def test_the_pair_plays_at_one_loudness(matched):
    fs = load_sim_settings().sample_rate
    a, b = (runner.load_render(runner.RENDER_DIR / s.render_key).output for s in matched.values())
    v = stimuli.verify_pair(a, b, fs)
    assert v["lufs_diff"] <= prepare.LUFS_TOL, v


def test_the_listening_aids_on_the_real_pair(matched):
    """Difference listening and exaggeration (varimu.listen.difference) on the matched
    renders: every stream at one loudness, the extrapolated unit's GR A's at k = 0 and
    B's at k = 1 (re-measured from the cached renders), a finite residual below A."""
    from varimu.listen import difference, matching

    fs = load_sim_settings().sample_rate
    s = list(matched.values())
    a, b, ra, rb = (runner.load_render(runner.RENDER_DIR / getattr(x, k)).output
                    for k in ("render_key", "reference_key") for x in s)  # fmt: skip
    res = difference.streams(a, b, ra, rb, fs)
    lufs = [matching.integrated_lufs(st["audio"], fs) for st in res["streams"]]
    assert max(lufs) - min(lufs) <= prepare.LUFS_TOL, lufs
    gr = {st["k"]: st["gr_db"] for st in res["streams"]}
    assert abs(gr[0.0] - TARGET_DB) <= stimuli.GR_TOL_DB and abs(gr[1.0] - TARGET_DB) <= 0.1
    assert -80 < res["residual"]["level_db"] < 0, res["residual"]
    for st in res["streams"]:
        print(st["name"], st["gr_db"], st["envelope"], st["artifacts"])
    print("residual", res["residual"]["level_db"], "dB re A")
    v = difference.exaggerated_pair(a, b, ra, rb, 4.0, fs)
    assert abs(v["lufs_after"][0] - v["lufs_after"][1]) <= prepare.LUFS_TOL, v["lufs_after"]

"""The fast engine's Python side: build freshness, engine settings, the default engine
(and what happens without it), progress and thread priority in the runner."""

import dataclasses

import pytest

from varimu.config import load_sim_settings
from varimu.sim import fast
from varimu.sim.io import TransientSettings


def test_installed_build_matches_the_crate_sources():
    """circuitsim embeds a hash of its sources (crates/circuitsim/build.rs); the
    Python computation of the same hash must agree, or renders would be cached
    under sources the binary wasn't built from. A failure here usually means
    the build is stale: `uv sync --extra fast` (name every extra you use)."""
    circuitsim = pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    assert circuitsim.SOURCE_HASH == fast.source_hash()
    assert fast.check_build() == circuitsim.SOURCE_HASH


def test_engine_settings():
    ng = TransientSettings.from_sim_settings()
    assert ng.engine == "ngspice"
    cs = TransientSettings.from_sim_settings(engine="circuitsim")
    block = load_sim_settings().data["circuitsim"]
    assert (cs.engine, cs.oversample, cs.method, cs.input_order) == (
        "circuitsim",
        block["oversample"],
        block["method"],
        block["input_order"],
    )
    assert (cs.error_abstol, cs.error_reltol) == (block["error_abstol"], block["error_reltol"])
    assert (cs.solver, cs.newton_reltol, cs.newton_vntol, cs.newton_reuse) == (
        block["solver"],
        block["newton_reltol"],
        block["newton_vntol"],
        block["newton_reuse"],
    )
    # Everything else is shared with ngspice's settings.
    assert cs.sample_rate == ng.sample_rate
    assert cs.full_scale_volts_peak == ng.full_scale_volts_peak
    configured = TransientSettings.from_sim_settings(engine="configured")
    assert configured.engine == load_sim_settings().data["simulator"]["engine"]
    with pytest.raises(ValueError, match="unknown engine"):
        TransientSettings.from_sim_settings(engine="spectre")


def test_engine_is_part_of_the_cache_key():
    from varimu.circuit import netlist as nl
    from varimu.sim import runner

    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    c = nl.build({})
    x = [0.0] * 10
    ng = TransientSettings.from_sim_settings()
    cs = TransientSettings.from_sim_settings(engine="circuitsim")
    k_ng, parts_ng = runner._key(c, x, ng)
    k_cs, parts_cs = runner._key(c, x, cs)
    assert k_ng != k_cs
    assert "engine_build" in parts_cs and "engine_build" not in parts_ng
    assert runner._key(c, x, dataclasses.replace(cs, error_abstol=0.0))[0] != k_cs


def test_renders_default_to_circuitsim():
    """Circuit-sim plan M6: renders, the CLI and the listen app use the fast engine;
    ngspice stays available by name for verification."""
    assert TransientSettings.from_sim_settings(engine="configured").engine == "circuitsim"


@pytest.fixture
def no_circuitsim(monkeypatch):
    """As if the `fast` extra weren't installed."""
    import sys

    monkeypatch.setitem(sys.modules, "circuitsim", None)  # import raises ImportError
    fast.check_build.cache_clear()
    yield
    fast.check_build.cache_clear()


def test_without_the_extra_renders_stop_with_instructions(no_circuitsim, tmp_path, monkeypatch):
    """No silent fallback to ngspice: the error says how to install the engine or
    choose ngspice, and the CLI exits with that message before any work."""
    from varimu.cli import main
    from varimu.sim import runner

    assert not fast.available()
    monkeypatch.setattr(runner, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(runner, "JOB_DIR", tmp_path / "jobs")
    with pytest.raises(fast.EngineUnavailable, match=r"uv sync --extra fast.*--engine ngspice"):
        runner.render(runner.RenderJob([0.0] * 10))
    with pytest.raises(SystemExit, match="--engine ngspice"):
        main(["render", "--signal", "steps_1000hz", "--seconds", "0.01", "--out", str(tmp_path)])
    assert not (tmp_path / "renders").exists()
    # ngspice settings don't touch circuitsim.
    from varimu.circuit import netlist as nl

    runner._key(nl.build({}), [0.0] * 10, TransientSettings.from_sim_settings())


def test_render_reports_progress_and_caches(tmp_path, monkeypatch):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    import numpy as np

    from varimu.sim import runner

    monkeypatch.setattr(runner, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(runner, "JOB_DIR", tmp_path / "jobs")
    x = 0.3 * np.sin(2 * np.pi * 1000 * np.arange(2000) / 96000)
    seen = []
    r = runner.render(runner.RenderJob(x), progress=seen.append)
    assert not r.cached and r.meta["settings"]["engine"] == "circuitsim"
    assert len(seen) > 100 and seen[-1] == 1.0 and np.all(np.diff(seen) > 0)
    again = runner.render(runner.RenderJob(x))
    assert again.cached and again.key == r.key
    np.testing.assert_allclose(again.output, r.output, rtol=1e-6, atol=1e-7)  # stored as f4


def test_the_identical_job_on_two_threads_at_once(tmp_path, monkeypatch):
    """Two threads rendering the same job (same cache key) at the same time: each
    writes its own temporary directory (they once shared `<key>.tmp`: WinError 32),
    both get the result, one cache entry is left and no temporary ones."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    import threading

    import numpy as np

    from varimu.sim import runner

    monkeypatch.setattr(runner, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(runner, "JOB_DIR", tmp_path / "jobs")
    x = 0.3 * np.sin(2 * np.pi * 1000 * np.arange(1000) / 96000)
    gate = threading.Barrier(2)
    got, errors = [], []

    def one():
        gate.wait()
        try:
            got.append(runner.render(runner.RenderJob(x)))
        except Exception as e:  # noqa: BLE001 (reported below)
            errors.append(e)

    threads = [threading.Thread(target=one) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(got) == 2 and got[0].key == got[1].key
    np.testing.assert_array_equal(got[0].output, got[1].output)
    left = sorted(p.name for p in (tmp_path / "renders").iterdir() if p.is_dir())
    assert left == [got[0].key]
    assert not list((tmp_path / "jobs").iterdir())
    assert runner.render(runner.RenderJob(x)).cached


def test_thread_priority_is_lowered_and_restored():
    import sys

    with pytest.raises(ValueError, match="unknown priority"):
        with fast.thread_priority("realtime"):
            pass
    with fast.thread_priority("normal"):
        pass
    if sys.platform != "win32":
        return
    k32 = fast._kernel32()
    me = k32.GetCurrentThread()
    before = k32.GetThreadPriority(me)
    with fast.thread_priority("below_normal"):
        assert k32.GetThreadPriority(me) == -2
    with fast.thread_priority("idle"):
        assert k32.GetThreadPriority(me) == -15
    assert k32.GetThreadPriority(me) == before


def test_draft_quality_settings(monkeypatch):
    """The draft (circuit-sim plan M8): the `circuitsim` block with `circuitsim_draft` on
    top, chosen by name or, for configured renders, by $VARIMU_QUALITY (the CLI's
    --quality); circuitsim only; a cache key of its own."""
    from varimu.circuit import netlist as nl
    from varimu.config import SimSettings
    from varimu.sim import io, runner

    monkeypatch.delenv(io.QUALITY_ENV, raising=False)
    prod = TransientSettings.from_sim_settings(engine="circuitsim")
    draft = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    block = load_sim_settings().data["circuitsim_draft"]
    assert (prod.quality, draft.quality) == ("production", "draft")
    for k, v in block.items():
        assert getattr(draft, k) == (tuple(v) if k == "partition" else v), k
    assert draft.sample_rate == prod.sample_rate and draft.settle_s == prod.settle_s
    assert TransientSettings.from_sim_settings(engine="configured").quality == "production"
    monkeypatch.setenv(io.QUALITY_ENV, "draft")
    assert TransientSettings.from_sim_settings(engine="configured") == draft
    # Callers that name an engine stay production.
    assert TransientSettings.from_sim_settings(engine="circuitsim") == prod
    monkeypatch.setenv(io.QUALITY_ENV, "fine")
    with pytest.raises(ValueError, match="VARIMU_QUALITY"):
        TransientSettings.from_sim_settings(engine="configured")
    with pytest.raises(ValueError, match="circuitsim"):
        TransientSettings.from_sim_settings(engine="ngspice", quality="draft")
    s = load_sim_settings()
    bad = SimSettings(s.sample_rate, s.seed, {**s.data, "circuitsim_draft": {**block, "x": 1}})
    with pytest.raises(ValueError, match="unknown keys"):
        TransientSettings.from_sim_settings(bad, engine="circuitsim", quality="draft")
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    c, x = nl.build({}), [0.0] * 10
    assert runner._key(c, x, draft)[0] != runner._key(c, x, prod)[0]


def test_draft_renders_the_670_partitioned(tmp_path, monkeypatch):
    """A draft render runs the 670's supplies on a second thread (the sections the
    circuit has: the EQP-1A only has a power supply) and lands near production."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    import numpy as np

    from varimu.circuit import builder, spec
    from varimu.sim import runner

    monkeypatch.setattr(runner, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(runner, "JOB_DIR", tmp_path / "jobs")
    draft = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    prod = TransientSettings.from_sim_settings(engine="circuitsim")
    job = runner.RenderJob(0.3 * np.sin(2 * np.pi * 1000 * np.arange(4800) / 96000))
    ir = runner.build_circuit(job, draft).ir
    assert fast.partition_sections(ir, draft) == list(draft.partition)
    eq = builder.build(spec.load_circuit(spec.circuit_path("pultec_eqp1a")), {}, cores="linear")
    assert fast.partition_sections(eq.ir, draft) == ["power supply"]
    assert fast.partition_sections(ir, prod) == []
    d, p = runner.render(job, settings=draft), runner.render(job, settings=prod)
    assert d.meta["settings"]["quality"] == "draft"
    e = d.output[480:] - p.output[480:]
    assert np.sqrt(np.mean(e**2)) < 10 ** (-40 / 20) * np.sqrt(np.mean(p.output[480:] ** 2))

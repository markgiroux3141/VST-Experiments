"""The fast engine's Python side: build freshness and engine settings."""

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

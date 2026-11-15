"""Hum from a stray mains field (varimu.devices.hum; 2026-11-14): the builder's option, chains,
scenes, and a render's lines."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import SineSource, Winding
from varimu.devices import hum as hum_mod
from varimu.rooms import scene


def _load(name: str) -> spec.CircuitSpec:
    return spec.load_circuit(spec.circuit_path(name))


@pytest.mark.parametrize("name", ["telefunken_v76", "rca_44bx", "shure_sm7", "u47_v76", "api_312"])
def test_off_is_the_circuit_without_the_block(name):
    c = _load(name)
    assert c.hum is not None
    bare = builder.build(dataclasses.replace(c, hum=None), {}).ir.to_json()
    assert builder.build(c, {}).ir.to_json() == bare
    assert builder.build(c, {}, hum=False).ir.to_json() == bare


def test_each_winding_gets_its_turns_worth():
    c = _load("telefunken_v76")
    ir = builder.build(c, {}, hum=1e-6).ir
    els = [e for s in ir.sections for e in s.elements]
    area = float(c.hum["pickups"]["T85"]["area_m2"]["value"])
    hz = 50.0
    for w in (e for e in els if isinstance(e, Winding) and e.name.startswith("LT85_")):
        srcs = [
            e for e in els if isinstance(e, SineSource) and e.name.startswith(f"VHUM_{w.name}_")
        ]
        assert [s.freq_hz for s in srcs] == [n * hz for n, _ in hum_mod.HARMONICS]
        for s_, (n, weight) in zip(srcs, hum_mod.HARMONICS, strict=True):
            want = math.sqrt(2) * w.turns * area * 2 * math.pi * n * hz * 1e-6 * weight
            assert s_.amplitude_v == pytest.approx(want, rel=1e-12)
        assert srcs[0].pos != w.a and srcs[-1].neg == w.a  # in series: a -> sources -> winding


def test_the_mains_wander_moves_the_hum_too():
    ir = builder.build(_load("telefunken_v76"), {}, hum=True, noise=7).ir
    assert ir.noise.mains_sources[0] == "VT90"
    assert any(n.startswith("VHUM_LT85_") for n in ir.noise.mains_sources)


def test_a_chain_has_both_stages_pickups_and_the_preamps_mains():
    c = _load("u47_v76")
    assert set(c.hum["pickups"]) == {"BV8_u47", "T85_v76"}
    assert "hz" not in c.hum  # the V76's mains block
    c = _load("sm7_n1073")
    assert set(c.hum["pickups"]) == {"MC_sm7", "T1_n1073"}
    assert c.hum["hz"]["value"] == 50.0  # the 1073's (UK), not the SM7's 60
    assert any(
        e.name.startswith("VHUM_LMC_SM7_le")
        for s in builder.build(c, {}, hum=True).ir.sections
        for e in s.elements
    )


def test_scene_mics_take_noise_and_hum():
    d = {
        "name": "t",
        "room": {
            "dims_m": [5, 4, 3],
            "materials": {
                "walls": "furnished_wall",
                "floor": "wood_floor",
                "ceiling": "gypsum_on_studs",
            },
        },
        "sources": [{"name": "A", "clip": "x.wav", "spl_db": 80, "position_m": [2, 2, 1]}],
        "mics": [
            {"name": "m1", "chain": "u47_v76", "position_m": [3, 2, 1], "noise": True, "hum": True},
            {"name": "m2", "chain": "u47_v76", "position_m": [3, 3, 1], "hum": 1e-6},
            {"name": "m3", "chain": "u47_v76", "position_m": [3, 1, 1]},
        ],
    }
    sc = scene.load_scene(d)
    assert [(m.noise, m.hum) for m in sc.mics] == [(True, True), (False, 1e-6), (False, False)]
    seeds = {scene.print_seed(0, m, s) for m in ("m1", "m2") for s in (None, "A")}
    assert len(seeds) == 4 and all(0 <= x < 2**64 for x in seeds)
    with pytest.raises(ValueError):
        scene.load_scene({**d, "mics": [{**d["mics"][0], "hum": "loud"}]})


def test_the_v76_hums_at_the_mains_and_its_odd_harmonics():
    """Silence through the V76 with hum on: lines at 50 / 150 / 250 Hz, linear in the field."""
    pytest.importorskip("circuitsim")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    c = _load("telefunken_v76")
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    n = int(0.5 * s.sample_rate)
    lines = {}
    for field in (1e-6, 1e-5):
        ir = builder.build(c, {"gain_db": 76}, hum=field).ir
        y = np.asarray(fast.run_transient(ir, np.zeros(n), settings=s).vectors["v(out)"])
        y = y[n // 5 :] - np.mean(y[n // 5 :])
        t = np.arange(len(y)) / s.sample_rate
        lines[field] = [
            abs(np.mean(y * np.exp(-2j * np.pi * f * t))) * 2 for f in (50.0, 150.0, 250.0)
        ]
    lo, hi = lines[1e-6], lines[1e-5]
    assert lo[0] > 10 * lo[1] > 0 and lo[1] > lo[2] > 0  # the fundamental leads
    assert 20 * math.log10(hi[0] / lo[0]) == pytest.approx(20.0, abs=0.3)  # linear in the field


# --- AC heaters (CHAINS_PLAN.md NH4) ---------------------------------------------------------


@pytest.mark.parametrize("name", ["telefunken_v76", "telefunken_v72", "emi_redd47", "u47_v76"])
def test_ac_heaters_hum_only_with_hum_on(name):
    """Each listed tube gets VHH_ (a sine at the mains, sqrt(2) imbalance v_rms / 2), RHH_ and
    CHH_ from its own node to its cathode, after its device element; nothing with hum off."""
    c = _load(name)
    assert not [e for e in builder.build(c).ir.elements() if e.name.startswith("VHH_")]
    ir = builder.build(c, hum=True).ir
    els = list(ir.elements())
    heaters = c.hum["heaters"]
    assert len([e for e in els if e.name.startswith("VHH_")]) == len(heaters)
    q = spec.resolve(c)
    for dev, h in heaters.items():
        i = next(k for k, e in enumerate(els) if e.name == dev)
        src, r, cap = els[i + 1 : i + 4]
        k = els[i].nodes[-1]
        assert isinstance(src, SineSource) and src.name == f"VHH_{dev}"
        assert src.freq_hz == 50.0 and src.phase_deg == 0.0
        want = math.sqrt(2) * q[h["imbalance"]] * q[h["v_rms"]] / 2
        assert src.amplitude_v == pytest.approx(want, rel=1e-15)
        assert (r.name, r.b, r.r_ohm) == (f"RHH_{dev}", k, q[h["r_hk_ohm"]])
        assert (cap.name, cap.b, cap.c_f) == (f"CHH_{dev}", k, q[h["c_hk_f"]])
    # With the noise on, the mains wander moves them as it does the mains.
    wander = builder.build(c, hum=True, noise=1).ir.noise.mains_sources
    assert {f"VHH_{d}" for d in heaters} <= set(wander)


def test_the_v76s_heater_hum_sits_under_its_noise():
    """Balanced heaters 2 % off null: the V76's 50 Hz line (the field at 0, the heaters alone)
    under its own noise at the output (measured 10.4 uV against 21.9 uV rms), as a unit that met
    its -120 dB acceptance (reports/chain_spike/)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    c = _load("telefunken_v76")
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    n = int(1.0 * st.sample_rate)
    ir = builder.build(c, hum=0.0).ir
    y = fast.run_transient(ir, np.zeros(n), settings=st).vectors["v(out)"]
    t = np.arange(n) / st.sample_rate
    line = 2 * abs(np.mean(y * np.exp(-2j * np.pi * 50.0 * t))) / math.sqrt(2)
    assert 5e-6 < line < 20e-6, f"{line * 1e6:.2f} uV rms"

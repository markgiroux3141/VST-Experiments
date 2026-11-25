"""Barkhausen avalanches in a core: varimu.devices.barkhausen (the reference) and circuitsim's
barkhausen.rs (the port) agree; the landscape's properties (docs/PART_NOISE_PLAN.md)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from varimu.circuit import ir as irm
from varimu.circuit import parts
from varimu.devices import barkhausen as bk
from varimu.devices.core import core_model

FS = 96000.0


def test_uniforms_are_open_and_reproducible():
    from varimu.devices import noise

    k = noise.key(1, "x", 3)
    u = bk.uniforms(k, 0, 1000)
    assert np.all((u > 0) & (u < 1))
    assert np.array_equal(u[5:9], bk.uniforms(k, 5, 4))


def test_mean_size_is_the_power_laws_mean():
    s = np.geomspace(1e-8, 1e-5, 200_001)
    p = s**-1.5
    numeric = np.trapezoid(s * p, s) / np.trapezoid(p, s)
    assert bk.mean_size(1e-8, 1e-5, 1.5) == pytest.approx(numeric, rel=1e-4)


def test_a_bin_is_its_own_whatever_the_order():
    w = 100 * 1e-5
    a = bk.make_bin(7, "VBK", -3, 1e-8, 1e-5, 1.5, w)
    b = bk.make_bin(7, "VBK", -3, 1e-8, 1e-5, 1.5, w)
    other = bk.make_bin(7, "VBK", 4, 1e-8, 1e-5, 1.5, w)
    assert np.array_equal(a.pos, b.pos) and np.array_equal(a.cum, b.cum)
    assert a.pos.size != other.pos.size or not np.array_equal(a.pos, other.pos)
    assert a.cum[-1] == pytest.approx(w, rel=1e-12)
    assert np.all(np.diff(a.pos) >= 0) and a.pos[0] >= 0 and a.pos[-1] <= w


def _rig(stress: float):
    """A winding (500 turns, 1 cm2) through 10 ohm from the input onto a mumetall core of 10
    cm path, and Barkhausen avalanches in it."""
    core = core_model("CORE_T", "mumetall", 0.1)
    els = [
        irm.Resistor("RS", "in", "w", 10.0),
        irm.Winding("LW", "w", "0", "core", 500.0, 1e-4),
        irm.Device("XCORE", "CORE_T", ("core", "0")),
        irm.Capacitor("CEDDY", "core", "0", 1e-9),
        *parts.barkhausen("BK", "core", core, stress, 3),
    ]
    ir = irm.CircuitIR(
        title="barkhausen rig",
        input_node="in",
        probes=(irm.VoltageProbe("core"), irm.VoltageProbe("bk_bk")),
        models=(core,),
        sections=(irm.Section("rig", tuple(els)),),
    )
    return ir, core


def _drive(n: int) -> np.ndarray:
    t = np.arange(n) / FS
    return 8.0 * np.minimum(t / 0.25, 1.0) * np.sin(2 * math.pi * 100.0 * t)


@pytest.mark.parametrize("stress", [100.0, 0.0])
def test_circuitsim_agrees_with_the_reference(stress):
    pytest.importorskip("circuitsim")
    from varimu.sim import fast, io

    ir, core = _rig(stress)
    n = int(0.3 * FS)
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        settle_s=0.0,
        partition=(),
    )
    assert st.sim_rate == FS
    v = fast.run_transient(ir, _drive(n), settings=st).vectors
    core_v, out = v["v(core)"], v["v(bk_bk)"]
    el = next(e for e in ir.elements() if isinstance(e, irm.Barkhausen))
    ref = bk.Barkhausen(core, el.name, el.seed, el.stress, el.out_v_per_a)
    want = np.array([ref.push(float(x), 1.0 / FS) for x in core_v])
    if stress == 0.0:
        assert not np.any(out)
        return
    # The medium senses after each step and drives its output at the next.
    scale = np.max(np.abs(want))
    assert scale > 0.0
    assert np.max(np.abs(out[1:] - want[:-1])) <= 1e-9 * scale
    # ... and it crackled: the jumps' current is a sizeable part of the core's own.
    assert np.max(np.abs(want)) * bk_gm() > 1e-7


def bk_gm() -> float:
    return parts.BARKHAUSEN_GM_S


def test_stress_rescales_the_same_sites():
    """A new STRESS keeps the sites (the same uniforms) and scales the jumps."""
    m = bk.Barkhausen(core_model("C", "mumetall", 0.1), "VBK", 1, 10.0, 1e6)
    a = m.deviation(0.01234)
    m.set_stress(100.0)
    b = m.deviation(0.01234)
    assert a != b
    m.set_stress(0.0)
    assert m.state is None and m.push(500.0, 1 / FS) == 0.0

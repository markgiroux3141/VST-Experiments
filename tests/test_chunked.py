"""Renders in pieces (TAPE_SPEED_PLAN.md P3, `fast.run_transient_chunked`): each piece starts
early at its place in the whole run (circuitsim's `origin_samples`), so where the circuit's
memory is shorter than the warm-up the pieces rebuild the continuous run, noise included."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from varimu.circuit.ir import (
    IR_VERSION,
    Capacitor,
    CircuitIR,
    NoiseCurrent,
    NoiseSpec,
    Resistor,
    Section,
    SineSource,
    VoltageProbe,
)
from varimu.sim.io import TransientSettings

K_B = 1.380649e-23


def _rc() -> CircuitIR:
    """The input and the mains (with its wander) into an RC (1 ms) with Johnson noise."""
    els = (
        Resistor("RIN", "in", "a", 1e3),
        SineSource("VM", "m", "0", 0.0, 1.0, 60.0, 90.0),
        Resistor("RM", "m", "a", 10e3),
        Resistor("R1", "a", "0", 10e3),
        NoiseCurrent("IN_R1", "a", "0", 4 * K_B * 300 / 10e3),
        Capacitor("C1", "a", "0", 1e-6),
    )
    ir = CircuitIR(
        version=IR_VERSION,
        title="rc",
        input_node="in",
        probes=(VoltageProbe("a"),),
        models=(),
        sections=(Section("all", els),),
        noise=NoiseSpec(seed=5, rate_hz=96_000.0, mains_rms=0.005, mains_sources=("VM",)),
    )
    ir.validate()
    return ir


def test_pieces_rebuild_the_continuous_run():
    from varimu.sim import fast

    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    st = dataclasses.replace(
        TransientSettings.from_sim_settings(engine="circuitsim"), settle_s=0.05
    )
    fs = st.sample_rate
    rng = np.random.default_rng(3)
    x = 0.3 * np.sin(2 * np.pi * 440 * np.arange(int(0.4 * fs)) / fs) + 0.05 * rng.standard_normal(
        int(0.4 * fs)
    )
    whole = fast.run_transient(_rc(), x, settings=st).vectors["v(a)"]
    pieces = fast.run_transient_chunked(
        _rc(), x, settings=st, chunk_s=0.1, warmup_s=0.03, fade_s=0.002, workers=3
    ).vectors["v(a)"]
    assert len(pieces) == len(whole)
    err = np.sqrt(np.mean((pieces - whole) ** 2)) / np.sqrt(np.mean(whole**2))
    assert err < 1e-6, err
    # Without the origin, the pieces' mains and noise would start over at every seam.
    alone = fast.run_transient(_rc(), x[int(0.1 * fs) - int(0.03 * fs) :], settings=st)
    tail = alone.vectors["v(a)"][int(0.03 * fs) : int(0.03 * fs) + int(0.1 * fs)]
    seg = whole[int(0.1 * fs) : int(0.2 * fs)]
    assert np.sqrt(np.mean((tail - seg) ** 2)) / np.sqrt(np.mean(seg**2)) > 1e-3


def test_pieces_carry_an_audio_control():
    """An audio control (the Ampex 300-4's in2..in4) through the pieces: each piece its
    stretch, faded in as the input is; the RC on it rebuilds the continuous run."""
    from varimu.circuit.ir import Control
    from varimu.sim import fast

    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    base = _rc()
    els = (
        Resistor("RC2", "c2", "b", 1e3),
        Resistor("RB", "b", "0", 10e3),
        Capacitor("CB", "b", "0", 1e-6),
    )
    ir = dataclasses.replace(
        base,
        probes=(VoltageProbe("a"), VoltageProbe("b")),
        sections=(*base.sections, Section("second", els)),
        controls=(Control("c2", "c2", audio=True),),
    )
    ir.validate()
    st = dataclasses.replace(
        TransientSettings.from_sim_settings(engine="circuitsim"), settle_s=0.05
    )
    fs = st.sample_rate
    t = np.arange(int(0.4 * fs)) / fs
    x = 0.3 * np.sin(2 * np.pi * 440 * t)
    c2 = 0.5 * np.sin(2 * np.pi * 1000 * t)
    whole = fast.run_transient(ir, x, settings=st, controls={"c2": c2}).vectors["v(b)"]
    pieces = fast.run_transient_chunked(
        ir,
        x,
        settings=st,
        chunk_s=0.1,
        warmup_s=0.03,
        fade_s=0.002,
        workers=3,
        controls={"c2": c2},
    ).vectors["v(b)"]
    assert np.abs(whole).max() > 0.01
    err = np.sqrt(np.mean((pieces - whole) ** 2)) / np.sqrt(np.mean(whole**2))
    assert err < 1e-6, err

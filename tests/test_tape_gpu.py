"""The tape's recording kernel on the GPU (docs/TAPE_SPEED_PLAN.md P5; crates/tapegpu): f32
on the GPU against the f64 CPU kernel, the reference and the default, through circuitsim's
bindings (the kernel, the stream, the literal stream). Skipped without a GPU."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from tests.test_tape_stream import FS, _literal, _small
from varimu.devices.tape_machine import stream_params


def _cs():
    try:
        import circuitsim
    except ImportError:
        pytest.skip("circuitsim isn't built (uv sync --extra fast)")
    if not hasattr(circuitsim, "tape_gpu"):
        pytest.skip("circuitsim is older than the GPU kernel")
    name, why = circuitsim.tape_gpu()
    if name is None:
        pytest.skip(why)
    return circuitsim


def _db(a, b) -> float:
    """The difference's rms re b's, dB."""
    return 20 * math.log10(np.sqrt(np.mean((a - b) ** 2)) / np.sqrt(np.mean(b**2)) + 1e-300)


@pytest.mark.parametrize("table_step", [0.0, 1 / 40])
def test_the_gpu_stream_is_the_cpu_streams_within_f32(table_step):
    cs = _cs()
    spec, tape, h, bias = _small()
    p = stream_params(spec, tape, bias)
    p["table_step"] = table_step
    cpu = np.asarray(cs.tape_stream_run(json.dumps(p), FS, h))
    gpu = np.asarray(cs.tape_stream_run(json.dumps(p), FS, h, gpu=True))
    assert np.abs(cpu).max() > 0
    d = _db(gpu, cpu)
    # f32 rounding (~1e-6 of Ms per cell): far below P5's -80 dB bound.
    assert d < -90, d
    # The GPU is deterministic: the same numbers twice.
    np.testing.assert_array_equal(
        np.asarray(cs.tape_stream_run(json.dumps(p), FS, h, gpu=True)), gpu
    )


def test_the_literal_gpu_stream_is_the_cpu_streams_within_f32():
    cs = _cs()
    m = 16
    spec, tape, hf, _, _, _ = _literal(m)
    p = stream_params(spec, tape, 0.0)
    p["bias_substeps"] = m
    cpu = np.asarray(cs.tape_stream_run(json.dumps(p), FS, hf, chunk=16 * m))
    gpu = np.asarray(cs.tape_stream_run(json.dumps(p), FS, hf, chunk=16 * m, gpu=True))
    d = _db(gpu, cpu)
    assert d < -90, d


def test_the_kernels_binding_takes_the_gpu():
    cs = _cs()
    oe = 1000.0 / (4.0 * math.pi)
    pre = (293.0 * oe, 0.33, 46.0 * oe, 2000.0 * oe, 256)
    head = (51e-6, 1.5e-3, 5.5e-3)
    heights = np.array([2e-6, 6e-6, 10e-6])
    speed, f_bias = 0.381, 99e3
    s_cells = 12.0 + np.arange(2000) * speed / (f_bias * 7.62)
    t = (s_cells[0] - 1e-3) / speed + np.arange(int(0.006 / speed * 2 * f_bias)) / (2 * f_bias)
    s_rec = t * speed
    hg = np.where(np.arange(len(t)) % 2 == 0, 1.0, -1.0) * 2.4e5 + 9e3 * np.sin(2e3 * np.pi * t)
    axes = np.array([[math.cos(f), math.sin(f), 0.25] for f in (-1.2, -0.4, 0.4, 1.2)]).ravel()
    zones = np.array([2.2e-4, 2.4e-4, 2.6e-4])
    args = (pre, head, heights, zones, s_rec, hg, s_cells, axes)
    cpu = cs.tape_record(*args, table_step=1 / 40)
    gpu = cs.tape_record(*args, table_step=1 / 40, gpu=True)
    assert np.abs(cpu[0]).max() > 0.01
    for c, g in zip(cpu, gpu, strict=True):
        assert np.abs(np.asarray(g) - np.asarray(c)).max() < 2e-5

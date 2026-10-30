"""Control inputs (the tube synth's S3): circuit nodes driven by their own samples beside
the audio input (CircuitIR.controls; a circuit file's `cv_inputs`). Python's IR and
circuitsim's read and write them alike, IRs without any are unchanged, and
`fast.run_transient(..., controls=...)` drives them, linear between samples."""

import dataclasses
import json

import numpy as np
import pytest

from varimu.circuit.ir import (
    Capacitor,
    CircuitIR,
    Control,
    IRError,
    Resistor,
    Section,
    VoltageProbe,
)
from varimu.preflight import check_ir
from varimu.sim import fast, io

FS = 96000


def rc_with_gate() -> CircuitIR:
    """The audio input into one RC, a control `gate` into another (1 ms each)."""
    return CircuitIR(
        title="controls",
        input_node="in",
        probes=(VoltageProbe("out"), VoltageProbe("a")),
        models=(),
        sections=(
            Section(
                "rc",
                (
                    Resistor("R1", "in", "a", 1e3),
                    Capacitor("C1", "a", "0", 1e-6),
                    Resistor("R2", "g", "out", 1e3),
                    Capacitor("C2", "out", "0", 1e-6),
                ),
            ),
        ),
        controls=(Control("gate", "g"),),
    )


def test_json_has_controls_after_the_input_node_and_round_trips():
    ir = rc_with_gate()
    d = json.loads(ir.to_json())
    assert list(d)[:4] == ["version", "title", "input_node", "controls"]
    assert CircuitIR.from_json(ir.to_json()) == ir
    plain = dataclasses.replace(ir, controls=())
    assert "controls" not in json.loads(plain.to_json())


def test_controls_are_checked():
    ir = rc_with_gate()
    with pytest.raises(IRError, match="not connected"):
        dataclasses.replace(ir, controls=(Control("gate", "nowhere"),))
    with pytest.raises(IRError, match="twice"):
        dataclasses.replace(ir, controls=(Control("gate", "g"), Control("gate", "out")))
    with pytest.raises(IRError, match="ground or the input"):
        dataclasses.replace(ir, controls=(Control("gate", "in"),))


def test_circuitsim_reads_and_writes_them_alike():
    circuitsim = pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    ir = rc_with_gate()
    assert CircuitIR.from_json(circuitsim.ir_roundtrip(ir.to_json())) == ir


def test_preflight_takes_a_control_as_a_source():
    assert check_ir(rc_with_gate()) == []


def test_run_transient_drives_a_gate():
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    ir = rc_with_gate()
    s = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim"), full_scale_volts_peak=1.0
    )
    n = 960
    gate = np.where(np.arange(n) < 96, 0.0, 1.0)
    out = fast.run_transient(ir, np.zeros(n), settings=s, controls={"gate": gate}).vectors
    y = out["v(out)"]
    t = (np.arange(n) - 96) / FS
    expect = np.where(t >= 0, 1 - np.exp(-t / 1e-3), 0.0)
    # The gate's step becomes a one-sample ramp at every rate (linear), so the RC's
    # response lags the ideal step's by half a sample at most.
    assert np.max(np.abs(y - expect)) < 0.02
    # (the outputs' band-limited decimation rings ~2e-5 ahead of the step)
    assert np.max(np.abs(y[:80])) < 1e-9 and np.max(np.abs(y[:96])) < 1e-4
    assert np.max(np.abs(out["v(a)"])) < 1e-9
    with pytest.raises(ValueError, match="control inputs"):
        fast.run_transient(ir, np.zeros(n), settings=s)

"""Audio control inputs inside a multi-rate part (circuitsim's partition.rs / stream.rs;
PERIOD_GEAR_BACKLOG.md PG1, MT5's prerequisite): the Ampex 300-4's four record sides run in
one multi-rate island from their inputs on, so tracks 2-4's inputs (audio controls) are read
there the way the stream's own input is read by a multi-rate part: the same samples and
interpolation, each of the part's steps a part of the sample's polynomial."""

from __future__ import annotations

import math

import numpy as np
import pytest

from varimu.circuit.ir import (
    IR_VERSION,
    Capacitor,
    CircuitIR,
    Control,
    Resistor,
    Section,
    VoltageProbe,
    VoltageSource,
)

FS = 96_000.0


def _rust():
    try:
        import circuitsim
    except ImportError:
        pytest.skip("circuitsim isn't built (uv sync --extra fast)")
    return circuitsim


def _island(drive: str) -> tuple:
    return (
        Resistor("RX", drive, "b", 1e3),
        Capacitor("CB", "b", "0", 2e-9),  # 80 kHz: the island's steps resolve it
        Resistor("RB", "b", "0", 4.7e3),
        # A partition shares a node: the front's stiff DC node, barely loading the RC.
        Resistor("RS", "d", "b", 1e9),
    )


def _ir(by_control: bool) -> CircuitIR:
    """An RC in a multi-rate island (4 steps per sample) driven by the stream's input, or
    by an audio control with the input elsewhere; a DC divider beside it."""
    front = (VoltageSource("VD", "d", "0", 1.0), Resistor("RD", "d", "0", 1e3))
    if by_control:
        front += (Resistor("RI", "in", "0", 1e3),)
    return CircuitIR(
        version=IR_VERSION,
        title="island",
        input_node="in",
        probes=(VoltageProbe("b"), VoltageProbe("d")),
        models=(),
        sections=(
            Section("front", front),
            Section("island", _island("c2" if by_control else "in"), substeps=4),
        ),
        controls=(Control("c2", "c2", audio=True),) if by_control else (),
    )


def _signal(n: int) -> np.ndarray:
    t = np.arange(n) / FS
    return 0.4 * np.sin(2 * math.pi * 7300 * t) + 0.2 * np.sin(2 * math.pi * 19100 * t + 1.0)


def test_an_audio_control_in_an_island_is_read_as_the_input():
    """The island's RC driven by an audio control equals it driven by the stream's input
    (the same samples, the input's 5th-order interpolation per step), within rounding."""
    cs = _rust()
    x = _signal(2000)
    kw = {"input_order": 5}
    want = np.asarray(cs.simulate(_ir(False).to_json(), x, 1 / FS, "esdirk4", **kw)["v(b)"])
    got = cs.simulate(_ir(True).to_json(), np.zeros_like(x), 1 / FS, "esdirk4", controls=[x], **kw)
    got = np.asarray(got["v(b)"])
    assert np.abs(want).max() > 0.1
    assert np.abs(got - want).max() < 1e-12


def test_a_stream_reads_an_islands_audio_control_in_chunks():
    """Through circuitsim's Stream (the app's live and print path) in uneven chunks: the
    same as one whole run."""
    cs = _rust()
    if not hasattr(cs, "Stream"):
        pytest.skip("circuitsim has no Stream")
    x = _signal(3000)
    whole = cs.simulate(
        _ir(True).to_json(), np.zeros_like(x), 1 / FS, "esdirk4", controls=[x], input_order=5
    )
    # Sample 0 at construction (the DC point), the rest fed as a render feeds them.
    st = cs.Stream(_ir(True).to_json(), 1 / FS, 0.0, "esdirk4", input_order=5, c0=[x[0]])
    got = []
    for a, b in ((1, 8), (8, 1500), (1500, 1501), (1501, 3000)):
        out = st.process(np.zeros(b - a), controls=[x[a:b]])
        got.append(np.asarray(out["v(b)"]))
    got.append(np.asarray(st.finish()["v(b)"]))
    got = np.concatenate(got)
    want = np.asarray(whole["v(b)"])[1:]
    assert len(got) == len(want)
    np.testing.assert_array_equal(got, want)


def test_a_plain_control_must_stay_in_the_first_part():
    cs = _rust()
    ir = _ir(True)
    import dataclasses

    plain = dataclasses.replace(ir, controls=(Control("c2", "c2"),))
    with pytest.raises((ValueError, RuntimeError), match="first partition"):
        cs.simulate(plain.to_json(), np.zeros(8), 1 / FS, "esdirk4", controls=[np.zeros(8)])

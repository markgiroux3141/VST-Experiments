"""Link-line cuts (METHODOLOGY_REVIEW.md W1): circuitsim's partitioned run against the
Python reference (varimu.line_cut), and the reference's one solve against circuitsim's."""

import math

import numpy as np
import pytest

from varimu import line_cut
from varimu.circuit.ir import (
    Capacitor,
    CircuitIR,
    Device,
    Inductor,
    Resistor,
    Section,
    VoltageProbe,
    VoltageSource,
)
from varimu.devices.diode import JunctionDiode

circuitsim = pytest.importorskip("circuitsim")

FS = 48000.0
DT = 1.0 / FS
DIODE = JunctionDiode("D1N", 1e-14, 1.0)


def ir(a, b, probes, models=()):
    return CircuitIR(
        "line cut test",
        "in",
        tuple(VoltageProbe(p) for p in probes),
        tuple(models),
        (Section("A", tuple(a)), Section("B", tuple(b))),
    )


def tones(n, amp):
    t = np.arange(n) * DT
    fade = np.clip(t / 0.002, 0, 1)
    return amp * fade * (np.sin(2 * math.pi * 220 * t) + 0.5 * np.sin(2 * math.pi * 3100 * t))


def rust(c: CircuitIR, x, partition=None):
    kw = {"partition": list(partition)} if partition else {}
    out = circuitsim.simulate(
        c.to_json(),
        x,
        DT,
        "trap",
        solver="dk",
        reltol=1e-12,
        vntol=1e-12,
        input_order=1,
        error_abstol=0.0,
        **kw,
    )
    return out


def shunt_rc():
    """A source through 1k into s (C to ground), B a 2k2 load and a diode clamp, a DC
    offset through the input (the line starts charged)."""
    a = [Resistor("R1", "in", "s", 1e3), Capacitor("C1", "s", "0", 0.5e-6)]
    b = [
        Resistor("R2", "s", "0", 2.2e3),
        Device("D1", DIODE.name, ("s", "k")),
        VoltageSource("VK", "k", "0", 0.8),
    ]
    return ir(a, b, ["s"], [DIODE])


def series_l():
    """A source through 100 ohm and L into b, B a 1k load, a diode to a 2 V clamp: DC flows
    through the cut inductor."""
    a = [Resistor("R1", "in", "a", 100.0), Inductor("L1", "a", "b", 50e-3)]
    b = [
        Resistor("R2", "b", "0", 1e3),
        Device("D1", DIODE.name, ("b", "k")),
        VoltageSource("VK", "k", "0", 2.0),
    ]
    return ir(a, b, ["a", "b"], [DIODE])


@pytest.mark.parametrize(
    ("make", "cut", "probe"),
    [(shunt_rc, "C1", "v(s)"), (series_l, "L1", "v(b)")],
)
def test_the_reference_and_circuitsim_agree(make, cut, probe):
    c = make()
    n = 2400
    x = tones(n, 3.0) + 1.0  # a DC offset: the cut starts with DC on it
    part = (f"cut:{cut}", "B")
    whole_py = line_cut.run(c, x, DT)
    whole_rs = rust(c, x)
    cut_py = line_cut.run(c, x, DT, part)
    cut_rs = rust(c, x, part)
    scale = np.max(np.abs(whole_py[probe]))
    # The reference's one solve is circuitsim's (both trapezoidal from the DC point).
    assert np.max(np.abs(whole_py[probe] - whole_rs[probe])) < 1e-8 * scale
    # The cut run is the reference's cut run.
    assert np.max(np.abs(cut_py[probe] - cut_rs[probe])) < 1e-8 * scale
    # And it is a different run from the one solve, close to it.
    d = np.max(np.abs(cut_rs[probe] - whole_rs[probe])) / scale
    assert 1e-6 < d < 0.2


def test_a_cut_starts_at_the_dc_point():
    """With a constant input the cut run stays at the whole circuit's DC point, inductor
    current and all."""
    for c, cut in ((series_l(), "L1"), (shunt_rc(), "C1")):
        x = np.full(200, 1.7)
        whole = rust(c, x)
        cut_rs = rust(c, x, (f"cut:{cut}", "B"))
        for k, v in whole.items():
            assert np.max(np.abs(cut_rs[k] - v[0])) < 1e-9 * (1 + abs(v[0])), k

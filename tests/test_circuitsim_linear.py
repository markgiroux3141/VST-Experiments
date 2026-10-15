"""The Rust engine's linear solver (circuit-sim plan, M2) against ngspice.

Both engines get the same upsampled input and the same decimation
(varimu.sim.io), so the remaining difference is the solvers'. ngspice runs as
a reference: tight reltol, a timepoint on every sample and 8 steps per sample
(io.run_transient's reference options). Without those, ngspice's own error
(timepoints straddling the input's sample kinks, then interpolation) is
-55 to -75 dB re signal and hides the comparison.

Measured 2026-10-14 (worst probe, re its AC swing, 30 ms of 100 Hz + 1 kHz +
10 kHz): the difference falls 12 dB per doubling of the oversampling, as the
fixed-step trapezoidal error should; DC points agree to 1e-8 or better.
"""

import dataclasses

import numpy as np
import pytest

from varimu.circuit import netlist as nl
from varimu.circuit import spice
from varimu.circuit.ir import (
    Capacitor,
    CircuitIR,
    Coupling,
    Inductor,
    Resistor,
    VoltageProbe,
)
from varimu.sim import ngspice

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
try:
    ngspice.find_ngspice()
except ngspice.SimulatorNotFound:
    pytest.skip("ngspice not available", allow_module_level=True)

from engine_compare import circuit, compare, signal  # noqa: E402

SMALL = {
    "rc": circuit([Resistor("R1", "in", "out", 1e3), Capacitor("C1", "out", "0", 100e-9)], ["out"]),
    "rlc": circuit(
        [
            Resistor("R1", "in", "a", 100.0),
            Inductor("L1", "a", "b", 10e-3),
            Capacitor("C1", "b", "0", 1e-6),
        ],
        ["a", "b"],
    ),
    # 1:2, k = 0.999, winding capacitance: leakage resonance ~180 kHz.
    "transformer": circuit(
        [
            Resistor("RS", "in", "p", 600.0),
            Inductor("L1", "p", "0", 1.0),
            Inductor("L2", "s", "0", 4.0),
            Coupling("K12", "L1", "L2", 0.999),
            Resistor("RL", "s", "0", 10e3),
            Capacitor("CS", "s", "0", 100e-12),
        ],
        ["p", "s"],
    ),
}


# Measured at k = 8: rc -99.5 dB, rlc -98.1 dB, transformer -72.0 dB. The
# transformer is worse because its 180 kHz leakage resonance is above the
# k = 2..4 Nyquist and trapezoidal integration warps it into the band
# (-48 dB at k = 2, the production rate; see docs/CIRCUIT_SIM_PLAN.md).
@pytest.mark.parametrize(("name", "bound_db"), [("rc", -95), ("rlc", -94), ("transformer", -68)])
def test_small_circuits_agree_and_converge_at_second_order(name, bound_db):
    x = signal()
    e4, dc4 = compare(SMALL[name], x, 4)
    e8, dc8 = compare(SMALL[name], x, 8)
    assert e8 < bound_db, f"k=8: {e8:.1f} dB"
    assert -14 < e8 - e4 < -10, f"k=4 {e4:.1f} dB -> k=8 {e8:.1f} dB (expect -12 dB)"
    assert max(dc4, dc8) < 1e-8


def _linear_670(drive: str) -> CircuitIR:
    """The 670 with tubes and diodes removed, driven at `drive`, probed at every node."""
    ir = nl.build().ir.without_devices()
    ir = dataclasses.replace(ir, input_node=drive)
    return dataclasses.replace(ir, probes=tuple(VoltageProbe(n) for n in ir.nodes()))


# The 670's transformers, tubes and diodes removed (M2's "done when"), driven
# at three points so all four transformers carry signal: the input (T101),
# the output (T102 backwards, T103 and the sidechain pads), and a 6973 plate
# (T104, all four windings). ngspice needs gear for the last one (trap ran
# > 300 s). The circuit has transformer resonances at 20-110 kHz with Q up to
# 7 (T101 secondary 35 kHz, T103 75 kHz, T104 110 kHz). Trapezoidal
# integration warps them, so the error near them is larger than for the small
# circuits. Measured on this 12 ms signal, worst probe, at k = 2 / 4 / 8:
#   in   -44.7 / -56.4 / -68.1 dB      out  -39.4 / -48.7 / -60.3 dB
#   pa3  -15.9 / -28.9 / -41.1 dB (gear reference; 12BH7 plate, 6973 grid network)
# and DC within 1e-9 of the circuit's largest voltage. k = 2 is the production
# oversampling: see docs/CIRCUIT_SIM_PLAN.md (M2) for what that means for M4.
@pytest.mark.parametrize(
    ("drive", "amp_v", "method", "bound_db"),
    [("in", 1.0, "trap", -65), ("out", 1.0, "trap", -57), ("pa3", 10.0, "gear", -38)],
)
def test_670_transformers_alone_agree_and_converge(drive, amp_v, method, bound_db):
    ir = _linear_670(drive)
    x = signal(dur_s=0.012, amp=amp_v)
    # DC is tested against .op below: the first decimated sample mixes in the
    # floating T104 secondary's roundoff (see compare()).
    e4, _ = compare(ir, x, 4, reltol=1e-4, method=method)
    e8, _ = compare(ir, x, 8, reltol=1e-4, method=method)
    assert e8 < bound_db, f"k=8: {e8:.1f} dB"
    assert -15 < e8 - e4 < -9, f"k=4 {e4:.1f} dB -> k=8 {e8:.1f} dB (expect -12 dB)"


@pytest.mark.parametrize("drive", ["in", "out", "pa3"])
def test_670_operating_point_matches_ngspice_op(drive):
    """Every node of the device-stripped 670 vs ngspice `.op` (measured: within 1.3e-9
    of the 240 V B+)."""
    import circuitsim

    ir = _linear_670(drive)
    text, _ = spice.emit(ir, triode_formulation="exact")
    save = [p.spice for p in ir.probes]
    ng = ngspice.run(
        text + f"Vin_dc {drive} 0 dc 0\n", "op", save, options="reltol=1e-9 vntol=1e-12"
    )
    rs = circuitsim.simulate(ir.to_json(), np.zeros(1), 1e-6)
    scale = max(abs(ng[n][0]) for n in save)
    worst = max(abs(rs[n][0] - ng[n][0]) for n in save)
    assert scale > 200  # B+ is in the circuit
    assert worst < 1e-8 * scale, f"{worst:.2e} V"


def test_without_devices_keeps_the_linear_network():
    ir = nl.build().ir
    lin = ir.without_devices()
    assert lin.models == () and not any(e.name.startswith(("X", "D")) for e in lin.elements())
    removed = {e.name for e in ir.elements()} - {e.name for e in lin.elements()}
    assert removed == {
        "XVA", "XVB", "XV105A", "XV105B", "XV106A", "XV106B", "XV107", "XV108",
        "DCR101", "DCR102", "DCR103", "DCR104",
    }  # fmt: skip
    assert dataclasses.replace(lin, title="x").nodes()  # still a valid IR

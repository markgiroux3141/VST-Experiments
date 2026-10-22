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
from varimu.measure import transformers as tx
from varimu.sim import ngspice

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
try:
    ngspice.find_ngspice()
except ngspice.SimulatorNotFound:
    pytest.skip("ngspice not available", allow_module_level=True)

from engine_compare import circuit, compare, compare_solvers, signal  # noqa: E402

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


@pytest.mark.parametrize("method", ["trap", "esdirk4"])
@pytest.mark.parametrize("name", list(SMALL))
def test_dk_matches_full_mna(name, method):
    """The DK solver against full MNA (M5): within one Newton tolerance everywhere."""
    worst = compare_solvers(SMALL[name], signal(), 2, method)
    assert worst < 1.0, f"{worst:.2f} x tolerance"


def _linear_670(drive: str) -> CircuitIR:
    """The 670 with tubes and diodes removed and its cores in their linear limit, driven
    at `drive`, probed at every node the SPICE text has (not the core nodes or the
    windings' inner nodes: it has the windings as coupled inductors,
    varimu.circuit.spice)."""
    ir = nl.build(cores="linear").ir.without_devices()
    ir = dataclasses.replace(ir, input_node=drive)
    nodes = [n for n in ir.nodes() if n in spice.spice_nodes(ir)]
    return dataclasses.replace(ir, probes=tuple(VoltageProbe(n) for n in nodes))


# The 670's transformers alone, each between the slice's own source and load
# impedances with the tubes as resistances (varimu.measure.transformers
# fixtures), cores in their linear limit: ngspice runs the windings as coupled
# inductors with k = 1 (varimu.circuit.spice). (Until Phase 2 this was the
# device-stripped 670 driven at three points; with the Phase 2 transformers
# ngspice stops on its floating T104 secondary within ~30 ns, every emission
# tried. The DK and .op checks below still use it.) Measured 2026-10-21, worst
# probe at k = 4 / 8 (trap, 12 ms of 100 Hz + 1 kHz + 10 kHz): T101 -50.6 / -62.0,
# T102 -58.9 / -70.9, T103 -48.2 / -59.8, T104 -56.4 / -68.5 dB.
@pytest.mark.parametrize(
    ("key", "bound_db"), [("t101", -58), ("t102", -67), ("t103", -56), ("t104", -65)]
)
def test_670_transformers_alone_agree_and_converge(key, bound_db):
    ir = tx.fixture(key, cores="linear").ir
    x = signal(dur_s=0.012, amp=1.0)
    e4, _ = compare(ir, x, 4, reltol=1e-4)
    e8, _ = compare(ir, x, 8, reltol=1e-4)
    print(key, f"k=4 {e4:.1f} dB, k=8 {e8:.1f} dB")
    assert e8 < bound_db, f"k=8: {e8:.1f} dB"
    assert -15 < e8 - e4 < -9, f"k=4 {e4:.1f} dB -> k=8 {e8:.1f} dB (expect -12 dB)"


# T104's secondary with the bridge diodes gone floats on its 1 GOhm leak, so its
# common mode carries roundoff far above the tolerance in either solver (measured
# 0.011 V apart driven at pa3; every other node within 0.07 tolerance).
FLOATING = ("v(ay)", "v(bk)", "v(T104_s_l)")


@pytest.mark.parametrize("drive", ["in", "out", "pa3"])
def test_670_transformers_alone_dk_matches_full_mna(drive):
    ir = _linear_670(drive)
    worst = compare_solvers(ir, signal(dur_s=0.006, amp=1.0), 2, "esdirk4", skip=FLOATING)
    assert worst < 1.0, f"{worst:.2f} x tolerance"


@pytest.mark.parametrize("drive", ["in", "out", "pa3"])
def test_670_operating_point_matches_ngspice_op(drive):
    """Every node of the device-stripped 670 vs ngspice `.op` (measured: within 1.3e-9
    of the 240 V B+)."""
    import circuitsim

    ir = _linear_670(drive)
    text, _ = spice.emit(ir, triode_formulation="exact", rshunt_ohm=None)
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
    ir = nl.build(cores="linear").ir
    lin = ir.without_devices()
    assert lin.models == () and not any(e.name.startswith(("X", "D")) for e in lin.elements())
    removed = {e.name for e in ir.elements()} - {e.name for e in lin.elements()}
    assert removed == {
        "XV101A", "XV102A", "XV103B", "XV104B", "XV101B", "XV102B", "XV103A", "XV104A",
        "XV105A", "XV105B", "XV106A", "XV106B", "XV107", "XV108",
        "DCR101", "DCR102", "DCR103", "DCR104",
        "XV301A", "XV301B", "XV302", "XV303", "DV304",
        "DGR301A", "DGR301B", "DGR301C", "DGR301D",
        "XV2_6386", "XV2_12BH7", "XV2_6973",
    }  # fmt: skip
    assert dataclasses.replace(lin, title="x").nodes()  # still a valid IR

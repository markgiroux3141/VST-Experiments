"""The Rust engine with devices (circuit-sim plan, M3) against ngspice.

Small nonlinear circuits, each driven hard enough to bring its nonlinearity
in (diodes clipping, grid current, push-pull crossover), compared like the
linear circuits (engine_compare.compare: ngspice as a reference, same input
and decimation). And the 670's DC operating point against ngspice's `.op`.

The circuits are test fixtures, not modelled hardware: component values are
round numbers, the tubes and diode are the project's device models
(config/devices/).
"""

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from varimu.circuit import netlist as nl
from varimu.circuit import spice
from varimu.circuit.ir import (
    Capacitor,
    Coupling,
    Device,
    Inductor,
    Resistor,
    Section,
    VoltageProbe,
    VoltageSource,
)
from varimu.devices.fixtures import device_fixtures_json
from varimu.devices.library import load_device
from varimu.sim import ngspice

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
try:
    ngspice.find_ngspice()
except ngspice.SimulatorNotFound:
    pytest.skip("ngspice not available", allow_module_level=True)

from engine_compare import circuit, compare, compare_solvers, signal  # noqa: E402

REPO = Path(__file__).parent.parent
DEVICE_FIXTURE = REPO / "crates/circuitsim/tests/fixtures/devices/devices.json"


def test_device_fixtures_are_current():
    """The Rust device tests read Python's model outputs (regenerate with
    scripts/export_circuit_fixtures.py)."""
    assert DEVICE_FIXTURE.read_text("utf-8") == device_fixtures_json()


# --- Small nonlinear circuits ----------------------------------------------------------


def diode_clipper():
    """Series 2.2k into antiparallel silicon diodes with 10 nF across: soft clipping."""
    d = load_device("SI_RECTIFIER")
    return circuit(
        [
            Resistor("R1", "in", "out", 2.2e3),
            Capacitor("C1", "out", "0", 10e-9),
            Device("D1", d.name, ("out", "0")),
            Device("D2", d.name, ("0", "out")),
        ],
        ["out"],
        [d],
    )


def triode_stage():
    """12AX7 common-cathode stage (100k plate load, bypassed 1.5k cathode, 1 MOhm grid
    leak, 470k load), driven through 10k so the peaks pull grid current."""
    t = load_device("12AX7")
    return circuit(
        [
            VoltageSource("VB", "bp", "0", 250.0),
            Resistor("RS", "in", "a", 10e3),
            Capacitor("CI", "a", "g", 100e-9),
            Resistor("RG", "g", "0", 1e6),
            Device("XV1", t.name, ("p", "g", "k")),
            Resistor("RP", "bp", "p", 100e3),
            Resistor("RK", "k", "0", 1.5e3),
            Capacitor("CK", "k", "0", 22e-6),
            Capacitor("CO", "p", "o", 100e-9),
            Resistor("RL", "o", "0", 470e3),
        ],
        ["g", "p", "k", "o"],
        [t],
    )


def push_pull():
    """12BH7 push-pull pair, transformer in and out.

    Input transformer 1:1+1 (k = 0.999) with the centre tap at -12 V bias;
    output transformer 2 x 5 H primary halves on a 250 V centre tap into a
    50 mH secondary (k = 0.995) loaded with 600 Ohm. Grid windings are damped
    with 47k so the leakage resonances stay below the comparison's error.
    """
    t = load_device("12BH7")
    els = [
        Resistor("RS", "in", "ip", 600.0),
        Inductor("LIP", "ip", "0", 1.0),
        Inductor("LGA", "ga", "ct", 1.0),
        Inductor("LGB", "ct", "gb", 1.0),
        Coupling("KI1", "LIP", "LGA", 0.999),
        Coupling("KI2", "LIP", "LGB", 0.999),
        Coupling("KI3", "LGA", "LGB", 0.999),
        Resistor("RDA", "ga", "ct", 47e3),
        Resistor("RDB", "gb", "ct", 47e3),
        VoltageSource("VBIAS", "ct", "0", -12.0),
        Device("XVA", t.name, ("pa", "ga", "k")),
        Device("XVB", t.name, ("pb", "gb", "k")),
        Resistor("RK", "k", "0", 47.0),
        VoltageSource("VB", "bp", "0", 250.0),
        Resistor("RWA", "pa", "pa_w", 50.0),
        Inductor("LPA", "pa_w", "bp", 5.0),
        Resistor("RWB", "pb", "pb_w", 50.0),
        Inductor("LPB", "bp", "pb_w", 5.0),
        Inductor("LS", "s", "0", 0.05),
        Coupling("KO1", "LPA", "LPB", 0.995),
        Coupling("KO2", "LPA", "LS", 0.995),
        Coupling("KO3", "LPB", "LS", 0.995),
        Resistor("RL", "s", "0", 600.0),
        Capacitor("CPA", "pa", "pb", 200e-12),
    ]
    return circuit(els, ["ga", "gb", "pa", "pb", "k", "s"], [t])


# name -> (circuit, input amplitude in V, bound at k = 8 in dB re signal). Measured
# 2026-10-14 (worst probe, 30 ms of 100 Hz + 1 kHz + 10 kHz), k = 2 / 4 / 8:
#   diode_clipper  -39.4 / -51.5 / -63.3 dB
#   triode_stage   -39.3 / -50.9 / -62.8 dB   (grid current on the peaks)
#   push_pull      -44.9 / -55.2 / -67.9 dB
# falling 12 dB per doubling: what's left is the fixed-step trapezoidal error
# (at k = 2 the 10 kHz tone's phase error, (wh)^2 / 12 ~ 0.9%), not Newton's.
# DC agrees to 1e-8 of the largest voltage or better.
SMALL = {
    "diode_clipper": (diode_clipper, 3.0, -60),
    "triode_stage": (triode_stage, 3.0, -60),
    "push_pull": (push_pull, 6.0, -64),
}


@pytest.mark.parametrize("name", list(SMALL))
def test_small_nonlinear_circuits_agree_and_converge_at_second_order(name):
    build, amp, bound_db = SMALL[name]
    x = signal(amp=amp)
    e4, dc4 = compare(build(), x, 4)
    e8, dc8 = compare(build(), x, 8)
    assert e8 < bound_db, f"k=8: {e8:.1f} dB"
    assert -15 < e8 - e4 < -9, f"k=4 {e4:.1f} dB -> k=8 {e8:.1f} dB (expect -12 dB)"
    assert max(dc4, dc8) < 1e-8


@pytest.mark.parametrize("method", ["trap", "esdirk4"])
@pytest.mark.parametrize("name", list(SMALL))
def test_dk_matches_full_mna(name, method):
    """The DK solver against full MNA at the production rate (k = 2), exact Newton:
    every probe at every sample within one Newton tolerance (M5's "done when";
    the 670 itself is checked node by node in crates/circuitsim/tests/dk.rs)."""
    build, amp, _ = SMALL[name]
    worst = compare_solvers(build(), signal(amp=amp), 2, method)
    assert worst < 1.0, f"{worst:.2f} x tolerance"


@pytest.mark.parametrize("name", list(SMALL))
def test_newton_is_cheap_on_audio(name):
    """At the production rate (k = 2) no step needs halving. Exact Newton takes about
    3 iterations per step (measured 2.9-3.4; the 670 takes 2.6 on a 1 kHz tone). With
    Jacobian reuse (the default) the iterations are cheaper and a few more, and the
    Newton matrix is refactored on a small fraction of the steps."""
    import circuitsim

    from varimu.sim.io import upsample

    build, amp, _ = SMALL[name]
    x = upsample(signal(amp=amp), 2)
    run = lambda reuse: circuitsim.simulate(  # noqa: E731
        build().to_json(), x, 1 / (2 * 96000), newton_reuse=reuse, stats=True
    )[1]
    st = run(False)
    assert st["halved_steps"] == 0 and st["dc_method"] == "newton", st
    assert st["iterations"] / st["steps"] < 4.0 and st["max_iterations"] <= 10, st
    st = run(True)
    assert st["halved_steps"] == 0, st
    assert st["factorizations"] / st["steps"] < 0.5, st


# --- The 670 operating point ----------------------------------------------------------

GOLDEN = json.loads((REPO / "tests/fixtures/netlist_golden/cases.json").read_text("utf-8"))


def _orderings(ir):
    """The same circuit with its unknowns in other orders (elements reversed, sections
    reversed), which changes the pivoting and so the roundoff."""
    yield ir
    yield dataclasses.replace(
        ir,
        sections=tuple(
            Section(s.title, tuple(reversed(s.elements))) for s in reversed(ir.sections)
        ),
    )
    yield dataclasses.replace(ir, sections=tuple(reversed(ir.sections)))


@pytest.mark.parametrize("case", ["default_exact", "mismatch_exact", "pots_min", "pots_max", "tc6"])
def test_670_operating_point_matches_ngspice_op(case):
    """Every node of the full nonlinear 670 against ngspice `.op` (exact triode
    formulation, reltol 1e-6, all digits).

    Each node must agree within 1e-10 of B+ or within 3x the engine's own
    roundoff spread across unknown orderings, whichever is larger. The spread
    matters on one island: at DC, T104's secondary (ay, bk, T104_s_l) is a
    1 mOhm winding whose common mode only the bridge diodes' leakage and a
    1 GOhm leak hold, so double precision resolves it to ~1e-6..1e-5 V in any
    engine (eps x 1000 S x 13 V / 6e-7 S), and the control-voltage nodes
    next to it inherit some of that. Measured 2026-10-14: every node within
    0.57x of the spread; ngspice's value lies inside Rust's spread; without
    the island (pots_min, where the bridge is reverse biased), every node
    within 5.7e-10 V (2e-12 of B+).

    Phase 2 (2026-10-21): T104's secondary has no winding resistance any more
    (the 1 mOhm placeholder went with the old transformer model), so Rust's
    spread there is 1e-11..2e-10 V; ngspice differs by up to 1.5e-7 V, inside its
    own convergence tolerance on the island (reltol 1e-6 of its 4-13 V), which
    bounds the island's nodes.
    """
    import circuitsim

    ir = nl.build(GOLDEN[case]["overrides"], cores="linear").ir
    # (the nodes the SPICE text has: not core nodes or the windings' inner nodes)
    ok = spice.spice_nodes(ir)
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(n) for n in ir.nodes() if n in ok))
    text, _ = spice.emit(ir, triode_formulation="exact", rshunt_ohm=None)
    save = [p.spice for p in ir.probes]
    ng = ngspice.run(
        text + f"Vin_dc {ir.input_node} 0 dc 0\n", "op", save, options="reltol=1e-6", digits=16
    )
    runs = [circuitsim.simulate(o.to_json(), np.zeros(1), 1e-6) for o in _orderings(ir)]
    b_plus = max(abs(ng[n][0]) for n in save)
    assert b_plus > 200
    for n in save:
        vals = [r[n][0] for r in runs]
        spread = max(vals) - min(vals)
        assert spread < 1e-7 * b_plus, f"{n}: roundoff spread {spread:.1e} V"
        diff = abs(vals[0] - ng[n][0])
        island = 1e-6 * abs(ng[n][0]) if n in ("v(ay)", "v(bk)") else 0.0
        assert diff <= 1e-10 * b_plus + 3 * spread + island, (
            f"{n}: Rust {vals[0]:.12f}, ngspice {ng[n][0]:.12f} (spread {spread:.1e})"
        )

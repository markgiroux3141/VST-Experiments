"""Circuit IR (varimu.circuit.ir): JSON round trips in Python and through Rust, validation."""

import dataclasses
import json
from pathlib import Path

import pytest

from varimu.circuit import netlist as nl
from varimu.circuit.ir import (
    IR_VERSION,
    CircuitIR,
    Coupling,
    Device,
    IRError,
    Resistor,
    Section,
    Winding,
)

REPO = Path(__file__).parent.parent
GOLDEN = json.loads((REPO / "tests/fixtures/netlist_golden/cases.json").read_text("utf-8"))
RUST_FIXTURES = REPO / "crates/circuitsim/tests/fixtures"
RUST_INDEX = json.loads((RUST_FIXTURES / "index.json").read_text("utf-8"))


def _ir(case: str) -> CircuitIR:
    c = GOLDEN[case]
    return nl.build(c["overrides"], triode_formulation=c["triode_formulation"]).ir


@pytest.fixture(scope="module")
def default_ir():
    return nl.build(triode_formulation="exact").ir


@pytest.mark.parametrize("case", sorted(GOLDEN))
def test_python_json_round_trip(case):
    ir = _ir(case)
    assert CircuitIR.from_json(ir.to_json()) == ir


@pytest.mark.parametrize("case", sorted(GOLDEN))
def test_rust_fixtures_are_current(case):
    """crates/circuitsim/tests/fixtures match today's IR (regenerate with
    scripts/export_circuit_fixtures.py)."""
    text = (RUST_FIXTURES / RUST_INDEX[case]).read_text("utf-8")
    assert text == _ir(case).to_json()


@pytest.mark.parametrize("case", sorted(GOLDEN))
def test_rust_round_trip(case):
    """Python -> JSON -> Rust (parse, validate) -> JSON -> Python gives the same IR."""
    circuitsim = pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    assert circuitsim.IR_VERSION == IR_VERSION
    ir = _ir(case)
    assert CircuitIR.from_json(circuitsim.ir_roundtrip(ir.to_json())) == ir


def test_rust_rejects_what_python_rejects(default_ir):
    circuitsim = pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    d = default_ir.to_dict()
    els = d["sections"][0]["elements"]
    els[1]["name"] = els[0]["name"]
    with pytest.raises(ValueError, match="duplicate element"):
        circuitsim.ir_roundtrip(json.dumps(d))
    with pytest.raises(IRError, match="duplicate element"):
        CircuitIR.from_dict(d)


def test_ir_is_the_circuit_the_netlist_describes(default_ir):
    assert default_ir.input_node == nl.INPUT_NODE
    assert tuple(p.spice for p in default_ir.probes) == nl.SAVE
    els = {e.name: e for e in default_ir.elements()}
    assert els["XV101A"] == Device("XV101A", "6386_V101A", ("pa", "ga", "ka"))
    assert els["LT101_sa"] == Winding("LT101_sa", "T101_sa_l", "cv", "t101_core", 4.5 * 1320, 1e-4)
    assert els["XT101_CORE"] == Device("XT101_CORE", "CORE_T101", ("t101_core", "0"))
    # Device models carry every parameter (Rust never reads the YAML).
    bank = default_ir.model("6386_V101A")
    assert len(bank.plate.mus) == len(bank.plate.weights) > 1


def test_json_numbers_are_floats(default_ir):
    """Rust writes f64 fields as floats; Python must too, or the JSON wouldn't round-trip."""

    def numbers(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k != "version":
                    yield from numbers(v)
        elif isinstance(x, list):
            for v in x:
                yield from numbers(v)
        elif isinstance(x, int | float) and not isinstance(x, bool):
            yield x

    assert all(isinstance(n, float) for n in numbers(json.loads(default_ir.to_json())))


def _with_extra(ir: CircuitIR, *els) -> CircuitIR:
    return dataclasses.replace(ir, sections=(*ir.sections, Section("extra", tuple(els))))


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (Resistor("R103", "a", "b", 1.0), "duplicate element"),
        (Resistor("r103", "a", "b", 1.0), "duplicate element"),  # SPICE ignores case
        (Resistor("Cx", "a", "b", 1.0), "must start with R"),
        (Resistor("Rx", "a", "b", -1.0), "> 0"),
        (Resistor("Rx", "a", "a", 1.0), "both ends"),
        (Resistor("Rx", "a", "b c", 1.0), "bad node name"),
        (Device("XVZ", "nope", ("a", "b", "c")), "unknown model"),
        (Device("XVZ", "6386_V101A", ("a", "b")), "pins"),
        (Device("DZ", "6386_V101A", ("a", "b", "c")), "must start with X"),
        (Coupling("Kx", "LT101_p", "R103", 0.5), "not an inductor"),
        (Coupling("Kx", "LT101_p", "LT101_sa", 1.5), "must be in"),
    ],
)
def test_validation(default_ir, extra, message):
    with pytest.raises(IRError, match=message):
        _with_extra(default_ir, extra)


def test_json_rejects_unknown_fields_and_versions(default_ir):
    d = default_ir.to_dict()
    d["sections"][0]["elements"][1]["tolerance"] = 0.01
    with pytest.raises(IRError, match="unknown fields"):
        CircuitIR.from_dict(d)
    d = default_ir.to_dict()
    d["version"] = IR_VERSION + 1
    with pytest.raises(IRError, match="version"):
        CircuitIR.from_dict(d)
    d = default_ir.to_dict()
    d["sections"][0]["elements"][0]["kind"] = "fuse"
    with pytest.raises(IRError, match="unknown kind"):
        CircuitIR.from_dict(d)


def test_a_capacitor_start_voltage_round_trips_and_is_absent_when_unset():
    """`Capacitor.v0_v` (a start state, held for the DC operating point) is written only
    when set, so IRs without it read and write as before."""
    from varimu.circuit.ir import Capacitor, CircuitIR, Resistor, Section, VoltageProbe

    def ir(v0):
        return CircuitIR(
            title="t",
            input_node="in",
            probes=(VoltageProbe("a"),),
            models=(),
            sections=(
                Section("s", (Resistor("R1", "in", "a", 1e3), Capacitor("C1", "a", "0", 1e-6, v0))),
            ),
        )

    plain, started = ir(None), ir(5.0)
    assert '"v0_v"' not in plain.to_json()
    assert '"v0_v": 5.0' in started.to_json()
    assert CircuitIR.from_json(plain.to_json()) == plain
    assert CircuitIR.from_json(started.to_json()) == started

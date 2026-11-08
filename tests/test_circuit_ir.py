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


def test_a_multirate_sections_decimation_and_ownership_round_trip():
    """`Section.decimate` and `Section.owns` (HYBRID_PHYSICS_PLAN.md H3a, M1) are written
    only when set, round-trip through Rust, and are refused outside a multi-rate section."""
    from varimu.circuit.ir import Capacitor, VoltageProbe

    def ir(substeps, decimate, owns):
        return CircuitIR(
            title="t",
            input_node="in",
            probes=(VoltageProbe("a"),),
            models=(),
            sections=(
                Section("slow", (Resistor("R2", "a", "0", 1e6),)),
                Section(
                    "island",
                    (Resistor("R1", "in", "a", 1e3), Capacitor("C1", "a", "0", 1e-6)),
                    substeps,
                    decimate,
                    owns,
                ),
            ),
        )

    plain, m1 = ir(8, None, None), ir(8, "fir", ("a",))
    assert '"decimate"' not in plain.to_json() and '"owns"' not in plain.to_json()
    assert CircuitIR.from_json(m1.to_json()) == m1
    circuitsim = pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    assert CircuitIR.from_json(circuitsim.ir_roundtrip(m1.to_json())) == m1
    for args, match in (
        ((None, "fir", None), "decimate"),
        ((8, "box", None), "decimate"),
        ((None, None, ("a",)), "owns"),
        ((8, None, ()), "owns"),
    ):
        with pytest.raises(IRError, match=match):  # the IR validates as it is made
            ir(*args).validate()
    # Rust: the same refusals, on JSON edited past Python's checks
    for edit, match in (
        ({"substeps": None}, "decimate"),
        ({"decimate": "box"}, "unknown variant"),
        ({"decimate": None, "substeps": None}, "owns"),
        ({"owns": []}, "owns"),
    ):
        d = m1.to_dict()
        d["sections"][1].update(edit)
        d["sections"][1] = {k: v for k, v in d["sections"][1].items() if v is not None}
        with pytest.raises(ValueError, match=match):
            circuitsim.ir_roundtrip(json.dumps(d))


def test_circuit_files_take_decimation_and_ownership(tmp_path):
    """A circuit file's section `decimate` / `owns`: built into the IR, and checked."""
    from varimu.circuit import builder, spec
    from varimu.config import CONFIG_DIR, ConfigError

    text = (CONFIG_DIR / "circuits" / "rca_884_sweep.yaml").read_text("utf-8")
    good = text.replace("  - title: oscillator\n", "  - title: oscillator\n    substeps: 8\n"
                        "    decimate: fir\n    owns: [out]\n")  # fmt: skip
    assert good != text
    path = tmp_path / "m1.yaml"
    path.write_text(good, "utf-8")
    s = spec.load_circuit(path)
    sec = builder.build_ir(s, spec.resolve(s)).sections[0]
    assert (sec.substeps, sec.decimate, sec.owns) == (8, "fir", ("out",))
    for bad in (
        text.replace("  - title: oscillator\n", "  - title: oscillator\n    decimate: fir\n"),
        good.replace("decimate: fir", "decimate: box"),
        good.replace("owns: [out]", "owns: []"),
    ):
        path.write_text(bad, "utf-8")
        with pytest.raises(ConfigError, match="decimate|owns"):
            spec.load_circuit(path)


def test_a_multirate_sections_lag_round_trips_and_is_checked():
    """`Section.lag_samples` (TAPE_SPEED_PLAN.md P2) is written only when set, round-trips
    through Rust, and is refused outside a multi-rate section that owns nothing and doesn't
    decimate, in both languages."""
    from varimu.circuit.ir import Capacitor, VoltageProbe

    def ir(substeps, lag, decimate=None):
        return CircuitIR(
            title="t",
            input_node="in",
            probes=(VoltageProbe("a"),),
            models=(),
            sections=(
                Section("slow", (Resistor("R2", "a", "0", 1e6),)),
                Section(
                    "fast",
                    (Resistor("R1", "in", "a", 1e3), Capacitor("C1", "a", "0", 1e-6)),
                    substeps,
                    decimate,
                    None,
                    lag,
                ),
            ),
        )

    plain, lagged = ir(8, None), ir(8, 64)
    assert '"lag_samples"' not in plain.to_json()
    assert CircuitIR.from_json(lagged.to_json()) == lagged
    for args in ((None, 64), (8, 0), (8, 64, "fir")):
        with pytest.raises(IRError, match="lag_samples"):
            ir(*args).validate()
    circuitsim = pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    assert CircuitIR.from_json(circuitsim.ir_roundtrip(lagged.to_json())) == lagged
    d = lagged.to_dict()
    del d["sections"][1]["substeps"]
    with pytest.raises(ValueError, match="lag_samples"):
        circuitsim.ir_roundtrip(json.dumps(d))


def test_a_multirate_sections_method_and_tables_round_trip_and_are_checked():
    """`Section.method` / `tube_tables` (TAPE_SPEED_PLAN.md P4) are written only when set,
    round-trip through Rust, are refused outside a multi-rate section (or with an unknown
    method) in both languages and both circuit-file parsers' Python one, and the builder
    carries them from a circuit file."""
    from varimu.circuit import builder, spec
    from varimu.circuit.ir import Capacitor, VoltageProbe

    def ir(substeps, method=None, tables=None):
        fast = Section(
            "fast",
            (Resistor("R1", "in", "a", 1e3), Capacitor("C1", "a", "0", 1e-6)),
            substeps,
        )
        fast = dataclasses.replace(fast, method=method, tube_tables=tables)
        return CircuitIR(
            title="t",
            input_node="in",
            probes=(VoltageProbe("a"),),
            models=(),
            sections=(Section("slow", (Resistor("R2", "a", "0", 1e6),)), fast),
        )

    plain, own = ir(8), ir(8, "trbdf2", True)
    assert '"method"' not in plain.to_json() and '"tube_tables"' not in plain.to_json()
    assert CircuitIR.from_json(own.to_json()) == own
    for args in ((None, "trbdf2"), (None, None, True), (8, "rk4")):
        with pytest.raises(IRError, match="method|tube_tables"):
            ir(*args).validate()
    circuitsim = pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    assert CircuitIR.from_json(circuitsim.ir_roundtrip(own.to_json())) == own
    d = own.to_dict()
    del d["sections"][1]["substeps"]
    with pytest.raises(ValueError, match="method"):
        circuitsim.ir_roundtrip(json.dumps(d))
    # The circuit file: the 351's record side (trbdf2 with tables since P4).
    c = spec.load_circuit(spec.circuit_path("ampex_351"))
    built = builder.build_ir(c, spec.resolve(c))
    fast = [x for x in built.sections if x.substeps]
    assert fast and all((x.method, x.tube_tables) == ("trbdf2", True) for x in fast)
    assert all(x.method is None and x.tube_tables is None for x in built.sections if not x.substeps)

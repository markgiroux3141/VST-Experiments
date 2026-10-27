"""KiCad as the schematic editor (device builder B3): the symbol library, the importer,
the exporter and the pre-flight checks.

The EQP-1A's generated KiCad project (kicad/generated/) and its netlist
(tests/fixtures/kicad/) come from scripts/make_kicad_fixtures.py; tests that need
kicad-cli skip without it."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

from varimu.circuit import builder
from varimu.circuit.builder import MACROS
from varimu.circuit.ir import PINS
from varimu.circuit.spec import circuit_path, load_circuit, resolve
from varimu.cli import main
from varimu.config import REPO_ROOT, ConfigError
from varimu.devices.pentode import Pentode
from varimu.devices.triode import Triode
from varimu.kicad import netlist as kn
from varimu.kicad.compare import ir_differences
from varimu.kicad.export import export_circuit, export_spec
from varimu.kicad.importer import import_netlist, load_sidecar, to_yaml
from varimu.kicad.netlist import Component, Net, Netlist, Pin, read_netlist
from varimu.kicad.symbols import SYMBOLS, library_text
from varimu.kicad.values import format_eng, parse_eng
from varimu.preflight import check_circuit, switch_configs

KICAD = REPO_ROOT / "kicad"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "kicad"
GENERATED = KICAD / "generated"
LIB_URI = "${KIPRJMOD}/../../varimu.kicad_sym"


def _has_kicad() -> bool:
    try:
        kn.find_kicad_cli()
    except kn.KiCadUnavailable:
        return False
    return True


needs_kicad = pytest.mark.skipif(not _has_kicad(), reason="kicad-cli not installed")


def _imported(xml: Path, project: str, tmp_path: Path):
    imp = import_netlist(read_netlist(xml), load_sidecar(GENERATED / project /
                                                         f"{project}.params.yaml"))  # fmt: skip
    f = tmp_path / f"{project}.yaml"
    f.write_text(to_yaml(imp.data), encoding="utf-8")
    return imp, load_circuit(f)


def _same_ir(a, b, overrides, cores="linear") -> list[str]:
    return ir_differences(builder.build_ir(a, resolve(a, overrides), cores),
                          builder.build_ir(b, resolve(b, overrides), cores))  # fmt: skip


# --- Engineering numbers --------------------------------------------------------------------


def test_engineering_numbers_read_exactly():
    assert parse_eng("40u") == 40.0e-6 and parse_eng("8.2n") == 8.2e-9
    assert parse_eng("4k7") == 4700.0 and parse_eng("4R7") == 4.7
    assert parse_eng("40uF") == 40.0e-6 and parse_eng("1.0e+9") == 1.0e9
    assert parse_eng("470") == 470 and isinstance(parse_eng("470"), int)
    assert isinstance(parse_eng("470.0"), float) and isinstance(parse_eng("1k"), float)
    assert parse_eng("r_psu1_ohm") is None and parse_eng("1meg") is None
    rng = random.Random(3)
    for _ in range(20000):
        x = rng.uniform(-1, 1) * 10 ** rng.uniform(-14, 11)
        assert parse_eng(format_eng(x)) == x
    for x in (0.5e-4, 117.0, 2554, 600, 0.0, 1e-15):
        y = parse_eng(format_eng(x))
        assert y == x and type(y) is type(x)


# --- The library -------------------------------------------------------------------------------


def test_library_symbols_match_the_macros():
    device_keys = {"emission", "mu", "grid_contact_v", "parallel", "area", "instance", "name"}
    for s in SYMBOLS.values():
        numbers = [p.number for p in s.pins]
        assert len(numbers) == len(set(numbers)), s.name
        lower = {f for f in s.fields if f[0].islower()}
        if s.kind == "macro":
            m = MACROS[s.macro]
            extra = 1 if s.macro == "vr_tube" else 0  # its inner node is the Mid field
            assert len(s.order) + extra == m.n_nodes, s.name
            assert s.primary is None or s.primary in m.params, s.name
            assert lower <= set(m.params) | device_keys | {"device"}, (s.name, lower)
        if s.kind == "device":
            assert lower <= device_keys
            for unit in s.units:
                roles = tuple(p.name for p in unit)
                assert roles in (PINS[Triode], PINS[Pentode], ("a", "k")), (s.name, roles)
    assert {s.macro for s in SYMBOLS.values() if s.macro} == set(MACROS) - {
        "device",
        "switch",
        "transformer",
    }


def test_library_file_is_current():
    lib = (KICAD / "varimu.kicad_sym").read_text(encoding="utf-8")
    assert lib.replace("\r\n", "\n") == library_text(), "run scripts/make_kicad_fixtures.py"


def test_generated_projects_are_current(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from make_kicad_fixtures import broken

    spec = load_circuit(circuit_path("pultec_eqp1a"))
    for project, s in (("pultec_eqp1a", spec), ("pultec_eqp1a_broken", broken(spec))):
        for f in export_spec(s, tmp_path / project, project, LIB_URI):
            committed = GENERATED / project / f.name
            assert committed.read_text(encoding="utf-8").replace("\r\n", "\n") == f.read_text(
                encoding="utf-8"
            ), f"{committed} is stale: run scripts/make_kicad_fixtures.py"


# --- The EQP-1A drawn in KiCad -----------------------------------------------------------------


def test_eqp1a_imports_to_the_same_ir(tmp_path):
    """B3's done-when: the drawing imports to a file that builds the same IR as the
    hand-written one (up to element order: see varimu.kicad.compare), at every switch
    combination, with both core models, at the pots' ends and with drawn tolerances."""
    imp, b = _imported(FIXTURES / "pultec_eqp1a.xml", "pultec_eqp1a", tmp_path)
    a = load_circuit(circuit_path("pultec_eqp1a"))
    assert imp.problems == []
    configs = switch_configs(a)
    assert len(configs) == 84
    for cfg in configs:
        assert _same_ir(a, b, cfg) == [], cfg
    knobs = ("lf_boost", "lf_atten", "hf_boost", "bandwidth", "hf_atten")
    for ov in ({}, {k: 1.0 for k in knobs}, {k: 0.0 for k in knobs},
               {"passive_spread": 1.0, "passive_seed": 7, "hf_boost": 0.3}):  # fmt: skip
        for cores in ("ja", "linear"):
            assert _same_ir(a, b, ov, cores) == [], (ov, cores)
    # Values drawn on the parts come back as the same parameters, with their sources.
    assert a.values == b.values
    assert a.devices == b.devices

    def unordered(tol):  # the classes' parts are in reference order after an import
        return {**tol, "classes": {c: sorted(ds) for c, ds in tol["classes"].items()}}

    assert unordered(a.parts) == unordered(b.parts)
    assert check_circuit(b) == []


def test_broken_drawing_is_caught(tmp_path):
    """The checks catch each of the broken drawing's four faults
    (scripts/make_kicad_fixtures.py)."""
    imp, spec = _imported(FIXTURES / "pultec_eqp1a_broken.xml", "pultec_eqp1a_broken", tmp_path)
    assert imp.problems == ["unconnected: pin 2 of RBIAS_B"]
    found = {(p.check, p.message) for p in check_circuit(spec)}
    assert found == {
        ("unconnected", "node n_RBIAS_B_2 has only RBIAS_B on it"),
        ("floating", "no DC path to ground from g2a"),
        ("loop", "LPCCA closes a loop of sources, inductors and windings with no resistance"),
        ("rectifier", "node rka (XV3A) is fed by an inductance and has no capacitor on it"),
    }


@needs_kicad
def test_fresh_netlist_imports_the_same(tmp_path):
    """kicad-cli's netlist of the committed project imports as the fixture does."""
    xml = kn.export_netlist(GENERATED / "pultec_eqp1a" / "pultec_eqp1a.kicad_sch",
                            tmp_path / "n.xml")  # fmt: skip
    side = load_sidecar(GENERATED / "pultec_eqp1a" / "pultec_eqp1a.params.yaml")
    assert (
        import_netlist(read_netlist(xml), side).data
        == import_netlist(read_netlist(FIXTURES / "pultec_eqp1a.xml"), side).data
    )


@needs_kicad
@pytest.mark.parametrize("name", ["fairchild_670", "triode_stage"])
def test_round_trip_through_kicad(name, tmp_path):
    """The other circuits through KiCad and back: the 670 has the macros the EQP-1A
    lacks (T-pad, tapped pot, bridge, VR tube, interwinding capacitance, pentodes,
    lumped parts, derived values)."""
    d = tmp_path / name
    export_circuit(circuit_path(name), d, name, "${KIPRJMOD}/varimu.kicad_sym")
    (d / "varimu.kicad_sym").write_text(library_text(), encoding="utf-8")
    xml = kn.export_netlist(d / f"{name}.kicad_sch", d / "n.xml")
    imp = import_netlist(read_netlist(xml), load_sidecar(d / f"{name}.params.yaml"))
    assert imp.problems == []
    f = tmp_path / f"{name}.yaml"
    f.write_text(to_yaml(imp.data), encoding="utf-8")
    a, b = load_circuit(circuit_path(name)), load_circuit(f)
    overrides = [*switch_configs(a)]
    if "passive_spread" in a.values:
        overrides.append({"passive_spread": 1.0, "passive_seed": 7})
    for ov in overrides:
        for cores in ("ja", "linear"):
            assert _same_ir(a, b, ov, cores) == [], (ov, cores)


# --- Pre-flight on the hand-written circuits ---------------------------------------------------


def test_preflight_on_the_hand_written_circuits():
    assert check_circuit(load_circuit(circuit_path("pultec_eqp1a"))) == []
    assert check_circuit(load_circuit(circuit_path("triode_stage"))) == []
    # The 670's T104 bridge nodes ay / bk failed the rectifier check until T104's secondary
    # got its self-capacitance (t104_c_sec_f, 2026-10-26; tests/test_editor.py checks the
    # finding without it).
    assert check_circuit(load_circuit(circuit_path("fairchild_670"))) == []


# --- Importer errors (netlists made by hand) ----------------------------------------------------


def _comp(ref, part, value, sheet="/s/", units=None, **fields):
    pins = units or {"A": ("1", "2")}
    return Component(ref, value, part, "varimu", sheet, dict(fields), pins)


def _nl(comps, nets):
    nets = tuple(Net(n, tuple(Pin(r, p, False) for r, p in ps)) for n, ps in nets)
    return Netlist("t", ("/", "/s/"), {c.ref: c for c in comps}, nets)


SIDE = {"title": "t", "input": "in", "probes": []}


def test_importer_errors():
    nets = [("/s/in", [("R1", "1"), ("R2", "1")]), ("GND", [("R1", "2"), ("R2", "2")])]
    with pytest.raises(ConfigError, match="needs a Source"):
        import_netlist(
            _nl([_comp("R1", "R", "1k"), _comp("R2", "R", "1k", Source="s")], nets), SIDE
        )
    with pytest.raises(ConfigError, match="disagree"):
        r1 = _comp("R1", "R", "1k", Param="r", Source="s")
        import_netlist(_nl([r1, _comp("R2", "R", "2k", Param="r", Source="s")], nets), SIDE)
    with pytest.raises(ConfigError, match="not one of varimu's"):
        import_netlist(_nl([_comp("R1", "Device_R", "1k", Source="s"),
                            _comp("R2", "R", "1k", Source="s")], nets), SIDE)  # fmt: skip
    clash = [("/a/x", [("R1", "1"), ("R2", "1")]), ("/b/x", [("R1", "2"), ("R2", "2")])]
    with pytest.raises(ConfigError, match="both node 'x'"):
        import_netlist(_nl([_comp("R1", "R", "1k", Source="s"),
                            _comp("R2", "R", "1k", Source="s")], clash), SIDE)  # fmt: skip
    ok = import_netlist(_nl([_comp("R1", "R", "1k", Param="r", Source="s", Genome="g.r"),
                             _comp("R2", "R", "1000.0", Param="r")], nets), SIDE)  # fmt: skip
    assert ok.data["values"]["r"] == {"value": 1000.0, "source": "s", "genome": "g.r"}
    assert ok.data["sections"][0]["parts"]["R2"] == {"R": ["in", "0"], "r": "r"}


def _switch_netlist(parts, nets):
    sw = SYMBOLS["SW_Rotary_2"]
    comps = [_comp("S1", "SW_Rotary_2", "SW", units={"A": tuple(p.number for p in sw.pins)},
                   Control="pos"), *parts]  # fmt: skip
    side = {**SIDE, "controls": {"pos": {"value": 1, "min": 1, "max": 2, "unit": "position",
                                         "source": "s"}}}  # fmt: skip
    return _nl(comps, nets), side


def test_switch_resolution():
    """A part on a contact is in at that position; a chain behind it goes with it; a
    contact net with two parts on it is a series path when open: its nodes change."""
    r = lambda ref, **f: _comp(ref, "R", "1k", Source="s", **f)  # noqa: E731
    nets = [("/s/in", [("R0", "1")]), ("/s/c", [("R0", "2"), ("S1", "C"), ("R9", "1")]),
            ("/s/k1", [("S1", "1"), ("R1", "1")]), ("/s/m", [("R1", "2"), ("R2", "1")]),
            ("GND", [("R2", "2"), ("R9", "2")])]  # fmt: skip
    nl, side = _switch_netlist([r("R0"), r("R1"), r("R2"), r("R9")], nets)
    parts = import_netlist(nl, side).data["sections"][0]["parts"]
    assert parts["S1"] == {"switch": "pos", "parts": {
        "R1": {"R": ["c", "m"], "r": {"value": 1000.0, "source": "s"}, "in": [1]},
        "R2": {"R": ["m", "0"], "r": {"value": 1000.0, "source": "s"}, "in": [1]}}}  # fmt: skip
    nets[2] = ("/s/k1", [("S1", "1"), ("R1", "1"), ("R3", "1")])
    nets[4] = ("GND", [("R2", "2"), ("R3", "2"), ("R9", "2")])
    nl, side = _switch_netlist([r("R0"), r("R1"), r("R2"), r("R3"), r("R9")], nets)
    with pytest.raises(ConfigError, match="nodes change with the switches"):
        import_netlist(nl, side)


# --- The CLI --------------------------------------------------------------------------------


def test_cli_import_and_check(tmp_path, capsys):
    side = GENERATED / "pultec_eqp1a" / "pultec_eqp1a.params.yaml"
    out = tmp_path / "eq.yaml"
    args = ["kicad-import", str(FIXTURES / "pultec_eqp1a.xml"), "--sidecar", str(side),
            "--out", str(out)]  # fmt: skip
    assert main(args) == 0 and out.read_text(encoding="utf-8").startswith("# Imported from")
    assert main(args) == 0  # its own output may be overwritten
    hand = tmp_path / "hand.yaml"
    hand.write_text("title: x\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="wasn't written by kicad-import"):
        main([*args[:-1], str(hand)])
    broken_side = GENERATED / "pultec_eqp1a_broken" / "pultec_eqp1a_broken.params.yaml"
    bad = tmp_path / "bad.yaml"
    assert main(["kicad-import", str(FIXTURES / "pultec_eqp1a_broken.xml"), "--sidecar",
                 str(broken_side), "--out", str(bad)]) == 2  # fmt: skip
    assert not bad.exists()
    assert main(["check", "--file", str(out)]) == 0
    assert "0 problem(s) over 84 switch combination(s)" in capsys.readouterr().out


def test_find_kicad_cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VARIMU_KICAD_CLI", str(tmp_path / "nope.exe"))
    with pytest.raises(kn.KiCadUnavailable):
        kn.find_kicad_cli()

"""The schematic editor (device builder B4a): symbols for the page, the drawing document,
connectivity, compiling through the importer, generated drawings of the hand-written
circuits, problems mapped onto the drawing, and the page's API."""

from __future__ import annotations

import json
import sys

import pytest

from varimu.circuit import builder
from varimu.circuit.spec import circuit_path, load_circuit, resolve
from varimu.config import REPO_ROOT
from varimu.editor.compile import check_drawing, compile_drawing, compiled_spec, element_symbols
from varimu.editor.connect import connect, netlist
from varimu.editor.drawing import Drawing, Label, Placement, Symbol, load_drawing, save_drawing
from varimu.editor.layout import generated_drawing
from varimu.editor.symbols import library_json, pin_points, transform
from varimu.kicad.compare import ir_differences
from varimu.kicad.symbols import SYMBOLS
from varimu.preflight import check_circuit, switch_configs


def _same_ir(a, b, overrides, cores="linear") -> list[str]:
    return ir_differences(builder.build_ir(a, resolve(a, overrides), cores),
                          builder.build_ir(b, resolve(b, overrides), cores))  # fmt: skip


def _round_trip(d: Drawing) -> Drawing:
    return Drawing.from_json(json.loads(json.dumps(d.to_json())))


# --- Symbols and placement ----------------------------------------------------------------------


def test_placement_transform():
    at = (10.0, 20.0)
    assert transform(1, 0, at) == (11, 20)
    assert transform(1, 0, at, 90) == (10, 19)  # counter-clockwise on the screen: right -> up
    assert transform(1, 0, at, 180) == (9, 20)
    assert transform(1, 0, at, 270) == (10, 21)
    assert transform(1, 0, at, 0, mirror=True) == (9, 20)
    assert transform(0, 1, at, 90, mirror=True) == (11, 20)  # mirrored first, then rotated
    with pytest.raises(ValueError):
        transform(0, 0, at, 45)


def test_symbols_as_json():
    lib = library_json()
    assert set(lib) == set(SYMBOLS)
    for name, s in lib.items():
        sym = SYMBOLS[name]
        assert len(s["units"]) == len(sym.units)
        for pins, defs in zip(s["units"], sym.units, strict=True):
            for p, q in zip(pins, defs, strict=True):
                assert (p["x"], p["y"]) == (q.x, -q.y)  # y flips to point down
                # The pin's line runs from its connection point into the body.
                assert p["into"] in (
                    [1, 0],
                    [-1, 0],
                    [0, 1],
                    [0, -1],
                    (1, 0),
                    (-1, 0),
                    (0, 1),
                    (0, -1),
                )
        for g in s["graphics"]:
            assert "d" in g or "text" in g
        x0, y0, x1, y1 = s["box"]
        assert x0 <= x1 and y0 <= y1
    # The inductor's bumps are four half circles bulging right, each clockwise going down.
    arcs = [g["d"] for g in lib["L"]["graphics"] if " A" in g["d"] and "Z" not in g["d"]]
    assert len(arcs) == 4 and all(" 0 0 1 " in a for a in arcs)
    json.dumps(lib)


def test_pin_points_on_the_grid():
    for sym in SYMBOLS.values():
        for u in range(1, len(sym.units) + 1):
            for rot in (0, 90, 180, 270):
                for x, y in pin_points(sym, u, (12.7, 25.4), rot).values():
                    assert abs(x / 1.27 - round(x / 1.27)) < 1e-9, sym.name
                    assert abs(y / 1.27 - round(y / 1.27)) < 1e-9, sym.name


# --- Connectivity -------------------------------------------------------------------------------


def _r(ref, x, y, rot=0, value="1k"):
    return ref, Symbol("R", value, {"Source": "test"}, {1: Placement(x, y, rot)})


def _drawing(symbols, wires=(), labels=(), grounds=()) -> Drawing:
    return Drawing(circuit={"title": "t", "input": "in", "probes": []},
                   symbols=dict(symbols), wires=[list(w) for w in wires],
                   labels=list(labels), grounds=list(grounds))  # fmt: skip


def _nets(d: Drawing) -> dict[str, set[str]]:
    return {n.node: {f"{p.ref}.{p.number}" for p in n.pins} for n in connect(d).nets}


def test_wires_join_at_ends_and_tees_not_at_crossings():
    # Wire A joins R1.2 and R2.2 by way of two bends; wire T ends on A's middle (a T
    # junction) and brings R3.1; wire C from R4.2 crosses A without ending on it.
    d = _drawing(
        [_r("R1", 0, 0), _r("R2", 20.32, 0), _r("R3", 10.16, 15.24), _r("R4", 30.48, 0)],
        wires=[
            [(0, 3.81), (0, 7.62), (20.32, 7.62), (20.32, 3.81)],  # A
            [(10.16, 11.43), (10.16, 7.62)],  # T
            [(30.48, 3.81), (30.48, 10.16), (15.24, 10.16), (15.24, 5.08)],  # C
        ],
    )
    nets = _nets(d)
    assert next(v for v in nets.values() if "R1.2" in v) == {"R1.2", "R2.2", "R3.1"}
    assert next(v for v in nets.values() if "R4.2" in v) == {"R4.2"}
    conn = connect(d)
    assert (10.16, 7.62) in [(round(x, 2), round(y, 2)) for x, y in conn.junctions]
    assert (15.24, 5.08) in [(round(x, 2), round(y, 2)) for x, y in conn.loose]


def test_pin_on_a_wire_joins_and_crossing_does_not():
    # R3 pin 1 at (5.08, 6.35) lies on the horizontal wire: joined. A vertical wire crossing
    # the horizontal one in its middle doesn't join.
    d = _drawing(
        [_r("R1", 0, 0), _r("R3", 5.08, 10.16), _r("R5", 7.62, 0)],
        wires=[[(0, 3.81), (0, 6.35), (10.16, 6.35)], [(7.62, 3.81), (7.62, 8.89)]],
    )
    nets = _nets(d)
    assert next(v for v in nets.values() if "R1.2" in v) == {"R1.2", "R3.1"}
    assert next(v for v in nets.values() if "R5.2" in v) == {"R5.2"}


def test_labels_and_grounds():
    d = _drawing(
        [_r("R1", 0, 0), _r("R2", 20.32, 0)],
        wires=[[(0, -3.81), (0, -6.35)], [(20.32, -3.81), (20.32, -6.35)]],
        labels=[Label("in", 0, -6.35), Label("in", 20.32, -6.35), Label("lost", 50, 50)],
        grounds=[Placement(0, 3.81), Placement(20.32, 3.81)],
    )
    conn = connect(d)
    by_node = {n.node: n for n in conn.nets}
    assert {f"{p.ref}.{p.number}" for p in by_node["in"].pins} == {"R1.1", "R2.1"}
    assert {f"{p.ref}.{p.number}" for p in by_node["0"].pins} == {"R1.2", "R2.2"}
    assert by_node["0"].name == "GND" and len(by_node["0"].grounds) == 2
    assert conn.warnings == ["label lost at (50, 50) touches no wire or pin"]
    assert conn.errors == []


def test_two_names_on_one_net_is_an_error():
    d = _drawing([_r("R1", 0, 0)], wires=[[(0, -3.81), (0, -6.35)]],
                 labels=[Label("a", 0, -6.35), Label("b", 0, -3.81)])  # fmt: skip
    assert connect(d).errors == ["labels a, b name one net"]
    d.labels = [Label("a", 0, -6.35)]
    d.grounds = [Placement(0, -3.81)]
    assert connect(d).errors == ["label a is on a ground net"]


def test_unlabelled_nets_are_named_as_kicad_names_them():
    d = _drawing([_r("R1", 0, 0), _r("R2", 0, 7.62)])  # R1.2 touches R2.1 at (0, 3.81)
    names = {n.name for n in connect(d).nets}
    assert names == {"Net-(R1-Pad2)", "unconnected-(R1-Pad1)", "unconnected-(R2-Pad2)"}
    nl = netlist(d)
    assert {n.name for n in nl.nets} == names and nl.components["R1"].sheet == "/"


def test_document_round_trip(tmp_path):
    d = generated_drawing(load_circuit(circuit_path("pultec_eqp1a")))
    path = save_drawing(d, tmp_path / "x.drawing.json")
    e = load_drawing(path)
    assert e.to_json() == d.to_json()
    with pytest.raises(ValueError, match="not a drawing"):
        Drawing.from_json({"format": "something else"})


# --- Hand-written circuits as drawings ----------------------------------------------------------


def test_eqp1a_drawing_compiles_to_the_same_ir():
    """B4a's first done-when on the EQP-1A: every switch combination, both core models,
    the pots' ends, drawn tolerances; values, devices and tolerance classes come back."""
    a = load_circuit(circuit_path("pultec_eqp1a"))
    c = compile_drawing(_round_trip(generated_drawing(a)))
    assert c.errors == [] and c.problems == [] and c.warnings == []
    b = compiled_spec(c)
    configs = switch_configs(a)
    assert len(configs) == 84
    for cfg in configs:
        assert _same_ir(a, b, cfg) == [], cfg
    knobs = ("lf_boost", "lf_atten", "hf_boost", "bandwidth", "hf_atten")
    for ov in ({}, {k: 1.0 for k in knobs}, {"passive_spread": 1.0, "passive_seed": 7}):
        for cores in ("ja", "linear"):
            assert _same_ir(a, b, ov, cores) == [], (ov, cores)
    assert a.values == b.values and a.devices == b.devices
    assert check_circuit(b) == []


@pytest.mark.parametrize("name", ["fairchild_670", "triode_stage"])
def test_other_circuits_compile_to_the_same_ir(name):
    a = load_circuit(circuit_path(name))
    c = compile_drawing(_round_trip(generated_drawing(a)))
    assert c.errors == [] and c.problems == []
    b = compiled_spec(c)
    overrides = [*switch_configs(a)]
    if "passive_spread" in a.values:
        overrides.append({"passive_spread": 1.0, "passive_seed": 7})
    for ov in overrides:
        for cores in ("ja", "linear"):
            assert _same_ir(a, b, ov, cores) == [], (ov, cores)


def test_670_findings_land_on_the_bridge():
    d = generated_drawing(load_circuit(circuit_path("fairchild_670")))
    c, found = check_drawing(d)
    rect = [m for m in found if m.check == "rectifier"]
    assert len(rect) == 2
    nodes = {c.conn.nets[i].node for m in rect for i in m.nets}
    assert nodes == {"ay", "bk"}
    assert {s for m in rect for s in m.symbols} == {"CR101", "CR102", "CR103", "CR104"}


def test_broken_eqp1a_faults_are_marked():
    """The broken EQP-1A (scripts/make_kicad_fixtures.py) as a drawing: each of its four
    faults is found and lands on the parts and nets it is about."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from make_kicad_fixtures import broken

    d = generated_drawing(broken(load_circuit(circuit_path("pultec_eqp1a"))))
    c, found = check_drawing(d)
    by = {m.check: m for m in found}
    assert set(by) == {"unconnected", "floating", "loop", "rectifier"}, [m.message for m in found]
    node = lambda m: {c.conn.nets[i].node for i in m.nets}  # noqa: E731
    assert by["floating"].message == "no DC path to ground from g2a" and node(by["floating"]) == {
        "g2a"
    }
    assert by["loop"].symbols == ["LBAD", "LPCCA"]
    assert by["rectifier"].symbols == ["V3"] and node(by["rectifier"]) == {"rka"}
    unconnected = [m for m in found if m.check == "unconnected"]
    assert {s for m in unconnected for s in m.symbols} == {"RBIAS_B"}
    assert {n for m in unconnected for n in node(m)} == {"n_RBIAS_B_2"}


def test_element_symbols():
    d = generated_drawing(load_circuit(circuit_path("pultec_eqp1a")))
    assert element_symbols(d, "RPL1A") == ["RPL1A"]
    assert element_symbols(d, "XV1A") == ["V1"]
    windings = element_symbols(d, "LT2_sa_lk")
    assert len(windings) == 1 and d.symbols[windings[0]].value == "sa"
    assert element_symbols(d, "RT2_core") == ["T2"]
    assert element_symbols(d, "RHBa") == ["RHB"]


def test_compile_errors_are_reported_not_raised():
    d = _drawing([_r("R1", 0, 0)])
    d.symbols["R1"].fields = {}  # a number without a source
    c = compile_drawing(d)
    assert not c.ok and any("needs a Source" in e for e in c.errors)
    _, found = check_drawing(d)
    assert [m.check for m in found] == ["import"] and found[0].symbols == ["R1"]


# --- The page's API -----------------------------------------------------------------------------


def test_editor_api():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from varimu.listen.app import AB, create_app

    client = TestClient(create_app(workers=1, ab=AB.__new__(AB)))
    assert "Schematic Editor" in client.get("/editor").text
    assert client.get("/editor/main.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/editor/../app.js").status_code == 404
    assert set(client.get("/api/editor/symbols").json()) == set(SYMBOLS)
    names = {c["name"]: c["kind"] for c in client.get("/api/editor/circuits").json()}
    assert names["triode_stage"] == "hand-written"
    r = client.get("/api/editor/open", params={"circuit": "triode_stage"}).json()
    assert r["kind"] == "hand-written" and r["ok"] and r["errors"] == []
    assert {n["node"] for n in r["nets"]} >= {"in", "g", "p", "k", "o", "0"}
    assert r["params"]["r_plate_ohm"]["value"] == 100.0e3
    assert r["bands"]["resistor"] == {"keys": ["tol_resistor_pct"], "pct": [5.0]}
    assert client.get("/api/editor/open", params={"circuit": "../x"}).status_code == 404
    assert client.post("/api/editor/check", json={"drawing": r["drawing"]}).json() == {
        "markers": []
    }
    again = client.post("/api/editor/analyze", json={"drawing": r["drawing"]}).json()
    assert again["nets"] == r["nets"]
    assert client.post("/api/editor/analyze", json={"drawing": {}}).status_code == 400

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


def test_670_bridge_without_its_secondary_capacitance():
    """The 670 passes the checks; without T104's secondary capacitance (added 2026-10-26)
    its bridge nodes fail the rectifier check, and the finding lands on the bridge."""
    import copy
    import dataclasses

    spec = load_circuit(circuit_path("fairchild_670"))
    assert check_drawing(generated_drawing(spec))[1] == []
    sections = copy.deepcopy(list(spec.sections))
    for s in sections:
        if "T104" in s["parts"]:
            del s["parts"]["T104"]["transformer"]["s"]["c"]
    d = generated_drawing(dataclasses.replace(spec, sections=tuple(sections)))
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


# --- Step 2: editing, saving, rendering ---------------------------------------------------------


def test_page_modules(tmp_path):
    """The page's edit rules and topology edits, in Node's own test runner (no npm), on
    the real symbol table; skipped without Node."""
    import os
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    symbols = tmp_path / "symbols.json"
    symbols.write_text(json.dumps(library_json()), encoding="utf-8")
    files = sorted(str(p) for p in (REPO_ROOT / "tests" / "editor_js").glob("*.test.mjs"))
    env = {**os.environ, "EDITOR_SYMBOLS": str(symbols)}
    r = subprocess.run([node, "--test", *files], capture_output=True, text=True, encoding="utf-8",
                       cwd=REPO_ROOT, env=env, check=False)  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr


def test_save_circuit(tmp_path):
    from varimu.editor.compile import save_circuit

    d = generated_drawing(load_circuit(circuit_path("pultec_eqp1a")))
    for ref in ("CC2A", "CC2B"):  # what the page does to a shared Param
        d.symbols[ref].value = "470n"
        d.symbols[ref].fields["Source"] = "edit 2026-10-26: by ear; was 250n (dwg: .25)"
    files = save_circuit(d, "eqp_mine", origin="pultec_eqp1a", root=tmp_path)
    assert [f.name for f in files] == ["eqp_mine.drawing.json", "eqp_mine.yaml"]
    saved = load_circuit(tmp_path / "eqp_mine.yaml")
    edited = {"value": 4.7e-7, "source": "edit 2026-10-26: by ear; was 250n (dwg: .25)"}
    assert saved.values["c_couple_f"] == edited
    assert (tmp_path / "eqp_mine.yaml").read_text(encoding="utf-8").startswith("# Generated from")
    assert load_drawing(files[0]).to_json() == d.to_json()
    save_circuit(d, "eqp_mine", root=tmp_path)  # a drawn circuit may be saved over
    (tmp_path / "hand.yaml").write_text("title: x\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="hand-written"):
        save_circuit(d, "hand", root=tmp_path)
    d.symbols["CC2A"].fields["Source"] = ""
    d.symbols["CC2B"].fields["Source"] = ""
    with pytest.raises(ValueError, match="doesn't compile"):
        save_circuit(d, "eqp_mine", root=tmp_path)


def test_render_job_takes_a_circuit_path():
    from varimu.sim import runner
    from varimu.sim.io import TransientSettings

    c = compile_drawing(generated_drawing(load_circuit(circuit_path("triode_stage"))))
    from varimu.editor.compile import cached_circuit

    path = cached_circuit(c)
    s = TransientSettings.from_sim_settings()
    by_path = runner.build_circuit(runner.RenderJob([0.0], circuit=str(path)), s)
    by_name = runner.build_circuit(runner.RenderJob([0.0], circuit="triode_stage"), s)
    assert ir_differences(by_path.ir, by_name.ir) == []


def test_editor_render_and_compare():
    """A drawing renders through the page's queue and comes back loudness-matched."""
    pytest.importorskip("fastapi")
    pytest.importorskip("circuitsim")
    import time

    from fastapi.testclient import TestClient

    from varimu.listen.app import AB, create_app

    client = TestClient(create_app(workers=1, ab=AB.__new__(AB)))
    stage = client.get("/api/editor/open", params={"circuit": "triode_stage"}).json()
    assert not stage["has_output"]  # its output node is `o`: renders read `out`
    body = {"drawing": stage["drawing"], "source": "signal:burst_1000hz_-10dbfs", "seconds": 0.05}
    assert (
        "label the output out to hear it"
        in client.post("/api/editor/render", json=body).json()["detail"]
    )
    r = client.get("/api/editor/open", params={"circuit": "pultec_eqp1a"}).json()
    assert r["has_output"]
    d = r["drawing"]
    body = {"drawing": d, "source": "signal:burst_1000hz_-10dbfs", "start_s": 0.0, "seconds": 0.05}
    job = client.post("/api/editor/render", json=body).json()
    assert job["circuit"].endswith(".yaml")
    for _ in range(600):
        [j] = client.get("/api/jobs", params={"ids": job["id"]}).json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert j["status"] == "done", j["error"]
    assert client.get("/api/jobs").json() == []  # the 670 page doesn't see the editor's renders
    r = client.get("/api/editor/compare", params={"ids": str(job["id"])}).json()
    assert len(r["audio"]) == 2 and len(r["envelopes"]) == 2  # dry and the render
    assert client.get(r["audio"][1]).headers["content-type"] == "audio/wav"
    assert abs(r["match"]["measured_lufs"][0] - r["match"]["measured_lufs"][1]) > 0  # matched after
    unsourced = {**d["symbols"], "RK1": {**d["symbols"]["RK1"], "fields": {}}}
    bad = {**body, "drawing": {**d, "symbols": unsourced}}
    assert "needs a Source" in client.post("/api/editor/render", json=bad).json()["detail"]
    save = lambda name: client.post("/api/editor/save", json={"drawing": d, "name": name})  # noqa: E731
    assert save("triode_stage").status_code == 409  # hand-written: never overwritten
    assert save("Bad Name").status_code == 400
    lib = client.get("/api/editor/library").json()
    assert {"12AX7", "6X4"} <= {x["name"] for x in lib["devices"]} and lib["materials"]


# --- Step 3: drawing topology ------------------------------------------------------------------


def _hand_written_stage_as_drawn(tmp_path, title: str):
    """triode_stage.yaml with what the drawing does differently: its output node is `out`
    (renders read it) and it is probed, its one section is `main` (no frame drawn)."""
    import yaml

    data = yaml.safe_load(circuit_path("triode_stage").read_text(encoding="utf-8"))
    data["title"], data["probes"] = title, ["out", "g", "p", "k"]
    data["sections"][0]["title"] = "main"
    for e in data["sections"][0]["parts"].values():
        for k, v in e.items():
            if isinstance(v, list):
                e[k] = ["out" if n == "o" else n for n in v]
    path = tmp_path / "stage.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load_circuit(path)


def test_triode_stage_drawn_in_the_editor(tmp_path):
    """B4a's done-when: the triode stage drawn from scratch in the editor (through its UI:
    scripts/editor_draw_triode.py) compiles, passes the checks, and builds the hand-written
    stage's IR; its compiled file is current."""
    import yaml

    from varimu.editor.drawing import drawing_path

    d = load_drawing(drawing_path("triode_stage_drawn"))
    assert d.frames == [] and len(d.symbols) == 10 and d.wires and d.labels and d.grounds
    c, found = check_drawing(d)
    assert c.ok and found == []
    b = compiled_spec(c)
    a = _hand_written_stage_as_drawn(tmp_path, b.title)
    for cores in ("linear", "ja"):
        ia, ib = builder.build_ir(a, resolve(a), cores), builder.build_ir(b, resolve(b), cores)
        assert ir_differences(ia, ib) == []
    committed = yaml.safe_load(circuit_path("triode_stage_drawn").read_text(encoding="utf-8"))
    committed = {k: {} if v is None else v for k, v in committed.items()}  # `values:` is empty
    assert committed == c.data, "stale: open and save triode_stage_drawn in the editor"


def test_a_drawing_probes_its_output():
    d = _drawing([_r("R1", 0, 0)], wires=[[(0, -3.81), (0, -6.35)]],
                 labels=[Label("out", 0, -6.35)], grounds=[Placement(0, 3.81)])  # fmt: skip
    d.circuit["probes"] = ["x"]
    c = compile_drawing(d)
    assert c.data["probes"] == ["out", "x"]
    assert list(c.data)[:3] == ["title", "input", "probes"]


def test_listening_stimuli_ignore_other_circuits(tmp_path, monkeypatch):
    """Saving a circuit from the editor keeps the 670's prepared A/B stimuli; changing the
    670's file doesn't."""
    import shutil

    import varimu.config
    from varimu.circuit import netlist
    from varimu.listen import prepare

    cfg = tmp_path / "config"
    shutil.copytree(varimu.config.CONFIG_DIR, cfg, ignore=shutil.ignore_patterns("*.json"))
    monkeypatch.setattr(varimu.config, "CONFIG_DIR", cfg)
    monkeypatch.setattr(netlist, "CIRCUIT_FILE", cfg / "circuits" / "fairchild_670.yaml")
    v1 = prepare.code_version()
    (cfg / "circuits" / "mine.yaml").write_text("title: x\n", encoding="utf-8")
    assert prepare.code_version() == v1
    with open(cfg / "circuits" / "fairchild_670.yaml", "a", encoding="utf-8") as f:
        f.write("\n# changed\n")
    assert prepare.code_version() != v1


USER_DRAWING = "pultec_eqp1a_drawn"


@pytest.mark.skipif(
    not (REPO_ROOT / "config" / "circuits" / f"{USER_DRAWING}.drawing.json").exists(),
    reason="the EQP-1A isn't drawn by hand in the editor yet",
)
def test_eqp1a_drawn_by_hand():
    """B4a's done-when (moved from B3): the EQP-1A drawn by hand in the editor, saved as
    pultec_eqp1a_drawn, passes the checks and builds the hand-written IR at every switch
    combination and with drawn tolerances. Name parts and nodes as the hand-written file
    does (its generated drawing shows them)."""
    from varimu.editor.drawing import drawing_path

    c, found = check_drawing(load_drawing(drawing_path(USER_DRAWING)))
    assert c.ok and [m.message for m in found] == []
    a, b = load_circuit(circuit_path("pultec_eqp1a")), compiled_spec(c)
    for ov in [*switch_configs(a), {"passive_spread": 1.0, "passive_seed": 7}]:
        assert _same_ir(a, b, ov) == [], ov

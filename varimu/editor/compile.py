"""A drawing -> a circuit file, and the pre-flight checks mapped back onto the drawing.

`compile_drawing` runs the connectivity (varimu.editor.connect) and the importer
(varimu.kicad.importer.import_netlist, the same code a KiCad netlist goes through), so a
drawn circuit gets the importer's rules: a number without a source is an error, switch
decks resolve into `switch` parts, windings join their core, dual tubes are two
instances. `check_drawing` writes the circuit file to cache/editor/ and runs
varimu.preflight at every switch combination; each problem comes back with the nets
and symbols it is about, for the page to mark.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from varimu.circuit.spec import CircuitSpec, load_circuit
from varimu.config import REPO_ROOT, ConfigError
from varimu.editor.connect import Connectivity, connect, netlist
from varimu.editor.drawing import Drawing
from varimu.kicad.importer import import_netlist, to_yaml
from varimu.kicad.symbols import SYMBOLS
from varimu.preflight import Problem, check_circuit

CACHE = REPO_ROOT / "cache" / "editor"
GENERATED_MARK = "Generated from"


@dataclass
class Compiled:
    data: dict[str, Any] | None  # the circuit file (None: it didn't compile)
    errors: list[str]  # what stopped it
    problems: list[str]  # the importer's netlist-level findings (pins without a connection)
    conn: Connectivity
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.data is not None


def compile_drawing(d: Drawing) -> Compiled:
    conn = connect(d)
    if conn.errors:
        return Compiled(None, list(conn.errors), [], conn, list(conn.warnings))
    try:
        imp = import_netlist(netlist(d, conn), d.circuit)
    except ConfigError as e:
        lines = [ln.strip() for ln in str(e).splitlines()]
        errors = [ln for ln in lines if ln and ln != "import:"]
        return Compiled(None, errors or [str(e)], [], conn, list(conn.warnings))
    return Compiled(imp.data, [], list(imp.problems), conn, list(conn.warnings))


def circuit_text(c: Compiled, origin: str) -> str:
    """The compiled circuit file's text, headed as generated from `origin`."""
    if c.data is None:
        raise ValueError("the drawing doesn't compile: " + "; ".join(c.errors))
    return to_yaml(c.data, f"{GENERATED_MARK} {origin} by the schematic editor "
                           "(varimu.editor): edit the drawing, not this file.")  # fmt: skip


def cached_circuit(c: Compiled, origin: str = "a drawing") -> Path:
    """The compiled circuit written to cache/editor/<hash>.yaml (content-addressed)."""
    text = circuit_text(c, origin)
    path = CACHE / f"{hashlib.sha256(text.encode()).hexdigest()[:16]}.yaml"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(path)
    return path


def compiled_spec(c: Compiled) -> CircuitSpec:
    return load_circuit(cached_circuit(c))


# --- Problems on the drawing -----------------------------------------------------------------


@dataclass
class Marker:
    """A problem as the page shows it."""

    check: str  # unconnected | floating | loop | rectifier | probe | build | import | drawing
    message: str
    config: str = ""
    nets: list[int] = field(default_factory=list)  # indexes into Connectivity.nets
    symbols: list[str] = field(default_factory=list)  # references

    def to_json(self) -> dict[str, Any]:
        return {"check": self.check, "message": self.message, "config": self.config,
                "nets": self.nets, "symbols": self.symbols}  # fmt: skip


def element_symbols(d: Drawing, element: str) -> list[str]:
    """The symbols an IR element (or a part's name) comes from: the part itself, a
    winding (T2's `RT2_sa` is the winding labelled sa on core T2), a tube's unit
    (`XV1A`: V1), a pot's half (`RHBa`: RHB)."""
    refs = d.symbols
    if element in refs:
        return [element]
    for ref, s in refs.items():
        if s.symbol == "Core" and element[1:].startswith(ref + "_"):
            label = re.sub(r"_(lk)$", "", element[len(ref) + 2 :])
            windings = [r for r, w in refs.items() if w.symbol == "Winding"
                        and w.fields.get("Transformer") == ref and w.value == label]  # fmt: skip
            return windings or [ref]
    if element[:1] in "XD":
        for ref, s in refs.items():
            sym = SYMBOLS.get(s.symbol)
            if sym is None or sym.kind != "device":
                continue
            multi = len(sym.units) > 1
            for u in s.units:
                if element[1:] == ref + (chr(ord("A") + u - 1) if multi else ""):
                    return [ref]
    best = max((r for r in refs if element.startswith(r) or element[1:].startswith(r)),
               key=len, default=None)  # fmt: skip
    return [best] if best else []


def markers(d: Drawing, c: Compiled, problems: list[Problem]) -> list[Marker]:
    """The import's errors and findings and the checks' problems, mapped onto the drawing."""
    by_node: dict[str, list[int]] = {}
    for i, n in enumerate(c.conn.nets):
        by_node.setdefault(n.node, []).append(i)
    by_name = {n.name: i for i, n in enumerate(c.conn.nets)}
    out = [Marker("drawing", w) for w in c.warnings]
    for e in c.errors:
        refs = [r for r in d.symbols if re.match(rf"{re.escape(r)}\b", e)]
        out.append(Marker("import", e, symbols=refs[:1]))
    for msg in c.problems:  # "unconnected: pin 2 of RBIAS_B"
        m = re.fullmatch(r"unconnected: pin (\S+) of (\S+)", msg)
        nets = []
        if m:
            name = f"unconnected-({m[2]}-Pad{m[1]})"
            nets = [by_name[name]] if name in by_name else []
        out.append(Marker("unconnected", msg, nets=nets, symbols=[m[2]] if m else []))
    for p in problems:
        nets = sorted({i for n in p.nodes for i in by_node.get(n, [])})
        syms = sorted({s for e in p.elements for s in element_symbols(d, e)})
        out.append(Marker(p.check, p.message, p.config, nets, syms))
    return out


def check_drawing(d: Drawing, c: Compiled | None = None) -> tuple[Compiled, list[Marker]]:
    """Compile and run the pre-flight checks; everything found, as markers."""
    c = c or compile_drawing(d)
    if not c.ok:
        return c, markers(d, c, [])
    try:
        problems = check_circuit(compiled_spec(c))
    except (ConfigError, ValueError, KeyError) as e:
        problems = [Problem("build", f"{type(e).__name__}: {e}")]
    return c, markers(d, c, problems)

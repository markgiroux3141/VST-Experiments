"""A circuit file -> a KiCad project drawn from the parts library (device builder, B3).

The result is label-connected, not a drawing: each section is a sheet, parts sit on a
grid, every pin has a wire stub and a label naming its node (global when the node is
on several sheets), ground pins a GND symbol. It opens in KiCad as a starting point
for a real drawing, and it is the importer's round-trip fixture: importing it builds
the same IR as the file it came from (tests/test_kicad.py).

What goes where (the inverse of varimu.kicad.importer):

- a part's main value that is a `values` key with a number becomes the symbol's Value
  (an engineering number) with Param, Source, Genome, Unit, Notes; such values leave
  the sidecar. A key into controls, derived values or device parameters stays a key;
- a switch becomes rotary switch decks on its control: the node most of its sub-parts
  share is the common, each switched part's pin on it goes to a contact net wired to
  the contacts of its positions, and parts with overlapping positions go on separate
  decks (a ganged switch). Sub-parts not on the common hang off switched ones;
- device parts become Triode / Pentode / Diode symbols, two with identical `devices`
  entries named <ref>A / <ref>B a dual symbol's units.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from varimu.circuit.spec import CircuitSpec, load_circuit
from varimu.devices.diode import JunctionDiode, VacuumDiode
from varimu.devices.library import load_device
from varimu.devices.pentode import Pentode
from varimu.devices.triode import Triode
from varimu.kicad.importer import to_yaml
from varimu.kicad.schematic import Placed, Sheet, write_project
from varimu.kicad.symbols import SYMBOLS, SymbolDef
from varimu.kicad.values import format_eng
from varimu.preflight import control_positions

CELL_MM = 38.1
_BY_MACRO = {s.macro: s for s in SYMBOLS.values() if s.kind == "macro"}
_DRAWN_KEYS = {"value", "source", "genome", "unit", "notes"}


def field_text(v: Any) -> str:
    """A param as a field: what yaml.safe_load reads back as `v`."""
    return yaml.safe_dump([v], default_flow_style=True, width=10**9).strip()[1:-1]


class _Exporter:
    def __init__(self, spec: CircuitSpec):
        self.spec = spec
        self.classes = spec.part_classes()
        self.drawn: set[str] = set()  # values keys that became symbol Values
        self.sheets: list[Sheet] = []
        self.node_sheets: dict[str, set[str]] = defaultdict(set)
        self.windings = 0
        self.tol_drawn: set[str] = set()  # designators whose class is on a symbol

    # --- values ------------------------------------------------------------------------

    def value_fields(self, x: Any) -> tuple[str, dict[str, str]]:
        """A main value as (Value, fields)."""
        if isinstance(x, Mapping):
            return format_eng(x["value"]), {"Source": str(x["source"])}
        e = self.spec.values.get(x)
        if (
            isinstance(x, str)
            and e is not None
            and set(e) <= _DRAWN_KEYS
            and isinstance(e["value"], int | float)
            and not isinstance(e["value"], bool)
        ):
            self.drawn.add(x)
            f = {"Param": x}
            for k, name in (
                ("source", "Source"),
                ("genome", "Genome"),
                ("unit", "Unit"),
                ("notes", "Notes"),
            ):
                if k in e:
                    f[name] = str(e[k])
            return format_eng(e["value"]), f
        if isinstance(x, str):
            return x, {}
        raise ValueError(f"{x!r}: a main value is a key or {{value, source}}")

    def tol_field(self, name: str, entry: Mapping, section_tol: str | None) -> dict[str, str]:
        if entry.get("tolerance", section_tol) == "none":
            return {"Tol": "none"}
        if name in self.classes:
            self.tol_drawn.add(name)
            return {"Tol": self.classes[name]}
        return {}

    # --- parts -------------------------------------------------------------------------

    def macro_part(self, name, entry, macro, sym: SymbolDef, nodes, section_tol) -> Placed:
        p = Placed(sym, name, 0, 0)
        if sym.primary:
            p.value, f = self.value_fields(entry[sym.primary])
            p.fields.update(f)
        if macro in ("R", "C", "pot", "rheostat", "tapped_pot", "t_pad"):
            p.fields.update(self.tol_field(name, entry, section_tol))
        elif entry.get("tolerance") == "none":
            p.fields["Tol"] = "none"
        for k, v in entry.items():
            if k in (macro, sym.primary, "tolerance", "in", "source", "notes", "model"):
                continue
            p.fields[k] = field_text(v)
        if macro == "bridge":
            dev = dict(self.spec.devices[entry["model"]])
            p.value = dev.pop("device")
            if entry["model"] != name:
                p.fields["Model"] = entry["model"]
            area = dev.pop("area", None)
            if area is not None and area != entry.get("area"):
                raise ValueError(f"{name}: the device's area differs from the bridge's")
            for k, v in dev.items():
                if k not in ("instance", "parallel"):
                    raise ValueError(f"{name}: device key {k} has no field")
                p.fields[k] = field_text(v)
        if macro == "vr_tube":
            dev = dict(self.spec.devices[entry["model"]])
            p.fields["device"] = field_text(dev.pop("device"))
            if "instance" in dev:
                p.fields["instance"] = field_text(dev.pop("instance"))
            if dev:
                raise ValueError(f"{name}: device keys {sorted(dev)} have no field")
            if entry["model"] != name:
                p.fields["Model"] = entry["model"]
            p.fields["Mid"] = nodes[1]
            nodes = [nodes[0], nodes[2]]
        p.nets = dict(zip(sym.order, nodes, strict=True))
        return p

    def device_type(self, key: str) -> type:
        d = self.spec.devices[key]["device"]
        e = self.spec.values.get(d)
        model = load_device(str(e["value"]) if e else d)
        for t in (Triode, Pentode, JunctionDiode, VacuumDiode):
            if isinstance(model, t):
                return t
        raise TypeError(type(model))

    def device_parts(self, items: list[tuple[str, Mapping]]) -> list[Placed]:
        """Device parts of one section as symbols, pairing <ref>A / <ref>B units."""
        out, refs = [], {}
        for name, e in items:
            letter, ref = name[0], name[1:]
            want = "D" if self.device_type(e["model"]) is JunctionDiode else "X"
            if letter != want:
                raise ValueError(f"{name}: a {self.device_type(e['model']).__name__} part's "
                                 f"name starts with {want}")  # fmt: skip
            refs[ref] = e
        done = set()
        for ref, e in refs.items():
            if ref in done:
                continue
            kind = self.device_type(e["model"])
            dev = self.spec.devices[e["model"]]
            base, unit = ref[:-1], ref[-1:]
            mate = base + "B" if unit == "A" else None
            twin = refs.get(mate) if mate else None
            dual = (
                twin is not None
                and kind is not Pentode
                and self.spec.devices[twin["model"]] == dev
                and (e["model"], twin["model"]) in ((ref, mate), (e["model"], e["model"]))
            )
            units = [(ref, e, 1), (mate, twin, 2)] if dual else [(ref, e, 1)]
            sym_name = {Triode: "Triode", Pentode: "Pentode"}.get(kind, "Diode")
            sym = SYMBOLS[sym_name + ("_Dual" if dual else "")]
            for r, ent, u in units:
                p = Placed(sym, base if dual else r, 0, 0, unit=u, value=str(dev["device"]))
                default_key = r
                if ent["model"] != default_key:
                    p.fields["Model"] = ent["model"]
                if dev.get("tolerance") == "tube":
                    p.fields["Tol"] = "tube"
                for k, v in dev.items():
                    if k in ("device", "tolerance"):
                        continue
                    if k in ("source", "notes"):
                        p.fields[k.capitalize()] = str(v)
                        continue
                    p.fields[k] = field_text(v)
                pins = sym.units[u - 1]
                p.nets = {pin.number: n for pin, n in zip(pins, ent["device"], strict=True)}
                out.append(p)
                done.add(r)
        return out

    def transformer(self, name: str, e: Mapping) -> list[Placed]:
        core = Placed(SYMBOLS["Core"], name, 0, 0, value="core")
        for k, v in e["core"].items():
            core.fields[k] = field_text(v)
        for k in ("turns", "leakage_h"):
            core.fields[k] = field_text(e[k])
        terminal = {}
        out = [core]
        for label, w in e["transformer"].items():
            self.windings += 1
            p = Placed(SYMBOLS["Winding"], f"W{self.windings}", 0, 0, value=str(label))
            p.fields["Transformer"] = name
            for k in ("ratio", "r", "c"):
                if k in w:
                    p.fields[k] = field_text(w[k])
            dot, other = (str(n) for n in w["nodes"])
            terminal.setdefault(dot, f"{label}.dot")
            terminal.setdefault(other, f"{label}.other")
            p.nets = {"1": dot, "2": other}
            out.append(p)
        if e.get("interwinding") is not None:
            iw = dict(e["interwinding"])
            iw["ends"] = [terminal[str(n)] for n in iw["ends"]]
            iw["to"] = terminal[str(iw["to"])]
            core.fields["interwinding"] = field_text(iw)
        return out

    def switch(self, name: str, e: Mapping, section_tol) -> list[Placed]:
        control = e["switch"]
        positions = control_positions(self.spec, control)
        subs = e["parts"]
        counts = Counter(n for s in subs.values() if "in" in s
                         for n in self.nodes_of(s))  # fmt: skip
        common = max(counts, key=lambda n: (counts[n], -list(counts).index(n)))
        decks: list[tuple[set, dict[int, str]]] = []
        out = []
        for sub, s in subs.items():
            p = self.part(sub, s, section_tol)
            [p] = p
            if "in" not in s or common not in self.nodes_of(s):
                out.append(p)
                continue
            pos = set(s["in"])
            deck = next((d for d in decks if not d[0] & pos), None)
            if deck is None:
                deck = (set(), {})
                decks.append(deck)
            used, contacts = deck
            used |= pos
            net = f"{name}_{sub}".lower()
            for k in pos:
                contacts[positions.index(k) + 1] = net
            pin = next(num for num, n in p.nets.items() if n == common)
            p.nets[pin] = net
            out.append(p)
        sym = SYMBOLS[f"SW_Rotary_{len(positions)}"]
        for i, (_, contacts) in enumerate(decks):
            d = Placed(sym, name if i == 0 else f"{name}_{chr(ord('B') + i - 1)}", 0, 0,
                       value=control, fields={"Control": control})  # fmt: skip
            d.nets = {"C": common}
            for k in range(1, len(positions) + 1):
                d.nets[str(k)] = contacts.get(k)
            out.append(d)
        return out

    def nodes_of(self, entry: Mapping) -> list[str]:
        macro = next(k for k in entry if k in _BY_MACRO or k == "device")
        return [str(n) for n in entry[macro]]

    def part(self, name: str, e: Mapping, section_tol) -> list[Placed]:
        if "switch" in e:
            return self.switch(name, e, section_tol)
        if "transformer" in e:
            return self.transformer(name, e)
        if "device" in e:
            raise AssertionError("device parts are drawn per section")
        macro = next(k for k in e if k in _BY_MACRO)
        if macro == "K":
            sym = SYMBOLS["K"]
            p = Placed(sym, name, 0, 0)
            p.value, f = self.value_fields(e["k"])
            p.fields.update(f)
            p.fields["inductors"] = field_text(e["K"])
            return [p]
        return [self.macro_part(name, e, macro, _BY_MACRO[macro], [str(n) for n in e[macro]],
                                section_tol)]  # fmt: skip

    # --- sheets ------------------------------------------------------------------------

    def run(self) -> None:
        for i, s in enumerate(self.spec.sections):
            sec_tol = s.get("tolerance")
            placed: list[Placed] = []
            devices = []
            for name, e in s["parts"].items():
                if "device" in e:
                    devices.append((str(name), e))
                else:
                    placed += self.part(str(name), e, sec_tol)
            placed += self.device_parts(devices)
            sheet = Sheet(str(s["title"]), f"sheet{i + 1}.kicad_sch", self.layout(placed))
            for p in placed:
                for n in p.nets.values():
                    if n:
                        self.node_sheets[n].add(sheet.name)
            self.sheets.append(sheet)

    @staticmethod
    def layout(placed: list[Placed]) -> list[Placed]:
        cols = 9
        for i, p in enumerate(placed):
            p.x = 25.4 + (i % cols) * CELL_MM + 12.7
            p.y = 38.1 + (i // cols) * CELL_MM
            for k, n in list(p.nets.items()):
                if n == "0":
                    p.nets[k] = "GND"
        return placed

    def sidecar(self) -> dict[str, Any]:
        spec = self.spec
        out: dict[str, Any] = {"title": spec.title, "input": spec.input_node,
                               "probes": list(spec.probes)}  # fmt: skip
        if spec.controls:
            out["controls"] = spec.controls
        out["values"] = {k: v for k, v in spec.values.items() if k not in self.drawn}
        if spec.device_params:
            out["device_params"] = spec.device_params
        if spec.derived:
            out["derived"] = spec.derived
        if spec.mains:
            out["mains"] = spec.mains
        if spec.parts:
            tol = {k: v for k, v in spec.parts.items() if k != "classes"}
            undrawn = {c: [d for d in ds if d not in self.tol_drawn]
                       for c, ds in (spec.parts.get("classes") or {}).items()}  # fmt: skip
            if any(undrawn.values()):
                tol["classes"] = {c: ds for c, ds in undrawn.items() if ds}
            out["tolerance"] = tol
        return out


def export_circuit(circuit: Path, directory: Path, project: str, library_uri: str) -> list[Path]:
    """Write `circuit` (a circuit file) as KiCad project `project` in `directory`, with
    its sidecar <project>.params.yaml. Returns the files written."""
    return export_spec(load_circuit(circuit), directory, project, library_uri)


def export_spec(spec: CircuitSpec, directory: Path, project: str, library_uri: str) -> list[Path]:
    """export_circuit for a loaded (or edited) circuit. A part's node "" is drawn as a pin
    left unconnected."""
    circuit = spec.path or Path(f"{project}.yaml")
    ex = _Exporter(spec)
    ex.run()
    global_nets = {n for n, sheets in ex.node_sheets.items() if len(sheets) > 1}
    files = write_project(directory, project, ex.sheets, title=spec.title,
                          global_nets=global_nets, library_uri=library_uri)  # fmt: skip
    side = Path(directory) / f"{project}.params.yaml"
    header = (f"Sidecar of {project}.kicad_sch: what isn't a part (varimu.kicad.importer).\n"
              f"Written by `varimu kicad-export` from {Path(circuit).name}; the parts' values\n"
              "are on the drawing (Value, Param, Source, Genome).")  # fmt: skip
    side.write_text(to_yaml(ex.sidecar(), header), encoding="utf-8", newline="\n")
    return [*files, side]

"""A KiCad schematic's netlist plus its sidecar -> a circuit file (device builder, B3).

The drawing has the parts (symbols of kicad/varimu.kicad_sym, varimu.kicad.symbols
has their fields) and their connections; the sidecar (<project>.params.yaml) has what
isn't a part: title, input, probes, controls, the values no part carries,
device_params, derived, mains, and the tolerance block, whose classes come from the
parts' Tol fields (the sidecar's classes list only designators on no symbol: parts
`combined` lumps into a drawn one). `import_schematic` exports the netlist with
kicad-cli, `import_netlist` reads one, and both return the circuit file's content
(`to_yaml` writes it) and the netlist-level problems (pins without a connection).

How the drawing maps onto the format:

- sections are the hierarchical sheets (title: the sheet's name), in page order;
  parts on the root sheet go in a section "main";
- nodes are the nets' labels (a local label's sheet path dropped; two nets with one
  name are an error), GND is node 0, an unlabeled net is n_<ref>_<pin>;
- a part's name is its Reference; a device unit is X<ref><unit> (D<ref><unit> for a
  junction diode, the SPICE letters) with `devices` key <ref><unit> (or Model);
- a Value that is a number makes an inline `{value, source}`, or with Param a
  `values` entry; several parts may share a Param when they agree;
- rotary switches: decks (SW_Rotary_N) are resolved, not emitted. For every
  combination of positions, a deck's common joins its selected contact, and what an
  open contact leaves hanging by one node (two-terminal parts in a chain) carries no
  current and is dropped. A part present in some combinations only becomes a
  `switch` sub-part with `in:` its positions; it must depend on one control and keep
  its nodes;
- transformers: a Core symbol (its Reference names the transformer, its fields the
  core) and Winding symbols naming it (Value: the winding's label); windings are in
  the order of their References, the elements in the core's section.

Order: parts are in the order of their References (natural sort), devices by key, so
an imported file's element order differs from a hand-written one's.
tests/test_kicad.py compares IRs element by element regardless of order, which is
the equivalence the importer promises (see docs/DEVICE_BUILDER_PLAN.md, B3).
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from varimu.circuit.ir import GROUND
from varimu.config import ConfigError
from varimu.devices.diode import JunctionDiode
from varimu.devices.library import load_device
from varimu.kicad.netlist import Netlist, export_netlist, read_netlist
from varimu.kicad.symbols import LIBRARY, SYMBOLS, SymbolDef
from varimu.kicad.values import parse_eng

GROUND_NETS = {"GND", "0"}
SIDECAR_KEYS = ("title", "input", "probes", "full_scale", "controls", "values", "device_params",
                "derived", "mains", "tolerance")  # fmt: skip
_TOLERANCED = {"R", "C", "pot", "rheostat", "tapped_pot", "t_pad"}
_PRUNABLE = {"R", "C", "L", "V", "sine", "mains", "rheostat"}  # two-terminal macros
_ROOT_SECTION = "main"


def natural(s: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


@dataclass
class Imported:
    data: dict[str, Any]  # the circuit file
    problems: list[str] = field(default_factory=list)  # netlist-level (unconnected pins)


@dataclass
class _Item:
    """A part before switch resolution: its entry with nets (KiCad net names) where the
    format has nodes."""

    name: str
    sheet: str
    entry: dict[str, Any]
    nets: list[str]  # the nets it touches, in `entry`'s node order
    prunable: bool
    place: Any = None  # how to put nodes back into `entry`


@dataclass
class _Deck:
    ref: str
    sheet: str
    control: str
    common: str | None
    contacts: dict[int, str]  # contact number -> net


class _Fail(Exception):
    pass


def _yaml_field(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise _Fail(f"field {text!r} is not YAML: {e}") from e


def _section_title(sheet: str) -> str:
    parts = [p for p in sheet.split("/") if p]
    return parts[-1] if parts else _ROOT_SECTION


class _Importer:
    def __init__(self, nl: Netlist, sidecar: Mapping[str, Any]):
        self.nl = nl
        unknown = set(sidecar) - set(SIDECAR_KEYS)
        if unknown:
            raise ConfigError(
                f"sidecar: unknown keys {sorted(unknown)} ({', '.join(SIDECAR_KEYS)})"
            )
        self.side = sidecar
        self.errors: list[str] = []
        self.problems: list[str] = []
        self.items: list[_Item] = []
        self.decks: list[_Deck] = []
        self.devices: dict[str, dict] = {}
        self.device_owner: dict[str, str] = {}
        self.param_defs: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        self.classes: dict[str, list[str]] = defaultdict(list)
        self.cores: dict[str, tuple[str, dict]] = {}
        self.windings: dict[str, list[tuple[str, str, list[str], dict]]] = defaultdict(list)
        self.pin_net: dict[tuple[str, str], str] = {}
        self.net_size: dict[str, int] = {}
        self.auto: set[str] = set()  # nets without a label

    # --- nets ------------------------------------------------------------------------

    def read_nets(self) -> None:
        names: dict[str, str] = {}
        for net in self.nl.nets:
            for p in net.pins:
                self.pin_net[(p.ref, p.pin)] = net.name
            self.net_size[net.name] = len(net.pins)
            n = net.name
            if n in GROUND_NETS:
                node = GROUND
            elif n.startswith(("Net-(", "unconnected-(")):
                first = min(net.pins, key=lambda p: (natural(p.ref), natural(p.pin)))
                node = f"n_{first.ref}_{first.pin}"
                self.auto.add(n)
            else:
                node = n.rsplit("/", 1)[-1]
            if node in names.values() and node != GROUND:
                other = next(k for k, v in names.items() if v == node)
                self.errors.append(f"nets {other!r} and {n!r} are both node {node!r}: "
                                   "name them apart (a global label joins them)")  # fmt: skip
            names[n] = node
        self.node_of = names

    def net(self, ref: str, pin: str) -> str:
        try:
            return self.pin_net[(ref, pin)]
        except KeyError:
            raise _Fail(f"pin {pin} is in no net") from None

    # --- values ----------------------------------------------------------------------

    def primary(self, ref: str, fields: dict, value: str) -> Any:
        """The Value as a param: a key, an inline {value, source}, or a Param's key."""
        num = parse_eng(value)
        if num is None:
            extra = [k for k in ("Param", "Source", "Genome") if k in fields]
            if extra:
                raise _Fail(f"Value {value!r} is a key; {', '.join(extra)} are for a number")
            return value
        src = fields.get("Source")
        if "Param" in fields:
            d = {"value": num}
            for f, k in (("Source", "source"), ("Genome", "genome"), ("Unit", "unit"),
                         ("Notes", "notes")):  # fmt: skip
                if f in fields:
                    d[k] = fields[f]
            self.param_defs[fields["Param"]].append((ref, d))
            return fields["Param"]
        if "Genome" in fields:
            raise _Fail("Genome needs a Param (the value's key)")
        if not src:
            raise _Fail(f"Value {value} needs a Source (or a Param defined with one)")
        return {"value": num, "source": src}

    def params(self, sym: SymbolDef, fields: dict, skip=()) -> dict[str, Any]:
        """The lowercase fields, as YAML."""
        return {k: _yaml_field(v) for k, v in fields.items() if k[0].islower() and k not in skip}

    # --- parts -----------------------------------------------------------------------

    def read_parts(self) -> None:
        for ref, c in sorted(self.nl.components.items(), key=lambda kv: natural(kv[0])):
            if ref.startswith("#"):
                continue
            sym = SYMBOLS.get(c.part)
            if sym is None or c.lib != LIBRARY:
                self.errors.append(f"{ref}: symbol {c.lib}:{c.part} is not one of {LIBRARY}'s")
                continue
            try:
                getattr(self, f"_{sym.kind}")(c, sym)
            except _Fail as e:
                self.errors.append(f"{ref} ({c.part}): {e}")
        # Netlist-level: unconnected pins. A pin alone on the input or the heard output
        # (`out`, e.g. a speaker's pressure pin) is connected: the render drives or reads it.
        ends = (self.side.get("input", "in"), "out")
        for ref, c in self.nl.components.items():
            sym = SYMBOLS.get(c.part)
            if sym is None or sym.kind in ("switch", "power"):
                continue
            for pins in c.units.values():
                for pin in pins:
                    net = self.pin_net.get((ref, pin))
                    if (
                        net is not None
                        and self.net_size[net] == 1
                        and self.node_of[net] not in ends
                    ):
                        self.problems.append(f"unconnected: pin {pin} of {ref}")

    def _tol(self, ref: str, macro: str, fields: dict, entry: dict) -> None:
        tol = fields.get("Tol")
        if tol is None:
            return
        if tol == "none":
            entry["tolerance"] = "none"
        elif macro in _TOLERANCED:
            self.classes[tol].append(ref)
        else:
            raise _Fail(f"a {macro} part takes no tolerance draw (Tol {tol!r})")

    def _macro(self, c, sym: SymbolDef) -> None:
        f = dict(c.fields)
        nets = [self.net(c.ref, p) for p in sym.order]
        entry: dict[str, Any] = {sym.macro: None}
        if sym.primary:
            entry[sym.primary] = self.primary(c.ref, f, c.value)
        skip = {"device", "instance", "parallel"} if sym.macro in ("bridge", "vr_tube") else set()
        entry.update(self.params(sym, f, skip))
        self._tol(c.ref, sym.macro, f, entry)
        if sym.macro == "bridge":
            key = f.get("Model", c.ref)
            entry["model"] = key
            dev = {"device": c.value}
            dev.update({k: _yaml_field(f[k]) for k in ("instance", "parallel", "area") if k in f})
            self.add_device(key, dev, c.ref)
        elif sym.macro == "vr_tube":
            key = f.get("Model", c.ref)
            entry["model"] = key
            if "device" not in f:
                raise _Fail("needs `device` (its device file)")
            dev = {"device": str(_yaml_field(f["device"]))}
            dev.update({k: _yaml_field(f[k]) for k in ("instance",) if k in f})
            self.add_device(key, dev, c.ref)
            nets.insert(1, None)  # the inner node, not a net
            mid = f.get("Mid", f"{c.ref.lower()}_mid")
            self.items.append(_Item(c.ref, c.sheet, entry, nets, False, ("vr", mid)))
            return
        self.items.append(_Item(c.ref, c.sheet, entry, nets, sym.macro in _PRUNABLE, "list"))

    def add_device(self, key: str, dev: dict, ref: str) -> None:
        if key in self.devices and self.devices[key] != dev:
            raise _Fail(f"Model {key} is {self.devices[key]} on {self.device_owner[key]}, "
                        f"{dev} here")  # fmt: skip
        self.devices[key] = dev
        self.device_owner.setdefault(key, ref)

    def _device_file(self, value: str) -> str:
        e = (self.side.get("values") or {}).get(value)
        return str(e["value"]) if isinstance(e, Mapping) else value

    def _device(self, c, sym: SymbolDef) -> None:
        f = dict(c.fields)
        tol = f.get("Tol")
        if tol not in (None, "tube", "none"):
            raise _Fail(f"Tol {tol!r}: a device takes `tube` (emission and mu draws) or none")
        try:
            base = load_device(self._device_file(c.value))
        except Exception as e:  # noqa: BLE001
            raise _Fail(f"device {c.value!r}: {e}") from e
        letter = "D" if isinstance(base, JunctionDiode) else "X"
        dev = {"device": c.value}
        if tol == "tube":
            dev["tolerance"] = "tube"
        dev.update(self.params(sym, f))
        dev.update({k.lower(): f[k] for k in ("Source", "Notes") if k in f})
        multi = len(sym.units) > 1
        placed = 0
        for i, pins in enumerate(sym.units):
            unit = chr(ord("A") + i) if multi else ""
            if not any((c.ref, p.number) in self.pin_net for p in pins):
                continue  # this unit isn't placed
            placed += 1
            key = f.get("Model", f"{c.ref}{unit}")
            self.add_device(key, dev, c.ref)
            nets = [self.net(c.ref, p.number) for p in pins]
            entry = {"device": None, "model": key}
            self.items.append(_Item(f"{letter}{c.ref}{unit}", c.sheet, entry, nets, False, "list"))
        if not placed:
            raise _Fail("no unit is placed")

    def _winding(self, c, sym: SymbolDef) -> None:
        f = dict(c.fields)
        t = f.get("Transformer")
        if not t:
            raise _Fail("needs Transformer (its core's Reference)")
        nets = [self.net(c.ref, "1"), self.net(c.ref, "2")]
        self.windings[t].append((c.ref, c.value, nets, self.params(sym, f)))

    def _core(self, c, sym: SymbolDef) -> None:
        self.cores[c.ref] = (c.sheet, self.params(sym, dict(c.fields)))

    def _coupling(self, c, sym: SymbolDef) -> None:
        f = dict(c.fields)
        entry = {"K": self.params(sym, f).get("inductors"), "k": self.primary(c.ref, f, c.value)}
        self.items.append(_Item(c.ref, c.sheet, entry, [], False, "none"))

    def _switch(self, c, sym: SymbolDef) -> None:
        ctrl = c.fields.get("Control")
        if not ctrl:
            raise _Fail("needs Control (the control it follows)")
        contacts = {}
        for pin in sym.pins:
            net = self.pin_net.get((c.ref, pin.number))
            if pin.number != "C" and net is not None and self.net_size[net] > 1:
                contacts[int(pin.number)] = net
        common = self.pin_net.get((c.ref, "C"))
        self.decks.append(_Deck(c.ref, c.sheet, ctrl, common, contacts))

    def _power(self, c, sym: SymbolDef) -> None:
        pass

    # --- transformers -------------------------------------------------------------------

    def build_transformers(self) -> None:
        for t in sorted(set(self.windings) - set(self.cores)):
            self.errors.append(f"windings {[w[0] for w in self.windings[t]]} name core {t}, "
                               "which isn't drawn")  # fmt: skip
        for t, (sheet, f) in self.cores.items():
            ws = sorted(self.windings.get(t, []), key=lambda w: natural(w[0]))
            if not ws:
                self.errors.append(f"{t}: a core without windings")
                continue
            labels = [w[1] for w in ws]
            if len(set(labels)) != len(labels):
                self.errors.append(f"{t}: winding labels repeat: {labels}")
                continue
            f = dict(f)
            entry: dict[str, Any] = {"transformer": None}
            entry["core"] = {k: f.pop(k) for k in ("material", "area_m2", "path_m", "gap_m")
                             if k in f}  # fmt: skip
            for k in ("turns", "leakage_h"):
                if k in f:
                    entry[k] = f.pop(k)
            terminals = {}
            nets: list[str] = []
            for _, label, wnets, _ in ws:
                terminals[f"{label}.dot"], terminals[f"{label}.other"] = wnets
                nets += wnets
            if "interwinding" in f:
                iw = dict(f.pop("interwinding"))
                try:
                    iw["ends"] = [terminals[e] for e in iw["ends"]]
                    iw["to"] = terminals[iw["to"]]
                except (KeyError, TypeError) as e:
                    self.errors.append(f"{t}: interwinding names {e}, not <label>.dot / .other")
                    continue
                entry["interwinding"] = iw
            if f:
                self.errors.append(f"{t}: unknown core fields {sorted(f)}")
            windings = {label: wf for _, label, _, wf in ws}
            self.items.append(_Item(t, sheet, entry, nets, False, ("transformer", windings)))

    # --- switches -----------------------------------------------------------------------

    def resolve_switches(self) -> dict[str, tuple[str | None, list[Any] | None, tuple]]:
        """Part name -> (control, positions it is in, its nets): (None, None, nets) for a
        part that is always in."""
        controls = self.side.get("controls") or {}
        positions: dict[str, list[Any]] = {}
        for d in self.decks:
            e = controls.get(d.control)
            if e is None:
                self.errors.append(f"{d.ref}: Control {d.control!r} is not a control")
                continue
            if "choices" in e:
                pos = list(e["choices"])
            elif e.get("unit") == "position":
                pos = list(range(int(e["min"]), int(e["max"]) + 1))
            else:
                self.errors.append(f"{d.ref}: control {d.control} has no `choices` or "
                                   "`unit: position`")  # fmt: skip
                continue
            if d.contacts and max(d.contacts) > len(pos):
                self.errors.append(f"{d.ref}: contact {max(d.contacts)} wired, but "
                                   f"{d.control} has {len(pos)} positions")  # fmt: skip
            positions[d.control] = pos
        if self.errors:
            raise _Fail("switches")
        keys = sorted(positions)
        combos = list(itertools.product(*(positions[k] for k in keys)))
        if len(combos) > 4096:
            raise _Fail(f"{len(combos)} switch combinations")
        contact_nets = {n for d in self.decks for n in d.contacts.values()}
        self.commons = {d.common for d in self.decks if d.common is not None}
        protected = {self.side.get("input", "in")}
        seen: dict[str, dict[tuple, tuple]] = defaultdict(dict)  # part -> combo -> nodes
        for combo in combos:
            at = dict(zip(keys, combo, strict=True))
            uf: dict[str, str] = {}

            def find(x: str, uf: dict[str, str] = uf) -> str:
                uf.setdefault(x, x)
                while uf[x] != x:
                    x = uf[x]
                return x

            for d in self.decks:
                if d.control not in at or d.common is None:
                    continue
                k = positions[d.control].index(at[d.control]) + 1
                if k in d.contacts:
                    uf[find(d.contacts[k])] = find(d.common)
            commons = {find(d.common) for d in self.decks if d.common is not None}
            live = [True] * len(self.items)
            degree: dict[str, int] = defaultdict(int)
            touching: dict[str, list[int]] = defaultdict(list)
            for i, it in enumerate(self.items):
                for n in it.nets:
                    if n is not None:
                        degree[find(n)] += 1
                        touching[find(n)].append(i)
            queue = [r for r in {find(n) for n in contact_nets} - commons if degree[r] <= 1]
            while queue:
                r = queue.pop()
                for i in touching[r]:
                    if not live[i] or not self.items[i].prunable:
                        continue
                    live[i] = False
                    for n in self.items[i].nets:
                        rn = find(n)
                        degree[rn] -= 1
                        if (
                            rn != r
                            and degree[rn] == 1
                            and self.node_of.get(rn) not in (GROUND, *protected)
                        ):
                            queue.append(rn)  # fmt: skip
            groups: dict[str, list[str]] = defaultdict(list)
            for n in self.node_of:
                groups[find(n)].append(n)
            named: dict[str, str] = {}

            def node(n: str | None, named: dict[str, str] = named, groups=groups, find=find):
                if n is None:
                    return None
                r = find(n)
                if r not in named:
                    named[r] = self._merged_name(groups[r])
                return named[r]

            for i, it in enumerate(self.items):
                if live[i]:
                    seen[it.name][combo] = tuple(node(n) for n in it.nets)
        out = {}
        for it in self.items:
            present = seen.get(it.name, {})
            if not present:
                self.errors.append(f"{it.name}: connected at no switch position")
                continue
            node_sets = set(present.values())
            if len(node_sets) > 1:
                self.errors.append(f"{it.name}: its nodes change with the switches "
                                   f"({sorted(node_sets, key=str)[:3]})")  # fmt: skip
                continue
            nodes = node_sets.pop()
            if len(present) == len(combos):
                out[it.name] = (None, None, nodes)
                continue
            dep = None
            for ci, k in enumerate(keys):
                f: dict[Any, bool] = {}
                if all(f.setdefault(cb[ci], cb in present) == (cb in present) for cb in combos):
                    dep = (k, [p for p in positions[k] if f.get(p)])
                    break
            if dep is None:
                self.errors.append(f"{it.name}: in or out depends on several switches")
                continue
            out[it.name] = (dep[0], dep[1], nodes)
        return out

    def _merged_name(self, group: list[str]) -> str:
        """The node a group of joined nets becomes: ground, else a deck common's label,
        else any label, else the common's (or the first net's) generated name."""
        if any(self.node_of[n] == GROUND for n in group):
            return GROUND
        commons = sorted(n for n in group if n in self.commons)
        for n in commons:
            if n not in self.auto:
                return self.node_of[n]
        labelled = sorted(self.node_of[n] for n in group if n not in self.auto)
        if labelled:
            return labelled[0]
        return self.node_of[(commons or sorted(group))[0]]

    # --- assembly -----------------------------------------------------------------------

    def place(self, it: _Item, nodes: tuple) -> dict[str, Any]:
        e = dict(it.entry)
        kind = next(iter(e))
        if it.place == "list":
            e[kind] = list(nodes)
        elif it.place == "none":
            pass
        elif it.place[0] == "vr":
            e[kind] = [nodes[0], it.place[1], nodes[2]]
        elif it.place[0] == "transformer":
            ws = {}
            for i, (label, wf) in enumerate(it.place[1].items()):
                ws[label] = {"nodes": [nodes[2 * i], nodes[2 * i + 1]], **wf}
            e[kind] = ws
        return e

    def values(self) -> dict[str, Any]:
        side = dict(self.side.get("values") or {})
        known = (
            set(side)
            | set(self.side.get("controls") or {})
            | set(self.side.get("device_params") or {})
            | set((self.side.get("derived") or {}).get("values") or {})
        )
        for key, defs in sorted(self.param_defs.items()):
            refs = [r for r, _ in defs]
            if key in known:
                self.errors.append(
                    f"Param {key} ({', '.join(refs)}) is also defined in the sidecar"
                )
                continue
            vals = {d["value"] for _, d in defs}
            if len(vals) > 1:
                said = ", ".join(f"{r}={d['value']}" for r, d in defs)
                self.errors.append(f"Param {key}: {said} disagree")
                continue
            merged: dict[str, Any] = {"value": defs[0][1]["value"]}
            for k in ("source", "genome", "unit", "notes"):
                got = {d[k] for _, d in defs if k in d}
                if len(got) > 1:
                    self.errors.append(f"Param {key}: parts disagree on its {k}")
                elif got:
                    merged[k] = got.pop()
            if "source" not in merged:
                self.errors.append(f"Param {key} ({', '.join(refs)}): no part gives a Source")
            side[key] = merged
        return side

    def run(self) -> Imported:
        self.read_nets()
        self.read_parts()
        self.build_transformers()
        if self.errors:
            raise ConfigError("import:\n  " + "\n  ".join(self.errors))
        try:
            resolved = self.resolve_switches()
        except _Fail:
            resolved = {}
        values = self.values()
        if self.errors:
            raise ConfigError("import:\n  " + "\n  ".join(self.errors))

        order = {s: i for i, s in enumerate(self.nl.sheets)}
        by_sheet: dict[str, list[_Item]] = defaultdict(list)
        for it in self.items:
            by_sheet[it.sheet].append(it)
        decks_by = defaultdict(list)
        for d in self.decks:
            decks_by[d.control].append(d)
        sections, names_used = [], {it.name for it in self.items}
        for sheet in sorted(by_sheet, key=lambda s: order.get(s, len(order))):
            parts: dict[str, Any] = {}
            switched: dict[str, dict[str, Any]] = {}
            rows: list[tuple[str, str]] = []  # (sort name, part name)
            for it in sorted(by_sheet[sheet], key=lambda i: natural(i.name)):
                ctrl, pos, nodes = resolved[it.name]
                e = self.place(it, nodes)
                if ctrl is None:
                    parts[it.name] = e
                    rows.append((it.name, it.name))
                    continue
                if ctrl not in switched:
                    here = sorted((d.ref for d in decks_by[ctrl] if d.sheet == sheet), key=natural)
                    name = (here or sorted((d.ref for d in decks_by[ctrl]), key=natural))[0]
                    while name in names_used:
                        name += "_"
                    names_used.add(name)
                    switched[ctrl] = {"name": name, "parts": {}}
                    rows.append((name, name))
                switched[ctrl]["parts"][it.name] = {**e, "in": pos}
            for _, name in sorted(rows, key=lambda r: natural(r[0])):
                if name in parts:
                    continue
                ctrl = next(k for k, v in switched.items() if v["name"] == name)
                parts[name] = {"switch": ctrl, "parts": switched[ctrl]["parts"]}
            ordered = {n: parts[n] for _, n in sorted(rows, key=lambda r: natural(r[0]))}
            sections.append({"title": _section_title(sheet), "parts": ordered})

        data: dict[str, Any] = {}
        for k in ("title", "input", "probes", "full_scale", "controls"):
            if k in self.side:
                data[k] = self.side[k]
        data.setdefault("title", self.nl.title)
        data["values"] = values
        for k in ("device_params", "derived", "mains"):
            if k in self.side:
                data[k] = self.side[k]
        if self.classes:
            tol = dict(self.side.get("tolerance") or {})
            if not tol:
                raise ConfigError(f"Tol fields name classes {sorted(self.classes)}, but the "
                                  "sidecar has no tolerance block")  # fmt: skip
            # The sidecar's classes: designators on no symbol (parts that `combined` lumps
            # into a drawn one, e.g. the 670's R102 into R101).
            drawn = {r for rs in self.classes.values() for r in rs}
            for c, refs in (tol.get("classes") or {}).items():
                if clash := sorted(set(refs) & drawn):
                    raise ConfigError(f"sidecar tolerance class {c} names drawn parts {clash}: "
                                      "their Tol fields give their class")  # fmt: skip
                self.classes[c] = [*self.classes[c], *refs]
            bands = list(tol.get("bands") or {})
            cls = sorted(self.classes, key=lambda c: (bands.index(c) if c in bands else 99, c))
            tol["classes"] = {c: sorted(self.classes[c], key=natural) for c in cls}
            data["tolerance"] = tol
        elif "tolerance" in self.side:
            data["tolerance"] = self.side["tolerance"]
        data["devices"] = {k: self.devices[k] for k in sorted(self.devices, key=natural)}
        data["sections"] = sections
        return Imported(data, self.problems)


def load_sidecar(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def sidecar_path(schematic: Path) -> Path:
    """<project>.params.yaml next to <project>.kicad_sch."""
    schematic = Path(schematic)
    return schematic.with_name(schematic.stem + ".params.yaml")


def import_netlist(nl: Netlist, sidecar: Mapping[str, Any]) -> Imported:
    return _Importer(nl, sidecar).run()


def import_schematic(schematic: Path, netlist_out: Path, sidecar: Path | None = None) -> Imported:
    """Export `schematic`'s netlist to `netlist_out` with kicad-cli and import it with
    its sidecar (default <project>.params.yaml)."""
    xml = export_netlist(schematic, netlist_out)
    return import_netlist(read_netlist(xml), load_sidecar(sidecar or sidecar_path(schematic)))


# --- Writing the circuit file ------------------------------------------------------------


def _flow(x: Any) -> str:
    return yaml.safe_dump(x, default_flow_style=True, width=10**9, sort_keys=False).strip()


def _scalar(x: Any) -> str:
    return _flow([x])[1:-1]


def to_yaml(data: Mapping[str, Any], header: str = "") -> str:
    """The circuit file, laid out like the hand-written ones: one entry per line."""
    out = [f"# {line}".rstrip() for line in header.splitlines()]
    if out:
        out.append("")
    for key, val in data.items():
        if key in ("controls", "values", "device_params", "devices") and isinstance(val, Mapping):
            out.append(f"{key}:")
            out += [f"  {_flow({k: v})[1:-1]}" for k, v in val.items()]
        elif key == "sections":
            out.append("sections:")
            for s in val:
                out.append(f"  - title: {_scalar(s['title'])}")
                if "tolerance" in s:
                    out.append(f"    tolerance: {s['tolerance']}")
                out.append("    parts:")
                for name, e in s["parts"].items():
                    if "switch" in e:
                        out.append(f"      {_flow({name: None})[1:-1].split(':')[0]}:")
                        out.append(f"        switch: {_scalar(e['switch'])}")
                        out.append("        parts:")
                        out += [f"          {_flow({n: p})[1:-1]}" for n, p in e["parts"].items()]
                    else:
                        out.append(f"      {_flow({name: e})[1:-1]}")
        elif isinstance(val, Mapping | list):
            out.append(yaml.safe_dump({key: val}, sort_keys=False, width=10**9,
                                      default_flow_style=None).rstrip())  # fmt: skip
        else:
            out.append(f"{key}: {_scalar(val)}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"

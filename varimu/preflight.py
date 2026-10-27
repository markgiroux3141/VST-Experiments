"""Pre-flight checks: what makes a circuit fail before it renders (device builder, B3).

`check_circuit(spec)` builds the circuit's IR at every combination of its switches'
positions and checks each one; `check_ir(ir)` checks one IR. The checks:

- unconnected: a node only one element terminal touches (the audio input counts as a
  source from the input node to ground, as the simulation drives it);
- floating: nodes with no DC path to ground through resistors, inductors, windings,
  sources or transformer cores (tube and diode pins don't count: a cut-off tube or a
  reverse-biased diode is no path; the 670's T104 needed its 1 GOhm leak for this);
- loop: a loop of voltage sources, inductors and windings alone (no resistance): its
  DC current is undetermined;
- rectifier: a diode's node that an inductor or winding reaches with no capacitor on
  it. When the rectifier cuts off, the inductance kicks into a node with nothing on it:
  ngspice stopped there until the 670's supply got its winding and cell capacitances
  (CLAUDE.md, "The power supply and the start of a run"). A rectifier node fed through
  resistance alone (the EQP-1A's 6X4 cathode) is fine;
- probe: a probe or the input naming no node.

Also varimu.kicad.importer's netlist-level check (pins without a connection).
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from varimu.circuit import builder
from varimu.circuit.ir import (
    GROUND,
    Capacitor,
    CircuitIR,
    Device,
    Inductor,
    Resistor,
    SineSource,
    VoltageSource,
    Winding,
    element_nodes,
)
from varimu.circuit.spec import CircuitSpec, resolve
from varimu.devices.core import MagneticCore
from varimu.devices.diode import JunctionDiode, VacuumDiode

MAX_CONFIGS = 4096


@dataclass(frozen=True)
class Problem:
    check: str  # unconnected | floating | loop | rectifier | probe | build
    message: str
    config: str = ""  # the switch positions it shows at ("" = all, or no switches)
    # What it is about, for the editor to mark (not part of equality): circuit nodes and
    # IR element names.
    nodes: tuple[str, ...] = field(default=(), compare=False)
    elements: tuple[str, ...] = field(default=(), compare=False)

    def __str__(self) -> str:
        at = f" [{self.config}]" if self.config else ""
        return f"{self.check}: {self.message}{at}"


def control_positions(spec: CircuitSpec, key: str) -> list[Any]:
    """A switch control's positions: its `choices`, or min..max for `unit: position`."""
    e = spec.controls[key]
    if "choices" in e:
        return list(e["choices"])
    if e.get("unit") == "position":
        return list(range(int(e["min"]), int(e["max"]) + 1))
    raise ValueError(f"control {key}: a switch's control has `choices` or `unit: position`")


def switch_controls(spec: CircuitSpec) -> list[str]:
    """The controls the file's switch parts follow, in order of appearance."""
    out: list[str] = []

    def walk(parts: Mapping) -> None:
        for entry in parts.values():
            if isinstance(entry, Mapping) and "switch" in entry:
                if entry["switch"] not in out:
                    out.append(entry["switch"])
                walk(entry.get("parts") or {})

    for s in spec.sections:
        walk(s["parts"])
    return out


def switch_configs(spec: CircuitSpec) -> list[dict[str, Any]]:
    """Every combination of the switch controls' positions ([{}] without switches)."""
    keys = switch_controls(spec)
    combos = [dict(zip(keys, c, strict=True)) for c in
              itertools.product(*(control_positions(spec, k) for k in keys))]  # fmt: skip
    if len(combos) > MAX_CONFIGS:
        raise ValueError(f"{len(combos)} switch combinations (more than {MAX_CONFIGS})")
    return combos


class _Union:
    def __init__(self) -> None:
        self.up: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.up.setdefault(x, x)
        while self.up[x] != x:
            self.up[x] = self.up[self.up[x]]
            x = self.up[x]
        return x

    def join(self, a: str, b: str) -> bool:
        """Join a and b; False when they were already joined."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.up[ra] = rb
        return True


def _terminals(el) -> tuple[str, ...]:
    """The circuit terminals of an element (a winding's core node is the core's own)."""
    return (el.a, el.b) if isinstance(el, Winding) else element_nodes(el)


def _path(tree: Mapping[str, list[tuple[str, str]]], a: str, b: str) -> list[str]:
    """The elements on the way from node a to node b in a forest of joined elements."""
    back: dict[str, tuple[str, str] | None] = {a: None}
    queue = [a]
    while queue:
        n = queue.pop(0)
        if n == b:
            break
        for m, el in tree.get(n, ()):
            if m not in back:
                back[m] = (n, el)
                queue.append(m)
    out, n = [], b
    while back.get(n) is not None:
        n, el = back[n]
        out.append(el)
    return [e for e in reversed(out) if e != "<input>"]


def check_ir(ir: CircuitIR, config: str = "") -> list[Problem]:
    models = {m.name: m for m in ir.models}
    els = [el for s in ir.sections for el in s.elements]
    nodes: dict[str, list[str]] = defaultdict(list)  # node -> element names on it
    for el in els:
        for n in element_nodes(el):
            nodes[n].append(el.name)
    out: list[Problem] = []

    def problem(check: str, msg: str, nodes=(), elements=()) -> None:
        out.append(Problem(check, msg, config, tuple(nodes), tuple(elements)))

    for n in [ir.input_node, *(p.node for p in ir.probes)]:
        if n not in nodes:
            problem("probe", f"{n!r} is not a node of the circuit", nodes=[n])
    if ir.input_node in nodes:
        nodes[ir.input_node].append("<input>")

    for n, names in sorted(nodes.items()):
        if n != GROUND and len(names) == 1:
            problem("unconnected", f"node {n} has only {names[0]} on it", [n], names[:1])

    dc, loops = _Union(), _Union()
    dc.find(GROUND)
    dc.join(ir.input_node, GROUND)
    loops.join(ir.input_node, GROUND)
    tree: dict[str, list[tuple[str, str]]] = defaultdict(list)  # node -> (node, element)
    tree[ir.input_node].append((GROUND, "<input>"))
    tree[GROUND].append((ir.input_node, "<input>"))
    for el in els:
        t = _terminals(el)
        if isinstance(el, Resistor | Inductor | VoltageSource | SineSource | Winding):
            dc.join(*t)
        if isinstance(el, Device) and isinstance(models.get(el.model), MagneticCore):
            for n in el.nodes[1:]:
                dc.join(el.nodes[0], n)
        if isinstance(el, Inductor | VoltageSource | SineSource | Winding):
            if not loops.join(*t):
                path = _path(tree, t[0], t[1])
                problem("loop", f"{el.name} closes a loop of sources, inductors and "
                                "windings with no resistance", t, [el.name, *path])  # fmt: skip
            else:
                tree[t[0]].append((t[1], el.name))
                tree[t[1]].append((t[0], el.name))
        if isinstance(el, Winding):
            dc.find(el.core)
    islands: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        if dc.find(n) != dc.find(GROUND):
            islands[dc.find(n)].append(n)
    for island in islands.values():
        island.sort()
        more = f" (+{len(island) - 6} more)" if len(island) > 6 else ""
        problem("floating", f"no DC path to ground from {', '.join(island[:6])}{more}", island)

    inductive = {n for el in els if isinstance(el, Inductor | Winding) for n in _terminals(el)}
    capacitive = {n for el in els if isinstance(el, Capacitor) for n in (el.a, el.b)}
    rect_nodes: dict[str, list[str]] = defaultdict(list)
    for el in els:
        if isinstance(el, Device) and isinstance(models.get(el.model), JunctionDiode | VacuumDiode):
            for n in el.nodes:
                rect_nodes[n].append(el.name)
    for n, names in sorted(rect_nodes.items()):
        if n != GROUND and n in inductive and n not in capacitive:
            problem("rectifier", f"node {n} ({', '.join(names)}) is fed by an inductance "
                                 "and has no capacitor on it", [n], names)  # fmt: skip
    return out


def check_circuit(
    spec: CircuitSpec, overrides: Mapping[str, Any] | None = None, cores: str = "linear"
) -> list[Problem]:
    """The checks at every switch combination; a problem found at every combination is
    reported once, without its positions."""
    configs = switch_configs(spec)
    found: dict[tuple[str, str], list[str]] = {}
    for cfg in configs:
        tag = ", ".join(f"{k}={v}" for k, v in cfg.items())
        try:
            ir = builder.build_ir(spec, resolve(spec, {**(overrides or {}), **cfg}), cores)
            probs = check_ir(ir)
        except Exception as e:  # noqa: BLE001 - a build error is the check's finding
            probs = [Problem("build", f"{type(e).__name__}: {e}")]
        for p in probs:
            found.setdefault((p.check, p.message), (p, []))[1].append(tag)
    out = []
    for (check, msg), (p, tags) in found.items():
        config = "" if len(tags) == len(configs) else "; ".join(tags)
        out.append(Problem(check, msg, config, p.nodes, p.elements))
    return out

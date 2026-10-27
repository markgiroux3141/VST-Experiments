"""A drawing's connectivity: which pins, wires, labels and grounds are one net.

The rules (the plan's B4a):
- a pin joins every wire that passes through its connection point (at an end, a bend or
  mid-segment), and every other pin, label or ground at that point;
- a wire's end (or bend) on another wire joins them (a T junction); wires that only
  cross don't join;
- labels with the same name are one net (one canvas: every label is global); a ground
  is node 0;
- a label or ground joins the wire or pin at its point.

`netlist(drawing)` turns the nets into a varimu.kicad.netlist.Netlist, named as kicad-cli
names them (a label's name, GND, "Net-(REF-PadN)", "unconnected-(REF-PadN)") so the
importer reads it as it reads KiCad's.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from varimu.editor.drawing import Drawing
from varimu.editor.symbols import pin_points
from varimu.kicad.importer import natural
from varimu.kicad.netlist import Component, Net, Netlist, Pin
from varimu.kicad.symbols import LIBRARY, SYMBOLS

GROUND_NAME = "GND"
_CELL_MM = 5.08
_EPS = 1e-3  # mm: points closer than this are one point


@dataclass(frozen=True)
class PinRef:
    ref: str
    unit: int
    number: str


@dataclass
class DrawnNet:
    name: str  # the netlist's name (see the module docstring)
    node: str  # the circuit node it becomes before switch resolution ("0" for ground)
    pins: list[PinRef] = field(default_factory=list)
    wires: list[int] = field(default_factory=list)
    labels: list[int] = field(default_factory=list)
    grounds: list[int] = field(default_factory=list)


@dataclass
class Connectivity:
    nets: list[DrawnNet]
    errors: list[str]  # what stops compiling (two names on one net, unknown symbols)
    warnings: list[str]  # labels and grounds that touch nothing
    pin_xy: dict[PinRef, tuple[float, float]]
    junctions: list[tuple[float, float]]  # where to draw a junction dot
    loose: list[tuple[float, float]]  # wire ends that touch nothing

    def net_of_pin(self) -> dict[PinRef, int]:
        return {p: i for i, n in enumerate(self.nets) for p in n.pins}


def _key(x: float, y: float) -> tuple[int, int]:
    return round(x / _EPS), round(y / _EPS)


def _on_segment(p, a, b) -> bool:
    (px, py), (ax, ay), (bx, by) = p, a, b
    if abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) > _EPS * max(1.0, math.dist(a, b)):
        return False
    return (min(ax, bx) - _EPS <= px <= max(ax, bx) + _EPS
            and min(ay, by) - _EPS <= py <= max(ay, by) + _EPS)  # fmt: skip


class _Segments:
    """Wire segments bucketed on a grid of cells, for point queries."""

    def __init__(self, wires: list[list[tuple[float, float]]]):
        self.cells: dict[tuple[int, int], list[tuple[int, tuple, tuple]]] = defaultdict(list)
        for i, w in enumerate(wires):
            pts = w if len(w) > 1 else w * 2
            for a, b in zip(pts, pts[1:], strict=False):
                x0, x1 = sorted((a[0], b[0]))
                y0, y1 = sorted((a[1], b[1]))
                for cx in range(
                    math.floor((x0 - _EPS) / _CELL_MM), math.floor((x1 + _EPS) / _CELL_MM) + 1
                ):
                    for cy in range(math.floor((y0 - _EPS) / _CELL_MM),
                                    math.floor((y1 + _EPS) / _CELL_MM) + 1):  # fmt: skip
                        self.cells[(cx, cy)].append((i, a, b))

    def wires_at(self, p: tuple[float, float]) -> set[int]:
        cell = (math.floor(p[0] / _CELL_MM), math.floor(p[1] / _CELL_MM))
        return {i for i, a, b in self.cells.get(cell, ()) if _on_segment(p, a, b)}


class _Union:
    def __init__(self) -> None:
        self.up: dict = {}

    def find(self, x):
        self.up.setdefault(x, x)
        while self.up[x] != x:
            self.up[x] = self.up[self.up[x]]
            x = self.up[x]
        return x

    def join(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.up[ra] = rb


def connect(d: Drawing) -> Connectivity:
    errors: list[str] = []
    warnings: list[str] = []
    pin_xy: dict[PinRef, tuple[float, float]] = {}
    for ref, s in d.symbols.items():
        sym = SYMBOLS.get(s.symbol)
        if sym is None:
            errors.append(f"{ref}: no symbol {s.symbol!r}")
            continue
        for unit, pl in s.units.items():
            if not 1 <= unit <= len(sym.units):
                errors.append(f"{ref}: {s.symbol} has no unit {unit}")
                continue
            for num, xy in pin_points(sym, unit, (pl.x, pl.y), pl.rot, pl.mirror).items():
                pin_xy[PinRef(ref, unit, num)] = xy

    segs = _Segments(d.wires)
    uf = _Union()
    at_point: dict[tuple[int, int], list] = defaultdict(list)  # pins, labels, grounds
    for p, xy in pin_xy.items():
        at_point[_key(*xy)].append(("p", p))
        uf.find(("p", p))
    for i, lb in enumerate(d.labels):
        at_point[_key(lb.x, lb.y)].append(("l", i))
        uf.join(("l", i), ("name", lb.name))
    for i, g in enumerate(d.grounds):
        at_point[_key(g.x, g.y)].append(("g", i))
        uf.join(("g", i), ("name", GROUND_NAME))
    for i in range(len(d.wires)):
        uf.find(("w", i))

    touched_points: dict[tuple[int, int], int] = defaultdict(int)  # for junction dots
    for k, items in at_point.items():
        xy = (k[0] * _EPS, k[1] * _EPS)
        for it in items[1:]:
            uf.join(items[0], it)
        hit = segs.wires_at(xy)
        for w in hit:
            uf.join(items[0], ("w", w))
        if not hit and len(items) == 1 and items[0][0] in ("l", "g"):
            kind = "label " + d.labels[items[0][1]].name if items[0][0] == "l" else "a ground"
            warnings.append(f"{kind} at ({xy[0]:g}, {xy[1]:g}) touches no wire or pin")

    junctions: list[tuple[float, float]] = []
    loose: list[tuple[float, float]] = []
    ends: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, w in enumerate(d.wires):
        if not w:
            continue
        for xy in {w[0], w[-1]}:
            ends[_key(*xy)].append(i)
    for k, ws in ends.items():
        xy = (k[0] * _EPS, k[1] * _EPS)
        hit = segs.wires_at(xy)
        for w in hit:
            uf.join(("w", ws[0]), ("w", w))
        others = hit - set(ws)  # wires through this point that don't end here: a T
        pins_here = sum(1 for it in at_point.get(k, ()) if it[0] == "p")
        n = len(ws) + 2 * len(others) + pins_here
        touched_points[k] = n
        if n >= 3:
            junctions.append(xy)
        elif n == 1 and not at_point.get(k):
            loose.append(xy)
    # A pin mid-wire is a junction too (the wire passes through it).
    for xy in pin_xy.values():
        k = _key(*xy)
        if k in touched_points:
            continue
        through = [w for w in segs.wires_at(xy) if xy not in (d.wires[w][0], d.wires[w][-1])]
        if through:
            junctions.append(xy)

    groups: dict = defaultdict(list)
    for item in list(uf.up):
        groups[uf.find(item)].append(item)
    nets: list[DrawnNet] = []
    for items in groups.values():
        pins = sorted((it[1] for it in items if it[0] == "p"),
                      key=lambda p: (natural(p.ref), p.unit, natural(p.number)))  # fmt: skip
        names = sorted({n for kind, n in items if kind == "name"} - {GROUND_NAME})
        grounded = ("name", GROUND_NAME) in items
        net = DrawnNet("", "", pins,
                       sorted(it[1] for it in items if it[0] == "w"),
                       sorted(it[1] for it in items if it[0] == "l"),
                       sorted(it[1] for it in items if it[0] == "g"))  # fmt: skip
        if grounded and names:
            errors.append(f"label {', '.join(names)} is on a ground net")
        elif len(names) > 1:
            errors.append(f"labels {', '.join(names)} name one net")
        if grounded:
            net.name, net.node = GROUND_NAME, "0"
        elif names:
            net.name = net.node = names[0]
        elif pins:
            first = pins[0]
            net.name = (f"{'unconnected' if len(pins) == 1 else 'Net'}-"
                        f"({first.ref}-Pad{first.number})")  # fmt: skip
            net.node = f"n_{first.ref}_{first.number}"
        else:
            continue  # wires and labels without a pin: nothing to name
        nets.append(net)
    nets.sort(key=lambda n: (n.node != "0", natural(n.node)))
    return Connectivity(nets, errors, warnings, pin_xy, junctions, loose)


def section_of(d: Drawing, ref: str) -> str | None:
    """The frame title a symbol belongs to (its first placed unit's origin), or None."""
    s = d.symbols[ref]
    if not s.units:
        return None
    pl = s.units[min(s.units)]
    f = d.frame_of(pl.x, pl.y)
    return f.title if f else None


def netlist(d: Drawing, conn: Connectivity | None = None) -> Netlist:
    """The drawing as the netlist varimu.kicad.importer reads: frames are sheets (in
    order), a part outside every frame is on the root sheet (section "main")."""
    conn = conn or connect(d)
    comps = {}
    for ref, s in d.symbols.items():
        sym = SYMBOLS.get(s.symbol)
        if sym is None:
            continue
        title = section_of(d, ref)
        units = {chr(ord("A") + u - 1): tuple(p.number for p in sym.units[u - 1])
                 for u in sorted(s.units) if 1 <= u <= len(sym.units)}  # fmt: skip
        comps[ref] = Component(
            ref=ref,
            value=s.value,
            part=s.symbol,
            lib=LIBRARY,
            sheet=f"/{title}/" if title else "/",
            fields={k: v for k, v in s.fields.items() if str(v).strip()},
            units=units,
        )
    nets = tuple(
        Net(n.name, tuple(Pin(p.ref, p.number, False) for p in n.pins)) for n in conn.nets if n.pins
    )
    sheets = ("/", *(f"/{f.title}/" for f in d.frames))
    return Netlist(source="drawing", sheets=sheets, components=comps, nets=nets,
                   title=str(d.circuit.get("title", "")))  # fmt: skip

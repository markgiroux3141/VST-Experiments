"""A generated drawing of a circuit file: its parts as symbols, wired where it is easy,
label-connected elsewhere.

The parts and fields come from varimu.kicad.export (the same symbols, Values, Param /
Source / Genome / Tol fields, switch decks, Core + Winding transformers, dual tubes, and
the sidecar). Each section is a frame. Within it:

- parts are ordered by signal flow: a breadth-first walk over shared nodes from the
  input (sections the walk doesn't reach keep the file's order);
- two-terminal parts (R, C, L, rheostat, sources, windings) stand vertically, ground at
  the bottom, and stack into chains where one's lower node is the next one's upper node:
  a wire joins them, labelled with the node;
- every other pin gets a short wire and a label naming its node, or a ground.

Every net keeps its node's name on a label, so compiling the drawing gives the circuit
file's IR back (tests/test_editor.py), which is what a hand-written circuit's drawing
promises. It is generated on open and never saved over the hand-written file.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from varimu.circuit.spec import CircuitSpec, load_circuit
from varimu.editor.drawing import GRID_MM, Drawing, Frame, Label, Placement, Symbol
from varimu.editor.symbols import pin_points
from varimu.kicad.export import _Exporter
from varimu.kicad.schematic import GROUND_NET, STUB_MM, Placed

TWO_TERMINAL = {"R", "C", "L", "Rheostat", "V", "Sine", "Mains", "Winding"}
CHAIN_MAX = 4
GAP_MM = 5.08  # the wire between two stacked parts
COL_MM = 17.78  # a chain's column
LABEL_ROOM_MM = 7.62  # room for a label beside a part's side pin
FRAME_PAD_MM = 10.16
ITEM_GAP_MM = 5.08
FRAME_GAP_MM = 20.32
ROW_WIDTH_MM = 520.0
# outward direction of a stub -> label rotation (text reading away from the pin), ground
# rotation (its bars away from the pin)
_LABEL_ROT = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}
_GROUND_ROT = {(0, 1): 0, (1, 0): 90, (0, -1): 180, (-1, 0): 270}
_INTO = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}


def _snap(x: float) -> float:
    return round(x / GRID_MM) * GRID_MM


@dataclass
class _Item:
    parts: list[tuple[Placed, int]]  # (part, rotation); a chain has several
    w: float = 0.0
    h: float = 0.0
    top: list[float] = field(default_factory=list)  # each part's origin below the item's top


def _span(p: Placed) -> tuple[float, float]:
    """A vertical two-terminal part's pin offsets above and below its origin (y down)."""
    return -p.sym.pin("1").y, -p.sym.pin("2").y  # pin 1 is up: negative y in y-down


def _signal_order(sheets, input_node: str) -> dict[int, int]:
    """id(part) -> its position in a breadth-first walk over nodes from the input."""
    on: dict[str, list[Placed]] = defaultdict(list)
    parts = [p for s in sheets for p in s.symbols]
    for p in parts:
        for n in p.nets.values():
            if n and n != GROUND_NET:
                on[n].append(p)
    order: dict[int, int] = {}
    seen_nodes = {input_node}
    queue = deque([input_node])
    while queue:
        n = queue.popleft()
        for p in on.get(n, []):
            if id(p) in order:
                continue
            order[id(p)] = len(order)
            for m in p.nets.values():
                if m and m != GROUND_NET and m not in seen_nodes:
                    seen_nodes.add(m)
                    queue.append(m)
    for p in parts:
        order.setdefault(id(p), len(order))
    return order


def _items(placed: list[Placed], order: dict[int, int]) -> list[_Item]:
    """Chains of stacked two-terminal parts, and every other part on its own."""
    placed = sorted(placed, key=lambda p: order[id(p)])
    rot: dict[int, int] = {}
    for p in placed:
        if p.sym.name in TWO_TERMINAL:
            top, bottom = p.nets.get("1"), p.nets.get("2")
            rot[id(p)] = 180 if top == GROUND_NET and bottom != GROUND_NET else 0

    def ends(p: Placed) -> tuple[str | None, str | None]:
        a, b = p.nets.get("1"), p.nets.get("2")
        return (b, a) if rot[id(p)] == 180 else (a, b)

    used: set[int] = set()
    items: list[_Item] = []
    for p in placed:
        if id(p) in used:
            continue
        used.add(id(p))
        if id(p) not in rot:
            items.append(_Item([(p, 0)]))
            continue
        chain = [p]
        while len(chain) < CHAIN_MAX:
            bottom = ends(chain[-1])[1]
            if not bottom or bottom == GROUND_NET:
                break
            nxt = next((q for q in placed if id(q) in rot and id(q) not in used
                        and ends(q)[0] == bottom), None)  # fmt: skip
            if nxt is None:
                break
            used.add(id(nxt))
            chain.append(nxt)
        items.append(_Item([(q, rot[id(q)]) for q in chain]))
    for it in items:
        if len(it.parts) == 1 and it.parts[0][0].sym.name not in TWO_TERMINAL:
            p = it.parts[0][0]
            xs = [q.x for q in p.unit_pins()] or [0.0]
            ys = [-q.y for q in p.unit_pins()] or [0.0]
            it.w = _snap(max(xs) - min(xs) + 2 * (STUB_MM + LABEL_ROOM_MM) + 2.54)
            it.h = _snap(max(ys) - min(ys) + 2 * (STUB_MM + 3.81))
            it.top = [_snap(-min(ys) + STUB_MM + 3.81)]
            continue
        it.w = COL_MM
        y = STUB_MM + 3.81
        for q, r in it.parts:
            up, down = _span(q)
            if r == 180:
                up, down = -down, -up
            it.top.append(_snap(y - up))
            y += down - up + GAP_MM
        it.h = _snap(y - GAP_MM + STUB_MM + 3.81)
    return items


def generated_drawing(spec: CircuitSpec) -> Drawing:
    ex = _Exporter(spec)
    ex.run()
    d = Drawing(circuit=ex.sidecar())
    order = _signal_order(ex.sheets, spec.input_node)
    x0 = y0 = row_h = 0.0
    for sheet in ex.sheets:
        items = _items(sheet.symbols, order)
        area = sum((it.w + ITEM_GAP_MM) * (it.h + ITEM_GAP_MM) for it in items)
        target = max(max(it.w for it in items), math.sqrt(area * 2.2))
        # Pack items in rows within the frame.
        rows: list[list[_Item]] = [[]]
        width = 0.0
        for it in items:
            if rows[-1] and width + it.w > target:
                rows.append([])
                width = 0.0
            rows[-1].append(it)
            width += it.w + ITEM_GAP_MM
        fw = max(sum(it.w + ITEM_GAP_MM for it in r) for r in rows) - ITEM_GAP_MM + 2 * FRAME_PAD_MM
        fh = sum(max(it.h for it in r) + ITEM_GAP_MM for r in rows) - ITEM_GAP_MM + 2 * FRAME_PAD_MM
        fw, fh = _snap(fw + GRID_MM), _snap(fh + GRID_MM)
        if x0 > 0 and x0 + fw > ROW_WIDTH_MM:
            x0, y0, row_h = 0.0, y0 + row_h + FRAME_GAP_MM, 0.0
        d.frames.append(Frame(sheet.name, x0, y0, fw, fh))
        y = y0 + FRAME_PAD_MM
        for r in rows:
            x = x0 + FRAME_PAD_MM
            for it in r:
                _place(d, it, _snap(x), _snap(y))
                x += it.w + ITEM_GAP_MM
            y += max(it.h for it in r) + ITEM_GAP_MM
        x0 += fw + FRAME_GAP_MM
        row_h = max(row_h, fh)
    return d


def _add(d: Drawing, p: Placed, x: float, y: float, rot: int) -> dict[str, tuple[float, float]]:
    s = d.symbols.setdefault(p.ref, Symbol(p.sym.name, p.value or p.sym.value, dict(p.fields)))
    s.units[p.unit] = Placement(x, y, rot)
    return pin_points(p.sym, p.unit, (x, y), rot)


def _stub(d: Drawing, p: Placed, number: str, xy, rot: int, net: str | None) -> None:
    """A short wire out of a pin and the label (or ground) at its end."""
    if not net:  # None: a contact left open; "": a pin left unconnected
        return
    into = _INTO[p.sym.pin(number).angle]
    if rot == 180:
        into = (-into[0], -into[1])
    out = (-into[0], -into[1])
    ax, ay = xy
    bx, by = ax + out[0] * STUB_MM, ay + out[1] * STUB_MM
    d.wires.append([(ax, ay), (bx, by)])
    if net == GROUND_NET:
        d.grounds.append(Placement(bx, by, _GROUND_ROT[out]))
    else:
        d.labels.append(Label(net, bx, by, _LABEL_ROT[out]))


def _place(d: Drawing, it: _Item, x: float, y: float) -> None:
    if len(it.parts) == 1 and it.parts[0][0].sym.name not in TWO_TERMINAL:
        p = it.parts[0][0]
        xs = [q.x for q in p.unit_pins()] or [0.0]
        cx = _snap(x + STUB_MM + LABEL_ROOM_MM + 1.27 - min(xs))
        pts = _add(d, p, cx, y + it.top[0], 0)
        for pin in p.unit_pins():
            _stub(d, p, pin.number, pts[pin.number], 0, p.nets.get(pin.number))
        return
    cx = _snap(x + 5.08)
    prev = None
    for (p, rot), top in zip(it.parts, it.top, strict=True):
        pts = _add(d, p, cx, y + top, rot)
        upper, lower = ("2", "1") if rot == 180 else ("1", "2")
        if prev is None:
            _stub(d, p, upper, pts[upper], rot, p.nets.get(upper))
        else:
            a, b = prev, pts[upper]
            d.wires.append([a, b])
            net = p.nets.get(upper)
            if net and net != GROUND_NET:
                d.labels.append(Label(net, a[0], _snap((a[1] + b[1]) / 2), 0))
        prev = pts[lower]
    p, rot = it.parts[-1]
    lower = "1" if rot == 180 else "2"
    _stub(d, p, lower, prev, rot, p.nets.get(lower))


def drawing_of_circuit(path: Path) -> Drawing:
    return generated_drawing(load_circuit(path))

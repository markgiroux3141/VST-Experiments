"""Hand-planned drawings of circuit files: the kit scripts/draw_*.py draw with.

A Sketch starts from a circuit's generated drawing (varimu.editor.layout), keeping every
symbol with its fields and the sidecar, and drops the layout. A script then places each
part, draws wires between pins and points, and adds labels, grounds and frames:

    sk = Sketch(load_circuit(circuit_path("pultec_eqp1a")))
    sk.offset = (100, 40)                      # coordinates below are relative to this
    sk.place("RPSU1", 10.16, 0, rot=90)        # pin 1 left, pin 2 right
    sk.wire("RPSU1.2", (None, 7.62), "CPSU1.1")  # None: the previous point's coordinate
    sk.label("b1", "RPSU1.2")

`problems()` says what keeps the drawing from being the circuit: unplaced symbols, off-grid
or diagonal wires, compile errors, labels touching nothing, loose wire ends, a symbol in
the wrong frame, and, pin by pin, nets that join what the circuit keeps apart, split what
it joins, or lack the circuit's node name. A deck contact's net needs no name (the
importer names it after the deck's common).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from varimu.circuit.spec import CircuitSpec
from varimu.editor.compile import compile_drawing
from varimu.editor.connect import PinRef, section_of
from varimu.editor.drawing import GRID_MM, Drawing, Frame, Label, Placement, Symbol
from varimu.editor.layout import generated_drawing
from varimu.editor.symbols import pin_points
from varimu.kicad.export import _Exporter
from varimu.kicad.schematic import GROUND_NET
from varimu.kicad.symbols import SYMBOLS

Point = tuple[float, float]
_EPS = 1e-6
# A label's text reads away from its wire: the direction of the wire's free side.
LABEL_ROT = {"right": 0, "up": 90, "left": 180, "down": 270}
GROUND_ROT = {"down": 0, "right": 90, "up": 180, "left": 270}


def _on_grid(v: float) -> bool:
    return abs(v / GRID_MM - round(v / GRID_MM)) < 1e-6


class Sketch:
    def __init__(self, spec: CircuitSpec):
        base = generated_drawing(spec)
        self.d = Drawing(
            circuit=base.circuit,
            symbols={r: Symbol(s.symbol, s.value, dict(s.fields)) for r, s in base.symbols.items()},
        )
        self.units = {r: sorted(s.units) for r, s in base.symbols.items()}
        ex = _Exporter(spec)
        ex.run()
        self.expected: dict[tuple[str, str], str | None] = {}  # (ref, pin) -> the circuit's net
        self.sheet: dict[str, str] = {}
        self.contact_nets: set[str] = set()
        commons: set[str] = set()
        for sheet in ex.sheets:
            for p in sheet.symbols:
                self.sheet[p.ref] = sheet.name
                for num, net in p.nets.items():
                    self.expected[(p.ref, num)] = net
                if p.sym.kind == "switch":
                    commons.add(p.nets.get("C"))
                    self.contact_nets |= {n for k, n in p.nets.items() if k != "C" and n}
        self.contact_nets -= commons
        self.offset: Point = (0.0, 0.0)
        self._last: Point | None = None

    # --- points ------------------------------------------------------------------------------

    def pin(self, ref_pin: str) -> Point:
        """'REF.N': pin N's connection point (on whichever unit has it)."""
        ref, num = ref_pin.rsplit(".", 1)
        s = self.d.symbols[ref]
        sym = SYMBOLS[s.symbol]
        for u, pl in s.units.items():
            pts = pin_points(sym, u, (pl.x, pl.y), pl.rot, pl.mirror)
            if num in pts:
                return pts[num]
        raise KeyError(f"{ref_pin}: not placed (or no such pin)")

    def at(self, p: Any) -> Point:
        """A point: 'REF.N', or (x, y) relative to the offset, where None takes the previous
        point's coordinate (so a wire can turn a corner without repeating it; a label or
        ground at (None, None) goes where the last wire ended)."""
        if isinstance(p, str):
            xy = self.pin(p)
        else:
            x, y = p
            ox, oy = self.offset
            last = self._last
            if (x is None or y is None) and last is None:
                raise ValueError(f"{p}: no previous point")
            xy = (last[0] if x is None else x + ox, last[1] if y is None else y + oy)
        self._last = xy
        return xy

    # --- drawing -----------------------------------------------------------------------------

    def place(self, ref: str, x: float, y: float, rot: int = 0, mirror: bool = False,
              unit: int = 1) -> None:  # fmt: skip
        if ref not in self.d.symbols:
            raise KeyError(f"{ref}: not a part of this circuit")
        ox, oy = self.offset
        self.d.symbols[ref].units[unit] = Placement(x + ox, y + oy, rot, mirror)

    def wire(self, *pts: Any) -> list[Point]:
        self._last = None
        w = [self.at(p) for p in pts]
        self.d.wires.append(w)
        return w

    def label(self, name: str, at: Any, side: str = "right") -> None:
        x, y = self.at(at)
        self.d.labels.append(Label(name, x, y, LABEL_ROT[side]))

    def ground(self, at: Any, side: str = "down") -> None:
        x, y = self.at(at)
        self.d.grounds.append(Placement(x, y, GROUND_ROT[side]))

    def frame(self, title: str, x: float, y: float, w: float, h: float) -> None:
        self.d.frames.append(Frame(title, x, y, w, h))

    # --- checking ----------------------------------------------------------------------------

    def problems(self) -> list[str]:
        d = self.d
        out: list[str] = []
        for ref, units in self.units.items():
            missing = [u for u in units if u not in d.symbols[ref].units]
            if missing:
                out.append(f"{ref}: unit {missing} not placed")
        if out:
            return out
        for i, w in enumerate(d.wires):
            for a, b in zip(w, w[1:], strict=False):
                if abs(a[0] - b[0]) > _EPS and abs(a[1] - b[1]) > _EPS:
                    out.append(f"wire {i}: diagonal {a} -> {b}")
            for x, y in w:
                if not (_on_grid(x) and _on_grid(y)):
                    out.append(f"wire {i}: ({x:g}, {y:g}) off the grid")
        for ref, s in d.symbols.items():
            for u, pl in s.units.items():
                if not (_on_grid(pl.x) and _on_grid(pl.y)):
                    out.append(f"{ref} unit {u}: ({pl.x:g}, {pl.y:g}) off the grid")
            got = section_of(d, ref)
            if got != self.sheet[ref]:
                out.append(f"{ref}: in frame {got!r}, belongs in {self.sheet[ref]!r}")
        c = compile_drawing(d)
        out += [f"error: {e}" for e in c.errors]
        out += [f"warning: {w}" for w in c.warnings]
        out += [f"loose wire end at ({x:g}, {y:g})" for x, y in c.conn.loose]
        # Pin by pin: one drawn net per circuit net, named as the circuit names it.
        of_pin = c.conn.net_of_pin()
        drawn_of: dict[str, set[int]] = defaultdict(set)
        want_of: dict[int, set[str]] = defaultdict(set)
        for (ref, num), net in self.expected.items():
            sym = SYMBOLS[d.symbols[ref].symbol]
            unit = next(u for u in self.units[ref] if num in pin_points(sym, u, (0, 0)))
            i = of_pin.get(PinRef(ref, unit, num))
            if not net:  # an open contact or a pin left unconnected: alone on its net
                if i is not None and len(c.conn.nets[i].pins) > 1:
                    out.append(f"{ref}.{num}: should be open, is on {c.conn.nets[i].node}")
                continue
            drawn_of[net].add(i)
            want_of[i].add(net)
        for net, idx in sorted(drawn_of.items()):
            if len(idx) > 1:
                parts = [sorted(f"{p.ref}.{p.number}" for p in c.conn.nets[i].pins) for i in idx]
                out.append(f"net {net} split: {parts}")
        for i, nets in sorted(want_of.items()):
            node = c.conn.nets[i].node
            if len(nets) > 1:
                out.append(f"one drawn net ({node}) joins {sorted(nets)}")
                continue
            (net,) = nets
            want = "0" if net == GROUND_NET else net
            if node != want and not (net in self.contact_nets and node.startswith("n_")):
                out.append(f"net {net}: named {node!r}")
        return out

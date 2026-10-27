"""The symbol table (varimu.kicad.symbols) as the editor page draws it, and the
placement transform the page and the connectivity share.

Coordinates are mm with y down (the drawing's, as on a KiCad sheet); the table's are y
up, so every y flips here. A placed unit is mirrored (x -> -x) if asked, then rotated
`rot` degrees counter-clockwise on the screen (a multiple of 90), then moved to (x, y):
SVG `translate(x y) rotate(-rot) scale(mirror ? -1 : 1, 1)`.
"""

from __future__ import annotations

import functools
import math
from typing import Any

from varimu.kicad.sexpr import Sym
from varimu.kicad.symbols import SYMBOLS, SymbolDef

ROTATIONS = (0, 90, 180, 270)
# A pin's `angle` (the table's: from the connection point into the body, y up) as a unit
# vector with y down.
_INTO = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}


def transform(x: float, y: float, at: tuple[float, float], rot: int = 0,
              mirror: bool = False) -> tuple[float, float]:  # fmt: skip
    """A point of a symbol (y down) placed at `at`, rotated and mirrored."""
    if rot not in ROTATIONS:
        raise ValueError(f"rotation {rot}: one of {ROTATIONS}")
    if mirror:
        x = -x
    c, s = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[rot]
    return at[0] + x * c + y * s, at[1] - x * s + y * c


def pin_points(sym: SymbolDef, unit: int, at, rot: int = 0, mirror: bool = False):
    """{pin number: (x, y)} of a placed unit's pins (their connection points)."""
    return {p.number: transform(p.x, -p.y, at, rot, mirror) for p in sym.units[unit - 1]}


# --- Graphics as SVG -------------------------------------------------------------------------


def _get(node: list, head: str) -> list | None:
    return next((k for k in node[1:] if isinstance(k, list) and k[0] == Sym(head)), None)


def _fill(node: list) -> str:
    f = _get(node, "fill")
    t = _get(f, "type") if f else None
    return t[1].name if t else "none"


def _n(x: float) -> str:
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _arc(start, mid, end) -> str:
    """An SVG arc through three points (already y down)."""
    (ax, ay), (bx, by), (cx, cy) = start, mid, end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return f"M{_n(ax)},{_n(ay)} L{_n(cx)},{_n(cy)}"
    ux = (
        (ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)
    ) / d
    uy = (
        (ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)
    ) / d
    r = math.hypot(ax - ux, ay - uy)
    turn = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)  # > 0: clockwise on the screen
    side_mid = (cx - ax) * (by - ay) - (cy - ay) * (bx - ax)
    side_centre = (cx - ax) * (uy - ay) - (cy - ay) * (ux - ax)
    large = 1 if side_mid * side_centre > 1e-12 else 0
    return f"M{_n(ax)},{_n(ay)} A{_n(r)},{_n(r)} 0 {large} {1 if turn > 0 else 0} {_n(cx)},{_n(cy)}"


def _graphic(node: list) -> tuple[dict[str, Any], list[tuple[float, float]]]:
    """A graphic as {d, fill} (or {text, x, y, size}), and the points that bound it."""
    head = node[0].name
    fill = _fill(node)
    if head == "polyline":
        pts = [(k[1], -k[2]) for k in _get(node, "pts")[1:]]
        d = "M" + " L".join(f"{_n(x)},{_n(y)}" for x, y in pts)
    elif head == "rectangle":
        (x0, y0), (x1, y1) = _get(node, "start")[1:3], _get(node, "end")[1:3]
        d = f"M{_n(x0)},{_n(-y0)} H{_n(x1)} V{_n(-y1)} H{_n(x0)} Z"
        pts = [(x0, -y0), (x1, -y1)]
    elif head == "circle":
        cx, cy = _get(node, "center")[1:3]
        r = _get(node, "radius")[1]
        cy = -cy
        d = (f"M{_n(cx - r)},{_n(cy)} A{_n(r)},{_n(r)} 0 1 0 {_n(cx + r)},{_n(cy)} "
             f"A{_n(r)},{_n(r)} 0 1 0 {_n(cx - r)},{_n(cy)} Z")  # fmt: skip
        pts = [(cx - r, cy - r), (cx + r, cy + r)]
    elif head == "arc":
        s, m, e = (tuple(_get(node, k)[1:3]) for k in ("start", "mid", "end"))
        pts = [(s[0], -s[1]), (m[0], -m[1]), (e[0], -e[1])]
        d = _arc(*pts)
    elif head == "text":
        at = _get(node, "at")
        size = _get(_get(_get(node, "effects"), "font"), "size")[1]
        return {"text": node[1], "x": at[1], "y": -at[2], "size": size}, [(at[1], -at[2])]
    else:
        raise ValueError(f"graphic {head!r}")
    return {"d": d, "fill": fill == "outline"}, pts


def symbol_json(s: SymbolDef) -> dict[str, Any]:
    """One symbol for the page: its graphics (SVG path data, y down), pins per unit with
    the direction into the body, its fields, and where Reference and Value go."""
    drawn = [_graphic(g) for g in s.graphics]
    graphics = [g for g, _ in drawn]
    units = []
    for pins in s.units:
        units.append([
            {"number": p.number, "name": p.name, "x": p.x, "y": -p.y, "length": p.length,
             "into": _INTO[p.angle]}
            for p in pins
        ])  # fmt: skip
    (rx, ry), (vx, vy), justify = s.text_at()
    pts = [(p.x, -p.y) for p in s.pins] + [q for _, ps in drawn for q in ps]
    box = (
        [min(x for x, _ in pts), min(y for _, y in pts), max(x for x, _ in pts),
         max(y for _, y in pts)] if pts else [-2.54, -2.54, 2.54, 2.54]
    )  # fmt: skip
    return {
        "name": s.name,
        "kind": s.kind,
        "prefix": s.prefix,
        "description": s.description,
        "macro": s.macro,
        "primary": s.primary,
        "fields": list(s.fields),
        "value": s.value,
        "units": units,
        "graphics": graphics,
        "text": {"ref": [rx, -ry], "value": [vx, -vy], "justify": justify},
        "box": box,
    }


@functools.cache
def library_json() -> dict[str, Any]:
    """Every symbol of the table, by name."""
    return {name: symbol_json(s) for name, s in SYMBOLS.items()}

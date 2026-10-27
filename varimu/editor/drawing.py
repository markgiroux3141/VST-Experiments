"""The drawing document: what the editor saves (config/circuits/<name>.drawing.json).

A drawing is the source of a circuit made in the editor; compiling it
(varimu.editor.compile) writes the circuit file renders read. Its JSON:

    {"format": "varimu-drawing", "version": 1,
     "circuit": {...},       # what isn't a part: title, input, probes, controls, values no
                             # part carries, device_params, derived, mains, tolerance (the
                             # importer's sidecar, varimu.kicad.importer.SIDECAR_KEYS)
     "frames": [{"title", "x", "y", "w", "h"}],      # the sections, in order
     "symbols": {"RPL1A": {"symbol": "R", "value": "200K",
                           "fields": {"Source": "...", "Tol": "r10", ...},
                           "units": {"1": {"x", "y", "rot", "mirror"}}}},
     "wires": [[[x, y], [x, y], ...], ...],           # polylines
     "labels": [{"name", "x", "y", "rot"}],          # a net's name at a point
     "grounds": [{"x", "y", "rot"}]}                  # node 0 at a point

Coordinates are mm, y down, on the 1.27 mm grid (varimu.editor.symbols has the
placement transform). A symbol's fields are those of varimu.kicad.symbols (Source, Param,
Genome, Tol, ... and the macro's lowercase params, as YAML text); its Value is an
engineering number or a key. A symbol belongs to the frame its first unit's origin is in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FORMAT = "varimu-drawing"
VERSION = 1
GRID_MM = 1.27


@dataclass
class Placement:
    x: float
    y: float
    rot: int = 0
    mirror: bool = False

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"x": _r(self.x), "y": _r(self.y)}
        if self.rot:
            d["rot"] = self.rot
        if self.mirror:
            d["mirror"] = True
        return d


@dataclass
class Symbol:
    symbol: str  # its name in varimu.kicad.symbols.SYMBOLS
    value: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    units: dict[int, Placement] = field(default_factory=dict)  # placed units (1-based)


@dataclass
class Frame:
    title: str
    x: float
    y: float
    w: float
    h: float

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h


@dataclass
class Label:
    name: str
    x: float
    y: float
    rot: int = 0


@dataclass
class Drawing:
    circuit: dict[str, Any] = field(default_factory=dict)
    frames: list[Frame] = field(default_factory=list)
    symbols: dict[str, Symbol] = field(default_factory=dict)
    wires: list[list[tuple[float, float]]] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    grounds: list[Placement] = field(default_factory=list)

    def frame_of(self, x: float, y: float) -> Frame | None:
        return next((f for f in self.frames if f.contains(x, y)), None)

    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "version": VERSION,
            "circuit": self.circuit,
            "frames": [
                {"title": f.title, "x": _r(f.x), "y": _r(f.y), "w": _r(f.w), "h": _r(f.h)}
                for f in self.frames
            ],  # fmt: skip
            "symbols": {
                ref: {
                    "symbol": s.symbol,
                    "value": s.value,
                    "fields": s.fields,
                    "units": {str(u): p.to_json() for u, p in sorted(s.units.items())},
                }
                for ref, s in self.symbols.items()
            },  # fmt: skip
            "wires": [[[_r(x), _r(y)] for x, y in w] for w in self.wires],
            "labels": [
                {
                    "name": lb.name,
                    "x": _r(lb.x),
                    "y": _r(lb.y),
                    **({"rot": lb.rot} if lb.rot else {}),
                }
                for lb in self.labels
            ],  # fmt: skip
            "grounds": [g.to_json() for g in self.grounds],
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Drawing:
        if d.get("format") != FORMAT:
            raise ValueError(f"not a drawing (format {d.get('format')!r}, want {FORMAT!r})")
        if d.get("version") != VERSION:
            raise ValueError(f"drawing version {d.get('version')}: this code reads {VERSION}")

        def place(p: dict) -> Placement:
            return Placement(float(p["x"]), float(p["y"]), int(p.get("rot", 0)),
                             bool(p.get("mirror", False)))  # fmt: skip

        return cls(
            circuit=dict(d.get("circuit") or {}),
            frames=[Frame(f["title"], *(float(f[k]) for k in "xywh")) for f in d.get("frames", [])],
            symbols={
                ref: Symbol(
                    s["symbol"],
                    str(s.get("value", "")),
                    {k: str(v) for k, v in (s.get("fields") or {}).items()},
                    {int(u): place(p) for u, p in (s.get("units") or {}).items()},
                )
                for ref, s in (d.get("symbols") or {}).items()
            },  # fmt: skip
            wires=[[(float(x), float(y)) for x, y in w] for w in d.get("wires", [])],
            labels=[
                Label(lb["name"], float(lb["x"]), float(lb["y"]), int(lb.get("rot", 0)))
                for lb in d.get("labels", [])
            ],  # fmt: skip
            grounds=[place(g) for g in d.get("grounds", [])],
        )


def _r(x: float) -> float:
    """A coordinate as written: 4 decimals (the grid is 1.27 mm), an int when whole."""
    y = round(float(x), 4)
    return int(y) if y == int(y) else y


def load_drawing(path: Path) -> Drawing:
    with open(path, encoding="utf-8") as f:
        return Drawing.from_json(json.load(f))


def save_drawing(d: Drawing, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(d.to_json(), indent=1, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    return path


def drawing_path(name: str) -> Path:
    """config/circuits/<name>.drawing.json (it may not exist)."""
    from varimu.config import CONFIG_DIR

    return CONFIG_DIR / "circuits" / f"{name}.drawing.json"

"""Writing KiCad schematics: a root sheet with one hierarchical sheet per section.

Symbols are placed by the caller; every pin is connected by a short wire stub and a
label at its end (a global label for a node on several sheets, else a local one), or
gets a no-connect flag. UUIDs are uuid5 of names, so writing the same circuit twice
gives the same files. The format is KiCad 9's (version 20250114), which KiCad 10 reads
and rewrites in its own on the first save.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from varimu.kicad.sexpr import N, S, Sym, Y, dumps
from varimu.kicad.symbols import LIBRARY, SYMBOLS, SymbolDef, prop, symbol_node

SCH_VERSION = 20250114
_NS = uuid.UUID("6f1c3a52-9d7e-4b8a-a2f1-5c0de0b3a9e1")
STUB_MM = 2.54
GROUND_NET = "GND"  # a pin on it gets a GND symbol


def uid(*names: object) -> str:
    return str(uuid.uuid5(_NS, "/".join(str(n) for n in names)))


@dataclass
class Placed:
    """A placed unit of a library symbol."""

    sym: SymbolDef
    ref: str
    x: float
    y: float
    unit: int = 1
    value: str = ""
    fields: dict[str, str] = field(default_factory=dict)  # hidden fields
    nets: dict[str, str | None] = field(default_factory=dict)  # pin -> net (None: no-connect)

    def pin_xy(self, number: str) -> tuple[float, float]:
        p = self.sym.pin(number)
        return self.x + p.x, self.y - p.y  # the sheet's y points down

    def unit_pins(self):
        return self.sym.units[self.unit - 1]


@dataclass
class Sheet:
    name: str
    file: str
    symbols: list[Placed] = field(default_factory=list)


def _stub(p: Placed, number: str) -> tuple[tuple[float, float], tuple[float, float], int]:
    """The wire from a pin outward, and the label angle at its end."""
    pin = p.sym.pin(number)
    x0, y0 = p.pin_xy(number)
    # The pin points into the body at `angle`; outward is the opposite direction.
    dx, dy, a = {0: (-1, 0, 180), 180: (1, 0, 0), 90: (0, 1, 270), 270: (0, -1, 90)}[pin.angle]
    return (x0, y0), (x0 + dx * STUB_MM, y0 + dy * STUB_MM), a


def _symbol_instance(p: Placed, project: str, path: str) -> list:
    (rx, ry), (vx, vy), just = p.sym.text_at()
    node = S(
        "symbol",
        S("lib_id", f"{LIBRARY}:{p.sym.name}"),
        S("at", p.x, p.y, 0),
        S("unit", p.unit),
        S("exclude_from_sim", N),
        S("in_bom", N if p.sym.kind == "power" else Y),
        S("on_board", N if p.sym.kind == "power" else Y),
        S("dnp", N),
        S("uuid", uid(path, p.ref, p.unit)),
        prop("Reference", p.ref, p.x + rx, p.y - ry, hide=p.sym.kind == "power",
             justify=just),
        prop("Value", p.value or p.sym.value, p.x + vx, p.y - vy, justify=just),
        prop("Footprint", "", p.x, p.y, hide=True),
        prop("Datasheet", "", p.x, p.y, hide=True),
        prop("Description", "", p.x, p.y, hide=True),
    )  # fmt: skip
    for k, v in p.fields.items():
        node.append(prop(k, v, p.x, p.y, hide=True))
    for pin in p.unit_pins():
        node.append(S("pin", pin.number, S("uuid", uid(path, p.ref, p.unit, pin.number))))
    node.append(
        S("instances", S("project", project, S("path", path, S("reference", p.ref),
                                                S("unit", p.unit)))))  # fmt: skip
    return node


def _label(name: str, x: float, y: float, angle: int, glob: bool, key: str) -> list:
    justify = {0: "left", 90: "left", 180: "right", 270: "right"}[angle]
    eff = S("effects", S("font", S("size", 1.27, 1.27)), S("justify", Sym(justify)))
    if not glob:
        return S("label", name, S("at", x, y, angle), eff, S("uuid", uid(key)))
    return S(
        "global_label",
        name,
        S("shape", Sym("passive")),
        S("at", x, y, angle),
        S("fields_autoplaced", Y),
        eff,
        S("uuid", uid(key)),
        S("property", "Intersheetrefs", "${INTERSHEET_REFS}", S("at", x, y, 0),
          S("effects", S("font", S("size", 1.27, 1.27)), S("hide", Y))),
    )  # fmt: skip


def _wire(a, b, key: str) -> list:
    return S(
        "wire",
        S("pts", S("xy", *a), S("xy", *b)),
        S("stroke", S("width", 0), S("type", Sym("default"))),
        S("uuid", uid(key)),
    )


def _header(sheet_uuid: str, title: str | None = None) -> list:
    node = S(
        "kicad_sch",
        S("version", SCH_VERSION),
        S("generator", "varimu"),
        S("generator_version", "1.0"),
        S("uuid", sheet_uuid),
        S("paper", "A3"),
    )
    if title:
        node.append(S("title_block", S("title", title)))
    return node


def write_project(
    directory: Path,
    project: str,
    sheets: list[Sheet],
    *,
    title: str,
    global_nets: set[str],
    library_uri: str,
) -> list[Path]:
    """Write <project>.kicad_pro, the root <project>.kicad_sch with one sheet symbol per
    sheet, the sheets, and a sym-lib-table naming the library at `library_uri`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    root_uuid = uid(project, "root")
    written = []
    root = _header(root_uuid, title)
    used = {p.sym.name: p.sym for s in sheets for p in s.symbols}
    used["GND"] = SYMBOLS["GND"]
    n_pwr = [0]
    root.append(S("lib_symbols"))
    for i, sh in enumerate(sheets):
        sheet_uuid = uid(project, "sheet", sh.name)
        x, y = 25.4 + (i % 4) * 76.2, 25.4 + (i // 4) * 50.8
        root.append(
            S(
                "sheet",
                S("at", x, y),
                S("size", 63.5, 30.48),
                S("exclude_from_sim", N),
                S("in_bom", Y),
                S("on_board", Y),
                S("dnp", N),
                S("stroke", S("width", 0), S("type", Sym("solid"))),
                S("fill", S("color", 0, 0, 0, 0.0)),
                S("uuid", sheet_uuid),
                S("property", "Sheetname", sh.name, S("at", x, y - 0.7, 0),
                  S("effects", S("font", S("size", 1.524, 1.524)),
                    S("justify", Sym("left"), Sym("bottom")))),
                S("property", "Sheetfile", sh.file, S("at", x, y + 31.2, 0),
                  S("effects", S("font", S("size", 1.524, 1.524)),
                    S("justify", Sym("left"), Sym("top")))),
                S("instances", S("project", project, S("path", f"/{root_uuid}",
                                                        S("page", str(i + 2))))),
            )
        )  # fmt: skip
        body = _header(sheet_uuid)
        names = sorted({p.sym.name for p in sh.symbols} | {"GND"})
        body.append(S("lib_symbols", *[symbol_node(used[n], f"{LIBRARY}:{n}") for n in names]))
        path = f"/{root_uuid}/{sheet_uuid}"
        grounds: list[Placed] = []
        for p in sh.symbols:
            for number, net in p.nets.items():
                key = f"{path}/{p.ref}/{p.unit}/{number}"
                a, b, angle = _stub(p, number)
                if net is None:
                    body.append(S("no_connect", S("at", *a), S("uuid", uid(key, "nc"))))
                    continue
                if net == "":  # left unconnected
                    continue
                body.append(_wire(a, b, key))
                if net == GROUND_NET:
                    n_pwr[0] += 1
                    grounds.append(Placed(SYMBOLS["GND"], f"#PWR{n_pwr[0]:03d}", *b, value="GND"))
                else:
                    body.append(_label(net, *b, angle, net in global_nets, key + "/label"))
        for p in [*sh.symbols, *grounds]:
            body.append(_symbol_instance(p, project, path))
        body.append(S("embedded_fonts", N))
        f = directory / sh.file
        f.write_text(dumps(body) + "\n", encoding="utf-8", newline="\n")
        written.append(f)
    root.append(S("sheet_instances", S("path", "/", S("page", "1"))))
    root.append(S("embedded_fonts", N))
    f = directory / f"{project}.kicad_sch"
    f.write_text(dumps(root) + "\n", encoding="utf-8", newline="\n")
    written.append(f)
    pro = directory / f"{project}.kicad_pro"
    meta = {"meta": {"filename": f"{project}.kicad_pro", "version": 1}}
    pro.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    written.append(pro)
    table = directory / "sym-lib-table"
    table.write_text(
        dumps(S("sym_lib_table", S("version", 7),
                S("lib", S("name", LIBRARY), S("type", "KiCad"), S("uri", library_uri),
                  S("options", ""), S("descr", "varimu macro parts")))) + "\n",
        encoding="utf-8",
        newline="\n",
    )  # fmt: skip
    written.append(table)
    return written

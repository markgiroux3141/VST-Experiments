"""The KiCad symbol library for the circuit format's macro parts (kicad/varimu.kicad_sym).

One table, SYMBOLS, is both the library (`write_library`) and what the importer reads
(varimu.kicad.importer): each symbol's kind, macro, pins (number -> the macro's node
order, or a device pin's role) and fields. Fields:

- Reference: the part's name in the circuit file (its element names, its tolerance
  designator and draw seed); Value: the macro's main value (`primary`), an engineering
  number ("470", "40u", "8.2n", "4k7") or a parameter key;
- capitalized fields are metadata: Source (needed for a number), Param (names the
  value: a `values` entry), Genome (its genome_bounds.yaml path), Tol (tolerance
  class, `none`, or `tube`), Unit, Notes; and per kind: Model (a device's `devices`
  key), Mid (a VR tube's inner node), Control (a switch's control), Transformer (a
  winding's core);
- lowercase fields are the macro's other params, written as in the circuit file: a
  parameter key, a structural number, or `{value: ..., source: ...}`.

Empty fields count as absent. Pin coordinates are in mm, y up (KiCad's symbol
editor); a pin's `at` is its connection point.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from varimu.kicad.sexpr import N, S, Sym, Y, dumps

LIBRARY = "varimu"
META = ("Source", "Param", "Genome", "Tol")


@dataclass(frozen=True)
class Pin:
    number: str
    name: str  # a device pin's role (p, g, k, g2, g1, a), else the number
    x: float
    y: float
    angle: int  # direction from the connection point into the body
    length: float = 2.54
    kind: str = "passive"


@dataclass(frozen=True)
class SymbolDef:
    name: str
    kind: str  # "macro" | "device" | "winding" | "core" | "coupling" | "switch" | "power"
    prefix: str  # the Reference's letters
    description: str
    units: tuple[tuple[Pin, ...], ...]  # pins per unit (one entry: a single-unit symbol)
    graphics: tuple[list, ...] = ()
    macro: str | None = None  # the circuit format's macro
    primary: str | None = None  # the macro param the Value carries
    fields: tuple[str, ...] = ()  # hidden fields in the library (empty defaults)
    value: str = ""
    order: tuple[str, ...] = ()  # pin numbers in the macro's node order (one unit)
    text: tuple[float, float, float, str] = (2.54, 1.27, -1.27, "left")  # x, y ref, y value

    def text_at(self) -> tuple[tuple[float, float], tuple[float, float], str]:
        """Where the Reference and Value go (symbol coordinates), and their justification."""
        x, yr, yv, j = self.text
        return (x, yr), (x, yv), j

    @property
    def pins(self) -> tuple[Pin, ...]:
        return tuple(p for u in self.units for p in u)

    def pin(self, number: str) -> Pin:
        for p in self.pins:
            if p.number == number:
                return p
        raise KeyError(number)


# --- Graphics --------------------------------------------------------------------------------


def _stroke(w: float = 0.254) -> list:
    return S("stroke", S("width", w), S("type", Sym("default")))


def _fill(kind: str = "none") -> list:
    return S("fill", S("type", Sym(kind)))


def poly(*pts: tuple[float, float], fill: str = "none") -> list:
    return S("polyline", S("pts", *[S("xy", x, y) for x, y in pts]), _stroke(), _fill(fill))


def rect(x0, y0, x1, y1) -> list:
    return S("rectangle", S("start", x0, y0), S("end", x1, y1), _stroke(), _fill())


def circle(x, y, r, fill: str = "none") -> list:
    return S("circle", S("center", x, y), S("radius", r), _stroke(), _fill(fill))


def arc(start, mid, end) -> list:
    return S("arc", S("start", *start), S("mid", *mid), S("end", *end), _stroke(), _fill())


def text(s: str, x: float, y: float, size: float = 1.27) -> list:
    return S("text", s, S("at", x, y, 0), S("effects", S("font", S("size", size, size))))


def _coil(top: float, bottom: float, x: float = 0.0) -> list[list]:
    """Four bumps to the right from y = top down to bottom."""
    h = (top - bottom) / 4
    return [
        arc((x, top - i * h), (x + h / 2, top - (i + 0.5) * h), (x, top - (i + 1) * h))
        for i in range(4)
    ]


def _vertical(prefix: str = "") -> tuple[Pin, Pin]:
    return (Pin(f"{prefix}1", "1", 0, 3.81, 270, 1.27), Pin(f"{prefix}2", "2", 0, -3.81, 90, 1.27))


_R_BODY = rect(-1.016, -2.54, 1.016, 2.54)
_ARROW_IN = poly((3.81, 0), (1.27, 0)), poly((2.032, 0.508), (1.27, 0), (2.032, -0.508))


def _triode(dx: float = 0.0) -> list[list]:
    return [
        circle(0, 0, 5.08),
        poly((-2.54, 2.54), (2.54, 2.54)),
        *[poly((x, 0), (x + 0.762, 0)) for x in (-2.54, -1.27, 0.0, 1.27)],
        poly((-2.54, -1.778), (-2.54, -2.54), (2.54, -2.54)),
    ]


def _diode() -> list[list]:
    return [
        poly((-1.27, 1.016), (1.27, 1.016), (0, -1.016), (-1.27, 1.016)),
        poly((-1.27, -1.016), (1.27, -1.016)),
    ]


def _rotary(n: int) -> SymbolDef:
    top = (n - 1) * 1.27
    contacts = tuple(
        Pin(str(k), str(k), 7.62, top - (k - 1) * 2.54, 180, 2.54) for k in range(1, n + 1)
    )
    marks = [circle(4.572, top - (k - 1) * 2.54, 0.508) for k in range(1, n + 1)]
    return SymbolDef(
        text=(-5.08, top + 4.064, top + 2.54, "left"),
        name=f"SW_Rotary_{n}",
        kind="switch",
        prefix="S",
        description=f"Rotary switch deck, {n} positions: contact k is the control's k-th choice "
        "(or position min + k - 1); decks with the same Control are ganged",
        units=((Pin("C", "C", -7.62, 0, 0, 2.54), *contacts),),
        graphics=(circle(-4.572, 0, 0.508), poly((-4.064, 0), (4.064, top)), *marks),
        fields=("Control",),
        value="SW",
    )


def _macro(name, macro, prefix, desc, pins, graphics, primary, extra=(), toleranced=True,
           text=(2.54, 1.27, -1.27, "left")):  # fmt: skip
    meta = META if toleranced else ("Source", "Param", "Genome")
    return SymbolDef(
        name,
        "macro",
        prefix,
        desc,
        (tuple(pins),),
        tuple(graphics),
        macro=macro,
        primary=primary,
        fields=(*meta, *extra),
        value=name,
        order=tuple(p.number for p in pins),
        text=text,
    )


def _source(name, macro, desc, mark, primary, extra):
    pins = (Pin("1", "1", 0, 5.08, 270, 2.54), Pin("2", "2", 0, -5.08, 90, 2.54))
    g = [circle(0, 0, 2.54), text("+", 0, 1.524, 1.0), *mark]
    return _macro(name, macro, "V", desc, pins, g, primary, extra, toleranced=False,
                  text=(3.302, 1.27, -1.27, "left"))  # fmt: skip


_SYMBOLS: list[SymbolDef] = [
    _macro("R", "R", "R", "Resistor (pins 1, 2)", _vertical(), [_R_BODY], "r", ("parallel",)),
    _macro(
        "C",
        "C",
        "C",
        "Capacitor (pins 1, 2)",
        (Pin("1", "1", 0, 3.81, 270, 3.048), Pin("2", "2", 0, -3.81, 90, 3.048)),
        [poly((-2.032, 0.762), (2.032, 0.762)), poly((-2.032, -0.762), (2.032, -0.762))],
        "c",
    ),
    _macro(
        "L",
        "L",
        "L",
        "Inductor (current from pin 1, the dotted end, to pin 2)",
        _vertical(),
        [*_coil(2.54, -2.54), circle(-1.27, 2.54, 0.254, "outline")],
        "l",
        toleranced=False,
    ),
    _macro(
        "Pot",
        "pot",
        "R",
        "Potentiometer: pin 1 end_a, 2 wiper, 3 end_b; at = 0 puts the wiper at pin 1",
        (
            Pin("1", "1", 0, 3.81, 270, 1.27),
            Pin("2", "2", 3.81, 0, 180, 2.54),
            Pin("3", "3", 0, -3.81, 90, 1.27),
        ),  # fmt: skip
        [_R_BODY, poly((2.032, 0.508), (1.27, 0), (2.032, -0.508))],
        "r",
        ("at", "taper_mid"),
        text=(-2.54, 1.27, -1.27, "right"),
    ),
    _macro(
        "Rheostat",
        "rheostat",
        "R",
        "Variable resistor (pins 1, 2): at = 0 is no resistance",
        _vertical(),
        [
            _R_BODY,
            poly((-2.032, -2.032), (2.032, 2.032)),
            poly((1.016, 2.032), (2.032, 2.032), (2.032, 1.016)),
        ],  # fmt: skip
        "r",
        ("at", "taper_mid"),
        text=(3.302, 1.27, -1.27, "left"),
    ),
    _macro(
        "Pot_Tapped",
        "tapped_pot",
        "R",
        "Tapped potentiometer: pin 1 end_a, 2 tap, 3 wiper, 4 end_b (at, tap: from end_a)",
        (
            Pin("1", "1", 0, 5.08, 270, 1.27),
            Pin("2", "2", -3.81, 0, 0, 2.794),
            Pin("3", "3", 3.81, 0, 180, 2.54),
            Pin("4", "4", 0, -5.08, 90, 1.27),
        ),  # fmt: skip
        [rect(-1.016, -3.81, 1.016, 3.81), poly((2.032, 0.508), (1.27, 0), (2.032, -0.508))],
        "r",
        ("at", "tap"),
        text=(-1.524, 4.064, 2.54, "right"),
    ),
    _macro(
        "T_Pad",
        "t_pad",
        "AT",
        "T attenuator: pin 1 a, 2 b, 3 common; Value is its impedance z",
        (
            Pin("1", "1", -6.35, 0, 0, 2.54),
            Pin("2", "2", 6.35, 0, 180, 2.54),
            Pin("3", "3", 0, -5.08, 90, 2.54),
        ),  # fmt: skip
        [rect(-3.81, -2.54, 3.81, 2.54), text("T", 0, 0)],
        "z",
        ("atten_db",),
        text=(-3.81, 5.08, 3.302, "left"),
    ),
    _source("V", "V", "DC voltage source: pin 1 +, 2 -", [], "v", ()),
    _source(
        "Sine",
        "sine",
        "Sine source: pin 1 +, 2 -; Value is its amplitude",
        [text("~", 0, -0.508, 1.524)],
        "amplitude_v",
        ("freq_hz", "offset_v", "phase_deg"),
    ),
    _source(
        "Mains",
        "mains",
        "A winding fed from the mains (the circuit's `mains` block): pin 1 +, 2 -; Value "
        "is its rms voltage at the rated mains",
        [text("~", 0, -0.508, 1.524), text("AC", 0, -3.81, 1.0)],
        "v_rms",
        ("phase_deg",),
    ),
    _macro(
        "Bridge",
        "bridge",
        "D",
        "Bridge rectifier: pin 1 ac_a, 2 ac_b, 3 +, 4 -; Value is the device file",
        (
            Pin("1", "1", -5.08, 0, 0, 2.54),
            Pin("2", "2", 5.08, 0, 180, 2.54),
            Pin("3", "3", 0, 5.08, 270, 2.54),
            Pin("4", "4", 0, -5.08, 90, 2.54),
        ),  # fmt: skip
        [poly((-2.54, 0), (0, 2.54), (2.54, 0), (0, -2.54), (-2.54, 0))],
        None,
        ("Model", "arm_c_f_per_area", "area", "instance", "parallel"),
        toleranced=False,
        text=(2.54, 3.81, 2.286, "left"),
    ),
    _macro(
        "VR_Tube",
        "vr_tube",
        "V",
        "Glow-discharge voltage reference: pin 1 anode, 2 cathode; Value is its operating "
        "voltage, `device` its device file (a junction diode: the slope)",
        (Pin("1", "1", 0, 5.08, 270, 2.54), Pin("2", "2", 0, -5.08, 90, 2.54)),
        [
            circle(0, 0, 2.54),
            circle(0.762, 0.762, 0.381, "outline"),
            poly((-1.27, -1.27), (1.27, -1.27)),
        ],  # fmt: skip
        "operating_v",
        ("device", "Model", "Mid", "ref_current_a", "instance"),
        toleranced=False,
        text=(3.302, 1.27, -1.27, "left"),
    ),
    _macro(
        "Speaker",
        "speaker",
        "LS",
        "Speaker in its cabinet (varimu.devices.speaker): pin 1 +, 2 -, 3 the sound "
        "pressure at the listening point (pascals as volts); Value is its component version",
        (
            Pin("1", "1", -5.08, 2.54, 0, 2.54),
            Pin("2", "2", -5.08, -2.54, 0, 2.54),
            Pin("3", "3", 6.35, 0, 180, 2.54),
        ),  # fmt: skip
        [
            rect(-2.54, -1.524, 0, 1.524),
            poly((0, 1.524), (3.81, 3.81), (3.81, -3.81), (0, -1.524), (0, 1.524)),
        ],
        "component",
        ("distance_m", "width_m", "height_m", "depth_m", "offset_x_m", "offset_y_m"),
        toleranced=False,
        text=(0, 6.35, 4.826, "left"),
    ),
]

_DEVICE_FIELDS = ("Tol", "Model", "emission", "mu", "grid_contact_v", "parallel", "area",
                  "instance", "name")  # fmt: skip


def _device(name, desc, units, graphics, value, prefix="V", text=(5.842, 1.27, -1.27, "left")):
    return SymbolDef(
        name, "device", prefix, desc, units, tuple(graphics), fields=_DEVICE_FIELDS, value=value,
        text=text,
    )  # fmt: skip


def _triode_pins(nums: tuple[str, str, str]) -> tuple[Pin, ...]:
    p, g, k = nums
    return (Pin(p, "p", 0, 7.62, 270, 5.08), Pin(g, "g", -7.62, 0, 0, 5.08),
            Pin(k, "k", 0, -7.62, 90, 5.08))  # fmt: skip


def _diode_pins(a: str, k: str) -> tuple[Pin, ...]:
    return (Pin(a, "a", 0, 3.81, 270, 2.794), Pin(k, "k", 0, -3.81, 90, 2.794))


_SYMBOLS += [
    _device(
        "Triode",
        "Triode (p, g, k); Value is the device file",
        (_triode_pins(("1", "2", "3")),),
        _triode(),
        "12AX7@1",
    ),  # fmt: skip
    _device(
        "Triode_Dual",
        "Dual triode, units A (pins 1-3) and B (6-8); each unit is one device instance",
        (_triode_pins(("1", "2", "3")), _triode_pins(("6", "7", "8"))),
        _triode(),
        "12AX7@1",
    ),
    _device(
        "Pentode",
        "Pentode (p, g2, g1, k); Value is the device file",
        (
            (
                Pin("1", "p", 0, 8.89, 270, 5.08),
                Pin("2", "g2", 8.89, 1.27, 180, 6.35),
                Pin("3", "g1", -8.89, -1.27, 0, 6.35),
                Pin("4", "k", 0, -8.89, 90, 5.08),
            ),
        ),
        [
            circle(0, 0, 6.35),
            poly((-2.54, 3.81), (2.54, 3.81)),
            *[poly((x, 1.27), (x + 0.762, 1.27)) for x in (-2.54, -1.27, 0.0, 1.27)],
            *[poly((x, -1.27), (x + 0.762, -1.27)) for x in (-2.54, -1.27, 0.0, 1.27)],
            poly((-2.54, -3.048), (-2.54, -3.81), (2.54, -3.81)),
        ],
        "6973@1",
        text=(-3.81, 8.89, 7.366, "right"),
    ),  # fmt: skip
    _device(
        "Diode",
        "Diode, vacuum or junction (a, k); Value is the device file",
        (_diode_pins("1", "2"),),
        _diode(),
        "6X4@1",
        prefix="D",
    ),  # fmt: skip
    _device(
        "Diode_Dual",
        "Dual diode (a full-wave rectifier), units A (pins 1, 2) and B (3, 4)",
        (_diode_pins("1", "2"), _diode_pins("3", "4")),
        _diode(),
        "6X4@1",
    ),
    SymbolDef(
        "Winding",
        "winding",
        "W",
        "Transformer winding: pin 1 the dotted end; Value is its label, Transformer its "
        "core's Reference; ratio (turns over the reference winding's), r, c",
        ((Pin("1", "1", 0, 3.81, 270, 1.27), Pin("2", "2", 0, -3.81, 90, 1.27)),),
        (*_coil(2.54, -2.54), circle(-1.27, 2.54, 0.254, "outline")),
        fields=("Transformer", "ratio", "r", "c"),
        value="p",
    ),
    SymbolDef(
        "Core",
        "core",
        "T",
        "Transformer core (no pins): its Reference names the transformer, whose Winding "
        "symbols name it; material, area_m2, path_m, gap_m, turns, leakage_h, "
        "interwinding ({ends: [<label>.dot, <label>.other], to: <label>.dot, c})",
        ((),),
        (poly((-0.508, 5.08), (-0.508, -5.08)), poly((0.508, 5.08), (0.508, -5.08))),
        fields=("material", "area_m2", "path_m", "gap_m", "turns", "leakage_h", "interwinding"),
        value="core",
    ),
    SymbolDef(
        "K",
        "coupling",
        "K",
        "Coupling of two inductors (no pins): `inductors` [L_a, L_b]; Value is k",
        ((),),
        (text("K", 0, 0),),
        macro="K",
        primary="k",
        fields=("Source", "Param", "Genome", "inductors"),
        value="K",
    ),
    *[_rotary(n) for n in range(2, 13)],
    SymbolDef(
        "GND",
        "power",
        "#PWR",
        "Ground: node 0",
        ((Pin("1", "GND", 0, 0, 270, 0, "power_in"),),),
        (poly((0, 0), (0, -1.27), (1.27, -1.27), (0, -2.54), (-1.27, -1.27), (0, -1.27)),),
        value="GND",
    ),
]

SYMBOLS: dict[str, SymbolDef] = {s.name: s for s in _SYMBOLS}


# --- The library file ------------------------------------------------------------------------


def _effects(hide: bool = False, size: float = 1.27, justify: str | None = None) -> list:
    e = S("effects", S("font", S("size", size, size)))
    if justify:
        e.append(S("justify", Sym(justify)))
    if hide:
        e.append(S("hide", Y))
    return e


def prop(name: str, value: str, x: float = 0, y: float = 0, angle: float = 0, *,
         hide: bool = False, justify: str | None = None) -> list:  # fmt: skip
    return S("property", name, value, S("at", x, y, angle), _effects(hide, justify=justify))


def _pin(p: Pin, hide_name: bool) -> list:
    node = S(
        "pin",
        Sym(p.kind),
        Sym("line"),
        S("at", p.x, p.y, p.angle),
        S("length", p.length),
    )
    if hide_name and p.kind == "power_in":
        node.append(S("hide", Y))
    node += [S("name", p.name, _effects()), S("number", p.number, _effects())]
    return node


def symbol_node(s: SymbolDef, lib_name: str | None = None) -> list:
    """The library entry of symbol `s` (named `lib_name`, e.g. "varimu:R" inside a
    schematic's lib_symbols)."""
    power = s.kind == "power"
    node = S("symbol", lib_name or s.name)
    if power:
        node.append(S("power"))
    node += [
        S("pin_numbers", S("hide", Y)) if s.kind != "switch" else S("pin_numbers", S("hide", N)),
        S("pin_names", S("offset", 0), S("hide", Y)),
        S("exclude_from_sim", N),
        S("in_bom", N if power else Y),
        S("on_board", N if power else Y),
        prop("Reference", s.prefix, *s.text_at()[0], hide=power, justify=s.text_at()[2]),
        prop("Value", s.value, *s.text_at()[1], justify=s.text_at()[2]),
        prop("Footprint", "", hide=True),
        prop("Datasheet", "", hide=True),
        prop("Description", s.description, hide=True),
        *[prop(f, "", hide=True) for f in s.fields],
    ]
    node.append(S("symbol", f"{s.name}_0_1", *s.graphics))
    for i, pins in enumerate(s.units, start=1):
        if pins:
            node.append(S("symbol", f"{s.name}_{i}_1", *[_pin(p, True) for p in pins]))
    node.append(S("embedded_fonts", N))
    return node


def library_text() -> str:
    lib = S(
        "kicad_symbol_lib",
        S("version", 20241209),
        S("generator", "varimu"),
        S("generator_version", "1.0"),
        *[symbol_node(s) for s in _SYMBOLS],
    )
    return dumps(lib) + "\n"


def write_library(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(library_text(), encoding="utf-8", newline="\n")
    return path

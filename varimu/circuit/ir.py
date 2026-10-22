"""Circuit IR: one typed description of a circuit, for both simulation engines.

`varimu.circuit.netlist.build()` makes an IR. `varimu.circuit.spice` turns it
into ngspice netlist text, and its JSON form (`CircuitIR.to_json()`) is what
the Rust engine reads (crates/circuitsim/src/ir.rs, field-for-field the same;
round-trip tests keep them in step). Bump IR_VERSION in both on any
incompatible change.

Conventions:
- nodes are strings, GROUND = "0";
- element and model names are the SPICE names (R103, XVA, LT101_sa), unique
  ignoring case, and an element name starts with its SPICE letter;
- values are SI with the unit in the field name (r_ohm, c_f, l_h, dc_v);
- pots, pads and switch positions are already resolved into plain elements;
- device models are the varimu.devices dataclasses themselves, with every
  parameter, so the Rust side never reads the YAML files;
- mutual inductance is one Coupling (SPICE K) per inductor pair. The linear
  engine groups connected inductors and stamps the inductance matrix
  M_ij = k_ij sqrt(L_i L_j) directly (docs/CIRCUIT_SIM_PLAN.md, M1 notes);
- a SineSource is SPICE's SIN source (mains, Phase 3): the DC operating
  point takes it at its t = 0 value, as ngspice's transient op does;
- a transformer on a nonlinear core (Phase 2) is Windings on a core node,
  whose voltage is the flux density B (1 V = 1 mT, varimu.devices.core),
  plus a MagneticCore device from that node to ground (or a resistor, in
  the core's linear limit). See Winding.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from varimu.devices.core import MagneticCore
from varimu.devices.diode import JunctionDiode, VacuumDiode
from varimu.devices.pentode import KorenPentode, Pentode
from varimu.devices.triode import GridCurrent, KorenTriode, Triode, VariMuTriode

IR_VERSION = 3  # 2: Winding, MagneticCore (Phase 2); 3: SineSource (Phase 3, mains)
GROUND = "0"


class IRError(ValueError):
    pass


# --- Elements ------------------------------------------------------------------------


@dataclass(frozen=True)
class Resistor:
    name: str
    a: str
    b: str
    r_ohm: float


@dataclass(frozen=True)
class Capacitor:
    name: str
    a: str
    b: str
    c_f: float


@dataclass(frozen=True)
class Inductor:
    """Current flows from a to b; a is the dotted end for Coupling."""

    name: str
    a: str
    b: str
    l_h: float


@dataclass(frozen=True)
class Coupling:
    """Coupling coefficient k between two inductors, by element name (SPICE K)."""

    name: str
    l_a: str
    l_b: str
    k: float


@dataclass(frozen=True)
class VoltageSource:
    """Ideal DC source: V(pos) - V(neg) = dc_v."""

    name: str
    pos: str
    neg: str
    dc_v: float


@dataclass(frozen=True)
class SineSource:
    """V(pos) - V(neg) = offset_v + amplitude_v sin(2 pi freq_hz t + phase_deg).

    SPICE's SIN(VO VA FREQ 0 0 PHASE). The DC operating point that starts a
    run takes the value at t = 0 (offset + amplitude sin(phase)), so phase 90
    starts at the peak with no jump.
    """

    name: str
    pos: str
    neg: str
    offset_v: float
    amplitude_v: float
    freq_hz: float
    phase_deg: float

    def at(self, t: float) -> float:
        return self.offset_v + self.amplitude_v * math.sin(
            2 * math.pi * self.freq_hz * t + math.radians(self.phase_deg)
        )


@dataclass(frozen=True)
class Winding:
    """`turns` turns on the core whose node is `core`, of cross-section `area_m2`.

    A branch from a to b: v(a) - v(b) = turns * area_m2 * dB/dt, with B the
    core node's voltage times varimu.devices.core.TESLA_PER_V, and its
    current (a to b, through the winding) adds turns * i to the core's
    magnetomotive force: the core node's KCL is sum(turns * i) = the
    current drawn from it (by a MagneticCore, a gap, eddy loss). Winding
    resistance and leakage are separate elements in series. The dotted end
    is a.
    """

    name: str
    a: str
    b: str
    core: str
    turns: float
    area_m2: float


@dataclass(frozen=True)
class Device:
    """An instance of a device model; nodes follow the model's PINS order."""

    name: str
    model: str
    nodes: tuple[str, ...]


Element = Resistor | Capacitor | Inductor | Coupling | VoltageSource | SineSource | Winding | Device
DeviceModel = Triode | Pentode | JunctionDiode | VacuumDiode | MagneticCore

PINS: dict[type, tuple[str, ...]] = {
    Triode: ("p", "g", "k"),
    Pentode: ("p", "g2", "g1", "k"),
    JunctionDiode: ("a", "k"),
    VacuumDiode: ("a", "k"),
    MagneticCore: ("b", "ref"),
}

_PREFIX = {
    Resistor: "R",
    Capacitor: "C",
    Inductor: "L",
    Coupling: "K",
    VoltageSource: "V",
    SineSource: "V",
    Winding: "L",
}


def instance_prefix(model: DeviceModel) -> str:
    """SPICE letter of an instance: D for the built-in diode, X for subcircuits."""
    return "D" if isinstance(model, JunctionDiode) else "X"


def element_nodes(el: Element) -> tuple[str, ...]:
    if isinstance(el, Resistor | Capacitor | Inductor):
        return (el.a, el.b)
    if isinstance(el, VoltageSource | SineSource):
        return (el.pos, el.neg)
    if isinstance(el, Winding):
        return (el.a, el.b, el.core)
    if isinstance(el, Device):
        return el.nodes
    return ()


@dataclass(frozen=True)
class VoltageProbe:
    """Node voltage relative to ground."""

    node: str

    @property
    def spice(self) -> str:
        return f"v({self.node})"


@dataclass(frozen=True)
class Section:
    """A titled group of elements (one stage). Only for readability."""

    title: str
    elements: tuple[Element, ...]


# --- The circuit ------------------------------------------------------------------------


@dataclass(frozen=True)
class CircuitIR:
    title: str
    input_node: str  # driven by the audio input, relative to ground
    probes: tuple[VoltageProbe, ...]
    models: tuple[DeviceModel, ...]
    sections: tuple[Section, ...]
    version: int = IR_VERSION

    def __post_init__(self):
        self.validate()

    def elements(self) -> Iterator[Element]:
        for s in self.sections:
            yield from s.elements

    def model(self, name: str) -> DeviceModel:
        for m in self.models:
            if m.name == name:
                return m
        raise KeyError(name)

    def nodes(self) -> tuple[str, ...]:
        """Every non-ground node, in order of first appearance."""
        seen: dict[str, None] = {}
        for el in self.elements():
            seen.update((n, None) for n in element_nodes(el) if n != GROUND)
        return tuple(seen)

    def without_devices(self) -> CircuitIR:
        """The linear part: every device instance (tube, diode) and model removed.

        Probes on nodes that only devices connected are dropped.
        """
        sections = tuple(
            Section(s.title, tuple(e for e in s.elements if not isinstance(e, Device)))
            for s in self.sections
        )
        nodes = {n for s in sections for e in s.elements for n in element_nodes(e)}
        probes = tuple(p for p in self.probes if p.node in nodes)
        return dataclasses.replace(self, models=(), sections=sections, probes=probes)

    def validate(self) -> None:
        """The same checks as CircuitIr::validate() in Rust. Raises IRError."""
        if self.version != IR_VERSION:
            raise IRError(f"version {self.version} (this code reads {IR_VERSION})")
        models: dict[str, DeviceModel] = {}
        for m in self.models:
            if m.name in models:
                raise IRError(f"duplicate model {m.name}")
            models[m.name] = m
            _validate_model(m)

        names: set[str] = set()
        inductors: set[str] = set()
        nodes: set[str] = set()
        for el in self.elements():
            if el.name.upper() in names:
                raise IRError(f"duplicate element name {el.name}")
            names.add(el.name.upper())
            if isinstance(el, Resistor):
                _positive(f"{el.name}.r_ohm", el.r_ohm)
            elif isinstance(el, Capacitor):
                _positive(f"{el.name}.c_f", el.c_f)
            elif isinstance(el, Inductor):
                _positive(f"{el.name}.l_h", el.l_h)
                inductors.add(el.name)
            elif isinstance(el, Coupling):
                if not (math.isfinite(el.k) and el.k != 0 and abs(el.k) <= 1):
                    raise IRError(f"{el.name}.k = {el.k} must be in [-1, 0) or (0, 1]")
            elif isinstance(el, VoltageSource):
                _finite(f"{el.name}.dc_v", el.dc_v)
            elif isinstance(el, SineSource):
                _finite(f"{el.name}.offset_v", el.offset_v)
                _finite(f"{el.name}.amplitude_v", el.amplitude_v)
                _positive(f"{el.name}.freq_hz", el.freq_hz)
                _finite(f"{el.name}.phase_deg", el.phase_deg)
            elif isinstance(el, Winding):
                _positive(f"{el.name}.turns", el.turns)
                _positive(f"{el.name}.area_m2", el.area_m2)
                if el.core == GROUND or el.core in (el.a, el.b):
                    raise IRError(f"{el.name}: core node {el.core} must be its own node")
            elif isinstance(el, Device):
                if el.model not in models:
                    raise IRError(f"{el.name}: unknown model {el.model}")
                pins = PINS[type(models[el.model])]
                if len(el.nodes) != len(pins):
                    raise IRError(
                        f"{el.name}: {len(el.nodes)} nodes, model {el.model} has pins {pins}"
                    )
            prefix = (
                instance_prefix(models[el.model]) if isinstance(el, Device) else _PREFIX[type(el)]
            )
            if not el.name.upper().startswith(prefix):
                raise IRError(f"element {el.name} must start with {prefix}")
            el_nodes = element_nodes(el)
            if len(el_nodes) == 2 and el_nodes[0] == el_nodes[1]:
                raise IRError(f"{el.name}: both ends on node {el_nodes[0]}")
            for n in el_nodes:
                if not n or any(c.isspace() for c in n):
                    raise IRError(f"{el.name}: bad node name {n!r}")
                nodes.add(n)
        for el in self.elements():
            if isinstance(el, Coupling):
                for ind in (el.l_a, el.l_b):
                    if ind not in inductors:
                        raise IRError(f"{el.name}: {ind} is not an inductor")
                if el.l_a == el.l_b:
                    raise IRError(f"{el.name}: couples {el.l_a} to itself")

        if GROUND not in nodes:
            raise IRError('no element connects to ground (node "0")')
        if self.input_node not in nodes:
            raise IRError(f"input node {self.input_node} is not connected")
        for p in self.probes:
            if p.node not in nodes:
                raise IRError(f"probe node {p.node} is not connected")

    # --- JSON ---

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "title": self.title,
            "input_node": self.input_node,
            "probes": [_encode(p) for p in self.probes],
            "models": [_encode(m) for m in self.models],
            "sections": [_encode(s) for s in self.sections],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=1, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CircuitIR:
        _check_keys(
            "circuit", d, {"version", "title", "input_node", "probes", "models", "sections"}
        )
        if d["version"] != IR_VERSION:
            raise IRError(f"version {d['version']} (this code reads {IR_VERSION})")
        return cls(
            title=d["title"],
            input_node=d["input_node"],
            probes=tuple(_decode(p, _PROBE_KINDS) for p in d["probes"]),
            models=tuple(_decode_model(m) for m in d["models"]),
            sections=tuple(
                _fields(
                    Section,
                    s,
                    tagged=False,
                    elements=lambda els: tuple(_decode(e, _ELEMENT_KINDS) for e in els),
                )
                for s in d["sections"]
            ),
            version=d["version"],
        )

    @classmethod
    def from_json(cls, text: str) -> CircuitIR:
        return cls.from_dict(json.loads(text))


def _positive(what: str, x: float) -> None:
    if not (math.isfinite(x) and x > 0):
        raise IRError(f"{what} = {x} must be finite and > 0")


def _finite(what: str, x: float) -> None:
    if not math.isfinite(x):
        raise IRError(f"{what} = {x} must be finite")


def _validate_model(m: DeviceModel) -> None:
    def nonneg(what, x):
        if not (math.isfinite(x) and x >= 0):
            raise IRError(f"{m.name}.{what} = {x} must be >= 0")

    values: list[tuple[str, float]] = []
    if isinstance(m, Triode):
        pl = m.plate
        if isinstance(pl, VariMuTriode):
            values += [("mus[]", x) for x in pl.mus] + [("weights[]", x) for x in pl.weights]
        else:
            values.append(("mu", pl.mu))
        values += [("ex", pl.ex), ("kg1", pl.kg1), ("kp", pl.kp), ("kvb", pl.kvb)]
        if m.grid is not None:
            values += [("grid.perveance", m.grid.perveance), ("grid.smooth_v", m.grid.smooth_v)]
            _finite(f"{m.name}.grid.contact_v", m.grid.contact_v)
        for what in ("c_gk", "c_gp", "c_pk"):
            nonneg(what, getattr(m, what))
    elif isinstance(m, Pentode):
        values += [(f.name, getattr(m.model, f.name)) for f in dataclasses.fields(m.model)]
        if m.grid is not None:
            values += [("grid.perveance", m.grid.perveance), ("grid.smooth_v", m.grid.smooth_v)]
            _finite(f"{m.name}.grid.contact_v", m.grid.contact_v)
        for what in ("c_g1k", "c_g1p", "c_pk"):
            nonneg(what, getattr(m, what))
    elif isinstance(m, JunctionDiode):
        values += [("is_a", m.is_a), ("n", m.n)]
        nonneg("rs_ohm", m.rs_ohm)
    elif isinstance(m, VacuumDiode):
        values += [("perveance", m.perveance), ("smooth_v", m.smooth_v)]
    elif isinstance(m, MagneticCore):
        problems = m.validate()
        if problems:
            raise IRError(f"{m.name}: " + "; ".join(problems))
    else:
        raise IRError(f"unknown device model type {type(m).__name__}")
    for what, x in values:
        _positive(f"{m.name}.{what}", x)


# --- JSON codec ---------------------------------------------------------------------
# Every dataclass becomes an object of its fields; the ones that sit in a union
# also get a "kind" tag. Numbers are always written as floats, so the JSON
# matches what Rust's f64 fields write back.

_ELEMENT_KINDS = {
    "resistor": Resistor,
    "capacitor": Capacitor,
    "inductor": Inductor,
    "coupling": Coupling,
    "voltage_source": VoltageSource,
    "sine_source": SineSource,
    "winding": Winding,
    "device": Device,
}
_MODEL_KINDS = {
    "triode": Triode,
    "pentode": Pentode,
    "junction_diode": JunctionDiode,
    "vacuum_diode": VacuumDiode,
    "magnetic_core": MagneticCore,
}
_PLATE_KINDS = {"koren": KorenTriode, "varimu": VariMuTriode}
_PROBE_KINDS = {"voltage": VoltageProbe}
_KIND_OF = {
    cls: kind
    for table in (_ELEMENT_KINDS, _MODEL_KINDS, _PLATE_KINDS, _PROBE_KINDS)
    for kind, cls in table.items()
}


def _encode(x: Any) -> Any:
    if dataclasses.is_dataclass(x):
        d = {"kind": _KIND_OF[type(x)]} if type(x) in _KIND_OF else {}
        d.update({f.name: _encode(getattr(x, f.name)) for f in dataclasses.fields(x)})
        return d
    if isinstance(x, tuple | list):
        return [_encode(v) for v in x]
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return x
    if isinstance(x, int | float):
        return float(x)
    raise IRError(f"can't encode {type(x).__name__} in the IR")


def model_to_dict(m: DeviceModel) -> dict[str, Any]:
    """A device model as it appears in the IR's "models" list."""
    return _encode(m)


def _check_keys(what: str, d: dict, expected: set[str]) -> None:
    if set(d) != expected:
        extra, missing = sorted(set(d) - expected), sorted(expected - set(d))
        raise IRError(f"{what}: unknown fields {extra}, missing fields {missing}")


def _fields(cls, d: dict, tagged: bool, **nested) -> Any:
    names = {f.name for f in dataclasses.fields(cls)}
    _check_keys(cls.__name__, d, names | ({"kind"} if tagged else set()))
    kw = {}
    for n in names:
        v = d[n]
        if n in nested:
            v = nested[n](v)
        elif isinstance(v, list):
            v = tuple(v)
        kw[n] = v
    return cls(**kw)


def _decode(d: dict, kinds: dict[str, type]) -> Any:
    cls = kinds.get(d.get("kind"))
    if cls is None:
        raise IRError(f"unknown kind {d.get('kind')!r} (expected one of {sorted(kinds)})")
    return _fields(cls, d, tagged=True)


def _decode_model(d: dict) -> DeviceModel:
    cls = _MODEL_KINDS.get(d.get("kind"))
    if cls is Triode:
        return _fields(
            Triode,
            d,
            tagged=True,
            plate=lambda p: _decode(p, _PLATE_KINDS),
            grid=lambda g: None if g is None else _fields(GridCurrent, g, tagged=False),
        )
    if cls is Pentode:
        return _fields(
            Pentode,
            d,
            tagged=True,
            model=lambda p: _fields(KorenPentode, p, tagged=False),
            grid=lambda g: None if g is None else _fields(GridCurrent, g, tagged=False),
        )
    return _decode(d, _MODEL_KINDS)

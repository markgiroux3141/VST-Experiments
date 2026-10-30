"""Circuit file -> circuit IR (+ SPICE text): the generic builder (device builder, B1).

`build(spec, overrides)` resolves the parameters (varimu.circuit.spec), adds
the derived values, makes the device model instances (`devices`, with their
per-instance draws), expands every part of every section with the parts
library (varimu.circuit.parts), applies the tolerance draws and returns a
Circuit: the IR (both engines' input) and, for linear cores, its SPICE text.

A part is `NAME: {<macro>: <connection>, param: value, ...}`. NAME is its
element name (or the stem of its elements' names) and its tolerance
designator. A param is a parameter key (a string), `{value, source}` inline,
or a bare number; bare numbers only where a param is structural (turns ratios
of windings, phases, positions, counts), never for a physical value. Every
part may also carry `tolerance: none` (no draw: not a physical part of the
unit, e.g. a source impedance or a numerical leak) and `source` / `notes`.

Macro parts (connection; params, * = required):

    R           [a, b]; r*, parallel (n equal resistors: r / n)
    C           [a, b]; c*
    L           [a, b]; l*            (current a -> b; a is the dotted end)
    K           [L_a, L_b] (inductor names); k*
    V           [pos, neg]; v*
    sine        [pos, neg]; amplitude_v*, freq_hz*, offset_v, phase_deg
    mains       [pos, neg]; v_rms* (at the rated mains), phase_deg  (the file's `mains`)
    device      [pins...] (the model's pin order); model* (a `devices` key)
    pot         [end_a, wiper, end_b]; r*, at* (0 = wiper at end_a), taper_mid (an
                audio taper: the track's fraction at half rotation; default linear)
    rheostat    [a, b]; r*, at* (0 = no resistance), taper_mid
    tapped_pot  [end_a, tap, wiper, end_b]; r*, at*, tap* (fractions from end_a)
    t_pad       [a, b, common]; z*, atten_db*
    switch      <control key>; parts* (sub-parts, each with `in: [positions]` or always)
    transformer {label: {nodes: [dot, other], ratio, r, c}} (each winding has ratio x
                turns; ratio 1 = the reference winding); core* {material, area_m2,
                path_m, gap_m}, turns*, leakage_h* (referred to the reference winding),
                interwinding {ends: [a, b], to, c}
    bridge      [ac_a, ac_b, plus, minus]; model*, arm_c_f_per_area, area
    vr_tube     [anode, mid, cathode]; model*, operating_v*, ref_current_a*
    speaker     [plus, minus, out]; component* (a speaker component version, NAME@N, or
                a parameter naming one), distance_m* (the listening point, on axis), the
                cabinet: width_m*, height_m*, depth_m* (0: a flat baffle), offset_x_m,
                offset_y_m (the driver's centre from the baffle's): the driver between
                plus and minus, the sound pressure at the listening point on `out`
                (pascals as volts; varimu.devices.speaker)

R, C, pot, rheostat, tapped_pot and t_pad parts take their tolerance draw (by NAME, in
the file's tolerance classes); a switch's sub-parts take their own.

A `devices` entry: {device* (a device file, or a parameter naming one),
name (default <device>_<key>), instance (false: the device file's model as
is), tolerance (tube: emission / mu draws by the key as designator), parallel,
emission, mu, grid_contact_v, area}. Models are in `devices` order, then the
transformer cores in order of appearance.

Circuit-specific macros: `register()` adds one (a module that a circuit file
names under `derived` can register its macros on import).

Noise (device builder B5; the file's `noise` block, or `build(..., noise=)`): each part's
noise elements follow its own. Every Resistor of an R, pot, rheostat, tapped_pot or t_pad
part and a transformer's winding resistances get a NoiseCurrent `IN_<name>` (4kT/R at the
block's temperature_k), except parts whose value's source is `numerical:` (a leak for the
solver, not a part) and resistors on a core node (a gap or core loss: magnetic, not
electrical); other macros' internals (mains, bridge, vr_tube, speaker) get none. Every
triode or pentode instance of a `device` part gets a TubeNoise `BN_<name>` (shot_k from
varimu.devices.noise, a pentode's partition factor, flicker_v2 over its `parallel` count:
independent cathodes average).

Heated cathodes (device builder B6; the file's `heaters` block, or `build(..., heaters=)`):
every triode, pentode and vacuum diode instance of a `device` part gets a HeatedCathode
`BH_<name>` after its noise (its emission from config/cathodes.yaml's heater ratings, times
its `parallel` count); the IR's `heaters` block has the oxide constants and the heater
ratio (the mains setting over the rated mains; 1 without a `mains` block).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from varimu.circuit import parts, spice
from varimu.circuit.ir import (
    PINS,
    Capacitor,
    CircuitIR,
    Control,
    Coupling,
    Device,
    DeviceModel,
    Element,
    HeatedCathode,
    HeaterSpec,
    Inductor,
    NoiseCurrent,
    NoiseSpec,
    Resistor,
    Section,
    SineSource,
    TubeNoise,
    VoltageProbe,
    VoltageSource,
    Winding,
)
from varimu.circuit.spec import CircuitSpec, resolve
from varimu.config import ConfigError, load_sim_settings
from varimu.devices import cathode as cathode_mod
from varimu.devices import noise as noise_mod
from varimu.devices import versions
from varimu.devices.core import MagneticCore
from varimu.devices.diode import JunctionDiode, VacuumDiode
from varimu.devices.library import load_device, load_speaker
from varimu.devices.pentode import Pentode
from varimu.devices.speaker import Cabinet
from varimu.devices.table import GRIDS
from varimu.devices.triode import Triode

CORE_MODES = ("ja", "linear")
_REQUIRED = object()
_PART_KEYS = {"tolerance", "source", "notes"}  # any part may carry these


# --- Parameters ----------------------------------------------------------------------------


@dataclass
class Context:
    """One build: the spec, the resolved parameters plus derived values, the device
    models, and what the parts used."""

    spec: CircuitSpec
    q: dict[str, Any]
    cores: str
    tolerance: parts.Tolerance | None
    models: dict[str, DeviceModel] = field(default_factory=dict)  # devices key -> model
    core_models: list[MagneticCore] = field(default_factory=list)
    used_devices: set[str] = field(default_factory=set)
    designators: set[str] = field(default_factory=set)
    missing_class: set[str] = field(default_factory=set)
    section_tolerance: str | None = None  # the current section's `tolerance`
    mains_sines: list[str] = field(default_factory=list)  # the mains macro's sources
    noise: Noise | None = None  # noise sources on (B5)
    parallel: dict[str, int] = field(default_factory=dict)  # model name -> `parallel`
    types: dict[str, str] = field(default_factory=dict)  # model name -> its device's name
    heaters: str | None = None  # heated cathodes (B6): "warm" | "cold" start, None: off

    def fail(self, where: str, msg: str) -> ConfigError:
        return ConfigError(f"{self.spec.path}: {where}: {msg}")

    def ref(self, where: str, key: str) -> Any:
        if key in self.q:
            return self.q[key]
        if key in self.spec.device_params:  # null: the device file's value
            return None
        raise self.fail(where, f"unknown parameter {key!r}")

    def physical(self, where: str, x: Any) -> Any:
        """A physical value: a parameter key or {value, source}; never a bare number."""
        if isinstance(x, str):
            return self.ref(where, x)
        if isinstance(x, Mapping) and "value" in x:
            if not str(x.get("source", "")).strip():
                raise self.fail(where, "an inline value needs a `source`")
            return x["value"]
        raise self.fail(where, f"{x!r}: give a parameter key or {{value, source}}")

    def number(self, where: str, x: Any) -> Any:
        """A structural number (a ratio, phase, position, count) or a physical value."""
        if isinstance(x, int | float) and not isinstance(x, bool):
            return x
        return self.physical(where, x)

    def count(self, where: str, x: Any) -> int:
        v = self.number(where, x)
        if int(v) != v or v < 1:
            raise self.fail(where, f"{v} is not a count")
        return int(v)

    def text(self, where: str, x: Any) -> str:
        """A name (a device file, a material): a parameter holding it, or the name."""
        if not isinstance(x, str):
            raise self.fail(where, f"{x!r} is not a name")
        return self.q[x] if x in self.q else x

    def model(self, where: str, key: Any) -> DeviceModel:
        if key not in self.models:
            raise self.fail(where, f"unknown device {key!r} (not in `devices`)")
        self.used_devices.add(key)
        return self.models[key]


@dataclass(frozen=True)
class Noise:
    """A build's noise (B5): the seed, the resistors' temperature, K_f, the mains wander's
    rms."""

    seed: int
    temperature_k: float
    flicker_v2: float
    mains_rms: float


# Parts whose resistors are resistors (their noise), and the param holding their value.
_NOISY = {
    "R": "r", "pot": "r", "rheostat": "r", "tapped_pot": "r", "t_pad": "z", "transformer": None,
}  # fmt: skip


def _numerical(ctx: Context, x: Any) -> bool:
    """Whether a part's value `x` (a key or {value, source}) is sourced `numerical:`."""
    if isinstance(x, str):
        for table in (ctx.spec.values, ctx.spec.controls, ctx.spec.device_params):
            if x in table:
                return str(table[x].get("source", "")).strip().startswith("numerical")
        return False
    if isinstance(x, Mapping):
        return str(x.get("source", "")).strip().startswith("numerical")
    return False


def _noise_elements(ctx: Context, kind: str, entry: Mapping, els: list[Element]) -> list[Element]:
    """A part's noise elements (the module docstring says which)."""
    nz = ctx.noise
    out: list[Element] = []
    if kind in _NOISY:
        key = _NOISY[kind]
        if key is not None and _numerical(ctx, entry.get(key)):
            return out
        cores = {e.core for e in els if isinstance(e, Winding)}
        for e in els:
            if isinstance(e, Resistor) and e.a not in cores and e.b not in cores:
                psd = 4.0 * noise_mod.K_B * nz.temperature_k / e.r_ohm
                out.append(NoiseCurrent(f"IN_{e.name}", e.a, e.b, psd))
    elif kind == "device":
        by_name = {m.name: m for m in ctx.models.values()}
        for e in els:
            m = by_name.get(e.model) if isinstance(e, Device) else None
            if isinstance(m, Triode | Pentode):
                out.append(
                    TubeNoise(
                        f"BN_{e.name}",
                        e.name,
                        noise_mod.shot_k(),
                        noise_mod.PARTITION if isinstance(m, Pentode) else 0.0,
                        nz.flicker_v2 / ctx.parallel.get(m.name, 1),
                    )
                )
    return out


# --- Macro parts --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    kind: str  # "physical" | "number" | "count" | "device" | "raw"
    default: Any = _REQUIRED


@dataclass(frozen=True)
class Macro:
    """How a macro part reads: its connection (n_nodes nodes, or None: the macro reads
    the connection itself), its params, and the expansion into elements."""

    expand: Callable[[Context, str, Any, dict[str, Any]], list[Element]]
    n_nodes: int | None
    params: dict[str, Param]
    toleranced: bool = False


MACROS: dict[str, Macro] = {}


def register(name: str, macro: Macro) -> None:
    if name in MACROS:
        raise ValueError(f"macro {name!r} already registered")
    MACROS[name] = macro


def _resolve_params(ctx: Context, where: str, macro: Macro, entry: Mapping) -> dict[str, Any]:
    out = {}
    for k, prm in macro.params.items():
        if k not in entry:
            if prm.default is _REQUIRED:
                raise ctx.fail(where, f"needs `{k}`")
            out[k] = prm.default
            continue
        x, w = entry[k], f"{where}.{k}"
        if prm.kind == "physical":
            out[k] = ctx.physical(w, x)
        elif prm.kind == "number":
            out[k] = ctx.number(w, x)
        elif prm.kind == "count":
            out[k] = ctx.count(w, x)
        elif prm.kind == "device":
            out[k] = ctx.model(w, x)
        else:
            out[k] = x
    return out


def expand_part(ctx: Context, name: str, entry: Mapping, *, extra=()) -> list[Element]:
    """The elements of part `name`, tolerance draw applied."""
    if not isinstance(entry, Mapping):
        raise ctx.fail(name, "a part is a mapping {<macro>: <connection>, ...}")
    kinds = [k for k in entry if k in MACROS]
    if len(kinds) != 1:
        raise ctx.fail(name, f"needs exactly one macro of {sorted(MACROS)}, has {kinds}")
    kind = kinds[0]
    macro = MACROS[kind]
    unknown = set(entry) - {kind} - set(macro.params) - _PART_KEYS - set(extra)
    if unknown:
        raise ctx.fail(name, f"{kind}: unknown keys {sorted(unknown)}")
    conn = entry[kind]
    if macro.n_nodes is not None:
        if not isinstance(conn, list) or len(conn) != macro.n_nodes:
            raise ctx.fail(name, f"{kind} takes {macro.n_nodes} nodes, got {conn!r}")
        conn = [str(n) for n in conn]
    els = macro.expand(ctx, name, conn, _resolve_params(ctx, name, macro, entry))
    tol = entry.get("tolerance", ctx.section_tolerance)
    if tol not in (None, "none"):
        raise ctx.fail(name, f"tolerance: {tol!r} (a part's class is in the tolerance block)")
    if macro.toleranced and ctx.tolerance is not None and tol != "none":
        ctx.designators.add(name)
        try:
            els = ctx.tolerance.apply(els, name)
        except KeyError as e:
            ctx.missing_class.update(e.args[0])
    if ctx.noise is not None:
        els = els + _noise_elements(ctx, kind, entry, els)
    if ctx.heaters is not None and kind == "device":
        els = els + _heated(ctx, els)
    return els


def _heated(ctx: Context, els: list[Element]) -> list[Element]:
    """A `device` part's heated cathodes (B6)."""
    ox, tubes = cathode_mod.load_cathodes()
    by_name = {m.name: m for m in ctx.models.values()}
    out: list[Element] = []
    for e in els:
        m = by_name.get(e.model) if isinstance(e, Device) else None
        if not isinstance(m, Triode | Pentode | VacuumDiode):
            continue
        kind = ctx.types.get(m.name, m.name)
        if kind not in tubes:
            raise ctx.fail(e.name, f"no heater rating for {kind} in config/cathodes.yaml")
        is0 = cathode_mod.instance_is0_a(ox, tubes[kind], ctx.parallel.get(m.name, 1))
        out.append(HeatedCathode(f"BH_{e.name}", e.name, is0))
    return out


def _nodes_device(ctx: Context, name: str, conn: Any, a: dict) -> list[Element]:
    model = a["model"]
    pins = PINS[type(model)]
    if not isinstance(conn, list) or len(conn) != len(pins):
        raise ctx.fail(name, f"device {model.name} has pins {pins}, got {conn!r}")
    return [Device(name, model.name, tuple(str(n) for n in conn))]


def _mains(ctx: Context, name: str, conn: list[str], a: dict) -> list[Element]:
    m = ctx.spec.mains
    if not m:
        raise ctx.fail(name, "a mains part needs the file's `mains` block")
    w = "mains"
    ctx.mains_sines.append(name)
    return [
        parts.mains_sine(
            name,
            *conn,
            v_rms=a["v_rms"],
            mains_v_rms=ctx.ref(w, m["v_rms"]),
            rated_mains_v_rms=ctx.physical(f"{w}.rated_v_rms", m["rated_v_rms"]),
            mains_hz=ctx.ref(w, m["hz"]),
            phase_deg=a["phase_deg"],
        )
    ]


def _switch(ctx: Context, name: str, conn: Any, a: dict) -> list[Element]:
    if not isinstance(conn, str) or conn not in ctx.spec.controls:
        raise ctx.fail(name, f"switch: {conn!r} is not a control")
    position = int(ctx.ref(name, conn))
    els: list[Element] = []
    for sub, entry in (a["parts"] or {}).items():
        where = f"{name}.{sub}"
        positions = entry.get("in") if isinstance(entry, Mapping) else None
        if positions is not None and not isinstance(positions, list):
            raise ctx.fail(where, "`in` is a list of positions")
        part = expand_part(ctx, sub, entry, extra=("in",))
        if positions is None or position in positions:
            els += part
    return els


def _transformer(ctx: Context, name: str, conn: Any, a: dict) -> list[Element]:
    windings, core = transformer_spec(ctx, name, conn, a)
    iw, c_iw = None, 0.0
    if a["interwinding"] is not None:
        d = a["interwinding"]
        iw = ((str(d["ends"][0]), str(d["ends"][1])), str(d["to"]))
        c_iw = ctx.physical(f"{name}.interwinding.c", d["c"])
    els, model = parts.transformer(
        name,
        windings,
        core,
        turns=a["turns"],
        leakage_h=a["leakage_h"],
        interwinding=iw,
        c_interwinding_f=c_iw,
        cores=ctx.cores,
    )
    if ctx.cores != "linear":
        ctx.core_models.append(model)
    return els


def transformer_spec(
    ctx: Context, name: str, conn: Any, a: dict
) -> tuple[list[parts.WindingSpec], parts.CoreSpec]:
    if not isinstance(conn, Mapping) or not conn:
        raise ctx.fail(name, "transformer: a mapping of windings {label: {nodes, ...}}")
    windings = []
    for label, w in conn.items():
        where = f"{name}.{label}"
        unknown = set(w) - {"nodes", "ratio", "r", "c"}
        if unknown or len(w.get("nodes", ())) != 2:
            raise ctx.fail(where, "a winding is {nodes: [dot, other], ratio, r, c}")
        windings.append(
            parts.WindingSpec(
                str(label),
                str(w["nodes"][0]),
                str(w["nodes"][1]),
                ctx.number(f"{where}.ratio", w.get("ratio", 1.0)),
                ctx.physical(f"{where}.r", w["r"]) if "r" in w else 0.0,
                ctx.physical(f"{where}.c", w["c"]) if "c" in w else 0.0,
            )
        )
    c = a["core"]
    if not isinstance(c, Mapping) or set(c) != {"material", "area_m2", "path_m", "gap_m"}:
        raise ctx.fail(name, "core: {material, area_m2, path_m, gap_m}")
    core = parts.CoreSpec(
        material=ctx.text(f"{name}.core.material", c["material"]),
        area_m2=ctx.physical(f"{name}.core.area_m2", c["area_m2"]),
        path_m=ctx.physical(f"{name}.core.path_m", c["path_m"]),
        gap_m=ctx.physical(f"{name}.core.gap_m", c["gap_m"]),
    )
    return windings, core


def _bridge(ctx: Context, name: str, conn: list[str], a: dict) -> list[Element]:
    c = 0.0
    if a["arm_c_f_per_area"] is not None:
        if a["area"] is None:
            raise ctx.fail(name, "arm_c_f_per_area needs `area`")
        c = a["arm_c_f_per_area"] * a["area"]
    return parts.bridge(name, *conn, a["model"], c)


def _vr_tube(ctx: Context, name: str, conn: list[str], a: dict) -> list[Element]:
    if not isinstance(a["model"], JunctionDiode):
        raise ctx.fail(name, "vr_tube: the model is a junction diode (the tube's slope)")
    return parts.vr_tube(name, *conn, a["model"], a["operating_v"], a["ref_current_a"])


def _speaker(ctx: Context, name: str, conn: list[str], a: dict) -> list[Element]:
    where = f"{name}.component"
    try:
        model = load_speaker(str(versions.require_pinned(ctx.text(where, a["component"]))))
    except (versions.VersionError, ValueError) as err:
        raise ctx.fail(where, str(err)) from err
    cab = Cabinet(a["width_m"], a["height_m"], a["depth_m"], a["offset_x_m"], a["offset_y_m"])
    return parts.speaker(name, *conn, model, cab, a["distance_m"])


def _r(ctx, name, c, a):
    r = a["r"] if a["parallel"] == 1 else a["r"] / a["parallel"]
    return [parts.resistor(name, *c, r)]


_P, _N = Param("physical"), Param("number")
for _name, _macro in {
    "R": Macro(_r, 2, {"r": _P, "parallel": Param("count", 1)}, toleranced=True),
    "C": Macro(
        lambda ctx, n, c, a: [Capacitor(n, *c, a["c"], a["v0"])],
        2,
        {"c": _P, "v0": Param("physical", None)},
        toleranced=True,
    ),
    "L": Macro(lambda ctx, n, c, a: [Inductor(n, *c, a["l"])], 2, {"l": _P}),
    "K": Macro(lambda ctx, n, c, a: [Coupling(n, *c, a["k"])], 2, {"k": _P}),
    "V": Macro(lambda ctx, n, c, a: [VoltageSource(n, *c, a["v"])], 2, {"v": _P}),
    "sine": Macro(
        lambda ctx, n, c, a: [
            SineSource(n, *c, a["offset_v"], a["amplitude_v"], a["freq_hz"], a["phase_deg"])
        ],
        2,
        {
            "amplitude_v": _P,
            "freq_hz": _P,
            "offset_v": Param("number", 0.0),
            "phase_deg": Param("number", 0.0),
        },
    ),
    "mains": Macro(_mains, 2, {"v_rms": _P, "phase_deg": Param("number", 0.0)}),
    "device": Macro(_nodes_device, None, {"model": Param("device")}),
    "pot": Macro(
        lambda ctx, n, c, a: parts.pot(n, *c, a["r"], a["at"], a["taper_mid"]),
        3,
        {"r": _P, "at": _N, "taper_mid": Param("physical", None)},
        toleranced=True,
    ),
    "rheostat": Macro(
        lambda ctx, n, c, a: [parts.rheostat(n, *c, a["r"], a["at"], a["taper_mid"])],
        2,
        {"r": _P, "at": _N, "taper_mid": Param("physical", None)},
        toleranced=True,
    ),
    "tapped_pot": Macro(
        lambda ctx, n, c, a: parts.tapped_pot(n, *c, a["r"], a["at"], a["tap"]),
        4,
        {"r": _P, "at": _N, "tap": _N},
        toleranced=True,
    ),
    "t_pad": Macro(
        lambda ctx, n, c, a: parts.t_pad(n, *c, a["z"], a["atten_db"]),
        3,
        {"z": _P, "atten_db": _N},
        toleranced=True,
    ),
    "switch": Macro(_switch, None, {"parts": Param("raw")}),
    "transformer": Macro(
        _transformer,
        None,
        {
            "core": Param("raw"),
            "turns": _P,
            "leakage_h": _P,
            "interwinding": Param("raw", None),
        },
    ),
    "bridge": Macro(
        _bridge,
        4,
        {
            "model": Param("device"),
            "arm_c_f_per_area": Param("physical", None),
            "area": Param("physical", None),
        },
    ),
    "vr_tube": Macro(
        _vr_tube,
        3,
        {"model": Param("device"), "operating_v": _P, "ref_current_a": _P},
    ),
    "speaker": Macro(
        _speaker,
        3,
        {
            "component": Param("raw"),
            "distance_m": _P,
            "width_m": _P,
            "height_m": _P,
            "depth_m": _P,
            "offset_x_m": Param("physical", 0.0),
            "offset_y_m": Param("physical", 0.0),
        },
    ),
}.items():
    register(_name, _macro)


# --- Devices -----------------------------------------------------------------------------------

_DEVICE_KEYS = {
    "device", "name", "instance", "tolerance", "parallel", "emission", "mu", "grid_contact_v",
    "area", "source", "notes",
}  # fmt: skip


def make_models(ctx: Context) -> dict[str, str]:
    """Every `devices` entry's model into ctx.models; returns model name -> device type
    (the device file's name, which picks a triode's SPICE table grid)."""
    types = {}
    for key, e in ctx.spec.devices.items():
        where = f"devices.{key}"
        unknown = set(e) - _DEVICE_KEYS
        if unknown:
            raise ctx.fail(where, f"unknown keys {sorted(unknown)}")
        try:  # a circuit names the component version it uses (versions.require_pinned)
            base = load_device(str(versions.require_pinned(ctx.text(where, e["device"]))))
        except versions.VersionError as err:
            raise ctx.fail(where, str(err)) from err
        if e.get("instance", True) is False:
            if set(e) - {"device", "instance", "source", "notes"}:
                raise ctx.fail(where, "instance: false takes the device file's model as is")
            model = base
        else:
            emission = ctx.number(f"{where}.emission", e.get("emission", 1.0))
            mu = ctx.number(f"{where}.mu", e.get("mu", 1.0))
            tol = e.get("tolerance")
            if tol is not None:
                if tol != "tube" or ctx.tolerance is None:
                    raise ctx.fail(where, f"tolerance: {tol!r} (tube, with a tolerance block)")
                ef, mf = ctx.tolerance.tube_deviation(key)
                emission = emission * ef
                if isinstance(base, Triode | Pentode):  # a rectifier's draw is emission only
                    mu = mu * mf
            contact = e.get("grid_contact_v")
            try:
                model = parts.device_instance(
                    base,
                    e.get("name") or f"{base.name}_{key}",
                    n_parallel=ctx.count(f"{where}.parallel", e.get("parallel", 1)),
                    emission_scale=emission,
                    mu_spread=mu,
                    grid_contact_v=None if contact is None else ctx.physical(where, contact),
                    area=ctx.physical(f"{where}.area", e["area"]) if "area" in e else 1.0,
                )
            except (TypeError, ValueError) as err:
                raise ctx.fail(where, str(err)) from err
        ctx.models[key] = model
        ctx.parallel[model.name] = (
            1 if e.get("instance", True) is False else ctx.count(where, e.get("parallel", 1))
        )
        types[model.name] = base.name
        ctx.types[model.name] = base.name
    return types


# --- The circuit --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Circuit:
    text: str | None  # SPICE; None when the cores are Jiles-Atherton (circuitsim only)
    input_node: str
    save: tuple[str, ...]
    params: dict[str, Any]
    files: dict[str, Path]  # extra files the netlist reads (job-dir name -> source), e.g. tables
    ir: CircuitIR  # what `text` was emitted from; the Rust engine's input
    cores: str = "ja"  # "ja" (then text is None: no SPICE core) or "linear"
    # The file's (input, output) volts peak at full scale; None: sim_settings' (spec.py).
    full_scale: tuple[float, float] | None = None


def tolerance(spec: CircuitSpec, q: Mapping[str, Any]) -> parts.Tolerance | None:
    """The unit's draws from the file's tolerance block (None: the file has none)."""
    t = spec.parts
    if not t:
        return None
    ctx = Context(spec, dict(q), "ja", None)
    bands = {}
    for cls, b in (t.get("bands") or {}).items():
        where = f"tolerance.bands.{cls}"
        if isinstance(b, list):
            bands[cls] = (ctx.number(where, b[0]), ctx.number(where, b[1]))
        else:
            v = ctx.number(where, b)
            bands[cls] = (v, v)
    tube = t.get("tube") or {}
    return parts.Tolerance(
        seed=int(ctx.ref("tolerance.seed", t["seed"])),
        spread=float(ctx.ref("tolerance.spread", t["spread"])),
        bands=bands,
        classes=spec.part_classes(),
        combined=t.get("combined") or {},
        tube_pct=(
            ctx.ref("tolerance.tube", tube["emission_pct"]) if tube else 0.0,
            ctx.ref("tolerance.tube", tube["mu_pct"]) if tube else 0.0,
        ),
    )


def context(
    spec: CircuitSpec,
    p: Mapping[str, Any],
    cores: str = "ja",
    noise: bool | int | None = None,
    heaters: bool | str | None = None,
) -> Context:
    """A build's context for resolved parameters `p` (see spec.resolve); `noise` and
    `heaters` as build_ir's."""
    if cores not in CORE_MODES:
        raise ValueError(f"unknown core model {cores!r} ({' | '.join(CORE_MODES)})")
    q = dict(p)
    q.update(spec.derive(p))
    ctx = Context(spec, q, cores, tolerance(spec, q))
    ctx.noise = _noise(ctx, noise)
    ctx.heaters = _heaters(spec, heaters)
    return ctx


def _heaters(spec: CircuitSpec, heaters: bool | str | None) -> str | None:
    """The build's heated cathodes: None, the file's `heaters` block; False, off; True, on
    (the block's start, else warm); "warm" / "cold", on with that start."""
    block = spec.heaters
    if heaters is None:
        return None if block is None else block.get("start", "warm")
    if heaters is False:
        return None
    if heaters is True:
        return (block or {}).get("start", "warm")
    if heaters in ("warm", "cold"):
        return heaters
    raise ValueError(f"heaters: {heaters!r} (None, a bool, warm or cold)")


def _heater_spec(ctx: Context) -> HeaterSpec:
    """The IR's heaters block: the oxide constants and the heater's ratio (the mains setting
    over the rated mains)."""
    ox, _ = cathode_mod.load_cathodes()
    ratio = 1.0
    m = ctx.spec.mains
    if m:
        rated = ctx.physical("mains.rated_v_rms", m["rated_v_rms"])
        ratio = float(ctx.ref("mains", m["v_rms"])) / float(rated)
    return HeaterSpec(
        ox.t0_k, ox.t_amb_k, ox.alpha, ox.tau_s, ox.phi_ev, ox.n, ox.reserve, ratio, ctx.heaters
    )


def _noise(ctx: Context, noise: bool | int | None) -> Noise | None:
    """The build's noise: None, the file's block; False, off; True, on (the block's seed,
    else 0); an integer, on with that seed (the block's values or the defaults)."""
    block = ctx.spec.noise
    if noise is None:
        noise = block is not None
    if noise is False:
        return None
    block = block or {}
    if noise is True:
        seed = int(block.get("seed", 0))
    elif isinstance(noise, int) and 0 <= noise < 2**64:
        seed = noise
    else:
        raise ValueError(f"noise: {noise!r} (None, a bool, or a seed)")
    t, kf = noise_mod.RESISTOR_T_K, noise_mod.FLICKER_V2
    if "temperature_k" in block:
        t = ctx.physical("noise.temperature_k", block["temperature_k"])
    if "flicker_v2" in block:
        kf = ctx.physical("noise.flicker_v2", block["flicker_v2"])
    mains = noise_mod.MAINS_RMS
    if "mains_rms" in block:
        mains = ctx.physical("noise.mains_rms", block["mains_rms"])
    return Noise(seed, float(t), float(kf), float(mains))


def build_ir(
    spec: CircuitSpec,
    p: Mapping[str, Any],
    cores: str = "ja",
    noise: bool | int | None = None,
    heaters: bool | str | None = None,
) -> CircuitIR:
    """The circuit IR for resolved parameters `p`; `cores`: "ja" or "linear" (each core
    in its linear limit); `noise`: None, the file's `noise` block; False, none; True, on
    (the block's seed or 0); an integer, on with that seed; `heaters`: None, the file's
    `heaters` block; False, none; True, on; "warm" / "cold", on with that start."""
    return _build(spec, p, cores, noise, heaters)[0]


def _build(
    spec: CircuitSpec,
    p: Mapping[str, Any],
    cores: str,
    noise: bool | int | None = None,
    heaters: bool | str | None = None,
) -> tuple[CircuitIR, dict]:
    ctx = context(spec, p, cores, noise, heaters)
    types = make_models(ctx)
    sections = []
    for s in spec.sections:
        ctx.section_tolerance = s.get("tolerance")
        els: list[Element] = []
        for name, entry in s["parts"].items():
            els += expand_part(ctx, str(name), entry)
        sections.append(Section(s["title"], tuple(els)))
    if ctx.missing_class:
        raise ConfigError(f"parts without a tolerance class: {sorted(ctx.missing_class)}")
    if ctx.tolerance is not None:
        named = set(ctx.tolerance.classes) | {
            d for ds in ctx.tolerance.combined.values() for d in ds
        }
        listed = ctx.designators | {d for x in ctx.designators for d in ctx.tolerance.parts_of(x)}
        stray = named - listed
        if stray:
            raise ConfigError(f"{spec.path}: tolerance classes name no part: {sorted(stray)}")
    unused = set(ctx.models) - ctx.used_devices
    if unused:
        raise ConfigError(f"{spec.path}: devices no part uses: {sorted(unused)}")
    ir = CircuitIR(
        title=spec.title,
        input_node=spec.input_node,
        probes=tuple(VoltageProbe(n) for n in spec.probes),
        models=(*ctx.models.values(), *ctx.core_models),
        sections=tuple(sections),
        controls=tuple(Control(n, node) for n, node in spec.cv_inputs),
        noise=None if ctx.noise is None else _noise_spec(ctx, sections),
        heaters=None if ctx.heaters is None else _heater_spec(ctx),
    )
    return ir, types


def _noise_spec(ctx: Context, sections: list[Section]) -> NoiseSpec:
    """The IR's noise block: the mains wander on the mains parts the build kept (a switch
    may leave one out)."""
    nz = ctx.noise
    rate = float(load_sim_settings().data["sample_rate"])
    kept = {e.name for sec in sections for e in sec.elements if isinstance(e, SineSource)}
    mains = tuple(n for n in ctx.mains_sines if n in kept) if nz.mains_rms > 0 else ()
    return NoiseSpec(nz.seed, rate, nz.mains_rms if mains else 0.0, mains)


def build(
    spec: CircuitSpec,
    overrides: Mapping[str, Any] | None = None,
    *,
    triode_formulation: str | None = None,
    cores: str | None = None,
    noise: bool | int | None = None,
    heaters: bool | str | None = None,
) -> Circuit:
    """The circuit for `spec` with `overrides`. `triode_formulation` is "table" or
    "exact" (default from sim_settings.yaml, devices.triode_formulation); `cores` is
    "ja" or "linear" (default devices.cores). A "ja" build has no SPICE text, nor
    does one with control inputs (ngspice runs none). `noise`, `heaters` as build_ir's."""
    p = resolve(spec, overrides)
    devices = load_sim_settings().data["devices"]
    form = triode_formulation or devices["triode_formulation"]
    if form not in spice.FORMULATIONS:
        raise ValueError(f"unknown triode formulation {form!r}")
    cores = cores or devices.get("cores", "ja")
    if cores not in CORE_MODES:
        raise ValueError(f"unknown core model {cores!r} ({' | '.join(CORE_MODES)})")
    ir, types = _build(spec, p, cores, noise, heaters)
    # Each triode instance's table grid is its tube type's.
    grids = {m.name: GRIDS[types[m.name]] for m in ir.models if isinstance(m, Triode)}
    text, files = None, {}
    # ngspice runs no circuit with control inputs (no SPICE text, as a "ja" build).
    if cores == "linear" and not ir.controls:
        text, files = spice.emit(ir, triode_formulation=form, table_grids=grids)
    save = tuple(pr.spice for pr in ir.probes)
    return Circuit(text, ir.input_node, save, p, files, ir, cores, spec.full_scale)


def find_part(spec: CircuitSpec, name: str) -> Mapping:
    for s in spec.sections:
        if name in s["parts"]:
            return s["parts"][name]
    raise KeyError(name)


def part_elements(
    spec: CircuitSpec, name: str, p: Mapping[str, Any], cores: str = "ja"
) -> list[Element]:
    """Part `name`'s elements alone, for resolved parameters `p` (no tolerance draw)."""
    ctx = context(spec, p, cores)
    make_models(ctx)
    ctx.tolerance = None
    return expand_part(ctx, name, find_part(spec, name))


def transformer_core(spec: CircuitSpec, name: str, p: Mapping[str, Any]) -> MagneticCore:
    """The Jiles-Atherton core of transformer part `name`."""
    ctx = context(spec, p)
    entry = find_part(spec, name)
    a = _resolve_params(ctx, name, MACROS["transformer"], entry)
    _, core = transformer_spec(ctx, name, entry["transformer"], a)
    return parts.transformer_core(name, core)

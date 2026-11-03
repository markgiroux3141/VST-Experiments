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
  the core's linear limit). See Winding;
- a Vccs is SPICE's G (component editor C3: a speaker's pressure readout senses
  the cone's motion without loading it). A new element kind, not a new schema:
  circuits without one write the same JSON;
- noise (device builder B5, varimu.devices.noise): the circuit's `noise` block (its
  seed) and the elements NoiseCurrent (a resistor's Johnson noise) and TubeNoise (a tube
  instance's shot, grid-current shot and flicker noise), all optional: an IR without
  noise reads and writes as before;
- heated cathodes (device builder B6, varimu.devices.cathode): the circuit's `heaters` block
  (the oxide constants, the heater's voltage ratio, warm or cold start) and a HeatedCathode
  per tube instance; optional as noise is;
- a ThyratronEvents is a gas thyratron as technique K's event kernels
  (HYBRID_PHYSICS_PLAN.md H3; varimu.devices.thyratron_events is the reference,
  circuitsim's events.rs the port): the off tube's capacitances and leakage, its strikes
  injected a -> k as charges held over each step. A new element kind, as Vccs.
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
from varimu.devices.lamp import Lamp
from varimu.devices.pentode import KorenPentode, Pentode
from varimu.devices.thyratron import Thyratron
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
    """`v0_v`: the voltage (a - b) the capacitor holds at the start of a run, None: none.
    The DC operating point is solved with it held there (a start state, as SPICE's IC=), so
    a run can start away from a balance point the circuit would otherwise sit at, such as
    a symmetric multivibrator's (a noiseless simulation never leaves it). Absent from the
    JSON when None. ngspice starts from its own operating point and ignores it."""

    name: str
    a: str
    b: str
    c_f: float
    v0_v: float | None = None


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
class Vccs:
    """Voltage-controlled current source (SPICE G): a current
    gm_s (v(ctrl_pos) - v(ctrl_neg)) flows from pos through the source to neg. Its
    control draws no current."""

    name: str
    pos: str
    neg: str
    ctrl_pos: str
    ctrl_neg: str
    gm_s: float


@dataclass(frozen=True)
class Plate:
    """A plate reverb's medium (docs/REVERB_PLAN.md, E2 / E6; varimu.devices.plate is the
    reference, circuitsim's plate.rs the port): a force force_per_v (v(sense_pos) -
    v(sense_neg)) (the exciter coil's current sensed across its resistance, times BL over
    that resistance; the sense draws no current) at drive_xy, and the acceleration at
    pickup_xy times out_per_m_s2 driving `out` to ground one sample after the force
    (one-way: the plate's load on the coil is the builder's resistor). Positions are
    fractions of the sides; decay is the energy decay rate (1/s) against frequency (Hz),
    rising in Hz. SPICE has no plate: ngspice sees `out` held at 0 V (the medium cut out at
    its ports)."""

    name: str
    sense_pos: str
    sense_neg: str
    force_per_v: float
    out: str
    out_per_m_s2: float
    lx_m: float
    ly_m: float
    thickness_m: float
    density_kg_m3: float
    youngs_pa: float
    poisson: float
    tension_n_m: float
    drive_xy: tuple[float, float]
    pickup_xy: tuple[float, float]
    f_max_hz: float
    decay: tuple[tuple[float, float], ...]
    tail_db: float


@dataclass(frozen=True)
class TapeMedium:
    """Tape's parameters (circuitsim's `tape_stream::TapeParams`;
    `varimu.devices.tape_machine.stream_params` writes them): the tape component's
    particles, the machine's transport, heads and bias, the numerics."""

    hc_median_a_m: float
    sigma_ln_hc: float
    sigma_hi_a_m: float
    h_max_a_m: float
    n_table: int
    ms_a_m: float
    coating_m: float
    kappa: float
    orientations: int
    speed_m_s: float
    f_bias_hz: float
    hg_bias_a_m: float
    bias_phase_rad: float
    rec_gap_m: float
    rep_gap_m: float
    pole_m: float
    relax_m: float
    spacing_m: float
    track_m: float
    head_distance_m: float
    rep_h_per_a: float
    layers: int
    ds_m: float
    table_step: float
    zone_floor_a_m: float
    local_zones: bool
    demag_iterations: int
    demag_tol: float
    head_image: bool
    lam_min_m: float
    block_m: float
    margin_m: float
    flutter: tuple[tuple[float, float, float], ...]
    flutter_noise: tuple[tuple[float, float, float], ...]
    particle_volume_m3: float
    packing: float
    packing_sigma: float
    packing_corr_m: float
    # The literal bias (TAPE_PLAN.md TM5, option A): the sense is the head's whole field,
    # bias included, M samples per step from a multi-rate part (`TapeStream`'s literal
    # mode). None: the medium's own bias (hg_bias_a_m), and no such key in the JSON.
    bias_substeps: int | None = None


@dataclass(frozen=True)
class Tape:
    """Magnetic tape between a record and a repro head (docs/TAPE_PLAN.md, TM4;
    varimu.devices.tape_machine.TapeStream is the reference, circuitsim's tape_stream.rs
    the port): the record gap's signal field h_per_v (v(sense_pos) - v(sense_neg))
    (deep-gap A/m: the record coil's current sensed across its resistance, times the
    head's field per ampere over that resistance; the sense draws no current), recorded
    with the medium's own AC bias, and the repro coil's EMF driving `out` to ground one
    sample later. SPICE has no tape: ngspice sees `out` held at 0 V."""

    name: str
    sense_pos: str
    sense_neg: str
    h_per_v: float
    out: str
    medium: TapeMedium


@dataclass(frozen=True)
class NoiseCurrent:
    """White noise current of one-sided density `psd_a2_hz` (A^2/Hz) from a through the
    source to b: a resistor's Johnson noise, its Norton source (B5). Its samples are the
    stream varimu.devices.noise.key(seed, name, STREAM_MAIN)."""

    name: str
    a: str
    b: str
    psd_a2_hz: float


@dataclass(frozen=True)
class TubeNoise:
    """A tube instance's noise (B5), on device element `device` (a triode or pentode):
    plate shot noise from the plate to the cathode, density shot_k gm (A^2/Hz; with
    `partition` > 0, a pentode's (Ib / Ik) shot_k (gm + partition Ic2)), full shot noise of
    the control grid's current (2 q |Ig|), both at the last accepted step's currents, and
    flicker as a voltage in series with the control grid, one-sided density
    flicker_v2 / f (V^2). varimu.devices.noise has the streams."""

    name: str
    device: str
    shot_k: float
    partition: float
    flicker_v2: float


@dataclass(frozen=True)
class HeatedCathode:
    """Device element `device` (a triode, pentode or vacuum diode instance) has a heated
    cathode (B6): its currents follow the circuit's cathode temperature through the
    space-charge shift and the emission ceiling (varimu.devices.cathode.heated), `is0_a` its
    emission at the rated temperature."""

    name: str
    device: str
    is0_a: float


@dataclass(frozen=True)
class HeaterSpec:
    """The circuit's heaters (B6): one cathode temperature for every HeatedCathode (they
    share the oxide constants and the heater winding), heated by `heater_ratio` (the heater
    winding's volts over their rating: the mains setting's ratio) times B5's mains wander
    when the noise has it; `start` "warm" (at the temperature that ratio holds) or "cold"
    (at t_amb_k: power on)."""

    t0_k: float
    t_amb_k: float
    alpha: float
    tau_s: float
    phi_ev: float
    n: float
    reserve: float
    heater_ratio: float
    start: str = "warm"


@dataclass(frozen=True)
class NoiseSpec:
    """The circuit's noise: the seed every source's stream is keyed by (an integer) and the
    sample grid its samples sit on (the project's rate, sim_settings' sample_rate). Mains
    wander: the SineSources named in `mains_sources` (the mains) have their amplitude times
    (1 + m(t)), m one shared stream of nominal rms `mains_rms` (varimu.devices.noise.
    mains_wander); written only when there are mains sources."""

    seed: int
    rate_hz: float
    mains_rms: float = 0.0
    mains_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThyratronEvents:
    """A triode gas thyratron as technique K's event kernels (HYBRID_PHYSICS_PLAN.md H3,
    "K's design"; varimu.devices.thyratron_events is the reference, circuitsim's events.rs
    the port), on the device's pins (a, g, w, k). Between events the tube is its
    capacitances (c_gk_f, c_ga_f, c_ak_f) and the grid-to-anode leakage g_leak_s; the plasma
    state's node w is held to k by a numerical 1 S (K has no state there). After each sample
    the element senses the unit's capacitor (v_ak plus r_s_ohm times its own current) and
    the grid (v_gk less r_g_ohm c_ga_f times the ramp's slope: the coupling the off tube's
    grid-to-anode capacitance gives the unit's grid return, which the tables already hold),
    predicts a strike within the next step and injects its charges a -> k, held over each
    step. The unit (c_f, r_s_ohm, r_g_ohm) is the exception's: its tables come from
    reference runs of it.

    The tables over (v_g_v, log_slope: ln V/s), both ascending, indexed [v_g][slope]: the
    strike voltage v_s_v (the unit's capacitor at the strike), the dead time dead_s, the
    latched points (the arc never goes out: no pulse, dead 0), and the anode current's
    pulse from the strike at ref_rate_hz (pulses_a; the pre-conduction in its first
    sample) and the grid's over the same samples (grid_pulses_a: into the grid pin, injected
    g -> k). The engine band-limits them for its own step (`thyratron_events.
    step_charges` at oversample ref_rate_hz * h). `source` names the reference run. SPICE
    has only the off tube."""

    name: str
    a: str
    g: str
    w: str
    k: str
    c_gk_f: float
    c_ga_f: float
    c_ak_f: float
    g_leak_s: float
    c_f: float
    r_s_ohm: float
    r_g_ohm: float
    ref_rate_hz: float
    v_g_v: tuple[float, ...]
    log_slope: tuple[float, ...]
    v_s_v: tuple[tuple[float, ...], ...]
    dead_s: tuple[tuple[float, ...], ...]
    latched: tuple[tuple[bool, ...], ...]
    pulses_a: tuple[tuple[tuple[float, ...], ...], ...]
    grid_pulses_a: tuple[tuple[tuple[float, ...], ...], ...]
    source: str


@dataclass(frozen=True)
class Device:
    """An instance of a device model; nodes follow the model's PINS order."""

    name: str
    model: str
    nodes: tuple[str, ...]


Element = (
    Resistor
    | Capacitor
    | Inductor
    | Coupling
    | VoltageSource
    | SineSource
    | Winding
    | Vccs
    | NoiseCurrent
    | TubeNoise
    | HeatedCathode
    | Device
    | Plate
    | Tape
    | ThyratronEvents
)
DeviceModel = Triode | Pentode | JunctionDiode | VacuumDiode | MagneticCore | Lamp | Thyratron

PINS: dict[type, tuple[str, ...]] = {
    Triode: ("p", "g", "k"),
    Pentode: ("p", "g2", "g1", "k"),
    JunctionDiode: ("a", "k"),
    VacuumDiode: ("a", "k"),
    MagneticCore: ("b", "ref"),
    Lamp: ("a", "t", "b"),
}


def pins_of(model: DeviceModel) -> tuple[str, ...]:
    """A model's pins: by type, except a thyratron's (a triode's or a tetrode's)."""
    return model.pins if isinstance(model, Thyratron) else PINS[type(model)]


_PREFIX = {
    Resistor: "R",
    Capacitor: "C",
    Inductor: "L",
    Coupling: "K",
    VoltageSource: "V",
    SineSource: "V",
    Winding: "L",
    Vccs: "G",
    NoiseCurrent: "I",
    TubeNoise: "B",
    HeatedCathode: "B",
    Plate: "V",
    Tape: "V",
    ThyratronEvents: "X",
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
    if isinstance(el, Vccs):
        return (el.pos, el.neg, el.ctrl_pos, el.ctrl_neg)
    if isinstance(el, NoiseCurrent):
        return (el.a, el.b)
    if isinstance(el, Device):
        return el.nodes
    if isinstance(el, Plate | Tape):
        return (el.sense_pos, el.sense_neg, el.out)
    if isinstance(el, ThyratronEvents):
        return (el.a, el.g, el.w, el.k)
    return ()


@dataclass(frozen=True)
class VoltageProbe:
    """Node voltage relative to ground."""

    node: str

    @property
    def spice(self) -> str:
        return f"v({self.node})"


@dataclass(frozen=True)
class Control:
    """A control input (a gate, a pitch voltage; the tube synth's S3): `node` to ground
    driven by its own samples beside the audio input, linear between samples (circuitsim;
    ngspice runs no circuit with control inputs)."""

    name: str
    node: str


# A multi-rate section's decimation of what it hands on (Section.decimate).
DECIMATIONS = ("fir",)


@dataclass(frozen=True)
class Section:
    """A titled group of elements (one stage). Only for readability, except `substeps`:
    a section with them steps that many times per sample on a thread of its own (a
    multi-rate part, circuitsim's partition.rs: the Ampex 351's bias oscillator, above
    the audio rate's Nyquist frequency). None: it steps with the rest (and the JSON
    has no `substeps`, as before).

    A multi-rate section's two options (HYBRID_PHYSICS_PLAN.md H3a, M1; None: absent from
    the JSON, the part as before):
    - `decimate`: "fir", what the part hands on (currents into nodes it doesn't own, the
      voltages of nodes it owns, its probes) through a linear-phase anti-alias low-pass
      over its steps, instead of their average over the sample;
    - `owns`: shared nodes the part owns (it publishes their voltages and is fed their
      users' currents), where by default a multi-rate part owns none: an island's
      low-impedance output into a high-impedance load."""

    title: str
    elements: tuple[Element, ...]
    substeps: int | None = None
    decimate: str | None = None
    owns: tuple[str, ...] | None = None


# --- The circuit ------------------------------------------------------------------------


@dataclass(frozen=True)
class CircuitIR:
    title: str
    input_node: str  # driven by the audio input, relative to ground
    probes: tuple[VoltageProbe, ...]
    models: tuple[DeviceModel, ...]
    sections: tuple[Section, ...]
    version: int = IR_VERSION
    # Control inputs (Control), each driven by its own samples. Optional: an IR without
    # any reads and writes as before (in JSON they follow input_node, as in Rust).
    controls: tuple[Control, ...] = ()
    # Noise (B5): None, none (an IR without reads and writes as before).
    noise: NoiseSpec | None = None
    # Heated cathodes (B6): None, none.
    heaters: HeaterSpec | None = None

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
            Section(
                s.title,
                tuple(
                    e for e in s.elements if not isinstance(e, Device | TubeNoise | HeatedCathode)
                ),
            )
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

        for s in self.sections:
            if s.substeps is not None and (
                not isinstance(s.substeps, int) or isinstance(s.substeps, bool) or s.substeps < 1
            ):
                raise IRError(f"section {s.title!r}: substeps {s.substeps!r} (a count, 1 or more)")
            multirate = s.substeps is not None and s.substeps > 1
            if s.decimate is not None and (s.decimate not in DECIMATIONS or not multirate):
                raise IRError(
                    f"section {s.title!r}: decimate {s.decimate!r} (one of {DECIMATIONS},"
                    " in a multi-rate section)"
                )
            if s.owns is not None and (not multirate or not s.owns):
                raise IRError(f"section {s.title!r}: owns needs nodes, in a multi-rate section")
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
                if el.v0_v is not None:
                    _finite(f"{el.name}.v0_v", el.v0_v)
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
            elif isinstance(el, Vccs):
                if not (math.isfinite(el.gm_s) and el.gm_s != 0):
                    raise IRError(f"{el.name}.gm_s = {el.gm_s} must be finite and nonzero")
                for a, b in ((el.pos, el.neg), (el.ctrl_pos, el.ctrl_neg)):
                    if a == b:
                        raise IRError(f"{el.name}: both ends on node {a}")
            elif isinstance(el, NoiseCurrent):
                _nonneg(f"{el.name}.psd_a2_hz", el.psd_a2_hz)
            elif isinstance(el, TubeNoise):
                for what in ("shot_k", "partition", "flicker_v2"):
                    _nonneg(f"{el.name}.{what}", getattr(el, what))
            elif isinstance(el, HeatedCathode):
                _positive(f"{el.name}.is0_a", el.is0_a)
            elif isinstance(el, Plate):
                _validate_plate(el, self.input_node)
            elif isinstance(el, Tape):
                _validate_tape(el, self.input_node)
            elif isinstance(el, ThyratronEvents):
                _validate_thyratron_events(el)
            elif isinstance(el, Device):
                if el.model not in models:
                    raise IRError(f"{el.name}: unknown model {el.model}")
                pins = pins_of(models[el.model])
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
        devices = {e.name: e for e in self.elements() if isinstance(e, Device)}
        noisy: set[str] = set()
        heated: set[str] = set()
        for el in self.elements():
            if isinstance(el, TubeNoise):
                d = devices.get(el.device)
                m = None if d is None else models[d.model]
                if not isinstance(m, Triode | Pentode):
                    raise IRError(f"{el.name}: {el.device} is not a triode or pentode instance")
                if el.partition > 0 and not isinstance(m, Pentode):
                    raise IRError(f"{el.name}: partition noise needs a pentode")
                if el.device in noisy:
                    raise IRError(f"{el.name}: {el.device} has noise twice")
                noisy.add(el.device)
            if isinstance(el, HeatedCathode):
                d = devices.get(el.device)
                m = None if d is None else models[d.model]
                if not isinstance(m, Triode | Pentode | VacuumDiode):
                    raise IRError(f"{el.name}: {el.device} is not a tube instance")
                if el.device in heated:
                    raise IRError(f"{el.name}: {el.device} is heated twice")
                if self.heaters is None:
                    raise IRError(f"{el.name}: a heated cathode needs the `heaters` block")
                heated.add(el.device)
            if isinstance(el, Coupling):
                for ind in (el.l_a, el.l_b):
                    if ind not in inductors:
                        raise IRError(f"{el.name}: {ind} is not an inductor")
                if el.l_a == el.l_b:
                    raise IRError(f"{el.name}: couples {el.l_a} to itself")

        # A source's nodes need other elements: its control draws no current and its
        # output alone would be a current into nothing.
        others = {n for e in self.elements() if not isinstance(e, Vccs) for n in element_nodes(e)}
        for el in self.elements():
            if isinstance(el, Vccs):
                for n in element_nodes(el):
                    if n != GROUND and n not in others:
                        raise IRError(f"{el.name}: node {n} has no other element")

        if GROUND not in nodes:
            raise IRError('no element connects to ground (node "0")')
        if self.input_node not in nodes:
            raise IRError(f"input node {self.input_node} is not connected")
        for i, c in enumerate(self.controls):
            if c.node in (GROUND, self.input_node):
                raise IRError(f"control {c.name}: node {c.node} is ground or the input")
            if c.node not in nodes:
                raise IRError(f"control {c.name}: node {c.node} is not connected")
            if any(d.name == c.name or d.node == c.node for d in self.controls[:i]):
                raise IRError(f"control {c.name}: a name or node twice")
        for p in self.probes:
            if p.node not in nodes:
                raise IRError(f"probe node {p.node} is not connected")
        if self.noise is not None:
            seed = self.noise.seed
            if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
                raise IRError(f"noise seed {seed!r} must be an integer in [0, 2^64)")
            _positive("noise.rate_hz", self.noise.rate_hz)
            _nonneg("noise.mains_rms", self.noise.mains_rms)
            sines = {e.name for e in self.elements() if isinstance(e, SineSource)}
            for m in self.noise.mains_sources:
                if m not in sines:
                    raise IRError(f"noise.mains_sources: {m} is not a sine source")
        if self.heaters is not None:
            h = self.heaters
            for what in ("t0_k", "t_amb_k", "tau_s", "phi_ev", "n", "reserve", "heater_ratio"):
                _positive(f"heaters.{what}", getattr(h, what))
            _nonneg("heaters.alpha", h.alpha)
            if h.start not in ("warm", "cold"):
                raise IRError(f"heaters.start {h.start!r}: warm or cold")
            if not h.t_amb_k < h.t0_k:
                raise IRError("heaters: t_amb_k must be below t0_k")

    # --- JSON ---

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "version": self.version,
            "title": self.title,
            "input_node": self.input_node,
        }
        if self.controls:
            d["controls"] = [{"name": c.name, "node": c.node} for c in self.controls]
        if self.noise is not None:
            # The seed as an integer, not the codec's float.
            d["noise"] = {"seed": self.noise.seed, "rate_hz": float(self.noise.rate_hz)}
            if self.noise.mains_sources:
                d["noise"]["mains_rms"] = float(self.noise.mains_rms)
                d["noise"]["mains_sources"] = list(self.noise.mains_sources)
        if self.heaters is not None:
            d["heaters"] = _encode(self.heaters)
        d.update(
            probes=[_encode(p) for p in self.probes],
            models=[_encode(m) for m in self.models],
            sections=[_encode(s) for s in self.sections],
        )
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=1, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CircuitIR:
        keys = {"version", "title", "input_node", "probes", "models", "sections"}
        _check_keys("circuit", d, keys | ({"controls", "noise", "heaters"} & set(d)))
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
                    substeps=_count,
                    owns=tuple,
                )
                for s in d["sections"]
            ),
            version=d["version"],
            controls=tuple(_fields(Control, c, tagged=False) for c in d.get("controls", ())),
            noise=_decode_noise(d["noise"]) if "noise" in d else None,
            heaters=_fields(HeaterSpec, d["heaters"], tagged=False) if "heaters" in d else None,
        )

    @classmethod
    def from_json(cls, text: str) -> CircuitIR:
        return cls.from_dict(json.loads(text))


def _decode_noise(d: Any) -> NoiseSpec:
    if not isinstance(d, dict):
        raise IRError("noise: an object {seed, rate_hz}")
    mains = {"mains_rms", "mains_sources"} & set(d)
    _check_keys("noise", d, {"seed", "rate_hz"} | (mains and {"mains_rms", "mains_sources"}))
    return NoiseSpec(
        seed=d["seed"],
        rate_hz=d["rate_hz"],
        mains_rms=d.get("mains_rms", 0.0),
        mains_sources=tuple(d.get("mains_sources", ())),
    )


def _nonneg(what: str, x: float) -> None:
    if not (math.isfinite(x) and x >= 0):
        raise IRError(f"{what} = {x} must be finite and >= 0")


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
        values += [
            (f.name, getattr(m.model, f.name))
            for f in dataclasses.fields(m.model)
            if f.name != "screen"
        ]
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
    elif isinstance(m, Lamp):
        values += [
            ("wire_d_m", m.wire_d_m),
            ("wire_l_m", m.wire_l_m),
            ("rad_fraction", m.rad_fraction),
            ("t_amb_k", m.t_amb_k),
        ]
        if len(m.emissivity) != 4:
            raise IRError(f"{m.name}.emissivity: 4 coefficients (c0..c3)")
        for c in m.emissivity:
            _finite(f"{m.name}.emissivity[]", c)
    elif isinstance(m, Thyratron):
        values += [
            (w, getattr(m, w))
            for w in (
                "mu_a",
                "e_v",
                "perveance",
                "x_n",
                "v_x_v",
                "k_ion",
                "w_ion_v",
                "c_meta",
                "w_meta_v",
                "tau_diff_s",
                "k_grid",
                "p_grid",
                "t_e_v",
                "q_s_c",
                "s0_per_s",
            )
        ]
        if m.mu_g2 is not None:
            values.append(("mu_g2", m.mu_g2))
        for w in ("v0_v", "v_ion_v", "v_meta_v", "v_float_v"):
            _finite(f"{m.name}.{w}", getattr(m, w))
        for w in ("g_leak_s", "c_gk", "c_ga", "c_ak"):
            nonneg(w, getattr(m, w))
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
    "vccs": Vccs,
    "noise_current": NoiseCurrent,
    "tube_noise": TubeNoise,
    "heated_cathode": HeatedCathode,
    "device": Device,
    "plate": Plate,
    "tape": Tape,
    "thyratron_events": ThyratronEvents,
}
_MODEL_KINDS = {
    "triode": Triode,
    "pentode": Pentode,
    "junction_diode": JunctionDiode,
    "vacuum_diode": VacuumDiode,
    "magnetic_core": MagneticCore,
    "lamp": Lamp,
    "thyratron": Thyratron,
}
_PLATE_KINDS = {"koren": KorenTriode, "varimu": VariMuTriode}
# Optional fields written only when set, so IRs without them read and write as before.
_OMITTED_WHEN_NONE = {
    (Capacitor, "v0_v"),
    (Section, "substeps"),
    (Section, "decimate"),
    (Section, "owns"),
    (TapeMedium, "bias_substeps"),
    (KorenPentode, "screen"),
}
_PROBE_KINDS = {"voltage": VoltageProbe}
_KIND_OF = {
    cls: kind
    for table in (_ELEMENT_KINDS, _MODEL_KINDS, _PLATE_KINDS, _PROBE_KINDS)
    for kind, cls in table.items()
}


def _encode(x: Any) -> Any:
    if dataclasses.is_dataclass(x):
        d = {"kind": _KIND_OF[type(x)]} if type(x) in _KIND_OF else {}
        d.update(
            {
                f.name: _encode(getattr(x, f.name))
                for f in dataclasses.fields(x)
                if not ((type(x), f.name) in _OMITTED_WHEN_NONE and getattr(x, f.name) is None)
            }
        )
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
    omitted = {n for n in names if (cls, n) in _OMITTED_WHEN_NONE and n not in d}
    _check_keys(cls.__name__, d, names - omitted | ({"kind"} if tagged else set()))
    kw = {}
    for n in names - omitted:
        v = d[n]
        if n in nested:
            v = nested[n](v)
        elif isinstance(v, list):
            v = tuple(v)
        kw[n] = v
    return cls(**kw)


def _count(v: Any) -> int:
    """A count the JSON writes as a float."""
    if float(v) != int(v):
        raise IRError(f"{v} isn't a count")
    return int(v)


def _decode(d: dict, kinds: dict[str, type]) -> Any:
    cls = kinds.get(d.get("kind"))
    if cls is None:
        raise IRError(f"unknown kind {d.get('kind')!r} (expected one of {sorted(kinds)})")
    if cls is Plate:
        return _fields(cls, d, tagged=True, decay=lambda v: tuple(tuple(x) for x in v))
    if cls is Tape:
        return _fields(cls, d, tagged=True, medium=_decode_tape_medium)
    if cls is ThyratronEvents:

        def grid(v):
            return tuple(tuple(x) for x in v)

        return _fields(
            cls,
            d,
            tagged=True,
            v_s_v=grid,
            dead_s=grid,
            latched=grid,
            pulses_a=lambda v: tuple(tuple(tuple(p) for p in row) for row in v),
            grid_pulses_a=lambda v: tuple(tuple(tuple(p) for p in row) for row in v),
        )
    return _fields(cls, d, tagged=True)


def _validate_plate(el: Plate, input_node: str) -> None:
    """The same checks as the Rust IR's for a plate."""
    for k in ("lx_m", "ly_m", "thickness_m", "density_kg_m3", "youngs_pa", "f_max_hz", "tail_db"):
        _positive(f"{el.name}.{k}", getattr(el, k))
    _nonneg(f"{el.name}.tension_n_m", el.tension_n_m)
    for k in ("force_per_v", "out_per_m_s2"):
        _finite(f"{el.name}.{k}", getattr(el, k))
    if not 0 <= el.poisson < 0.5:
        raise IRError(f"{el.name}.poisson = {el.poisson} must be in [0, 0.5)")
    for xy in (el.drive_xy, el.pickup_xy):
        if not all(0 < v < 1 for v in xy):
            raise IRError(f"{el.name}: position {list(xy)} must be inside the plate (0..1)")
    ok = (
        bool(el.decay)
        and all(f > 0 and s >= 0 and math.isfinite(s) for f, s in el.decay)
        and all(b[0] > a[0] for a, b in zip(el.decay, el.decay[1:], strict=False))
    )
    if not ok:
        raise IRError(f"{el.name}.decay: (Hz, 1/s) points rising in Hz, rates finite and >= 0")
    if el.sense_pos == el.sense_neg:
        raise IRError(f"{el.name}: its force senses {el.sense_pos} against itself")
    if el.out in (GROUND, input_node):
        raise IRError(f"{el.name}: its pickup drives {el.out} (ground or the input)")


def _validate_thyratron_events(el: ThyratronEvents) -> None:
    """The same checks as the Rust IR's for a thyratron's event kernels."""
    for k in ("c_f", "r_s_ohm", "r_g_ohm", "ref_rate_hz"):
        _positive(f"{el.name}.{k}", getattr(el, k))
    for k in ("c_gk_f", "c_ga_f", "c_ak_f", "g_leak_s"):
        _nonneg(f"{el.name}.{k}", getattr(el, k))
    for k in ("v_g_v", "log_slope"):
        ax = getattr(el, k)
        if len(ax) < 2 or not all(math.isfinite(x) for x in ax):
            raise IRError(f"{el.name}.{k}: two or more finite values")
        if not all(b > a for a, b in zip(ax, ax[1:], strict=False)):
            raise IRError(f"{el.name}.{k}: ascending")
    shape = (len(el.v_g_v), len(el.log_slope))
    for k in ("v_s_v", "dead_s", "latched", "pulses_a", "grid_pulses_a"):
        t = getattr(el, k)
        if len(t) != shape[0] or any(len(row) != shape[1] for row in t):
            raise IRError(f"{el.name}.{k}: {shape[0]} rows of {shape[1]} (v_g_v by log_slope)")
    live = 0
    for i in range(shape[0]):
        for j in range(shape[1]):
            v, dead, latched, p = (el.v_s_v[i][j], el.dead_s[i][j], el.latched[i][j],
                                   el.pulses_a[i][j])  # fmt: skip
            _finite(f"{el.name}.v_s_v", v)
            _nonneg(f"{el.name}.dead_s", dead)
            if not isinstance(latched, bool):
                raise IRError(f"{el.name}.latched: true or false")
            if latched and (p or dead != 0):
                raise IRError(f"{el.name}: a latched point has no pulse and no dead time")
            if not latched and not (p and all(math.isfinite(x) for x in p)):
                raise IRError(f"{el.name}: a pulse of finite samples at every point not latched")
            gp = el.grid_pulses_a[i][j]
            if len(gp) != len(p) or not all(math.isfinite(x) for x in gp):
                raise IRError(f"{el.name}: a grid pulse of finite samples as long as the anode's")
            live += not latched
    if not live:
        raise IRError(f"{el.name}: every point latched")
    if len({el.a, el.g, el.w, el.k}) != 4:
        raise IRError(f"{el.name}: its pins (a, g, w, k) on four nodes")


#: Recording runs this much tape past a block's ends (`tape_machine.ZONE_PAD_M`).
_TAPE_ZONE_PAD_M = 2e-3


def _decode_tape_medium(d: dict) -> TapeMedium:
    def rows(v):
        return tuple(tuple(x) for x in v)

    m = _fields(
        TapeMedium,
        d,
        tagged=False,
        flutter=rows,
        flutter_noise=rows,
        bias_substeps=_count,
    )
    ints = {f.name for f in dataclasses.fields(TapeMedium) if f.type == "int"}
    return dataclasses.replace(m, **{k: int(getattr(m, k)) for k in ints})


def _validate_tape(el: Tape, input_node: str) -> None:
    """The same checks as the Rust IR's for tape (`TapeParams::check` without a step
    rate)."""
    m = el.medium
    _finite(f"{el.name}.h_per_v", el.h_per_v)
    for k in (
        "hc_median_a_m", "sigma_ln_hc", "sigma_hi_a_m", "h_max_a_m", "ms_a_m", "coating_m",
        "speed_m_s", "f_bias_hz", "rec_gap_m", "rep_gap_m", "pole_m", "track_m", "ds_m",
        "zone_floor_a_m", "lam_min_m", "block_m",
    ):  # fmt: skip
        _positive(f"{el.name}.medium.{k}", getattr(m, k))
    for k in ("relax_m", "spacing_m", "margin_m", "kappa", "hg_bias_a_m"):
        _nonneg(f"{el.name}.medium.{k}", getattr(m, k))
    grain_ok = (
        m.particle_volume_m3 >= 0
        and 0 <= m.packing < 1
        and m.packing_sigma >= 0
        and (m.packing_sigma == 0 or m.packing_corr_m > 0)
    )
    if not grain_ok:
        raise IRError(f"{el.name}.medium: its grain (particles, packing) is out of range")
    flutter_ok = all(a >= 0 and f > 0 and math.isfinite(ph) for a, f, ph in m.flutter) and all(
        rms >= 0 and f > 0 and q > 0 for rms, f, q in m.flutter_noise
    )
    if not flutter_ok:
        raise IRError(f"{el.name}.medium: its flutter's components are out of range")
    if m.n_table < 4 or m.orientations < 1 or m.layers < 1:
        raise IRError(f"{el.name}.medium: n_table >= 4, orientations and layers >= 1")
    nb = round(m.block_m / m.ds_m)
    nm = round(m.margin_m / m.ds_m)
    nr = math.ceil(2.0 * (m.rep_gap_m / 2.0 + m.pole_m + m.relax_m) / m.ds_m)
    if nr > nb:
        raise IRError(f"{el.name}: the repro head's reach is longer than a block")
    if m.head_distance_m <= (2 * nb + nm) * m.ds_m + _TAPE_ZONE_PAD_M:
        raise IRError(f"{el.name}: the heads are too close for the blocks")
    if el.sense_pos == el.sense_neg:
        raise IRError(f"{el.name}: its record head senses {el.sense_pos} against itself")
    if el.out in (GROUND, input_node):
        raise IRError(f"{el.name}: its repro head drives {el.out} (ground or the input)")


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

"""The parts library: macro parts that expand into circuit IR elements.

A circuit file (varimu.circuit.spec) lists parts; varimu.circuit.builder
resolves each part's values and calls the functions here, which know nothing
about any particular circuit. Every function takes plain numbers and node
names and returns IR elements (or a device model):

- resistor (with the zero end of a pot clamped to MIN_R_OHM), pot, tapped_pot,
  t_pad: resistive networks;
- transformer: windings on one core with winding resistance, leakage,
  self- and interwinding capacitance, the core (Jiles-Atherton or its linear
  limit), the joint gap and classical eddy loss;
- bridge: four diodes (and their cells' capacitance), vr_tube: a glow-discharge
  regulator, mains_sine: a winding fed from the mains;
- speaker: a moving-coil driver's electrical equivalent with its breakup modes, and
  the pressure at a listening point in front of its cabinet (varimu.devices.speaker);
- tube_instance, pentode_instance, device_instance: a device model's instance
  (parallel sections, emission and mu spreads, grid contact, junction area);
- Tolerance: per-part seeded draws in each part's tolerance band, and tubes'
  emission / mu draws.

Element names: a macro part named N makes elements named from N (a pot R105:
R105a, R105b; a T-pad AT101: RAT1011..3; a transformer T101: RT101_p,
LT101_p_lk, LT101_p, ...), so names stay the drawing's designators.
"""

from __future__ import annotations

import dataclasses
import math
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from varimu.circuit.ir import (
    GROUND,
    Capacitor,
    Coupling,
    Device,
    DeviceModel,
    Element,
    Inductor,
    Plate,
    Resistor,
    SineSource,
    Tape,
    TapeMedium,
    Vccs,
    VoltageSource,
    Winding,
)
from varimu.devices import capsule as cap
from varimu.devices import plate as plt
from varimu.devices import speaker as spk
from varimu.devices.core import MU0, TESLA_PER_V, MagneticCore, core_model, materials
from varimu.devices.diode import VT_TNOM, JunctionDiode, VacuumDiode
from varimu.devices.lamp import Lamp
from varimu.devices.pentode import Pentode
from varimu.devices.tape import TapeFormulation
from varimu.devices.triode import GridCurrent, KorenTriode, Triode, VariMuTriode

MIN_R_OHM = 1e-3  # stands in for the zero end of a pot (and a 0 dB pad's through path)


# --- Resistive networks ---------------------------------------------------------------


def resistor(name: str, a: str, b: str, ohms: float) -> Resistor:
    """A resistor, never below MIN_R_OHM (a pot's end, a pad's through path)."""
    return Resistor(name, a, b, max(ohms, MIN_R_OHM))


def taper(pos: float, mid: float | None = None) -> float:
    """The fraction of a track between its start and a wiper at rotation `pos` (0..1).
    Linear (mid None): pos. An audio (logarithmic) taper with `mid` of the track at half
    rotation: (a^pos - 1) / (a - 1), a = ((1 - mid) / mid)^2, which passes through 0,
    (0.5, mid) and 1."""
    if mid is None:
        return pos
    if not 0 < mid < 0.5:
        raise ValueError(f"taper mid {mid} must be in (0, 0.5)")
    a = ((1 - mid) / mid) ** 2
    return (a**pos - 1) / (a - 1)


def pot(
    name: str,
    end_a: str,
    wiper: str,
    end_b: str,
    total: float,
    pos: float,
    taper_mid: float | None = None,
) -> list[Resistor]:
    """Potentiometer `name` (elements <name>a, <name>b); pos = 0 puts the wiper at end_a,
    1 at end_b; the track follows `taper` from end_a (linear by default)."""
    f = pos if taper_mid is None else taper(pos, taper_mid)
    return [
        resistor(f"{name}a", end_a, wiper, f * total),
        resistor(f"{name}b", wiper, end_b, (1 - f) * total),
    ]


def rheostat(
    name: str,
    a: str,
    b: str,
    total: float,
    pos: float,
    taper_mid: float | None = None,
    reverse: bool = False,
) -> Resistor:
    """A potentiometer used as a variable resistor (its wiper tied to one end): the track
    between the other end and the wiper, taper(pos) x total (0 = no resistance). `reverse`:
    a reverse-taper (C) pot's track from the wiper to its far end, taper(1 - pos) x total
    (full resistance at 0, none at 1: turning it up lowers the resistance, evenly in log
    with an audio `taper_mid`)."""
    return resistor(name, a, b, taper(1.0 - pos if reverse else pos, taper_mid) * total)


def tapped_pot(
    name: str,
    end_a: str,
    tap: str,
    wiper: str,
    end_b: str,
    total: float,
    pos: float,
    tap_pos: float,
) -> list[Resistor]:
    """Potentiometer with a fixed tap; `pos` (wiper) and `tap_pos` are fractions of the
    track from end_a. Three segments, <name>a / b / c from end_a up, between end_a,
    the tap and the wiper in track order (a wiper at the tap counts as above it)."""
    if pos >= tap_pos:
        stops = [(end_a, 0.0), (tap, tap_pos), (wiper, pos), (end_b, 1.0)]
    else:
        stops = [(end_a, 0.0), (wiper, pos), (tap, tap_pos), (end_b, 1.0)]
    return [
        resistor(f"{name}{s}", a, b, (xb - xa) * total)
        for s, (a, xa), (b, xb) in zip("abc", stops, stops[1:], strict=False)
    ]


def t_pad(name: str, a: str, b: str, common: str, z: float, atten_db: float) -> list[Resistor]:
    """Symmetric T attenuator `name` between a and b (shunt leg to `common`),
    characteristic impedance z: R<name>1, R<name>2 in series through the inner node
    <name>_m, R<name>3 from it to common; at 0 dB one through resistor R<name>s."""
    if atten_db <= 0:
        return [resistor(f"R{name}s", a, b, 0.0)]
    k = 10 ** (atten_db / 20)
    r1 = z * (k - 1) / (k + 1)
    r2 = 2 * z * k / (k * k - 1)
    return [
        resistor(f"R{name}1", a, f"{name}_m", r1),
        resistor(f"R{name}2", f"{name}_m", b, r1),
        resistor(f"R{name}3", f"{name}_m", common, r2),
    ]


# --- Transformers -----------------------------------------------------------------------


@dataclass(frozen=True)
class WindingSpec:
    """One winding: from its dotted end to the other, turns relative to the reference
    winding, DC resistance, self-capacitance across its terminals (0 = none), and its own
    series leakage inductance (None: its share of the transformer's total)."""

    label: str
    dot: str
    other: str
    ratio: float = 1.0
    r_ohm: float = 0.0
    c_f: float = 0.0
    leak_h: float | None = None


@dataclass(frozen=True)
class CoreSpec:
    material: str
    area_m2: float
    path_m: float
    gap_m: float


def turns_for_inductance(l_h: float, core: CoreSpec) -> float:
    """Turns of a winding whose inductance is `l_h` in the core's linear limit (its
    susceptibility at the demagnetized origin) with the joint gap: the magnetic circuit
    is G u = N i with G the core's and the gap's conductance on the core node, and the
    winding's voltage N A TESLA_PER_V du/dt, so L = N^2 A TESLA_PER_V / G."""
    g = transformer_core("x", core).linear_conductance()
    if core.gap_m > 0:
        g += core.gap_m * TESLA_PER_V / MU0
    return math.sqrt(l_h * g / (core.area_m2 * TESLA_PER_V))


def transformer_core(name: str, core: CoreSpec) -> MagneticCore:
    """The Jiles-Atherton core of transformer `name` (model CORE_<NAME>)."""
    return core_model(f"CORE_{name.upper()}", core.material, core.path_m)


def transformer(
    name: str,
    windings: Sequence[WindingSpec],
    core: CoreSpec,
    *,
    turns: float,
    leakage_h: float | None,
    interwinding: tuple[tuple[str, str], str] | None = None,
    c_interwinding_f: float = 0.0,
    couplings: Sequence[tuple[str, str, float]] = (),
    cores: str = "ja",
) -> tuple[list[Element], MagneticCore]:
    """Transformer `name`: windings on one core (varimu.devices.core); the elements and
    its core model (in the IR's models only when `cores` is "ja").

    Per winding: its DC resistance, its leakage inductance (its own `leak_h` when it has
    one, else half the transformer's leakage `leakage_h`, which is referred to the
    reference winding of `turns` turns, times ratio^2: a designed transformer's windings
    each carry their own, an asymmetric pair included), the Winding on the core node
    <name>_core, and its
    self-capacitance across the terminals. A positive voltage from dot to other on
    one winding gives the same on the others. On the core node: the core (a
    MagneticCore, or its linear limit as a resistor when `cores` is "linear"), the
    joint gap (B g / mu0 of magnetomotive force) and classical eddy-current loss in
    the laminations (l_e sigma d^2 / 12 dB/dt).
    `couplings` (label_a, label_b, k): a Coupling K<NAME>_<a>_<b> between two windings'
    leakage inductors (a designed transformer's leakage as coupled series inductances,
    exact for any number of windings where a star of leak values would need a negative
    branch: varimu-components' `leakage.rs`); both windings need a leakage.
    `interwinding` ((end_a, end_b), other): `c_interwinding_f` split in half from both
    ends of a balanced winding to a terminal of the other side, as the 670
    replacements' balanced two-chamber construction has it (common mode only; one
    capacitor at one end couples in differential mode, and that made the 670's 6386
    stage oscillate at ~32 kHz, measured 2026-10-21).
    """
    upper = name.upper()
    mat = materials()[core.material]
    u = f"{name.lower()}_core"
    els: list[Element] = []
    for w in windings:
        n = f"{upper}_{w.label}"
        top = w.dot
        if w.r_ohm > 0:
            els.append(resistor(f"R{n}", top, f"{n}_r", w.r_ohm))
            top = f"{n}_r"
        if w.leak_h is not None:
            leak = w.leak_h
        elif leakage_h is not None:
            leak = 0.5 * leakage_h * w.ratio * w.ratio
        else:
            raise ValueError(
                f"{name}: winding {w.label} has no leakage (leak, or the leakage_h total)"
            )
        if leak > 0:
            els.append(Inductor(f"L{n}_lk", top, f"{n}_l", leak))
            top = f"{n}_l"
        els.append(Winding(f"L{n}", top, w.other, u, w.ratio * turns, core.area_m2))
        if w.c_f > 0:
            els.append(Capacitor(f"C{n}", w.dot, w.other, w.c_f))
    leaks = {e.name for e in els if isinstance(e, Inductor)}
    for a, b, k in couplings:
        la, lb = f"L{upper}_{a}_lk", f"L{upper}_{b}_lk"
        for lbl, ind in ((a, la), (b, lb)):
            if ind not in leaks:
                raise ValueError(f"{name}: leak_couplings: winding {lbl} has no leakage inductor")
        els.append(Coupling(f"K{upper}_{a}_{b}", la, lb, k))
    if interwinding and c_interwinding_f > 0:
        (end_a, end_b), other = interwinding
        half = 0.5 * c_interwinding_f
        els.append(Capacitor(f"C{upper}_iwa", end_a, other, half))
        els.append(Capacitor(f"C{upper}_iwb", end_b, other, half))
    model = transformer_core(name, core)
    if cores == "linear":
        els.append(Resistor(f"R{upper}_core", u, GROUND, 1 / model.linear_conductance()))
    else:
        els.append(Device(f"X{upper}_CORE", model.name, (u, GROUND)))
    if core.gap_m > 0:
        els.append(Resistor(f"R{upper}_gap", u, GROUND, MU0 / (core.gap_m * TESLA_PER_V)))
    eddy = core.path_m * mat["lamination_m"] ** 2 / (12 * mat["resistivity_ohm_m"]) * TESLA_PER_V
    els.append(Capacitor(f"C{upper}_eddy", u, GROUND, eddy))
    return els, model


# --- Rectifiers, references, sources ----------------------------------------------------


def bridge(
    name: str,
    ac_a: str,
    ac_b: str,
    plus: str,
    minus: str,
    model: DeviceModel,
    arm_c_f: float = 0.0,
) -> list[Element]:
    """Bridge rectifier `name`: arms D<name>A (ac_a to plus), B (ac_b to plus), C (minus
    to ac_a), D (minus to ac_b), then each arm's capacitance C<name>A..D (0 = none),
    e.g. a selenium cell's."""
    arms = [("A", ac_a, plus), ("B", ac_b, plus), ("C", minus, ac_a), ("D", minus, ac_b)]
    prefix = "D" if isinstance(model, JunctionDiode) else "X"
    els: list[Element] = [Device(f"{prefix}{name}{s}", model.name, (a, k)) for s, a, k in arms]
    if arm_c_f > 0:
        els += [Capacitor(f"C{name}{s}", a, k, arm_c_f) for s, a, k in arms]
    return els


def burning_voltage(model: JunctionDiode, operating_v: float, ref_current_a: float) -> float:
    """A glow tube modeled as `model` in series with a fixed voltage: that voltage, so the
    pair drops `operating_v` at `ref_current_a`."""
    drop = model.n * VT_TNOM * math.log1p(ref_current_a / model.is_a) + ref_current_a * model.rs_ohm
    return operating_v - drop


def vr_tube(
    name: str,
    anode: str,
    mid: str,
    cathode: str,
    model: JunctionDiode,
    operating_v: float,
    ref_current_a: float,
) -> list[Element]:
    """Glow-discharge voltage reference `name`: the diode D<name> (its slope) from the
    anode to `mid`, then its burning voltage, a source named `name`, to the cathode
    (no ignition: lit from the DC operating point on)."""
    return [
        Device(f"D{name}", model.name, (anode, mid)),
        VoltageSource(name, mid, cathode, burning_voltage(model, operating_v, ref_current_a)),
    ]


def mains_sine(
    name: str,
    pos: str,
    neg: str,
    v_rms: float,
    mains_v_rms: float,
    rated_mains_v_rms: float,
    mains_hz: float,
    phase_deg: float,
) -> SineSource:
    """A winding fed from the mains: `v_rms` at the rated mains voltage, scaled with the
    actual mains (phase 90 starts a run at the peak)."""
    scale = mains_v_rms / rated_mains_v_rms
    return SineSource(name, pos, neg, 0.0, math.sqrt(2) * v_rms * scale, mains_hz, phase_deg)


# --- Speakers --------------------------------------------------------------------------------


def speaker_driver(
    name: str, plus: str, minus: str, s: spk.Speaker
) -> tuple[list[Element], list[tuple[str, float]]]:
    """The driver's electrical equivalent (varimu.devices.speaker): the elements, and each
    radiating node (its voltage to `minus` is BL times a velocity) with its area. Element
    names: R<name>_re, L<name>_le, L<name>_l2 || R<name>_r2, then C<name>_m, L<name>_cms,
    R<name>_rms on the coil's node <name>_m, and per mode k (from 1) R<name>_k || L<name>_k
    to its node <name>_k<k>, C<name>_k<k> from there to minus."""
    n, upper = name.lower(), name.upper()
    bl2 = s.bl_tm * s.bl_tm
    # Plain left-to-right sums (Python 3.12's sum() compensates; Rust's builder doesn't).
    modes_kg, modes_m2 = 0.0, 0.0
    for m in s.modes:
        modes_kg += m.mass_kg
        modes_m2 += m.area_m2
    m0 = s.mms_kg - modes_kg
    s0 = s.sd_m2 - modes_m2
    coil = f"{n}_m"
    els: list[Element] = [
        Resistor(f"R{upper}_re", plus, f"{n}_l", s.re_ohm),
        Inductor(f"L{upper}_le", f"{n}_l", f"{n}_e", s.le_h),
        Inductor(f"L{upper}_l2", f"{n}_e", coil, s.l2_h),
        Resistor(f"R{upper}_r2", f"{n}_e", coil, s.r2_ohm),
        Capacitor(f"C{upper}_m", coil, minus, m0 / bl2),
        Inductor(f"L{upper}_cms", coil, minus, s.cms_m_per_n * bl2),
        Resistor(f"R{upper}_rms", coil, minus, bl2 / s.rms_ns_per_m),
    ]
    radiating = [(coil, s0)]
    for k, m in enumerate(s.modes, 1):
        w = 2 * math.pi * m.f_hz
        stiffness = m.mass_kg * (w * w)
        damping = w * m.mass_kg / m.q
        node = f"{n}_k{k}"
        els += [
            Resistor(f"R{upper}_k{k}", coil, node, bl2 / damping),
            Inductor(f"L{upper}_k{k}", coil, node, bl2 / stiffness),
            Capacitor(f"C{upper}_k{k}", node, minus, m.mass_kg / bl2),
        ]
        radiating.append((node, m.area_m2))
    return els, radiating


def speaker_readout(
    name: str,
    minus: str,
    out: str,
    s: spk.Speaker,
    radiating: Sequence[tuple[str, float]],
    cabinet: spk.Cabinet,
    distance_m: float,
) -> list[Element]:
    """The sound pressure at `out` (pascals as volts, to ground), on axis at `distance_m`
    in front of the cabinet: front wave, back wave around the edges (varimu.devices
    .speaker). It draws no current from the driver (every coupling is a Vccs)."""
    n, upper = name.lower(), name.upper()
    r0 = spk.READOUT_OHM
    pf, lp = f"{n}_pf", f"{n}_b"
    els: list[Element] = []
    # Front: rho S a / (2 pi r) per radiating node, as currents through one 1 H inductor
    # (its voltage is the derivative of the current, the voltage BL v giving BL a).
    for i, (node, area) in enumerate(radiating):
        gm = spk.RHO_AIR_KG_M3 * area / (2 * math.pi * distance_m * s.bl_tm)
        if gm != 0:
            els.append(Vccs(f"G{upper}_a{i}", GROUND, pf, node, minus, gm))
    els.append(Inductor(f"L{upper}_pf", pf, GROUND, 1.0))
    # Back: the directivity pole, then a doubly terminated delay line, tapped per edge.
    fb = spk.directivity_pole_hz(s.sd_m2)
    els += [
        Vccs(f"G{upper}_b", GROUND, lp, pf, GROUND, 1 / r0),
        Resistor(f"R{upper}_b", lp, GROUND, r0),
        Capacitor(f"C{upper}_b", lp, GROUND, 1 / (2 * math.pi * fb * r0)),
    ]
    taps = spk.edge_taps(cabinet, distance_m)
    last = max(t for t, _ in taps)
    tau = spk.LADDER_SECTION_S
    els += [
        Vccs(f"G{upper}_d", GROUND, f"{n}_d0", lp, GROUND, 2 / r0),
        Resistor(f"R{upper}_d0", f"{n}_d0", GROUND, r0),
        Capacitor(f"C{upper}_d0", f"{n}_d0", GROUND, tau / r0 / 2),
    ]
    for i in range(1, last + 1):
        els.append(Inductor(f"L{upper}_d{i}", f"{n}_d{i - 1}", f"{n}_d{i}", tau * r0))
        c = tau / r0 if i < last else tau / r0 / 2
        els.append(Capacitor(f"C{upper}_d{i}", f"{n}_d{i}", GROUND, c))
    els.append(Resistor(f"R{upper}_dt", f"{n}_d{last}", GROUND, r0))
    # Heard: p_f minus the edges' back waves.
    els.append(Vccs(f"G{upper}_o", GROUND, out, pf, GROUND, 1 / r0))
    for e, (tap, weight) in enumerate(taps):
        if weight != 0:
            els.append(Vccs(f"G{upper}_o{e}", GROUND, out, f"{n}_d{tap}", GROUND, -weight / r0))
    els.append(Resistor(f"R{upper}_o", out, GROUND, r0))
    return els


def speaker(
    name: str,
    plus: str,
    minus: str,
    out: str,
    s: spk.Speaker,
    cabinet: spk.Cabinet,
    distance_m: float,
) -> list[Element]:
    """Speaker `name` between plus and minus, its sound pressure on `out`."""
    els, radiating = speaker_driver(name, plus, minus, s)
    return els + speaker_readout(name, minus, out, s, radiating, cabinet, distance_m)


def capsule(
    name: str, front: str, backplate: str, out: str, c: cap.Capsule, polarization_v: float
) -> list[Element]:
    """Condenser capsule `name` (varimu.devices.capsule): its front pressure on `front`
    (pascals as volts, to ground: the ambient), the backplate electrode `backplate`, the
    other electrode `out`. Elements: L<NAME>_m (the diaphragm's and radiation mass) from
    front to <name>_1, C<NAME>_d (its compliance at the polarization) to the gap
    <name>_g, C<NAME>_g, R<NAME>_h and L<NAME>_h (squeeze film and holes) to the cavity
    <name>_c, C<NAME>_c, R<NAME>_v (the vent) back to front; the electrical port:
    G<NAME>_x into R<NAME>_x (the open-circuit voltage on <name>_e re the backplate),
    C<NAME>_0 from there to out, C<NAME>_s (stray) from out to the backplate."""
    n, upper = name.lower(), name.upper()
    cd = c.c_diaphragm_at(polarization_v)
    k = c.volts_per_volume(polarization_v) * cd  # volts per volt across C_d
    one, gap, holes, cav, e = f"{n}_1", f"{n}_g", f"{n}_h", f"{n}_c", f"{n}_e"
    els: list[Element] = [
        Inductor(f"L{upper}_m", front, one, c.m_front),
        Capacitor(f"C{upper}_d", one, gap, cd),
        Capacitor(f"C{upper}_g", gap, GROUND, c.c_gap),
        Resistor(f"R{upper}_h", gap, holes, c.r_holes),
        Inductor(f"L{upper}_h", holes, cav, c.m_holes),
        Capacitor(f"C{upper}_c", cav, GROUND, c.c_cavity),
        Resistor(f"R{upper}_v", cav, front, c.r_vent),
        Vccs(f"G{upper}_x", backplate, e, one, gap, k / cap.READOUT_OHM),
        Resistor(f"R{upper}_x", e, backplate, cap.READOUT_OHM),
        Capacitor(f"C{upper}_0", e, out, c.c0_f),
    ]
    if c.c_stray_f > 0:
        els.append(Capacitor(f"C{upper}_s", out, backplate, c.c_stray_f))
    return els


def capsule_dual(
    name: str,
    front: str,
    rear: str,
    backplate: str,
    out_front: str,
    out_rear: str,
    c: cap.DualCapsule,
    polarization_front_v: float,
    polarization_rear_v: float,
) -> list[Element]:
    """Dual-diaphragm capsule `name` (varimu.devices.capsule, DualCapsule): the outside
    pressures on `front` and `rear` (pascals as volts), the backplate electrode, each
    diaphragm's electrode out_front / out_rear. Per side s (f, r): L<NAME>_m<s> from its
    pressure to <name>_<s>1, C<NAME>_d<s> (at its polarization) to the gap <name>_<s>g,
    C<NAME>_g<s>, R<NAME>_f<s> (squeeze film) to <name>_<s>h, R<NAME>_b<s> into the blind
    holes <name>_<s>b with C<NAME>_b<s>; the through-holes R<NAME>_t, L<NAME>_t from fh via
    <name>_t to rh, R<NAME>_l (the leak) from <name>_t to ground; each side's readout as
    the pressure capsule's (G<NAME>_x<s>, R<NAME>_x<s>, C<NAME>_0<s>, C<NAME>_s<s>); an
    unpolarized side (0 V) has no source: C<NAME>_0<s> from the backplate to its electrode."""
    n, upper = name.lower(), name.upper()
    els: list[Element] = []
    for s, outside, out, e0 in (
        ("f", front, out_front, polarization_front_v),
        ("r", rear, out_rear, polarization_rear_v),
    ):
        cd = c.c_diaphragm_at(e0)
        k = c.volts_per_volume(e0) * cd
        one, gap, holes, blind, e = (f"{n}_{s}{x}" for x in ("1", "g", "h", "b", "e"))
        els += [
            Inductor(f"L{upper}_m{s}", outside, one, c.m_diaphragm),
            Capacitor(f"C{upper}_d{s}", one, gap, cd),
            Capacitor(f"C{upper}_g{s}", gap, GROUND, c.c_gap),
            Resistor(f"R{upper}_f{s}", gap, holes, c.r_film),
            Resistor(f"R{upper}_b{s}", holes, blind, c.r_blind),
            Capacitor(f"C{upper}_b{s}", blind, GROUND, c.c_blind),
        ]
        if e0 == 0.0:  # unpolarized: no source, C0 straight from the backplate
            els.append(Capacitor(f"C{upper}_0{s}", backplate, out, c.c0_f))
        else:
            els += [
                Vccs(f"G{upper}_x{s}", backplate, e, one, gap, k / cap.READOUT_OHM),
                Resistor(f"R{upper}_x{s}", e, backplate, cap.READOUT_OHM),
                Capacitor(f"C{upper}_0{s}", e, out, c.c0_f),
            ]
        if c.c_stray_f > 0:
            els.append(Capacitor(f"C{upper}_s{s}", out, backplate, c.c_stray_f))
    through = f"{n}_t"
    els += [
        Resistor(f"R{upper}_t", f"{n}_fh", through, c.r_through),
        Inductor(f"L{upper}_t", through, f"{n}_rh", c.m_through),
        Resistor(f"R{upper}_l", through, GROUND, c.r_leak),
    ]
    return els


# --- Device instances -----------------------------------------------------------------------


def tube_instance(
    base: Triode,
    name: str,
    *,
    n_parallel: int = 1,
    emission_scale: float = 1.0,
    mu_spread: float = 1.0,
    grid_contact_v: float | None = None,
) -> Triode:
    """A triode instance: n identical sections in parallel, with this instance's spreads.

    Emission scales plate current (Kg1 / scale), mu_spread scales every
    section's mu, and the grid current, capacitances and current scale with n.
    """
    k = n_parallel * emission_scale
    pl = base.plate
    if isinstance(pl, VariMuTriode):
        plate = dataclasses.replace(pl, mus=tuple(m * mu_spread for m in pl.mus), kg1=pl.kg1 / k)
    elif isinstance(pl, KorenTriode):
        plate = dataclasses.replace(pl, mu=pl.mu * mu_spread, kg1=pl.kg1 / k)
    else:
        raise TypeError(type(pl))
    grid = base.grid
    if grid is not None:
        grid = GridCurrent(
            grid.perveance * n_parallel,
            grid.contact_v if grid_contact_v is None else grid_contact_v,
            grid.smooth_v,
        )
    return Triode(
        name,
        plate,
        grid,
        c_gk=base.c_gk * n_parallel,
        c_gp=base.c_gp * n_parallel,
        c_pk=base.c_pk * n_parallel,
    )


def pentode_instance(
    base: Pentode,
    name: str,
    *,
    n_parallel: int = 1,
    emission_scale: float = 1.0,
    mu_spread: float = 1.0,
) -> Pentode:
    """n identical pentodes in parallel: n times the plate, screen and grid current and
    the capacitances; emission scales the plate and screen current, mu_spread mu."""
    m, k = base.model, n_parallel * emission_scale
    model = dataclasses.replace(m, mu=m.mu * mu_spread, kg1=m.kg1 / k, kg2=m.kg2 / k)
    g = base.grid
    grid = None if g is None else dataclasses.replace(g, perveance=g.perveance * n_parallel)
    return Pentode(
        name,
        model,
        grid,
        c_g1k=base.c_g1k * n_parallel,
        c_g1p=base.c_g1p * n_parallel,
        c_pk=base.c_pk * n_parallel,
    )


def device_instance(
    base: DeviceModel,
    name: str,
    *,
    n_parallel: int = 1,
    emission_scale: float = 1.0,
    mu_spread: float = 1.0,
    grid_contact_v: float | None = None,
    area: float = 1.0,
) -> DeviceModel:
    """An instance of any device model. Triodes and pentodes: see tube_instance /
    pentode_instance; a vacuum diode: perveance times n and emission; a junction
    diode: `area` times the device file's (saturation current times it, series
    resistance over it: SPICE's area factor)."""
    if isinstance(base, Triode):
        return tube_instance(
            base,
            name,
            n_parallel=n_parallel,
            emission_scale=emission_scale,
            mu_spread=mu_spread,
            grid_contact_v=grid_contact_v,
        )
    if grid_contact_v is not None:
        raise ValueError(f"{name}: grid_contact_v is for triodes")
    if isinstance(base, Pentode):
        return pentode_instance(
            base, name, n_parallel=n_parallel, emission_scale=emission_scale, mu_spread=mu_spread
        )
    if mu_spread != 1.0:
        raise ValueError(f"{name}: mu_spread is for triodes and pentodes")
    if isinstance(base, VacuumDiode):
        return dataclasses.replace(
            base, name=name, perveance=base.perveance * n_parallel * emission_scale
        )
    if isinstance(base, JunctionDiode):
        if emission_scale != 1.0:
            raise ValueError(f"{name}: a junction diode has no emission spread")
        k = n_parallel * area
        return dataclasses.replace(base, name=name, is_a=base.is_a * k, rs_ohm=base.rs_ohm / k)
    if isinstance(base, Lamp):
        if (n_parallel, emission_scale, area) != (1, 1.0, 1.0):
            raise ValueError(f"{name}: a lamp takes no parallel, emission or area")
        return dataclasses.replace(base, name=name)
    raise TypeError(f"{name}: no instances of {type(base).__name__}")


# --- Per-instance tolerance -------------------------------------------------------------------


@dataclass(frozen=True)
class Tolerance:
    """A unit's part draws: u uniform in [-1, 1] per part from
    default_rng([seed, crc32(designator)]) (adding a part doesn't move the others'
    draws), times `spread` and the part's band in percent (minus, plus). Tubes deviate
    in emission and mu by their own two draws times tube_pct (emission, mu)."""

    seed: int
    spread: float
    bands: Mapping[str, tuple[float, float]]  # class -> (minus %, plus %)
    classes: Mapping[str, str]  # designator -> class
    combined: Mapping[str, Sequence[str]]  # element designator -> the parts it stands for
    tube_pct: tuple[float, float] = (0.0, 0.0)

    def draws(self, designator: str, n: int = 1) -> np.ndarray:
        rng = np.random.default_rng([self.seed, zlib.crc32(designator.encode())])
        return self.spread * rng.uniform(-1.0, 1.0, n)

    def tube_deviation(self, designator: str) -> tuple[float, float]:
        """(emission factor, mu factor) of tube `designator`."""
        ue, um = self.draws(designator, 2)
        return 1 + ue * self.tube_pct[0] / 100, 1 + um * self.tube_pct[1] / 100

    def part_factor(self, designator: str, cls: str) -> float:
        """The value factor of one part: its draw in its class's band."""
        u = float(self.draws(designator)[0])
        minus, plus = self.bands[cls]
        pct = minus if u < 0 else plus
        return 1 + u * pct / 100

    def parts_of(self, designator: str) -> list[str]:
        return list(self.combined.get(designator, [designator]))

    def factor(self, designator: str) -> float:
        """The factor of an element standing for part `designator` (the mean of its
        parts' factors when it combines several). KeyError: a part without a class."""
        parts = self.parts_of(designator)
        missing = [x for x in parts if x not in self.classes]
        if missing:
            raise KeyError(missing)
        return float(np.mean([self.part_factor(x, self.classes[x]) for x in parts]))

    def apply(self, elements: Sequence[Element], designator: str) -> list[Element]:
        """Every resistor and capacitor of a part times the part's factor."""
        f = self.factor(designator)
        out: list[Element] = []
        for el in elements:
            if isinstance(el, Resistor):
                out.append(dataclasses.replace(el, r_ohm=el.r_ohm * f))
            elif isinstance(el, Capacitor):
                out.append(dataclasses.replace(el, c_f=el.c_f * f))
            else:
                out.append(el)
        return out


# --- Media (docs/REVERB_PLAN.md) --------------------------------------------------------


def plate(
    name: str, plus: str, minus: str, out: str, c: plt.PlateComponent, decay_500hz_s: float
) -> list[Element]:
    """A plate reverb's plate between its exciter's terminals (plus, minus) and its pickup's
    (out to ground): the exciter coil (L<name>_le, then R<name>_mot, the plate's resistive
    load BL^2 / (8 sqrt(D rho H)), then R<name>_re into minus), the plate V<name> sensing
    the coil's current across R<name>_re (force BL / Re per volt) and driving <name>_p with
    the pickup's open-circuit voltage, and the pickup's capacitance C<name>_pu from there
    to out. The damper set to decay_500hz_s at 500 Hz (varimu.devices.plate)."""
    n, upper = name.lower(), name.upper()
    bl = c.exciter_bl_tm
    return [
        Inductor(f"L{upper}_le", plus, f"{n}_a", c.exciter_le_h),
        Resistor(f"R{upper}_mot", f"{n}_a", f"{n}_c", bl * bl / plt.plate_impedance_ns_per_m(c)),
        Resistor(f"R{upper}_re", f"{n}_c", minus, c.exciter_re_ohm),
        Plate(
            name=f"V{upper}",
            sense_pos=f"{n}_c",
            sense_neg=minus,
            force_per_v=bl / c.exciter_re_ohm,
            out=f"{n}_p",
            out_per_m_s2=c.pickup_v_per_m_s2,
            lx_m=c.lx_m,
            ly_m=c.ly_m,
            thickness_m=c.thickness_m,
            density_kg_m3=c.density_kg_m3,
            youngs_pa=c.youngs_pa,
            poisson=c.poisson,
            tension_n_m=c.tension_n_m,
            drive_xy=c.drive_xy,
            pickup_xy=c.pickup_xy,
            f_max_hz=c.f_max_hz,
            decay=plt.decay_table(c, decay_500hz_s),
            tail_db=c.tail_db,
        ),
        Capacitor(f"C{upper}_pu", f"{n}_p", out, c.pickup_c_f),
    ]


#: The tape part's numerics (TAPE_PLAN.md, "Speed" and TM4: each a measured setting;
#: the same as varimu-circuit's `tape::NUMERICS`).
TAPE_LAYERS = 6
#: Cells per bias wavelength (`TapeMachineSpec.ds_m`: 0.5 um at 15 ips and 100 kHz).
TAPE_CELLS_PER_BIAS_WAVELENGTH = 7.62
TAPE_TABLE_STEP = 1 / 40
TAPE_ZONE_FLOOR_A_M = 120.0 * (1000.0 / (4.0 * math.pi))  # 120 Oe
TAPE_DEMAG_ITERATIONS = 8
TAPE_DEMAG_TOL = 2e-3
TAPE_BLOCK_M = 16e-3
TAPE_MARGIN_M = 0.5e-3

#: The tape part's physical values, in the order the macro takes them.
TAPE_VALUES = (
    "speed_m_s",
    "f_bias_hz",
    "bias_a_m",
    "rec_gap_m",
    "rep_gap_m",
    "pole_m",
    "relax_m",
    "spacing_m",
    "track_m",
    "head_distance_m",
    "rec_l_h",
    "rec_r_ohm",
    "rec_h_per_a",
    "rep_l_h",
    "rep_r_ohm",
    "rep_h_per_a",
)


#: The values only the medium's own bias reads (the literal bias leaves them out).
TAPE_OWN_BIAS = ("bias_a_m", "rec_l_h")

#: The transport (TAPE_PLAN.md TM3; varimu.devices.tape_machine.TapeMachineSpec's fields of
#: the same names): optional, all or none (none: the tape runs at a constant speed).
TAPE_TRANSPORT = (
    "capstan_d_m",
    "capstan_rms",
    "roller_d_m",
    "roller_rms",
    "reel_r_m",
    "reel_rms",
    "hunting_hz",
    "hunting_q",
    "hunting_rms",
    "scrape_span_m",
    "scrape_c_m_s",
    "scrape_q",
    "scrape_rms",
)


def tape_transport(speed_m_s: float, tr: Mapping[str, float]) -> tuple[tuple, tuple]:
    """The speed's components from TAPE_TRANSPORT's values, as
    `TapeMachineSpec.transport` makes them: periodic (relative peak, Hz, phase) for the
    capstan's runout, the rubber idler and the supply reel; random resonances (relative
    rms, Hz, Q) for the motor's hunting and scrape flutter (the free span's first
    longitudinal mode, c / 2L)."""
    v = speed_m_s
    periodic = (
        (tr["capstan_rms"] * math.sqrt(2.0), v / (math.pi * tr["capstan_d_m"]), 0.0),
        (tr["roller_rms"] * math.sqrt(2.0), v / (math.pi * tr["roller_d_m"]), 1.0),
        (tr["reel_rms"] * math.sqrt(2.0), v / (2.0 * math.pi * tr["reel_r_m"]), 2.0),
    )
    random = (
        (tr["hunting_rms"], tr["hunting_hz"], tr["hunting_q"]),
        (tr["scrape_rms"], tr["scrape_c_m_s"] / (2.0 * tr["scrape_span_m"]), tr["scrape_q"]),
    )
    return periodic, random


def tape(
    name: str,
    rec_plus: str,
    rec_minus: str,
    out: str,
    t: TapeFormulation,
    v: Mapping[str, float],
    bias_substeps: int | None = None,
    transport: Mapping[str, float] | None = None,
) -> list[Element]:
    """Magnetic tape t between a record head and a repro head (docs/TAPE_PLAN.md, TM4;
    varimu.devices.tape_machine.TapeStream): the record coil between rec_plus and
    rec_minus (L<name>_rec, then R<name>_rec, its winding resistance, into rec_minus), the
    tape V<name> sensing the coil's current across R<name>_rec (rec_h_per_a over it: the
    deep-gap field per volt), recorded with its own AC bias (bias_a_m, the deep-gap field,
    at f_bias_hz), and the repro coil's EMF on <name>_e behind the coil's inductance and
    resistance (L<name>_rep, R<name>_rep) to out. v: the physical values of TAPE_VALUES
    (heads' geometry, transport, coils); the numerics are the module's TAPE_* settings.
    transport: TAPE_TRANSPORT's values (wow and flutter, `tape_transport`), or None (a
    constant speed).

    bias_substeps (M): the literal bias (TAPE_PLAN.md TM5, option A). rec_plus and
    rec_minus are then the record coil's resistance's ends, drawn in a multi-rate section
    of M steps with the circuit's own oscillator (the coil isn't the part's: no
    L<name>_rec / R<name>_rec; bias_a_m and rec_l_h aren't read); the tape senses the
    head's whole current there, bias included (`TapeStream`'s literal mode). f_bias_hz is
    then the oscillator's nominal frequency, for the cells' length."""
    n, upper = name.lower(), name.upper()
    o = t.orientation
    p = t.preisach
    periodic, random = tape_transport(v["speed_m_s"], transport) if transport else ((), ())
    medium = TapeMedium(
        hc_median_a_m=p.hc_median_a_m,
        sigma_ln_hc=p.sigma_ln_hc,
        sigma_hi_a_m=p.sigma_hi_a_m,
        h_max_a_m=p.h_max_a_m,
        n_table=p.n_table,
        ms_a_m=t.ms_a_m,
        coating_m=t.coating_m,
        kappa=o.kappa,
        orientations=o.n,
        speed_m_s=v["speed_m_s"],
        f_bias_hz=v["f_bias_hz"],
        hg_bias_a_m=0.0 if bias_substeps else v["bias_a_m"],
        bias_phase_rad=0.0,
        rec_gap_m=v["rec_gap_m"],
        rep_gap_m=v["rep_gap_m"],
        pole_m=v["pole_m"],
        relax_m=v["relax_m"],
        spacing_m=v["spacing_m"],
        track_m=v["track_m"],
        head_distance_m=v["head_distance_m"],
        rep_h_per_a=v["rep_h_per_a"],
        layers=TAPE_LAYERS,
        ds_m=v["speed_m_s"] / (v["f_bias_hz"] * TAPE_CELLS_PER_BIAS_WAVELENGTH),
        table_step=TAPE_TABLE_STEP,
        zone_floor_a_m=TAPE_ZONE_FLOOR_A_M,
        local_zones=True,
        demag_iterations=TAPE_DEMAG_ITERATIONS,
        demag_tol=TAPE_DEMAG_TOL,
        head_image=True,
        lam_min_m=3.0 * v["speed_m_s"] / v["f_bias_hz"],
        block_m=TAPE_BLOCK_M,
        margin_m=TAPE_MARGIN_M,
        flutter=periodic,
        flutter_noise=random,
        particle_volume_m3=t.noise.particle_volume_m3 if t.noise else 0.0,
        packing=t.noise.packing if t.noise else 0.0,
        packing_sigma=t.noise.packing_sigma if t.noise else 0.0,
        packing_corr_m=t.noise.packing_corr_m if t.noise else 0.0,
        bias_substeps=bias_substeps,
    )
    h_per_v = v["rec_h_per_a"] / v["rec_r_ohm"]
    repro = [
        Inductor(f"L{upper}_rep", f"{n}_e", f"{n}_b", v["rep_l_h"]),
        Resistor(f"R{upper}_rep", f"{n}_b", out, v["rep_r_ohm"]),
    ]
    if bias_substeps:
        return [Tape(f"V{upper}", rec_plus, rec_minus, h_per_v, f"{n}_e", medium), *repro]
    return [
        Inductor(f"L{upper}_rec", rec_plus, f"{n}_a", v["rec_l_h"]),
        Resistor(f"R{upper}_rec", f"{n}_a", rec_minus, v["rec_r_ohm"]),
        Tape(f"V{upper}", f"{n}_a", rec_minus, h_per_v, f"{n}_e", medium),
        *repro,
    ]

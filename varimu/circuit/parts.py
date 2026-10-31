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
    Device,
    DeviceModel,
    Element,
    Inductor,
    Plate,
    Resistor,
    SineSource,
    Vccs,
    VoltageSource,
    Winding,
)
from varimu.devices import plate as plt
from varimu.devices import speaker as spk
from varimu.devices.core import MU0, TESLA_PER_V, MagneticCore, core_model, materials
from varimu.devices.diode import VT_TNOM, JunctionDiode, VacuumDiode
from varimu.devices.pentode import Pentode
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
    winding, DC resistance, self-capacitance across its terminals (0 = none)."""

    label: str
    dot: str
    other: str
    ratio: float = 1.0
    r_ohm: float = 0.0
    c_f: float = 0.0


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
    leakage_h: float,
    interwinding: tuple[tuple[str, str], str] | None = None,
    c_interwinding_f: float = 0.0,
    cores: str = "ja",
) -> tuple[list[Element], MagneticCore]:
    """Transformer `name`: windings on one core (varimu.devices.core); the elements and
    its core model (in the IR's models only when `cores` is "ja").

    Per winding: its DC resistance, its leakage inductance (half the transformer's
    leakage `leakage_h`, which is referred to the reference winding of `turns` turns,
    times ratio^2), the Winding on the core node <name>_core, and its
    self-capacitance across the terminals. A positive voltage from dot to other on
    one winding gives the same on the others. On the core node: the core (a
    MagneticCore, or its linear limit as a resistor when `cores` is "linear"), the
    joint gap (B g / mu0 of magnetomotive force) and classical eddy-current loss in
    the laminations (l_e sigma d^2 / 12 dB/dt).
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
        leak = 0.5 * leakage_h * w.ratio * w.ratio
        if leak > 0:
            els.append(Inductor(f"L{n}_lk", top, f"{n}_l", leak))
            top = f"{n}_l"
        els.append(Winding(f"L{n}", top, w.other, u, w.ratio * turns, core.area_m2))
        if w.c_f > 0:
            els.append(Capacitor(f"C{n}", w.dot, w.other, w.c_f))
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

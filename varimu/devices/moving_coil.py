"""Moving-coil microphone cartridges as lumped acoustic networks (docs/SM57_PLAN.md, SM2).

A cartridge is a component (kind `moving_coil`, config/components/<name>/<N>.yaml): its
geometry and materials (sourced), and the lumped elements derived from them here at fit
time (`varimu fit-devices`), so both circuit builders read the same numbers and only
instantiate them (varimu.circuit.parts.moving_coil; varimu-circuit's moving_coil.rs).

The acoustic side is in the impedance analogy with pressures as volts (Pa = V) and volume
velocities as currents (m^3/s = A), as `capsule.py`: an acoustic mass (kg/m^4) is an
inductance, a compliance (m^5/N) a capacitance, a resistance (Pa s/m^3) a resistance. Its
topology is data, not code: the geometry's `network` is a list of physical elements
between named nodes, `front` (the pressure at the front entry), `rear` (at the rear
entries), `0` (the ambient) and the cartridge's own nodes, each compiled by its kind:

    screen     a cloth, felt or mesh: a specific flow resistance (rayl, Pa s/m) over its
               open area, R = rayl / area; its air mass rho t / (porosity area) when it
               has a thickness (a woven screen's is negligible: thickness_m 0)
    tube       n parallel round ducts (Poiseuille): R = 8 mu l / (n pi r^4), M = 4 rho l'
               / (3 n pi r^2), l' with an end correction END_CORRECTION r per open end;
               with `wide_at_hz`, a duct wide against its viscous boundary layer there
               (sqrt(2 mu / rho w) << r: Crandall's limit, e.g. Kinsler et al.,
               "Fundamentals of Acoustics", sec. 10.8; Beranek, "Acoustics"): R = l'
               sqrt(2 w rho mu) / (n pi r^3), M = rho l' / (n pi r^2), the resistance
               taken at that frequency (a lumped element can't follow its sqrt(f))
    slit       a thin gap between parallel walls (the coil's annular gap): width w (the
               gap), breadth b (the circumference), length l along the flow: R = 12 mu l /
               (b w^3), M = 6 rho l / (5 b w) (plane Poiseuille flow); with `wide_at_hz`,
               a channel wide against its boundary layer there (a ribbon's pole-piece
               channel): plug flow, M = rho l / (b w), and Crandall's wall loss on both
               walls, R = l sqrt(2 w rho mu) / (b w^2) (the tube's formula with the walls'
               area 2 b l over the section b w), the resistance taken at that frequency
    radiation  an opening's radiation load into the free field, from the pressure there
               (its blocked pressure, a: the entry) to the opening (b): a rectangle
               width_m x length_m or a disk radius_m in a baffle, its low-frequency mass
               rho I / (2 pi S^2) (the Rayleigh integral's self term, I the integral of
               1 / |r - r'| over the face twice: `rectangle_self_integral`; a disk's gives
               8 rho / (3 pi^2 r)) in parallel with its high-frequency limit rho c / S
               (a lumped approximation: the real part rises as w^2 below the corner,
               within ~45% of the piston's rho w^2 / (2 pi c), then flattens). Elements
               <name>_m (L), <name>_r (R), both a -> b
    cavity    a closed volume of air to the ambient's reference: C = V / (gamma P0)
               (adiabatic: the cavities are wide against the thermal boundary layer), or
               its compliance_m5_n where a fit gives it
    film       a thin layer of air (the cap's: between the resonator plate and the dome) of
               radius radius_m and height height_m, filled through a ring of holes at
               ring_radius_m: radial viscous flow between parallel walls, outward to the rim
               and inward to a quarter of the ring's radius (the dome's apex, where the
               layer has little volume), the two paths in parallel, each R = 6 mu ln(r2 /
               r1) / (pi h^3), M = 6 rho ln(r2 / r1) / (10 pi h); into the layer's
               compliance fill x pi radius^2 h / (gamma P0) (fill: the share the dome's
               rise leaves). A lumped approximation of the distributed layer: <name>
               (R, a -> <name>_m), <name>_m (L, to <name>_c), <name>_c (C, to the ambient)
    acoustic   a resistance r_pa_s_m3 and / or a mass m_kg_m4 in series, given directly
               (a fitted unknown whose geometry no source gives: its source says so)
    line       a pipe of section area_m2 (or radius_m) and length length_m, empty or
               filled with a fibrous stuffing (a ribbon's labyrinth, the RCA 77's damped
               pipe), from its mouth `a`; its far end closed (`end: closed`, the default),
               open into `b` (`end: open`), or `matched`: ended in the line's high-
               frequency characteristic resistance sqrt(rho alpha gamma_p P0) / (phi S) to
               the ambient (a long, lossy line beyond the modelled length, which returns
               nothing: Olson's damped pipe as a pure resistance, with the first length_m
               of it as a line). A staggered ladder of `sections` sections of length dx:
               each one's compliance phi S dx / (gamma_p P0) to the ambient at its centre,
               between two centres (and from the mouth, and to an open or matched end: half
               a section) a series resistance sigma l / S and mass rho alpha l / (phi S) of
               that span l (second-order accurate in dx; Zwikker & Kosten's rigid-
               frame porous medium in its low-frequency limit: flow_resistivity_pa_s_m2
               sigma, porosity phi, tortuosity alpha, the polytropic exponent gamma_p:
               `polytropic`, adiabatic GAMMA unless given; Beranek, "Acoustics", ch. 4 / 7).
               The sections may be graded (`grading`: the last's length over the first's,
               1 uniform), short at the mouth and long further in, which pays only where
               the stuffing kills the high frequencies before the long sections: a section
               needs to be under ~a tenth of the wavelength that still reaches it (12
               uniform sections on 5 cm: 0.3 dB to 6 kHz, ~2.5 near 13 kHz, against a 400-
               section line: tests/test_labyrinth.py). An empty pipe (sigma 0) has no
               resistance (its wall loss neglected). Elements <name>_<k> (R) and
               <name>_<k>_m (L) of span k, <name>_<k>_c (C) of section k, on node
               <name>_<k>; a matched end's resistance <name>_end on node <name>_e
    slotted_line
               a Variable-D rear path (Mawby, US 3,378,649; CHAINS_PLAN.md WP13): `tubes`
               parallel round tubes of radius_m from the mouth `a` (behind the diaphragm), a
               plain lead lead_m long, then the slotted part, the body's slot band
               (`body.slot_m` [from, to] behind the front face, in `body.slot_sections` equal
               sections: the slotted line takes both from the body, so the BEM's slot bands
               and the ladder's are the same), the far end closed (a cavity element may hang on
               its last node <name>_<n>). Per section: the tubes' air mass rho dx / (N pi r^2)
               and Poiseuille resistance 8 mu dx / (N pi r^4) in series between centres (half a
               section from the lead's end), the air's compliance N pi r^2 dx / (gamma P0) at
               its centre, and the slot's cloth, a specific resistance `slot_rayl` over the
               slot's open area N slot_width_m dx, from the centre to that section's own entry.
               Entry 1 (the section nearest the diaphragm) is `b`, the others the ambient: the
               rear entries reduce exactly to one (`rear_entry_weights`). With the body's
               `ports_m` (the head's own rear ports, ahead of the slots) entry 1 is the ports'
               band, node `rear`, driven by the other elements on it (a near path), and every
               slot section is an entry of its own (the ambient here; `b` must be '0').
               Elements <name>_lead
               (R, L), <name>_<k> (R) / <name>_<k>_m (L) spans, <name>_<k>_c (C),
               <name>_<k>_s (R, the slot) on node <name>_<k>
    seeler     the Unidyne III's phase-shift network (`seeler_rear_network`) from the node
               under the dome `a` to the rear entry `b`, its magnet cavity on node `mid`:
               the back entry R1 + L1 (a -> b), the cavity under the dome Ca (a), the coil's
               slits and screen Rb + Lb (a -> mid), the magnet's cavity Cb (mid); from
               d_m (K = d / c), r1_pa_s_m3 and q (= L1 / K R1): elements <name>_r1 / _l1,
               _ca, _rb / _lb, _cb
    diaphragm  the moving system (exactly one), between the pressures on its front face
               (`a`) and on its back face (`b`): its mass (dome, coil, former and the air
               load on its faces) as m / S^2, its suspension's compliance as Cm S^2, its
               mechanical loss as Rm / S^2, then the transducer; with the diaphragm's
               `modes` (below), the rigid part's mass and area are what the modes leave

The transducer is a gyrator of ratio r = B l / S (ohms both ways in these units): the
coil's EMF is B l v = r U and the coil current i pushes on the diaphragm with the pressure
B l i / S = r i. So the preamp's load damps the diaphragm with no extra modelling (the
plan's "one coupled simulation"). A gyrator from two voltage-controlled current sources
(admittance form, g = 1 / r): i_a = g v_e into the acoustic port, i_e = -g v_a into the
electrical one; lossless (v_a i_a + v_e i_e = 0). The electrical side: plus -- Re -- Le
-- (L2 || R2: the coil's eddy currents in the pole pieces, as speaker.py's LR-2) -- the
gyrator -- minus.

The diaphragm's modes (SM3: pat713's dome is two cones with the coil on their joint,
the dome decoupling from the coil at high frequencies): each mode k is a mass m_k (a
`mass_fraction` of the moving mass) on a spring and damper hung from the coil, f_k and q_k
with the coil held still (k_k = m_k (2 pi f_k)^2, r_k = 2 pi f_k m_k / q_k), with its own
area S_k (an `area_fraction` of S), as speaker.py hangs a cone's breakup from its voice coil.
It lives in the mobility analogy on the gyrator's electrical side, where the port's voltage
is B l v of the coil: L = (B l)^2 / k_k || R = (B l)^2 / r_k from the coil's node `@v` to
the mode's node, C = m_k / (B l)^2 from there to `@minus`; and a gyrator of ratio B l / S_k
from the diaphragm's own acoustic port to the mode's node, so the pressure across the
diaphragm pushes the mode (p S_k) and its velocity moves air (U_k = S_k v_k). The rigid
part keeps (1 - sum of the fractions) of the mass and area. Elements <mode> (L), <mode>_r
(R), <mode>_m (C), <mode>_g (G, its electrical port on `c`: the mode's node; a gyrator
without `c` has the coil's node). `@v` and `@minus` are the coil's port and the part's minus
terminal.

The diaphragm's compliance blocks DC, so the moving system's nodes float at DC unless the
coil is loaded: a numerical leak (LEAK_S_PER_ACOUSTIC_OHM times the compliance's
admittance scale, `_leak`) across the compliance holds them, far below any acoustic
effect (no noise: `numerical`).

Self-noise is not a feature: every resistance (the coil's DC resistance, its eddy-current
loss, the acoustic resistances) gets Johnson noise like any resistor under a circuit's
`noise` block (4kTR is the pressure noise density of an acoustic resistance), the leak
none.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from varimu.devices.capsule import C_AIR, END_CORRECTION, GAMMA, MU_AIR, P0, RHO_AIR

KINDS = (
    "screen", "tube", "slit", "radiation", "cavity", "film", "acoustic", "line", "seeler",
    "slotted_line", "diaphragm",
)  # fmt: skip
PORTS = ("front", "rear", "0")
# The leak across the diaphragm's compliance: a resistance this many times the
# compliance's reactance at LEAK_HZ (a time constant of ~1 / (2 pi LEAK_HZ x 1e6)): numerical.
LEAK_HZ = 1.0
LEAK_RATIO = 1.0e6


@dataclass(frozen=True)
class Element:
    """A compiled element: kind R, L, C (between a and b) or G (the gyrator: its acoustic
    port a -> b, ratio `value` = B l / S in ohms, its electrical port from `c` to the part's
    minus terminal: `@v`, the coil's node, unless a mode's); `stop`: the shutter stop it
    belongs to (varimu.devices.ribbon), None in every stop."""

    name: str
    kind: str
    a: str
    b: str
    value: float
    c: str = "@v"
    stop: int | None = None  # a ribbon's shutter stop (varimu.devices.ribbon), else in all


@dataclass(frozen=True)
class MovingCoil:
    """A cartridge's compiled network and its electrical constants."""

    name: str
    bl_tm: float
    sd_m2: float
    re_ohm: float
    le_h: float
    l2_h: float
    r2_ohm: float
    elements: tuple[Element, ...]

    @property
    def gyrator_ohm(self) -> float:
        return self.bl_tm / self.sd_m2


def _leak(c_m5_n: float) -> float:
    """The numerical leak's resistance across a compliance (module docstring)."""
    return LEAK_RATIO / (2.0 * math.pi * LEAK_HZ * c_m5_n)


def moving_mass(d: Mapping[str, Any], coil: Mapping[str, Any]) -> dict[str, float]:
    """The moving system's mass from its parts (kg): the dome, density_kg_m3 x
    thickness_m over the effective area pi radius_m^2; the coil's wire, of length B l / B
    (`b_gap_t`) at the measured DC resistance re_ohm: a wire of resistivity rho_e and
    density rho_m weighs rho_m rho_e l^2 / R (wire_density_kg_m3, wire_resistivity_ohm_m);
    its adhesive, adhesive_fraction of the wire; the air load on both faces, a baffled
    piston's 8 rho a^3 / 3 each (the masses inside the network's ducts are their own
    elements)."""
    s = math.pi * d["radius_m"] ** 2
    dome = d["density_kg_m3"] * d["thickness_m"] * s
    length = coil["bl_tm"] / coil["b_gap_t"]
    wire = coil["wire_density_kg_m3"] * coil["wire_resistivity_ohm_m"] * length**2 / coil["re_ohm"]
    adhesive = coil["adhesive_fraction"] * wire
    air = 2.0 * 8.0 * RHO_AIR * d["radius_m"] ** 3 / 3.0
    return {
        "dome_kg": dome,
        "wire_kg": wire,
        "adhesive_kg": adhesive,
        "air_kg": air,
        "wire_length_m": length,
        "total_kg": dome + wire + adhesive + air,
    }


# The coil's own nodes in parts.moving_coil / moving_coil.rs (<part>_l, _e, _v): a network node
# of the same name would be the same node there (found 2026-11-12, CHAINS_PLAN.md WP13).
RESERVED_NODES = frozenset({"l", "e", "v"})


def compile_network(g: Mapping[str, Any]) -> dict[str, Any]:
    """The lumped elements of a cartridge from its geometry `g` (SI): `diaphragm`
    {radius_m (the effective radiating radius: S = pi r^2), moving_mass_kg (dome, coil,
    former and the air load; or its parts, `moving_mass`), compliance_m_per_n (or
    resonance_hz: the moving system's in vacuo with its mass), resistance_ns_per_m (or
    q: the moving system's own)}, `coil` {bl_tm, re_ohm, le_h, l2_h, r2_ohm} and `network`
    (a list of {name, kind, a, b, ...}: the module docstring). Node names: `front`,
    `rear`, `0`, else the cartridge's own."""
    d, coil = dict(g["diaphragm"]), g["coil"]
    s = math.pi * d["radius_m"] ** 2
    mass_parts = None
    if "moving_mass_kg" not in d:
        mass_parts = moving_mass(d, coil)
        d["moving_mass_kg"] = mass_parts["total_kg"]
    if "compliance_m_per_n" not in d:
        w0 = 2.0 * math.pi * d["resonance_hz"]
        d["compliance_m_per_n"] = 1.0 / (w0 * w0 * d["moving_mass_kg"])
    if "resistance_ns_per_m" not in d:
        w0 = 1.0 / math.sqrt(d["moving_mass_kg"] * d["compliance_m_per_n"])
        d["resistance_ns_per_m"] = w0 * d["moving_mass_kg"] / d["q"]
    els: list[dict[str, Any]] = []
    names: set[str] = set()
    n_diaphragm = 0
    for e in g["network"]:
        name, kind, a = str(e["name"]), str(e["kind"]), str(e["a"])
        b = str(e.get("b", "0"))
        if kind not in KINDS:
            raise ValueError(f"network element {name}: kind {kind!r} ({KINDS})")
        if name in names:
            raise ValueError(f"network element {name}: the name is taken")
        names.add(name)
        clash = {str(e[k]) for k in ("a", "b", "mid") if k in e} & RESERVED_NODES
        if clash:  # the part prefixes acoustic and electrical nodes alike (parts.moving_coil)
            raise ValueError(f"network element {name}: node {sorted(clash)} is the coil's own")
        if kind == "slotted_line":
            band = _slot_body(g)
            if _ports(g):
                if b != "0":
                    raise ValueError(f"slotted_line {name}: with the body's ports_m, b is '0'")
                els += _slotted_line(name, a, b, e, band, ["0"] * band[2])
            else:
                els += _slotted_line(name, a, b, e, band)
        elif kind != "diaphragm":
            els += compile_element(e)
        else:
            n_diaphragm += 1
            modes = d.get("modes") or []
            mf = 1.0 - sum(float(x["mass_fraction"]) for x in modes)
            af = 1.0 - sum(float(x["area_fraction"]) for x in modes)
            if not (mf > 0 and af > 0):
                raise ValueError(f"diaphragm {name}: its modes take all of its mass or area")
            s0, m0 = s * af, d["moving_mass_kg"] * mf
            m_a = m0 / (s0 * s0)
            c_a = d["compliance_m_per_n"] * s0 * s0
            r_a = d["resistance_ns_per_m"] / (s0 * s0)
            m1, m2, m3 = f"{name}_1", f"{name}_2", f"{name}_3"
            els += [
                _el(f"{name}_m", "L", a, m1, m_a),
                _el(f"{name}_c", "C", m1, m2, c_a),
                _el(f"{name}_leak", "R", m1, m2, _leak(c_a)),
                _el(f"{name}_r", "R", m2, m3, r_a),
                _el(f"{name}_g", "G", m3, b, coil["bl_tm"] / s0),
            ]
            bl2 = float(coil["bl_tm"]) ** 2
            for k, x in enumerate(modes, 1):
                mk = d["moving_mass_kg"] * float(x["mass_fraction"])
                wk = 2.0 * math.pi * float(x["f_hz"])
                node = f"{name}_k{k}"
                els += [
                    _el(f"{name}_k{k}", "L", "@v", node, bl2 / (mk * wk * wk)),
                    _el(f"{name}_k{k}_r", "R", "@v", node, bl2 * float(x["q"]) / (wk * mk)),
                    _el(f"{name}_k{k}_m", "C", node, "@minus", mk / bl2),
                    {**_el(f"{name}_k{k}_g", "G", a, b,
                           coil["bl_tm"] / (s * float(x["area_fraction"]))), "c": node},
                ]  # fmt: skip
    if n_diaphragm != 1:
        raise ValueError(f"a cartridge has one diaphragm ({n_diaphragm} in its network)")
    return {
        "bl_tm": float(coil["bl_tm"]),
        "sd_m2": s,
        "re_ohm": float(coil["re_ohm"]),
        "le_h": float(coil["le_h"]),
        "l2_h": float(coil.get("l2_h", 0.0)),
        "r2_ohm": float(coil.get("r2_ohm", 0.0)),
        "elements": els,
        # Reported, not used by the network:
        "resonance_hz": 1.0
        / (2.0 * math.pi * math.sqrt(d["moving_mass_kg"] * d["compliance_m_per_n"])),
        "gyrator_ohm": coil["bl_tm"] / s,
        "moving_mass_kg": d["moving_mass_kg"],
        "compliance_m_per_n": d["compliance_m_per_n"],
        "resistance_ns_per_m": d["resistance_ns_per_m"],
        **({"mass_parts": mass_parts} if mass_parts else {}),
    }


def compile_element(e: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The lumped elements of one network element `e` of any kind but the moving system's
    (`diaphragm`; a ribbon's `ribbon`, varimu.devices.ribbon): the module docstring's
    formulas. Shared by every transducer kind built on these networks."""
    name, kind, a = str(e["name"]), str(e["kind"]), str(e["a"])
    b = str(e.get("b", "0"))
    els: list[dict[str, Any]] = []
    if kind == "screen":
        area = float(e["area_m2"])
        els.append(_el(f"{name}", "R", a, b, float(e["rayl"]) / area))
        t = float(e.get("thickness_m", 0.0))
        if t > 0:
            m = RHO_AIR * t / (float(e.get("porosity", 1.0)) * area)
            els[-1]["b"] = f"{name}_m"
            els.append(_el(f"{name}_m", "L", f"{name}_m", b, m))
    elif kind == "tube":
        n, r, length = float(e.get("count", 1)), float(e["radius_m"]), float(e["length_m"])
        ends = float(e.get("open_ends", 2))
        l_eff = length + ends * END_CORRECTION * r
        if "wide_at_hz" in e:
            w = 2.0 * math.pi * float(e["wide_at_hz"])
            res = l_eff * math.sqrt(2.0 * w * RHO_AIR * MU_AIR) / (n * math.pi * r**3)
            mass = RHO_AIR * l_eff / (n * math.pi * r * r)
        else:
            res = 8.0 * MU_AIR * length / (n * math.pi * r**4)
            mass = 4.0 * RHO_AIR * l_eff / (3.0 * n * math.pi * r * r)
        els += _series(name, a, b, res, mass)
    elif kind == "slit":
        w, br, length = float(e["width_m"]), float(e["breadth_m"]), float(e["length_m"])
        if "wide_at_hz" in e:
            om = 2.0 * math.pi * float(e["wide_at_hz"])
            res = length * math.sqrt(2.0 * om * RHO_AIR * MU_AIR) / (br * w * w)
            mass = RHO_AIR * length / (br * w)
        else:
            res = 12.0 * MU_AIR * length / (br * w**3)
            mass = 6.0 * RHO_AIR * length / (5.0 * br * w)
        els += _series(name, a, b, res, mass)
    elif kind == "radiation":
        if "radius_m" in e:
            r = float(e["radius_m"])
            area, self_integral = math.pi * r * r, 16.0 * math.pi * r**3 / 3.0
        else:
            w, ln = float(e["width_m"]), float(e["length_m"])
            area, self_integral = w * ln, rectangle_self_integral(w, ln)
        mass = RHO_AIR * self_integral / (2.0 * math.pi * area * area)
        els += [
            _el(f"{name}_m", "L", a, b, mass),
            _el(f"{name}_r", "R", a, b, RHO_AIR * C_AIR / area),
        ]
    elif kind == "seeler":
        k_s = float(e["d_m"]) / C_AIR
        r1, q = float(e["r1_pa_s_m3"]), float(e["q"])
        net = seeler_rear_network(k_s, r1, q * k_s * r1)
        mid = str(e["mid"])
        els += [
            _el(f"{name}_r1", "R", a, f"{name}_1", r1),
            _el(f"{name}_l1", "L", f"{name}_1", b, q * k_s * r1),
            _el(f"{name}_ca", "C", a, "0", net["ca"]),
            _el(f"{name}_rb", "R", a, f"{name}_b", net["rb"]),
            _el(f"{name}_lb", "L", f"{name}_b", mid, net["lb"]),
            _el(f"{name}_cb", "C", mid, "0", net["cb"]),
        ]
    elif kind == "cavity":
        if b != "0":
            raise ValueError(f"cavity {name}: a compliance to the ambient (b: '0')")
        if "compliance_m5_n" in e:
            comp = float(e["compliance_m5_n"])
        else:
            comp = float(e["volume_m3"]) / (GAMMA * P0)
        els.append(_el(name, "C", a, "0", comp))
    elif kind == "film":
        if b != "0":
            raise ValueError(f"film {name}: a compliance to the ambient (b: '0')")
        h, rr = float(e["height_m"]), float(e["ring_radius_m"])
        ro = float(e["radius_m"])
        out_r = 6.0 * MU_AIR * math.log(ro / rr) / (math.pi * h**3)
        in_r = 6.0 * MU_AIR * math.log(4.0) / (math.pi * h**3)
        out_m = 6.0 * RHO_AIR * math.log(ro / rr) / (10.0 * math.pi * h)
        in_m = 6.0 * RHO_AIR * math.log(4.0) / (10.0 * math.pi * h)
        comp = float(e.get("fill", 1.0)) * math.pi * ro * ro * h / (GAMMA * P0)
        els += [
            _el(name, "R", a, f"{name}_m", out_r * in_r / (out_r + in_r)),
            _el(f"{name}_m", "L", f"{name}_m", f"{name}_c", out_m * in_m / (out_m + in_m)),
            _el(f"{name}_c", "C", f"{name}_c", "0", comp),
        ]
    elif kind == "acoustic":
        r_, m_ = float(e.get("r_pa_s_m3", 0.0)), float(e.get("m_kg_m4", 0.0))
        if r_ > 0 and m_ > 0:
            els += _series(name, a, b, r_, m_)
        elif r_ > 0:
            els.append(_el(name, "R", a, b, r_))
        elif m_ > 0:
            els.append(_el(name, "L", a, b, m_))
        else:
            raise ValueError(f"acoustic {name}: needs r_pa_s_m3 and / or m_kg_m4")
    elif kind == "line":
        els += _line(name, a, b, e)
    else:
        raise ValueError(f"network element {name}: kind {kind!r} isn't a passive element")
    return els


def rectangle_self_integral(a: float, b: float) -> float:
    """The integral of 1 / |r - r'| over a rectangle a x b twice (m^3): (2/3) (a^3 + b^3 -
    d^3) + 2 a^2 b asinh(b / a) + 2 a b^2 asinh(a / b), d its diagonal (4 x the integral of
    (a - u) (b - v) / sqrt(u^2 + v^2) over [0, a] x [0, b]; checked against quadrature in
    tests/test_ribbon.py). A disk's is 16 pi r^3 / 3."""
    d = math.hypot(a, b)
    return (
        2.0 * (a**3 + b**3 - d**3) / 3.0
        + 2.0 * a * a * b * math.asinh(b / a)
        + 2.0 * a * b * b * math.asinh(a / b)
    )


def line_sections(length_m: float, n: int, grading: float) -> list[float]:
    """The lengths of a `line`'s n sections, in a geometric progression from the mouth whose
    last is `grading` times the first, summing to length_m."""
    if n < 1 or not grading > 0:
        raise ValueError(f"line: sections {n}, grading {grading}")
    if n == 1:
        return [length_m]
    q = grading ** (1.0 / (n - 1))
    w = [q**k for k in range(n)]
    total = 0.0
    for x in w:  # a plain loop: the builders' float sums (CLAUDE.md)
        total += x
    return [length_m * x / total for x in w]


def _line(name: str, a: str, b: str, e: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The `line` kind's ladder (the module docstring)."""
    area = float(e["area_m2"]) if "area_m2" in e else math.pi * float(e["radius_m"]) ** 2
    sigma = float(e.get("flow_resistivity_pa_s_m2", 0.0))
    phi, alpha = float(e.get("porosity", 1.0)), float(e.get("tortuosity", 1.0))
    gamma_p = float(e.get("polytropic", GAMMA))
    end = str(e.get("end", "closed"))
    if end not in ("closed", "open", "matched"):
        raise ValueError(f"line {name}: end {end!r} (closed, open or matched)")
    if end != "open" and b != "0":
        raise ValueError(f"line {name}: a {end} line has no far node (b: '0' or none)")
    if not (0 < phi <= 1 and alpha >= 1 and sigma >= 0 and gamma_p >= 1):
        raise ValueError(f"line {name}: porosity {phi}, tortuosity {alpha}, sigma {sigma}")
    dxs = line_sections(float(e["length_m"]), int(e["sections"]), float(e.get("grading", 1.0)))
    n = len(dxs)
    # The staggered ladder: a compliance at each section's centre, the series element between
    # two centres their mean length, half a section's from the mouth and to the far end.
    spans = [0.5 * dxs[0]] + [0.5 * (dxs[k] + dxs[k + 1]) for k in range(n - 1)]
    far = {"closed": None, "open": b, "matched": f"{name}_e"}[end]
    if far is not None:
        spans.append(0.5 * dxs[-1])
    els: list[dict[str, Any]] = []
    for k, dx in enumerate(spans, 1):
        src = a if k == 1 else f"{name}_{k - 1}"
        dst = f"{name}_{k}" if k <= n else far
        m = RHO_AIR * alpha * dx / (phi * area)
        if sigma > 0:
            els += [
                _el(f"{name}_{k}", "R", src, f"{name}_{k}_n", sigma * dx / area),
                _el(f"{name}_{k}_m", "L", f"{name}_{k}_n", dst, m),
            ]
        else:
            els.append(_el(f"{name}_{k}_m", "L", src, dst, m))
        if k <= n:
            c = phi * area * dxs[k - 1] / (gamma_p * P0)
            els.append(_el(f"{name}_{k}_c", "C", dst, "0", c))
    if end == "matched":
        z0 = math.sqrt(RHO_AIR * alpha * gamma_p * P0) / (phi * area)
        els.append(_el(f"{name}_end", "R", far, "0", z0))
    return els


def _slot_body(g: Mapping[str, Any]) -> tuple[float, float, int]:
    """The slot band (from, to behind the front face) and its sections, from the geometry's
    body (form `variable_d`: varimu.mics.bor.variable_d_mesh)."""
    body = g.get("body") or {}
    if body.get("form") != "variable_d":
        raise ValueError("a slotted_line needs a body of form variable_d (its slot band)")
    lo, hi = (float(x) for x in body["slot_m"])
    n = int(body["slot_sections"])
    if not (0 < lo < hi and n >= 1):
        raise ValueError(f"variable_d body: slot_m {body['slot_m']}, sections {n}")
    return lo, hi, n


def _ports(g: Mapping[str, Any]) -> bool:
    """Whether the geometry's variable_d body has the head's rear ports (`ports_m`)."""
    return (g.get("body") or {}).get("ports_m") is not None


def _slotted_line(
    name: str, a: str, b: str, e: Mapping[str, Any], band: tuple[float, float, int],
    entries: Sequence[str] | None = None,
) -> list[dict[str, Any]]:  # fmt: skip
    """The `slotted_line` kind's ladder (the module docstring). `entries`: the sections' entry
    nodes (default: `b`, then the ambient)."""
    lo, hi, n = band
    big_n, r = float(e.get("tubes", 1)), float(e["radius_m"])
    area = big_n * math.pi * r * r
    dx = (hi - lo) / n
    lead = float(e["lead_m"])
    entries = list(entries) if entries is not None else [b] + ["0"] * (n - 1)
    if len(entries) != n:
        raise ValueError(f"slotted_line {name}: {len(entries)} entries for {n} sections")
    rho_l = RHO_AIR / area  # mass per metre
    res_l = 8.0 * MU_AIR / (big_n * math.pi * r**4)  # resistance per metre
    slot = float(e["slot_rayl"]) / (big_n * float(e["slot_width_m"]) * dx)
    els: list[dict[str, Any]] = []
    span0 = lead + 0.5 * dx  # the mouth to the first section's centre
    els += _series(f"{name}_lead", a, f"{name}_1", res_l * span0, rho_l * span0)
    for k in range(1, n + 1):
        node = f"{name}_{k}"
        els.append(_el(f"{name}_{k}_c", "C", node, "0", area * dx / (GAMMA * P0)))
        els.append(_el(f"{name}_{k}_s", "R", node, entries[k - 1], slot))
        if k < n:
            els += _series(f"{name}_{k}", node, f"{name}_{k + 1}", res_l * dx, rho_l * dx)
    return els


def rear_entry_weights(g: Mapping[str, Any], f_hz: Sequence[float]) -> np.ndarray:
    """The Variable-D reduction (CHAINS_PLAN.md WP13): the rear network is linear and meets the
    rest only at the diaphragm's back face, so its N slot entries act on the diaphragm through
    one Thevenin pressure there, sum_k G_k p_k (G_k: the back face's pressure, the diaphragm
    blocked, per pascal at entry k alone), behind one impedance (all entries at the ambient).
    The compiled network drives only entry 1 (`rear`) and grounds the others, so it is exact
    with the rear entry's pressure sum_k w_k p_k, w_k = G_k / G_1. Returns w, (n, len(f)):
    w[0] = 1. With the body's `ports_m`, entry 1 is the ports (node `rear`) and the slot sections
    are entries 2..n + 1: w is (n + 1, len(f)). A cartridge without a slotted_line: a (1, len(f))
    array of ones."""
    f = np.atleast_1d(np.asarray(f_hz, float))
    lines = [e for e in g["network"] if e["kind"] == "slotted_line"]
    if not lines:
        return np.ones((1, len(f)))
    if len(lines) > 1:
        raise ValueError("one slotted_line per cartridge")
    band = _slot_body(g)
    n = band[2]
    dia = next(e for e in g["network"] if e["kind"] == "diaphragm")
    back = str(dia.get("b", "0"))
    line = lines[0]
    if _ports(g):
        slots = ["@port"] + [f"@slot{k}" for k in range(1, n + 1)]
        entry1, line_entries = "rear", slots[1:]
    else:
        slots = [f"@slot{k}" for k in range(1, n + 1)]
        entry1, line_entries = str(line.get("b", "0")), slots
    els: list[dict[str, Any]] = []
    for e in g["network"]:
        if e["kind"] == "diaphragm":
            continue  # blocked: no volume velocity at its faces
        if e["kind"] == "slotted_line":
            els += _slotted_line(str(e["name"]), str(e["a"]), "0", e, band, line_entries)
        else:
            els += compile_element(e)
    if entry1 != "0":  # other elements on entry 1's node see its pressure
        els = [{**el, "a": slots[0] if el["a"] == entry1 else el["a"],
                "b": slots[0] if el["b"] == entry1 else el["b"]} for el in els]  # fmt: skip
    n = len(slots)
    fixed = {"0", "front", "rear", *slots}
    nodes = sorted({x for el in els for x in (el["a"], el["b"])} - fixed)
    if back not in nodes:
        raise ValueError(f"the diaphragm's back node {back!r} isn't in the rear network")
    idx = {x: i for i, x in enumerate(nodes)}
    s = 2j * math.pi * f
    y = np.zeros((len(f), len(nodes), len(nodes)), complex)
    rhs = np.zeros((len(f), len(nodes), n), complex)
    for el in els:
        v = el["value"]
        adm = {"R": np.full(len(f), 1.0 / v, complex), "L": 1.0 / (s * v), "C": s * v}[el["kind"]]
        ia, ib = idx.get(el["a"]), idx.get(el["b"])
        for i0, other in ((ia, el["b"]), (ib, el["a"])):
            if i0 is None:
                continue
            y[:, i0, i0] += adm
            if other in idx:
                y[:, i0, idx[other]] -= adm
            elif other in slots:  # a driven entry: its pressure into the right side
                rhs[:, i0, slots.index(other)] += adm
    g_k = np.linalg.solve(y, rhs)[:, idx[back], :].T  # (n, f)
    return g_k / g_k[0]


def _series(name: str, a: str, b: str, r: float, m: float) -> list[dict[str, Any]]:
    """A resistance `name` from a to <name>_m and a mass <name>_m from there to b."""
    return [_el(name, "R", a, f"{name}_m", r), _el(f"{name}_m", "L", f"{name}_m", b, m)]


def _el(name: str, kind: str, a: str, b: str, value: float) -> dict[str, Any]:
    if not (value > 0 and math.isfinite(value)):
        raise ValueError(f"element {name}: {kind} {value!r} must be positive and finite")
    return {"name": name, "kind": kind, "a": a, "b": b, "value": float(value)}


def seeler_rear_network(k_s: float, r1: float, l1: float) -> dict[str, float]:
    """The Unidyne III's phase-shift network from its back entry (Seeler, "A Small
    Unidirectional Dynamic Probe Microphone", JAES 9(4), 1961, Eqs. 5-10): the back entry
    Z1 = p L1 + R1 (the annular slit around the magnet with its screen B), the cavity under
    the dome Ca, the coil's slits and screen A (Lb, Rb) into the cavity in the magnet Cb,
    chosen so that 1 + Z1 / Z2 = exp(p K) to fourth order in p (Eq. 3: the cardioid's
    condition, independent of the diaphragm), K = d / c the delay between the entries.
    q = L1 / (K R1) > 1/2; s = Cb / (Ca + Cb) a root of Eq. 10. Returns ca, cb, rb, lb, q,
    s.

    The root: the paper keeps the larger one ("only the larger one will yield positive
    circuit parameters"), but with Eqs. 5-9 as printed (checked against the series of
    1 + Z1 / Z2 term by term: tests/test_moving_coil.py) the larger root gives Lb < 0 at
    every q, and the smaller one gives all four elements positive (Lb > 0 needs s <
    (q - 1/2)^2 / (q^2 - q/2 + 1/6)). Both satisfy the four equations; the physical one is
    taken."""
    q = l1 / (k_s * r1)
    if not q > 0.5:
        raise ValueError(f"Seeler's network needs q = L1 / (K R1) > 1/2 (q = {q:.4g})")
    u = 1.0 - 2.0 * q
    w = 1.0 - 3.0 * q * u
    a2, a1, a0 = 1.0 - 4.0 * q * w, -4.0 * u * w, 3.0 * u**3
    if abs(a2) < 1e-12:
        roots = [-a0 / a1]
    else:
        disc = a1 * a1 - 4.0 * a2 * a0
        if disc < 0:
            raise ValueError(f"Seeler's Eq. 10 has no real root at q = {q:.4g}")
        roots = [(-a1 + sg * math.sqrt(disc)) / (2.0 * a2) for sg in (1.0, -1.0)]
    for s in sorted(roots):
        net = {
            "ca": (k_s / r1) * (1.0 - s),
            "cb": (k_s / r1) * s,
            "rb": r1 * (2.0 * q - 1.0) / (2.0 * s * s),
            "lb": (k_s * r1 / (12.0 * s**3)) * (3.0 * u * u - 2.0 * s * w),
        }
        if 0 < s < 1 and all(v > 0 for v in net.values()):
            return {**net, "q": q, "s": s}
    raise ValueError(f"Seeler's Eq. 10 gives no physical network at q = {q:.4g} (roots {roots})")


def moving_coil_from_data(
    d: Mapping[str, Any], name: str = "moving_coil", kind: str = "moving_coil"
) -> MovingCoil:
    """A component's compiled network: a moving-coil cartridge, or with kind `ribbon_motor`
    a ribbon motor (varimu.devices.ribbon: the same lumped format)."""
    if d.get("kind") != kind:
        what = {"moving_coil": "a moving-coil cartridge", "ribbon_motor": "a ribbon motor"}[kind]
        raise ValueError(f"{name} is not {what} (kind {d.get('kind')!r})")
    lp = d["lumped"]
    missing = [
        k for k in ("bl_tm", "sd_m2", "re_ohm", "le_h", "l2_h", "r2_ohm", "elements") if k not in lp
    ]
    if missing:
        raise ValueError(f"{name}: lumped needs {missing}")
    els = tuple(
        Element(
            str(e["name"]), str(e["kind"]), str(e["a"]), str(e["b"]), float(e["value"]),
            str(e.get("c", "@v")), None if e.get("stop") is None else int(e["stop"]),
        )
        for e in lp["elements"]
    )  # fmt: skip
    if sum(e.kind == "G" and e.c == "@v" for e in els) != 1:
        raise ValueError(f"{name}: one gyrator (G) on the coil in lumped.elements")
    return MovingCoil(
        d["name"],
        float(lp["bl_tm"]),
        float(lp["sd_m2"]),
        float(lp["re_ohm"]),
        float(lp["le_h"]),
        float(lp["l2_h"]),
        float(lp["r2_ohm"]),
        els,
    )


def nodes(c: MovingCoil) -> Sequence[str]:
    """The cartridge's own acoustic nodes (not front, rear or 0), in order of appearance."""
    out: list[str] = []
    for e in c.elements:
        for x in (e.a, e.b):
            if x not in PORTS and not x.startswith("@") and x not in out:
                out.append(x)
    return out

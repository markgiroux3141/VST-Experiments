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
               (b w^3), M = 6 rho l / (5 b w) (plane Poiseuille flow)
    cavity     a closed volume of air to the ambient's reference: C = V / (gamma P0)
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

from varimu.devices.capsule import C_AIR, END_CORRECTION, GAMMA, MU_AIR, P0, RHO_AIR

KINDS = ("screen", "tube", "slit", "cavity", "film", "acoustic", "seeler", "diaphragm")
PORTS = ("front", "rear", "0")
# The leak across the diaphragm's compliance: a resistance this many times the
# compliance's reactance at LEAK_HZ (a time constant of ~1 / (2 pi LEAK_HZ x 1e6)): numerical.
LEAK_HZ = 1.0
LEAK_RATIO = 1.0e6


@dataclass(frozen=True)
class Element:
    """A compiled element: kind R, L, C (between a and b) or G (the gyrator: its acoustic
    port a -> b, ratio `value` = B l / S in ohms, its electrical port from `c` to the part's
    minus terminal: `@v`, the coil's node, unless a mode's)."""

    name: str
    kind: str
    a: str
    b: str
    value: float
    c: str = "@v"


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
            res = 12.0 * MU_AIR * length / (br * w**3)
            mass = 6.0 * RHO_AIR * length / (5.0 * br * w)
            els += _series(name, a, b, res, mass)
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
        else:  # diaphragm
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


def moving_coil_from_data(d: Mapping[str, Any], name: str = "moving_coil") -> MovingCoil:
    if d.get("kind") != "moving_coil":
        raise ValueError(f"{name} is not a moving-coil cartridge (kind {d.get('kind')!r})")
    lp = d["lumped"]
    missing = [
        k for k in ("bl_tm", "sd_m2", "re_ohm", "le_h", "l2_h", "r2_ohm", "elements") if k not in lp
    ]
    if missing:
        raise ValueError(f"{name}: lumped needs {missing}")
    els = tuple(
        Element(
            str(e["name"]), str(e["kind"]), str(e["a"]), str(e["b"]), float(e["value"]),
            str(e.get("c", "@v")),
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

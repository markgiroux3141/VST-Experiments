"""Condenser microphone capsules as lumped acoustic networks (MIC_ROOM_PLAN.md, A2).

A capsule is a component (kind `capsule`, config/components/<name>/<N>.yaml): its
geometry and materials (sourced), and the lumped elements derived from them here at
fit time (`varimu fit-devices`), so both circuit builders read the same numbers.

The network is in the impedance analogy with pressures as volts (Pa = V) and volume
velocities as currents (m^3/s = A): an acoustic mass (kg/m^4) is an inductance, an
acoustic compliance (m^5/N) a capacitance, an acoustic resistance (Pa s/m^3) a
resistance. A single-diaphragm pressure capsule (the verification case: a measurement
microphone) from its front pressure node `front` to the ambient (ground):

    front -- M (diaphragm + its radiation mass) -- C_d (the diaphragm's compliance,
    softened by the electrostatic force) -- gap: C_g to ground; R_h + M_h (the
    squeeze film and the backplate's holes) -- cavity: C_c to ground; R_v (the static
    pressure vent) from the cavity back to `front` (a vent exposed to the sound field).

The diaphragm's volume displacement is C_d times the voltage across it; the mean
displacement over the backplate is `displacement_per_volume` times that (a membrane
under tension deflects parabolically: over a backplate of radius b on a membrane of
radius a, (2 - b^2 / a^2) / (pi a^2) per unit volume). The electrical port is the
linearized electrostatic transducer: an open-circuit voltage E0 x / h behind the
capacitance C0 (+ stray), as a Thevenin source: a Vccs into a 1 ohm readout resistor
on the backplate's node, C0 from there to the other electrode. The back-reaction of
the electrical load on the diaphragm is left out (a condenser capsule into ~GOhm), its
static part, the electrostatic negative stiffness E0^2 e0 A / h^3, is in C_d.

Self-noise is not a feature: the acoustic resistances get Johnson noise like any
resistor (B5's noise sources; in these units 4kTR is the pressure noise density the
fluctuation-dissipation theorem gives an acoustic resistance), the readout resistor
none.

Formulas (sources in the component's `formulas` block; data/schematics/bk_4134/README.md):
membrane compliance pi a^4 / (8 T) and mass 4 rho_s / (3 pi a^2) (the first mode's
volume-displacement equivalents); a piston's radiation mass 8 rho / (3 pi^2 a); the
squeeze film over a perforated backplate (Skvor): 12 mu / (N pi h^3) (B/2 - B^2/8 -
ln(B)/4 - 3/8), B the open area fraction; holes: 8 mu t / (N pi r^4) and
4 rho t' / (3 N pi r^2) (Poiseuille flow, t' with end corrections); the gap's
compliance isothermal, pi b^2 h / P0; the cavity's adiabatic, V / (gamma P0); the vent
8 mu l / (pi r^4).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

EPS0 = 8.8541878128e-12  # F/m
# Air at 20 C, 101.325 kPa (web: https://www.engineeringtoolbox.com/air-properties-d_156.html)
RHO_AIR = 1.204  # kg/m^3
C_AIR = 343.2  # m/s (as varimu.devices.speaker)
MU_AIR = 1.813e-5  # Pa s
P0 = 101325.0  # Pa
GAMMA = 1.4
READOUT_OHM = 1.0  # the Thevenin source's resistance (numerical; no noise)
# The end correction of a hole's acoustic mass, per end, in hole radii (a flanged
# opening, 0.85 r; Kinsler et al., Fundamentals of Acoustics, sec. 10.8).
END_CORRECTION = 0.85


@dataclass(frozen=True)
class Capsule:
    """A capsule's lumped elements (SI, acoustic units) and electrical constants."""

    name: str
    m_front: float  # kg/m^4: the diaphragm's mass and its radiation mass
    c_diaphragm: float  # m^5/N: at zero polarization
    c_gap: float  # m^5/N
    r_holes: float  # Pa s/m^3: squeeze film + holes
    m_holes: float  # kg/m^4
    c_cavity: float  # m^5/N
    r_vent: float  # Pa s/m^3
    c0_f: float  # F: the active capacitance (diaphragm to backplate)
    c_stray_f: float  # F: in parallel (housing, insulator)
    gap_m: float  # h
    displacement_per_volume: float  # 1/m^2: mean displacement over the backplate per m^3
    neg_stiffness_per_v2: float  # Pa/m^3 per V^2: the electrostatic softening / E0^2

    def c_diaphragm_at(self, e0_v: float) -> float:
        """The diaphragm's compliance at polarization e0_v (the electrostatic force's
        negative stiffness in series)."""
        return 1.0 / (1.0 / self.c_diaphragm - self.neg_stiffness_per_v2 * e0_v * e0_v)

    def volts_per_volume(self, e0_v: float) -> float:
        """Open-circuit volts per m^3 of volume displacement (E0 x / h)."""
        return e0_v * self.displacement_per_volume / self.gap_m


def lumped(g: Mapping[str, Any]) -> dict[str, float]:
    """The lumped elements of a pressure capsule from its geometry `g` (SI): diaphragm
    {radius_m, thickness_m, density_kg_m3, tension_n_m}, gap_m, backplate {radius_m,
    thickness_m, holes, hole_radius_m}, cavity_m3, vent {radius_m, length_m} or
    {lf_3db_hz}, stray_capacitance_f; optionally film_resistance_pa_s_m3, the squeeze
    film's resistance from a better source than Skvor's uniform-array formula (which
    assumes a periodic hole array: a few large holes and a slit drain the film faster)."""
    d, bp, v = g["diaphragm"], g["backplate"], g["vent"]
    a, h, b = d["radius_m"], g["gap_m"], bp["radius_m"]
    t_n_m = d["tension_n_m"]
    rho_s = d["density_kg_m3"] * d["thickness_m"]
    n, r, t = bp["holes"], bp["hole_radius_m"], bp["thickness_m"]
    area_fraction = n * r * r / (b * b)
    m_d = 4.0 * rho_s / (3.0 * math.pi * a * a)
    m_rad = 8.0 * RHO_AIR / (3.0 * math.pi * math.pi * a)
    skvor = area_fraction / 2.0 - area_fraction * area_fraction / 8.0
    skvor = skvor - math.log(area_fraction) / 4.0 - 3.0 / 8.0
    r_film = 12.0 * MU_AIR / (n * math.pi * h**3) * skvor
    if "film_resistance_pa_s_m3" in g:  # a published value (an FEM solution) over Skvor's
        r_film = g["film_resistance_pa_s_m3"]
    r_holes = 8.0 * MU_AIR * t / (n * math.pi * r**4)
    t_eff = t + 2.0 * END_CORRECTION * r
    kappa = 2.0 - b * b / (a * a)
    return {
        "m_front": m_d + m_rad,
        "c_diaphragm": math.pi * a**4 / (8.0 * t_n_m),
        "c_gap": math.pi * b * b * h / P0,
        "r_holes": r_film + r_holes,
        "m_holes": 4.0 * RHO_AIR * t_eff / (3.0 * n * math.pi * r * r),
        "c_cavity": g["cavity_m3"] / (GAMMA * P0),
        "r_vent": _vent(v, g["cavity_m3"] / (GAMMA * P0) + math.pi * b * b * h / P0),
        "c0_f": EPS0 * math.pi * b * b / h,
        "c_stray_f": g["stray_capacitance_f"],
        "gap_m": h,
        "displacement_per_volume": kappa / (math.pi * a * a),
        "neg_stiffness_per_v2": EPS0 * b * b * kappa * kappa / (math.pi * h**3 * a**4),
        # Reported, not used by the network:
        "film_share_of_r_holes": r_film / (r_film + r_holes),
        "membrane_resonance_hz": math.sqrt(6.0 * t_n_m / (rho_s * a * a)) / (2.0 * math.pi),
    }


def _vent(v: Mapping[str, Any], c_inside: float) -> float:
    """The vent's resistance: a capillary {radius_m, length_m} (Poiseuille), or
    {lf_3db_hz} (the -3 dB point a data sheet gives: the time constant with the inside's
    compliances)."""
    if "lf_3db_hz" in v:
        return 1.0 / (2.0 * math.pi * v["lf_3db_hz"] * c_inside)
    return 8.0 * MU_AIR * v["length_m"] / (math.pi * v["radius_m"] ** 4)


_FIELDS = (
    "m_front", "c_diaphragm", "c_gap", "r_holes", "m_holes", "c_cavity", "r_vent", "c0_f",
    "c_stray_f", "gap_m", "displacement_per_volume", "neg_stiffness_per_v2",
)  # fmt: skip


def capsule_from_data(d: Mapping[str, Any], name: str = "capsule") -> Capsule:
    if d.get("kind") != "capsule" or d.get("form", "pressure") != "pressure":
        raise ValueError(f"{name} is not a capsule (kind {d.get('kind')!r})")
    lp = d["lumped"]
    missing = [k for k in _FIELDS if k not in lp]
    if missing:
        raise ValueError(f"{name}: lumped needs {missing}")
    return Capsule(d["name"], *(float(lp[k]) for k in _FIELDS))


def sensitivity(
    c: Capsule, f_hz: np.ndarray, e0_v: float, c_load_f: float = 0.0, r_load_ohm: float = np.inf
) -> np.ndarray:
    """Complex volts at the electrode per pascal at `front` (the network solved in the
    frequency domain: the reference the circuit's renders are tested against), into a
    load c_load_f || r_load_ohm from the electrode to the backplate's (AC) ground."""
    w = 2j * np.pi * np.asarray(f_hz, float)
    cd = c.c_diaphragm_at(e0_v)
    z_m = w * c.m_front
    z_d = 1.0 / (w * cd)
    # Behind the diaphragm: C_g || (R_h + M_h + (C_c || (R_v back to front))).
    # The vent returns to `front`: solve the two-loop network by nodal analysis.
    # Nodes: g (gap), c (cavity); unknown U (diaphragm volume velocity).
    y_g = w * c.c_gap
    y_c = w * c.c_cavity
    y_h = 1.0 / (c.r_holes + w * c.m_holes)
    y_v = 1.0 / c.r_vent
    z_s = z_m + z_d  # series branch front -> g
    y_s = 1.0 / z_s
    # KCL at g: y_s (p - pg) = y_g pg + y_h (pg - pc)
    # KCL at c: y_h (pg - pc) + y_v (p - pc) = y_c pc
    p = 1.0
    a11 = y_s + y_g + y_h
    a12 = -y_h
    a21 = -y_h
    a22 = y_h + y_v + y_c
    det = a11 * a22 - a12 * a21
    pg = (y_s * p * a22 - a12 * y_v * p) / det
    u = y_s * (p - pg)
    vol = u / w
    e_oc = c.volts_per_volume(e0_v) * vol
    # C0 carries the source; the stray capacitance sits across the electrode (as in
    # parts.capsule), in parallel with the load.
    y = w * (c_load_f + c.c_stray_f) + (0.0 if np.isinf(r_load_ohm) else 1.0 / r_load_ohm)
    return e_oc / (1.0 + y / (w * c.c0_f))


# --- Dual-diaphragm capsules (the Braunmuhl-Weber K47 / K67 family; A3) ----------------------
#
# Two equal diaphragms on either side of one thick backplate: each diaphragm's series
# branch (mass, compliance) from its outside pressure to its gap; each gap: the air film's
# compliance to ground, the squeeze film's resistance to the backplate's holes; blind holes
# (cavities) on each side, a resistance into a compliance; through-holes (a resistance and
# a mass) joining the two sides; a slow static-pressure leak from the through-holes to the
# ambient. Each diaphragm has its own electrical readout (its polarization may differ:
# the pattern is electrical, the sum and difference of two back-to-back cardioids).

DUAL_FIELDS = (
    "m_diaphragm", "c_diaphragm", "c_gap", "r_film", "r_blind", "c_blind", "r_through",
    "m_through", "r_leak", "c0_f", "c_stray_f", "gap_m", "displacement_per_volume",
    "neg_stiffness_per_v2",
)  # fmt: skip


@dataclass(frozen=True)
class DualCapsule:
    """A dual-diaphragm capsule's lumped elements (per side; the halves are equal)."""

    name: str
    m_diaphragm: float  # kg/m^4: a diaphragm's mass and its radiation mass
    c_diaphragm: float  # m^5/N: at zero polarization
    c_gap: float  # m^5/N: one side's air film
    r_film: float  # Pa s/m^3: one side's squeeze film to the holes
    r_blind: float  # Pa s/m^3: into one side's blind holes
    c_blind: float  # m^5/N: one side's blind holes
    r_through: float  # Pa s/m^3: the through-holes
    m_through: float  # kg/m^4
    r_leak: float  # Pa s/m^3: the static-pressure leak (to the ambient)
    c0_f: float  # F: one side's active capacitance
    c_stray_f: float  # F: one side's, across its electrode
    gap_m: float
    displacement_per_volume: float  # 1/m^2
    neg_stiffness_per_v2: float  # Pa/m^3 per V^2

    def c_diaphragm_at(self, e0_v: float) -> float:
        return 1.0 / (1.0 / self.c_diaphragm - self.neg_stiffness_per_v2 * e0_v * e0_v)

    def volts_per_volume(self, e0_v: float) -> float:
        return e0_v * self.displacement_per_volume / self.gap_m


def dual_capsule_from_data(d: Mapping[str, Any], name: str = "capsule") -> DualCapsule:
    if d.get("kind") != "capsule" or d.get("form") != "dual":
        raise ValueError(f"{name} is not a dual-diaphragm capsule")
    lp = d["lumped"]
    missing = [k for k in DUAL_FIELDS if k not in lp]
    if missing:
        raise ValueError(f"{name}: lumped needs {missing}")
    return DualCapsule(d["name"], *(float(lp[k]) for k in DUAL_FIELDS))


def dual_lumped(g: Mapping[str, Any]) -> dict[str, float]:
    """The lumped elements of a dual-diaphragm capsule from its geometry `g` (SI; both
    halves equal): diaphragm {radius_m, thickness_m, density_kg_m3, tension_n_m}, gap_m,
    backplate {radius_m, thickness_m, through: {holes, radius_m}, blind: {holes (per
    side), radius_m, depth_m}}, leak_time_s, stray_capacitance_f.

    The blind holes: their air isothermal (narrow holes), filled through a third of
    their depth's Poiseuille resistance (a closed tube's flow falls off toward its end;
    provisional: model knowledge). The squeeze film drains into all holes of its side.
    The leak: a resistance giving leak_time_s with the inside's compliances."""
    d, bp = g["diaphragm"], g["backplate"]
    a, h, b = d["radius_m"], g["gap_m"], bp["radius_m"]
    t_n_m = d["tension_n_m"]
    rho_s = d["density_kg_m3"] * d["thickness_m"]
    th, bl = bp["through"], bp["blind"]
    nt, rt, t = th["holes"], th["radius_m"], bp["thickness_m"]
    nb, rb, db = bl["holes"], bl["radius_m"], bl["depth_m"]
    n_all = nt + nb
    area_fraction = (nt * rt * rt + nb * rb * rb) / (b * b)
    skvor = area_fraction / 2.0 - area_fraction * area_fraction / 8.0
    skvor = skvor - math.log(area_fraction) / 4.0 - 3.0 / 8.0
    c_gap = math.pi * b * b * h / P0
    c_blind = nb * math.pi * rb * rb * db / P0
    kappa = 2.0 - b * b / (a * a)
    return {
        "m_diaphragm": 4.0 * rho_s / (3.0 * math.pi * a * a)
        + 8.0 * RHO_AIR / (3.0 * math.pi * math.pi * a),
        "c_diaphragm": math.pi * a**4 / (8.0 * t_n_m),
        "c_gap": c_gap,
        "r_film": 12.0 * MU_AIR / (n_all * math.pi * h**3) * skvor,
        "r_blind": 8.0 * MU_AIR * (db / 3.0) / (nb * math.pi * rb**4),
        "c_blind": c_blind,
        "r_through": 8.0 * MU_AIR * t / (nt * math.pi * rt**4),
        "m_through": 4.0
        * RHO_AIR
        * (t + 2.0 * END_CORRECTION * rt)
        / (3.0 * nt * math.pi * rt * rt),
        "r_leak": g["leak_time_s"] / (2.0 * (c_gap + c_blind)),
        "c0_f": EPS0 * math.pi * b * b / h,
        "c_stray_f": g["stray_capacitance_f"],
        "gap_m": h,
        "displacement_per_volume": kappa / (math.pi * a * a),
        "neg_stiffness_per_v2": EPS0 * b * b * kappa * kappa / (math.pi * h**3 * a**4),
        "membrane_resonance_hz": math.sqrt(6.0 * t_n_m / (rho_s * a * a)) / (2.0 * math.pi),
    }

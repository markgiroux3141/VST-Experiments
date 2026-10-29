"""Loudspeakers: a moving-coil driver from its physical quantities, its cabinet and the
listening point (component editor C3, docs/COMPONENT_EDITOR_PLAN.md).

A speaker component version (`config/components/<name>/<N>.yaml`, kind `speaker`) holds
the driver: the voice coil (DC resistance Re, inductance Le plus the eddy-current pair
L2 || R2 that makes it frequency-dependent: the "LR-2" model), the moving system (mass
Mms, compliance Cms, mechanical resistance Rms, motor strength BL, cone area Sd) and
the cone's breakup as modes. A circuit places it with the `speaker` macro (varimu.circuit
.parts.speaker), which also takes the cabinet (`Cabinet`) and the listening distance.

The model, in the circuit as plain elements (no new physics in the engines):

- The voice coil and the moving system are the driver's electrical equivalent: Re, Le,
  L2 || R2 in series with the motional network, the mechanical system seen through BL
  (mobility analogy: the voltage across it is BL times a velocity, the current through
  it a force over BL). The cone's rigid part (mass M0) is a capacitor M0 / BL^2, the
  suspension an inductor Cms BL^2, its loss a resistor BL^2 / Rms. Mms and Qms are the
  datasheet's free-air figures, so they already hold the air load (the air mass and the
  radiation resistance at Fs).
- Each breakup mode k is a mass m_k on a spring and damper hung from the voice coil
  (f_k = sqrt(k_k / m_k) / 2 pi with the coil held still, Q_k = sqrt(k_k m_k) / r_k):
  through BL, (R || L) from the coil's node to the mode's node and m_k / BL^2 from it to
  the speaker's minus terminal. M0 = Mms - sum(m_k), so at low frequencies the cone
  moves as one and the impedance keeps Re, Fs and Qts. Each mode radiates with its own
  signed share of the cone area, S0 = Sd - sum(S_k) for the rigid part: a modal
  expansion fitted to the published response, not ring geometry.
- The pressure at the listening point, on axis at `distance_m`, is read out without
  loading the driver (voltage-controlled current sources: the far field doesn't push
  back on the cone; what does, the air load, is in Mms and Rms):
  front: p_f = rho / (2 pi r) sum(S_x a_x), a baffled rigid piston's on-axis far field,
  exact on axis at any frequency (the textbook result, e.g. Kinsler et al., "Fundamentals
  of Acoustics"; Beranek, "Acoustics"); the accelerations are the
  derivatives of the radiating nodes' voltages (each source's current through one
  inductor);
  back (open back or a finite baffle): the back wave reaches the listener around each
  of the four edges of the baffle, inverted, low-passed by the cone's directivity at
  90 degrees (a piston's 2 J1(ka) / ka, -3 dB at ka = 1.616: approximated by one
  first-order pole there) and delayed by its extra path (`edge_taps`); the delays are
  taps on one lumped delay line (`LADDER_SECTION_S` per section, doubly terminated);
  heard: p = p_f - sum(w_e p_back(t - path_e / c)), in pascals as volts.

Not modelled: excursion nonlinearity (BL and Cms vs excursion: a later option), the
radiation resistance's rise with frequency beyond what the modes absorb, the cabinet's
internal resonances and its partial back panels, the front wave's own diffraction at the
edges beyond the edge model, the listener's room.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Air at 20 C and 101.325 kPa. Source: derived: the ideal gas law with R_specific
# 287.05 J/(kg K) at 293.15 K (101325 / (287.05 x 293.15) = 1.204 kg/m^3) and
# c = sqrt(1.4 x 287.05 x 293.15) = 343.2 m/s.
RHO_AIR_KG_M3 = 1.204
C_AIR_M_S = 343.2
P_REF_PA = 20e-6  # dB SPL reference

# A baffled piston's directivity 2 J1(x) / x falls to 1/sqrt(2) at x = ka sin(theta) = 1.616
# (derived: the root of 2 J1(x) / x = 1/sqrt(2)); the back wave turns ~90 degrees to reach
# an edge.
PISTON_KA_3DB = 1.616

# Numerical choices of the readout (not physics): each section of the delay line delays by
# LADDER_SECTION_S (its cutoff 1 / (pi LADDER_SECTION_S) = 5.1 kHz; the back wave is down
# by its directivity pole long before), and the readout's impedance level.
LADDER_SECTION_S = 62.5e-6
READOUT_OHM = 1000.0


@dataclass(frozen=True)
class Mode:
    """A breakup mode: its modal mass, frequency and Q with the voice coil held still,
    and its signed share of the radiating area."""

    mass_kg: float
    f_hz: float
    q: float
    area_m2: float


@dataclass(frozen=True)
class Speaker:
    name: str
    re_ohm: float
    le_h: float
    l2_h: float
    r2_ohm: float
    mms_kg: float
    cms_m_per_n: float
    rms_ns_per_m: float
    bl_tm: float
    sd_m2: float
    modes: tuple[Mode, ...]

    @property
    def fs_hz(self) -> float:
        return 1 / (2 * math.pi * math.sqrt(self.mms_kg * self.cms_m_per_n))

    @property
    def qms(self) -> float:
        return 2 * math.pi * self.fs_hz * self.mms_kg / self.rms_ns_per_m

    @property
    def qes(self) -> float:
        return 2 * math.pi * self.fs_hz * self.mms_kg * self.re_ohm / self.bl_tm**2

    @property
    def qts(self) -> float:
        return 1 / (1 / self.qms + 1 / self.qes)


@dataclass(frozen=True)
class Cabinet:
    """The baffle around the driver: its outer width and height, the depth of an
    open-back cabinet (0 for a flat baffle) and the driver's centre's offset from the
    baffle's centre (x to the right, y up)."""

    width_m: float
    height_m: float
    depth_m: float
    offset_x_m: float = 0.0
    offset_y_m: float = 0.0


# IEC 60268-5's standard baffle (the P12R sheet's DIN 45575 one): 1650 x 1350 mm, the
# drive unit 225 mm and 150 mm off the centre lines. Source: web:
# https://psqca.com.pk/cs/newitems2021/electronics/28-PS%20IEC%2060268-5-2014_FINAL.pdf
# (PS: IEC 60268-5/2014, the adoption of IEC 60268-5:2007), Figure 2; the size also
# web: https://www.klippel.de/fileadmin/klippel/Files/News/ALMA2016%20-%20The%20infinite%20baffle.pdf
IEC_BAFFLE = Cabinet(1.65, 1.35, 0.0, 0.225, 0.150)


def edge_taps(cab: Cabinet, distance_m: float) -> list[tuple[int, float]]:
    """(delay-line tap, weight) of the back wave around each edge: top, left, bottom,
    right. An edge at distance d from the driver's axis: the back wave goes from the cone
    to the open back's edge (sqrt(depth^2 + d^2)), forward along the outside (depth), and
    from the front edge to the listener on axis (sqrt(r^2 + d^2) against the front wave's
    r). Its share is the angle the edge subtends at the driver (the four add to one)
    times r / (r + path) for the longer way. The tap is the path over c in sections,
    rounded (half up: Rust's builder does the same)."""
    x0, x1 = -cab.width_m / 2 - cab.offset_x_m, cab.width_m / 2 - cab.offset_x_m
    y0, y1 = -cab.height_m / 2 - cab.offset_y_m, cab.height_m / 2 - cab.offset_y_m
    corners = [(x1, y1), (x0, y1), (x0, y0), (x1, y0)]  # counter-clockwise from top right
    angles = [math.atan2(y, x) for x, y in corners]
    dists = [y1, -x0, -y0, x1]  # top, left, bottom, right
    out = []
    r, depth = distance_m, cab.depth_m
    for e in range(4):
        span = angles[(e + 1) % 4] - angles[e]
        if span < 0:
            span += 2 * math.pi
        d = dists[e]
        path = math.sqrt(depth * depth + d * d) + depth + math.sqrt(r * r + d * d) - r
        tap = math.floor(path / (C_AIR_M_S * LADDER_SECTION_S) + 0.5)
        out.append((tap, span / (2 * math.pi) * r / (r + path)))
    return out


def directivity_pole_hz(sd_m2: float) -> float:
    """The back wave's low-pass: ka = PISTON_KA_3DB for the cone's equivalent radius."""
    a = math.sqrt(sd_m2 / math.pi)
    return PISTON_KA_3DB * C_AIR_M_S / (2 * math.pi * a)


def speaker_from_data(d: Mapping[str, Any], what: str = "speaker") -> Speaker:
    """A speaker version's data (kind speaker) as a Speaker."""
    if d.get("kind") != "speaker":
        raise ValueError(f"{what}: kind {d.get('kind')!r}, not a speaker")
    vc, mech = d["voice_coil"], d["moving_system"]
    modes: Sequence[Mapping[str, Any]] = d["modes"]["list"]
    return Speaker(
        name=d["name"],
        re_ohm=vc["re_ohm"],
        le_h=vc["le_h"],
        l2_h=vc["l2_h"],
        r2_ohm=vc["r2_ohm"],
        mms_kg=mech["mms_kg"],
        cms_m_per_n=mech["cms_m_per_n"],
        rms_ns_per_m=mech["rms_ns_per_m"],
        bl_tm=mech["bl_tm"],
        sd_m2=mech["sd_m2"],
        modes=tuple(Mode(m["mass_kg"], m["f_hz"], m["q"], m["area_m2"]) for m in modes),
    )

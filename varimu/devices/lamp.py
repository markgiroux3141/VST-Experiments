"""Incandescent lamps: a tungsten filament's resistance and heat balance (SYNTH_IDEAS.md #7).

A lamp is a device with pins (a, t, b) and two ports, both relative to b:

- the electrical port, V(a, b): the filament's current v / R(T), R(T) = rho(T) L / A;
- the thermal port, V(t, b) = T - T_amb in kelvin (1 V = 1 K). The circuit puts a 1 F
  capacitor from t to b (the thermal node: its voltage integrates dT/dt), and the port's
  current is dT/dt with the sign of a current into pin t:

      i_t = (P_rad(T) + P_cond(T) - v^2 / R(T)) / (m c_p(T)),

  so that the capacitor charges at (heat in - heat out) / heat capacity. Its steady state
  is the heat balance; a DC operating point is the hot filament. The thermal current
  closes through t and b only (the capacitor carries it back), so b's KCL sees only the
  electrical current.

The filament is lumped at one temperature: a wire of diameter d and (uncoiled) length L,
radiating from a fraction `rad_fraction` of its surface (a coil shades itself) as a grey
body against surroundings at T_amb, P_rad = sigma f pi d L eps(T) (T^4 - T_amb^4), and
conducting to its supports at T_amb at both ends: a uniformly heated rod with its ends held
has a mean rise of P L / (12 k A) (textbook), so P_cond = (12 A / L) * integral of k(T')
from T_amb to T (the Kirchhoff transform: exact for a temperature-dependent k at that
geometry). The heat capacity is m c_p(T), exact in T (the capacitor is 1 F, the device
divides).

Tungsten (P. Tolias, "Analytical expressions for thermophysical properties of solid and
liquid tungsten relevant for fusion applications", arXiv:1703.06302 (2017), web:
https://arxiv.org/abs/1703.06302):

- resistivity: the White-Minges fit (1997), 100-3600 K, 0.2% rms (Tolias Sec. II B);
- specific heat: the White-Minges fit, 300-3400 K, 1.1% rms (Sec. II C);
- thermal conductivity: the modified Hust-Lankford fit, 300-3700 K (Sec. II D).

The total emissivity eps(T) is a cubic per lamp component (`emissivity`, Horner
coefficients c0..c3), fitted by `varimu fit-devices` to Holladay's table
(data/datasheets/published_points.yaml, LAMP327). The temperature is clamped to
[T_MIN_K, T_MAX_K] (the fits' range; past it the filament has melted): there the model holds
its values at the edge plus a restoring G_EXT_PER_S (T - T_edge) in dT/dt, so a Newton
iterate that strays past the range is pulled back (the thermal port never loses its
conductance).

`Lamp.from_rating` solves d and L from a lamp's rated volts and amps at an assumed rated
filament temperature; `steady_k` is the temperature a constant voltage holds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from varimu.devices.triode import num

SIGMA_W_M2K4 = 5.670374419e-8  # Stefan-Boltzmann constant (CODATA 2018, exact in SI)
# Tungsten at room temperature (Tolias Sec. II E, White and Minges' reference density;
# thermal expansion, ~1% in length at 2400 K, is neglected).
DENSITY_KG_M3 = 19250.0
MOLAR_KG = 0.18384  # IUPAC 2013 standard atomic weight of W, 183.84 g/mol
T_MIN_K, T_MAX_K = 200.0, 3400.0
# dT/dt per kelvin past the fits' range (numerics only: ~a hot lamp's 1 / tau).
G_EXT_PER_S = 100.0

# White-Minges resistivity (1e-8 ohm m): -0.9680 + 1.9274e-2 T + 7.8260e-6 T^2
# - 1.8517e-9 T^3 + 2.0790e-13 T^4.
RHO = (-0.9680, 1.9274e-2, 7.8260e-6, -1.8517e-9, 2.0790e-13)
# White-Minges specific heat (J / (mol K)): 21.868372 + 8.068661e-3 T - 3.756196e-6 T^2
# + 1.075862e-9 T^3 + 1.406637e4 / T^2.
CP = (21.868372, 8.068661e-3, -3.756196e-6, 1.075862e-9, 1.406637e4)
# Modified Hust-Lankford conductivity (W / (m K)): 149.441 - 45.466e-3 T + 13.193e-6 T^2
# - 1.484e-9 T^3 + 3.866e6 / T^2.
KTH = (149.441, -45.466e-3, 13.193e-6, -1.484e-9, 3.866e6)


def clamp_k(t):
    return np.minimum(np.maximum(t, T_MIN_K), T_MAX_K)


def rho_ohm_m(t):
    """Resistivity (ohm m) and its derivative in T."""
    a0, a1, a2, a3, a4 = RHO
    r = (((a4 * t + a3) * t + a2) * t + a1) * t + a0
    d = ((4.0 * a4 * t + 3.0 * a3) * t + 2.0 * a2) * t + a1
    return r * 1e-8, d * 1e-8


def cp_j_kg_k(t):
    """Specific heat (J / (kg K)) and its derivative in T."""
    b0, b1, b2, b3, b4 = CP
    c = ((b3 * t + b2) * t + b1) * t + b0 + b4 / (t * t)
    d = (3.0 * b3 * t + 2.0 * b2) * t + b1 - 2.0 * b4 / (t * t * t)
    return c / MOLAR_KG, d / MOLAR_KG


def k_w_m_k(t):
    """Thermal conductivity (W / (m K))."""
    k0, k1, k2, k3, k4 = KTH
    return ((k3 * t + k2) * t + k1) * t + k0 + k4 / (t * t)


def k_integral(t):
    """An antiderivative of the conductivity in T (W / m)."""
    k0, k1, k2, k3, k4 = KTH
    return (((k3 / 4.0 * t + k2 / 3.0) * t + k1 / 2.0) * t + k0) * t - k4 / t


@dataclass(frozen=True)
class Lamp:
    name: str
    wire_d_m: float
    wire_l_m: float
    rad_fraction: float
    emissivity: tuple[float, float, float, float]  # c0..c3: eps(T) = c0 + c1 T + c2 T^2 + c3 T^3
    t_amb_k: float = 300.0

    @property
    def area_m2(self) -> float:
        return math.pi * self.wire_d_m * self.wire_d_m / 4.0

    @property
    def r_per_rho(self) -> float:
        """R / rho (1/m)."""
        return self.wire_l_m / self.area_m2

    @property
    def rad_area_m2(self) -> float:
        return self.rad_fraction * math.pi * self.wire_d_m * self.wire_l_m

    @property
    def g_cond_m(self) -> float:
        """12 A / L (m): the conduction loss is this times the integral of k."""
        return 12.0 * self.area_m2 / self.wire_l_m

    @property
    def mass_kg(self) -> float:
        return DENSITY_KG_M3 * self.area_m2 * self.wire_l_m

    def eps(self, t):
        """Total emissivity and its derivative in T."""
        c0, c1, c2, c3 = self.emissivity
        return ((c3 * t + c2) * t + c1) * t + c0, (3.0 * c3 * t + 2.0 * c2) * t + c1

    def r_ohm(self, t):
        return rho_ohm_m(clamp_k(np.asarray(t, float)))[0] * self.r_per_rho

    def p_loss_w(self, t):
        """Heat out at filament temperature T (radiation and conduction), W."""
        t = clamp_k(np.asarray(t, float))
        return self._loss(t)[0]

    def _loss(self, t):
        """(P_rad + P_cond, its derivative in T) at clamped T."""
        ta = self.t_amb_k
        e, de = self.eps(t)
        t2 = t * t
        ta2 = ta * ta
        q4 = t2 * t2 - ta2 * ta2
        sa = SIGMA_W_M2K4 * self.rad_area_m2
        p_rad = sa * e * q4
        dp_rad = sa * (de * q4 + e * 4.0 * t2 * t)
        g = self.g_cond_m
        p_cond = g * (k_integral(t) - k_integral(ta))
        dp_cond = g * k_w_m_k(t)
        return p_rad + p_cond, dp_rad + dp_cond

    def eval(self, v, u):
        """Port currents (i_a, i_t) and the Jacobian ((dia/dv, dia/du), (dit/dv, dit/du)) at
        the port voltages v = V(a, b), u = V(t, b) (arrays broadcast)."""
        v = np.asarray(v, float)
        u = np.asarray(u, float)
        traw = self.t_amb_k + u
        t = clamp_k(traw)
        inside = (traw >= T_MIN_K) & (traw <= T_MAX_K)
        rho, drho = rho_ohm_m(t)
        r = rho * self.r_per_rho
        dr = drho * self.r_per_rho
        ia = v / r
        heat = v * ia
        loss, dloss = self._loss(t)
        c, dc = cp_j_kg_k(t)
        mc = self.mass_kg * c
        dmc = self.mass_kg * dc
        it = (loss - heat) / mc + G_EXT_PER_S * (traw - t)
        dia_dv = 1.0 / r
        dit_dv = -2.0 * ia / mc
        dia_du = np.where(inside, -ia * (dr / r), 0.0)
        dit_du = np.where(inside, (dloss + heat * (dr / r)) / mc - it * (dmc / mc), G_EXT_PER_S)
        return (ia, it), ((dia_dv, dia_du), (dit_dv, dit_du))

    def currents(self, v, u):
        return self.eval(v, u)[0]

    def steady_k(self, v: float) -> float:
        """The filament temperature a constant voltage v across it holds."""
        if v == 0.0:
            return self.t_amb_k

        def f(t):
            return v * v / float(self.r_ohm(t)) - float(self.p_loss_w(t))

        return brentq(f, self.t_amb_k, T_MAX_K, xtol=1e-12, rtol=1e-14)

    @classmethod
    def from_rating(
        cls,
        name: str,
        v_rated: float,
        i_rated: float,
        t_rated_k: float,
        rad_fraction: float,
        emissivity: tuple[float, float, float, float],
        t_amb_k: float = 300.0,
    ) -> Lamp:
        """The wire (d, L) that draws i_rated at v_rated with its filament at t_rated_k: R
        fixes L / A, the heat balance at the rated power the surface (and the ends)."""
        r_rated = v_rated / i_rated
        p_rated = v_rated * i_rated
        rho_r = float(rho_ohm_m(t_rated_k)[0])
        # L = c d^2 with c = R pi / (4 rho); the loss rises monotonically with d at fixed c.

        def lamp(d):
            length = r_rated * math.pi * d * d / (4.0 * rho_r)
            return cls(name, d, length, rad_fraction, tuple(emissivity), t_amb_k)

        d = brentq(
            lambda d: float(lamp(d).p_loss_w(t_rated_k)) - p_rated,
            1e-7,
            1e-3,
            xtol=1e-18,
            rtol=1e-15,
        )
        return lamp(d)

    @property
    def subckt_name(self) -> str:
        return "LAMP_" + "".join(c if c.isalnum() else "_" for c in self.name).upper()

    def subckt(self) -> str:
        """SPICE subcircuit with pins (a, t, b); node tk holds the clamped temperature."""
        ta = self.t_amb_k
        tk = "V(tk)"
        a0, a1, a2, a3, a4 = RHO
        rho = (
            f"((((({num(a4)}*{tk}+{num(a3)})*{tk}+{num(a2)})*{tk}+{num(a1)})*{tk}+{num(a0)})*1e-8)"
        )
        r = f"({rho}*{num(self.r_per_rho)})"
        c0, c1, c2, c3 = self.emissivity
        eps = f"((({num(c3)}*{tk}+{num(c2)})*{tk}+{num(c1)})*{tk}+{num(c0)})"
        q4 = f"({tk}*{tk}*{tk}*{tk}-{num(ta**4)})"
        p_rad = f"{num(SIGMA_W_M2K4 * self.rad_area_m2)}*{eps}*{q4}"
        k0, k1, k2, k3, k4 = KTH
        kint = (
            f"(((({num(k3 / 4.0)}*{tk}+{num(k2 / 3.0)})*{tk}+{num(k1 / 2.0)})*{tk}"
            f"+{num(k0)})*{tk}-{num(k4)}/{tk})"
        )
        p_cond = f"{num(self.g_cond_m)}*({kint}-{num(float(k_integral(ta)))})"
        b0, b1, b2, b3, b4 = CP
        cp = (
            f"(((({num(b3)}*{tk}+{num(b2)})*{tk}+{num(b1)})*{tk}+{num(b0)}"
            f"+{num(b4)}/({tk}*{tk}))/{num(MOLAR_KG)})"
        )
        heat = f"V(a,b)*V(a,b)/{r}"
        return (
            f"* {self.name}: generated by varimu.devices.lamp\n"
            f".subckt {self.subckt_name} a t b\n"
            f"Btk tk 0 V={{min(max(V(t,b)+{num(ta)},{num(T_MIN_K)}),{num(T_MAX_K)})}}\n"
            f"Ba a b I={{V(a,b)/{r}}}\n"
            f"Bt t b I={{({p_rad}+{p_cond}-{heat})/({num(self.mass_kg)}*{cp})"
            f"+{num(G_EXT_PER_S)}*(V(t,b)+{num(ta)}-{tk})}}\n"
            f".ends {self.subckt_name}\n"
        )


def lamp_from_data(d: dict, ref: str) -> Lamp:
    """A lamp component version's model (its derived wire and emissivity)."""
    w = d["filament"]
    return Lamp(
        d["name"],
        w["wire_d_m"],
        w["wire_l_m"],
        w["rad_fraction"],
        tuple(d["emissivity"]["coeffs"]),
        d["t_amb_k"],
    )

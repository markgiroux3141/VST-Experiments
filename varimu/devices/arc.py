"""A carbon arc (docs/INVENTED_LIVE_PLAN.md IL7; the Arc Organ, docs/INVENTED_DEVICES.md I13):
Mayr's arc whose steady state is Ayrton's static law.

A DC carbon arc's voltage falls as its current rises (Hertha Ayrton, The Electric Arc, 1902:
V = a + b l + (c + d l) / I for solid carbons, l the gap in mm), so an LC tank across it
oscillates (Duddell's singing arc, 1900). Mayr's model (O. Mayr, "Beitraege zur Theorie des
statischen und des dynamischen Lichtbogens", Archiv fuer Elektrotechnik 37, 1943) gives the
arc's conductance g a thermal memory:

    d ln g / dt = (v i / P(i) - 1) / tau,

with the loss P(i) = (a + b l) |i| + (c + d l) taken from Ayrton's law (its steady state
v i = P(i) is then V(I) = a + b l + (c + d l) / I exactly). The sketch (varimu.invented.arc)
adds a strike (hot carbons restrike above STRIKE_V: the conductance then grows at RATIO_MAX /
tau), a cap on the ratio (RATIO_MAX) and a floor on the conductance (the hot carbons' residual
G_FLOOR_S).

An arc is a device with pins (a, s, w, b) and three ports, all relative to b:

- the electrical port, V(a, b): the arc's current g v;
- the state port, V(s, b) = ln(g / 1 S) (1 V = 1 neper). The circuit puts a 1 F capacitor
  from s to b, and the port's current is -d ln g / dt (a current into pin s discharges it),
  as the lamp's thermal port (varimu.devices.lamp). A DC operating point is the burning arc
  on its static curve. Give s a leak too (~1 GOhm): at 0 V the growth doesn't depend on the
  state, so Newton's first iterate from rest has no DC path there;
- the power readout, pin w: the power the arc dissipates, v i, out of pin w (its current
  -v i; 1 A = 1 W). The arc is its own loudspeaker (a thermophone: its heat swings, the hot
  gas expands and contracts): a circuit loads w with 1 ohm (V(w) = the power) and
  differentiates it into the pressure (`thermophone_rc_s`). The port draws nothing from the
  arc; its own voltage moves nothing.

Numerics (none of it in the steady state): |i| is smoothed as sqrt(i^2 + I_SMOOTH_A^2) (the
Jacobian has no kink at zero current); the strike ramps in over STRIKE_RAMP_V above STRIKE_V
(a step would stall Newton); past [ln G_FLOOR_S, LN_G_MAX] the model holds the edge's values
and pulls the state back at G_EXT_PER_S per neper (the floor and the cap the sketch clamps).

The gap l is the instance's (`gap_mm`: the ARC GAP; the carbons' feed sets it).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from varimu.devices.triode import num

I_SMOOTH_A = 1e-3
STRIKE_RAMP_V = 5.0
G_EXT_PER_S = 1e7  # ~300 / tau: the state overshoots the floor by ~(1 / tau) / G_EXT, 3 mNp
GAMMA_AIR = 1.4
C_AIR_M_S = 343.0


def thermophone_rc_s(r_m: float) -> float:
    """Pressure (Pa) r_m from a small heat source per watt per second of its power's change:
    the gas's expansion is a volume velocity (gamma - 1) / (rho c^2) Q, radiating as a monopole
    rho / (4 pi r) dU/dt, so p = (gamma - 1) / (4 pi r c^2) dQ/dt (the thermophone; Arnold and
    Crandall, Phys. Rev. 10, 1917). A C-R differentiator with this RC turns V(w) into pascals."""
    return (GAMMA_AIR - 1.0) / (4.0 * math.pi * r_m * C_AIR_M_S * C_AIR_M_S)


@dataclass(frozen=True)
class Arc:
    name: str
    a_v: float  # Ayrton's a, b, c, d (V, V/mm, W, W/mm)
    b_v_mm: float
    c_w: float
    d_w_mm: float
    tau_s: float  # Mayr's thermal time constant
    v_strike_v: float
    ratio_max: float
    g_floor_s: float
    ln_g_max: float
    gap_mm: float = 2.0

    @property
    def pa(self) -> float:
        """Ayrton's a + b l (V): the loss per ampere."""
        return self.a_v + self.b_v_mm * self.gap_mm

    @property
    def pc(self) -> float:
        """Ayrton's c + d l (W)."""
        return self.c_w + self.d_w_mm * self.gap_mm

    def static_v(self, i_a):
        """Ayrton's V(I) at this gap."""
        return self.pa + self.pc / np.asarray(i_a, float)

    def eval(self, v, u, w=0.0):
        """Port currents (i_a, i_s, i_w) and the Jacobian (row per current, column per port
        voltage) at the port voltages v = V(a, b), u = V(s, b), w = V(w, b) (arrays
        broadcast; nothing depends on w)."""
        v = np.asarray(v, float)
        u = np.asarray(u, float)
        lo = math.log(self.g_floor_s)
        x = np.minimum(np.maximum(u, lo), self.ln_g_max)
        inside = (u >= lo) & (u <= self.ln_g_max)
        g = np.exp(x)
        ia = g * v
        dia_dv = g
        dia_du = np.where(inside, ia, 0.0)
        ai = np.sqrt(ia * ia + I_SMOOTH_A * I_SMOOTH_A)
        loss = self.pa * ai + self.pc
        p = ia * v
        ratio = p / loss
        # d(ratio) = (dp loss - p dloss) / loss^2, dp = 2 g v dv + p du, dloss = pa (i / ai) di
        di_dv, di_du = g, ia
        dl = self.pa * (ia / ai)
        dr_dv = (2.0 * g * v * loss - p * dl * di_dv) / (loss * loss)
        dr_du = (p * loss - p * dl * di_du) / (loss * loss)
        dr_du = np.where(inside, dr_du, 0.0)
        av = np.abs(v)
        ramp = np.clip((av - self.v_strike_v) / STRIKE_RAMP_V, 0.0, 1.0)
        strike = self.ratio_max * ramp
        ds_dv = np.where(
            (av > self.v_strike_v) & (av < self.v_strike_v + STRIKE_RAMP_V),
            self.ratio_max * np.sign(v) / STRIKE_RAMP_V,
            0.0,
        )
        struck = strike > ratio
        r = np.where(struck, strike, ratio)
        r_dv = np.where(struck, ds_dv, dr_dv)
        r_du = np.where(struck, 0.0, dr_du)
        capped = r > self.ratio_max
        r = np.where(capped, self.ratio_max, r)
        r_dv = np.where(capped, 0.0, r_dv)
        r_du = np.where(capped, 0.0, r_du)
        i_s = -(r - 1.0) / self.tau_s + G_EXT_PER_S * (u - x)
        dis_dv = -r_dv / self.tau_s
        dis_du = np.where(inside, -r_du / self.tau_s, G_EXT_PER_S)
        zero = np.zeros_like(p + np.asarray(w, float))
        return (ia + zero, i_s + zero, -p + zero), (
            (dia_dv + zero, dia_du + zero, zero),
            (dis_dv + zero, dis_du + zero, zero),
            (-2.0 * g * v + zero, np.where(inside, -p, 0.0) + zero, zero),
        )

    def currents(self, v, u, w=0.0):
        return self.eval(v, u, w)[0]

    def steady_ln_g(self, i_a: float) -> float:
        """The state of an arc burning at i_a on its static curve."""
        return math.log(i_a / float(self.static_v(i_a)))

    @property
    def subckt_name(self) -> str:
        return "ARC_" + "".join(c if c.isalnum() else "_" for c in self.name).upper()

    def subckt(self) -> str:
        """SPICE subcircuit with pins (a, s, w, b); node x holds the clamped state."""
        lo = math.log(self.g_floor_s)
        g = "exp(V(x))"
        i = f"({g}*V(a,b))"
        ai = f"sqrt({i}*{i}+{num(I_SMOOTH_A * I_SMOOTH_A)})"
        ratio = f"({i}*V(a,b)/({num(self.pa)}*{ai}+{num(self.pc)}))"
        ramp = f"min(max((abs(V(a,b))-{num(self.v_strike_v)})/{num(STRIKE_RAMP_V)},0),1)"
        strike = f"({num(self.ratio_max)}*{ramp})"
        r = f"min(max({ratio},{strike}),{num(self.ratio_max)})"
        return (
            f"* {self.name}: generated by varimu.devices.arc\n"
            f".subckt {self.subckt_name} a s w b\n"
            f"Bx x 0 V={{min(max(V(s,b),{num(lo)}),{num(self.ln_g_max)})}}\n"
            f"Ba a b I={{{i}}}\n"
            f"Bs s b I={{-({r}-1)/{num(self.tau_s)}+{num(G_EXT_PER_S)}*(V(s,b)-V(x))}}\n"
            f"Bw w b I={{-{i}*V(a,b)}}\n"
            f".ends {self.subckt_name}\n"
        )


def arc_from_data(d: dict, ref: str) -> Arc:
    """An arc component version's model (its gap the instance's)."""
    a = d["ayrton"]
    m = d["mayr"]
    return Arc(
        d["name"],
        a["a_v"],
        a["b_v_mm"],
        a["c_w"],
        a["d_w_mm"],
        m["tau_s"],
        m["v_strike_v"],
        m["ratio_max"],
        m["g_floor_s"],
        m["ln_g_max"],
    )

"""Junction field-effect transistors: SPICE's level-1 JFET (Shichman-Hodges with the
Sydney University doping tail B), the DC model.

A JFET is a device with pins (d, g, s) and two ports relative to the source, V(d, s) and
V(g, s); the port currents flow into the drain and the gate (the source carries their sum
back). N-channel and P-channel (`polarity` njf / pjf): a P-channel JFET is the N-channel's
equations on the negated voltages, its currents negated.

The model is ngspice's JFET level 1 (`jfetload.c`) with the parameters VTO, BETA, LAMBDA,
IS, N, B and PB, at TNOM = 27 C (no temperature scaling), so ngspice's native `J` element
with a `.model ... NJF(...)` / `PJF(...)` card of the same parameters is this model's SPICE
implementation (`model_card`). With Vt = k T / q, the gate junctions (gate to source, gate to
drain) are diodes

    Igs = IS (exp(vgs / (N Vt)) - 1),   Igd = IS (exp(vgd / (N Vt)) - 1),

and the channel current in normal mode (vds >= 0), with vgst = vgs - VTO,
bfac = (1 - B) / (PB - VTO) and beta' = BETA (1 + LAMBDA vds):

    vgst <= 0:           Ich = 0                                     (cut off)
    0 < vds <= vgst:     Ich = beta' vds (vds (bfac vds - B) + vgst (2 B + 3 bfac (vgst - vds)))
    vds > vgst:          Ich = beta' vgst^2 (B + bfac vgst)          (saturated)

(B = 1, SPICE's default: the textbook square law, beta' vds (2 vgst - vds) and beta' vgst^2).
In inverse mode (vds < 0) source and drain trade places: Ich = -f(vgd, -vds), f the normal
mode's function, which is ngspice's inverse-mode formula. Into the drain flows Ich - Igd,
into the gate Igs + Igd.

Differences from ngspice's evaluation, below the agreement tests' floor: ngspice replaces
a gate junction's current below -5 N Vt by -IS (here the exponential throughout: they differ
by < 0.007 IS there), and ngspice adds GMIN (1e-12 S) across both gate junctions, which
circuitsim's MNA stamps the same way (`mna.rs`); the tests add it to the reference. Above
EXP_MAX the junction exponentials continue linearly (numerics only, as the BJT's).

**What is left out, and why (2026-11-06, DEVICE_BUILDER_PLAN.md B12, CHAINS_PLAN.md WP21).**
The device is stateless, like the BJT: the gate junctions' depletion charge isn't the
device's. RD and RS are linear elements the `jfet` part macro places around the device
(internal nodes where nonzero), CGS and CGD linear capacitors at zero bias (an upper bound:
a few pF, which audio impedances don't reach). No temperature (VTOTC, BETATCE, XTI, EG
keep their TNOM values), no noise yet.

Component files (kind `jfet`, config/components/<name>/<N>.yaml): `polarity`, a `dc` block
(vto_v, beta_a_per_v2, lambda_per_v, is_a, n, b, pb_v), a `parasitics` block (rd_ohm, rs_ohm,
cgs_f, cgd_f) and the published card verbatim (`card`) with its source; written by `varimu
fit-devices` (library.build_2n3819, ...) from data/datasheets/published_points.yaml.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from varimu.devices.diode import VT_TNOM
from varimu.devices.triode import num

EXP_MAX = 80.0
_E_MAX = math.exp(EXP_MAX)
# ngspice's default GMIN across each gate junction (S): the tests' reference adds it.
SPICE_GMIN = 1e-12

POLARITIES = ("njf", "pjf")


def _exp(x):
    """exp(x) and its derivative, continued linearly above EXP_MAX."""
    x = np.asarray(x, float)
    e = np.exp(np.minimum(x, EXP_MAX))
    big = x > EXP_MAX
    if np.any(big):
        e = np.where(big, _E_MAX * (1.0 + (x - EXP_MAX)), e)
        d = np.where(big, _E_MAX, e)
        return e, d
    return e, e


@dataclass(frozen=True)
class Jfet:
    name: str
    polarity: str  # "njf" | "pjf"
    vto_v: float
    beta_a_per_v2: float
    lambda_per_v: float = 0.0
    is_a: float = 1e-14
    n: float = 1.0
    b: float = 1.0
    pb_v: float = 1.0
    # The part macro's linear elements (not the device's): the module docstring.
    rd_ohm: float = 0.0
    rs_ohm: float = 0.0
    cgs_f: float = 0.0
    cgd_f: float = 0.0

    @property
    def sign(self) -> float:
        return 1.0 if self.polarity == "njf" else -1.0

    @property
    def bfac(self) -> float:
        return (1.0 - self.b) / (self.pb_v - self.vto_v)

    def _normal(self, vgs, vds):
        """The normal mode's channel current (vds >= 0) and its derivatives
        (I, dI/dvgs, dI/dvds), N-channel signs."""
        vgst = vgs - self.vto_v
        lam, beta, b, bfac = self.lambda_per_v, self.beta_a_per_v2, self.b, self.bfac
        betap = beta * (1.0 + lam * vds)
        on = vgst > 0.0
        lin = on & (vgst >= vds)
        sat = on & (vgst < vds)
        # Linear region.
        apart = 2.0 * b + 3.0 * bfac * (vgst - vds)
        cpart_l = vds * (vds * (bfac * vds - b) + vgst * apart)
        # d cpart / d vgst and / d vds (vgst and vds independent).
        dcl_g = vds * (apart + 3.0 * bfac * vgst)
        dcl_d = (vds * (bfac * vds - b) + vgst * apart) + vds * (
            2.0 * bfac * vds - b - 3.0 * bfac * vgst
        )
        # Saturation.
        cpart_s = vgst * vgst * (b + bfac * vgst)
        dcs_g = vgst * (2.0 * b + 3.0 * bfac * vgst)
        cpart = np.where(lin, cpart_l, np.where(sat, cpart_s, 0.0))
        dc_g = np.where(lin, dcl_g, np.where(sat, dcs_g, 0.0))
        dc_d = np.where(lin, dcl_d, 0.0)
        i = betap * cpart
        di_g = betap * dc_g
        di_d = betap * dc_d + beta * lam * cpart
        return i, di_g, di_d

    def channel(self, vgs, vds):
        """N-channel-signed (vgs, vds) -> (Ich, dIch/dvgs, dIch/dvds), both modes."""
        vgs, vds = np.asarray(vgs, float), np.asarray(vds, float)
        vgd = vgs - vds
        i_n, dn_g, dn_d = self._normal(vgs, np.maximum(vds, 0.0))
        # Inverse: Ich = -f(vgd, -vds); d/dvgs = -f_g; d/dvds = -(f_g * -1 + f_d * -1).
        i_r, dr_g, dr_d = self._normal(vgd, np.maximum(-vds, 0.0))
        fwd = vds >= 0.0
        i = np.where(fwd, i_n, -i_r)
        di_g = np.where(fwd, dn_g, -dr_g)
        di_d = np.where(fwd, dn_d, dr_g + dr_d)
        return i, di_g, di_d

    def gate(self, v):
        """A gate junction's current and conductance at its forward voltage v."""
        nvt = self.n * VT_TNOM
        e, de = _exp(np.asarray(v, float) / nvt)
        return self.is_a * (e - 1.0), self.is_a * de / nvt

    def currents(self, vds, vgs):
        """Port voltages (V(d, s), V(g, s)) -> (Id, Ig) into the drain and the gate."""
        s = self.sign
        vds, vgs = s * np.asarray(vds, float), s * np.asarray(vgs, float)
        ich, _, _ = self.channel(vgs, vds)
        igs, _ = self.gate(vgs)
        igd, _ = self.gate(vgs - vds)
        return s * (ich - igd), s * (igs + igd)

    def jacobian(self, vds, vgs):
        """d(Id, Ig) / d(vds, vgs): [[dId/dvds, dId/dvgs], [dIg/dvds, dIg/dvgs]]."""
        s = self.sign
        vds, vgs = s * np.asarray(vds, float), s * np.asarray(vgs, float)
        _, di_g, di_d = self.channel(vgs, vds)
        _, ggs = self.gate(vgs)
        _, ggd = self.gate(vgs - vds)
        # Igd depends on vgd = vgs - vds.
        return np.array([[di_d + ggd, di_g - ggd], [-ggd, ggs + ggd]])

    @property
    def model_name(self) -> str:
        return "J_" + "".join(c if c.isalnum() else "_" for c in self.name).upper()

    def model_card(self) -> str:
        """ngspice's native JFET with this model's DC parameters (the parasitics are the
        part's elements, not the card's)."""
        p = [("VTO", self.vto_v), ("BETA", self.beta_a_per_v2), ("LAMBDA", self.lambda_per_v)]
        p += [("IS", self.is_a), ("N", self.n), ("B", self.b), ("PB", self.pb_v)]
        body = " ".join(f"{k}={num(v)}" for k, v in p)
        return f".model {self.model_name} {self.polarity.upper()}({body})\n"


def jfet_from_data(d: dict[str, Any], name: str) -> Jfet:
    """A component file's data (kind `jfet`) as a model."""
    if d.get("polarity") not in POLARITIES:
        raise ValueError(f"{name}: polarity must be one of {POLARITIES}")
    dc, par = d["dc"], d.get("parasitics", {})
    return Jfet(
        d["name"],
        d["polarity"],
        float(dc["vto_v"]),
        float(dc["beta_a_per_v2"]),
        lambda_per_v=float(dc.get("lambda_per_v", 0.0)),
        is_a=float(dc.get("is_a", 1e-14)),
        n=float(dc.get("n", 1.0)),
        b=float(dc.get("b", 1.0)),
        pb_v=float(dc.get("pb_v", 1.0)),
        rd_ohm=float(par.get("rd_ohm", 0.0)),
        rs_ohm=float(par.get("rs_ohm", 0.0)),
        cgs_f=float(par.get("cgs_f", 0.0)),
        cgd_f=float(par.get("cgd_f", 0.0)),
    )


def parse_card(card: str) -> tuple[str, dict[str, float]]:
    """A SPICE `.model NAME NJF(K=V ...)` card -> (polarity, {KEY: value})."""
    from varimu.devices.bjt import _spice_number

    head, _, body = card.partition("(")
    words = head.split()
    if len(words) < 3 or words[0].lower() != ".model":
        raise ValueError(f"not a .model card: {card[:40]!r}")
    polarity = words[2].lower()
    if polarity not in POLARITIES:
        raise ValueError(f"{words[1]}: {polarity} is not a JFET")
    out: dict[str, float] = {}
    for tok in body.rstrip(") \n").replace("\n+", " ").split():
        key, _, val = tok.partition("=")
        try:
            out[key.upper()] = _spice_number(val)
        except ValueError:
            continue  # vendor fields (mfg=..., Vds=..., ...)
    return polarity, out

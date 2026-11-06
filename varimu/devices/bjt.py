"""Bipolar junction transistors: SPICE's Gummel-Poon transport model, a DC subset.

A BJT is a device with pins (c, b, e) and two ports relative to the emitter, V(c, e) and
V(b, e); the port currents flow into the collector and the base (the emitter carries
their sum back). NPN and PNP (`polarity`): a PNP is the NPN's equations on the negated
junction voltages, its currents negated.

The model is SPICE's Gummel-Poon BJT (ngspice `bjtload.c`, SPICE3 level 1) with the DC
parameters IS, BF, BR, NF, NR, VAF, VAR, IKF, IKR, ISE, NE, ISC, NC, with SPICE's
definitions and defaults (VAF, VAR, IKF, IKR absent: infinite; ISE, ISC 0; NE 1.5, NC 2),
at TNOM = 27 C (no temperature scaling). So ngspice's native `Q` element with a `.model
... NPN(...)` / `PNP(...)` card of the same DC parameters is this model's SPICE
implementation (`model_card`). In the junction voltages vbe, vbc (NPN signs):

    Ibe = IS (exp(vbe / (NF Vt)) - 1),   Ibc = IS (exp(vbc / (NR Vt)) - 1),
    Iben = ISE (exp(vbe / (NE Vt)) - 1), Ibcn = ISC (exp(vbc / (NC Vt)) - 1),
    q1 = 1 / (1 - vbc / VAF - vbe / VAR),   q2 = Ibe / IKF + Ibc / IKR,
    qb = q1 (1 + sqrt(1 + 4 q2)) / 2,
    Ic = (Ibe - Ibc) / qb - Ibc / BR - Ibcn,
    Ib = Ibe / BF + Iben + Ibc / BR + Ibcn.

Differences from ngspice's evaluation, all below the agreement tests' floor: SPICE
continues a junction's exponential below -3 n Vt with a cubic (here the exponential
throughout: they differ by < 0.1 IS there), and ngspice adds GMIN (1e-12 S) across both
junctions, which circuitsim's MNA stamps the same way, as it does across a diode
(`mna.rs`), and across its substrate junction (to ground; this model has no substrate);
the tests add both to the reference. Above EXP_MAX (a junction forward-biased by
~2 V, which no working circuit reaches: the solver limits junction steps first) the
exponentials continue linearly, so a stray Newton iterate never overflows (numerics only).

**What is left out, and why (decided 2026-11-06, CLAVINET_PLAN.md CL0, CHAINS_PLAN.md
WP10).** The device is stateless, like the diode and the triode: no charge storage in the
device. The transit time TF and the diffusion charge are left out (audio transistors have
fT of 100+ MHz: the BC550's datasheet gives fT >= 100 MHz; TF's charge matters above a few
MHz at audio impedances). The series resistances RB, RC, RE and the junction
capacitances CJE, CJC are kept, as *linear* elements the `bjt` part macro places around
the device (internal nodes where a resistance is nonzero; varimu.circuit.parts.bjt), not as
the device's nonlinear depletion charge: CJE at zero bias (a forward-biased junction's is
at least that), CJC at a stated reverse bias (the component file's `parasitics` block says
which). RB is constant (IRB, RBM unused). No substrate, no excess phase.
No noise yet (shot noise of the junctions and RB's Johnson noise are later work: a `bjt`
part gets no noise elements under a noise block).

**Temperature (2026-11-06, DEVICE_BUILDER_PLAN.md B11).** A model whose `temp_k` is set is
evaluated at that junction temperature, by SPICE's scaling (ngspice `bjttemp.c`, TLEV 0):
Vt = k T / q, and with r = T / TNOM, f = (r - 1) EG / Vt + XTI ln r, b = r^XTB,

    IS(T) = IS e^f,  BF(T) = BF b,  BR(T) = BR b,
    ISE(T) = ISE e^(f / NE) / b,  ISC(T) = ISC e^(f / NC) / b

(EG, XTI, XTB: `eg_ev`, `xti`, `xtb`, SPICE's defaults 1.11, 3, 0 when None). The other
parameters keep their values (their temperature coefficients default to zero in SPICE).
ngspice's instance parameter `temp` is its SPICE implementation. `temp_k` None is TNOM,
exactly the model before temperature (every existing IR unchanged). A circuit sets it per
`devices` entry (`temp_c`): matched transistors on one die share one temperature.

The model's dataclass carries the parasitics too (rb_ohm .. cjc_f), so that an instance's
`area` scales them with the junctions (SPICE's area factor: IS, ISE, ISC, IKF, IKR and
the capacitances times it, the resistances over it); the device's equations ignore them,
and the generic `device` part refuses a BJT (it would drop them): use the `bjt` part.

Component files (kind `bjt`, config/components/<name>/<N>.yaml): `polarity`, a `dc` block
of the card's DC parameters, a `parasitics` block, and the published card verbatim
(`card`) with its source; written by `varimu fit-devices` (library.build_bc550c, ...) from
data/datasheets/published_points.yaml.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from varimu.devices.diode import VT_TNOM
from varimu.devices.triode import num

# Exponent past which a junction's exponential continues linearly (numerics only).
EXP_MAX = 80.0
_E_MAX = math.exp(EXP_MAX)
# ngspice's default GMIN across each junction (S): the tests' reference adds it.
SPICE_GMIN = 1e-12
# ngspice's constants (const.h): k / q as it precomputes it, TNOM (REFTEMP) in kelvin.
K_OVER_Q = 1.38064852e-23 / 1.6021766208e-19
TNOM_K = 300.15
# SPICE's defaults for the temperature parameters.
EG_DEFAULT_EV, XTI_DEFAULT, XTB_DEFAULT = 1.11, 3.0, 0.0

POLARITIES = ("npn", "pnp")


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
class Bjt:
    name: str
    polarity: str  # "npn" | "pnp"
    is_a: float
    bf: float
    br: float = 1.0
    nf: float = 1.0
    nr: float = 1.0
    vaf_v: float | None = None  # None: infinite (no Early effect)
    var_v: float | None = None
    ikf_a: float | None = None  # None: infinite (no high injection)
    ikr_a: float | None = None
    ise_a: float = 0.0
    ne: float = 1.5
    isc_a: float = 0.0
    nc: float = 2.0
    # The part macro's linear elements (not the device's): the module docstring.
    rb_ohm: float = 0.0
    rc_ohm: float = 0.0
    re_ohm: float = 0.0
    cje_f: float = 0.0
    cjc_f: float = 0.0
    # Temperature (the module docstring): None = TNOM / SPICE's defaults.
    temp_k: float | None = None
    eg_ev: float | None = None
    xti: float | None = None
    xtb: float | None = None

    def at_temperature(self) -> tuple[float, float, float, float, float, float]:
        """(Vt, IS, BF, BR, ISE, ISC) at the model's temperature (TNOM's values when
        `temp_k` is None)."""
        if self.temp_k is None:
            return VT_TNOM, self.is_a, self.bf, self.br, self.ise_a, self.isc_a
        t = self.temp_k
        eg = EG_DEFAULT_EV if self.eg_ev is None else self.eg_ev
        xti = XTI_DEFAULT if self.xti is None else self.xti
        xtb = XTB_DEFAULT if self.xtb is None else self.xtb
        vt = t * K_OVER_Q
        ratlog = math.log(t / TNOM_K)
        ratio1 = t / TNOM_K - 1.0
        factlog = ratio1 * eg / vt + xti * ratlog
        factor = math.exp(factlog)
        bfactor = math.exp(ratlog * xtb)
        return (
            vt,
            self.is_a * factor,
            self.bf * bfactor,
            self.br * bfactor,
            self.ise_a * math.exp(factlog / self.ne) / bfactor,
            self.isc_a * math.exp(factlog / self.nc) / bfactor,
        )

    @property
    def sign(self) -> float:
        return 1.0 if self.polarity == "npn" else -1.0

    def junction(self, vbe, vbc):
        """NPN-signed (vbe, vbc) -> (Ic, Ib, dIc/dvbe, dIc/dvbc, dIb/dvbe, dIb/dvbc)."""
        vbe, vbc = np.asarray(vbe, float), np.asarray(vbc, float)
        vt, is_a, bf, br, ise_a, isc_a = self.at_temperature()
        nfv, nrv = self.nf * vt, self.nr * vt
        ef, dfe = _exp(vbe / nfv)
        er, dre = _exp(vbc / nrv)
        ibe = is_a * (ef - 1.0)
        gbe = is_a * dfe / nfv
        ibc = is_a * (er - 1.0)
        gbc = is_a * dre / nrv
        if ise_a > 0.0:
            nev = self.ne * vt
            en, den = _exp(vbe / nev)
            iben = ise_a * (en - 1.0)
            gben = ise_a * den / nev
        else:
            iben = gben = np.zeros_like(vbe)
        if isc_a > 0.0:
            ncv = self.nc * vt
            ec, dec = _exp(vbc / ncv)
            ibcn = isc_a * (ec - 1.0)
            gbcn = isc_a * dec / ncv
        else:
            ibcn = gbcn = np.zeros_like(vbc)
        inv_f = 0.0 if self.vaf_v is None else 1.0 / self.vaf_v
        inv_r = 0.0 if self.var_v is None else 1.0 / self.var_v
        oik = 0.0 if self.ikf_a is None else 1.0 / self.ikf_a
        oikr = 0.0 if self.ikr_a is None else 1.0 / self.ikr_a
        q1 = 1.0 / (1.0 - inv_f * vbc - inv_r * vbe)
        if oik == 0.0 and oikr == 0.0:
            qb = q1
            dqb_e = q1 * qb * inv_r
            dqb_c = q1 * qb * inv_f
        else:
            q2 = oik * ibe + oikr * ibc
            sq = np.sqrt(np.maximum(1.0 + 4.0 * q2, 0.0))
            qb = q1 * (1.0 + sq) / 2.0
            dqb_e = q1 * (qb * inv_r + oik * gbe / sq)
            dqb_c = q1 * (qb * inv_f + oikr * gbc / sq)
        it = (ibe - ibc) / qb
        ic = it - ibc / br - ibcn
        ib = ibe / bf + iben + ibc / br + ibcn
        dic_e = gbe / qb - it / qb * dqb_e
        dic_c = -gbc / qb - it / qb * dqb_c - gbc / br - gbcn
        dib_e = gbe / bf + gben
        dib_c = gbc / br + gbcn
        return ic, ib, dic_e, dic_c, dib_e, dib_c

    def currents(self, vce, vbe):
        """Port voltages (V(c, e), V(b, e)) -> (Ic, Ib) into the collector and base."""
        s = self.sign
        vce, vbe = np.asarray(vce, float), np.asarray(vbe, float)
        ic, ib, *_ = self.junction(s * vbe, s * (vbe - vce))
        return s * ic, s * ib

    def jacobian(self, vce, vbe):
        """d(Ic, Ib) / d(vce, vbe): [[dIc/dvce, dIc/dvbe], [dIb/dvce, dIb/dvbe]]."""
        s = self.sign
        vce, vbe = np.asarray(vce, float), np.asarray(vbe, float)
        _, _, dic_e, dic_c, dib_e, dib_c = self.junction(s * vbe, s * (vbe - vce))
        return np.array([[-dic_c, dic_e + dic_c], [-dib_c, dib_e + dib_c]])

    @property
    def model_name(self) -> str:
        return "Q_" + "".join(c if c.isalnum() else "_" for c in self.name).upper()

    def model_card(self) -> str:
        """ngspice's native BJT with this model's DC parameters (the parasitics are the
        part's elements, not the card's)."""
        p = [("IS", self.is_a), ("BF", self.bf), ("BR", self.br), ("NF", self.nf)]
        p += [("NR", self.nr), ("ISE", self.ise_a), ("NE", self.ne), ("ISC", self.isc_a)]
        p += [("NC", self.nc)]
        for key, x in (("VAF", self.vaf_v), ("VAR", self.var_v), ("IKF", self.ikf_a)):
            if x is not None:
                p.append((key, x))
        if self.ikr_a is not None:
            p.append(("IKR", self.ikr_a))
        for key, x in (("EG", self.eg_ev), ("XTI", self.xti), ("XTB", self.xtb)):
            if x is not None:
                p.append((key, x))
        body = " ".join(f"{k}={num(v)}" for k, v in p)
        return f".model {self.model_name} {self.polarity.upper()}({body})\n"


def depletion_c_f(c0_f: float, vj_v: float, mj: float, v_reverse_v: float) -> float:
    """A junction's depletion capacitance at a reverse bias (SPICE's CJ (1 + V / VJ)^-MJ)."""
    return c0_f * (1.0 + v_reverse_v / vj_v) ** (-mj)


def bjt_from_data(d: dict[str, Any], name: str) -> Bjt:
    """A component file's data (kind `bjt`) as a model."""
    if d.get("polarity") not in POLARITIES:
        raise ValueError(f"{name}: polarity must be one of {POLARITIES}")
    dc, par = d["dc"], d.get("parasitics", {})

    def opt(key: str) -> float | None:
        x = dc.get(key)
        return None if x is None else float(x)

    return Bjt(
        d["name"],
        d["polarity"],
        float(dc["is_a"]),
        float(dc["bf"]),
        br=float(dc.get("br", 1.0)),
        nf=float(dc.get("nf", 1.0)),
        nr=float(dc.get("nr", 1.0)),
        vaf_v=opt("vaf_v"),
        var_v=opt("var_v"),
        ikf_a=opt("ikf_a"),
        ikr_a=opt("ikr_a"),
        ise_a=float(dc.get("ise_a", 0.0)),
        ne=float(dc.get("ne", 1.5)),
        isc_a=float(dc.get("isc_a", 0.0)),
        nc=float(dc.get("nc", 2.0)),
        rb_ohm=float(par.get("rb_ohm", 0.0)),
        rc_ohm=float(par.get("rc_ohm", 0.0)),
        re_ohm=float(par.get("re_ohm", 0.0)),
        cje_f=float(par.get("cje_f", 0.0)),
        cjc_f=float(par.get("cjc_f", 0.0)),
        eg_ev=opt("eg_ev"),
        xti=opt("xti"),
        xtb=opt("xtb"),
    )


def parse_card(card: str) -> tuple[str, dict[str, float]]:
    """A SPICE `.model NAME NPN(K=V ...)` card -> (polarity, {KEY: value}) (upper-case
    keys; SPICE's unit suffixes f p n u m k meg g t)."""
    head, _, body = card.partition("(")
    words = head.split()
    if len(words) < 3 or words[0].lower() != ".model":
        raise ValueError(f"not a .model card: {card[:40]!r}")
    polarity = words[2].lower()
    if polarity not in POLARITIES:
        raise ValueError(f"{words[1]}: {polarity} is not a BJT")
    out: dict[str, float] = {}
    for tok in body.rstrip(") \n").replace("\n+", " ").split():
        key, _, val = tok.partition("=")
        try:
            out[key.upper()] = _spice_number(val)
        except ValueError:
            continue  # vendor fields (mfg=NXP, ...)
    return polarity, out


_SUFFIX = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9,
           "p": 1e-12, "f": 1e-15}  # fmt: skip


def _spice_number(s: str) -> float:
    t = s.strip().lower()
    for suf in ("meg", "t", "g", "k", "m", "u", "n", "p", "f"):
        if t.endswith(suf):
            try:
                return float(t[: -len(suf)]) * _SUFFIX[suf]
            except ValueError:
                break
    return float(t)

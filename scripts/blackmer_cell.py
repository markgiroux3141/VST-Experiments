"""The Blackmer gain cell as parts (DEVICE_BUILDER_PLAN.md B11): THAT's 2180-series core
after Hebert's AES preprint 4055 (1995), built from our BJTs, and its test circuit.

    uv run python scripts/blackmer_cell.py [--check]

writes config/circuits/blackmer_vca_test.yaml (THAT 2180 datasheet's Figure 2, the typical
application circuit); --check exits 1 when the file would change. The SSL bus compressor's
generator (scripts/make_ssl_bus_comp.py) places cells with `cell_parts`.

**The cell** (data/datasheets/that_vca/: the 2180 datasheet's Figure 5, Hebert's Figure 4
and Appendix A). Four core transistors log and antilog the signal current, each with a
diode-connected transistor of the other polarity in its emitter (Hebert's Q5-Q8), so a path
is two junctions and the gain is exp(Vc / 2 Vt): 6.1 mV/dB at the datasheet's chip
temperature of 35 C. Positive signal currents go through the NPN half, negative ones
through the PNP half:

    Q1 NPN, collector IN,  base Ec-, emitter e1;  Q5 PNP diode e1 -> N
    Q2 NPN, collector OUT, base SYM, emitter e2;  Q6 PNP diode e2 -> N
    Q3 PNP, collector IN,  base Ec+, emitter e3;  Q7 NPN diode P -> e3
    Q4 PNP, collector OUT, base Ec-, emitter e4;  Q8 NPN diode P -> e4

Hebert's KVL (A3, A4) needs the control voltage on a diagonal: the NPN output and the PNP
input (Ec+, SYM 27 ohm from it: Hebert's R1, the symmetry trim's injection point) against
the NPN input and the PNP output (Ec-). Then Ic2 / Ic1 = Ic4 / Ic3 = exp((Ec+ - Ec-) /
2 Vt), and the output current Ic2 - Ic4 is the gain times the input current Ic1 - Ic3.

A voltage VB from N to P biases the core class AB (Hebert's V_BIAS, A11): its value is the
four junctions' drop at the datasheet's idle current, 20 uA (derived here from the core
models). The input amplifier (Hebert's OA1, his Figure 12: a voltage gain stage into a
transconductance output, Q14 / R5) holds IN at a virtual ground by driving N: an `opamp`
part with a high output resistance, so its output is a current (the loop transmission
Gm Rin / (G + 1) of his eq. 20). Its gain-bandwidth puts the loop's crossover at Hebert's
20 MHz with Rin 20 kOhm at unity gain.

Left out (documented provisional choices): Hebert's correction resistors RC1-RC4 (where they
sit isn't drawn in what we have; with the cards' sub-ohm emitter resistances their effect is
a few hundredths of a percent of THD), the bias generator's temperature tracking (VB is
fixed at its derived value), the on-chip PTAT symmetry trim (nominal cells are matched).
The core transistors are BC550C@1 / BC560C@1 (THAT doesn't publish its devices; a matched
small-signal NPN / PNP pair of the same class) at the chip temperature.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varimu.devices.bjt import Bjt  # noqa: E402
from varimu.devices.library import load_device  # noqa: E402

TEST = ROOT / "config" / "circuits" / "blackmer_vca_test.yaml"
NPN, PNP = "BC550C@1", "BC560C@1"
CHIP_C = 35.0  # the datasheet's T_CHIP at T_A 25 C
I_IDLE_A = 20e-6  # the datasheet's gain cell idling current
SRC_2180 = "data/datasheets/that_vca/THAT_2180-Series_Datasheet.pdf"
SRC_HEBERT = "data/datasheets/that_vca/AES4055_An_Improved_Monolithic_VCA.pdf"


def _at(model: Bjt) -> Bjt:
    import dataclasses

    return dataclasses.replace(model, temp_k=CHIP_C + 273.15)


def _vbe_for(q: Bjt, ic_a: float, vce_v: float) -> float:
    """The (NPN-signed) base-emitter voltage giving collector current ic_a at vce_v."""
    s = q.sign

    def f(vbe):
        ic, _ = q.currents(s * vce_v, s * vbe)
        return float(s * ic) - ic_a

    return brentq(f, 0.2, 1.0, xtol=1e-15)


def _diode_v_for(q: Bjt, i_a: float) -> float:
    """A diode-connected transistor's drop (NPN-signed, base = collector) at total i_a."""
    s = q.sign

    def f(v):
        ic, ib = q.currents(s * v, s * v)
        return float(s * (ic + ib)) - i_a

    return brentq(f, 0.2, 1.0, xtol=1e-15)


def bias_v() -> float:
    """VB from N to P for I_IDLE_A through each core transistor at idle (unity gain, the
    inputs and Ec at 0 V): the NPN path's two drops plus the PNP path's."""
    qn, qp = _at(load_device(NPN)), _at(load_device(PNP))
    # NPN input path: Q1's collector at 0 V, its emitter ~ -0.65 V; Q5 carries Q1's emitter
    # current (collector plus base).
    vbe1 = _vbe_for(qn, I_IDLE_A, vbe_guess := 0.65)
    ib1 = float(qn.currents(vbe1, vbe1)[1])  # base current at about this point
    v5 = _diode_v_for(qp, I_IDLE_A + ib1)
    # PNP input path, mirrored: Q3's collector at 0 V, its emitter ~ +0.65 V.
    veb3 = _vbe_for(qp, I_IDLE_A, vbe_guess)
    ib3 = -float(qp.currents(-veb3, -veb3)[1])
    v7 = _diode_v_for(qn, I_IDLE_A + ib3)
    return vbe1 + v5 + veb3 + v7


def cell_parts(p: str, n: dict[str, str], keys: dict[str, str]) -> dict[str, dict]:
    """One cell's parts, names prefixed `p` (Q<p>1 ... ), nodes from `n` (in, out, ecp,
    ecm, gnd: the input amplifier's reference) and parameter keys from `keys` (npn, pnp:
    devices keys; vbias, r_sym, a0, gbw, r_out, r_in: values)."""
    i = p.lower()
    e = {k: f"{i}_{k}" for k in ("e1", "e2", "e3", "e4", "n", "p", "sym")}
    q = {"model_n": keys["npn"], "model_p": keys["pnp"]}
    return {
        f"Q{p}1": {"bjt": [n["in"], n["ecm"], e["e1"]], "model": q["model_n"]},
        f"Q{p}5": {"bjt": [e["n"], e["n"], e["e1"]], "model": q["model_p"]},
        f"Q{p}2": {"bjt": [n["out"], e["sym"], e["e2"]], "model": q["model_n"]},
        f"Q{p}6": {"bjt": [e["n"], e["n"], e["e2"]], "model": q["model_p"]},
        f"Q{p}3": {"bjt": [n["in"], n["ecp"], e["e3"]], "model": q["model_p"]},
        f"Q{p}7": {"bjt": [e["p"], e["p"], e["e3"]], "model": q["model_n"]},
        f"Q{p}4": {"bjt": [n["out"], n["ecm"], e["e4"]], "model": q["model_p"]},
        f"Q{p}8": {"bjt": [e["p"], e["p"], e["e4"]], "model": q["model_n"]},
        # Leaks across the diode-connected transistors: a half's emitter nodes keep a DC
        # path when it cuts off (numerical, like the 670's T104 leak).
        **{
            f"R{p}L{k}": {
                "R": [e[f"e{k}"], e["n"] if k <= 2 else e["p"]],
                "r": keys["leak"],
                "tolerance": "none",
            }
            for k in (1, 2, 3, 4)
        },
        f"V{p}B": {"V": [e["p"], e["n"]], "v": keys["vbias"]},
        f"R{p}SYM": {"R": [n["ecp"], e["sym"]], "r": keys["r_sym"], "tolerance": "none"},
        f"U{p}": {
            "opamp": [n["gnd"], n["in"], e["n"]],
            "a0": keys["a0"],
            "gbw_hz": keys["gbw"],
            "r_out_ohm": keys["r_out"],
            "r_in_ohm": keys["r_in"],
        },
    }


def cell_values(prefix: str = "vca") -> dict[str, tuple[float, str]]:
    """The cell's values (key -> (value, source)), keys `<prefix>_...`."""
    vb = bias_v()
    return {
        f"{prefix}_vbias_v": (
            round(vb, 6),
            f"derived: scripts/blackmer_cell.py, the four core junctions' drop at the 2180's "
            f"idling current 20 uA ({SRC_2180}, I_IDLE) on BC550C@1 / BC560C@1 at the chip's "
            f"{CHIP_C:g} C (Hebert's V_BIAS, {SRC_HEBERT} eq. A11)",
        ),
        f"{prefix}_leak_ohm": (
            1.0e9,
            "numerical: a junction-leakage stand-in across each diode-connected core "
            "transistor, so a class-AB half's emitter nodes keep a DC path when it cuts off "
            "(0.6 nA at a junction's drop against the 20 uA idle)",
        ),
        f"{prefix}_r_sym_ohm": (
            27.0,
            f"{SRC_HEBERT} section 2.2 (the symmetry trim's R1, 'nominally 27 ohms')",
        ),
        f"{prefix}_ota_r_out_ohm": (
            1.0e6,
            "provisional: model knowledge (the input amplifier's current output, Hebert's "
            "Q14 collector: a high impedance, so the amplifier is a transconductance; "
            f"{SRC_HEBERT} Figures 11b-12)",
        ),
        f"{prefix}_ota_a0": (
            1.0e5,
            "provisional: model knowledge (the input amplifier's DC voltage gain ahead of "
            "its transconductance: a two-stage bipolar amplifier's, ~100 dB)",
        ),
        f"{prefix}_ota_gbw_hz": (
            2.0e9,
            f"derived: Hebert's 20 MHz loop crossover with Rin 20 kOhm at unity gain "
            f"({SRC_HEBERT} section 2.3): Gm(f) Rin / 2 = 1 at 20 MHz with Gm(f) = "
            "(gbw / f) / r_out, so gbw = 2 x 20 MHz x r_out / Rin",
        ),
        f"{prefix}_ota_r_in_ohm": (
            1.0e6,
            "provisional: model knowledge (the input amplifier's differential input "
            "resistance; the 2180's equivalent input bias current is 2 nA)",
        ),
    }


def _fmt(x: float) -> str:
    if x == 0 or 1e-3 <= abs(x) < 1e4:
        return repr(float(x))
    return f"{x:.6e}".replace("e+0", "e+").replace("e-0", "e-")


def _flow(d: dict) -> str:
    def v(x):
        if isinstance(x, list):
            return "[" + ", ".join(v(y) for y in x) + "]"
        if isinstance(x, str) and x in ("0",):
            return '"0"'
        return str(x)

    return "{" + ", ".join(f"{k}: {v(x)}" for k, x in d.items()) + "}"


def test_circuit() -> str:
    vals = cell_values()
    lines = [
        "# GENERATED by scripts/blackmer_cell.py: never edit by hand (rerun it).",
        "#",
        "# The Blackmer gain cell (DEVICE_BUILDER_PLAN.md B11) in THAT's typical application",
        f"# circuit ({SRC_2180}, Figure 2): IN -> 10 uF -> 20 kOhm -> the cell's",
        "# virtual-ground input; its output current into an op-amp's virtual ground, 20 kOhm",
        "# || 22 pF back to its output (non-inverting overall, unity at Ec = 0). Ec+ held at",
        "# 0 V, Ec- the control `ec_minus_v` (a V source), SYM through the cell's 27 Ohm.",
        "# The cell itself: scripts/blackmer_cell.py's docstring. The I-V converter is an",
        "# NE5534A for the sheet's OP275 (data/datasheets/opamps/README.md).",
        "",
        'title: "Blackmer gain cell (THAT 2180 application circuit)"',
        "input: in",
        "probes: [out, vin, vout, ca_n, ca_p]",
        "",
        "controls:",
        "  ec_minus_v: {value: 0.0, min: -0.6, max: 0.6, unit: V, source: \"the test's: the "
        'control voltage at Ec- (6.1 mV/dB: -6.1 mV is +1 dB)"}',
        "",
        "values:",
    ]
    for k, (x, src) in vals.items():
        lines.append(f'  {k}: {{value: {_fmt(x)}, source: "{src}"}}')
    lines += [
        '  supply_v: {value: 15.0, source: "' + SRC_2180 + ' (Figure 2: +-15 V)"}',
        '  c_in_f: {value: 10.0e-6, source: "' + SRC_2180 + ' (Figure 2: 10 uF)"}',
        '  r_in_ohm: {value: 20.0e+3, source: "' + SRC_2180 + ' (Figure 2: 20 kOhm)"}',
        '  r_f_ohm: {value: 20.0e+3, source: "' + SRC_2180 + ' (Figure 2: 20 kOhm)"}',
        '  c_f_f: {value: 22.0e-12, source: "' + SRC_2180 + ' (Figure 2: 22 pF)"}',
        '  u_a0: {value: 1.0e+5, source: "web: https://www.ti.com/lit/ds/symlink/ne5534.pdf '
        '(AVD 100 V/mV typ; data/datasheets/opamps/README.md)"}',
        '  u_gbw_hz: {value: 10.0e+6, source: "web: https://www.ti.com/lit/ds/symlink/'
        'ne5534.pdf (B1 10 MHz typ)"}',
        '  u_r_in_ohm: {value: 100.0e+3, source: "web: https://www.ti.com/lit/ds/symlink/'
        'ne5534.pdf (ri 100 kOhm typ)"}',
        "  u_r_out_ohm: {value: 30.0, source: \"provisional: model knowledge (a 5534's "
        'open-loop output resistance, tens of ohms)"}',
        '  load_ohm: {value: 10.0e+3, source: "provisional: model knowledge (a line input)"}',
        "",
        "devices:",
        f'  QN: {{device: {NPN}, temp_c: {{value: {CHIP_C}, source: "{SRC_2180} '
        '(T_CHIP ~ 35 C at T_A 25 C)"}}',
        f'  QP: {{device: {PNP}, temp_c: {{value: {CHIP_C}, source: "{SRC_2180} '
        '(T_CHIP ~ 35 C at T_A 25 C)"}}',
        "",
        "sections:",
        "  - title: input",
        "    parts:",
        "      CIN: {C: [in, a], c: c_in_f}",
        "      RIN: {R: [a, vin], r: r_in_ohm}",
        '      VEC: {V: [ecm, "0"], v: ec_minus_v}',
        "  - title: cell",
        "    parts:",
    ]
    parts = cell_parts(
        "CA",
        {"in": "vin", "out": "vout", "ecp": "0", "ecm": "ecm", "gnd": "0"},
        {
            "npn": "QN",
            "pnp": "QP",
            "vbias": "vca_vbias_v",
            "leak": "vca_leak_ohm",
            "r_sym": "vca_r_sym_ohm",
            "a0": "vca_ota_a0",
            "gbw": "vca_ota_gbw_hz",
            "r_out": "vca_ota_r_out_ohm",
            "r_in": "vca_ota_r_in_ohm",
        },
    )
    for name, part in parts.items():
        lines.append(f"      {name}: {_flow(part)}")
    lines += [
        "  - title: output",
        "    parts:",
        '      U2: {opamp: ["0", vout, out], a0: u_a0, gbw_hz: u_gbw_hz, '
        "r_out_ohm: u_r_out_ohm, r_in_ohm: u_r_in_ohm}",
        "      RF: {R: [out, vout], r: r_f_ohm}",
        "      CF: {C: [out, vout], c: c_f_f}",
        '      RL: {R: [out, "0"], r: load_ohm}',
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the file would change")
    a = ap.parse_args()
    text = test_circuit()
    if a.check:
        same = TEST.exists() and TEST.read_text(encoding="utf-8") == text
        print("up to date" if same else f"{TEST} is stale")
        return 0 if same else 1
    TEST.write_text(text, encoding="utf-8")
    print(TEST)
    print(f"VB = {bias_v():.6f} V")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

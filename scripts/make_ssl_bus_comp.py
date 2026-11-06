"""The SSL 4000 E / G bus compressor, keyed (DEVICE_BUILDER_PLAN.md B11): one bus card
(82E26: the patch-return receiver, the program VCA, the side chain) and the shared time
constants card (82E27), from SSL's drawings (data/schematics/ssl_bus_comp/README.md).

    uv run python scripts/make_ssl_bus_comp.py [--check]

writes config/circuits/ssl_bus_comp.yaml (GENERATED: never edit it by hand); --check exits
1 when it would change.

What is modelled (the README's transcription; references are the drawings'):
- 82E26: the patch return into T2 (an NE5534 balanced receiver, driven unbalanced here: pin
  13 grounded), C9 / R12 into the program VCA A1 (a dbx 202C), T3 its I-V converter, the
  second insert link and T4 the output receiver. The side chain: R11 47K from T2 (pre-A1:
  the feed-forward tap), TR4 (J175) COMP IN / OUT across it, R30 47K into the side-chain VCA
  A2 (a dbx 202C), T5 its I-V converter, C18, the TL081 full-wave rectifier T6 / T7 with
  the RATIO network around T7, D6 onto the detector line D.
- 82E27: ATTACK (R1-R6) into the RELEASE network (C3-C6 with R9-R12; AUTO C1 || R7 in
  series with C2 || R8, as the drawing reads), T1 (LF351) buffering the timed voltage, T2
  (CA324) summing it with MAKE UP into B (the program VCA's control), T3 (LF351) summing it
  with THRESHOLD into C (the side-chain VCA's control).
- A KEY INT / EXT switch at R11 (not on the original; DEVICE_CANDIDATES.md B11 step 6): at
  EXT the side chain's input is the KEY jack, so the detector's loop closes around the key
  (the side-chain VCA is inside it) and the ratio holds when keyed.

The dbx 202C is modelled as THAT's documented drop-in for it, the 202XT (its schematic,
data/datasheets/that_vca/THAT_202XT_schematic.pdf: eight 2180-class cells in parallel, each
input through 10 kOhm, the control port scaled to -20 dB/V by two 4570 op-amp sections:
EC -> 1k65 into an inverter of 100R feedback drives Ec+, EC -> 1k54 / 100R into a follower
drives Ec-). Eight matched cells in parallel are one cell of eight times the area: the core
devices are `area: 8` and the input amplifier's output resistance an eighth
(scripts/blackmer_cell.py). The 202C's own insides (a discrete Blackmer cell, THAT DN127)
weren't found.

Left out: the mix-bus amplifier ahead of the patch return (LM394 pairs; the insert's input
is the patch return), the GR meter, the autofader and master-fader terms (pin 15 of 82E26
and R24 of 82E27 held at 0 V: provisional), a second bus card (the stereo link is the
diode-OR on D; mono for now), the console's regulators (ideal rails).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import blackmer_cell as bc  # noqa: E402

OUT = ROOT / "config" / "circuits" / "ssl_bus_comp.yaml"
S26 = "sch26"  # data/schematics/ssl_bus_comp/ssl_82E26.pdf (T82026.71 rev 8)
S27 = "sch27"  # data/schematics/ssl_bus_comp/ssl_82E27.pdf (T82027.71 rev 8)
XT = "data/datasheets/that_vca/THAT_202XT_schematic.pdf"
XTD = "data/datasheets/that_vca/THAT_202_modular_datasheet.pdf"
OPA = "data/datasheets/opamps/README.md"


def q(s: str) -> str:
    return '"' + s.replace('"', "'") + '"'


def val(key: str, x: float, src: str) -> str:
    return f"  {key}: {{value: {bc._fmt(x)}, source: {q(src)}}}"


def flow(d: dict) -> str:
    return bc._flow(d)


# --- values ------------------------------------------------------------------------------


def values() -> list[str]:
    v: list[tuple[str, float, str]] = []

    def add(k, x, s):
        v.append((k, x, s))

    # Rails (the console's regulated supplies).
    for k, x, s in (
        ("rail_18_v", 18.0, f"{S26}: pins 49 / 51 +18 / -18 V (the console's supply)"),
        ("rail_15_v", 15.0, f"{S27}: T12 7815 / T11 LM337 regulators, pins 30 / 31"),
        ("rail_12_v", 12.0, f"{S27}: T10 78L12 / T9 79L12 regulators, pins 34 / 33"),
    ):
        add(k, x, s + " (ideal rails: provisional)")
    # 82E26: patch return receiver T2.
    add("r61_ohm", 5.0e3, f"{S26}: R61 5K across pins 12-13")
    add("c_couple_f", 5.0e-6, f"derived: {S26}: '2 x 10uF 35V' back to back (C3 / C4 etc.)")
    add("r_3k01_ohm", 30.1e3, f"{S26}: R7* / R10* / R19* / R22* 30K1")
    add("r_10k0_ohm", 10.0e3, f"{S26}: R8* / R9* / R20* / R21* 10K0")
    add("c_33p_f", 33.0e-12, f"{S26}: C7 / C15 33p")
    add("c_100p_f", 100.0e-12, f"{S26}: C8 / C16 100p")
    # Program VCA path.
    add("c9_f", 2.2e-6, f"{S26}: C9 2U2")
    add("r12_ohm", 15.0e3, f"{S26}: R12* 15K0")
    add("r16_ohm", 15.0e3, f"{S26}: R16* 15K0")
    add("c10_f", 22.0e-12, f"{S26}: C10 22p")
    add("r15_ohm", 470.0, f"{S26}: R15 470R")
    add("r13_ohm", 909.0, f"{S26}: R13* 909R (B into A1's control)")
    add("r_pin15_ohm", 4.32e3, f"{S26}: the 4K32* from pin 15 to A1's control node")
    add("r14_ohm", 1.5e6, f"{S26}: R14 1M5 (A1's symmetry pin from RV1)")
    add("rv1_ohm", 50.0e3, f"{S26}: RV1 50K DISTORTION NULL across +-15")
    add("r49_ohm", 47.0, f"{S26}: R49 47R")
    add("r17_ohm", 10.0, f"{S26}: R17 10R")
    add("r18_ohm", 15.0e3, f"{S26}: R18 15K")
    add("r23_ohm", 10.0, f"{S26}: R23 10R")
    add("load_ohm", 10.0e3, "provisional: model knowledge (a line input)")
    # Side chain on 82E26.
    add("r11_ohm", 47.0e3, f"{S26}: R11 47K")
    add("r30_ohm", 47.0e3, f"{S26}: R30 47K")
    add("r28_ohm", 100.0e3, f"{S26}: R28 100K")
    add("r29_ohm", 100.0e3, f"{S26}: R29 100K")
    add("r_comp_ohm", 100.0, f"{S26}: COMP IN / OUT SW 2a's 100R from +18")
    add(
        "r_gate_leak_ohm",
        1.0e9,
        "numerical: TR4's gate held to its source while D1 is "
        "reverse-biased (COMP OUT): the junction's leakage, so the gate has a DC path",
    )
    add("r31_ohm", 909.0, f"{S26}: R31* 909R (C into A2's control)")
    add("r32_ohm", 33.0e3, f"{S26}: R32 33K")
    add("c17_f", 22.0e-12, f"{S26}: C17 22p")
    add("r33_ohm", 470.0, f"{S26}: R33 470R")
    add("c18_f", 6.8e-6, f"{S26}: C18 6u8 35V")
    add("r_20k_ohm", 20.0e3, f"{S26}: R34 / R35 / R37 20K")
    add("r36_ohm", 10.0e3, f"{S26}: R36 10K")
    add("r38_ohm", 1.0e6, f"{S26}: R38 1M")
    add("r39_ohm", 510.0e3, f"{S26}: R39 510K")
    add("r40_ohm", 270.0e3, f"{S26}: R40 270K")
    add("r41_ohm", 68.0e3, f"{S26}: R41 68K")
    add("r42_ohm", 1.2e6, f"{S26}: R42 1M2")
    add("r43_ohm", 1.6e6, f"{S26}: R43 1M6")
    add("r44_ohm", 3.9e6, f"{S26}: R44 3M9")
    add("r45_ohm", 620.0e3, f"{S26}: R45 620K")
    add(
        "key_source_impedance_ohm",
        600.0,
        "provisional: model knowledge (a 600 ohm line feeding the KEY jack, as for the keyed 670)",
    )
    add(
        "key_termination_ohm",
        10.0e3,
        "provisional: model knowledge (the KEY jack's load while the switch is at INT)",
    )
    # 82E27.
    for k, x, r in (
        ("r1", 820.0, "R1 820R (ATTACK 0.1 ms)"),
        ("r2", 2.7e3, "R2 2K7 (0.3 ms)"),
        ("r3", 8.2e3, "R3 8K2 (1 ms)"),
        ("r4", 27.0e3, "R4 27K (3 ms)"),
        ("r5", 82.0e3, "R5 82K (10 ms)"),
        ("r6", 270.0e3, "R6 270K (30 ms)"),
        ("r7", 91.0e3, "R7 91K (AUTO, across C1 as the drawing reads; Gyraf pairs it with 6u8)"),
        ("r8", 750.0e3, "R8 750K (AUTO, across C2)"),
        ("r9", 1.2e6, "R9 1M2 (RELEASE 1.2 s)"),
        ("r10", 560.0e3, "R10 560K (0.6 s)"),
        ("r11b", 270.0e3, "R11 270K (0.3 s)"),
        ("r12b", 180.0e3, "R12 180K (0.1 s)"),
        ("r13b", 3.3e6, "R13 3M3 (T1's + input to ground)"),
        ("r14b", 470.0e3, "R14 470K (T1's feedback)"),
        ("r_100k", 100.0e3, "R19 / R25 / R21 / R27 100K"),
        ("r20", 620.0e3, "R20 620K (MAKE UP into T2)"),
        ("r22", 360.0e3, "R22 360K (THRESHOLD into T3)"),
        ("r16b", 4.7e3, "R16 4K7 (the make-up reference's feed)"),
        ("r_3k9", 3.9e3, "R17 / R18 3K9 (THRESHOLD's ends to +-12 V)"),
        ("r_100r", 100.0, "R51 / R52 100R (out to B and C)"),
        ("makeup_pot", 25.0e3, "MAKE UP 25K LIN"),
    ):
        add(f"{k}_ohm", x, f"{S27}: {r}")
    add("c_0u47_f", 0.47e-6, f"{S27}: C1, C3-C6 0u47 35V")
    add("c2_f", 6.8e-6, f"{S27}: C2 6u8 35V (AUTO)")
    add("c_100n_f", 100.0e-9, f"{S27}: C11 / C12 100nF")
    add(
        "threshold_pot_ohm",
        10.0e3,
        "provisional: model knowledge (THRESHOLD's value isn't "
        "printed on 82E27; a linear 10K between its 3K9 end resistors spans about +-6.7 V, "
        "which through R22 / R27 moves the side-chain VCA by about the panel's +-15 dB)",
    )
    add("zener_v", 12.0, f"{S27}: D3 '12v' (the make-up reference)")
    add(
        "zener_ref_a",
        5.0e-3,
        "provisional: model knowledge (the ZPD / BZX55 series' test current, 5 mA)",
    )
    # dbx 202C as THAT's 202XT: eight cells in parallel are one cell of eight times the area.
    add(
        "dbx202_r_in_ohm",
        1.25e3,
        f"derived: {XT}: RP2A-H 10k into each of the eight cells "
        f"(in parallel: 10k / 8; {XTD}: input impedance 1.25 kOhm)",
    )
    add("dbx202_r1_ohm", 1.65e3, f"{XT}: R1 1k65 (EC into U1B)")
    add("dbx202_r3_ohm", 100.0, f"{XT}: R3 100R0 (U1B's feedback)")
    add("dbx202_r2_ohm", 1.54e3, f"{XT}: R2 1k54 (EC to U1A's divider)")
    add("dbx202_r5_ohm", 100.0, f"{XT}: R5 100R0 (U1A's divider to ground)")
    add("dbx202_r_snub_ohm", 51.0, f"{XT}: R4 / R6 51R (the control buffers' snubbers)")
    add("dbx202_c_snub_f", 1.5e-9, f"{XT}: C3 / C4 1n5 NPO")
    add("dbx202_r_sym_port_ohm", 51.0, f"{XT}: R8 51R ({XTD}: symmetry port impedance 51 Ohm)")
    for k, (x, s) in bc.cell_values("vca").items():
        add(k, x, s)
    add(
        "vca8_ota_r_out_ohm",
        1.0e6 / 8,
        "derived: the eight cells' input amplifiers in "
        "parallel, each vca_ota_r_out_ohm (scripts/blackmer_cell.py)",
    )
    add(
        "vca8_ota_r_in_ohm",
        1.0e6 / 8,
        "derived: the eight cells' input amplifiers in parallel, each vca_ota_r_in_ohm",
    )
    add(
        "vca8_r_sym_ohm",
        27.0 / 8,
        "derived: the eight cells' internal 27 Ohm symmetry "
        "resistors in parallel (scripts/blackmer_cell.py)",
    )
    add("cell_area", 8.0, f"derived: {XT}: eight matched cells in parallel")
    add("chip_temp_c", bc.CHIP_C, f"{bc.SRC_2180} (T_CHIP ~ 35 C at T_A 25 C)")
    # Op-amps.
    ne = "web: https://www.ti.com/lit/ds/symlink/ne5534.pdf"
    for k, x, s in (
        ("ne_a0", 1.0e5, f"{ne} (AVD 100 V/mV typ; {OPA})"),
        ("ne_gbw_hz", 10.0e6, f"{ne} (B1 10 MHz typ, CC 22 pF: the drawing's CT 22p)"),
        ("ne_r_in_ohm", 100.0e3, f"{ne} (ri 100 kOhm typ)"),
        (
            "ne_r_out_ohm",
            30.0,
            "provisional: model knowledge (a 5534's open-loop output resistance, tens of ohms)",
        ),
        (
            "ne_swing_v",
            15.4,
            "provisional: model knowledge (a 5534 on +-18 V rails swings "
            "to about 2 V from them; less the clamp diode's ~0.6 V)",
        ),
        (
            "tl_a0",
            2.0e5,
            f"web: https://www.ti.com/lit/ds/symlink/tl081.pdf (AVD 200 V/mV "
            f"typ, as the TL07x's; {OPA})",
        ),
        ("tl_gbw_hz", 3.0e6, "web: https://www.ti.com/lit/ds/symlink/tl081.pdf (GBW 3 MHz typ)"),
        ("tl_r_in_ohm", 1.0e12, "web: https://www.ti.com/lit/ds/symlink/tl081.pdf (ri 10^12 Ohm)"),
        (
            "tl_r_out_ohm",
            75.0,
            "provisional: model knowledge (a TL08x's open-loop output resistance)",
        ),
        (
            "tl_swing_v",
            12.9,
            "derived: the TL08x's +-13.5 V peak swing at +-15 V "
            f"(RL 10 kOhm; {OPA}) less the clamp diode's ~0.6 V",
        ),
        (
            "lf_a0",
            1.0e5,
            "provisional: model knowledge (LF351: AVOL 100 V/mV typ, "
            "web: https://www.ti.com/lit/ds/symlink/lf351.pdf)",
        ),
        ("lf_gbw_hz", 4.0e6, "provisional: model knowledge (LF351: GBW 4 MHz typ)"),
        ("lf_r_in_ohm", 1.0e12, "provisional: model knowledge (LF351: JFET input, 10^12 Ohm)"),
        (
            "lf_r_out_ohm",
            75.0,
            "provisional: model knowledge (a BiFET op-amp's open-loop output resistance)",
        ),
        (
            "lm_a0",
            1.0e5,
            "provisional: model knowledge (CA324 = LM324: AVOL 100 V/mV typ, "
            "web: https://www.ti.com/lit/ds/symlink/lm324.pdf)",
        ),
        ("lm_gbw_hz", 1.0e6, "provisional: model knowledge (LM324: GBW 1 MHz typ)"),
        (
            "lm_r_in_ohm",
            2.0e6,
            "provisional: model knowledge (a bipolar-input LM324's differential input resistance)",
        ),
        (
            "lm_r_out_ohm",
            50.0,
            "provisional: model knowledge (LM324's open-loop output resistance)",
        ),
        (
            "u4570_a0",
            3.0e5,
            f"web: https://www.renesas.com/en/document/dst/upc4570-datasheet "
            f"(AV 300000 typ; {OPA}): the 202XT's '4570'",
        ),
        (
            "u4570_gbw_hz",
            15.0e6,
            "web: https://www.renesas.com/en/document/dst/upc4570-datasheet (GBW 15 MHz typ)",
        ),
        (
            "u4570_r_in_ohm",
            1.0e6,
            "provisional: model knowledge (a bipolar-input op-amp's differential input resistance)",
        ),
        (
            "u4570_r_out_ohm",
            50.0,
            "provisional: model knowledge (the 4570's open-loop output resistance)",
        ),
    ):
        add(k, x, s)
    return [val(k, x, s) for k, x, s in v]


# --- parts ------------------------------------------------------------------------------


def opamp(plus, minus, out, fam, clamp=False):
    d = {"opamp": [plus, minus, out], "a0": f"{fam}_a0", "gbw_hz": f"{fam}_gbw_hz",
         "r_out_ohm": f"{fam}_r_out_ohm", "r_in_ohm": f"{fam}_r_in_ohm"}  # fmt: skip
    if clamp:
        d |= {"clamp": "DCLAMP", "swing_v": f"{fam}_swing_v"}
    return d


def dbx202(p: str, inp: str, out: str, ec: str, sym: str | None) -> dict[str, dict]:
    """One dbx 202C as THAT's 202XT (the module docstring): pins IN, OUT, EC, SYM."""
    i = p.lower()
    ecp, ecm, cin = f"{i}_ecp", f"{i}_ecm", f"{i}_cin"
    parts = {
        f"R{p}IN": {"R": [inp, cin], "r": "dbx202_r_in_ohm"},
        # U1B: EC -> 1k65 into an inverter (100R feedback): Ec+.
        f"R{p}1": {"R": [ec, f"{i}_ubm"], "r": "dbx202_r1_ohm"},
        f"R{p}3": {"R": [ecp, f"{i}_ubm"], "r": "dbx202_r3_ohm"},
        f"U{p}B": opamp("0", f"{i}_ubm", ecp, "u4570"),
        f"R{p}4": {"R": [ecp, f"{i}_sb"], "r": "dbx202_r_snub_ohm", "tolerance": "none"},
        f"C{p}3": {"C": [f"{i}_sb", "0"], "c": "dbx202_c_snub_f", "tolerance": "none"},
        # U1A: EC -> 1k54 / 100R into a follower: Ec-.
        f"R{p}2": {"R": [ec, f"{i}_uap"], "r": "dbx202_r2_ohm"},
        f"R{p}5": {"R": [f"{i}_uap", "0"], "r": "dbx202_r5_ohm"},
        f"U{p}A": opamp(f"{i}_uap", ecm, ecm, "u4570"),
        f"R{p}6": {"R": [ecm, f"{i}_sa"], "r": "dbx202_r_snub_ohm", "tolerance": "none"},
        f"C{p}4": {"C": [f"{i}_sa", "0"], "c": "dbx202_c_snub_f", "tolerance": "none"},
    }
    parts |= bc.cell_parts(
        p,
        {"in": cin, "out": out, "ecp": ecp, "ecm": ecm, "gnd": "0"},
        {
            "npn": "QN8",
            "pnp": "QP8",
            "vbias": "vca_vbias_v",
            "leak": "vca_leak_ohm",
            "r_sym": "vca8_r_sym_ohm",
            "a0": "vca_ota_a0",
            "gbw": "vca_ota_gbw_hz",
            "r_out": "vca8_ota_r_out_ohm",
            "r_in": "vca8_ota_r_in_ohm",
        },  # fmt: skip
    )
    if sym is not None:
        parts[f"R{p}8"] = {"R": [sym, f"{i}_sym"], "r": "dbx202_r_sym_port_ohm"}
    return parts


def sections() -> list[tuple[str, dict[str, dict]]]:
    out: list[tuple[str, dict[str, dict]]] = []
    out.append(("rails", {
        "V18N": {"V": ["0", "m18"], "v": "rail_18_v"},
        "V15P": {"V": ["p15", "0"], "v": "rail_15_v"},
        "V15N": {"V": ["0", "m15"], "v": "rail_15_v"},
        "V12P": {"V": ["p12", "0"], "v": "rail_12_v"},
        "V12N": {"V": ["0", "m12"], "v": "rail_12_v"},
    }))  # fmt: skip
    out.append(("patch return (82E26 T2)", {
        "R61": {"R": ["in", "0"], "r": "r61_ohm"},
        "C3": {"C": ["in", "t2a"], "c": "c_couple_f"},
        "R7": {"R": ["t2a", "t2m"], "r": "r_3k01_ohm"},
        "C5": {"C": ["0", "t2b"], "c": "c_couple_f"},
        "R8": {"R": ["t2b", "t2p"], "r": "r_10k0_ohm"},
        "R9": {"R": ["t2p", "0"], "r": "r_10k0_ohm"},
        "C8": {"C": ["t2p", "0"], "c": "c_100p_f"},
        "R10": {"R": ["t2o", "t2m"], "r": "r_3k01_ohm"},
        "C7": {"C": ["t2o", "t2m"], "c": "c_33p_f"},
        "U2": opamp("t2p", "t2m", "t2o", "ne", clamp=True),
    }))  # fmt: skip
    a1 = {
        "C9": {"C": ["t2o", "c9b"], "c": "c9_f"},
        "R12": {"R": ["c9b", "a1in"], "r": "r12_ohm"},
        "R13": {"R": ["vb", "a1ec"], "r": "r13_ohm"},
        "R4K32": {"R": ["a1ec", "0"], "r": "r_pin15_ohm"},
        "RV1": {"pot": ["p15", "rv1w", "m15"], "r": "rv1_ohm", "at": "sym_trim"},  # fmt: skip
        "R14": {"R": ["rv1w", "a1sym"], "r": "r14_ohm"},
    }
    a1 |= dbx202("A1", "a1in", "t3m", "a1ec", "a1sym")
    a1 |= {
        "R15": {"R": ["t3p", "0"], "r": "r15_ohm"},
        "R16": {"R": ["t3o", "t3m"], "r": "r16_ohm"},
        "C10": {"C": ["t3o", "t3m"], "c": "c10_f"},
        "U3": opamp("t3p", "t3m", "t3o", "ne", clamp=True),
    }
    out.append(("program VCA (82E26 A1, T3)", a1))
    out.append(("output (82E26 T4)", {
        "R49": {"R": ["t3o", "p23"], "r": "r49_ohm"},
        "R17": {"R": ["p24", "0"], "r": "r17_ohm"},
        "R18": {"R": ["p23", "p24"], "r": "r18_ohm"},
        "C11": {"C": ["p23", "t4a"], "c": "c_couple_f"},
        "R19": {"R": ["t4a", "t4m"], "r": "r_3k01_ohm"},
        "C13": {"C": ["p24", "t4b"], "c": "c_couple_f"},
        "R20": {"R": ["t4b", "t4p"], "r": "r_10k0_ohm"},
        "R21": {"R": ["t4p", "0"], "r": "r_10k0_ohm"},
        "C16": {"C": ["t4p", "0"], "c": "c_100p_f"},
        "R22": {"R": ["t4o", "t4m"], "r": "r_3k01_ohm"},
        "C15": {"C": ["t4o", "t4m"], "c": "c_33p_f"},
        "U4": opamp("t4p", "t4m", "t4o", "ne", clamp=True),
        "R23": {"R": ["t4o", "out"], "r": "r23_ohm"},
        "RL": {"R": ["out", "0"], "r": "load_ohm"},
    }))  # fmt: skip
    sc = {
        "RKEY": {"R": ["key_src", "key"], "r": "key_source_impedance_ohm", "tolerance": "none"},
        "KEY": {"switch": "key_mode", "parts": {
            "R11": {"R": ["t2o", "sc"], "r": "r11_ohm", "in": [0]},
            "RKT": {"R": ["key", "0"], "r": "key_termination_ohm", "tolerance": "none",
                    "in": [0]},
            "R11K": {"R": ["key", "sc"], "r": "r11_ohm", "in": [1]},
        }},
        # COMP IN / OUT (SW 2a, not on the PCB): +18 through 100R onto pin 17 at IN.
        "COMP": {"switch": "comp_in", "parts": {
            # +18 V reaches nothing else modelled here, so its source is switched with it.
            "V18P": {"V": ["p18", "0"], "v": "rail_18_v", "in": [1]},
            "RCOMP": {"R": ["p18", "a17"], "r": "r_comp_ohm", "tolerance": "none", "in": [1]},
        }},
        "R28": {"R": ["a17", "m18"], "r": "r28_ohm"},
        "R29": {"R": ["a17", "d1a"], "r": "r29_ohm"},
        "D1": {"device": ["d1a", "jg"], "model": "DSIG"},
        "RGL": {"R": ["jg", "0"], "r": "r_gate_leak_ohm", "tolerance": "none"},
        "JTR4": {"jfet": ["sc", "jg", "0"], "model": "J175"},
        "R30": {"R": ["sc", "a2in"], "r": "r30_ohm"},
        "R31": {"R": ["vc", "a2ec"], "r": "r31_ohm"},
    }  # fmt: skip
    sc |= dbx202("A2", "a2in", "t5m", "a2ec", None)
    sc |= {
        "R33": {"R": ["t5p", "0"], "r": "r33_ohm"},
        "R32": {"R": ["t5o", "t5m"], "r": "r32_ohm"},
        "C17": {"C": ["t5o", "t5m"], "c": "c17_f"},
        "U5": opamp("t5p", "t5m", "t5o", "tl", clamp=True),
        "C18": {"C": ["t5o", "rect"], "c": "c18_f"},
    }
    out.append(("side chain VCA (82E26 A2, T5)", sc))
    out.append(("rectifier and ratio (82E26 T6, T7)", {
        # T6: inverting half-wave (negative inputs out, positive), T7: the full-wave sum.
        "R34": {"R": ["rect", "t6m"], "r": "r_20k_ohm"},
        "U6": opamp("0", "t6m", "t6o", "tl", clamp=True),
        "D2": {"device": ["t6o", "hw"], "model": "DSIG"},
        "R35": {"R": ["hw", "t6m"], "r": "r_20k_ohm"},
        "D3": {"device": ["t6m", "t6o"], "model": "DSIG"},
        "R36": {"R": ["hw", "t7m"], "r": "r36_ohm"},
        "R37": {"R": ["rect", "t7m"], "r": "r_20k_ohm"},
        "U7": opamp("0", "t7m", "t7o", "tl", clamp=True),
        "R38": {"R": ["t7m", "x"], "r": "r38_ohm"},
        "D4": {"device": ["x", "t7o"], "model": "DSIG"},
        "D5": {"device": ["t7o", "t7m"], "model": "DSIG"},
        "D6": {"device": ["d", "t7o"], "model": "DSIG"},
        "R39": {"R": ["x", "x38"], "r": "r39_ohm"},
        "R43": {"R": ["x38", "m12"], "r": "r43_ohm"},
        "R40": {"R": ["x", "x39"], "r": "r40_ohm"},
        "R44": {"R": ["x39", "m12"], "r": "r44_ohm"},
        "R41": {"R": ["x", "x41"], "r": "r41_ohm"},
        "R45": {"R": ["x41", "p12"], "r": "r45_ohm"},
        "DR": {"device": ["x39", "x41"], "model": "DSIG"},
        # RATIO (not on the PCB): common = T7's summing node; 10:1 contact 37 (R42's
        # offset only), 4:1 contact 38 (R39's tap), 2:1 contact 39 (R40's tap): the more
        # feedback around T7, the less loop gain, the lower the ratio (derived; the drawing
        # doesn't name them; tests/test_ssl_bus_comp.py checks the order).
        "RATIO": {"switch": "ratio", "parts": {
            "R42": {"R": ["t7m", "m12"], "r": "r42_ohm", "in": [10]},
            "RS38": {"R": ["t7m", "x38"], "r": "r_contact_ohm", "tolerance": "none", "in": [4]},
            "RS39": {"R": ["t7m", "x39"], "r": "r_contact_ohm", "tolerance": "none", "in": [2]},
        }},
    }))  # fmt: skip
    att = {f"RA{i}": {"R": ["d", "tn"], "r": f"r{i}_ohm", "in": [i - 1]} for i in range(1, 7)}
    rel = {
        "RREL12": {"R": ["tn", "0"], "r": "r12b_ohm", "in": [0]},
        "CREL6": {"C": ["tn", "0"], "c": "c_0u47_f", "in": [0]},
        "RREL11": {"R": ["tn", "0"], "r": "r11b_ohm", "in": [1]},
        "CREL5": {"C": ["tn", "0"], "c": "c_0u47_f", "in": [1]},
        "RREL10": {"R": ["tn", "0"], "r": "r10_ohm", "in": [2]},
        "CREL4": {"C": ["tn", "0"], "c": "c_0u47_f", "in": [2]},
        "RREL9": {"R": ["tn", "0"], "r": "r9_ohm", "in": [3]},
        "CREL3": {"C": ["tn", "0"], "c": "c_0u47_f", "in": [3]},
        "RREL7": {"R": ["tn", "ta"], "r": "r7_ohm", "in": [4]},
        "CREL1": {"C": ["tn", "ta"], "c": "c_0u47_f", "in": [4]},
        "RREL8": {"R": ["ta", "0"], "r": "r8_ohm", "in": [4]},
        "CREL2": {"C": ["ta", "0"], "c": "c2_f", "in": [4]},
    }
    out.append(("time constants (82E27)", {
        "ATTACK": {"switch": "attack", "parts": att},
        "RELEASE": {"switch": "release", "parts": rel},
        "RD": {"R": ["d", "tn"], "r": "r_d_leak_ohm", "tolerance": "none"},
        "R13B": {"R": ["tn", "0"], "r": "r13b_ohm"},
        "UT1": opamp("tn", "t1m", "t1o", "lf"),
        "R14B": {"R": ["t1o", "t1m"], "r": "r14b_ohm"},
    }))  # fmt: skip
    out.append(("control voltages (82E27)", {
        # Make-up's reference: from the COMP line through D2, R16, a 12 V zener.
        "D2B": {"device": ["a17", "mu1"], "model": "DSIG"},
        "R16B": {"R": ["mu1", "mu2"], "r": "r16b_ohm"},
        "VZ3": {"vr_tube": ["mu2", "mu3", "0"], "model": "DZ12", "operating_v": "zener_v",
                "ref_current_a": "zener_ref_a"},
        "RMU": {"pot": ["0", "muw", "mu2"], "r": "makeup_pot_ohm", "at": "makeup"},
        "R20B": {"R": ["muw", "t2bm"], "r": "r20_ohm"},
        "R19B": {"R": ["t1o", "t2bm"], "r": "r_100k_ohm"},
        "R25B": {"R": ["t2bo", "t2bm"], "r": "r_100k_ohm"},
        "UT2": opamp("0", "t2bm", "t2bo", "lm"),
        "R51B": {"R": ["t2bo", "vb"], "r": "r_100r_ohm"},
        "C12B": {"C": ["vb", "0"], "c": "c_100n_f"},
        # THRESHOLD between 3K9s to +-12 V; T3 sums it with the timed voltage into C.
        "R17B": {"R": ["p12", "th40"], "r": "r_3k9_ohm"},
        "RTH": {"pot": ["th39", "thw", "th40"], "r": "threshold_pot_ohm", "at": "threshold"},
        "R18B": {"R": ["th39", "m12"], "r": "r_3k9_ohm"},
        "R22B": {"R": ["thw", "t3bm"], "r": "r22_ohm"},
        "R21B": {"R": ["t1o", "t3bm"], "r": "r_100k_ohm"},
        "R27B": {"R": ["t3bo", "t3bm"], "r": "r_100k_ohm"},
        "UT3": opamp("0", "t3bm", "t3bo", "lf"),
        "R52B": {"R": ["t3bo", "vc"], "r": "r_100r_ohm"},
        "C11B": {"C": ["vc", "0"], "c": "c_100n_f"},
    }))  # fmt: skip
    return out


def text() -> str:
    lines = [
        "# GENERATED by scripts/make_ssl_bus_comp.py: never edit by hand (rerun it).",
        "#",
        "# The SSL 4000 E / G mix-bus compressor, one bus (DEVICE_BUILDER_PLAN.md B11): SSL's",
        "# cards 82E26 (patch return, program VCA, side chain) and 82E27 (time constants, the",
        "# two control voltages), sch26 / sch27 = data/schematics/ssl_bus_comp/ssl_82E2{6,7}.pdf",
        "# (README.md there transcribes them). The dbx 202C VCAs as THAT's 202XT, the Blackmer",
        "# cell from our BJTs (scripts/blackmer_cell.py). A KEY INT / EXT switch at the side",
        "# chain's input (not on the original): at EXT the detector's loop closes around the key.",
        "# What's left out, and why: the generator's docstring.",
        "",
        'title: "SSL bus compressor (82E26 / 82E27), one bus, with a KEY input"',
        "input: in",
        "cv_inputs:",
        "  key: key_src",
        "probes: [out, t2o, t3o, vb, vc, d, tn, t1o, t5o, x, a17]",
        "",
        "controls:",
        "  threshold: {value: 0.5, min: 0.0, max: 1.0, unit: rotation, source: "
        + q(f"{S27}: THRESHOLD, ends '-15dB' (pin 39, to -12 V) and '+15dB' (pin 40, to +12 V)")
        + ", notes: \"0 = pin 39's end ('-15dB'), 1 = pin 40's ('+15dB')\"}",
        "  ratio: {value: 4, choices: [2, 4, 10], unit: ratio, source: "
        + q(f"{S26}: RATIO SW (contacts 37 / 38 / 39; which is which derived, see RATIO)")
        + "}",
        "  attack: {value: 4, choices: [0, 1, 2, 3, 4, 5], unit: position, source: "
        + q(f"{S27}: ATTACK mS .1 / .3 / 1 / 3 / 10 / 30 (R1-R6)")
        + ', notes: "0 .1 ms, 1 .3, 2 1, 3 3, 4 10, 5 30 ms"}',
        "  release: {value: 1, choices: [0, 1, 2, 3, 4], unit: position, source: "
        + q(f"{S27}: RELEASE .1 / .3 / .6 / 1.2 / AUTO")
        + ', notes: "0 .1 s, 1 .3, 2 .6, 3 1.2, 4 AUTO"}',
        "  makeup: {value: 0.0, min: 0.0, max: 1.0, unit: rotation, source: "
        + q(f"{S27}: MAKE UP 25K LIN")
        + "}",
        "  comp_in: {value: 1, choices: [0, 1], unit: position, source: "
        + q(f"{S26}: COMP IN / OUT SW 2a")
        + ', notes: "1 IN, 0 OUT (TR4 shorts the side chain)"}',
        "  sym_trim: {value: 0.5, min: 0.0, max: 1.0, unit: rotation, source: "
        + q(f"{S26}: RV1 DISTORTION NULL (a trim inside)")
        + "}",
        "  key_mode: {value: 0, choices: [0, 1], unit: position, source: "
        + q(
            "provisional: model knowledge (a KEY INT / EXT switch at R11, "
            "docs/DEVICE_CANDIDATES.md B11 step 6; not on the original)"
        )
        + ', notes: "0 INT = the program feeds the side chain, 1 EXT = the KEY jack"}',
        "",
        "values:",
        *values(),
        val("r_contact_ohm", 1.0e-3, "numerical: the RATIO switch's closed contact"),
        val(
            "r_d_leak_ohm",
            1.0e9,
            "numerical: the detector line's leakage to the timing "
            "node, so D keeps a DC path while D6 is off",
        ),
        "",
        "devices:",
        f"  QN8: {{device: {bc.NPN}, area: cell_area, temp_c: chip_temp_c}}",
        f"  QP8: {{device: {bc.PNP}, area: cell_area, temp_c: chip_temp_c}}",
        "  DSIG: {device: 1N4148@1, source: "
        + q(f"provisional: model knowledge ({S26} / {S27} don't print the signal diodes' type)")
        + "}",
        '  DCLAMP: {device: SI_RECTIFIER@1, source: "the op-amp macro\'s output clamp"}',
        "  DZ12: {device: ZPD12@1}",
        "  J175: {device: J175@1, source: " + q(f"{S26}: TR4 J175") + "}",
        "",
        "sections:",
    ]
    for title, parts in sections():
        lines += [f"  - title: {q(title)}", "    parts:"]
        for name, part in parts.items():
            if "switch" in part:
                lines += [f"      {name}:", f"        switch: {part['switch']}",
                          "        parts:"]  # fmt: skip
                for sub, sp in part["parts"].items():
                    lines.append(f"          {sub}: {flow(sp)}")
            else:
                lines.append(f"      {name}: {flow(part)}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the file would change")
    a = ap.parse_args()
    t = text()
    if a.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == t
        print("up to date" if same else f"{OUT} is stale")
        return 0 if same else 1
    OUT.write_text(t, encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

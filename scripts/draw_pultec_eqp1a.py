"""Draw the Pultec EQP-1A as a schematic (device builder B4a): the hand-written circuit
(config/circuits/pultec_eqp1a.yaml) laid out after the drawings in
data/schematics/pultec_eqp1a/ (redraw_amplifier.jpg, redraw_passive_network.jpg,
dwg_e72658_amplifier.png), saved as config/circuits/pultec_eqp1a_drawn.

    uv run python scripts/draw_pultec_eqp1a.py [--check] [--dry-run]

Signal flows left to right: the input transformer, the passive network (HF boost with its
LC ladder on SW1a / SW1b, HF atten, LF atten, LF boost), the 12AX7 push-pull stage and the
12AU7 output stage, with the supply below. Every part, value and field is the circuit
file's (varimu.editor.sketch keeps them); only the layout is drawn here. The rails b3 and
b4 are labels; the feedback from T3's windings to the 12AX7 cathodes is drawn along the
bottom, as on the original. --check compares the saved circuit's IR with the hand-written
one at every switch combination and with drawn tolerances (tests/test_editor.py does too).
"""

from __future__ import annotations

import argparse
import sys

from varimu.circuit.spec import circuit_path, load_circuit
from varimu.editor.compile import save_circuit
from varimu.editor.sketch import Sketch

NAME = "pultec_eqp1a_drawn"
H, FLIP = {"rot": 90}, {"rot": 180, "mirror": True}  # pin 1 left; pin 1 at the bottom
TOP = 20.32  # the signal line: eq_in and the network's main node eq_m
YC = 62.23  # the push-pull stages' centre line (the transformers' centre taps)


def input_section(sk: Sketch) -> None:
    sk.offset = (0, 0)
    sk.frame("input", 0, 0, 55.88, 40.64)
    sk.place("Rsrc", 12.7, TOP, **H)
    sk.wire((3.81, TOP), "Rsrc.1")
    sk.label("in", (3.81, TOP), "left")
    sk.place("W1", 25.4, TOP + 3.81)
    sk.place("T1", 27.94, TOP + 3.81)
    sk.place("W2", 30.48, TOP + 3.81, mirror=True)
    sk.wire("Rsrc.2", "W1.1")
    sk.label("in_s", (19.05, TOP))
    sk.place("RIN_TERM", 43.18, TOP + 3.81)
    for p in ("W1.2", "W2.2", "RIN_TERM.2"):
        sk.wire(p, (None, TOP + 10.16))
        sk.ground((None, None))
    sk.label("eq_in", (48.26, TOP))


def passive_network(sk: Sketch) -> None:
    ox = 63.5
    sk.offset = (ox, TOP - 10.16)
    sk.frame("passive network", ox, 0, 228.6, 127)
    y0 = 10.16  # eq_m, locally
    # eq_in from T1's secondary along the top into the HF boost pot.
    sk.place("RHB", 34.29, y0, rot=270)  # pin 3 (eq_in) left, 1 (eq_m) right, wiper down
    sk.offset = (0, 0)
    sk.wire("W2.1", "RHB.3")
    sk.offset = (ox, TOP - 10.16)
    # HF boost: the capacitors on the wiper's bus, SW1a (SHB) picks one.
    caps = ["CHB18", "CHB15", "CHB82", "CHB56", "CHB33"]
    for i, c in enumerate(caps):
        sk.place(c, 25.4 + 12.7 * i, 24.13)
    sk.wire("RHB.2", (None, 20.32))
    sk.wire("CHB18.1", "CHB33.1")
    sk.label("hbw", (30.48, 20.32))
    sk.place("SHB", 50.8, 45.72, rot=90)  # contacts along the top, 1 at the left
    sk.wire("CHB18.2", (None, 34.29), (43.18, None), "SHB.1")
    sk.wire("SHB.1", "SHB.2")
    sk.wire("CHB15.2", (None, 31.75), (48.26, None), "SHB.3")
    sk.wire("CHB82.2", "SHB.4")
    sk.wire("SHB.4", "SHB.5")
    sk.wire("CHB56.2", (None, 31.75), (55.88, None), "SHB.6")
    sk.wire("CHB33.2", (None, 34.29), (58.42, None), "SHB.7")
    # SW1b (SHB_B): the coil tap, ganged; its common is SW1a's.
    sk.place("SHB_B", 50.8, 63.5, rot=90, mirror=True)  # common up, contacts below
    sk.wire("SHB.C", "SHB_B.C")
    sk.label("hbc", "SHB.C", "left")
    coils = [("LHB150", "RLHB150", "hbl150"), ("LHB82", "RLHB82", "hbl82"),
             ("LHB68", "RLHB68", "hbl68"), ("LHB47", "RLHB47", "hbl47"),
             ("LHB33", "RLHB33", "hbl33"), ("LHB27", "RLHB27", "hbl27")]  # fmt: skip
    for i, (lc, rc, node) in enumerate(coils):
        x = 12.7 + 12.7 * i
        sk.place(lc, x, 85.09)
        sk.place(rc, x, 96.52)
        sk.wire(f"{lc}.2", f"{rc}.1")
        sk.label(node, (x, 90.17))
    sk.wire("SHB_B.1", (None, 73.66), (12.7, None), "LHB150.1")
    sk.wire("SHB_B.2", (None, 76.2), (25.4, None), "LHB82.1")
    sk.wire("SHB_B.3", (None, 78.74), (38.1, None), "LHB68.1")
    sk.wire("SHB_B.4", "LHB47.1")
    sk.wire("SHB_B.5", (None, 78.74), (63.5, None), "LHB33.1")
    sk.wire("SHB_B.5", "SHB_B.6")
    sk.wire("SHB_B.7", (None, 76.2), (76.2, None), "LHB27.1")
    # The coils' bus (hbr) through BANDWIDTH back up to eq_m.
    sk.place("RBW", 88.9, 104.14, **H)
    sk.wire("RLHB150.2", (None, 104.14), "RBW.1")
    for _, rc, _ in coils[1:]:
        sk.wire(f"{rc}.2", (None, 104.14))
    sk.label("hbr", (80.01, 104.14))
    sk.wire("RBW.2", (None, y0))

    # HF atten: the 1k pot from eq_m to lb, its wiper through 75 ohm to the capacitors.
    sk.place("RHA", 106.68, 17.78, **FLIP)  # pin 3 (eq_m) up, 1 (lb) down, wiper right
    sk.wire("RHA.3", (None, y0))
    sk.place("RHA75", 114.3, 21.59)
    sk.wire("RHA.2", "RHA75.1")
    sk.label("haw", (110.49, 17.78))
    sk.place("CHA68", 121.92, 33.02)
    sk.place("SHA", 134.62, 36.83, rot=90, mirror=True)
    sk.wire("RHA75.2", (None, 29.21), "SHA.C")
    sk.label("hac", (116.84, 29.21))
    sk.place("CHA5K", 127, 50.8)
    sk.place("CHA10K", 142.24, 50.8)
    sk.wire("SHA.1", (None, 46.99), "CHA5K.1")
    sk.wire("SHA.2", (None, 46.99), "CHA10K.1")

    # LF atten: the 100k rheostat and its capacitors from eq_m to la (SW3b: SLA).
    sk.place("RLA", 154.94, 40.64)
    sk.place("CLA12", 165.1, 40.64)
    sk.place("SLA", 186.69, 22.86, rot=90, mirror=True)
    sk.wire("RHB.1", (186.69, y0), "SLA.C")
    sk.label("eq_m", (43.18, y0))
    for p in ("RLA.1", "CLA12.1"):
        sk.wire(p, (None, y0))
    for i, c in enumerate(["CLA20", "CLA30", "CLA60"]):
        sk.place(c, 175.26 + 10.16 * i, 40.64)
    sk.wire("SLA.1", (None, 33.02), (175.26, None), "CLA20.1")
    sk.wire("SLA.2", "CLA30.1")
    sk.wire("SLA.3", (None, 33.02), (195.58, None), "CLA60.1")
    sk.place("RLA_SER", 205.74, 48.26, **H)
    sk.wire("RLA.2", (None, 48.26), "RLA_SER.1")
    for c in ("CLA12", "CLA20", "CLA30", "CLA60"):
        sk.wire(f"{c}.2", (None, 48.26))
    sk.label("la", (198.12, 48.26))
    # The network's output, and the 10k shunt to lb.
    sk.place("RSHUNT", 215.9, 52.07)
    sk.label("eq_out", (220.98, 48.26))

    # lb: the HF atten pot's end, its capacitors, the shunt and the LF boost.
    sk.wire("RHA.1", (None, 60.96), (215.9, None), "RSHUNT.2")
    for p in ("CHA68.2", "CHA5K.2", "CHA10K.2"):
        sk.wire(p, (None, 60.96))
    sk.label("lb", (111.76, 60.96))
    sk.place("RLB", 154.94, 68.58)
    sk.place("CLB330", 165.1, 68.58)
    sk.place("SLB", 186.69, 73.66, rot=90, mirror=True)
    for p in ("RLB.1", "CLB330.1", "SLB.C"):
        sk.wire(p, (None, 60.96))
    for p in ("RLB.2", "CLB330.2"):
        sk.wire(p, (None, 74.93))
        sk.ground((None, None))
    for i, c in enumerate(["CLB20", "CLB30", "CLB60"]):
        sk.place(c, 175.26 + 10.16 * i, 91.44)
        sk.wire(f"{c}.2", (None, 97.79))
        sk.ground((None, None))
    sk.wire("SLB.1", (None, 83.82), (175.26, None), "CLB20.1")
    sk.wire("SLB.2", "CLB30.1")
    sk.wire("SLB.3", (None, 83.82), (195.58, None), "CLB60.1")


def interstage(sk: Sketch) -> None:
    ox = 299.72
    sk.offset = (ox, 0)
    sk.frame("interstage and 12AX7", ox, 0, 96.52, 127)
    # HS-29: the primary from the network, the secondary's halves to the grids, the
    # centre tap grounded.
    sk.place("W3", 12.7, YC, **FLIP)  # eq_out at the top, the grounded end below
    sk.place("T2", 15.24, YC)
    sk.place("W4", 17.78, YC - 3.81, mirror=True)
    sk.place("W5", 17.78, YC + 3.81, mirror=True)
    sk.offset = (0, 0)
    sk.wire("RLA_SER.2", "W3.2")
    sk.offset = (ox, 0)
    sk.wire("W3.1", (None, YC + 6.35))
    sk.ground((None, None))
    sk.ground("W4.2", "right")
    # The 270 pF + 43k across the secondary, the 12AX7 grids.
    sk.place("CZIN", 33.02, YC - 3.81)
    sk.place("RZIN", 33.02, YC + 3.81)
    sk.label("zin", "CZIN.2", "left")
    sk.place("V1", 48.26, YC - 15.24, unit=1)
    sk.place("V1", 48.26, YC + 15.24, unit=2, **FLIP)
    sk.wire("W4.1", (38.1, None), (None, YC - 15.24), "V1.2")
    sk.wire("W5.2", (38.1, None), (None, YC + 15.24), "V1.7")
    sk.label("g1a", (25.4, YC - 7.62))
    sk.label("g1b", (25.4, YC + 7.62))
    # The cathodes: 820 between them, the 360s to T3's feedback windings.
    sk.place("RK1", 48.26, YC)
    sk.wire("V1.3", "RK1.1")
    sk.wire("RK1.2", "V1.8")
    sk.label("k1a", (48.26, YC - 5.08), "left")
    sk.label("k1b", (48.26, YC + 5.08), "left")
    sk.place("RFBA", 55.88, YC - 7.62, **H)
    sk.place("RFBB", 55.88, YC + 7.62, **H)
    sk.wire("V1.3", "RFBA.1")
    sk.wire("V1.8", "RFBB.1")
    # The plates: 20 pF between them, the 200k loads with B+ (b4) between them.
    sk.label("p1a", (55.88, YC - 25.4))
    sk.label("p1b", (55.88, YC + 25.4))
    sk.place("CPP1", 74.93, YC)
    sk.wire("CPP1.1", (None, YC - 25.4))
    sk.wire("CPP1.2", (None, YC + 25.4))
    sk.place("RPL1A", 85.09, YC - 7.62, **FLIP)
    sk.place("RPL1B", 85.09, YC + 7.62)
    sk.wire("RPL1A.2", (None, YC - 25.4))
    sk.wire("RPL1B.2", (None, YC + 25.4))
    sk.wire("RPL1A.1", "RPL1B.1")
    sk.label("b4", (85.09, YC), "left")
    sk.place("RFBR", 69.85, YC + 41.91)
    sk.wire("RFBR.2", (None, YC + 45.72))
    sk.ground((None, None))


def output_stage(sk: Sketch) -> None:
    ox = 403.86
    sk.offset = (ox, 0)
    sk.frame("12AU7 and output", ox, 0, 137.16, 127)
    # Coupling capacitors, grid leaks to the bias divider (gb2).
    sk.place("CC2A", 12.7, YC - 25.4, **H)
    sk.place("CC2B", 12.7, YC + 25.4, **H)
    sk.place("RG2A", 25.4, YC - 7.62)
    sk.place("RG2B", 25.4, YC + 7.62, **FLIP)  # g2b below, gb2 above
    sk.wire("CC2A.2", (25.4, None), "RG2A.1")
    sk.wire("CC2B.2", (25.4, None), "RG2B.1")
    sk.label("g2a", (17.78, YC - 25.4))
    sk.label("g2b", (17.78, YC + 25.4))
    sk.wire("RG2A.2", "RG2B.2")
    sk.place("RBIAS_T", 17.78, YC, **H)
    sk.wire("RBIAS_T.2", (25.4, None))
    sk.offset = (0, 0)
    sk.wire((384.81, YC), "RBIAS_T.1")  # b4, from between the 12AX7's plate loads
    sk.wire("V1.1", (None, YC - 25.4), "CC2A.1")
    sk.wire("V1.6", (None, YC + 25.4), "CC2B.1")
    sk.offset = (ox, 0)
    sk.place("RBIAS_B", 35.56, YC + 3.81)
    sk.wire((25.4, YC), "RBIAS_B.1")
    sk.label("gb2", (30.48, YC))
    sk.wire("RBIAS_B.2", (None, YC + 10.16))
    sk.ground((None, None))
    # The 12AU7: grid from the leak's top, cathode resistor and bypass to ground.
    sk.place("V2", 45.72, YC - 17.78, unit=1)
    sk.place("V2", 45.72, YC + 17.78, unit=2, **FLIP)
    sk.wire("V2.2", (25.4, None))
    sk.wire("V2.7", (25.4, None))
    sk.place("RK2A", 53.34, YC - 6.35)
    sk.place("CK2A", 63.5, YC - 6.35)
    sk.place("RK2B", 53.34, YC + 6.35, **FLIP)
    sk.place("CK2B", 63.5, YC + 6.35, **FLIP)
    sk.wire("V2.3", "CK2A.1")
    sk.wire("V2.8", "CK2B.1")
    sk.label("k2a", (48.26, YC - 10.16))
    sk.label("k2b", (48.26, YC + 10.16))
    sk.wire("RK2A.2", "CK2A.2")
    sk.wire("RK2B.2", "CK2B.2")
    sk.wire((58.42, YC - 2.54), (None, YC + 2.54))
    sk.ground((58.42, YC), "right")
    # S-217-D: the primary's halves to the plates, B+ (b3) at its centre tap.
    sk.place("W6", 83.82, YC - 3.81)
    sk.place("W7", 83.82, YC + 3.81)
    sk.place("T3", 86.36, YC)
    sk.wire("V2.1", (None, YC - 30.48), (73.66, None), (None, YC - 7.62), "W6.1")
    sk.wire("V2.6", (None, YC + 30.48), (73.66, None), (None, YC + 7.62), "W7.2")
    sk.label("b3", "W6.2", "left")
    sk.label("p2a", (63.5, YC - 30.48))
    sk.label("p2b", (63.5, YC + 30.48))
    # The secondary to the output, the Zobel and the load.
    sk.place("W8", 88.9, YC - 3.81, mirror=True)
    sk.place("W9", 88.9, YC + 3.81, mirror=True)
    sk.label("s9", "W8.2")
    sk.wire("W9.2", (None, YC + 10.16))
    sk.ground((None, None))
    sk.place("CZOUT", 104.14, YC - 11.43)
    sk.place("RZOUT", 104.14, YC - 3.81)
    sk.label("zout", "CZOUT.2", "left")
    sk.wire("RZOUT.2", (None, YC + 2.54))
    sk.ground((None, None))
    sk.place("Rload", 116.84, YC - 11.43)
    sk.wire("Rload.2", (None, YC - 5.08))
    sk.ground((None, None))
    sk.wire("W8.1", (97.79, None), (None, YC - 15.24), (124.46, None))
    sk.label("out", (124.46, YC - 15.24))
    # The feedback windings, back to the 12AX7 cathodes along the bottom.
    sk.place("W10", 88.9, YC + 19.05, mirror=True)
    sk.place("W11", 88.9, YC + 26.67, mirror=True)
    sk.offset = (0, 0)
    sk.wire("RFBA.2", (364.49, None), (None, YC + 33.02), (ox + 99.06, None),
            (None, YC + 15.24), "W10.1")  # fmt: skip
    sk.wire("RFBB.2", (361.95, None), (None, YC + 35.56), (ox + 88.9, None), "W11.2")
    sk.wire("W10.2", (ox + 106.68, None), (None, YC + 38.1), "RFBR.1")
    sk.offset = (ox, 0)
    sk.label("fba", (99.06, YC + 29.21))
    sk.label("fbb", (68.58, YC + 35.56))
    sk.label("fbs", (101.6, YC + 22.86))


def power_supply(sk: Sketch) -> None:
    ox, oy = 299.72, 139.7
    sk.offset = (ox, oy)
    sk.frame("power supply", ox, oy, 152.4, 63.5)
    yp = 30.48
    # The PCC-55's HV winding as two mains sources (centre tap grounded), each through
    # its winding resistance and leakage to a 6X4 anode.
    for src, r, lk, cap, d, row, names in (
        ("VHVA", "RPCCA", "LPCCA", "CPCCA", 1, yp - 10.16, ("hva", "hva_r", "rka")),
        ("VHVB", "RPCCB", "LPCCB", "CPCCB", 2, yp + 10.16, ("hvb", "hvb_r", "rkb")),
    ):
        sk.place(src, 12.7, row + 5.08)
        sk.wire(f"{src}.2", (None, row + 12.7))
        sk.ground((None, None))
        sk.place(r, 22.86, row, **H)
        sk.place(lk, 35.56, row, **H)
        sk.place("V3", 58.42, row, rot=90, unit=d)
        anode = "V3.1" if d == 1 else "V3.3"
        sk.wire(f"{src}.1", f"{r}.1")
        sk.wire(f"{r}.2", f"{lk}.1")
        sk.wire(f"{lk}.2", anode)
        sk.place(cap, 44.45, row + (3.81 if d == 1 else -3.81), **({} if d == 1 else FLIP))
        sk.label(names[0], (15.24, row))
        sk.label(names[1], (27.94, row))
        sk.label(names[2], (40.64, row))
    sk.wire("CPCCA.2", "CPCCB.2")
    sk.ground((44.45, yp), "right")
    sk.wire("V3.2", (64.77, None), (None, yp + 10.16), "V3.4")
    # The RC filter: b0 -> 470 -> b1 -> 1000 -> b2 -> 2200 -> b3, 47k -> b4.
    sk.place("RPSU1", 72.39, yp, **H)
    sk.wire((64.77, yp), "RPSU1.1")
    sk.label("b0", (66.04, yp))
    sk.place("CPSU1", 80.01, yp + 3.81)
    sk.place("RPSU2", 93.98, yp, **H)
    sk.wire("RPSU1.2", "RPSU2.1")
    sk.label("b1", (85.09, yp))
    sk.place("CPSU2", 101.6, yp + 3.81)
    sk.place("RHTR_T", 114.3, yp + 3.81)
    sk.place("RPSU3", 127, yp, **H)
    sk.wire("RPSU2.2", "RPSU3.1")
    sk.label("b2", (106.68, yp))
    sk.place("CPSU3", 135.89, yp + 3.81)
    sk.wire("RPSU3.2", (142.24, yp))
    sk.label("b3", (142.24, yp))
    for c in ("CPSU1", "CPSU2", "CPSU3"):
        sk.wire(f"{c}.2", (None, yp + 10.16))
        sk.ground((None, None))
    sk.place("RPSU4", 111.76, yp - 17.78, **H)
    sk.wire((104.14, yp), (None, yp - 17.78), "RPSU4.1")
    sk.wire("RPSU4.2", (142.24, None))
    sk.label("b4", (142.24, yp - 17.78))
    sk.place("CPSU4", 121.92, yp - 13.97)
    sk.wire("CPSU4.2", (None, yp - 7.62))
    sk.ground((None, None))
    # The heater's elevation: 270k / 62k with 0.3 uF.
    sk.place("RHTR_B", 114.3, yp + 11.43)
    sk.place("CHTR", 127, yp + 11.43)
    sk.wire("RHTR_B.1", "CHTR.1")
    sk.label("htr", (119.38, yp + 7.62))
    for p in ("RHTR_B.2", "CHTR.2"):
        sk.wire(p, (None, yp + 17.78))
        sk.ground((None, None))


def draw() -> Sketch:
    sk = Sketch(load_circuit(circuit_path("pultec_eqp1a")))
    input_section(sk)
    passive_network(sk)
    interstage(sk)
    output_stage(sk)
    power_supply(sk)
    return sk


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="check the layout, save nothing")
    ap.add_argument("--check", action="store_true", help="compare the saved IR (all switches)")
    args = ap.parse_args()
    sk = draw()
    found = sk.problems()
    for p in found:
        print(p)
    if found:
        sys.exit(f"{len(found)} problems")
    if not args.dry_run:
        for p in save_circuit(sk.d, NAME, origin="scripts/draw_pultec_eqp1a.py"):
            print("wrote", p)
    if args.check:
        check(sk)


def check(sk: Sketch) -> None:
    from varimu.circuit import builder
    from varimu.circuit.spec import resolve
    from varimu.editor.compile import check_drawing, compiled_spec
    from varimu.kicad.compare import ir_differences
    from varimu.preflight import switch_configs

    c, found = check_drawing(sk.d)
    assert c.ok and not found, [m.message for m in found]
    a, b = load_circuit(circuit_path("pultec_eqp1a")), compiled_spec(c)
    configs = [*switch_configs(a), {"passive_spread": 1.0, "passive_seed": 7}]
    for ov in configs:
        diff = ir_differences(builder.build_ir(a, resolve(a, ov), "linear"),
                              builder.build_ir(b, resolve(b, ov), "linear"))  # fmt: skip
        assert not diff, (ov, diff)
    print(f"same IR at {len(configs)} configurations")


if __name__ == "__main__":
    main()

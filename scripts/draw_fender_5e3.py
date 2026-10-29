"""Draw the Fender 5E3 Deluxe as a schematic (device builder B9 step 5): the hand-written
circuit (config/circuits/fender_5e3.yaml) laid out after Fender's drawing F-EE
(data/schematics/fender_5e3/schematic_f-ee.png), saved as config/circuits/fender_5e3_drawn.

    uv run python scripts/draw_fender_5e3.py [--check] [--dry-run]

Signal flows left to right as on F-EE: the two channels' jacks (the bright channel on
top), the 12AY7 with the bright triode up and the normal one turned over below their
shared cathode, the interacting volumes with the tone control between them on V2A's grid,
the 12AX7 (V2A and the cathodyne), and the 6V6GT pair on the output transformer and the
speaker's electrical equivalent; the supply runs along the bottom. The jacks are rotary
switch decks on `input_jack` (the circuit file's contacts as resistors); B+1..3 are
labels. Every part, value and field is the circuit file's (varimu.editor.sketch keeps
them); only the layout is drawn here. --check compares the saved circuit's IR with the
hand-written one at every jack and with drawn tolerances.
"""

from __future__ import annotations

import argparse
import sys

from varimu.circuit.spec import circuit_path, load_circuit
from varimu.editor.compile import save_circuit
from varimu.editor.sketch import Sketch

NAME = "fender_5e3_drawn"
CIRCUIT = "fender_5e3"
H, HR = {"rot": 90}, {"rot": 270}  # pin 1 left; pin 1 right
FRAME_H = 121.92


def jacks(sk: Sketch, ch: str, oy: float) -> None:
    """One channel's jacks: deck A (common j1) puts input 1's tip on `in` or grounds it,
    deck C (common j1) ties input 2's tip to it, deck B (common `in`) feeds input 2."""
    sk.offset = (0, oy)
    j1, j2, g1 = f"j1{ch}", f"j2{ch}", f"g1{ch}"
    deck_a, deck_b, deck_c = f"SIN{ch.upper()}", f"SIN{ch.upper()}_B", f"SIN{ch.upper()}_C"
    r_in, r_gnd = f"RJ1{ch.upper()}_IN", f"RJ1{ch.upper()}_GND"
    r2_in, r2_j1 = f"RJ2{ch.upper()}_IN", f"RJ2{ch.upper()}_J1"
    sk.place(deck_a, 15.24, 10.16)
    sk.place(deck_c, 15.24, 27.94)
    sk.place(deck_b, 15.24, 45.72)
    sk.wire(f"{deck_a}.C", f"{deck_c}.C")
    sk.wire(f"{deck_a}.C", (3.81, 10.16))
    sk.label(j1, (None, None), "left")
    sk.wire(f"{deck_b}.C", (3.81, 45.72))
    sk.label("in", (None, None), "left")
    # Deck A: the contact that feeds input 1, the ones that ground it.
    feed = 1 if ch == "b" else 3
    y_feed = 6.35 + 2.54 * (feed - 1)
    sk.place(r_in, 30.48, y_feed, **HR)
    sk.wire(f"{deck_a}.{feed}", f"{r_in}.2")
    sk.wire(f"{r_in}.1", (36.83, y_feed))
    sk.label("in", (None, None))
    sk.place(r_gnd, 25.4, 17.78)
    if ch == "b":  # 2, 3, 4 ground it
        sk.wire(f"{deck_a}.2", f"{deck_a}.4", f"{r_gnd}.1")
    else:  # 1, 2, 4: around contact 3's wire
        sk.wire(f"{deck_a}.1", f"{deck_a}.2", (25.4, None), f"{r_gnd}.1")
        sk.wire(f"{deck_a}.4", f"{r_gnd}.1")
    sk.wire(f"{r_gnd}.2", (None, 22.86))
    sk.ground((None, None))
    # Deck C: input 2's tip to input 1's unless input 2 is played.
    sk.place(r2_j1, 30.48, 24.13, **HR)
    sk.wire(f"{deck_c}.1", f"{r2_j1}.2")
    if ch == "b":  # 1, 3, 4 (2 open)
        sk.wire((25.4, 24.13), (None, 31.75), f"{deck_c}.4")
        sk.wire(f"{deck_c}.3", (25.4, None))
    else:  # 1, 2, 3 (4 open)
        sk.wire(f"{deck_c}.1", f"{deck_c}.3")
    # Deck B: `in` to input 2's tip when it's played.
    play = 2 if ch == "b" else 4
    y_play = 41.91 + 2.54 * (play - 1)
    sk.place(r2_in, 30.48, y_play, **H)
    sk.wire(f"{deck_b}.{play}", f"{r2_in}.1")
    sk.wire(f"{r2_j1}.1", f"{r2_in}.2")
    sk.label(j2, (34.29, 34.29))
    # The divider: 1 MEG to ground, 68K to the grid, 68K from input 2's tip.
    sk.place(f"RIN1{ch.upper()}", 40.64, 13.97)
    sk.place(f"RGA{ch.upper()}", 48.26, 13.97)
    sk.place(f"RGB{ch.upper()}", 48.26, 24.13)
    sk.wire((38.1, 10.16), f"RGA{ch.upper()}.1")
    sk.label(j1, (38.1, 10.16), "left")
    sk.wire(f"RIN1{ch.upper()}.2", (None, 20.32))
    sk.ground((None, None))
    sk.wire(f"RGA{ch.upper()}.2", f"RGB{ch.upper()}.1")
    sk.wire((48.26, 19.05), (55.88, None))
    sk.label(g1, (None, None))
    sk.wire(f"RGB{ch.upper()}.2", (34.29, None))


def inputs(sk: Sketch) -> None:
    sk.offset = (0, 0)
    sk.frame("inputs", 0, 0, 73.66, FRAME_H)
    jacks(sk, "b", 0.0)
    jacks(sk, "n", 60.96)


def preamp(sk: Sketch) -> None:
    ox = 81.28
    sk.offset = (0, 0)
    sk.frame("12AY7 and controls", ox, 0, 63.5, FRAME_H)
    sk.offset = (ox, 0)
    # The 12AY7: the bright triode up, the normal one turned over, one cathode between.
    sk.place("V1B", 15.24, 25.4)
    sk.place("V1N", 15.24, 83.82, rot=180, mirror=True)
    sk.wire("V1B.2", (2.54, None))
    sk.label("g1b", (None, None), "left")
    sk.wire("V1N.2", (2.54, None))
    sk.label("g1n", (None, None), "left")
    sk.wire("V1B.3", "V1N.3")
    sk.place("RK1", 25.4, 58.42)
    sk.place("CK1", 33.02, 58.42)
    sk.wire((15.24, 54.61), "CK1.1")
    sk.label("k1", (15.24, 54.61), "left")
    for p in ("RK1.2", "CK1.2"):
        sk.wire(p, (None, 64.77))
        sk.ground((None, None))
    # Plates: 100K to B+3, .1 to the volume's wiper.
    plates = (("V1B", "RPL1B", "CC1B", 15.24, 5.08, "up"),
              ("V1N", "RPL1N", "CC1N", 93.98, 104.14, "down"))  # fmt: skip
    for tube, rpl, cc, y, yb, side in plates:
        sk.place(rpl, 25.4, y - 3.81 if side == "up" else y + 3.81, rot=0 if side == "up" else 180)
        sk.place(cc, 35.56, y, **H)
        sk.wire(f"{tube}.1", (None, y), f"{rpl}.2")
        sk.wire(f"{rpl}.2", f"{cc}.1")
        sk.label(f"p1{tube[-1].lower()}", (15.24, y), "left")
        sk.wire(f"{rpl}.1", (None, yb))
        sk.label("b3", (None, None), side)
    # The volumes: ground at the outer end, the plate's signal on the wiper, V2A's grid
    # at the inner end; the tone control between the bright wiper and that grid.
    sk.place("RVOLB", 45.72, 15.24, mirror=True)
    sk.place("RVOLN", 45.72, 93.98, rot=180)
    sk.wire("CC1B.2", "RVOLB.2")
    sk.wire("CC1N.2", "RVOLN.2")
    sk.label("vb", (40.64, 15.24), "up")
    sk.label("vn", (40.64, 93.98), "down")
    sk.wire("RVOLB.1", (None, 10.16))
    sk.ground((None, None), "up")
    sk.wire("RVOLN.1", (None, 99.06))
    sk.ground((None, None))
    sk.place("CTT", 40.64, 24.13)
    sk.place("RTONE", 40.64, 34.29, rot=180, mirror=True)
    sk.place("CTB", 40.64, 43.18)
    sk.wire((40.64, 15.24), "CTT.1")
    sk.wire("CTT.2", "RTONE.3")
    sk.label("tt", (40.64, 29.21), "left")
    sk.wire("RTONE.1", "CTB.1")
    sk.label("tb", (40.64, 38.1), "left")
    sk.wire("CTB.2", (None, 49.53))
    sk.ground((None, None))
    sk.wire("RVOLB.3", (None, 21.59), (50.8, None), (None, 87.63), (45.72, None), "RVOLN.3")
    sk.wire("RTONE.2", (50.8, None))
    sk.wire((50.8, 54.61), (58.42, None))
    sk.label("g2", (None, None))


def driver(sk: Sketch) -> None:
    ox = 149.86
    sk.offset = (0, 0)
    sk.frame("12AX7 and inverter", ox, 0, 83.82, FRAME_H)
    sk.offset = (ox, 0)
    # V2A: 100K plate, 1500 / 25 uF cathode, .1 to the cathodyne.
    sk.place("V2", 15.24, 50.8, unit=1)
    sk.wire("V2.2", (2.54, None))
    sk.label("g2", (None, None), "left")
    sk.place("RPL2", 15.24, 35.56)
    sk.wire("RPL2.2", "V2.1")
    sk.wire("RPL2.1", (None, 29.21))
    sk.label("b3", (None, None), "up")
    sk.place("RK2", 15.24, 64.77)
    sk.place("CK2", 22.86, 64.77)
    sk.wire("V2.3", "RK2.1")
    sk.wire("RK2.1", "CK2.1")
    sk.label("k2", (15.24, 60.96), "left")
    for p in ("RK2.2", "CK2.2"):
        sk.wire(p, (None, 71.12))
        sk.ground((None, None))
    sk.place("CC2", 25.4, 41.91, **H)
    sk.wire((15.24, 41.91), "CC2.1")
    sk.label("p2", (15.24, 41.91), "left")
    # The cathodyne: 56K plate, 1500 + 56K cathode, 1 MEG grid leak to their junction.
    sk.place("V2", 40.64, 50.8, unit=2)
    sk.place("RG3", 31.75, 62.23)
    sk.wire("CC2.2", (31.75, None), "RG3.1")
    sk.wire((31.75, 50.8), "V2.7")
    sk.label("g3", (31.75, 41.91), "up")
    sk.place("RPL3", 40.64, 35.56)
    sk.wire("RPL3.2", "V2.6")
    sk.wire("RPL3.1", (None, 29.21))
    sk.label("b3", (None, None), "up")
    sk.place("RK3", 40.64, 64.77)
    sk.place("RTAIL", 40.64, 76.2)
    sk.wire("V2.8", "RK3.1")
    sk.wire("RK3.2", "RTAIL.1")
    sk.wire("RG3.2", (None, 69.85), (40.64, None))
    sk.label("kj", (31.75, 69.85), "left")
    sk.wire("RTAIL.2", (None, 82.55))
    sk.ground((None, None))
    # Outputs: the plate's and the cathode's, each .1 to a 220K leak and a 1500 stopper.
    for tap, cc, rgl, rgs, node, g6, y in (
        ((40.64, 41.91), "CC3A", "RGLA", "RGSA", "oa", "g6a", 41.91),
        ((40.64, 59.69), "CC3B", "RGLB", "RGSB", "ob", "g6b", 59.69),
    ):
        sk.place(cc, 55.88, y, **H)
        sk.place(rgl, 63.5, y + 6.35)
        sk.place(rgs, 71.12, y, **H)
        sk.wire(tap, f"{cc}.1")
        sk.wire(f"{cc}.2", f"{rgs}.1")
        sk.wire((63.5, y), f"{rgl}.1")
        sk.label(node, (63.5, y), "up")
        sk.wire(f"{rgl}.2", (None, y + 12.7))
        sk.ground((None, None))
        sk.wire(f"{rgs}.2", (78.74, None))
        sk.label(g6, (None, None))
    sk.label("p3", (40.64, 41.91), "left")
    sk.label("k3", (40.64, 59.69), "left")


def output(sk: Sketch) -> None:
    ox = 238.76
    sk.offset = (0, 0)
    sk.frame("output", ox, 0, 106.68, FRAME_H)
    sk.offset = (ox, 0)
    # The 6V6GT pair: V6A up, V6B turned over, one bypassed cathode resistor between.
    sk.place("V6A", 15.24, 30.48)
    sk.place("V6B", 15.24, 76.2, rot=180, mirror=True)
    for tube, g6 in (("V6A", "g6a"), ("V6B", "g6b")):
        sk.wire(f"{tube}.3", (2.54, None))
        sk.label(g6, (None, None), "left")
        sk.wire(f"{tube}.2", (27.94, None))
        sk.label("b2", (None, None))
    sk.wire("V6A.4", "V6B.4")
    sk.place("RK6", 22.86, 57.15)
    sk.place("CK6", 30.48, 57.15)
    sk.wire((15.24, 53.34), "CK6.1")
    sk.label("k6", (15.24, 53.34), "left")
    for p in ("RK6.2", "CK6.2"):
        sk.wire(p, (None, 63.5))
        sk.ground((None, None))
    # The output transformer: plates on the primary's ends, B+1 on its centre tap.
    sk.place("W1", 45.72, 45.72)
    sk.place("W2", 45.72, 57.15)
    sk.place("T1", 48.26, 50.8)
    sk.place("W3", 50.8, 53.34, mirror=True)
    sk.wire("V6A.1", (None, 17.78), (45.72, None), "W1.1")
    sk.label("p6a", (15.24, 17.78), "left")
    sk.wire("V6B.1", (None, 88.9), (45.72, None), "W2.2")
    sk.label("p6b", (15.24, 88.9), "left")
    sk.wire("W1.2", "W2.1")
    sk.wire((45.72, 50.8), (40.64, None))
    sk.label("b1", (None, None), "left")
    sk.wire("W3.2", (None, 63.5))
    sk.ground((None, None))
    # The speaker's electrical equivalent: Re + Le, then the motional RLC.
    sk.place("RSPK_E", 64.77, 45.72, **H)
    sk.place("LSPK_E", 76.2, 45.72, **H)
    sk.wire("W3.1", (None, 45.72), "RSPK_E.1")
    sk.label("out", (55.88, 45.72), "up")
    sk.wire("RSPK_E.2", "LSPK_E.1")
    sk.label("spk_l", (68.58, 45.72), "up")
    for i, part in enumerate(("RSPK_M", "LSPK_M", "CSPK_M")):
        x = 83.82 + 7.62 * i
        sk.place(part, x, 53.34)
        sk.wire(f"{part}.2", (None, 60.96))
        sk.ground((None, None))
    sk.wire("LSPK_E.2", (99.06, None), "CSPK_M.1")
    sk.wire((83.82, 45.72), "RSPK_M.1")
    sk.wire((91.44, 45.72), "LSPK_M.1")
    sk.label("spk_m", (83.82, 45.72), "up")


def power_supply(sk: Sketch) -> None:
    ox, oy = 81.28, 132.08
    sk.offset = (0, 0)
    sk.frame("power supply", ox, oy, 132.08, 50.8)
    sk.offset = (ox, oy)
    # The power transformer's HV halves (each behind its resistance and leakage) into the
    # 5Y3GT's plates; its filament is B+1.
    for half, y in (("A", 15.24), ("B", 33.02)):
        lo = half.lower()
        sk.place(f"VHV{half}", 10.16, y + 5.08)
        sk.place(f"RPT{half}", 20.32, y, **H)
        sk.place(f"LPT{half}", 31.75, y, **H)
        sk.place(f"CPT{half}", 40.64, y + 3.81)
        sk.wire(f"VHV{half}.1", f"RPT{half}.1")
        sk.label(f"hv_{lo}", (10.16, y), "up")
        sk.wire(f"RPT{half}.2", f"LPT{half}.1")
        sk.label(f"hv_{lo}r", (24.13, y), "up")
        sk.wire(f"VHV{half}.2", (None, y + 12.7))
        sk.ground((None, None))
        sk.wire(f"CPT{half}.2", (None, y + 10.16))
        sk.ground((None, None))
    sk.place("V5", 50.8, 15.24, rot=90, unit=1)
    sk.place("V5", 50.8, 33.02, rot=90, unit=2)
    sk.wire("LPTA.2", "V5.1")
    sk.label("hva", (40.64, 15.24), "up")
    sk.wire("LPTB.2", "V5.3")
    sk.label("hvb", (40.64, 33.02), "up")
    sk.wire("V5.2", (58.42, None), (None, 33.02), "V5.4")
    # B+1 .. B+3: 16 uF each, 5000 and 22K between (and the numerical leak on B+1).
    sk.place("CB1", 66.04, 27.94)
    sk.place("RLEAK", 73.66, 27.94)
    sk.place("RB12", 83.82, 24.13, **H)
    sk.place("CB2", 93.98, 27.94)
    sk.place("RB23", 104.14, 24.13, **H)
    sk.place("CB3", 114.3, 27.94)
    sk.wire((58.42, 24.13), "RB12.1")
    sk.label("b1", (58.42, 24.13), "left")
    sk.wire("RB12.2", "RB23.1")
    sk.label("b2", (87.63, 24.13), "up")
    sk.wire("RB23.2", (119.38, None))
    sk.label("b3", (None, None))
    for p in ("CB1.2", "RLEAK.2", "CB2.2", "CB3.2"):
        sk.wire(p, (None, 35.56))
        sk.ground((None, None))


def draw() -> Sketch:
    sk = Sketch(load_circuit(circuit_path(CIRCUIT)))
    inputs(sk)
    preamp(sk)
    driver(sk)
    output(sk)
    power_supply(sk)
    return sk


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="check the layout, save nothing")
    ap.add_argument("--check", action="store_true", help="compare the saved IR (all jacks)")
    args = ap.parse_args()
    sk = draw()
    found = sk.problems()
    for p in found:
        print(p)
    if found:
        sys.exit(f"{len(found)} problems")
    if not args.dry_run:
        for p in save_circuit(sk.d, NAME, origin="scripts/draw_fender_5e3.py"):
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
    a, b = load_circuit(circuit_path(CIRCUIT)), compiled_spec(c)
    assert a.full_scale == b.full_scale, (a.full_scale, b.full_scale)
    configs = [*switch_configs(a), {"passive_spread": 1.0, "passive_seed": 7}]
    for ov in configs:
        diff = ir_differences(builder.build_ir(a, resolve(a, ov), "linear"),
                              builder.build_ir(b, resolve(b, ov), "linear"))  # fmt: skip
        assert not diff, (ov, diff)
    print(f"same IR at {len(configs)} configurations")


if __name__ == "__main__":
    main()

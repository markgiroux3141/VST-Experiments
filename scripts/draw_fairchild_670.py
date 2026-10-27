"""Draw the Fairchild 670 as a schematic (device builder B4a): the hand-written channel
(config/circuits/fairchild_670.yaml) laid out after the drawings in
data/schematics/fairchild_670/ (audio_path, sidechain_1 / 2, psu_1 / 2, rails*), saved as
config/circuits/fairchild_670_drawn.

    uv run python scripts/draw_fairchild_670.py [--check] [--dry-run]

Three rows, signal left to right: the audio path (input pad and T101, the four 6386s a
side, T102) with the idle channel 2 beside it; the sidechain (T103 and the threshold
pots, the 12AX7, the 12BH7, the 6973 and T104, the bridge and the Time Constant
switch); the supplies (the regulated B+ with its EL34 / 6084 / 5651 regulator, the
selenium bias supply). Every part, value and field is the circuit file's
(varimu.editor.sketch keeps them); only the layout is drawn here. Rails (bp, ur, sg,
nb2-nb4) are labels, as are the sidechain's feeds that cross the page: the output into
the sidechain (out), the control voltage back to T101's centre tap (cv) and T104's
feedback winding back to the 12BH7's cathodes (fy, fg). --check compares the saved
circuit's IR with the hand-written one at every Time Constant position, both core
models and drawn tolerances (tests/test_editor_drawings.py does too).
"""

from __future__ import annotations

import argparse
import sys

from varimu.circuit.spec import circuit_path, load_circuit
from varimu.editor.compile import save_circuit
from varimu.editor.sketch import Sketch

NAME = "fairchild_670_drawn"
H, FLIP = {"rot": 90}, {"rot": 180, "mirror": True}  # pin 1 left; pin 1 at the bottom
R270 = {"rot": 270}  # pin 1 right
ROW1, ROW2, ROW3 = 0.0, 101.6, 254.0  # the rows' tops
Y1 = 45.72  # the audio path's centre line (T101's and T102's centre taps), in row 1
Y2 = 55.88  # the sidechain's centre line, in row 2


def at(sk: Sketch, x: float, y: float) -> None:
    sk.offset = (x, y)


def input_section(sk: Sketch) -> None:
    at(sk, 0, ROW1)
    sk.frame("input", 0, ROW1, 73.66, 91.44)
    y = Y1 - 3.81
    sk.place("Rsrc", 11.43, y, **H)
    sk.wire((3.81, y), "Rsrc.1")
    sk.label("in", (3.81, y), "left")
    sk.place("AT101", 27.94, y)
    sk.wire("Rsrc.2", "AT101.1")
    sk.label("in_s", (17.78, y))
    sk.wire("AT101.3", (None, Y1 + 3.81))
    sk.ground((None, None))
    # T101: the primary across 360 ohm, the secondary's halves to the 6386 grids, the
    # control voltage (cv) into its centre tap.
    sk.place("R101", 38.1, Y1)
    sk.place("W1", 55.88, Y1)
    sk.place("T101", 58.42, Y1)
    sk.place("W2", 60.96, Y1 - 3.81, mirror=True)
    sk.place("W3", 60.96, Y1 + 3.81, mirror=True)
    sk.wire("AT101.2", "W1.1")
    sk.label("pri", (45.72, y))
    for p in ("R101.2", "W1.2"):
        sk.wire(p, (None, Y1 + 6.35))
        sk.ground((None, None))
    sk.label("cv", "W2.2")


def push_pull(sk: Sketch) -> None:
    ox = 81.28
    at(sk, ox, ROW1)
    sk.frame("6386 push-pull", ox, ROW1, 190.5, 91.44)
    side_a = ["V101A", "V102A", "V103B", "V104B"]
    side_b = ["V101B", "V102B", "V103A", "V104A"]
    xs = [25.4 + 20.32 * i for i in range(4)]
    ya, yb = Y1 - 21.59, Y1 + 21.59  # the tubes' centres
    for x, a, b in zip(xs, side_a, side_b, strict=True):
        sk.place(a, x, ya)
        sk.place(b, x, yb, **FLIP)  # plate down, cathode up
    # Grid buses from T101's secondary, plate buses to T102, cathode buses to the
    # balance network.
    at(sk, 0, ROW1)
    sk.wire("W2.1", (71.12, None), (None, Y1 - 31.75), (ox + xs[-1] - 7.62, None))
    sk.wire("W3.2", (71.12, None), (None, Y1 + 31.75), (ox + xs[-1] - 7.62, None))
    at(sk, ox, ROW1)
    for a, b in zip(side_a, side_b, strict=True):
        sk.wire(f"{a}.2", (None, Y1 - 31.75))
        sk.wire(f"{b}.2", (None, Y1 + 31.75))
    sk.label("ga", (5.08, Y1 - 31.75))
    sk.label("gb", (5.08, Y1 + 31.75))
    for a, b in zip(side_a[1:], side_b[1:], strict=True):
        sk.wire(f"{a}.1", (None, Y1 - 34.29))
        sk.wire(f"{b}.1", (None, Y1 + 34.29))
        sk.wire(f"{a}.3", (None, Y1 - 11.43))
        sk.wire(f"{b}.3", (None, Y1 + 11.43))
    xp = 152.4  # T102's primary
    sk.label("pa", (101.6, Y1 - 34.29))
    sk.label("pb", (101.6, Y1 + 34.29))
    # The cathodes: 680 each to the BALANCE pot (its wiper on the bias rail nb2), 4 uF
    # between them.
    xc, xn = 91.44, 106.68
    sk.place("R103", xn, Y1 - 7.62)
    sk.place("R105", xn, Y1)
    sk.place("R104", xn, Y1 + 7.62, **FLIP)
    sk.place("C101", xc, Y1)
    sk.wire(f"{side_a[0]}.3", (None, Y1 - 11.43), "R103.1")
    sk.wire(f"{side_b[0]}.3", (None, Y1 + 11.43), "R104.1")
    sk.wire("C101.1", (None, Y1 - 11.43))
    sk.wire("C101.2", (None, Y1 + 11.43))
    sk.label("ka", (35.56, Y1 - 11.43))
    sk.label("kb", (35.56, Y1 + 11.43))
    sk.label("ta", "R103.2")
    sk.label("tb", "R104.2")
    sk.wire("R105.2", (113.03, None))
    sk.label("nb2", (113.03, Y1))
    # T102: B+ through 33 ohm to the 30 ohm pair into the primary's centre taps.
    xr = 134.62
    sk.place("R107", xr, Y1 - 3.81, **FLIP)
    sk.place("R108", xr, Y1 + 3.81)
    sk.place("R111", 127, Y1, **H)
    sk.wire("R111.2", (xr, None))
    sk.label("bp", "R111.1", "left")
    sk.label("ctr", (xr, Y1))
    sk.place("W4", xp, Y1 - 11.43)
    sk.place("W5", xp, Y1 + 11.43)
    sk.place("T102", xp + 2.54, Y1)
    sk.wire(f"{side_a[0]}.1", (None, Y1 - 34.29), (xp - 10.16, None), (None, Y1 - 15.24), "W4.1")
    sk.wire(f"{side_b[0]}.1", (None, Y1 + 34.29), (xp - 10.16, None), (None, Y1 + 15.24), "W5.2")
    sk.wire("R107.2", "W4.2")
    sk.wire("R108.2", "W5.1")
    sk.label("t3", (140.97, Y1 - 7.62))
    sk.label("t2", (140.97, Y1 + 7.62))
    sk.place("W6", xp + 5.08, Y1, mirror=True)
    sk.wire("W6.2", (None, Y1 + 6.35))
    sk.ground((None, None))
    sk.place("Rload", 172.72, Y1)
    sk.wire("Rload.2", (None, Y1 + 6.35))
    sk.ground((None, None))
    sk.wire("W6.1", (182.88, None))
    sk.label("out", (182.88, Y1 - 3.81))


def channel_2(sk: Sketch) -> None:
    ox = 279.4
    at(sk, ox, ROW1)
    sk.frame("channel 2 (idle, lumped)", ox, ROW1, 165.1, 50.8)
    y = 25.4
    # Its 6386s as one triode: grid from its BALANCE pot, plate load, cathode to nb2.
    sk.place("R242", 12.7, y, **FLIP)  # nb3 up, ground down, wiper right
    sk.place("V2_6386", 27.94, y)
    sk.wire("R242.2", "V2_6386.2")
    sk.label("g6c2", (17.78, y))
    sk.wire("R242.3", (None, y - 6.35))
    sk.label("nb3", (None, None), "up")
    sk.wire("R242.1", (None, y + 6.35))
    sk.ground((None, None))
    sk.place("R211", 27.94, y - 11.43)
    sk.wire("R211.1", (None, y - 17.78))
    sk.label("bp", (None, None), "up")
    sk.label("p6c2", "V2_6386.1")
    sk.place("R203", 27.94, y + 11.43)
    sk.wire("R203.2", (None, y + 17.78))
    sk.label("nb2", (None, None), "down")
    sk.label("k6c2", "V2_6386.3")
    # Its 12AX7's cathode network (DC BALANCE), without the tube.
    sk.place("R218", 48.26, y - 3.81)
    sk.place("R219", 48.26, y + 3.81)
    sk.place("R217", 66.04, y + 3.81, **FLIP)  # k1c2 up, ground down, wiper right
    sk.wire("R218.2", "R217.3")
    sk.label("k1c2", (53.34, y))
    sk.wire("R218.1", (None, y - 10.16))
    sk.label("bp", (None, None), "up")
    for p in ("R219.2", "R217.1"):
        sk.wire(p, (None, y + 10.16))
        sk.ground((None, None))
    sk.place("R216", 73.66, y)
    sk.wire("R217.2", "R216.2")
    sk.label("dw2", (71.12, y + 3.81))
    sk.wire("R216.1", (None, y - 6.35))
    sk.label("bp", (None, None), "up")
    # Its 12BH7, grid grounded.
    sk.place("V2_12BH7", 99.06, y)
    sk.ground("V2_12BH7.2")
    sk.place("R226", 99.06, y - 11.43)
    sk.wire("R226.1", (None, y - 17.78))
    sk.label("ur", (None, None), "up")
    sk.label("p2c2", "V2_12BH7.1")
    sk.place("R224", 99.06, y + 11.43)
    sk.wire("R224.2", (None, y + 17.78))
    sk.ground((None, None))
    sk.label("k2c2", "V2_12BH7.3")
    # Its 6973s as one pentode.
    sk.place("V2_6973", 139.7, y)
    sk.wire("V2_6973.1", (None, y - 11.43))
    sk.label("ur", (None, None), "up")
    sk.place("R232", 152.4, y + 2.54, **FLIP)
    sk.wire("V2_6973.2", "R232.2")
    sk.wire("R232.1", (None, y + 8.89))
    sk.label("sg", (None, None), "down")
    sk.label("s3c2", (149.86, y - 1.27))
    sk.place("R230", 127, y + 5.08)
    sk.wire("V2_6973.3", "R230.1")
    sk.wire("R230.2", (None, y + 11.43))
    sk.label("nb4", (None, None), "down")
    sk.label("g3c2", (129.54, y + 1.27))
    sk.wire("V2_6973.4", (None, y + 11.43))
    sk.ground((None, None))


def sidechain_input(sk: Sketch) -> None:
    at(sk, 0, ROW2)
    sk.frame("sidechain input", 0, ROW2, 81.28, 104.14)
    y = Y2
    # T103 from the output across 150 / 1360 / 150 ohm.
    sk.place("R145", 10.16, y - 3.81, **H)
    sk.place("R147", 10.16, y + 3.81, **H)
    sk.wire((2.54, y - 3.81), "R145.1")
    sk.label("out", (2.54, y - 3.81), "left")
    sk.wire("R147.1", (None, y + 6.35))
    sk.ground((None, None))
    sk.place("R149", 20.32, y)
    sk.place("W7", 38.1, y)
    sk.place("T103", 40.64, y)
    sk.wire("R145.2", "W7.1")
    sk.wire("R147.2", "W7.2")
    sk.label("s1", (27.94, y - 3.81))
    sk.label("s2", (27.94, y + 3.81))
    sk.place("W8", 43.18, y - 3.81, mirror=True)
    sk.place("W9", 43.18, y + 3.81, mirror=True)
    # The THRESHOLD pots (tapped, 24k from the tap to ground), their wipers to the 12AX7.
    sk.place("R115A", 71.12, y - 15.24, **FLIP)  # t5 up, ground down, tap left, wiper right
    sk.place("R115B", 71.12, y + 15.24)
    sk.place("R113", 58.42, y - 11.43)
    sk.place("R114", 58.42, y + 11.43, **FLIP)
    sk.wire("W8.1", (None, y - 22.86), (71.12, None), "R115A.4")
    sk.wire("W9.2", (None, y + 22.86), (71.12, None), "R115B.4")
    sk.label("t5", (50.8, y - 22.86))
    sk.label("t8", (50.8, y + 22.86))
    sk.wire("R115A.2", "R113.1")
    sk.wire("R115B.2", "R114.1")
    sk.label("x1a", (60.96, y - 15.24))
    sk.label("x1b", (60.96, y + 15.24))
    sk.wire("W8.2", (71.12, None))
    for p in ("R113.2", "R114.2", "R115A.1", "R115B.1"):
        sk.wire(p, (None, y))
    sk.ground((66.04, y))


def twelve_ax7(sk: Sketch) -> None:
    ox = 88.9
    at(sk, ox, ROW2)
    sk.frame("12AX7", ox, ROW2, 55.88, 104.14)
    y, xt = Y2, 33.02
    sk.place("V105", xt, y - 15.24, unit=1)
    sk.place("V105", xt, y + 15.24, unit=2, **FLIP)
    sk.wire("R115A.3", "V105.2")
    sk.wire("R115B.3", "V105.7")
    sk.label("w1a", (7.62, y - 15.24))
    sk.label("w1b", (7.62, y + 15.24))
    # The common cathode: 1M from B+, 18k to ground, DC BALANCE (100k, 270k from B+).
    sk.wire("V105.3", "V105.8")
    sk.place("R118", 40.64, y - 3.81)
    sk.place("R119", 40.64, y + 3.81)
    sk.wire((xt, y), "R118.2")
    sk.place("R117", 17.78, y + 3.81, rot=180)  # k1 up, ground down, wiper left
    sk.wire("R117.3", (xt, None))
    sk.label("k1", (25.4, y))
    sk.place("R116", 7.62, y)
    sk.wire("R117.2", "R116.2")
    sk.label("dw", (10.16, y + 3.81))
    for p, yy in (("R118.1", y - 10.16), ("R116.1", y - 6.35)):
        sk.wire(p, (None, yy))
        sk.label("bp", (None, None), "up")
    for p in ("R119.2", "R117.1"):
        sk.wire(p, (None, y + 10.16))
        sk.ground((None, None))
    # Plate loads and the coupling capacitors to the 12BH7.
    sk.place("R120", xt, y - 26.67)
    sk.place("R121", xt, y + 26.67, **FLIP)
    sk.wire("R120.1", (None, y - 33.02))
    sk.label("bp", (None, None), "up")
    sk.wire("R121.1", (None, y + 33.02))
    sk.label("bp", (None, None), "down")
    sk.place("C103", 45.72, y - 22.86, **H)
    sk.place("C104", 45.72, y + 22.86, **H)
    sk.wire("V105.1", "C103.1")
    sk.wire("V105.6", "C104.1")
    sk.label("p1a", (36.83, y - 22.86))
    sk.label("p1b", (36.83, y + 22.86))


def twelve_bh7(sk: Sketch) -> None:
    ox = 152.4
    at(sk, ox, ROW2)
    sk.frame("12BH7", ox, ROW2, 55.88, 104.14)
    y, xu = Y2, 25.4
    sk.place("V106", xu, y - 22.86, unit=1)
    sk.place("V106", xu, y + 22.86, unit=2, **FLIP)
    sk.wire("C103.2", "V106.2")
    sk.wire("C104.2", "V106.7")
    sk.label("g2a", (2.54, y - 22.86))
    sk.label("g2b", (2.54, y + 22.86))
    # Grid leaks and cathode resistors to the centre ground; T104's feedback winding
    # (fy, fg) into the cathodes through 2700 ohm.
    sk.place("R122", 7.62, y - 12.7)
    sk.place("R123", 7.62, y + 12.7, **FLIP)
    sk.wire((7.62, y - 22.86), "R122.1")
    sk.wire((7.62, y + 22.86), "R123.1")
    sk.place("R124", xu, y - 11.43)
    sk.place("R125", xu, y + 11.43, **FLIP)
    sk.place("R128", 38.1, y - 15.24, **R270)
    sk.place("R129", 38.1, y + 15.24, **R270)
    sk.wire("V106.3", "R128.2")
    sk.wire("V106.8", "R129.2")
    sk.label("k2a", (30.48, y - 15.24))
    sk.label("k2b", (30.48, y + 15.24))
    sk.place("R134", 45.72, y - 11.43)
    sk.place("R135", 45.72, y + 11.43, **FLIP)
    sk.wire("R128.1", "R134.1", (50.8, None))
    sk.wire("R129.1", "R135.1", (50.8, None))
    sk.label("fy", (50.8, y - 15.24))
    sk.label("fg", (50.8, y + 15.24))
    sk.wire("R122.2", (None, y), (45.72, None))
    sk.wire("R123.2", (None, y))
    for p in ("R124.2", "R125.2", "R134.2", "R135.2"):
        sk.wire(p, (None, y))
    sk.ground((35.56, y))
    # Plate loads from the unregulated rail, coupling capacitors to the 6973s.
    sk.place("R126", xu, y - 34.29)
    sk.place("R127", xu, y + 34.29, **FLIP)
    sk.wire("R126.1", (None, y - 40.64))
    sk.label("ur", (None, None), "up")
    sk.wire("R127.1", (None, y + 40.64))
    sk.label("ur", (None, None), "down")
    sk.place("C107", 38.1, y - 30.48, **H)
    sk.place("C108", 38.1, y + 30.48, **H)
    sk.wire("V106.1", "C107.1")
    sk.wire("V106.6", "C108.1")
    sk.label("p2a", (29.21, y - 30.48))
    sk.label("p2b", (29.21, y + 30.48))


def sixty_nine_73(sk: Sketch) -> None:
    ox = 215.9
    at(sk, ox, ROW2)
    sk.frame("6973", ox, ROW2, 81.28, 104.14)
    y = Y2
    sk.place("V107", 33.02, y - 31.75)
    sk.place("V108", 33.02, y + 31.75, **FLIP)
    sk.wire("C107.2", "V107.3")
    sk.wire("C108.2", "V108.3")
    sk.label("g3a", (2.54, y - 30.48))
    sk.label("g3b", (2.54, y + 30.48))
    # Grid leaks to the bias rail nb4; 47k + 20 pF from each plate back to its grid.
    sk.place("R130", 7.62, y - 26.67)
    sk.place("R131", 7.62, y + 26.67, **FLIP)
    sk.wire("R130.2", (None, y - 20.32))
    sk.label("nb4", (None, None), "down")
    sk.wire("R131.2", (None, y + 20.32))
    sk.label("nb4", (None, None), "up")
    sk.place("R143", 15.24, y - 34.29, **FLIP)
    sk.place("R144", 15.24, y + 34.29)
    sk.place("C105", 22.86, y - 45.72, **H)
    sk.place("C106", 22.86, y + 45.72, **H)
    sk.wire("R143.2", (None, y - 45.72), "C105.1")
    sk.wire("R144.2", (None, y + 45.72), "C106.1")
    sk.label("nfa", (15.24, y - 41.91), "left")
    sk.label("nfb", (15.24, y + 41.91), "left")
    xp = 60.96  # T104's primary
    sk.place("W10", xp, y - 3.81)
    sk.place("W11", xp, y + 3.81)
    sk.place("T104", xp + 2.54, y)
    sk.wire("V107.1", (None, y - 45.72), (xp - 7.62, None), (None, y - 7.62), "W10.1")
    sk.wire("V108.1", (None, y + 45.72), (xp - 7.62, None), (None, y + 7.62), "W11.2")
    sk.wire("C105.2", (33.02, None))
    sk.wire("C106.2", (33.02, None))
    sk.label("pa3", (45.72, y - 45.72))
    sk.label("pb3", (45.72, y + 45.72))
    sk.label("ur", "W10.2", "left")
    # Screens through 560 ohm from sg; the cathodes to ground.
    sk.place("R132", 44.45, y - 29.21, **FLIP)
    sk.place("R133", 44.45, y + 29.21)
    sk.wire("V107.2", "R132.2")
    sk.wire("V108.2", "R133.2")
    sk.label("sa3", (43.18, y - 33.02))
    sk.label("sb3", (43.18, y + 33.02))
    sk.wire("R132.1", (None, y - 22.86))
    sk.label("sg", (None, None), "down")
    sk.wire("R133.1", (None, y + 22.86))
    sk.label("sg", (None, None), "up")
    sk.wire("V107.4", "V108.4")
    sk.ground((33.02, y), "right")
    # T104's secondary to the bridge; its feedback winding back to the 12BH7 (fy, fg).
    sk.place("W12", xp + 5.08, y - 7.62, mirror=True)
    sk.place("W13", xp + 5.08, y + 7.62, mirror=True)
    sk.label("fy", "W13.1")
    sk.label("fg", "W13.2")


def rectifier(sk: Sketch) -> None:
    ox = 304.8
    at(sk, ox, ROW2)
    sk.frame("rectifier and time constant", ox, ROW2, 93.98, 152.4)
    y = Y2
    yt, yb = y - 7.62, y + 7.62
    # The bridge as a ladder: cv on the left, tcb on the right, ay and bk between.
    sk.place("CR103", 24.13, yt, **H)
    sk.place("CR101", 39.37, yt, **H)
    sk.place("CR104", 24.13, yb, **H)
    sk.place("CR102", 39.37, yb, **H)
    sk.wire("CR103.2", "CR101.1")
    sk.wire("CR104.2", "CR102.1")
    sk.place("R136", 33.02, y)
    sk.wire((33.02, yt), "R136.1")
    sk.wire("R136.2", (None, yb))
    sk.offset = (0, 0)
    sk.wire("W12.1", (ox + 29.21, None), (None, ROW2 + yt))
    sk.wire("W12.2", (ox - 12.7, None), (None, ROW2 + y + 15.24), (ox + 29.21, None),
            (None, ROW2 + yb))  # fmt: skip
    sk.offset = (ox, ROW2)
    sk.label("ay", (12.7, y - 11.43))
    sk.label("bk", (12.7, y + 15.24))
    sk.place("Rleak", 7.62, y + 19.05)
    sk.wire("Rleak.2", (None, y + 22.86))
    sk.ground((None, None))
    # The Time Constant switch: S102 and S102_B from cv, each position's parts to tcb.
    sk.place("S102", 27.94, y + 30.48)
    sk.place("S102_B", 27.94, y + 57.15)
    rows1 = [("R141", 17.78), ("R138", 26.67), ("C113", 35.56), ("R140", 44.45)]
    rows2 = [("C111", 58.42), ("R139", 67.31), ("R137", 76.2), ("C109", 85.09)]
    for ref, yy in rows1 + rows2:
        sk.place(ref, 50.8, y + yy, **H)
    sk.place("C112", 63.5, y + 44.45, **H)
    sk.place("C110", 63.5, y + 67.31, **H)
    sk.wire("CR103.1", (None, y + 85.09), "C109.1")
    sk.wire((20.32, y + 76.2), "R137.1")
    sk.label("cv", (20.32, y + 72.39), "left")
    sk.wire("S102.1", (38.1, None), (None, y + 17.78), "R141.1")
    sk.wire("S102.2", "R138.1")
    sk.wire("S102.3", "S102.5")
    sk.wire("S102.5", (40.64, None), (None, y + 35.56), "C113.1")
    sk.wire("S102.6", (38.1, None), (None, y + 44.45), "R140.1")
    sk.wire("R140.2", "C112.1")
    sk.label("tc140", (57.15, y + 44.45))
    sk.wire("S102_B.4", "C111.1")
    sk.wire("S102_B.5", "S102_B.6")
    sk.wire("S102_B.6", (38.1, None), (None, y + 67.31), "R139.1")
    sk.wire("R139.2", "C110.1")
    sk.label("tc139", (57.15, y + 67.31))
    tb = 73.66  # the tcb bus
    sk.wire("CR101.2", (None, y + 12.7), (83.82, None), (None, y + 13.97))
    sk.wire((tb, y + 12.7), (None, y + 85.09))
    for ref in ("R141", "R138", "C113", "C111", "R137", "C109"):
        sk.wire(f"{ref}.2", (tb, None))
    for ref in ("C112", "C110"):
        sk.wire(f"{ref}.2", (tb, None))
    sk.label("tcb", (76.2, y + 12.7))
    # C115 and ZERO (R142: its wiper on tcb, its end on the bias rail nb3).
    sk.place("C115", 83.82, y + 17.78)
    sk.wire("C115.2", (None, y + 24.13))
    sk.ground((None, None))
    sk.place("R142", 83.82, y + 38.1, rot=180)  # nb3 up, ground down, wiper left
    sk.wire("R142.2", (tb, None))
    sk.wire("R142.3", (None, y + 31.75))
    sk.label("nb3", (None, None), "up")
    sk.wire("R142.1", (None, y + 44.45))
    sk.ground((None, None))


def power_supply(sk: Sketch) -> None:
    oy = ROW3
    at(sk, 0, oy)
    sk.frame("power supply", 0, oy, 213.36, 76.2)
    yp = 20.32
    # T302's HV winding as two mains sources (centre tap grounded), each through its
    # winding resistance and leakage to a GZ34 anode.
    for src, r, lk, cap, d, row, names in (
        ("VHVA", "RT302A", "LT302A", "CT302A", 1, yp - 10.16, ("hva", "hva_r", "rka")),
        ("VHVB", "RT302B", "LT302B", "CT302B", 2, yp + 10.16, ("hvb", "hvb_r", "rkb")),
    ):
        sk.place(src, 12.7, row + 5.08)
        sk.wire(f"{src}.2", (None, row + 12.7))
        sk.ground((None, None))
        sk.place(r, 22.86, row, **H)
        sk.place(lk, 35.56, row, **H)
        sk.place("V301", 58.42, row, rot=90, unit=d)
        sk.wire(f"{src}.1", f"{r}.1")
        sk.wire(f"{r}.2", f"{lk}.1")
        sk.wire(f"{lk}.2", "V301.1" if d == 1 else "V301.3")
        sk.place(cap, 44.45, row + (3.81 if d == 1 else -3.81), **({} if d == 1 else FLIP))
        sk.label(names[0], (15.24, row))
        sk.label(names[1], (27.94, row))
        sk.label(names[2], (40.64, row))
    sk.wire("CT302A.2", "CT302B.2")
    sk.ground((44.45, yp), "right")
    sk.wire("V301.2", (64.77, None), (None, yp + 10.16), "V301.4")
    # raw -> 4 uF, L301 (with its resistance) -> ur, the 140 uF pair with their 100k
    # equalizers.
    sk.place("C304", 67.31, yp + 3.81)
    sk.place("RL301", 77.47, yp, **H)
    sk.place("L301", 90.17, yp, **H)
    sk.wire((64.77, yp), "RL301.1")
    sk.label("raw", (69.85, yp))
    sk.wire("C304.2", (None, yp + 10.16))
    sk.ground((None, None))
    sk.wire("RL301.2", "L301.1")
    sk.label("l301", (83.82, yp))
    sk.place("C305", 99.06, yp + 3.81)
    sk.place("C306", 99.06, yp + 11.43)
    sk.place("R305", 109.22, yp + 3.81)
    sk.place("R306", 109.22, yp + 11.43)
    sk.wire("C305.2", "R305.2")
    sk.label("c305", (104.14, yp + 7.62))
    for p in ("C306.2", "R306.2"):
        sk.wire(p, (None, yp + 17.78))
        sk.ground((None, None))
    # The regulator: EL34 (as a triode) in series, the 6084 comparing B+ (through
    # R310 / R311 and the B+ ADJ pot) with the 5651's 87 V.
    xe = 139.7
    sk.place("R309", xe - 2.54, yp + 3.81)
    sk.place("V302", xe + 10.16, yp + 7.62)
    sk.wire("L301.2", "V302.1")
    sk.label("ur", (95.25, yp))
    sk.wire("R309.2", "V302.2")
    sk.place("V303", xe, yp + 25.4)
    sk.wire((xe, yp + 7.62), "V303.1")
    sk.label("eg", (xe, yp + 12.7), "left")
    sk.place("V304", xe, yp + 40.64)
    sk.wire("V303.4", "V304.1")
    sk.wire("V304.2", (None, yp + 48.26))
    sk.ground((None, None))
    sk.place("R310", xe + 15.24, yp + 20.32)
    sk.place("R311", xe + 15.24, yp + 27.94)
    sk.wire("V303.2", "R310.2")
    sk.label("es", (xe + 12.7, yp + 24.13))
    sk.wire("R311.2", (None, yp + 35.56), "V304.1")
    sk.label("ref", (xe + 7.62, yp + 35.56))
    sk.place("R312", xe - 17.78, yp + 19.05)
    sk.place("R313", xe - 17.78, yp + 26.67)
    sk.place("R314", xe - 17.78, yp + 34.29)
    sk.wire("R313.2", "V303.3")
    sk.label("eadj", (xe - 12.7, yp + 26.67))
    sk.label("adj_t", "R312.2")
    sk.label("adj_b", "R313.3")
    sk.wire("R312.1", (None, yp + 12.7))
    sk.label("bp", (None, None), "up")
    sk.wire("R314.2", (None, yp + 40.64))
    sk.ground((None, None))
    # B+ (bp) from the EL34's cathode: 80 uF, the screen divider (sg), the heaters'
    # elevation (hct).
    sk.wire("V302.3", (203.2, yp + 15.24))
    sk.wire("R310.1", (None, yp + 15.24))
    sk.label("bp", (203.2, yp + 15.24))
    sk.place("C307A", 165.1, yp + 19.05)
    sk.place("R315", 175.26, yp + 19.05)
    sk.place("R316", 175.26, yp + 26.67)
    sk.place("C307B", 185.42, yp + 26.67)
    sk.place("R307", 195.58, yp + 19.05)
    sk.place("R308", 195.58, yp + 26.67)
    sk.wire("R315.2", "C307B.1")
    sk.label("sg", (180.34, yp + 22.86))
    sk.label("hct", "R307.2")
    for p in ("C307A.2", "R316.2", "C307B.2", "R308.2"):
        sk.wire(p, (None, yp + 34.29))
        sk.ground((None, None))


def bias_supply(sk: Sketch) -> None:
    ox, oy = 220.98, ROW3
    at(sk, ox, oy)
    sk.frame("bias supply", ox, oy, 127, 55.88)
    yb = 30.48
    # T301's winding (a mains source) through its resistance and leakage into the
    # selenium bridge; its other end leaks to ground through 1 GOhm.
    sk.place("VBS", 12.7, yb)
    sk.place("RT301", 22.86, yb - 5.08, **H)
    sk.place("LT301", 35.56, yb - 5.08, **H)
    sk.place("GR301", 50.8, yb, rot=90, mirror=True)  # ac top / bottom, + left, - right
    sk.wire("VBS.1", "RT301.1")
    sk.wire("RT301.2", "LT301.1")
    sk.wire("LT301.2", "GR301.1")
    sk.wire("VBS.2", "GR301.2")
    sk.label("bs1", (15.24, yb - 5.08))
    sk.label("bs1_r", (27.94, yb - 5.08))
    sk.label("bsa", (41.91, yb - 5.08))
    sk.label("bsb", (35.56, yb + 5.08))
    sk.place("Rbsleak", 25.4, yb + 8.89)
    sk.wire("Rbsleak.2", (None, yb + 15.24))
    sk.ground((None, None))
    sk.wire("GR301.3", (43.18, None))
    sk.ground((None, None))
    # nb1 -> 250 uF, L302 -> nb2 (1000 uF); nb1 -> 1k -> nb3 (250 uF) -> 10k -> nb4.
    sk.place("C302", 60.96, yb + 3.81)
    sk.place("RL302", 73.66, yb, **H)
    sk.place("L302", 86.36, yb, **H)
    sk.place("C303", 95.25, yb + 3.81)
    sk.wire("GR301.4", "RL302.1")
    sk.label("nb1", (58.42, yb))
    sk.wire("RL302.2", "L302.1")
    sk.label("l302", (80.01, yb))
    sk.wire("L302.2", (102.87, None))
    sk.label("nb2", (102.87, yb))
    for p in ("C302.2", "C303.2"):
        sk.wire(p, (None, yb + 10.16))
        sk.ground((None, None))
    sk.place("R301", 74.93, yb - 20.32, **H)
    sk.place("C108B", 83.82, yb - 16.51)
    sk.place("R302", 93.98, yb - 20.32, **H)
    sk.place("C308", 102.87, yb - 16.51)
    sk.place("R303", 113.03, yb - 16.51)
    sk.wire((67.31, yb), (None, yb - 20.32), "R301.1")
    sk.wire("R301.2", "R302.1")
    sk.label("nb3", (86.36, yb - 20.32))
    sk.wire("R302.2", (120.65, None))
    sk.label("nb4", (120.65, yb - 20.32))
    for p in ("C108B.2", "C308.2", "R303.2"):
        sk.wire(p, (None, yb - 10.16))
        sk.ground((None, None))


def draw() -> Sketch:
    sk = Sketch(load_circuit(circuit_path("fairchild_670")))
    power_supply(sk)
    bias_supply(sk)
    channel_2(sk)
    input_section(sk)
    push_pull(sk)
    sidechain_input(sk)
    twelve_ax7(sk)
    twelve_bh7(sk)
    sixty_nine_73(sk)
    rectifier(sk)
    return sk


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="check the layout, save nothing")
    ap.add_argument("--check", action="store_true", help="compare the saved IR (all positions)")
    args = ap.parse_args()
    sk = draw()
    found = sk.problems()
    for p in found:
        print(p)
    if found:
        sys.exit(f"{len(found)} problems")
    if not args.dry_run:
        for p in save_circuit(sk.d, NAME, origin="scripts/draw_fairchild_670.py"):
            print("wrote", p)
    if args.check:
        check(sk)


def configs(spec) -> list[dict]:
    """Every Time Constant position, and drawn tolerances (spread 1, seed 7)."""
    from varimu.preflight import switch_configs

    return [*switch_configs(spec), {"passive_spread": 1.0, "passive_seed": 7}]


def check(sk: Sketch) -> None:
    from varimu.circuit import builder
    from varimu.circuit.spec import resolve
    from varimu.editor.compile import check_drawing, compiled_spec
    from varimu.kicad.compare import ir_differences

    c, found = check_drawing(sk.d)
    assert c.ok and not found, [m.message for m in found]
    a, b = load_circuit(circuit_path("fairchild_670")), compiled_spec(c)
    n = 0
    for ov in configs(a):
        for cores in ("linear", "ja"):
            diff = ir_differences(builder.build_ir(a, resolve(a, ov), cores),
                                  builder.build_ir(b, resolve(b, ov), cores))  # fmt: skip
            assert not diff, (ov, cores, diff)
            n += 1
    print(f"same IR at {n} configurations (both core models)")


if __name__ == "__main__":
    main()

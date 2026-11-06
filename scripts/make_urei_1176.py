"""The UREI 1176LN, a D / E-era unit (DEVICE_BUILDER_PLAN.md B12; DEVICE_CANDIDATES.md
"Next: dynamics and EQ"), from the drawings in data/schematics/urei_1176/ (README.md there
transcribes them).

    uv run python scripts/make_urei_1176.py [--check]

writes config/circuits/urei_1176.yaml (GENERATED: never edit it by hand); --check exits 1
when it would change.

Sources (`ua:` UA's reissue manual, rev 1.02, which says "we patterned our reproduction on
the D/E versions"; `schA:` UA drawing R-10743 rev A; `schF:` UREI drawing R11914, Rev F):
- the input: the INPUT "T" attenuator (620 ohm arms) and T1, the UTC O-12, loaded by 270
  ohm (schA: R4, schF: R5);
- the gain-reduction stage and the signal preamp: ua: Figure 3 (the LN circuit; its part
  numbers are used here), Q1 the VVR FET, Q2 / Q3 / Q14 the preamp, R23 the OUTPUT pot;
- the gain-reduction control circuit: ua: Figure 5 (values; its part numbers), wired as
  schF's GR CONTROL AMP draws it. Figure 5 is drafted loosely: it labels two resistors R46
  (the 1k rail decoupler and the 47k feedback, here R46A / R46B) and returns the 50 uF
  decoupler (its C20) to the R49 / R50 junction, where schF (C18) returns it to ground.
  schF's values differ in places (R70 4.7K for Fig 5's 1k decoupler, R69 44.2K 1 % for
  R47 47k, a different signal deck); Fig 5's are used, the D / E circuit;
- the line amp: schA's SIGNAL LINE AMP (Q4, Q5 2N3707, Q6 2N3053, T2 UA-5002 with its
  emitter and feedback windings; part names suffixed A). The manual (p. 9) says D / E kept
  this class-A 2N3053 stage. Rev B's drawing (the "series D" file) shows Q4 as a 2N3391A,
  but its values aren't legible, so Rev A's FET stage stands in (the same FET as Q1).
  T2's wiring as read from schA (page 2): the collector winding BRN-BLK from Q6's
  collector to +30 V; the emitter winding WHT/BLK-WHT/RED from Q6's emitter through R32
  to ground; the output BLU-RED (YEL-ORG strapped); SLT-VIO a feedback winding (VIO
  grounded) back through R54 || C16 to Q4's source, with R35 + C15 from the collector to
  it. The polarities are chosen so both the emitter winding and the feedback winding feed
  back negatively (schA doesn't mark them).

Factory-selected ("T+C") and trimmed values, set the way the factory did
(scripts/urei_1176_trim.py; its numbers are in the values' sources):
- R83 (Fig 5's "T&C" in series with the Q-bias pot R59): the E24 value that puts the
  Q-bias setting found by the manual's procedure nearest the pot's mid-rotation;
- R59 ("Q" BIAS ADJ.): the manual's procedure (p. 5), which "sets the compression
  threshold": a 1 kHz sine, INPUT and OUTPUT for 0 dB on the +4 meter (+4 dBm out), R59
  fully CCW, then R59 turned CW until the output drops 1.0 dB. The manual doesn't say how
  INPUT and OUTPUT share the gain; here +4 dBu in with the two splitting the 45 dB equally
  (the panel's matched unity setting), 4:1, ATTACK and RELEASE mid. Read with gain
  reduction disabled, or with OUTPUT fully CW (the side chain then never reaches its
  diodes' bias), the procedure parks the FET 1 dB into conduction with no signal, where
  the LN drive swings it through pinch-off each cycle: ~2 % 2nd harmonic below threshold,
  against the manual's 0.5 %;
- R86 (Fig 3's 100 ohm variable): how much of the preamp's feedback node reaches Q1's
  gate through C9 / R6, the LN circuit's distortion null: set for the least THD at 10 dB
  of gain reduction (1 kHz, 4:1, slowest release);
- Rev A's R30 (Q5's base bias, "120K* (T+C)", it sets Q6's class-A current): the printed
  nominal, which meets the manual's +22 dBm at 0.5 % THD;
- the ratio decks' "T&C" resistors at the 20:1 contacts: on the bias deck it is where schF
  (Rev E on) has R46 10M, the anti-pop resistor the manual's footnote describes (used);
  on the signal deck (schF's "UA4706 T+C *") no value or criterion is known, so it is
  left out (open).

Provisional: the VVR FET (a 2N5457, repairers' stand-in for the selected "UREI 13-0027":
onsemi's Figure 3 unit, `2N5457@2`, which the Q-bias range reaches; Q4, not selected, on
Central's card, `2N5457@1`), the preamp's transistors (Fig 3 doesn't name them; schF's
2N3391A has no model, so 2N3707@1), the diodes (FD333 / 1N914 as 1N4148@1), both
transformers (no winding data published: README.md "Transformers"), the pots' tapers.

Left out: the GR meter driver (Q11-Q13 / Rev F's IC1: the meter only), the stereo link
(J1 on the GR line), the power supply (ideal +30 V and -10 V rails: the original's are
zener-regulated, CR8 30 V 10 W / CR9 10 V), the signal deck's T&C (above).
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "circuits" / "urei_1176.yaml"
UA = "ua"  # data/schematics/urei_1176/ua_1176ln_reissue_manual_rev1.02.pdf
SCHA = "schA"  # data/schematics/urei_1176/waltzingbear/Urei_1176_page_{1,2}.JPG (R-10743)
SCHF = "schF"  # data/schematics/urei_1176/waltzingbear/Urei_1176LN_series_F_page_*.JPG
TRIM = "scripts/urei_1176_trim.py"

# The factory trims (scripts/urei_1176_trim.py, rerun after a change that moves them).
T2_FB_RATIO = 0.6838
R83_OHM = 0.0
Q_BIAS_AT = 0.5406
R86_AT = 0.419


def q(s: str) -> str:
    return '"' + s.replace('"', "'") + '"'


def _fmt(x: float) -> str:
    if x == 0 or 1e-3 <= abs(x) < 1e4:
        return repr(float(x))
    return f"{x:.6e}".replace("e+0", "e+").replace("e-0", "e-")


def flow(d: dict) -> str:
    def v(x):
        if isinstance(x, list):
            return "[" + ", ".join(v(y) for y in x) + "]"
        if isinstance(x, dict):
            return flow(x)
        if isinstance(x, str) and x == "0":
            return '"0"'
        return str(x)

    return "{" + ", ".join(f"{k}: {v(x)}" for k, x in d.items()) + "}"


def val(key: str, x: float | str, src: str) -> str:
    x = _fmt(x) if isinstance(x, float) else x
    return f"  {key}: {{value: {x}, source: {q(src)}}}"


# --- values ------------------------------------------------------------------------------


def values() -> list[str]:
    v: list[tuple[str, float | str, str]] = []

    def add(k, x, s):
        v.append((k, x, s))

    f3, f5 = f"{UA}: Figure 3", f"{UA}: Figure 5"
    # Rails.
    add("rail_30_v", 30.0, f"{SCHF}: '+30V @ 50mA' ({SCHA} the same; ideal: provisional, "
        "the original's is a 30 V 10 W zener, CR8 1N2989A, after R80 / R84)")  # fmt: skip
    add("rail_10_v", 10.0, f"{SCHF}: '-10V' (CR6 1N4740 10 V; ideal: provisional)")
    # Input.
    add("attenuator_z_ohm", 600.0, f"{SCHF} / {SCHA}: the 'T' attenuator's R2 / R3 620 ohm "
        "arms (a bridged T, R1A / R1B unprinted: the builder's constant-impedance T stands "
        f"in, the same terminated behaviour); {UA} p. 1: input impedance 600 ohm")  # fmt: skip
    add("r_t1_load_ohm", 270.0, f"{SCHA}: R4 270 / {SCHF}: R5 270, across T1's secondary")
    add("t1_core_material", "mumetall", "provisional: model knowledge (UTC's Ouncers: "
        "nickel-alloy cores; as config/circuits/ua_610.yaml's O-1)")  # fmt: skip
    add("t1_core_area_m2", 3.6e-5, "provisional: model knowledge (the Ouncer's core, as "
        "ua_610.yaml's O-1: a 1/4 in tongue and stack)")  # fmt: skip
    add("t1_core_path_m", 0.036, "provisional: model knowledge (~5.6 x the 1/4 in tongue)")
    add("t1_gap_m", 2.5e-6, "provisional: model knowledge (an interleaved nickel-alloy "
        "core's joint gap, ua_610.yaml's O-1)")  # fmt: skip
    add("t1_turns", 925.0, "derived: a 500 ohm primary at +8 dBm (2.51 V peak) and 30 Hz "
        "at a provisional 0.4 T peak in the provisional core (the O-1's rating, "
        "ua_610.yaml)")  # fmt: skip
    add("t1_sec_ratio", 0.6325, "derived: sqrt(200 / 500) (web: "
        "https://www.sowter.co.uk/specs/1260.php, Sowter's O-12 replacement '1:1.58 200/500 "
        "Ohms', wired 500:200 so the 270 ohm load reflects to ~675 ohm, the 600 ohm input "
        f"of {UA} p. 1)")  # fmt: skip
    add("t1_r_pri_ohm", 52.0, "provisional: model knowledge (a 500 ohm Ouncer winding, "
        "the O-1's 52 ohm: ua_610.yaml)")  # fmt: skip
    add("t1_r_sec_ohm", 33.0, "provisional: model knowledge (the 200 ohm side, 0.63 of the "
        "turns of the same wire)")  # fmt: skip
    add("t1_leakage_h", 1.0e-3, "provisional: model knowledge (an interleaved line "
        "transformer, referred to the primary: ~100 kHz with the 600 ohm source)")  # fmt: skip
    add("t1_c_sec_f", 50.0e-12, "provisional: model knowledge (a 200 ohm winding's "
        "self-capacitance)")  # fmt: skip
    # Gain-reduction stage (Figure 3).
    for k, x, s in (
        ("r5_ohm", 27.0e3, "R5 27k (with Q1 the gain-reduction divider)"),
        ("r10_ohm", 10.0e3, "R10 10k (Q1's source to ground)"),
        ("c28_f", 50.0e-6, "C28 50uF 6.4V (Q1's source to R18 / R84: the LN feedback)"),
        ("r6_ohm", 2.2e6, "R6 2.2M (gate from the preamp's feedback node)"),
        ("c3_f", 200.0e-12, "C3 200pF across R6"),
        ("c9_f", 0.22e-6, "C9 .22"),
        ("r7_ohm", 2.2e6, "R7 2.2M (gate from the GR line)"),
        ("c6_f", 200.0e-12, "C6 200pF across R7"),
        ("c22_f", 0.22e-6, "C22 .22 (the GR line's timing capacitor)"),
        # Signal preamp.
        ("c1_f", 1.0e-6, "C1 1uF"),
        ("r8_ohm", 1.0e3, "R8 1k"),
        ("c2_f", 27.0e-12, "C2 27pF"),
        ("r9_ohm", 560.0e3, "R9 560k (Q2's base bias from Q3's emitter)"),
        ("r13_ohm", 1.0e6, "R13 1M (Q2's collector)"),
        ("r17_ohm", 6.8e3, "R17 6.8k (the preamp's rail decoupler)"),
        ("c4_f", 80.0e-6, "C4 80uF 25V"),
        ("r14_ohm", 22.0e3, "R14 22k (Q3's collector)"),
        ("r18_ohm", 180.0, "R18 180"),
        ("r84_ohm", 180.0, "R84 180"),
        ("r85_ohm", 150.0, "R85 150"),
        ("r86_ohm", 100.0, "R86 100 (variable)"),
        ("r11_ohm", 82.0, "R11 82"),
        ("r12_ohm", 1.0e3, "R12 1k"),
        ("c5_f", 80.0e-6, "C5 80uF"),
        ("r30_ohm", 6.8e3, "R30 6.8k (the preamp's feedback)"),
        ("c7_f", 1.0e-6, "C7 1uF 40V"),
        ("r88_ohm", 68.0e3, "R88 68k (R23's wiper to ground)"),
    ):
        add(k, x, f"{f3}: {s}")
    add("r23_ohm", 100.0e3, f"{SCHF}: R27 100K 2W OUTPUT GAIN ({UA}'s Figure 3 prints R23 "
        "10k: with C7 1uF that is 18 Hz, against the manual's +-1 dB at 20 Hz, and R88 68k "
        "from the wiper shapes a 100K track's law, not a 10k's; read as a misprint)")  # fmt: skip
    # Line amp (Rev A).
    for k, x, s in (
        ("c8a_f", 0.15e-6, "C8 .15"),
        ("r24a_ohm", 15.0e6, "R24 15M (Q4's drain to gate)"),
        ("r25a_ohm", 3.3e6, "R25 3.3M (Q4's gate to ground; read as 3.3M (?), README.md)"),
        ("r26a_ohm", 33.0e3, "R26 33K (Q4's drain)"),
        ("r27a_ohm", 12.0e3, "R27 12K"),
        ("r28a_ohm", 560.0, "R28 560"),
        ("c9a_f", 6.4e-6, "C9 6.4uF 40V (across R27)"),
        ("c10a_f", 1.0e-6, "C10 1uF 40V"),
        ("r29a_ohm", 1.2e6, "R29 1.2M (Q6's collector to Q5's base)"),
        ("c11a_f", 47.0e-12, "C11 47pF across R29"),
        ("r38a_ohm", 8.2e3, "R38 8.2K (the line amp's rail decoupler)"),
        ("c12a_f", 80.0e-6, "C12 80uF 25V"),
        ("c14a_f", 0.033e-6, "C14 .033 (Q6's emitter to ground)"),
        ("r32a_ohm", 39.0, "R32 39 (read as 39 (?), README.md; the emitter winding's foot)"),
        ("r35a_ohm", 560.0, "R35 560 (with C15 from Q6's collector to SLT)"),
        ("c15a_f", 0.0047e-6, "C15 .0047"),
        ("r54a_ohm", 8.2e3, "R54 8.2K (SLT to Q4's source network)"),
        ("c16a_f", 35.0e-12, "C16 35pF across R54"),
    ):
        add(k, x, f"{SCHA}: {s}")
    add("r30a_ohm", 120.0e3, f"{SCHA}: R30 '120K* (T+C)', the printed nominal: Q6 idles at "
        "~26 mA and the unit makes +23.3 dBm at 0.5 % THD, 1 kHz (the manual's +22 dBm), so "
        "no other selection is called for")  # fmt: skip
    add("load_ohm", 600.0, f"{UA} p. 1: output load impedance 600 ohm")
    # T2 (UA-5002): no winding data; a provisional design from Q6's operating point.
    t2 = (
        "provisional: model knowledge (UA-5002, no winding data published; designed for "
        f"Q6's ~26 mA class A at +30 V and +22 dBm into 600 ohm, {UA} p. 1)"
    )
    add("t2_core_material", "grain_oriented_si_steel", t2.replace("(", "(a gapped steel "
        "core for the DC; ", 1))  # fmt: skip
    add("t2_core_area_m2", 1.532e-4, t2.replace("(", "(a 1/2 in tongue and stack; ", 1))
    add("t2_core_path_m", 0.076, t2.replace("(", "(~6 x the tongue; ", 1))
    add("t2_gap_m", 2.5e-4, t2.replace("(", "(B_dc ~0.3 T at Q6's ~26 mA in the collector "
        "and emitter windings; ", 1))  # fmt: skip
    add("t2_turns", 2000.0, t2.replace("(", "(the collector winding; ~0.6 T peak at 20 Hz "
        "with 25 V peak on it; ", 1))  # fmt: skip
    add("t2_emitter_ratio", 0.05, t2.replace("(", "(the emitter winding's turns re the "
        "collector winding's, Q6's local feedback: at 0.25 the line amp's loop gain was ~6 "
        "and its 2nd harmonic 0.75 % at +15 dBm; at 0.05, 0.5 % THD at +23.3 dBm, at 0.1 "
        "+21.2 dBm; ", 1))  # fmt: skip
    add("t2_out_ratio", 1.0, t2.replace("(", "(the output winding: 600 ohm reflects as ~660 "
        "ohm across collector and emitter windings, about the collector's ~25 V swing over "
        "Q6's current; ", 1))  # fmt: skip
    add("t2_fb_ratio", T2_FB_RATIO, f"derived: {UA} p. 1's gain, 45 dB ({TRIM}): the "
        "SLT-VIO feedback winding's turns re the collector winding's; "
        + t2[:-1].split("(", 1)[1])  # fmt: skip
    add("t2_r_pri_ohm", 80.0, t2.replace("(", "(the collector winding's DCR; ", 1))
    add("t2_r_emit_ohm", 15.0, t2.replace("(", "(the emitter winding's DCR; ", 1))
    add("t2_r_out_ohm", 80.0, t2.replace("(", "(the output winding's DCR; ", 1))
    add("t2_r_fb_ohm", 150.0, t2.replace("(", "(the feedback winding's DCR, finer wire; ", 1))
    add("t2_leakage_h", 3.0e-3, t2.replace("(", "(interleaved, referred to the collector "
        "winding; ", 1))  # fmt: skip
    add("t2_c_pri_f", 200.0e-12, t2.replace("(", "(the collector winding's "
        "self-capacitance; ", 1))  # fmt: skip
    # Ratio decks and the control amp (Figure 5).
    for k, x, s in (
        ("r6s_ohm", 1.0e3, "R6 1k (from the preamp's output; R6S here: Fig 3 has an R6)"),
        ("r19_ohm", 68.0e3, "R19 68k 1/4w"),
        ("r20_ohm", 56.0e3, "R20 56k 1/4w"),
        ("r21_ohm", 56.0e3, "R21 56k 1/4w"),
        ("r22_ohm", 47.0e3, "R22 47k 1/4w (to ground through U2's shield)"),
        ("r76_ohm", 150.0, "R76 150"),
        ("r75_ohm", 470.0, "R75 470 1/4w"),
        ("r73_ohm", 560.0, "R73 560 1/4w"),
        ("r68_ohm", 1.5e3, "R68 1.5k 1/4w"),
        ("r64_ohm", 1.5e3, "R64 1.5k (to -10 V)"),
        ("c17_f", 1.0e-6, "C17 1uF"),
        ("r36_ohm", 1.0e6, "R36 1M"),
        ("r37_ohm", 470.0e3, "R37 470k"),
        ("r38_ohm", 47.0e3, "R38 47k"),
        ("r39_ohm", 4.7e3, "R39 4.7k"),
        ("r40_ohm", 2.4e3, "R40 2.4k"),
        ("r41_ohm", 270.0, "R41 270"),
        ("r42_ohm", 180.0e3, "R42 180k"),
        ("r43_ohm", 38.3e3, "R43 38.3k"),
        ("r46a_ohm", 1.0e3, "R46 1k (the rail decoupler; schF's R70 is 4.7K)"),
        ("r46b_ohm", 47.0e3, "R46 47k (the feedback from Q10's emitter to Q7's)"),
        ("c20_f", 50.0e-6, "C20 50uf 50V (returned to ground as schF's C18)"),
        ("r47_ohm", 47.0e3, "R47 47k"),
        ("r48_ohm", 7.68e3, "R48 7.68k"),
        ("r49_ohm", 2.4e3, "R49 2.4k"),
        ("r50_ohm", 180.0, "R50 180"),
        ("c19_f", 6.8e-6, "C19 6.8uf 35V"),
        ("c23_f", 6.8e-6, "C23 6.8uf 35V"),
        ("r52_ohm", 47.0e3, "R52 47k"),
        ("r53_ohm", 47.0e3, "R53 47k"),
        ("c21_f", 80.0e-6, "C21 80uf 25V"),
        ("r54_ohm", 470.0, "R54 470 (Attack Time Control)"),
        ("c27_f", 0.022e-6, "C27 .022"),
        ("r55_ohm", 25.0e3, "R55 25k (ATTACK, F.P.)"),
        ("r56_ohm", 5.0e6, "R56 5M (RELEASE, F.P.)"),
        ("r57_ohm", 270.0e3, "R57 270k"),
        ("r59_ohm", 2.0e3, "R59 2k ('Q' Bias Adj., P.C.B.)"),
        ("r35_ohm", 10.0e3, "R35 10k (to -10 V)"),
        ("r60_ohm", 3.9e3, "R60 3.9k"),
    ):
        add(k, x, f"{f5}: {s}")
    jumper = " (0 ohm: a jumper, 1 mOhm here)" if R83_OHM == 0 else ""
    add("r83_ohm", R83_OHM or 1.0e-3, f"derived: {f5}: R83 'T&C', unprinted: the E24 value "
        f"or a jumper that puts the Q-bias setting nearest R59's mid-rotation ({TRIM})"
        + jumper)  # fmt: skip
    add("r_tc_bias_ohm", 10.0e6, f"{SCHF}: R46 10M, where {UA}'s Figure 5 draws the bias "
        "deck's 'T&C' (Rev E's anti-pop resistor, the manual's p. 9 footnote)")  # fmt: skip
    add("r_contact_ohm", 1.0e-3, "numerical: a closed switch contact")
    add("r_leak_ohm", 1.0e9, "numerical: a DC path for a node a switch leaves on "
        "capacitors or junctions only")  # fmt: skip
    return [val(k, x, s) for k, x, s in v]


# --- parts ------------------------------------------------------------------------------


def R(a, b, r, **kw):
    return {"R": [a, b], "r": r, **kw}


def C(a, b, c, **kw):
    return {"C": [a, b], "c": c, **kw}


def sections() -> list[tuple[str, dict[str, dict]]]:
    out: list[tuple[str, dict[str, dict]]] = []
    out.append(("rails", {
        "V30": {"V": ["p30", "0"], "v": "rail_30_v"},
        "V10": {"V": ["0", "m10"], "v": "rail_10_v"},
    }))  # fmt: skip
    out.append(("input", {
        "AT1": {"t_pad": ["in", "t1p", "0"], "z": "attenuator_z_ohm", "atten_db": "input_atten_db"},
        "T1": {"transformer": {
            "p": {"nodes": ["t1p", "0"], "r": "t1_r_pri_ohm"},
            "s": {"nodes": ["s1", "0"], "ratio": "t1_sec_ratio", "r": "t1_r_sec_ohm",
                  "c": "t1_c_sec_f"},
        }, "core": {"material": "t1_core_material", "area_m2": "t1_core_area_m2",
                    "path_m": "t1_core_path_m", "gap_m": "t1_gap_m"},
            "turns": "t1_turns", "leakage_h": "t1_leakage_h"},
        "R4": R("s1", "0", "r_t1_load_ohm"),
    }))  # fmt: skip
    out.append(("gain reduction", {
        "R5": R("s1", "dr", "r5_ohm"),
        "J1": {"jfet": ["dr", "g1", "qs"], "model": "QVVR"},
        "R10": R("qs", "0", "r10_ohm"),
        "C28": C("qs", "e2m", "c28_f"),
        "R7": R("gr", "g1", "r7_ohm"),
        "C6": C("gr", "g1", "c6_f"),
        "R6": R("g1", "n9", "r6_ohm"),
        "C3": C("g1", "n9", "c3_f"),
        "C9": C("n9", "fb", "c9_f"),
        "C22": C("gr", "0", "c22_f"),
    }))  # fmt: skip
    out.append(("preamp", {
        "C1": C("dr", "c1b", "c1_f"),
        "R8": R("c1b", "b2", "r8_ohm"),
        "C2": C("b2", "0", "c2_f"),
        "R9": R("b2", "e3m", "r9_ohm"),
        "R17": R("p30", "vd", "r17_ohm"),
        "C4": C("vd", "0", "c4_f"),
        "R13": R("vd", "c2", "r13_ohm"),
        "Q2": {"bjt": ["c2", "b2", "e2"], "model": "QPRE"},
        "R18": R("e2", "e2m", "r18_ohm"),
        "R84": R("e2m", "0", "r84_ohm"),
        "R85": R("e2", "r86n", "r85_ohm"),
        "R86": {"rheostat": ["r86n", "fb"], "r": "r86_ohm", "at": "ln_null"},
        "R14": R("vd", "c3", "r14_ohm"),
        "Q3": {"bjt": ["c3", "c2", "e3"], "model": "QPRE"},
        "R11": R("e3", "e3m", "r11_ohm"),
        "R12": R("e3m", "0", "r12_ohm"),
        "C5": C("e3m", "0", "c5_f"),
        "Q14": {"bjt": ["p30", "c3", "po"], "model": "QPRE"},
        "R30": R("po", "fb", "r30_ohm"),
        "C7": C("po", "op", "c7_f"),
        # A linear track: R88 from the wiper to ground bends its law toward an audio taper.
        "R23": {"pot": ["0", "ow", "op"], "r": "r23_ohm", "at": "output"},
        "R88": R("ow", "0", "r88_ohm"),
    }))  # fmt: skip
    out.append(("line amp", {
        "C8A": C("ow", "g4", "c8a_f"),
        "R24A": R("d4", "g4", "r24a_ohm"),
        "R25A": R("g4", "0", "r25a_ohm"),
        "R38A": R("p30", "vla", "r38a_ohm"),
        "C12A": C("vla", "0", "c12a_f"),
        "R26A": R("vla", "d4", "r26a_ohm"),
        "J4A": {"jfet": ["d4", "g4", "s4"], "model": "QLINE"},
        "R27A": R("s4", "s4m", "r27a_ohm"),
        "C9A": C("s4", "s4m", "c9a_f"),
        "R28A": R("s4m", "0", "r28a_ohm"),
        "R54A": R("fbw", "s4m", "r54a_ohm"),
        "C16A": C("fbw", "s4m", "c16a_f"),
        "C10A": C("d4", "b5", "c10a_f"),
        "R29A": R("c6", "b5", "r29a_ohm"),
        "C11A": C("c6", "b5", "c11a_f"),
        "R30A": R("b5", "r30n", "r30a_ohm"),
        "DCR1A": {"device": ["r30n", "0"], "model": "DSIG"},
        "Q5A": {"bjt": ["vla", "b5", "b6"], "model": "Q3707"},
        "Q6A": {"bjt": ["c6", "b6", "e6"], "model": "Q3053"},
        "RB6L": R("b6", "0", "r_leak_ohm", tolerance="none"),
        "C14A": C("e6", "0", "c14a_f"),
        "R32A": R("e6r", "0", "r32a_ohm"),
        "R35A": R("c6", "r35n", "r35a_ohm"),
        "C15A": C("r35n", "fbw", "c15a_f"),
        "T2": {"transformer": {
            "p": {"nodes": ["c6", "p30"], "r": "t2_r_pri_ohm", "c": "t2_c_pri_f"},
            "e": {"nodes": ["e6r", "e6"], "ratio": "t2_emitter_ratio", "r": "t2_r_emit_ohm"},
            "o": {"nodes": ["out", "0"], "ratio": "t2_out_ratio", "r": "t2_r_out_ohm"},
            "f": {"nodes": ["fbw", "0"], "ratio": "t2_fb_ratio", "r": "t2_r_fb_ohm"},
        }, "core": {"material": "t2_core_material", "area_m2": "t2_core_area_m2",
                    "path_m": "t2_core_path_m", "gap_m": "t2_gap_m"},
            "turns": "t2_turns", "leakage_h": "t2_leakage_h"},
        "RL": R("out", "0", "load_ohm", tolerance="none"),
    }))  # fmt: skip
    sig = {"R6S": R("op", "a4", "r6s_ohm"), "R19": R("a4", "a3", "r19_ohm"),
           "R20": R("a3", "a2", "r20_ohm"), "R21": R("a2", "a1", "r21_ohm"),
           "R22": R("a1", "0", "r22_ohm")}  # fmt: skip
    bias = {"R76": R("w", "t1", "r76_ohm"), "R75": R("t1", "t2", "r75_ohm"),
            "R73": R("t2", "t3", "r73_ohm"), "R68": R("t3", "t4", "r68_ohm"),
            "R64": R("t4", "m10", "r64_ohm"), "RTC": R("t4", "bs", "r_tc_bias_ohm")}  # fmt: skip
    contacts = {}
    for i, ratio in enumerate((4, 8, 12, 20), start=1):
        # Position 0 is "all buttons in": the four pushed at once, every contact of both
        # decks closed (the ladders shorted to their first taps).
        pos = {"tolerance": "none", "in": [ratio, 0]}
        contacts[f"RS{i}A"] = R(f"a{i}", "scc", "r_contact_ohm", **pos)
        contacts[f"RS{i}B"] = R(f"t{i}", "bs", "r_contact_ohm", **pos)
    out.append(("ratio switch", {
        **sig, **bias,
        "RATIO": {"switch": "ratio", "parts": contacts},
        "RSCL": R("scc", "0", "r_leak_ohm", tolerance="none"),
        # S1 (schF's S9), GR DISABLE, on the ATTACK pot: off grounds C17's input.
        "GRSW": {"switch": "attack_off", "parts": {
            "RS1N": R("scc", "sci", "r_contact_ohm", tolerance="none", **{"in": [0]}),
            "RS1D": R("sci", "0", "r_contact_ohm", tolerance="none", **{"in": [1]}),
        }},
    }))  # fmt: skip
    out.append(("control amp", {
        "R46A": R("p30", "vg", "r46a_ohm"),
        "C20": C("vg", "0", "c20_f"),
        "C17": C("sci", "b7", "c17_f"),
        "R36": R("c7", "b7", "r36_ohm"),
        "R37": R("b7", "0", "r37_ohm"),
        "R38": R("vg", "c7", "r38_ohm"),
        "Q7": {"bjt": ["c7", "b7", "e7"], "model": "Q3707"},
        "R39": R("e7", "e8m", "r39_ohm"),
        "R46B": R("e10", "e7", "r46b_ohm"),
        "Q8": {"bjt": ["p30", "c7", "e8"], "model": "Q3707"},
        "R40": R("e8", "e8m", "r40_ohm"),
        "R41": R("e8m", "0", "r41_ohm"),
        "R42": R("e8", "b9", "r42_ohm"),
        "R43": R("b9", "e10m", "r43_ohm"),
        "R47": R("vg", "c9", "r47_ohm"),
        "Q9": {"bjt": ["c9", "b9", "e9"], "model": "Q3707"},
        "R48": R("e9", "e10m", "r48_ohm"),
        "Q10": {"bjt": ["p30", "c9", "e10"], "model": "Q3707"},
        "R49": R("e10", "e10m", "r49_ohm"),
        "R50": R("e10m", "0", "r50_ohm"),
    }))  # fmt: skip
    out.append(("detector", {
        "C19": C("e10", "k2a", "c19_f"),
        "C23": C("e8", "k3a", "c23_f"),
        "R52": R("k2a", "bs", "r52_ohm"),
        "R53": R("k3a", "bs", "r53_ohm"),
        "C21": C("0", "bs", "c21_f"),
        "DCR2": {"device": ["k2a", "att"], "model": "DSIG"},
        "DCR3": {"device": ["k3a", "att"], "model": "DSIG"},
        # ATTACK: R55 from the rectifiers to the GR line, R54 || C27 to its wiper (CW =
        # the wiper at the GR line's end = fastest).
        "R55": {"pot": ["att", "aw", "gr"], "r": "r55_ohm", "at": "attack"},
        "R54": R("att", "aw", "r54_ohm"),
        "C27": C("att", "aw", "c27_f"),
        # RELEASE: R56 from the GR line to the Q-bias wiper, R57 from its wiper to that end
        # (CW = the wiper at the GR line's end = fastest).
        "R56": {"pot": ["w", "rw", "gr"], "r": "r56_ohm", "at": "release"},
        "R57": R("rw", "w", "r57_ohm"),
        # Q bias: -10 V, R35, the node nq with R60 to ground; R59 from nq to R83 to ground
        # (CCW = the wiper at nq = the most negative gate).
        "R35": R("m10", "nq", "r35_ohm"),
        "R60": R("nq", "0", "r60_ohm"),
        "R59": {"pot": ["nq", "w", "r83n"], "r": "r59_ohm", "at": "q_bias"},
        "R83": R("r83n", "0", "r83_ohm"),
    }))  # fmt: skip
    return out


def text() -> str:
    lines = [
        "# GENERATED by scripts/make_urei_1176.py: never edit by hand (rerun it).",
        "#",
        "# The UREI 1176LN, a D / E-era unit (DEVICE_BUILDER_PLAN.md B12): UA's reissue",
        "# manual's Figures 3 and 5 (the LN gain-reduction stage, the preamp, the control",
        "# circuit, wired as UREI's Rev F drawing R11914 draws it), Rev A's class-A line amp",
        "# (UA drawing R-10743), sources in data/schematics/urei_1176/ (README.md). The",
        "# factory's T+C parts and trims set as the factory did (scripts/urei_1176_trim.py).",
        "# What's provisional and what's left out, and why: the generator's docstring.",
        "",
        'title: "UREI 1176LN (D / E), FET limiter"',
        "input: in",
        "probes: [out, gr, w, bs, att, dr, g1, po, op, e8, e10, c6, e6, fbw, s4m, d4]",
        "# 0 dBFS in and out = +24 dBu peak (17.36 V), the studio line's headroom as the",
        "# V76's and 610's output; the 1176's +22 dBm maximum output fits under it.",
        "full_scale:",
        "  input_volts_peak: {value: 17.36, source: "
        + q(
            "derived: +24 dBu, x sqrt(2): a line input's headroom (as telefunken_v76.yaml's output)"
        )
        + "}",  # fmt: skip
        "  output_volts_peak: {value: 17.36, source: "
        + q(f"derived: +24 dBu, x sqrt(2): headroom over {UA} p. 1's +22 dBm maximum output")
        + "}",
        "",
        "controls:",
        "  input_atten_db: {value: 20.0, min: 0.0, max: 40.0, unit: dB, source: "
        + q(
            f"{SCHF} / {SCHA}: the INPUT 'T' attenuator (R1A / R1B, front panel); the range "
            "end is provisional: R1A / R1B's values aren't printed"
        )
        + ', notes: "0 = INPUT fully CW (no loss, the most gain reduction)"}',
        "  output: {value: 0.6, min: 0.0, max: 1.0, unit: rotation, source: "
        + q(f"{UA}: Figure 3, R23 OUTPUT (front panel)")
        + "}",
        "  attack: {value: 0.6, min: 0.0, max: 1.0, unit: rotation, source: "
        + q(f"{UA}: Figure 5, R55 25k ATTACK; p. 4: 20-800 us, fastest fully CW")
        + ', notes: "0 = CCW (R55 whole, slowest), 1 = CW (R55 || R54, fastest)"}',
        "  release: {value: 0.5, min: 0.0, max: 1.0, unit: rotation, source: "
        + q(f"{UA}: Figure 5, R56 5M RELEASE; p. 4: 50-1100 ms, fastest fully CW")
        + ', notes: "0 = CCW (5M, ~1.1 s), 1 = CW (5M || 270k, ~55 ms)"}',
        "  ratio: {value: 4, choices: [4, 8, 12, 20, 0], unit: ratio, source: "
        + q(f"{UA}: Figure 5, S1-S4 (front-panel push buttons, interlocked)")
        + ', notes: "0 = all buttons in (all four pushed at once: every contact closed)"}',
        "  attack_off: {value: 0, choices: [0, 1], unit: switch, source: "
        + q(
            f"{UA}: Figure 5, S1 / {SCHF}: S9 'G.R. DISABLE SWITCH LOCATED ON R77' (the "
            "ATTACK pot's fully-CCW detent)"
        )
        + ', notes: "1 = gain reduction off (C17 grounded)"}',
        "  q_bias: {value: "
        + _fmt(Q_BIAS_AT)
        + ", min: 0.0, max: 1.0, unit: rotation, source: "
        + q(
            f"derived: {UA}: Figure 5, R59 'Q' BIAS ADJ. (P.C.B.), set by p. 5's procedure ({TRIM})"
        )
        + ', notes: "0 = CCW (the gate most negative, no gain reduction)"}',
        "  ln_null: {value: "
        + _fmt(R86_AT)
        + ", min: 0.0, max: 1.0, unit: rotation, source: "
        + q(
            f"derived: {UA}: Figure 3, R86 100 ohm variable: the least THD at 10 dB of "
            f"gain reduction ({TRIM})"
        )
        + ', notes: "the fraction of R86 in circuit"}',
        "",
        "values:",
        *values(),
        "",
        "devices:",
        "  QVVR: {device: 2N5457@2, source: "
        + q(
            "provisional: model knowledge (Q1 'UREI 13-0027' (schF), 'selected' (schA's "
            "notes); repairers fit 2N5457 / 2N5458, data/schematics/urei_1176/README.md). "
            "2N5457@2 is onsemi's sheet's Figure 3 unit (VGS(off) ~-1.2 V): a 2N5457 the "
            "Q-bias network can bias off (the sheet's typical part, ~-3 V, it can't), as "
            "selecting it would ensure"
        )
        + "}",
        "  QLINE: {device: 2N5457@1, source: "
        + q(
            "provisional: model knowledge (schA's Q4, the line amp's FET, the same house "
            "label as Q1 but not selected: a 2N5457 near the sheet's typical IDSS, Central's "
            "card's 3.5 mA; on onsemi's 1.05 mA unit the line amp makes +21.2 dBm at 0.5 % "
            "THD, on this one +23.1)"
        )
        + "}",
        "  QPRE: {device: 2N3707@1, source: "
        + q(
            f"provisional: model knowledge ({UA}'s Figure 3 doesn't name Q2 / Q3 / Q14; "
            f"{SCHF}'s 2N3391A has no model: a 2N3707, schA's preamp transistor)"
        )
        + "}",
        "  Q3707: {device: 2N3707@1, source: "
        + q(f"{UA}: Figure 5, Q7-Q10 2N3707; {SCHA}: Q5 2N3707")
        + "}",
        "  Q3053: {device: 2N3053@1, source: " + q(f"{SCHA}: Q6 '2N3053 or 2N2270'") + "}",
        "  DSIG: {device: 1N4148@1, source: "
        + q(
            f"provisional: model knowledge ({SCHA}: CR1 1N914, CR2 / CR3 FD333; the 1N914 "
            "is the 1N4148's die, the FD333 a low-leakage signal diode)"
        )
        + "}",
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

# Minimoog Model D: sources

Status 2026-11-07: sources found and the filter board read; nothing built yet. Plan:
[docs/MINIMOOG_PLAN.md](../../../docs/MINIMOOG_PLAN.md). Scans are not committed (copyright): fetch them from the
URLs below into `cache/` or a scratch folder.

## Primary: the service manual with schematics (open)

- Internet Archive, "SERVICE MANUAL for MINIMOOG Model 204D" (46 pages, scanned; the OCR text layer is too noisy
  for values, read the page images):
  `https://archive.org/download/JL11387/Minimoog%20Service%20Manual_text.pdf`
- PDF page -> figure: 3 oscillator board No. 1 assembly (serial 10175 and above, Fig 9-1), 4 its schematic
  (Fig 9-2), 5 the board below serial 10175 (Fig 9-3), 7 matching-transistor circuits (Fig 9-5), 9 contour
  generator and keyboard No. 2 (Fig 9-7), 10 power supply No. 3 (Fig 9-8), **13 filter board No. 4 (Fig 9-11:
  the ladder filter, the VCA, the A-440 reference, the external pre-amp, the overload lamp driver)**, 14
  left-hand controller (Fig 9-12), 15 rectifier No. 5, 16 octave buffer No. 6 (Fig 9-14).
- Other copies: Folkman's text-only "minimoog MODEL D TECHNICAL SERVICE MANUAL" (adjustment procedures, no
  schematics): `https://www.benmook.com/tech/documents/Schematics%202/Schematics%201/minimoog2.pdf`;
  Internet Archive "MINIMOOG D SCHEMATICS" (not fetched yet):
  `https://archive.org/details/moog_MINIMOOG-D_SCHEMATICS/MINIMOOG-D_SCHEMATICS`;
  the fold-out schematics as GIFs (not fetched yet):
  `http://www.fantasyjackpalance.com/fjp/sound/synth/synthdata/16-moog-minimoog.html`.
  manualmachine.com and lost-manuals.com return a login / HTML page, not the PDF.

## Filter board No. 4, circuit No. 6, the VCF (read from Fig 9-11, 2026-11-07)

Printed notes: resistors 1/4 W +-5 %, capacitors in uF; alternates TIS92 -> 2N3904, TIS93 -> 2N3906; **Q26 and
Q28 matched to +-3 mV at 20 mA**; C17 / C25 selected 600-1200 pF (the A-440 oscillator).

- **The ladder:** four stages of two **TIS97** NPN each (Q2/Q3, Q10/Q11, Q19/Q20, Q23/Q24), a **0.068 uF**
  capacitor between each pair's emitters (C3, C7, C11, C16); the input differential pair Q29/Q30 (TIS97,
  marked (M): matched) at the bottom. Collectors of Q2/Q3 at +10 V.
- **Base bias string** from +10 V: R4 220, R16 150, R32 150, R41 150, R52 150 to the Q29/Q30 bases' node, then
  R67 200 to ground with C24 220 uF across it (Table 7-8: R67 200 Ohm; R61 is the pre-amp's 200K). R54 470
  (Table 7-8; the drawing prints "410") feeds Q29's base.
- **Audio in:** pin 4 -> C27 10 uF -> Q29's base. **Feedback (EMPHASIS):** pin 6 -> R73 1K trim (REGEN CAL) ->
  R76 330 -> Q30's base.
- **Control current:** Q28 (TIS92) sinks the tail of Q29/Q30 through R60 680. Its base is driven by Q26 (TIS93,
  PNP; the complementary Vbe of the matched pair is the temperature compensation): the control node (pin 5)
  sums R74 47K (pin 16, AMOUNT OF CONTOUR), SCALE R49 500 ohm trim with R70 1.8K to ground, RANGE R39 10K trim from
  +10 V via R46 68K, C18 100 pF to ground; R45 330 in Q26's base lead.
- **Output amplifier:** the top stage's emitters via C5 0.22 / C1 0.22 into followers Q8 / Q6 (TIS97; R31 47K,
  R38 47K to ground), their emitters (R24 220K, R20 100K to -10 V) into the differential pair Q7 / Q5 (TIS97, tail
  R26 1K to -10 V); Q7's and Q8's collectors share R3 1K + R7 180 from a decoupled +10 V (R6 47, C9 100 uF); that
  node feeds the VCA through R2 82K (in series: see below); the R7 / R3 junction feeds EMPHASIS through C10 10 uF
  (pin 7). EMPHASIS (R14 on the panel, 50K rev. audio) is a rheostat between pins 7 and 6 (Fig 9-16: its
  terminal 1 unconnected).
- **The panel's pins** (Fig 9-16's connector CO4): 1 +10 V, 3 -10 V (BD5-3A), 4 the mixer (SW13), 5 the control
  node, 6 / 7 EMPHASIS, 9 the contour, 10 EXT. LOUDNESS (J3), 16 AMOUNT OF CONTOUR (a 5K linear pot: board 2's
  contour on one end, ground on the other).

## Filter board No. 4, circuit No. 7, the VCA (read 2026-11-07; values per Table 7-8)

- **Input:** the filter's output through R2 82K, then C6 0.33 into Q16's base; R34 820 to Q15's base, which
  R22 120 / R36 510 from the loads' chain hold (C15 220 uF): the filter arrives ~1/100 down.
- **1st stage:** Q16 / Q15 (TIS97), tail R35 1K into Q18 (TIS97), whose base takes the contour (pin 9) through
  R59 68K (emitter R37 6.8K to ground, R43 270K to -10 V); loads R19 / R23 100 on R14 (25 ohm trim, 1ST VCA BAL).
- **2nd stage:** Q14 / Q13 (TIS97) on the 1st's collectors, tail R33 470 into Q21 (TIS97), base from EXT.
  LOUDNESS (pin 10) through R51 33K (emitter R42 3.3K, R44 150K to -10 V); loads R18 / R21 330 on R12 (100 ohm
  trim, 2ND VCA BAL). J3 empty: pin 10 on +10 V through the panel's R56 (Fig 9-16, label faint: 33K read).
- **Loads' chain:** +10 V, R10 120 (C4 220 uF across it; Q1's base at its foot), R11 150 (R12's wiper), R13 120
  (R14's wiper and R22).
- **Output:** Q12 / Q17 (2N4058, PNP) on the 2nd's collectors (Q14 -> Q12, Q13 -> Q17), emitters R8 / R28 8.2 into
  Q1 (2N4058, R9 62 from +10 V); Q12's collector R30 680 to ground, Q17's R29 680 the output, CR2 (from ground)
  and CR1 (to +10 V) 1N458A clamps, C2 10 uF, R75 1K MAIN OUTPUT (pin 21), R77 1K headphone amp (pin 22).
- **A-440** (circuit No. 13, powered by pin 14): its output Q4's emitter (R5 22K) through R40 and C8 0.1 onto
  Q14's collector. R40: Table 7-8 2.2K (852-512222-001), the drawing 22K.
- Folkman's VCA Balance (p. 13) jumps filter-board point "A" to oscillator-board point "A" (the points' places
  are on component location drawings his copy lacks).

## Oscillator board No. 1, oscillator 1 (Fig 9-2, PDF page 4; read 2026-11-07 at ~1.25x, check the
## values against Table 7-4 before building)

- **Summer** IC1B (1/2 MC1458, inverting): inputs from the octave range (R20 121K 1%), OSC 1 SCALE (R16 10K trim
  via R17 90.9K 1%), OSC 1 OCT ADJ (R18 5K trim via R19 53.6K 1%), the primary summer (R15 402K 1%; N2 network
  949-042331-001: R12 82.5K, R13 69.8K, R15, R17, R19, R20, R21), OSC 1 SHIFT (R14 10K trim, R13 69.8K, R12 82.5K);
  feedback R21 50K 1%, R22 15K at the + input. Its output through R23 2.32K 1% onto R24 100 1% (C4 100 pF): the
  726's base, "0.00 mV @ 2' LO F = 350 Hz" (note 3), ~18 mV / octave there.
- **Expo converter** IC5, a uA726 (a matched pair on a die held at a set temperature: the drawing marks
  "T = 78.4 C"): Q7 the reference, its collector fed I_R = 5.0 uA from R30 2.0M 1%; IC6 (TL081, "OSC 1 CURRENT
  SOURCE") closes the loop on the common emitters (pins 10 / 13, ~-2.5 V) through R27 49.9K 1%, R28 100K, R29 1K,
  C8 .001; Q8's base grounded, its collector the oscillator's current I_c, "200 Hz / uA". C5 .01 decouples the
  726's heater supply (pins 8 / 4 from +10 V).
- **Core:** I_c from the capacitor node (C7 .001 uF; C6 1.5 uF / 20 V and R31 10K trim at the +5 V reference),
  the reset switch Q4, an E112 JFET (source to IC4A's +5 V, drain to the capacitor node); IC7 (TL081, C10 / C11 .01
  supply bypass) buffers the ramp (+1.75 V .. -1.75 V); IC8B (1/2 LM393, R34 1M, C12 18 pF, R35 100 ohm, pull-up
  R36 1K) compares it and, through C9 100 pF / R33 2K (a ~1 us pulse, "+10 .. -10, 1 us"), drives Q4's gate.
- **HI END COMP** IC4A (1/2 1458): R25 10K / R26 10K at its input, R32 100K and CR1 from the core (a correction
  for the reset's dead time at the top of the range).
- **Shapers:** the 2N3904 pair Q5 / Q6 (R40 10K, R41 10K, R42 10K, C13 500 pF; R43 8.25K, R44 4.99K into IC4B 1/2
  1458) makes the triangle; R37 5.6K / R38 4.02K the sawtooth output; IC8A (1/2 393; R39 1K, C14 .01, R45 / R47
  100K, R46 2.2M, R48 5.1K, R49 2.7K) the rectangle, its width from PW 1 IN (pin 22B: 0 V = square, -2.5 V = 15 %).
  Outputs at pins 10B (R135 220K, note 4), 9B, 20B, 21B.

## Oscillator board (notes from Fig 9-1)

Fig 9-1's notes: the expo converter's matched pair is a **uA726** (a temperature-regulated pair: the chip heats
itself to a set point; units between serials 11362 and 11794 with date codes 7850 / 7907 won't hold tune); R27,
R67, R105 selected for 20.5 mV +-0.4 mV per octave across pins 1 and 10 (49.9K, 75K or 100K); the rectangular
wave's duty cycle 50 % +-1 %; R59 deleted above serial 10175. Parts: 2N3904 / 2N3906, MC1458CP-1, TL081, LM393, 726.

## Revisions (MatrixSynth's change list after Brian Kehew; dates unverified)

R. A. Moog boards (about 100, the earliest, hard to tune); "older" oscillators (the first ~6000, 7 calibration
holes); "new" oscillators from serial 10175 (17 trim holes; the octave buffer, standard from ~5000).
`https://www.matrixsynth.com/2008/02/minimoog-change-list-minimoog-versions.html`
**The pick (proposed):** this manual's "new" oscillator board (10175 and above) and its filter board; the 2022
reissue keeps the 1970s signal path.

## Papers (behaviour to check the model against)

- Huovilainen, "Non-linear digital implementation of the Moog ladder filter", DAFx-04 (read: the circuit analysis,
  each stage's current as tanh of its differential voltage, the self-oscillation limit):
  `https://dafx.de/paper-archive/2004/P_061.PDF`
- Stilson and Smith, "Analyzing the Moog VCF with considerations for digital implementation", ICMC 1996 (no PDF
  found yet); Moog's patent US 3,475,623 (1969); Moog, AES 1965; Gallagher, "Analyzing the Moog filter" (All About
  Circuits, a worked ladder with values); Levien, `https://levien.com/ladder.pdf`.

## Gaps

- No TIS97 / TIS92 / TIS93 / 2N4058 datasheet fetched. The sheet names 2N3904 / 2N3906 as alternates for TIS92 /
  TIS93; the TIS97 is used as the 2N3904 until a sheet is found (provisional).
- Matching of the middle ladder pairs is unspecified (Norlin bulletin 804C, quoted secondhand on the Moog forum:
  only Q29/Q30 is marked matched).

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

## Contour generator and keyboard, board No. 2 (Fig 9-7, PDF page 9; read 2026-11-07, not yet built)

Parts values: Table 7-6 (PDF page 27). Rails: +9.3 V from the decoupling circuit (Q26 2N3415 / TIS92 alt 2N3904,
R62 330 from +10 V, R63 15 from +15 V), -10 V. Transistors 2N3392 (NPN; alt 2N3904), TIS93 (PNP; alt 2N3906).
The two contour sections are the same circuit (filter: Q1-Q8, Q21, Q22; loudness: Q25, Q15-Q19, Q2, Q3), read at
230 dpi in tiles (render the page with PyMuPDF and clip).

**One section (filter's names; loudness's in brackets):**
- Pair Q1 / Q4 [Q25 / Q15], both emitters grounded. Q1's collector node N_A runs to R5 3.3K [R40] and R6 560 [R41]
  from +9.3 V (the PNP Q5 [Q16] has its emitter on +9.3 V and its base on the R6 / R5 junction, collector through
  R7 100 [R42] to pin 14 [18], "TO ATTACK": the attack current source into the attack pot). Q1's collector, its base
  (wire to the dot), R3 10K [R38] to Q4's collector, which has R4 10K [R39] to +9.3 V. Q4's base: R14 33K [R56] from
  N_A, CR3 1N34A [CR6] from N_B, CR1 1N34A [CR8] from the trigger line through R35 10K [R36].
  **Open: a diode-connected Q1 (base wired to collector) pins N_A near 0.65 V and nothing could flip it, so either
  the base wire does not meet the collector at the dot (an Eccles-Jordan bistable, Q1's base fed by R3 from Q4's
  collector, state switched by C1 .01 / R26 10K from the trigger node and by CR3 from the output) or the drawing
  was misread. The bistable reading gives the right logic: Q1 on = Q5 on = attack, Q1 off = N_A high = decay.**
- N_A also drives follower Q6 [Q17], whose emitter (R8 10K [R43] to -10 V) feeds Q7 [Q18]'s base through R9 4.7K
  [R44]. Q7's collector = pin 13 [17] "TO DECAY" (the decay pot's end); its emitter E7 has R10 27K [R45] to +9.3 V,
  CR2 1N4004 [CR9] (anode E7) to pin 6 [15], "to pin 22 (trigger) thru LHC", and the emitter of PNP Q8 [Q19]: base on
  the SUSTAIN node (R13 4.7K to pin 12 [R57 to pin 16], R1 3K to ground and R17 150K to -10 V [R41 4.7K to ground]),
  collector R11 100 [R46] to ground: a clamp, E7 = sustain + 0.65 V.
- C5 10 uF [C2] is the envelope capacitor, on pin 10 [9] (the attack and decay pots' wipers); CR7 1N4004 [CR4], cathode to
  pin 2 [8] "TO DECAY SWITCH" (the release path); R48 10K [R16] into Q22 [Q3]'s base. The output stage: Q22 NPN
  with Q21 TIS93 [Q2, Q3 as an NPN pair with R15 560 on the collectors] a complementary pair onto the output node
  (pin 11 [7]), R50 560 [R15] from +9.3 V, C11 47 pF / C12 500 pF compensation. Output node to N_B through R33 5.6K
  [R24 6.8K]; N_B has R29 16.9K 1% [R27] to -10 V and CR3 [CR6] (anode N_B) to Q4's base: the peak detector,
  flipping at Vout of about 4 V (N_B > ~0.5 V).
- Trigger section: Q12 2N3392 (base from pin 21 / 22 "decay switch (V-TRIG)" and, through R49 220 + R19 10K, from pin 19
  EXT. S-TRIG; collector T1 pulled up by R32 10K and R23 3.3K, feeding both sections' C1 / R26 and C4 / R28);
  Q20 2N3392 (base from pin 20 KEYBOARD TRIG through R60 100K, CR10 1N34A, R55 47K, C1 .1 to ground; collector TL,
  R37 10K from +9.3 V, feeding R35 / CR1 and R36 / CR8). CR10's and CR1's orientations are not read with certainty.
- Panel pots (Table 7-3, listed in order): R9, R12, R13, R15, R16 are 1 Megohm audio (the attack / decay pots and
  glide); R17-R21 5K linear (sustain levels, amount of contour); R2 5 Megohm; R3, R6, R7, R8, R10 25K. Which is
  which is on Fig 9-16 (PDF page 18; 2994 x 1566 pt: render clips) and not yet traced.

**Keyboard circuit (circuit No. 1, same sheet, right half):** pitch bus 43 x 10 ohm 1% string from the +10 V bar, current
8.33 mA; the pitch bus into the Q23 / Q14 matched pair (2N3392, R58 6.2K, R51 560, R52 43K, R54 1.5K, R30 10K, R59
8.9K, R61 330) with PNP Q24 (2N4058), the sample-and-hold C9 .33 uF (R53 4.1M), glide: JFETs Q13 / Q10 (2N4303),
C6 1 uF (glide up), R64 100K, R21 10K, R31 22M, R2 330, CR5 1N4004, R65 5.1K, C13 .01, R34 100K; the current source
Q9 / Q11 (TIS93 / TIS92, matched PNP 10 to 20 mV under the NPN at 200 uA), R1 590, R20 1K, R22 1.1K 1%, R25 1K; output
R18 3.9K to -10 V at pins 4 / 5 (to the oscillators and filter). Not yet traced node by node.

### Fig 9-7 resolved with a sharper scan (2026-11-07)

The user found www.fantasyjackpalance.com's Minimoog page (http://www.fantasyjackpalance.com/fjp/sound/synth/synthdata/16-moog-minimoog.html;
WebFetch gets 403, `curl` with a browser User-Agent gets 200). It hosts the manual's schematics as GIFs in three
resolutions (`16-minimoog/000|001|002/907-cont-gen-key-schem.gif`; 002 is 4572 x 3084), also 906 (board layout), 912
(left controller), 916 (front panel wiring, Fig 9-16), 917 (interconnect wiring). Scratch copies in `cache/fjp/` (not committed).
Read there:
- **Q1 base is NOT tied to its collector.** Q1's base goes through R3 (10K) to Q4's collector node; the small dot at
  Q1 is a printing blot. Same for Q25 (R38 to Q15's collector, R40 3.3K on its collector). Both pairs are
  Eccles-Jordan flip-flops (the user's reading of Q25's missing dot, confirmed on the 002 scan).
- Q4's base (the pair's other input) joins R14 33K (up) and CR3 (to the peak-detector node); CR1 (points right,
  user and scan agree) joins R35 / R37 pull-ups to that same base node.
- **Trigger section:** CR10 points toward R60 (the user: "points left"; scan: cathode on the R60 side), so a
  positive voltage at pin 20 (keyboard trigger) charges C7 through R60 / R55 into Q20's base: Q20 (NPN) conducts when the
  key trigger goes HIGH. R19 10K / R49 220 from pin 19 (EXT. S-TRIG) feed Q12's base and Q20's collector line.

### The panel's contour wiring (Fig 9-17, the 002 scan's `917-interconnect-wiring.gif`; read 2026-11-07)

- Filter contour: ATTACK R12 (1 Meg audio) between 14B and 10B (the wipers' junction), DECAY R15 (1 Meg audio)
  between 13B and 10B (Fig 9-7's "to decay" pin is 13, not 18: 18 is the loudness attack). SUSTAIN R18 (5K): wiper
  to 12B, one end to ground, the other end's connection not legible; taken as +10 V like R19 (read literally, the
  filter's sustain node would have no positive source).
- Loudness contour: ATTACK R13 (1 Meg audio) 18B - 9B, DECAY R16 (1 Meg audio) 17B - 9B, SUSTAIN R19 (5K) from
  +10 V to ground, its wiper to 16B.
- AMOUNT OF CONTROL R17 (5K, printed "56"): one end to ground, the other on the filter contour (board 2's 11B), its
  wiper to board 4's pin 16 (R74). GLIDE R2 (5 Meg audio). EXT. S-TRIG jack SO-1 to 19B.

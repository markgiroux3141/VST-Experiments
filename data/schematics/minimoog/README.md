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
- **Core** (re-read 2026-11-09 from the 002 GIF at 2-3x and the Internet Archive scan's page 4; the 002 GIF's
  junction dots on the +5 V line at IC7's output and at node 2 are crossings: taken as joins, Q5's base and
  emitter would be one node and the triangle a constant, and the archive scan has no dot at IC7's output):
  IC4A (1/2 1458, the box "OSC 1 HI END COMP" printed beside it) follows R25 10K / R26 10K on +10 V: the +5 V
  reference (C6 1.5 uF / 20 V tantalum on its output), which is Q4's source, C7's top and R40's top (node 2,
  "+5V"). C7 .001 from it to D, Q4's drain (an E112 JFET). R31 10K trim (its wiper on the CW end) from D to the
  expo's collector line (I_c, "200Hz/uA"), which is IC7's + input: IC7 (TL081; C10 / C11 .01 bypass) drives Q5's
  base, Q5 (2N3904, collector on +10 V) its emitter, which is IC7's - input and the ramp (node 10: "+5V .. 0.0V",
  falling): the comparator sees the ramp I_c x R31 early, R31 x C7 (up to 10 us) of each period, which takes out
  the reset's dead time: R31 is the HI END trim. IC8B (1/2 LM393, open collector to -10 V): - input the ramp, +
  input R35 100 to ground with R34 1M || C12 18 pF from its output (hysteresis and a speed-up), output pin 7
  pulled up by R33 2K to +10 V ("+10 .. -10, .5 us"). Q4's gate: R32 100K to the +5 V reference, C9 100 pF and CR1
  (anode at the gate) to the comparator's output: between resets CR1 holds the gate at -9.4 V; the comparator's
  rising edge through C9 lifts it, Q4 shorts C7 back to +5 V, the ramp rises through IC7 and the comparator
  falls again.
- **Shapers:** saw: the ramp through R36 1K onto node 9, R37 5.6K to ground and R38 4.02K to -10 V: +1.76 ..
  -1.74 V (pins 10B through R135 220K, note 4, and 9B). Triangle: Q6 (2N3904) base on the ramp, R42 10K emitter
  to ground, R40 10K from the +5 V reference to its collector (node 1): 5.6 V - ramp until it saturates past mid-
  ramp, then the ramp less a drop: a V from ~+5 V down to "+2.75V" and back; R41 10K / C13 500 pF (to ground)
  into IC4B (1/2 1458; R44 4.99K feedback, R43 8.25K to +10 V: x1.6, -6 V): +-1.75 V at 21B. Rectangle: IC8A
  (1/2 393) + input node 11 (R39 1K from node 9, R46 2.2M from its output), - input PW / 2 (R47 100K from PW 1
  IN, 22B; R45 100K and C14 .01 to ground); its open collector through R48 5.1K onto R49 2.7K to ground: 0 /
  -3.5 V at 20B (0 V PW = square, -2.5 V = 15 %).
- **Summer inputs, re-read:** the primary summer's output (-1.00 V / oct) enters through SCALE (R16 10K trim +
  R17 90.9K), the RANGE line 14A (-571 mV / oct) through OCT ADJ (R18 5K trim + R19 53.6K), SHIFT from +10 V (R13
  69.8K + R14 10K trim); the network's R12 82.5K, R15 402K and R20 121K have open ends on oscillator 1. Fig 9-2's
  "+2.10V @ LO F" at the primary summer's output must read -2.10 V (its inputs at nominal sum to ~-2.3 V, and only
  a negative low F puts 2' near the printed 350 Hz). Note 3's "0.00 mV = 2' LO F = 350 Hz" at V01 doesn't fit
  I_R 5 uA at 200 Hz / uA (0 mV would be ~1 kHz): the trims set the tuning (scripts/minimoog_vco_trim.py).
- **The range ladder** (Fig 9-2, lower left): from -5 V, 1K 1% per octave (2', 4', 8', 16', 32'), 4.75K 1% to LO,
  909 ohm 1% on; each oscillator's RANGE switch picks a tap into its 741 buffer (osc 1's to 14A).
- **Folkman's oscillator tuning** (p. 12-13 of his TECHNICAL SERVICE MANUAL): on 2' the oscillator's "Range
  Trimpot" for 3520 Hz at the high A, its Scale Trimpot for 440 Hz at the low A, repeated; the Octave Range
  trimmer for 8' to beat with 2' on the second A. On this board: SHIFT R14, SCALE R16, OCT ADJ R18; HI END R31
  isn't in his text.

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

**Keyboard circuit (circuit No. 1, same sheet, right half):** read node by node on the 002 scan below
("The keyboard circuit, traced").

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

### The keyboard circuit, traced (Fig 9-7's right half on the 002 scan, Table 7-6; read 2026-11-07)

Built as `config/circuits/minimoog_keyboard.yaml` (docs/MINIMOOG_PLAN.md MM4).
- **The keyboard wiring diagram:** the 43-resistor string (all 10 ohm 1%) has its left end (the lowest key, F) on
  GROUND (PL-1 pin 3) and takes CURRENT IN (pin 9, from the board's pin 10) at its top; a key's pitch contact puts its
  tap on the N.O. pitch bar (pin 2, the board's pin 9), its trigger contact closes the TRIGGER BUS (pin 6) onto the
  +10 bar (pin 4). So the pitch is the lowest key's tap (two keys short the string between them) and the trigger is
  positive-going, +10 V.
- **Current source:** Q11 (TIS92) base on R20 1K / R22 1K 1% (+10 V to ground; Table 7-6: R20, R22 1K 1%, the
  earlier "1.1K" a misreading), emitter on R25 1K and C3 .1 to ground and on Q9's base; Q9 (TIS93) emitter through R1
  590 1% from +10 V, collector the 8.33 mA ("<- 8.33 ma" on pin 10). Fig 9-17 writes **8.48 mA** on the same wire;
  the circuit as built measures 8.437 mA.
- **S&H:** the pitch bar (pin 9) runs straight to C9 .33 (to ground) and Q23's base; R53 4.7M from +10 V to that node.
  Q23 / Q14 (2N3392, matched) share R52 43K to -10 V; Q23's collector R58 6.2K, Q14's R51 560 from +10 V; Q24 (2N4058,
  emitter on +10 V) has its base on Q23's collector, its collector on R59 3.9K (to +10 V), R54 1.5K (to -10 V) and R61
  330 to pin 8. **Q14's base meets only R30 10K** (a corner, no dot: zoomed); R30's other end is the output node.
- **Glide:** pin 8 (OUTPUT TO GLIDE) -> the panel's GLIDE R2 5M audio (Fig 9-17: between 7A and its wiper on 8A, the
  third lug open; both wires also run to the left-hand controller, whose GLIDE switch shorts them) -> pin 7 (INPUT FROM
  GLIDE) -> Q13's source (2N4303, "glide up"); Q13's drain on C6 1 uF (to ground) and R21 10K into Q10's gate (2N4303,
  "glide down"); Q10's drain R2 330 from +10 V, its source the output node (pins 4 / 5 to the oscillators and filter,
  R18 3.9K to -10 V at pin 3).
- **Q13's gate:** the trigger (pin 6) through R65 5.1K onto C13 .01 and R34 100K (both to -10 V); CR5 (1N4004) cathode
  on that node, anode on the junction of R64 100K (to Q13's gate) and R31 22M (to Q13's source).
- **Table 7-6 against the drawing:** R54's text reads 15K, its part number 852-512152 is 1.5K (the drawing's);
  R65's part number is also 852-512152 (1.5K), its text and the drawing 5.1K (Table 7-5's R178 shows 512512 = 5.1K, so
  the code is the slip); R25's part number reads 1.6K, text and drawing 1K. Two of three taken each time. C6 1 uF and C9
  0.33 uF polyester, C13 .01, C3 .1; Q10 / Q13 2N4303; Q14 / Q23 a matched 2N3392 set; Q9 / Q11 a matched TIS93 / TIS92
  set (alternates 2N3906 / 2N3904).
- Also on Fig 9-17: the filter's KEYBOARD CONTROL rockers SW16 (FILTER KBD 1/3) with R53 300K and SW17 (2/3) with R54
  150K, confirming MM1's inference; R55 200K and R51 100K (FILTER EXT CONTROL IN) beside them.


## Oscillators 2 and 3, the RANGE path, the mixer (read 2026-11-09 from the 002 GIFs 902, 914, 917, 901)

Scans: `curl` with a browser User-Agent from
http://www.fantasyjackpalance.com/fjp/sound/synth/synthdata/16-minimoog/002/ (902-osc-print-schem-above.gif,
901-osc-print-circ-1-above.gif, 914-oct-buff-schem-asm.gif, 917-interconnect-wiring.gif, 908-power-print-circ-schem.gif,
911-filt-print-circ-schem.gif) into `cache/sources/minimoog/`.

- **The three oscillators share the core, expo and shapers value for value** (Fig 9-2): C7 / C18 / C29 .001, HI END
  R31 / R71 / R109 10K, the reset JFET Q4 / Q9 / Q14 E112 with C9 / C20 / C31 100 pF, R32 / R72 / R110 100K, R33 /
  R73 / R111 2K, R34 / R74 / R112 1M, C12 / C23? / C34 18 pF, R35 / R75 / R113 100; I_R R30 / R70 / R108 2.0M; the
  triangle's R40 / R80 / R118 10K 1%, R41 / R81 / R119 10K, C13 / C24 / C35 500 pF. So oscillator 1's event tables
  serve all three.
- **What differs:** SHIFT's series resistor is R53 / R93 82.5K 1% on oscillators 2 / 3 (oscillator 1's R13
  69.8K); SCALE R55 / R91 10K + R56 / R94 90.9K, OCT ADJ R57 / R92 5K + R58 / R95 53.6K, feedback R59 / R99 50K,
  R62 / R100 15K, R63 / R101 2.32K, R64 / R102 100 (as oscillator 1's). OSC 2 / OSC 3 FREQUENCY: a 5K LIN pot from
  +10 V over 5.1K to ground ("7.5V +-2.5V, +-5TH") into R54 / R96 402K 1% (oscillator 1's R15 402K is that input,
  left open). Oscillator 3's R97 121K 1% takes OSC 3 CONTROL's 10A ("+-2.75 OCT"); R51 121K and R50 69.8K on
  oscillator 2 are spare network resistors with open ends.
- **OSC 3 CONTROL** (SW2; Fig 9-2 lower left, Fig 9-17): its first pole puts the OSC 3 FREQ wiper on 10A when OFF
  (open when ON); its second pole puts 16A on the board's -5 V when OFF, on -10 V (15A) when ON. 16A drives Q3
  (2N3904, base through R61 100K, emitter -10 V), whose collector holds Q2's gate (E101, an N-channel JFET; R60 1M
  gate to source), and Q19 (2N3904, base through R98 69.8K, emitter -10 V). Q2's source is on the primary summer's
  output (the line oscillator 2's SCALE hangs on: no dots at its crossings with the OCT ADJ and R54 lines), its
  drain oscillator 3's SCALE line, which Q19's collector also meets. ON: Q3 and Q19 off, Q2 on, the keys reach
  oscillator 3. OFF: Q3 shuts Q2, Q19 holds the SCALE line near -10 V: oscillator 3 no longer follows the keys.
- **REV SAW 3 OUT** (7B): Q20 2N3904 (emitter grounded), its collector on R124 2.2K's end of the +10 V decoupled by
  R123 330 / C37 5.6 uF 35 V tantalum, fed back to its base through R129 68K; the sawtooth (node 9) into the base
  through R130 33K, R128 390K to -10 V; the collector node divided by R133 7.5K / R134 18K (to -10 V) onto 7B. (The
  first reading put the collector on 7B: Q20 saturated. The 2x zoom shows the collector on the top line.)
- **Fig 9-1's notes:** note 3, R27 / R67 / R105 selected for 20.5 mV +-0.4 mV an octave across pins 1 and 10;
  **note 4, R135 / R136 / R137 (220K from +10 V onto each sawtooth's pin 10B / 8B / 13B) "factory selected (if
  necessary) to achieve 50 % +-1 % rect. duty cycle"**; note 5, R59 deleted above serial 10175.
- **The -5 V reference** (Fig 9-2, upper left): IC2 (741) + input on R9 / R10 4.99K 1% (ground / -10 V) with C3 27
  uF / 10 V tantalum, - input through R8 4.7K from 18A (the sense), output through R11 4.7K into Q1 (2N3906),
  emitter on 17A (the -5 V line), collector on -10 V: Q1 sinks the ladder's current.
- **The RANGE ladder** (on the front panel, Fig 9-17 / 9-2): from the -5 V line (2') R25 / R26 / R27 / R28 1K 1% to
  4', 8', 16', 32', then R29 4.75K 1% to LO, which is ground (pins 20A-22A); R59 90.9 ohm (LO to the -5 V line) deleted
  above serial 10175 (Fig 9-1 note 5, Fig 9-16's note). 571 mV an octave, 2' -5 V, LO 0 V. Each oscillator's RANGE
  switch (SW3 / SW4 / SW5) picks a tap.
- **The octave buffer** (board No. 6, Fig 9-14): three 741s as followers (pin 2 tied to 6): OSC 1's wiper (5) out on
  14A, OSC 2's (8) on 13A, OSC 3's (2) on 11A.
- **The waveform switches** (Fig 9-17): SW6 / SW7 / SW8, two poles, six positions. First pole: triangle, the second
  shape, sawtooth, then the rectangle (21B / 19B / 14B) on the last three. The second shape is the triangle-sawtooth
  mix on oscillators 1 and 2 (a node fed from the sawtooth through R30 / R36 47K and from the triangle through R31 /
  R37 10K) and REV SAW on oscillator 3. Second pole (PULSE WIDTH IN): ground on the first four, then the panel's
  divider from ground, R34 / R40 / R44 1.5K to -1.5 V (wide), R33 / R39 / R43 1K to -2.5 V (narrow), R32 / R38 / R42
  7.5K to -10 V.
- **The mixer** (Fig 9-17): each source onto a 25K LEVEL pot (R6 / R7 / R8 OSC 1-3, R10 NOISE; the wiper end to
  ground), the wiper through R45 / R47 / R49 33K (R48 11K for NOISE) into its ON / OFF switch (SW9 / SW11 / SW13,
  SW12 NOISE), ON onto the bus, board 4's pin 4 (C27 into the ladder). EXTERNAL INPUT: J6 onto R9 1 Meg audio, its
  wiper into board 4's pre-amp (pin 11), PREAMP OUT (pin 17) through R46 33K and SW10 onto the bus. SW14 picks WHITE
  (board 3's pin 5) or PINK (pin 6) for R10.
- **The external pre-amp** (board 4, circuit No. 12, Fig 9-11): pin 11, R78 1K, C23 .1 into Q27 (TIS97; R66 100K
  base to ground), Q27 / Q32 (TIS97) a pair on R58 150K to -10 V, Q27's collector R65 27K to +10 V (R64 100 + C22 100
  pF across it) into Q33's base (2N4058, emitter +10 V), its collector the output on R57 10K to -10 V; R61 200K from
  the output to R63 1K into Q32's base, R62 1K + C26 220 uF to ground at their junction, C21 10 pF base to output:
  +46 dB at audio, unity at DC. Q32's collector on +10 V. The overload lamp driver (circuit No. 11) hangs on the output
  through C20 1.0.
- **The noise generator** (board 3, circuit No. 3, Fig 9-8): Q15 2N3392, base on ground, collector open, emitter on
  R67 470K from +10 V through R47 75K (C25 10 uF): the reverse-biased emitter-base junction ("the noise generator
  uses a reverse biased transistor junction", Folkman). C12 5.6 into Q12 (2N3392; R17 100K collector load, R29 4.7M
  collector to base, C11 100 pF collector to ground, NOISE LEVEL R26 2.5K in its emitter), Q4 (2N3392) a follower (R9
  470, R19 3.3K, C5 100 pF base to emitter), C18 .15 to WHITE NOISE (pin 5; C18 crosses the ground line without a
  dot). R16 10K onto C3 .12 + R8 3.3K and C2 .033 + R13 220 to ground (the pinking legs), C1 2.5 into Q3 (2N3392; R3
  3.3K, R1 120; bias R7 / R6 560K with C4 2.5 at their junction), C20 2.5 to PINK NOISE (pin 6). RED NOISE (pin 2)
  through R12 10K, C7 .15, C8 2.5, Q6, R28 / R23 2.2M, C10 .1, C28 10, R59 100K: not traced in full.
- **Folkman's Noise Level** (TECHNICAL SERVICE MANUAL p. 14): "factory-set to yield -5dB maximum in the white
  position"; read here as 5 dB under an oscillator's sawtooth at the mixer's input (scripts/minimoog_noise_trim.py).
- **The filter's control summing** (Fig 9-17): CUTOFF R11 5K from +10 to -10 V, its wiper through R55 200K; J2
  FILTER EXT CONTROL IN through R51 100K (the jack's switch grounds it when empty); FILTER MOD SW15 through R52 33K
  (OFF grounds R52's far end); KEYBOARD CONTROL SW16 R53 300K, SW17 R54 150K: all onto board 4's pin 5. The
  modulation mix: MOD MIX R3 25K between board 3's pins 4 and 3, its wiper on ground; noise through R24 24K onto pin
  4, oscillator 3 through R23 24K onto pin 3 (circuit No. 15's inputs).

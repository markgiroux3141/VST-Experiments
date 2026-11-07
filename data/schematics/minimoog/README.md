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
  R61 200 to ground with C24 220 uF across it. R54 (470; the scan reads "410", no E-series value) feeds Q29's base.
- **Audio in:** pin 4 -> C27 10 uF -> Q29's base. **Feedback (EMPHASIS):** pin 6 -> R73 1K trim (REGEN CAL) ->
  R76 330 -> Q30's base.
- **Control current:** Q28 (TIS92) sinks the tail of Q29/Q30 through R60 680. Its base is driven by Q26 (TIS93,
  PNP; the complementary Vbe of the matched pair is the temperature compensation): the control node (pin 5)
  sums R74 47K (pin 16, AMOUNT OF CONTOUR), SCALE R49 500 ohm trim with R70 1.8K to ground, RANGE R39 10K trim from
  +10 V via R46 68K, C18 100 pF to ground; R45 330 in Q26's base lead.
- **Output amplifier:** the top stage's emitters via C5 0.22 / C1 0.22 into followers Q8 / Q6 (TIS97; R31 47K,
  R38 47K to ground), their emitters (R24 220K, R20 100K to -10 V) into the differential pair Q7 / Q5 (TIS97, tail
  R26 1K to -10 V); Q7's collector load R3 1K + R7 180 from +10 V (C9 100 uF at the junction); output via C10 10 uF
  to pin 7 (EMPHASIS pot and the VCA).

## Filter board No. 4, circuit No. 7, the VCA (read, transcribe when it is built)

TIS97 pairs Q13/Q14 and Q15/Q16, Q21 (TIS97) the tail current source (R33 470, R34 820, R35 1K, R43 270K, R59
68K), 2N4058 PNP Q1, Q12, Q17 (output), balance trims R14 25 ohm (1ST VCA BAL) and R12 100 ohm (2ND VCA BAL),
C4 220 uF, C6 0.33, C15 220 uF, C2 10 uF, CR1 / CR2 1N458A (or CL1), R29 / R30 680, R75 / R77 1K to the main and
headphone outputs.

## Oscillator board (read next)

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

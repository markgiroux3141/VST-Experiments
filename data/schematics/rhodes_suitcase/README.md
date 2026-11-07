# Rhodes Suitcase electronics (Mark I Suitcase 73, target year 1978)

Collected 2026-11-06 for a component-level model of a **1978 Rhodes Mark I Suitcase 73**: the
preamp with its stereo "vibrato" (an auto-panner), the power amplifiers, and the speaker
cabinet. The reference recording's vibrato runs at ~3.8 Hz with a ~+-8 dB antiphase L/R swing.

All schematics come from the **Rhodes Service Manual, chapter 11 "Diagrams, Schematics and
Pictorials"** (RHODES Keyboard Instruments / CBS Musical Instruments, **copyright 1979**, P/N
34.0119.000), as scanned and hosted by fenderrhodes.com (the "badrat" scan). They are the
factory drawings at 100-200 dpi.

## Which revision fits a 1978 Mark I Suitcase

Rhodes used three Suitcase amp systems, named after their designers (fenderrhodes.com,
`service/amp-diffs.html`):

| System | Power | Years | Preamp ID | Drawings here |
|---|---|---|---|---|
| Jordan | 50 W, mono | 1966-1969 | rotary knobs, 1/4" stereo cable | fig11-17 (pre-1969) |
| Peterson (FR7054) | 80 W (2 x 40 W), stereo | 1969 - 1977 | 4-pin DIN cable, concentric Treble/Bass and Intensity/Speed knobs | fig11-8, 11-9, 11-10, 11-11 |
| Haigler (FR7710, "Janus" electronics) | 100 W (2 x 50 W), stereo | late 1977 - (Mark II era) | 5-pin XLR-type cable, Bass/Treble sliders, Volume knob, Vibrato on/off switch + Speed / Intensity knobs, LED indicators | fig11-1 ... 11-7 |

Dating evidence:
- fenderrhodes.com `pianos/mark1b.html`: "the Suitcase Piano continuing to use the FR7054 80W
  Peterson amplifier until 1977"; "The new FR7710 amp was now 100W stereo (2 x 50W)", also
  packaged as the Janus I (1978, `pianos/amp.html`).
- Chicago Electric Piano and mmguitarbar dealer listings: "the suitcase electronics were updated
  with the Janus design in late 1977"; Vintage Vibe: "Late MKI Pianos 1977-79: Feature Janus Era
  ('5-Pin') Electronics" (secondary sources, sales copy).
- `amp-failures.html`: the 100 W replaced the 80 W when Delco stopped making the germanium
  output transistors (Fender P/N 120725 / 020725).

**So a 1978 Suitcase 73 almost certainly has the 100 W Haigler / Janus electronics: the
preamp of fig11-1 (op-amps, LED / LDR vibrato) and the dual 50 W amp of fig11-3.** Check the
actual piano: a 5-pin preamp cable, sliders for Bass / Treble, a Vibrato toggle and LEDs mean
100 W; a 4-pin DIN cable, concentric knobs and two #19 lamps on the preamp board mean 80 W
(an early-1978 unit built from old stock could still be 80 W). The 80 W drawings are kept here
for that case and because the classic early-70s "Suitcase sound" is the Peterson one.

## Files

Base URL for the figures: `https://www.fenderrhodes.com/org/manual/` (index page
`https://fenderrhodes.com/org/manual/ch11.html`, saved as `ch11.html`).

| File | Source | Covers | Legibility |
|---|---|---|---|
| `fig11-1.jpg` | `.../fig11-1.jpg` | **Schematic, Preamplifier Assembly, 100 W Suitcase and Janus I** (1978 target). Op-amps A1-A3 (MC1458P1 drawn), LED/LDR vibrato, 5-pin P2 | Good: all values and refs readable (zoomed); a few net routings at the input jacks are ambiguous (see below) |
| `fig11-2.jpg` | `.../fig11-2.jpg` | PCB, Preamplifier Assembly, 100 W / Janus I (Assy 015244, PCB 015245), component side | Good. Shows R39, C20 and only CR1-CR2, which differ from fig11-1 (see "Discrepancies") |
| `fig11-2.html` | `.../fig11-2.html` | Parts list for fig11-2 (part numbers, values) | Text |
| `fig11-3.jpg` | `.../fig11-3.jpg` | **Schematic, Dual 50 W Power Amplifier, 100 W Suitcase and Janus I**: channel A board in full, channel B as a box, the jacks, mains transformer T1 013579, +-30 V raw supply, the +-15 V regulator board | Good |
| `fig11-4.jpg` | `.../fig11-4.jpg` | Schematic, Power Amplifier, Janus I (same amp board; Janus master/slave jacks, a dual 50 K pot) | Readable at thumbnail; not needed for the Suitcase |
| `fig11-5.jpg`, `fig11-5.html` | `.../fig11-5.*` | PCB + parts, +-15 V regulator (MC7815P / MC7915P, 4 x 3 A diodes, 2 x 1000 uF 35 V, 2 x 500 uF 15 V) | Good |
| `fig11-6.jpg`, `fig11-6.html` | `.../fig11-6.*` | PCB + parts, 50 W power amplifier, **Suitcase** (PCB 012835 / assy 012838) | Good |
| `fig11-7.jpg`, `fig11-7.html` | `.../fig11-7.*` | PCB + parts, 50 W power amplifier, Janus I (differs from the Suitcase's in R1: 220 K vs 100 K) | Good |
| `fig11-8.jpg` | `.../fig11-8.jpg` | **Schematic, Preamplifier, 80 W Suitcase and Super Satellite** (Peterson): discrete transistors, two #19 lamps + two ORP61 CdS cells, 4-pin J1 | Values readable; no reference designators for most parts, and several wire junctions are hard to follow (transcribed only as an inventory, below) |
| `fig11-9.jpg` | `.../fig11-9.jpg` | Schematic, Power Module, 80 W Suitcase (one of two): driver transformer, germanium outputs P/N 120725, "OUTPUT (16 OHM LOAD)" | Good |
| `fig11-10.jpg` | `.../fig11-10.jpg` | Schematic, Power Supply Regulator Assembly (Peterson design), 80 W: T1 005601, +-35 V, regulated +25 V for the preamp, speaker / headphone jacks | Good |
| `fig11-11.jpg` | `.../fig11-11.jpg` | Circuit board assembly, Peterson regulator (2N2924 or equiv., 12 V zener, 500 ohm adjust) | Good |
| `fig11-17.jpg` | `.../fig11-17.jpg` | Schematic, Preamp and Power Amp (Jordan design), Suitcase pre-1969 | Readable; not the 1978 unit (kept for completeness) |
| `rhodes_service_manual_manual2.pdf` | `https://www.fenderrhodes.com/org/manual2.pdf` | A 28-page print (2000-05-24) of the online manual's text, chapters 1-11 (OCR; copyright 1979). Has **no text on the amplifiers or the vibrato**: chapter 11 is only the figure list | Text |
| `federal_suitcase_bright_kit.pdf` | `https://speakeasy.federalproductions.com/assets/Suitcase-Bright-Kit.pdf` | Speakeasy Vintage Music's Suitcase tweeter kit instructions: confirms four 12" speakers, front (player side) and rear (audience side) grille frames, each 12" with its own black/white wire pair | Text |
| `ch11.html` | `https://www.fenderrhodes.com/org/manual/ch11.html` | The chapter 11 index (figure titles) | Text |

## The 100 W (Haigler / Janus) preamp, fig11-1: transcription

Source of every value below: `fig11-1.jpg` (parts list `fig11-2.html` where noted). Resistors
1/2 W +-10 %, capacitors in uF unless pF, rated 15 V min (fig11-1 notes 1-2). Op-amps: drawn
as **MC1458P1** (dual; "A1A/A1B" etc. = U1-U3 on the PCB); parts list item 36 "INTEGRATED
CIRCUIT - DUAL OP AMP W1,2,3" P/N 013528; fenderrhodes.com's failure page calls it a "4558".
Pinout is the standard dual (A: 2-, 3+, 1 out; B: 6-, 5+, 7 out; 8 V+, 4 V-).

### Power (P2, 5-pin, preamp end; pin use per fig11-1 and fig11-3's P4)
- P2-5 (E16) = +15 V; P2-2 (E15) = -15 V; P2-1 (E12) = ground; P2-3 (E6) and P2-4 (E5) = the two
  channel outputs. (amp-diffs.html: pin 1 GND, 2 -15 V, 3 CH1, 4 CH2, 5 +15 V.)
- R22 100: +15 V -> node VA+ (A1 pin 8); C15 100 uF VA+ -> GND.
- R20 100: -15 V -> node VA- (A1 pin 4); C13 100 uF VA- -> GND.
- R21 100: +15 V -> node VB+ (A2 pin 8, CR1 anode, R28); C14 100 uF VB+ -> GND.
- R19 100: -15 V -> node VB- (A2 pin 4, CR3 cathode, C3 -); C12 100 uF VB- -> GND.
- A3 pins 8 / 4 are drawn as "+V" / "-V" arrows; which (decoupled or raw) rail feeds them is
  not drawn: UNREADABLE (not shown).

### Input (from the harp)
- The harp ("P1 KEYBOARD INPUT", a shielded cable with a phono-type plug): shield -> E3 (outer)
  -> E17 -> GND; centre -> E3-1 -> the tip of J1 ("ACCESSORY IN"). J1's normally-closed contact
  -> node IN = E3-2 = tip of J2 ("ACCESSORY OUT"). J1 / J2 sleeves (pin 3) -> GND.
  The jack switching is drawn ambiguously (which contact breaks when a plug goes into J1):
  with nothing plugged in, the harp's centre reaches node IN. UNREADABLE beyond that.
- C1 0.1: IN -> n1. R1 10 K: n1 -> A1A pin 2 (virtual ground). So the harp sees ~10 kOhm in
  series with 0.1 uF (corner 159 Hz into a resistive source; the harp's inductance resonates
  with C1).

### Gain stage A1A (inverting)
- A1A pin 3 -> GND. R2 220 K and C2 120 pF in parallel, pin 2 <-> pin 1 (gain -22, -3 dB at
  ~6 kHz). C19 0.001 from A1A out (pin 1) -> GND.
- R27 100: A1A out -> E9. E9 - - - E8: a dashed link (a jumper on the board).

### Volume (off-board pot)
- C4 5 uF (parts list: 25 V, "N.P.S.", i.e. non-polar): E8 -> node E10.
- R7 5 K audio taper "VOLUME" (P/N 013577): pin 1 = E10, pin 3 = GND, wiper pin 2 = E2.

### Tone, A1B (Baxandall-type in the feedback loop)
- C6 5 uF (NP): E2 -> n5.
- R9 4.7 K: n5 -> n6 (R13 pin 1). R13 50 K lin slide "BASS" (P/N 012528): pin 1 n6, pin 3 n7.
  C9 0.047 across R13 (n6 - n7). R18 4.7 K: n7 -> n9 (A1B out, pin 7).
- R14 39 K: R13 wiper -> n8 (A1B pin 6).
- C7 0.01: n5 -> R16 pin 1. R16 50 K lin slide "TREBLE": pin 3 -> C10 0.01 -> n9. R15 5.6 K:
  R16 wiper -> n8.
- A1B pin 5 -> GND.
- C16 1 uF NP (parts list: 15 V N.P.): n9 -> node S (the vibrato's input).

### Vibrato: panning network and output amps (A3)
- Two LED / LDR optocouplers, "LED 1" and "LED 2" on the schematic (parts list: "LIGHT DEP
  RESISTOR LDR1, 2", P/N 013556; a 4-terminal package, pins 1-2 the LED, 3-5 the LDR; maker /
  type not given: UNKNOWN). On the drawing the LED's anode is pin 2, cathode pin 1.
- LDR1 (pins 3-5): S -> node A. LDR2 (pins 3-5): S -> node B.
- R24 3.3 K: S -> node M. R29 10 K: M -> A. R30 10 K: M -> B.
- R31 25 K reverse-audio "INTENSITY" (P/N 013578): pin 1 = M; pin 3 and wiper (pin 2) tied
  together to GND (a rheostat from M to ground).
- A3A: R32 100 K: A -> pin 2; pin 3 -> GND; R34 220 K pin 2 <-> pin 1; C17 0.001 pin 1 -> GND;
  R37 100: pin 1 -> E5 -> P2-4 (a channel output).
- A3B: R33 100 K: B -> pin 6; pin 5 -> GND; R35 220 K pin 6 <-> pin 7; C18 0.001 pin 7 -> GND;
  R38 100: pin 7 -> E6 -> P2-3 (the other channel).
- How it pans: each channel's inverting amp (gain -220 K / (100 K + source)) is fed from S
  through its LDR, shunted to the M node through 10 K. When an LDR is lit (low resistance) its
  channel gets S nearly in full; dark, the channel only gets what R24 / R31 leave at M. R31 sets
  depth: at 0 ohm M is grounded and a dark LDR's channel is nearly silent (max intensity); at
  25 K, M carries ~0.88 S to both channels and the LDRs barely matter. The two LEDs are driven
  in antiphase (below), so the channels swing in antiphase: the auto-pan.

### Vibrato: LED drive
- CR1 (anode VB+) -> LED1 anode (pin 2); LED1 cathode (pin 1) -> R23 2.2 K -> node V.
- V -> R25 2.2 K -> LED2 anode (pin 2); LED2 cathode (pin 1) -> CR2 -> CR3 (in series,
  cathodes toward) -> VB-.
- So both LEDs sit between the rails with node V in the middle: as V rises, LED2's current
  rises and LED1's falls (I1 ~ (15 - V - drops) / 2.2 K, I2 ~ (V + 15 - drops) / 2.2 K):
  complementary, antiphase drive. (Parts list: R23, R25 = 1 K, see "Discrepancies".)
- S1 "VIBRATO" (SPDT toggle P/N 013575, drawn as a single make contact, "ON" marked):
  A2B out (pin 7) -> V. With S1 off, V floats to where the two LED currents balance (both LEDs
  steady: no modulation).
- Q1 2N3392 (vibrato indicator): base <- R26 10 K <- V; collector <- R28 1 K <- VB+ (R28 is
  printed "1 ohm"-like on the drawing; the parts list says 1 K); emitter -> E11 -> LED3
  "VIBRATO INDICATOR" -> E18 -> GND. LED3 flashes at the vibrato rate.

### Vibrato: the oscillator (A2A) and shaper (A2B)
- A2A (relaxation oscillator):
  - R4 100 K reverse-audio "VIBRATO SPEED" (P/N 013580): pin 3 and wiper pin 2 tied = A2A out
    (pin 1); pin 1 -> R3 1 K -> node X. (A rheostat of 0-100 K plus 1 K from the output to X.)
  - C3 10 uF (+ at X): X -> VB- (the timing capacitor, to an AC ground).
  - R5 100 K: X -> pin 2. C5 0.01: pin 2 <-> pin 1.
  - R6 1 M: GND -> pin 3; R8 470 K: pin 3 <-> pin 1 (positive feedback: thresholds at
    +-0.68 x the output swing).
  - The output is a square wave; X carries the timing capacitor's exponential "triangle"
    (+-0.68 of the swing). Estimated rate (not on the drawing): f ~ 1 / (2 R C ln((1 + 0.68) /
    (1 - 0.68))) = 1 / (3.32 (R4 + 1 K) 10 uF), ~0.3 Hz at full R4 to ~30 Hz at R4 = 0, ignoring
    R5 / C5; 3.8 Hz needs R4 + R3 ~ 8 K.
- A2B (gain and clipping, non-inverting):
  - C8 1 uF (schematic; see "Discrepancies") and R11 1 M in series: X -> pin 5; R12 1 M: pin 5
    -> GND (X's waveform halved).
  - R10 10 K: pin 6 -> GND; R17 100 K and C11 0.22 in parallel: pin 6 <-> pin 7 (gain
    1 + (R17 || C11) / R10: 11 at DC, ~10 at 4 Hz, falling 6 dB / octave above 7.2 Hz toward 1
    above ~70 Hz, so the oscillator's edges are softened): the +-4 V triangle overdrives
    A2B into its rails, so V is a **clipped triangle (a rounded trapezoid)**, which the LDRs'
    slow response smooths further.

### Pilot indicator
- E13 (the -15 V line) - LED4 "PILOT INDICATOR" - E10 - R36 1 K - E4 (ground side). Polarity
  per the drawing; the label E10 is used twice on fig11-1 (also the volume pot's top).

### Discrepancies between fig11-1, the PCB (fig11-2) and its parts list (fig11-2.html)
- R23, R25: schematic 2.2 K; parts list 1 K (listed with R3, R28, R36). The parts list has an
  **R39 2.2 K** that the schematic lacks, and the PCB shows R39 next to CR2 / R25.
- Diodes: schematic CR1, CR2, CR3; PCB and parts list only CR1, CR2 ("DIODE, SILICON" 006260).
  R39 may replace CR3 on the board revision. UNRESOLVED.
- C8: schematic 1 uF; parts list "C8, 20: CAPACITOR 25V 25" (25 uF) and a **C20** absent from
  the schematic; on the PCB C8 and C20 are two large electrolytics beside the LDRs.
  UNRESOLVED: the PCB / parts list are probably a later revision than the schematic.
- C4, C6: parts list value field reads "N.P.S." (non-polar, value missing); schematic 5.
- So the schematic and the board are not the same revision. For a 1978 piano neither is dated;
  the board's parts list is the safer guess for what was built, but the LED-drive and C8 / C20
  wiring of that revision can only come from the PCB traces (not transcribed here).

## The 100 W power amplifier, fig11-3 (two identical boards, A and B)

Source: `fig11-3.jpg`, parts `fig11-6.html` (Suitcase board 012835). Notes on the drawing:
transistors Q1, Q2, Q3, Q5 2N5784; diodes CR2-CR8 1 A 200 V (064089); CR1 1N4148; capacitors
200 V min.

- Input: preamp out (P4 pin 3 / 4) -> R1 / R2 680 -> "PREAMP OUTPUT" jacks J1 / J2 (CH A / B)
  -> through the normalling contacts of "POWER AMP INPUT" J3 / J4 -> board P1-7.
- Topology: a conventional quasi-complementary class-AB amp on **+-30 V** rails, direct
  coupled to the speaker (no output capacitor):
  - input R22 4.7 K + C1 5 uF NP into the base of Q1; R2 100 K base -> ground; feedback R1 100 K
    (Janus board: 220 K) with C7 10 pF from the output (P1-8) to Q1's base, i.e. an **inverting
    amp, gain ~ -100 K / 4.7 K = -21 (26.6 dB)** (from the drawing; check against the board);
  - Q1 / Q3 differential pair (R3 / R5 820 collector loads), Q3's base on R7 3.3 K + R8 100 K
    OFFSET ADJUST with C2 1.0 NP; Q2 tail current source (R4 330, biased by CR2 / CR3 and R6
    5.6 K 1 W); CR1 1N4148 clamp;
  - Q4 2N5781 (PNP) voltage amplifier (R9 33 1 W emitter, C3 0.0047 compensation), Q5 current
    source load (R10 68 1 W);
  - bias string CR4-CR7 + R11 150 + R12 500 BIAS ADJ;
  - drivers Q6 RCA29B (NPN) / Q7 RCA30B (PNP), R13-R15 100, R16 / R17 4.7; outputs Q8 / Q9
    **2N6254** (both NPN, quasi-complementary) on the heatsink with C4 / C5 120 pF; CR8 1 A;
    emitter resistors R18 / R21 0.5 ohm 5 W on the schematic, "R18-R21 0.2 ohm 10 W nichrome
    (x4)" in the parts list.
- Output: P1-8 -> F1 / F2 4 A -> "CH A / CH B SPEAKER" jacks J7 / J6; headphone jack J5 through
  R3 / R4 330.
- Supply: T1 013579 (120 V or 240 V export primaries); bridge CR1 013594 + C1 / C2 11,000 uF 40 V
  -> +-30 V; a second winding -> bridge 072934 + 1000 uF 35 V -> MC7815P / MC7915P -> +-15 V for
  the preamp (P3 -> P4 pins 5 / 2).

### As built (2026-11-07): `config/circuits/rhodes_suitcase_100w.yaml`

GENERATED by `scripts/make_rhodes_suitcase_100w.py` (the preamp file plus the amp). Read from
fig11-3 at zoom (2026-11-07), node by node, then checked against the idle point:

- Q1 / Q3 the long-tailed pair, Q2 its tail (base on the CR2 / CR3 string, which R6 5.6K feeds
  **from ground**, so the string sits at -30 V + 1.4 V: Q2's emitter R4 330 then draws ~2 mA,
  Q5's R10 68 draws ~10 mA); Q3's base returns to ground through R7 + OFFSET ADJUST R8 (its
  wiper tied to its far end: a 0-100K rheostat), C2 across; R2 100K from Q1's base to ground.
- CR1 (1N4148): its triangle points from the emitter node to Q1's base node, a reverse-bias
  protection of Q1's base-emitter junction.
- Q4 (PNP, R9 33 in its emitter) the voltage amplifier into the bias string: CR4-CR7 in
  parallel with R11 150 + BIAS ADJ R12 (wiper tied to its upper end), Q5 the current-source
  load (10 mA); C3 .0047 from +30 V to the string's top (Q6's base).
- Output: Q6 (RCA29B) follows into Q8 (2N6254) through R16 4.7, R13 100 to the output,
  R18 in Q8's emitter. The lower half is a **complementary-feedback (Sziklai) pair**: Q7
  (RCA30B)'s emitter takes its current **from the output through R14 100** (CR8 across it points
  the other way: a clamp, reverse in normal use), its collector (R15 100 to -30 V) drives Q9
  (2N6254)'s base through R17 4.7, Q9's collector is the output, R21 in its emitter. So the
  bias string must cover Vbe6 + Vbe8 + the R14 drop + Veb7 ~ 2.5 V: the four diodes (~2.4 V)
  clamp it, the pot lowers it, the factory setting sits near the diodes' end of the range.
- R18-R21: the schematic prints R18 and R21 as 0.5 ohm 5 W; the parts list (fig11-6.html) has
  four 0.2 ohm 10 W nichrome assemblies, R18-R21, and the board (fig11-6.jpg) shows R18 / R19
  as a pair beside P2 and R20 / R21 as another. **Used: two 0.2 ohm in series per output
  transistor, 0.4 ohm**: the parts list is the assembly as built, two in series is the only
  pairing near the drawing's 0.5 (parallel gives 0.1), and 0.4 is inside its 20% room.
- The supply: T1 013579's two halves from the mains (22.2 V rms each, provisional: chosen so the
  rails idle at the drawing's +-30 V), the bridge across the winding's ends with its centre
  tap as ground, C1 / C2 11,000 uF; the +-15 V regulator board stays ideal (the preamp's rails).
- Factory trims (`scripts/rhodes_amp_trim.py`): OFFSET ADJUST for 0 V at each output, BIAS ADJ
  for 25 mA through each output transistor (provisional: the manual publishes no setting).

Measured (`scripts/rhodes_amp_study.py` -> `reports/rhodes/suitcase_amp/`): see
docs/RHODES_PLAN.md "The Suitcase".

### The 1978 speaker configuration, chosen (2026-11-07)

**Four 8 ohm 12" ceramic speakers, two per channel in series: 16 ohm per channel.** Evidence:
the Reverb listing of a 1978 pair ("50W 8 ohm"), ep-forum topic 6862 (series for 16 ohm),
unbrokenstring.com; fig11-9's "16 OHM LOAD" for the 80 W amp of the preceding years. The 32
ohm CTS alnicos in parallel belong to the early (1971-75) cabinets; ep-forum topic 8862's "4 ohm
in series" is a single unverified post. The 100 W amp clips at ~22 W into 16 ohm in our model
(its +-26 V loaded rails), matching the arithmetic above: the "50 W" rating is optimistic for
16 ohm, or the cabinets were lower. Model: two P12R@1 (8 ohm, Jensen's 12", provisional
stand-in: maker unknown) in series, the front one reading out as the player's pressure 1 m on
axis, the rear one (mirrored: the channel's speaker directly behind) as the audience's; the
cabinet 48 x 27 x 14 in as an open baffle (open / closed back unknown).

## The 80 W (Peterson) preamp, fig11-8: inventory only

Source: `fig11-8.jpg`. Notes: all transistors 037119 (selected 2N3392) except the two lamp
drivers marked 2N3053; diodes 069906 (2 A 100 V); ORP61 = P/N 003770; R1A / R1B / S1 = 006096;
R2A / R2B = 006112; R3 = 006104. Supply: +25 V regulated from the power-supply assembly (J1-1).
Most parts have no reference designator and several junctions are hard to follow, so this is a
**stage-by-stage inventory, not a netlist** (connections to verify):

- Input: upper / lower harp jacks on the name-board rail -> 0.22 uF -> NPN common emitter
  (base divider 390 K / 33 K from a 3.3 K + 100 uF 15 V decoupled rail; collector 12 K; emitter
  1.5 K; 330 pF collector-base) -> NPN emitter follower (4.7 K) -> 5 uF NP 25 V -> two 6.8 K.
- Tone: 100 K lin TREBLE and 100 K lin BASS (concentric pot), 0.0047, 22 K, 0.1, 0.1, 0.047,
  R2A / R2B 6.8 K, around a two-transistor stage (390 K, 1 M), then a stage with 12 K, 6.8 K,
  68 K, 470 pF, 0.0047, 6.8 K, 10 K, 0.001, R3 100 K lin VOLUME, 1.0 uF 35 V + 100 ohm.
- Splitter / modulator: NPN with base bias 100 K / 100 K, 0.22 in, collector 1.5 K, emitter
  4.7 K; collector via 50 uF 25 V and emitter via 5 uF NP + 3.3 K; 10 K, 47 K, 47 K; two
  **ORP61 CdS cells, each lit by a GE #19 lamp** in its own housing (dashed boxes).
- Lamp drive: two 2N3053s, each lamp fed through 150 ohm 2 W with 50 uF 25 V; emitters via 68
  ohm + CR5 / CR6 to S1 (VIB. N.C., with 4.7 K); CR1-CR4 steering; R1A 50 K reverse-log VIB.
  INTENSITY.
- Oscillator: two NPNs with 2.2 K collector loads, a 5 uF NP - 22 K - 22 K - 5 uF NP network
  (R1B 50 K reverse-log VIB. SPEED at the 22 K / 22 K junction), 470 ohm + 50 uF 25 V
  decoupling, 10 K base feeds to the drivers. Oscillator type: UNREADABLE with confidence (a
  two-transistor RC oscillator; drawn like a phase-shift / multivibrator hybrid).
- Outputs: two NPN emitter followers (4.7 K emitters; bias from 4.7 K / 47 K / 47 K with 100 uF
  15 V and 10 uF 25 V; 100 K, 100 K, 0.22, 0.22) -> 5 uF NP 25 V -> J1 pins 2 (CH 1) / 3 (CH 2).
  J1 = 4-pin to the power-supply / amplifier assembly (Switchcraft 60GA4F).
- Panning: the same principle as the 100 W (each channel's level set by a CdS cell lit in
  antiphase), but with incandescent lamps (thermal lag of the filament plus the CdS lag: the
  "attack and decay of two lamp filaments").

## The 80 W power module and supply (fig11-9, fig11-10)
- Two modules, each: input 10 K level pot -> 6.4 uF -> 2N3391A -> 2N3405 -> driver
  transformer T1 (split secondaries) -> two **germanium** output transistors P/N 120725 in a
  single-ended push-pull on **+-35 V**, 0.5 ohm 5 W emitter resistors, 820 ohm 2 W / 2.7 ohm bias
  networks, 5.6 K || 1200 pF feedback; "OUTPUT (16 OHM LOAD)"; 270 ohm 2 W to ground.
- Supply (fig11-10): T1 005601, CR1-CR4 3 A 100 V, 2 x 3000 uF 50 V -> +-35 V; a regulated
  +25 V (pass transistor 020725, 2N3392, 12 V zener, 500 ohm VOLTAGE ADJUST) for the preamp;
  speaker output jacks and a headphone jack (330 ohm).

## Speakers and cabinet

- **Four 12" speakers**, two on the player-side (front) baffle and two on the audience-side
  (rear) baffle (`federal_suitcase_bright_kit.pdf`; ep-forum topic 6862).
- **Channel split** (ep-forum topic 6862, a forum post, not a factory document): one pair per
  channel, each pair spanning front and back **on the same side**; "The front and rear baffles
  each have a left and right channel speaker on them ... each channel speaker is mounted across
  from its mirror. So left/right on the front changes to right/left on the back." So the
  pan moves the sound left/right for the player, mirrored for the audience.
- **Impedance:** both amp generations are reported to want **16 ohm per channel** (fig11-9 says
  "16 OHM LOAD" for the 80 W; for the 100 W only forum posts). Early cabinets: **32 ohm** 12"
  speakers in parallel per channel (Fender-branded CTS alnico, June 1975 date code:
  unbrokenstring.com; Eminence also cited; a 1971 CTS 32 ohm on Reverb). Late-70s / early-80s
  cabinets: **8 ohm** ceramic 12" (a Reverb listing of a 1978 pair, "50W 8 ohm"), which must be
  in **series** for 16 ohm (ep-forum 6862; unbrokenstring.com). One ep-forum post (topic 8862)
  claims 4 ohm in series (Oxford OEM code 465, "12T6"); conflicting, unverified.
  Arithmetic check (ours, not a source): +-30 V rails reach ~27 V peak, so 50 W needs ~7 ohm;
  into 16 ohm the 100 W amp gives ~23 W per channel. Either the rating is optimistic or the
  load is lower: UNCONFIRMED for a 1978 cabinet.
- **Cabinet:** "speaker section 48 x 27 x 14" (presumably inches), keyboard 49 x 26 x 13,
  150 lb for the bottom (ep-forum topic 420, a user's figures). Open / closed back: not found.
  The 100 W amp's heatsink is mounted to the side of the enclosure (amp-diffs.html). Panel
  material, baffle construction and internal volume: not found.

## What's missing
- A dated (1978) revision of the 100 W preamp: fig11-1 and the fig11-2 board / parts list
  disagree (R23 / R25, R39, CR3, C8 / C20); the board's LED-drive wiring isn't transcribed.
- The optocouplers' type (Rhodes P/N 013556, "light dependent resistor"): no datasheet, no
  maker; its LED current -> LDR resistance law and time constants must come from elsewhere
  (a VTL5C-type Vactrol is the usual replacement).
- Published voltages and test points: none in the manual (no amplifier text at all).
- The harp-side numbers (pickup inductance / resistance, the harp's output level) are not in
  these drawings; the harp wiring is the manual's Fig. 10-4 (in RHODES_PLAN.md's sources).
- Speaker model, Thiele-Small parameters, and the cabinet's construction for 1978.
- The 80 W preamp as a netlist (the drawing has no designators; see the inventory above).

## Sources consulted (not downloaded)
- https://www.fenderrhodes.com/service/amp-diffs.html (the three systems, cable pinouts)
- https://fenderrhodes.com/service/amp-failures.html (GE #19 lamps; 4558; germanium outputs)
- https://www.fenderrhodes.com/pianos/mark1b.html (FR7054 80 W until 1977; FR7710 100 W)
- https://fenderrhodes.com/pianos/amp.html (Janus I, 1978)
- https://ep-forum.com/smf/index.php?topic=6862.0 (speaker wiring per channel, 16 ohm)
- https://ep-forum.com/smf/index.php?topic=8862.0 (speaker impedance, conflicting)
- https://ep-forum.com/smf/index.php?topic=420.0 (dimensions)
- https://www.unbrokenstring.com/fender-rhodes-electric-piano-amp-refurbishment/ (CTS 32 ohm)
- https://reverb.com/item/60238888-fender-rhodes-12-speaker-pair-for-suitcase-cabinet-late-70s-version-ceramic-50w-8-ohm (403 to the fetcher; title only)
- https://music-electronics-forum.com/forum/amplification/other-amps/23095-rhodes-suitcase-amps
- Not fetched (rate-limited or blocked; may hold part numbers):
  https://www.vintagevibe.com/products/rhodes-5-pin-100w-pre-amp-rebuild-kit,
  https://www.vintagevibe.com/products/fender-rhodes-4-pin-pre-amp-rebuild-kit,
  https://gearspace.com/board/so-much-gear-so-little-time/671183-best-speakers-fender-rhodes-suitcase.html
- Forum thread that may have a PCB print (GroupDIY, attachments login-walled):
  https://groupdiy.com/threads/fender-rhodes-piano-pcb-print.15804/

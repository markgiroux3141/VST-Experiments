# API 312 / 2520 (CHAINS_PLAN.md WP12)

Sources and provenance. Nothing here is a transistor-level 2520 yet: see "Missing".

## Found

- `API_312_Mic_Preamp_Cut_Sheet_R2.pdf` (user-supplied, 50 MB, not committed: API's
  marketing sheet, one page, no schematic): the 312 = AP2516 input transformer + 2520 +
  output transformer; max gain 69 dB; 20 dB pad; 3:1 output transformer tap select;
  polarity; 48 V phantom; peak LED; 500-series module. Block diagram only.
- `api_2520_circuit_specifications_1972.png`: Automated Processes Inc.'s "Circuit
  Specifications" sheet (c) 1972, from steampoweredradio.com
  (`https://www.steampoweredradio.com/pdf/api/manuals/api%202520%20op%20amp.pdf`). **Figure 1
  is API's own mic preamp (58 dB)**: 150 ohm source into an **AP2622, 1:8**; secondary loaded
  by 220 pF and 5.1 k; the 2520 non-inverting; feedback Rf 47 k with 47 pF across it; Rs 470
  ohm to ground through a 60 uF / 10 V cap; output through a 60 uF / 10 V cap into 600 ohm.
  Gain A = (Rs + Rf)/Rs + transformer gain. Published: gain 58 dB, equivalent input noise
  -129 dBm (20-20 kHz, unweighted), input impedance > 1500 ohm, output < 5 ohm, output
  +21 dBm at +-15 V / +24 dBm at +-20 V, +-0.25 dB 20-20 kHz, < 0.2% THD at rated output.
  Figure 2 (line amp, AP2503 1:3 output transformer via 47 ohm, 49 dB) is the output stage.
- `api_2520_info_sheet.png`: the 2520's data sheet (`retrorecordingsxr.com/wp-content/
  uploads/manuals/api/API_2520_info.pdf`): gain > 110 dB DC; GBW ~50 MHz; full-output
  frequency 40 kHz; EIN < 0.5 uV; Zin > 10 Mohm; offset current 25 nA typ; offset voltage
  4 mV typ; common mode +-12 V at +-15 V supply; THD 0.2% 20-20 kHz at rated output; output
  > 7.75 V rms at +-15 V (> 11 V at +-20 V); min load 75 ohm; 0.8 W at +-15 V; quiescent
  15 mA at +-15 V (26 mA at +-20 V); 18 mA at 600 ohm rated output; 60 mA at 75 ohm; supply
  +-12 to +-20 V. Nine transistors, epoxy-potted. Pins: +IN, -IN, +V, C (common), -V, OUT, T
  (trim: 100 k between +V and T nulls the offset).
- Clone descriptions (forum / vendors, a second-hand source): the GAR 2520 is 9 transistors
  with a resistive tail for the input pair; Capi's CA-0252 has 10 (transistor tail); original
  input pair BC414C, interstage TIS98 NPNs, output pair TO-39 BC141-16 / BC161-16. No
  differential-amp active load, no current mirrors; compensated with double differential
  stages. Revisions: Melville and Huntington (API's two best known). A stability cap across
  Rf: one builder 100 pF.

## The 2520's internal schematic (supplied by the user, 2026-11-06)

- `api_2520_schematic_r1.gif` and `api_2520_schematic_groupdiy.png`: GroupDIY's "Origin of
  2520 Schematic?" thread (https://groupdiy.com/threads/origin-of-2520-schematic.62035/,
  Di_Sousa's attachment `API_2520_schematic2.gif`, "2520 R1", and a cleaner redraw of the
  same). A reverse-engineered drawing, not API's. Q1 / Q2 SKA4693 (BC414C in another version),
  Q3 / Q4 TIS98 / TIS97, Q5 TIS98, Q6 / Q9 2N5087, Q7 2N3053, Q8 2N4036; R1 150k, R2 100R, R3
  82k, R4 22k, R5 68k (the trim tap between them), R6 3k, R7 3k-5k, R8 1k, R9 56R, R10 800,
  R11 / R12 5R6, R13 56R, R14 1k, R15 1k, R16 47k; C1 1000p, C2 47p, C3 47p, C4 39p, C5 47p;
  D1 MZ2361 (two in series on the R1 drawing), D2 / D3 MZ2361 clamps. Its notes list variants
  (C4 68p, R3 20k, R4 3k9, R5 16k, R6 3k9, R7 3k3, R14 0R, a current-source tail).
- Transcribed into `config/circuits/api_2520_test.yaml`, with two deviations a working op-amp
  needs (Q7's base on Q9's collector; C5 on Q4's base): the circuit file's header and
  CHAINS_PLAN.md WP12's Notes say why.

## Still missing

The AP2516 / AP2622 input and AP2503 output transformers' figures (turns, DCR, inductance):
only their ratios are published (API: 1:8 for the AP2622 in the 1972 Fig. 1; the 312 cut
sheet's "3:1 output transformer tap selection"; the AP2503 1:3 in Fig. 2).

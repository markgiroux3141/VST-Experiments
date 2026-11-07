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

## Missing (the user fetches; GroupDIY attachments are login-walled)

The 2520's internal schematic with its values:
GroupDIY "Origin of 2520 Schematic?" thread, Di_Sousa's attachments of 2016-04-15,
`API_2520_schematic1.pdf` and `API_2520_schematic2.gif` (the second has the right D2 / Q9
connection), `https://groupdiy.com/threads/origin-of-2520-schematic.62035/`; also
`https://groupdiy.com/threads/current-api-2520-schematic.53738/`. Also the AP2516 / AP2622
and AP2503 transformers' figures (turns, DCR, inductance).

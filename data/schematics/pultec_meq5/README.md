# Pultec MEQ-5 sources (docs/EQ_PLAN.md EQ2)

## Found

- `gyraf_meq5.gif`: "Pultec MEQ5 Equalizer, Filter Sections", Gyraf Audio, rev 1, 15-02-2002
  (a reconstruction, not Pulse Techniques' drawing; Gyraf: "the schematic shows the filter
  sections only, but amplifier section seems cross-compatible with the PEQ1A"; not built by its
  author). web: https://gyraf.dk/gy_pd/pultec/meq5.gif (page: https://gyraf.dk/gy_pd/pultec/pultec.htm),
  downloaded 2026-11-15, 1024 x 332, sha256
  `c8b5231b19add4eca05f4b299cfafa00f143b269168ea55f328e4826db92bbfb`.
  - Topology: a 600:600 input transformer with 620 ohm across it (as the EQP-1A); LOW BOOST a
    2K5 linear pot in series, its wiper into a tapped coil (120 / 280 / 420 / 520 mH) and a
    switched capacitor (1 uF, 470 nF, 150 nF, 200 nF) back to the line (200 / 300 / 500 / 700 /
    1000 Hz); 1K shunt; MID CUT 510 ohm in series, a 2K5 reverse-log pot to ground whose wiper
    feeds 270 ohm into a tapped coil (34 / 61 / 108 / 145 / 277 / 420 mH) and a switched
    capacitor to ground (1.5 uF ... 10 nF; 200 Hz-7 kHz, eleven positions); HIGH BOOST a 10K
    linear pot in series, its wiper into a coil tapped 477 / 625 mH and a switched capacitor (16
    n, 8n2, 3n9, 2 n, 1 nF; 1.5-5 kHz); 5K1 shunt; the interstage transformer to the EQP-1A's
    amplifier.
  - **Why it isn't built yet:** at 1024 px the switches' wiring (which tap and capacitor each
    position joins) can't be read, and pairing them by their height on the drawing doesn't
    resonate on the panel's frequencies. Guessing them would be invention.

## Wanted

- The redraw a GroupDIY member posted (credited to Greg Boboski: CJ, "never seen a real MEQ 5
  filter doc"): attachment `meq_5.jpg`, 259.7 KB, in GroupDIY thread 18056
  (web: https://groupdiy.com/threads/pultec-meq-5-eq-full-schematic.18056/), behind the forum's
  login; the copy CJ linked on vacuumbrain.com is gone.
- A Pulse Techniques MEQ-5 manual (vintagedigital.com.au lists one).
- What tubes the MEQ-5's amplifier has: one post says "12 ax into a 6aq5", Gyraf says the
  EQP-1A's (12AX7, 12AU7) fits.

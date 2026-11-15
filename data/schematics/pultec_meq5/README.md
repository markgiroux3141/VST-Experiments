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
  - **How the switches were read (2026-11-15):** the GIF is lossless line art, so a
    nearest-neighbour zoom shows every wire. Each switch's two decks are drawn mirrored: the
    coil deck's first contact (its clockwise end, the drawing's dot) pairs with the capacitor
    deck's last. Under that reading MID CUT's eleven positions resonate at 200, 302, 507, 727,
    1032, 1564, 2095, 3313, 4987, 6826 and 8631 Hz for knobs 200 ... 7000: on the knob within
    5% to 2 kHz, the top three 25-37% high (all on the 34 mH tap). LOW BOOST: 221, 358, 777,
    673, 1027 Hz for 200, 300, 500, 700, 1000 (500 is 55% high). HIGH BOOST: 1.59, 2.22, 3.69,
    5.15, 7.29 kHz for 1.5 ... 5 kHz (read same-height instead: 1.82, 2.54, 3.69, 4.50, 6.37,
    a steadier 1.13-1.27x; the mirrored reading is kept for one convention across the drawing).
    These misses are the reconstruction's parts, reported, not fitted.
  - The user fetched GroupDIY thread 18056's attachment (2026-11-15): byte-identical to this
    GIF, so no better copy is known.

## Wanted

- Pulse Techniques' own drawing, or a measured unit's curves: either would settle the
  frequencies the reconstruction misses.
- A Pulse Techniques MEQ-5 manual (vintagedigital.com.au lists one).
- What tubes the MEQ-5's amplifier has: one post says "12 ax into a 6aq5", Gyraf says the
  EQP-1A's (12AX7, 12AU7) fits.

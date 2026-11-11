# The Shure 520 "Green Bullet" (CHAINS_PLAN.md WP30)

## Sources

- Shure Brothers, 1959 catalog (worldradiohistory.com):
  https://www.worldradiohistory.com/Archive-Company-Publications/Shure/1959_shure.pdf
  (`shure_1959_catalog.pdf`, git-ignored, sha256
  537bd81f65602df848df042dd8b2138dd35d12bc5e753c475fb86f9ea709a17e). PDF p. 14 (index 13): the
  520 "Green Bullet" and the 520SL "Dispatcher": **Controlled Magnetic**, 100 to 9,000 cps, -52.5
  db (0 db = 1 volt per microbar: -32.5 dBV/Pa, 23.7 mV/Pa), high impedance (recommended load
  100,000 ohms or more), semi-directional, die-cast zinc, metallic green. PDF p. 17 (index 16): the
  R5 controlled-magnetic cartridge, the 520's replacement element ("also ideal for replacement of
  crystal cartridges in Shure cases of the Model 707A and 708A Series").

So the Green Bullet of the catalog is a controlled-magnetic (balanced-armature) element, not a
crystal: WP30's Decisions.

## Supplied by the user (2026-11-11)

- **Shure, Model 520D Controlled Magnetic Microphone, data sheet (27A1633, 1980)**, two page scans:
  `shure_520d_data_sheet_1980_p1.png` (sha256
  332b0e02ebd0e1e744690274b5275324b962c56f6c4dc5dd51d79a98374216a3) and
  `shure_520d_data_sheet_1980_p2.png` (sha256
  2c403586bd3d8677963a693c16b6f4c75876ffeee64c8549720481fe7f308633). p. 1: controlled magnetic,
  "Green Bullet", 100 to 5,000 Hz, **Figure 1, the typical frequency response** (dB re 1 kHz, 20 Hz
  to 20 kHz, 10 dB rules); omnidirectional; dual impedance, 150 ohm (160 actual) and "High";
  loads: low 150 ohm minimum / 1 k recommended, high 15 k minimum / 100 k recommended; open circuit
  at 1 kHz -73.0 dB (0.22 mV) low, **-56.0 dB (1.6 mV) high** (0 dB = 1 V per microbar: 16 mV/Pa);
  20 ft two-conductor shielded cable; 62.7 mm diameter, 82.6 mm long; Figure 2, the internal
  connections (the cartridge's coil, a 39k across the high-impedance terminals). p. 2: the
  cartridge R44D; Figure 4, the response "tailored" (the 39k clipped and an accessory resonator in
  front of the cartridge: a ~3 kHz peak, for amateur radio).
- **Shure, 520DX Harmonica Microphone specification sheet (FOD 01105, 1997)**:
  `shure_520dx_spec_sheet_1997.pdf` (git-ignored; sha256
  d8eb986d930f6c303e1e45c993150de671b6dd5448b1e4cba9b77ef3a022b946; web:
  https://www.fullcompass.com/common/files/457-Shure520DXSpecSheet.pdf). The later "Green Bullet":
  type "Dynamic" (the R198 element), 100 to 5,000 Hz, its Figure 2 response, high impedance
  unbalanced (100 k minimum), -54.0 dB (2.0 mV) at 1 kHz, a volume pot and a step-up transformer in
  the case (Figure 3). A reference only: WP30 builds the 520D of the 1950s-80s.

The 1959 catalog's 520 (100-9,000 cps, -52.5 dB) and the 1980 520D (100-5,000 Hz, -56.0 dB high)
differ: the 520D's data sheet is the one with a curve, so WP30 fits to it.

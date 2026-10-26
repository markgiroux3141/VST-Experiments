# Pultec EQP-1A sources

The device builder's second circuit (B2; docs/DEVICE_BUILDER_PLAN.md). Values in
`config/circuits/pultec_eqp1a.yaml` cite these as `dwg:` (printed on Pulse
Techniques' drawing), `dwg-interp:` (wiring read off the scan, where it isn't
certain), `redraw:` (the passive network's redraw, below) or `web:`.

## The manual

"Installation and operating instructions, Pultec model EQP-1A program
equalizer", Pulse Techniques, Inc. (West Englewood / Teaneck, N.J.), 8 pages:
brochures of the EQP-1A and EQP-1A3, the response curves, the instructions, the
potentiometer list, the EQP-1R's passive network (hand drawn), and the drawings
DWG E-72,658-2 (EQP-1A) and DWG E-112,353-7 (EQP-1R).

- Source: web: https://archive.org/details/Pultec_EQP-1A_owners_manual
  (`Pultec_EQP-1A_owners_manual.pdf`), downloaded 2026-10-26
- sha256 of the PDF: `2bb99d5fcf170884aa06e2f5996e3f534f693d5f36b5e4f3465357498b8abdb1`
  (425 kB, scanned, not committed); the same file is at
  web: https://www.recproaudio.com/diy_pro_audio/diy_files/eqp_1a/PultecEQP.pdf
- Pages rendered at 200 dpi grayscale (pdftoppm) on 2026-10-26.

| File | PDF page | Shows |
|---|---|---|
| `brochure_specs.png` | 1 | EQP-1A brochure: boost / cut frequencies and ranges, transformers 600 / 250 / 150 ohm, noise 92 dB below +10 dBm, distortion 0.15% at +10 dBm into 600 ohm, amplifier flat 20 Hz-20 kHz +0 / -1 dB, tubes ECC82/12AU7, ECC83/12AX7, 6X4, 117 V 50/60 Hz 25 W |
| `response_curves.png` | 3 | The published curves for every switch position: LF boost and attenuate at 20 / 30 / 60 / 100 cps, HF peak boost sharp and broad at 3-16 kc, HF attenuate at 5 / 10 / 20 kc. "The curves in the above families represent typical settings, not steps" |
| `instructions.png` | 4 | Input 600 ohm matching (strappable 250 / 150), output feeds 600 ohm (300 / 150), average input -15 to +8 dBm, maximum peak output +21 dBm; the operation of the controls |
| `potentiometers.png` | 5 | EQP-1A pots: low boost 10k audio taper (A-B JA-1031), low attenuate 100k audio (JA-1041), high boost 10k linear (JU-1031), high attenuate 1k linear (JU-1021), bandwidth 2.5k linear (JU-2521) |
| `dwg_e72658_amplifier.png` | 7 | DWG E-72,658-2: Triad HS-56 input transformer, "passive equalizer circuits" (a box), Triad HS-29 interstage, ECC83/12AX7 and ECC82/12AU7 push-pull with feedback from the output transformer, Peerless S-217-D output transformer, Chicago PCC-55 mains transformer, 6X4, the supply's RC filter; typical voltages (11 MOhm voltmeter, no signal) |

## The passive network

The drawing shows the passive network as a box. Its values come from a redraw:

- `redraw_passive_network.jpg`: "Pultec EQP-1A Passive EQ Section", signed Hoef,
  dated 7-11-97; web: https://www.recproaudio.com/diy_pro_audio/diy_files/eqp_1a/eqp1a_filter_schematic.jpg
  (sha256 `28b275ad3df8ebadd6924283a9001c7ecd4619f420b8b500b350aa90ec7699ca`),
  downloaded 2026-10-26. Its inductor and capacitor pairs resonate at the panel's
  frequencies (150 mH / 18 nF 3.06 kHz, 82 mH / 18 nF 4.14 kHz, 68 mH / 15 nF
  4.98 kHz, 47 mH / 8.2 nF 8.11 kHz, 33 mH / 8.2 nF 9.68 kHz, 33 mH / 5.6 nF
  11.7 kHz, 27 mH / 3.3 nF 16.9 kHz), and its pot values are the manual's.
- `redraw_amplifier.jpg`: the same site's copy of DWG E-72,658-2 (a cleaner scan of
  the left half; sha256 `95689ae3a8e84d56201988b6f03520540c2f932831bb7a0ce260354325e6d421`).
- The original inductor was one tapped toroid. A vendor of replacements lists its
  five taps as 32.0, 51.1, 84.3, 100.2 and 150.5 mH at 14-34 ohm (web:
  https://vintagewindings.com/products/VintageWindings%20EQ-1A.html); the same page
  disputes the commonly used values (27 / 33 / 47 / 68 / 82 / 150 mH) with its own
  calculation (29.9 / 31.4 / 48.2 / 67.5 / 87.9 / 156 mH). Neither is a measurement
  we can check, so the inductances are bounded genome parameters.

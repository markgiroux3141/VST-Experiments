# Royer Labs R-121 (CHAINS_PLAN.md WP16)

Fetched 2026-11-10 (not committed: Royer's documents; `.gitignore`):

- `R-121manual.pdf` (sha256 1de6d2354b7530de3ad81e2d9c6a00fdb7c586914dfa020c0d80b61ba473ce8e;
  web: https://cf3.zzounds.com/media/R-121manual-2c43c453a7fd3f8c7fc0b9bf5d670e47.pdf), the
  Operation Instructions Manual. Electrical: electro-dynamic pressure gradient, **figure-8**, 2.5
  micron aluminium ribbon, 30-15,000 Hz +-3 dB, **sensitivity -49 dB (ref 1 V/Pa)**, **300 ohm
  nominal balanced**, rated load 1500 ohm, **135 dB SPL @ 30 Hz** (the rear side: 115 dB).
  Mechanical: "High grade Neodymium magnet assembly in Royer's patented Flux-Frame transducer;
  **1.5" x 3/16" x 2.5-micron ribbon assembly**; Stainless steel internal baffle and dampener",
  244 g, 158 x 25 mm. p.14: the **offset ribbon** "positions the ribbon element towards the
  front"; it "records slightly brighter on its back side ... three feet or closer"; the internal
  dampening screen is much closer to the ribbon at the front. p.18: the polar pattern (200 Hz, 1
  kHz, 10 kHz: a figure-8) and the frequency response chart (digitized:
  `data/datasheets/royer_r121_response.csv`, its provenance sidecar; the chart's rules aren't a
  uniform log scale).
- `R-121cutsheet.pdf` (sha256 cf4be70000ce6b8ef3fbee53397522ec60a6b3d57ca68202fc5857fd9b800832;
  web: https://media.sweetwater.com/store/media/r121_R-121cutsheet.pdf), Royer's 2000 cut sheet:
  -50 dBv re 1 V/Pa, 300 ohm @ 1K, > 1500 ohm load, > 135 dB.

`RIBBON_R121` (published_points.yaml) is the ribbon on Olson's circuit with the front channel 30%
of the pole pieces' depth (the offset; provisional), fitted by `scripts/fit_r121.py`; `R121_OT`
a design (1:40, inferred).

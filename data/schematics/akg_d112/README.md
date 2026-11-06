# AKG D112 sources

The chains build-out's WP9 (docs/CHAINS_PLAN.md), found 2026-11-06. The PDFs are not
committed (they live in the git-ignored cache); URLs, sha256 and sizes are below. Values read
2026-11-06 from the page images; recheck against the page when one goes into a file.

## akg: AKG D112 data sheet (the original, Harman-era layout), 2 pages

- web: https://www.barryrudolph.com/recall/manuals/akgd112.pdf (170,400 bytes, sha256
  `a49c4e8297b2c2b518f505037506f1a539c4f8abc95e58e206e768c32a16ebac`). A copy of AKG's own
  sheet ("AKG Model D112 is a descendent of AKG's earlier D12 dynamic microphone"). Page 1:
  - "Dynamic pressure gradient", **cardioid**, **210 ohm**, XLR-M, **1.8 mV/Pa; -54 dB (re 1 V)**,
    20 Hz-20 kHz (+-10 dB), **40 Hz-17 kHz (+-3 dB)**, "THD virtually unmeasurable" at 1 % / 3 %,
    150 x 70 x 115 mm, 380 g, built-in windscreen;
  - the description: "a low resonance frequency", "very high mechanical linearity", "the
    response has been tailored to keep both bass drum and bass guitar clearly
    distinguishable in the mix" (a bass lift and a presence rise).
  Page 2: the graphical data: the response (20 Hz-20 kHz, -30 to +20 dB: about 0 dB mid-band,
  a bass bump of a few dB between 80 and 250 Hz, a presence bump of ~3 dB at 4-6 kHz, falling
  below -10 dB at 20 kHz and at 20 Hz; a dashed curve at 10 cm (proximity)) and the polar
  diagrams at 125, 250, 500, 1000 Hz (left half) and 2000, 4000, 8000, 16000 Hz (right half):
  **not digitized yet** (WP9's step 1).

## akg2: AKG D112 MKII quick user guide / technical data (2015)

- web: https://www.farnell.com/datasheets/2632014.pdf (788,099 bytes, sha256
  `7a76bc45806726300544c3423ff3679da3e6636dd8419183a051951f54718933`). The MKII: 1.8 mV/Pa
  (-55 dBV), **<= 200 ohm**, load >= 600 ohm, max SPL > 160 dB at 0.5 % THD, 20 Hz-17 kHz,
  455 g; the response (a vector graph, with the 10 cm proximity curve: +5 dB at 100-150 Hz)
  and polars (125 Hz-16 kHz) on page 2: sharper than the original sheet's scan.

## Not found

- The construction: no teardown, patent or service manual turned up. AKG's later text calls
  it a "large-diaphragm dynamic capsule, a bass resonance volume chamber and an integrated
  hum-compensation coil" (the original 1986 D112 "an acoustic bass chamber and a hum
  compensation coil", per distributors); the housing is 70 mm wide, the diaphragm's diameter
  and the chamber's volume are unpublished. micpedia.com and the Recording Hacks page
  (https://recordinghacks.com/microphones/akg-acoustics/d-112) were not read.

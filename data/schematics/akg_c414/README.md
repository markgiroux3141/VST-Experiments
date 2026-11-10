# AKG C414 B-ULS (for CHAINS_PLAN.md WP23)

`akg414b-uls_barryrudolph.pdf`: AKG Acoustics' C414B/ULS product sheet (2 pages; via Barry
Rudolph's site). AKG's C414 schematic and the GroupDIY thread can't be had (the user,
2026-11-10: don't ask again); WP23 is built by inference from the sheet (the user's decision).

The sheet's figures (page 1): condenser, externally polarized; omnidirectional, cardioid,
hypercardioid and figure-eight; **12.5 mV/Pa at 1 kHz on axis for all patterns**; 14 dB-A
self noise; **134 dB SPL wide-band, 140 dB at 1 kHz for 0.5% THD** (unpadded); **180 ohm**,
load > 1000 ohm; 12-48 V phantom; pre-attenuation -10 / -20 dB; bass cut 12 dB/octave below 75
or 150 Hz; dual back-to-back 1 in. (25 mm) diaphragms. Page 2: on-axis responses and polars per
pattern (vector paths, not digitized: flat within +-2 dB over 20-20 kHz, the omni and cardioid
~-2 dB at 20 kHz; read by eye, CHAINS_PLAN.md WP23's Notes).

What `config/circuits/akg_c414.yaml` infers: the CK12@1 capsule (the C12's), the four patterns
as the C12's equivalent polarizations, a 2N3819-class FET common source with gate bias and a
partly bypassed source, a BC550C emitter follower, an output transformer; the source
degeneration, the transformer's ratio and the gate bias fitted to the three bold figures, the
pads to their steps.

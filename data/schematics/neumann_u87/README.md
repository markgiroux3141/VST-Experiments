# Neumann U 87 / U 87 i (CHAINS_PLAN.md WP22)

## Sources

- `U87-schematic.png`: Neumann's "Kondensator Mikrophon U87, U87i" circuit diagram 10241 901
  21.7 (11.9.80), web: http://recordinghacks.com/images/mic_extras/neumann/U87-schematic.png
  (linked from https://recordinghacks.com/microphones/Neumann/U-87).
- `U87-schematic-1972.png`: the 1972 drawing, same site.
- `copi0042.pdf`: the U 87 i's operating instructions (September 1982), web:
  http://recordinghacks.com/pdf/neumann/copi0042.pdf: p. 10 the on-axis responses per pattern
  (digitized: `scripts/digitize_neumann_u87.py` -> `data/datasheets/neumann_u87_response.csv`,
  provenance `data/datasheets/neumann_u87.provenance.yaml`), p. 11 the polars (125 Hz, 1, 4, 8,
  12.5 kHz).
- `cata0120.pdf`: Neumann's transistor condenser microphone catalog (1970s), same site: the
  U 87's figures: pressure gradient, omni / cardioid / figure-8, 40-16,000 Hz, ~0.8 mV/ubar (8
  mV/Pa), load >= 1000 / 250 ohm, source 200 / 50 ohm, capsule 2 x ~50 pF, self-noise ~26 dB
  (DIN 45 405), 400 ubar (126 dB) at 0.5% THD, 48 +6/-8 V phantom at ~0.4 mA. (Also the KM 84's:
  cardioid, ~0.5 mV/ubar, 34 pF, 25 dB, 300 ubar: WP24.)
- RecordingHacks' page: the K87 is center-terminated, dual-backplate, dual-diaphragm, 34 mm
  capsule / 26 mm diaphragms, a 40 um plastic spacer; run at ~46 V in the U 87 (60 V by design).

## Readings (the 1980 drawing)

KK87 (2 x 50 pF); the backplates (signal) at contact 4: C4 470p to T1's gate, R6 1G (contact 4)
and R7 1G (gate) to 0 V, C1 470p from contact 4 to contact 1; -10 dB: C15 560p switched across
the capsule (a capacitive divider). Contact 6 at 47 V through R2 150k; R8 1M || C6 220p from
there to the contact-2 line (the front diaphragm), which C5 0.033u + R9 6k8 + R10 560 hold at
AC ground (R9 / R10 the calibration input). The pattern switch (contacts 1, 2, 3, 5, 7, 8, R1
300k, R3 1G, R4 / R5 68M, C2 10000p) sets the rear diaphragm's voltage. T1 (8280800006.4, a
selected FET: a 2N3819 or similar, ProSoundWeb's version list) a source follower: drain C7 1u
into the transformer 90415 (Ue1: 200 / 50 ohm), source resistor selected (*); R12 47k, R13
330k, C9 0.47u (bootstrap), R14 10k, R15 / R16 150k, C10 4.7u, C11 / C13 2.2u, C8 20u, C12 10u;
supply: phantom through R18 / R19 2k2 (paired), D1 TCR503 (a current regulator), Gr1 33 V
zener (the 33 V / 29 V rails), D2 1N4148, R22 2k2, R23 680k.

Corrected readings (while building): the K87's four leads bring out both backplates, joined by
C1 470p at AC, which is the dual capsule model's one backplate node (not a load to ground); C2
10000p joins the rear diaphragm to the front diaphragm's line at AC, so both diaphragms carry
the feedback; C3 10p feeds the bootstrapped polarization line (the drain's signal through C9)
into the backplates. With R8 / C6 / C3 that feedback costs 4.9 dB, pattern-independent.

Built (2026-11-10): `config/circuits/neumann_u87.yaml`, the capsule `K87@1` (fitted by
`scripts/fit_k87.py` through the circuit's feedback); numbers in CHAINS_PLAN.md WP22's Notes.

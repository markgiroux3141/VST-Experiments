# Neumann KM 84 (CHAINS_PLAN.md WP24)

## Sources (all via RecordingHacks, https://recordinghacks.com/microphones/Neumann/KM-84)

- `KM83-84-85-SM84_Schematic.pdf`: Neumann's circuit diagram "Kondensator-Mikrophon KM 83...KM 85,
  SRM 84", KM 84-930-12, 2.12.68 (web: http://recordinghacks.com/pdf/neumann/KM83-84-85-SM84_Schematic.pdf).
- `KM84-manual.pdf`: the KM 83 i / KM 84 i / KM 85 i operating instructions (scanned): p. 15 the
  technical data (KM 84 i: pressure gradient, cardioid, 40-20,000 Hz, 10 mV/Pa, 200 / 50 ohm,
  load 1000 / 250 ohm, 17 dB-A), p. 16 the on-axis responses (read by eye: scripts/fit_kk84.py's
  ON_AXIS, the scan's 1.3% tilt removed).
- `KM84-brochure.pdf` (Neumann's history: the first phantom-powered microphone, 1966; the -10 dB
  pad at the FET's gate, 130 dB with it), `KM84-parts.pdf`, `KM84i-catalogpage.jpg`.
- Neumann's catalog cata0120 (`data/schematics/neumann_u87/cata0120.pdf`): the KM 84 ~0.5
  mV/ubar (5 mV/Pa: the drawing's era; the later KM 84 i 10 mV/Pa), ~34 pF, 25 dB, 300 ubar.
- RecordingHacks: the KK 64 / KK 84, a 20 mm capsule with a crossed-slit backplate; at 135 deg
  ~14 dB down from 100 Hz to 18 kHz, "almost parallel" to the on-axis curve.

## Readings (930-12)

The capsule's electrode A polarized through R1 1G from +46 V (filtered by R5 / R8 10M, C6 /
C10 0.1u), the other at ground; C1 470p to T1's gate (R2 1G to ground); C2 3p3 from A to the
drain, and S1 (-10 dB) adds C9 15p there. T1 2N3819 common source: the source R3 (selected) ||
C3 1.5u 15V; the drain on R4 47K from +21.5 V (R7 10K from Gr1 ZF24's +24 V; C5 / C8 5u), printed
+10 V; C4 1u into Ue1 Bv. 107 (50 / 200 / 50 ohm taps); R6 56K from +46 V to the zener; R9 / R10
2k2 the phantom feed (paired), R11 / R12 47, R13 10.

Built (2026-11-10): `config/circuits/neumann_km84.yaml`, `KK84@1`: CHAINS_PLAN.md WP24's Notes.

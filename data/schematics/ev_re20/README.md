# EV RE20 (CHAINS_PLAN.md WP13)

Sources (provenance per value):
- EV's RE20 data sheet, Rev G 07/2010 (`https://products.electrovoice.com/download/970110`;
  PNGs of both pages here, curves in `data/datasheets/ev_re20_*.csv`, digitized by
  `scripts/digitize_ev_re20.py`): dynamic cardioid, 150 ohm balanced, **1.5 mV/Pa** at 1 kHz,
  45 Hz-18 kHz; response flat 80-6000 Hz, a broad +2.5 dB rise 6-14 kHz, -3 dB at 18 kHz and
  at 45 Hz; the **bass-tilt switch** (S1 / S2) tilts 4.5 dB down from 400 to 100 Hz; rear
  attenuation > 15 dB 45-10000 Hz, > 13 dB above; Acoustalloy diaphragm, low-mass aluminium
  coil, hum-bucking coil, steel case; 216.7 mm long, 54.4 mm widest, 49.2 mm body.
  **Wiring diagram (p.2):** XLR 2 / 3 balanced from the transformer secondary (XFMR, blue /
  black); C1 0.01 uF, L2 15 mH, C3 22 uF, L1 560 mH, C2 0.022 uF, R1 220 ohm, with S1 / S2
  (the bass-tilt network). Component placement to be read from the page image.
- US 3,115,207 (Wiggins, filed 1954, granted 1963: Variable-D: a front opening and two rear
  openings at different distances behind the diaphragm; the acoustic circuit and vector
  diagrams) and **US 3,378,649 (Mawby, filed 1964, granted 1968: the continuously
  Variable-D: the cavity behind the diaphragm connects to two parallel tubes along the body,
  each with a long slot covered by cloth (an acoustic resistance), the slots facing the
  casing's slot sets on opposite sides: the rear entry is a distributed transmission line;
  diaphragm after Moiser US 3,258,853; the magnet has an axial channel with a cloth layer and
  fibreglass plug as the damping; a terminating tube cavity behind)**, both from Google
  Patents. The RE20 is "dual-ported, continuously Variable-D" (EV); principal designer Tom
  Lininger (Rick Chinn's history, ProSoundWeb 2010).
- Not found: the diaphragm's diameter, the tubes' dimensions, the cloth's resistance, the
  coil's resistance. These are fitted to the sheet's curves (the D112's method).

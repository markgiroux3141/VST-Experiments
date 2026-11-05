# Tascam Portastudio sources

The chains build-out's WP4 (docs/CHAINS_PLAN.md: the SM57 and SM58 into a Portastudio),
found 2026-11-05. The modelled machine is the **424 (mk1, 1991)**: its mic input is one
op-amp. The 144 (1979) and 244 (1982), whose drawings are below too, have discrete input
stages (a JFET, PNP transistors) and wait for the JFET model (WP21; the 144 also the BJT,
WP10). Values in `config/circuits/tascam_portastudio.yaml` cite the 424's service manual as
`sm:` by part reference. None of the files is committed (scanned service documents); their
URLs, sha256 and sizes are below. Transcribed 2026-11-05 from the PDFs' page images
(rendered at 300-400 dpi; every value legible; the drawings print no voltages).

## The 424 mk1 (sm:)

TASCAM "424 Service Manual" (TEAC Professional Division), 36 pages, the schematics on pages
33-36 (PDF pages 32-35): BOTTOM PCB (1/2) the record / reproduce amplifiers, BOTTOM PCB (2/2)
the control section and the supply, MIX PCB, IN PCB / OUT PCB / wiring diagram.

- web: https://audiopro.r-massive.com/Tascam/Tascam%20%28TEAC%29%20424%20%28mk1%29%20Service%20Manual.pdf
  (10,167,098 bytes, sha256 `3c20b141c254a7f97dfe280eb47a6e69a40cb930b4c0451f398921259724ec34`),
  listed at web: https://zine.r-massive.com/tascamteac-cassette-recorder-manuals/.

### IN PCB (the jacks)

MIC/LINE inputs 1-4 "(-50 ~ -10 dBV)", unbalanced 1/4" jacks (J101-J401, tip and a switch
contact; the sleeve on A. GND). Per channel (channel 1):

| Ref | Value | Where |
|---|---|---|
| R101 | 1k | the tip in series |
| R102 | 100k | to ground |
| C101 | 1500p (CE) | to ground |

then J1 pin 1 "1 CH IN" to the MIX PCB's P5.

### MIX PCB, channel 1 ("CH 1"; channels 2-4 the same)

| Ref | Value | Where |
|---|---|---|
| C101 | 10/25V | P5 pin 1 to U101A's + (pin 4) |
| R101 | 100k | U101A's + to the lower bus (the half rail, A. +5V) |
| U101A | uPC4570HA (IC list: "U101 U301 uPC4570HA") | output pins "1,9" / 2 |
| R102 | 470k | output to - (pin 3) |
| C102 | 100p (CE) | across R102 |
| C103 | 10/25V | - to TRIM's wiper (2) |
| R103 | 10k (RD), TRIM | pin 1 at C104's far end, pin 3 to R104 |
| R104 | 100 | R103's pin 3 to A. GND |
| C104 | 10/25V | U101A's output to R103's pin 1 and S101 |
| S101 | INPUT | "A: TAPE, MIC/LINE ▶ L; B: TAPE; C: MIC/LINE" |
| R114 | 10k | the EQ's input node (S101 at C) to the bus |
| R105 | 120k | S101's other deck to the bus |
| R106 | 22k | into the EQ (U102B: EQ HIGH R107 100k (B) 10 kHz, EQ LOW R108 100k (B) 100 Hz, R109-R112, C105-C110) |
| R113 | 10k (A), INPUT FADER | then C111, R115 47k into U102A (R116 110k / C112 10p) |

U101A's gain with the wiper a fraction of the way along the track: (R102 + Rw) / (Rw +
R102 k), k the share of the track (plus R104) below the wiper, Rw the wiper's source
resistance (the two parts in parallel): 0 dB with the wiper at pin 1, (470k + 99) / (99 +
470k x 100 / 10100) = 98.9 (+39.9 dB) at pin 3: the jack's 40 dB range. "RD" isn't
explained on the drawing; the circuit file reads it as a reverse audio taper
(provisional), so the gain in dB follows the rotation about evenly. The other ICs on the
MIX PCB: U102-U107 NJM4565L.

### The supply (BOTTOM PCB 2/2)

+12 V into U702 (M5237L, an adjustable regulator) with R704 36k (F) / R705 5.6k (F): +10 V
as drawn (1.25 V x (1 + 36 / 5.6) = 9.29 V); U703B (M5218L) buffers R706 / R707 10k / 10k
as "RP +5V", U703A as "MX +5V": the op-amps' half rail. The audio op-amps run single-supply
about it.

## The earlier Portastudios (for WP21)

- **144** (1979): "TEAC Tascam 144 Portastudio Schematics", 6 pages.
  web: https://audiopro.r-massive.com/Tascam/TEAC%20Tascam%20144%20Portastudio%20Schematics.pdf
  (5,658,983 bytes, sha256 `1bf1fff5463aa988925d0e0d805e6ffe512df071901289ec73b8eb71005664f5`).
  MIXING AMPLIFIER, input A: R101 100 / C101 10/16V into Q101 (2SK68A, a JFET), Q102 and
  Q103 (2SA970, PNP), TRIM R131 10k, then the MIC/LINE / TAPE switch S101 into U101
  (NJM4558DF) with BASS / TREBLE.
- **244** (1982): "Tascam (TEAC) 244 Portastudio Service Manual", 63 pages.
  web: https://audiopro.r-massive.com/Tascam/Tascam%20%28TEAC%29%20244%20Portastudio%20Service%20Manual.pdf
  (5,113,225 bytes, sha256 `07920da355eea649148ccf61caa8f1ad0f8239a2ebd0fab22adbe22a57d3b327`).
  INPUT AMPL. PCB (PDF page 62): Q101 / Q102 a JFET differential pair into U101 (1/2), the
  TRIM VR01 10k (C), the MIC/LINE / TAPE switch S101, then the parametric EQ (U101 / U102)
  and the INPUT FADER into U103.

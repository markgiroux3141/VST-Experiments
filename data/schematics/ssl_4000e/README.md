# SSL 4000 E mic amplifier sources

The chains build-out's WP4 (docs/CHAINS_PLAN.md: the SM58, D112, U87, C414 and PZM into the
SSL), found 2026-11-05. This is the E-series channel's mic amplifier on the **channel
amplifier card 82E01** (transformer input), not the G-series' transformerless mic amp.
Values in `config/circuits/ssl_4000e.yaml` cite these as `sch:` (the 82E01 drawing, by
part reference), `jensen:` (the JT-115K-E60 sheet) or `web:`; SSL's Revival 4000 figures
are a reissue's and a reference only (`rev:`), never checked against.

None of the files is committed (the drawing carries SSL's "may not be reproduced" notice);
their URLs, sha256 and sizes are below. Transcribed 2026-11-05 from the PDFs' own page
images (847 x 1102 px scans; every value legible on 2-3x zooms; the drawing prints no
voltages).

## The drawing: SSL "Channel Amplifier Card", Drg. No. T82001·71 (sch:)

Rev. 16, 11-84, "REDRAWN"; "R58 & RC14B omitted on Rev 9 up"; page "1-14". Two sheets:
the mic input, mic amp, line input, line trim, routing (sheet 1); the channel input select,
phase, channel fader select, patch return, routing (sheet 2). Notes: "All FETs are J112
unless stated", "** = 1% tol, * = 5% tol", "T2-T9 5534N" (T1 too: drawn as an op-amp with
the same 22 pF compensation).

- web: https://www.ka-electronics.com/images/SSL/ssl_82E01.pdf (166,703 bytes, sha256
  `b099ac80629cb39bf805795be00d8b2ec3f82fe597894b03cd1d95329e38af38`), linked from
  web: https://groupdiy.com/threads/ssl-4k-e-mic-input.34585/ (the E-series mic amp is the
  82E01, "a Jensen transformer", SSL's tech Keith quoted).
- The same site has the 82E02 (the 02 "brown knob" EQ card, sha256
  `4f30c2e4f20454b8b6ae347c8f416ca32b5192f0459e6600f41e22f45db0a814`), not modelled.

### The mic input

| Ref | Value | Where |
|---|---|---|
| +8 / -7 | | the mic pins (hot / cold) |
| R1, R2 | 6K81 5% | phantom feed, +8 and -7 to the 48 V line (pin 2) |
| C1 | 3µ3 | the 48 V line to ground |
| R1 (upper bus), C4 3·3µF | | the phantom supply's filter, ahead of PHANTOM VOLTAGE ON / OFF |
| SW1A / SW1B | | the pad: at 5 / 6 the transformer straight across +8 / -7; at 4 / 9 the pad below |
| R4 | 649 5% | +8 to the transformer's top (shorted by SW1A at 5) |
| R5 | 645 5% | the transformer's bottom (pin 6) to -7 (shorted by SW1B at 6) |
| R6 | 165 5% | the transformer's top to pin 9 (to -7 by SW1B at 9) |
| R3 | 13K7 5% | pin 4 (to +8 by SW1A at 4) to -7 |
| BR / R | | the transformer's primary leads (brown, red) |
| Y / OR | | its secondary leads (yellow to T1's +, orange to ground; "OR BK W": black, white) |
| C2, R8 | 100pF, LINK | across the secondary: "C2, R8 (LINK) BBC ONLY" (not fitted) |
| R7 | 150K | the secondary's load to ground |

The pad: with SW1 at 4 / 9 the source sees R4 649 into the primary's top, R6 165 from
there to -7, the primary's bottom through R5 645 to -7, and R3 13K7 across the input.
Rev's "PAD Introduces a 20 dB pad ahead of the microphone preamp gain control".

### The mic amp

| Ref | Value | Where |
|---|---|---|
| T1 | 5534N | +: the secondary (Y); -: node 19 |
| C58 | 22pF CT | T1's compensation |
| R9, C3 | 619R 5%, 100µF 10V | node 19 to ground |
| R10, R11, C4 | 10K, 10K, 100µF 10V | T1's output to node 19 through R11 then R10, C4 from their junction to ground (DC feedback only) |
| R72, C54 | 100K, 220µF 25V | in parallel, T1's output to node X |
| R73 | 1M | node X to +ve (the electrolytics' polarization) |
| C55 | 220µF 25V | node X to the wiper (10) |
| MIC GAIN | 10K LIN | ends 19 (bottom) and 33 (top), wiper 10 |
| R69 | 619R 5% | 33 to T9's - |
| T9 | 5534N | +: R70 5K11 5% to ground; C57 22pF |
| R71, C56 | 10K7 5%, 100pF | T9's feedback |
| R46 | 100 | T9's output to RC1 (the channel input select's mic FET) |

T1 is non-inverting with the gain pot's wiper-to-19 part over R9 || R10 (583 ohm; C4 holds
R10's far end at AC ground) as its feedback; T9 is inverting with the wiper-to-33 part
plus R69 as its input resistor. With the wiper a fraction x of the way from 19 to 33:
gain = (1 + 10k x / 583) * 10.7k / (10k (1 - x) + 619): x = 0 gives 1.008 (+0.07 dB),
x = 1 gives 313.7 (+49.9 dB). With the transformer's +19.75 dB: about +20 to +70 dB (rev:
"Gain +20 dB to +70 dB typical").

### The channel input select (sheet 2)

| Ref | Value | Where |
|---|---|---|
| RC1 | J112 | R46's far end to the select bus (the mic; RC2: the line amp T3 through R47 100R; RC4: the bus to ground, a mute) |
| PHASE | | a 2-pole switch: the bus onto C36 (to T4's -) or onto C35 (to T4's +), the other grounded |
| R57 | 1M0 | between the two lines |
| C36, R55 | 10µ, 10K0 5% | to T4's - |
| C35, R60 | 10µF, 10K0 5% | to T4's +, with R54 10K0 5% and C40 100pF to ground |
| T4 | 5534N | R56 10K0 5% with C38 100pF from its output to - |
| C8, R48 | 100µF, 10R | T4's output to pin 28 |
| R16 | 47K | pin 28 to ground |

Into -: gain -1; into +: 0.5 x 2 = +1. The drawn position of the PHASE switch isn't
legible in the scan.

Power: +18 V and -18 V through R14 / R15 22R with C6 / C7 10µF (pins 15, 14; 0 V 12, 13).

## Jensen JT-115K-E (jensen:)

"Jensen JT-115K-E60 Microphone Input Transformer, double shielded version of JT-115K-E
... electrically identical to our standard JT-115K-E". The standard part's sheet has moved
off Jensen's site; the E60's was fetched from the Wayback Machine:
web: https://web.archive.org/web/2020id_/https://www.jensen-transformers.com/wp-content/uploads/2014/08/jt-115k-e60.pdf
(391,241 bytes, sha256 `31a4fc31b5ae07d489fa58cadaf823984cdfa2eec52e5c0d5b29529c1fab46fe`).

Test circuit 1 (its typical application): 150 ohm source (the mic) on RED / BRN, YEL to
an AD743's + with R1 150k to ground (the 82E01's R7), ORG to ground.

| Parameter | Conditions | Min | Typ | Max |
|---|---|---|---|---|
| Input impedance | 1 kHz, -20 dBu, test circuit 1 | 1.33 kΩ | 1.40 kΩ | 1.47 kΩ |
| Voltage gain | 1 kHz, -20 dBu | 19.65 dB | 19.75 dB | 19.85 dB |
| Response re 1 kHz | 20 Hz, -20 dBu | -0.50 dB | -0.26 dB | 0.0 dB |
| | 20 kHz, -20 dBu | -0.25 dB | -0.13 dB | +0.1 dB |
| THD | 1 kHz, -20 dBu | | 0.001% | |
| | 20 Hz, -20 dBu | | 0.065% | 0.15% |
| Maximum 20 Hz input level | 1% THD | -4 dBu | -2.5 dBu | |
| Output impedance | 1 kHz | | 17.0 kΩ | |
| DC resistance | primary (RED to BRN) | | 19.7 Ω | |
| | secondary (YEL to ORG) | | 2465 Ω | |
| Capacitance @ 1 kHz | primary to shield and case | | 475 pF | |
| | secondary to shield and case | | 205 pF | |
| Turns ratio | | 1:9.95 | 1:10.00 | 1:10.05 |

Front page: "Wide bandwidth: -3 dB at 2.5 Hz and 90 kHz", "Input impedance of 1.4 kΩ for
loading loss of 0.9 dB", "Noise Figure of only 1.5 dB". The response plot (2 Hz-200 kHz)
reads about -4.4 dB at 2 Hz and -0.25 dB at 20 Hz, rising slowly to 0 by ~2 kHz.

## SSL's Revival 4000 (rev:, a reissue: a reference only)

SSL, "Revival 4000 User Guide V1.1" (2025),
web: https://solidstatelogic.com/assets/uploads/downloads/Revival%204000%20User%20Guide%20V1.1.pdf
(2,570,242 bytes, sha256 `59adf0109ad9d4200efae25020d0154f577deb226ef0d94ba73901a7b2b0f8cd`):
"Classic SSL 4000 E Jensen transformer-balanced mic preamp"; the product page and SSL's
press release: "the exact same Jensen JT-115K-E transformer-balanced preamp circuit as
found on the original 4000 E-Series console". Its "Mic Input to Insert Send" figures:
gain +20 dB to +70 dB typical, a switchable 20 dB pad, input impedance 1.3 kΩ, maximum
input level > +23.2 dBu at +20 dB with the pad, EIN < -130.6 dBu (A, 70 dB, 150R),
response ±0.175 dB 20 Hz-20 kHz at any gain, THD+N < 0.00067% (-25 dBu in, 45 dB, +20 dBu
out, 1 kHz). Onset of clipping is taken as 1% THD there.

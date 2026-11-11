# EMI REDD.47 (CHAINS_PLAN.md WP28)

## Sources (fetched 2026-11-11; third-party, git-ignored: URLs and sha256 here)

- `EMI-REDD47.pdf` (sha256 7d4f3db9a8586807694715dd09b28b27b5340ad2542e1aa9e7d36b7c80c01301),
  web: https://www.sowter.co.uk/schematics/EMI-REDD47.pdf (linked from GroupDIY's REDD.47 threads):
  - PDF p. 1 and pp. 8-13: EMI Records & International Division, Record Engineering Development
    Dept., "Line Amplifier Type REDD.47", Ref. REDD.M47 (LAP/AV, August 1961; p. 4 dated 22.1.60),
    six typed pages. **txt:** below.
  - PDF pp. 14-15: the drawing **REDD.47/C1/1** "Line amplifier, cassette type" (E.M.I.
    International, Hayes; drawn 1.10.59), photocopied in two halves, turned 90 deg and extracted
    at 300 dpi as `REDD47-C1-left.png` (sha256 50f4a7eb0581681ec9745e49c18f36404dd8c6a1d81bd367e917b504e305ff11;
    the input, V1, V2, the gain switch) and `REDD47-C1-right.png` (sha256
    5e961117d7f81c056537c5c08a40e01d36f16d748361120ab1b8da4ed72eaa0d; T2, the HT filter and the neon
    stabilizers, the valve bases). **sch:** below.
  - PDF pp. 2-7: Revolution Recording's R.47 MkII pages (a reproduction; not used).

## txt: (REDD.M47)

Two valve stages, RC coupled, two loops of negative feedback. Input transformer with the highest
step-up the space allows; its leakage and secondary capacitance resonate, damped by R1, whose
loading C13 removes at low frequencies. First stage an EF86 "under conventional conditions", its
cathode decoupled not to earth but to R5 120 ohm, across which the overall feedback is developed.
Output stage both halves of an E88CC in parallel, cathode decoupled, RC coupled to the output
transformer; low voltage, high current. Feedback from its anode to its grid, developed across R8
(also the first stage's load): the second harmonics of the two stages (anodes in antiphase)
cancel. Overall feedback from the second stage's anode to the first's cathode; the gain switched
by its resistance; small phase-correcting capacitors across the feedback resistors (the output
transformer's leakage). **Voltage gain with a 200 ohm load between 2/5 and 2/6: 34, 40 or 46
dB.** Fine gain: R5 shunted by a 5k variable resistor and R6 240 (range 2.6 / 2 / 1.2 dB at 34 /
40 / 46). **Output 0 dBm matched, +6 dBm into 200 ohm with low output impedance, 1 V rms open
circuit, about +14 dBm on overload peaks.** Heaters 6.3 V a.c. at 0.5 A; H.T. 380-400 V from the
rectifier unit's reservoir, RC filtering into a pair of neon stabilisers, 30 mA. Rumble filter: a
1.8 uF condenser in series with the input line with the primary inductance (cut-off just below 30
c/s); with it in circuit the input impedance falls to 3k (0.6 dB loading loss from 200 ohm).
Signal-to-noise: equivalent hum and noise -120 dBm or better at the input (maximum gain).

## sch: REDD.47/C1/1 (traced 2026-11-11)

- Input 2/9, 2/10 ("200 ohm HIGH") crossed to 2/1, 2/2 into T1 REDD.A92, 1:7 (primary 1-4; "T1
  L 18 H: C14 1.8 uF; 45 H: 0.75 uF, adjust on test"); the rumble filter C14 in series and R24 3k
  ("to remove rumble filter disconnect 2-4 and connect 3-4"). The secondary 5 (earth) - 8; C13
  100p (adjust on test) in series with R1 100k across it; 8 to V1's grid (pin 9).
- V1 EF86 (M8195 Mullard): anode (pin 6, 73 V) on R2 100k from the 205 V line (orange; C1 8u,
  R7 51k from the 290 V line, 1.35 mA); screen (pin 1) on R3 390k, C3 0.47u to earth; g3 (pin 8)
  on the cathode (pin 3, 1.65 V); R4 1k from the cathode to the feedback node X with C2 100u
  across it; R5 120 to earth, shunted by VR1 5k (rheostat) + R6 240 ("limits 77-120 ohm").
- V2 E88CC (Mullard), both halves in parallel: anodes (pins 6, 1, 138 V) on R11 8.2k from the
  290 V line (18 mA); grids (pins 7, 2) through R25 / R26 1k from the node G; R10 1M from G to
  earth; C4 0.02u from N to G; R8 330k from V1's anode to N, R9 1.6M from V2's anode to N (the
  anode follower); cathodes (pins 3, 8, 3.7 V) on R12 200 with C6 100u.
- V2's anode through C5 1u to T2 REDD.A83 7:1 (primary 8 - 5 to earth; the secondary 1 - 4 with 2 /
  3 joined) to 2/5 (1) and 2/6 (4); R23 150 from 2/6 to 2/13 (the build-out to 200 ohm).
- The overall feedback (yellow) from T2's pin 8 (V2's anode after C5) to X: R13 47k, R14 10k ||
  C7 330p, then R15A 6k8 || R15B 120k || C8 680p; S1 shorts the anode end to the R13 / R14 node
  (40 dB) or to the R14 / R15 node (34 dB); at 46 the whole chain.
- Supply: H.T. 380 V (30 mA) through F1, R18-R21 1k and C9-C12 (8, 8, 20, 40, 40 u), V3 / V4
  (150C4 / OA2 neon stabilisers) to the 290 V line; R16 470k / R17 220k the meter's points.
- Not modelled: the H.T. supply (the 290 V line ideal), the heaters (a.c.), the alternative fine
  gain circuit (R5 150, VR1 500, R6 160), the metering, the build-out R23.

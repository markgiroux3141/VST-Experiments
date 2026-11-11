# Neumann U 67 (CHAINS_PLAN.md WP28)

## Sources (fetched 2026-11-11; the files are third-party, git-ignored: URLs and sha256 here)

- `U67-vintagewindings.pdf` (sha256 766000b8cac2c99f35ee7ca94fb05d4da6399fe3e2d168777019c538d8f47534),
  web: https://vintagewindings.com/gen%20pop/8299543VW8335/ProAudio1/Neumann%20U-67%20Tube%20Microphone.pdf:
  a history page and three drawings, extracted as:
  - `U67-schematic.png` (sha256 66f9a4977ee1d9382a9a9ec3963448a9cc9fbd1dc8101d01c8bccbe1612a0a93):
    Neumann's "Kondensator-Mikrophon U 67 / Condenser Microphone U 67", 1020390101, "gültig ab
    Gerät Nr. 10 000", statically measured voltages in ovals. **sch:** below.
  - `U67-p3.png` (sha256 59899a93baf8210d483261183a48167fe52f4e1b513bf01a68146c3cedb6507e): the power
    supply NU 67 u (NU67u-930-06): +210 V (B+) at 0.88 mA, -6.3 V (A-) at 0.2 A, a zener-regulated
    heater; not modelled (the mic's pins as ideal rails).
  - `U67-output-transformer.jpeg` (sha256 b7b54ef648c4052aab43aca2512b4a01df58a41b78858b30d718752e9a5860d6):
    Neumann's winding specification "Ausgangsübertrager U67" (09012-100-001.00, faxed by Sennheiser
    1996, "nur zur Information"): mu-metal "UI 30/25 x 0,35", stack 7.1 mm, core 0.05 kg,
    interleaved ("wechselschichtig"); windings I / Ia 390 turns 0.14 mm (<= 20 ohm each), II / IIa
    125 turns 0.06 mm (<= 37 ohm), III / IIIa 2700 turns 0.06 mm (<= 1050 ohm), Cu-foil screens S1 /
    S2; two coils (Spule 1: I, II, III; Spule 2: Ia, IIa, IIIa). **ot:** below.
- coutant.org's U 67 page (https://coutant.org/u67): `coutant_1966mar.pdf` (sha256
  764c3632bdb770954e03a9d14fd075bb22c73a375d2eeaa91f81eeb0e6663a15; Neumann's specification sheets
  U 67 - 910 - 02 - 01, March 1966: **spec:** below; p. 7 the frequency responses, digitized:
  `data/datasheets/neumann_u67.provenance.yaml`; p. 8 the polar diagrams), `coutant_1963mar.pdf`
  (operating instructions 1963), `coutant_1960.pdf` (the 1960 background sheet),
  `coutant_1992sep.pdf` (the reissue's 1992 instructions; not used), `coutant_u67freq.gif` (p. 7's
  chart as a GIF).

## spec: (1966, p. 5)

Two pressure transducers, switchable omni / cardioid / figure-8; 30-16 000 cps; **output 1.1 / 2.0
/ 1.4 mV/ub (11 / 20 / 14 mV/Pa) omni / cardioid / figure-8 across 1000 ohm**; load >= 1000 (250)
ohm; source 200 (50) ohm +-20% (60-15 000 cps); capsule approx. 1 x 50 pF (cardioid), 2 x 50 pF
(omni, figure-8); noise <= 5.5 uV (DIN 45 405) = 25 dB (cardioid), 28 dB (omni, figure-8) above
2e-4 ub; **max SPL >= 125 ub (116 dB) for 0.5% THD at 40, 1000 and 5000 cps** (about 400 ub with
the pre-attenuation); **amplification of the preamplifier at 1 kcps: -2.0 dB (cardioid), 0 dB
(omni, figure-8)**; switchable attenuation approx. 10 dB; calibrating input 600 ohm unbalanced; 1
x EF 86. p. 2: below 30 cps attenuated before the grid, 40 cps up unaffected; the limit shifts to
100 cps by the head's switch; the transmission reduced ~10 dB by the third switch; "The microphone
tube operates as an anode amplifier into an output transformer with separate feedback winding".

## The circuit, traced (2026-11-11; the drawing upscaled 3x)

- The capsule KK 67 (2 x CA 50 pF): front diaphragm -> contact 2 -> g1 (-1.6..-1.8 V); backplate
  -> contact 1 (+59 V); rear diaphragm -> S3's arm (the pattern switch on the head): its first
  contact on contact 4 (= the grid line in the head: omni, the rear on the front), the second open
  (cardioid: the rear floating, unpolarized), the third on contact 5 (+120 V: figure-8, opposite
  polarization). C1 0.01u from contact 4 to contact 5 (in figure-8 the rear on the grid at AC).
- S5 (the pre-attenuation, "-10 dB") puts C10 270p from contact 2 (the grid) to contact 1 (the
  backplate).
- The EF 86 as a triode: g2 on the anode, g3 on the cathode, the cathode at 0 V, the heater from
  the A- line (-5.7..-6.3 V at the tube) to 0 V. The anode (+75 V) on R14 150k from +210 V (0.8-1.0
  mA), into Ü1 (BV 12) through C9 1u/450 V.
- The grid bias: R10 15k from the A- line, R11 6.81k to 0 V (-1.6..-1.8 V at their junction W);
  R9 68M from W to the node V (C7 0.01u to 0 V), R8 500M from V to g1.
- The polarization: R15 3.3M from +210 V to the node Y (+120 V), R13 2.21M from Y to Z (+59 V),
  R12 2.21M from Z to W; R2 68M from Z to contact 1 (C4 0.01u from Z to 0 V); R16 68M from Y to
  Q (C8 0.01u to 0 V), R1 500M from Q to contact 5. (The oval at Z reads +59 V; R15 reads "3,3 M":
  with it Y = 119.5 V, Z = 58.9 V by arithmetic.)
- Ü1 (BV 12): the primary (III + IIIa, 5400 turns) from C9 to 0 V; the output windings I and Ia
  (390 turns each) strapped by S4: series 200 ohm, parallel 50 ohm; out on St1 pins 2 / 1, C12 /
  C13 1600p from them to the shield. The feedback winding II + IIa (250 turns) in series, its start
  (II "ws", dotted like the primary's start) on node F, its end on node E; R18 475 ohm across it
  (F to E); R19 10k from E to the calibration node (St1 pin 6, C16 1600p), R20 61.9 ohm from there
  to 0 V. C17 80-160 pF (selected) from the anode to F.
- The feedback network (into the backplate): C3 0.01u from F to node A; C2 0.01u from A to contact
  1 (the backplate). From A: R3 825k to D (C5 0.01u to 0 V), R6 681k from D to C (C6 0.01u to 0 V),
  R7 681k from C to B, R5 2.21M from B to A; R4 825k from A to contact 6. S1 (on the head: contacts
  3 and 6) puts the anode (contact 3) on R4: the 100 Hz bass cut. S2 (inside: the "wire bridge"
  of p. 2) puts the anode on B: the built-in cut below 30 cps (the flat setting has it).
- Not modelled: the NU 67 supply (ideal +210 V and -6.3 V), C11 / C14 / C15 (RF and supply
  bypasses), the cable, the heater's hum.

## ot: Ü1 / BV 12

The winding specification is the reissue's (Sennheiser's fax, 1996) but its counts give the
forum's figures for the original (primary : feedback 21.6, primary : output 6.9 at 200 ohm:
GroupDIY "transformer in the u*67", https://groupdiy.com/threads/transformer-in-the-u-67.10934).

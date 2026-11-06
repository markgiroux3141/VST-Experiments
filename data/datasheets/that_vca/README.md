# THAT / dbx Blackmer VCA sources

For device builder B11 (the SSL bus compressor's VCAs) and its Blackmer-cell macro part.
Downloaded 2026-11-06. Cite as `that2180:`, `that2181:`, `that2150:`, `dnNNN:`, `aes4055:`
or `pat:` with the page or figure.

## Files

| File | What | Source |
|---|---|---|
| `THAT_2180-Series_Datasheet.pdf` | 2180A/B/C pre-trimmed Blackmer VCA, Document 600029 Rev 02, © 2008, 12 pp | web: https://thatcorp.com/datashts/THAT_2180-Series_Datasheet.pdf |
| `THAT_2181-Series_Datasheet.pdf` | 2181A/B/C trimmable, Document 600030 Rev 03, © 2016, 12 pp | web: https://thatcorp.com/datashts/THAT_2181-Series_Datasheet.pdf |
| `THAT_2150-Series_Datasheet.pdf` | 2151 / 2150A / 2155 ("Based on dbx technology"), Rev. 10/25/96, marked OBSOLETE, 10 pp | web: https://thatcorp.com/datashts/THAT_2150-Series_Datasheet.pdf |
| `AES4055_An_Improved_Monolithic_VCA.pdf` | G. K. Hebert, "An Improved Monolithic Voltage-Controlled Amplifier", AES 99th Convention, New York, Oct 1995, preprint 4055 (C-5), 35 pp: the 2180's design at transistor level | web: https://thatcorp.com/datashts/AES4055_An_Improved_Monolithic_VCA.pdf |
| `dn127.pdf` | DN127 "Upgrading Modular VCAs": dbx 202 Black Can, 202C Gold Can, 2001, 202X / XL, THAT 202XT / R / XTC application circuits | web: https://thatcorp.com/datashts/dn127.pdf |
| `dn128.pdf` | DN128 "What's a PTAT Temp. Coefficient": the cell's temperature coefficient derived | web: https://thatcorp.com/datashts/dn128.pdf |
| `dn121.pdf` | DN121 VCA symmetry auto-trim ("THD might typically average 0.5-0.7%" untrimmed) | web: https://thatcorp.com/datashts/dn121.pdf |
| `dn124.pdf`, `dn137.pdf` | interchanging 2181Lx / 215x; substituting 2180 / 2181 for 2150 (trim networks per part) | web: https://thatcorp.com/datashts/dn124.pdf, .../dn137.pdf |
| `dn106.pdf`, `dn110.pdf`, `dn103.pdf` | distortion troubleshooting; noise modulation and control-port oscillation; off isolation | web: https://thatcorp.com/datashts/dn106.pdf etc. |
| `dn00A.pdf`, `dn01A.pdf` | basic compressor / limiter design (2180 + 2252); the mathematics of log-based dynamics processors | web: https://thatcorp.com/datashts/dn00A.pdf, dn01A.pdf |
| `THAT_202_modular_datasheet.pdf` | THAT 202XT / 202XTC / 202R modular VCAs (dbx 202 replacements), 2 pp, 2004 | web: http://www.thatcorp.com/datashts/202data.pdf |
| `THAT_202R_schematic.pdf`, `THAT_202XT_schematic.pdf` | THAT's schematics of the 202R / 202XT modules (eight paralleled VCA ICs with 10k input resistors and a control buffer). Protel drawings, 2002 / 2005, marked "not to be reproduced ... without the written permission of THAT Corporation" | web: http://www.ka-electronics.com/images/THAT_Corp/VCA_202R.pdf, .../VCA_202XT.pdf (linked from https://groupdiy.com/threads/dbx-202x-schematic.51331/) |
| `US3714462_blackmer_multiplier.pdf` | D. E. Blackmer, "Multiplier circuits", US 3,714,462, filed 1971-06-14, granted 1973-01-30: the original Blackmer cell | web: https://patentimages.storage.googleapis.com/a5/31/ce/937fc563f24d21/US3714462.pdf |
| `US3681618_blackmer_rms.pdf` | Blackmer, "RMS circuits with bipolar logarithmic converter", US 3,681,618 (1972) | web: https://patentimages.storage.googleapis.com/64/d8/b4/fda9584a44805f/US3681618.pdf |
| `US4234804_dbx_signal_correction.pdf` | G. Bergstrom (dbx), "Signal correction for electrical gain control systems", US 4,234,804 (1980): the correction scheme of the 202C generation (THAT's history credits Bergstrom with it) | web: https://patentimages.storage.googleapis.com/14/81/18/fba47878e4d5ca/US4234804.pdf |
| `US4454433_welland_multiplier.pdf` | D. R. Welland (dbx), "Multiplier circuit", US 4,454,433 (1984): the 8-transistor class AB cell of the 2150 | web: https://patentimages.storage.googleapis.com/85/ff/90/e1b43c9588db40/US4454433.pdf |

THAT's history page (web: https://thatcorp.com/a-brief-history-of-vcas/):
- the Black Can 202 used discrete transistors "individually matched in an oven", with
  symmetry and log-slope trims;
- the next generation (Bergstrom) used pre-matched discrete devices and a patented
  error correction;
- the 2001 (Bob Adams) was class A with an 8-transistor cell;
- the 2150 (Welland) was a class AB 8-transistor IC;
- the 202X / XT modules are paralleled ICs.

## The figures

| Parameter | 2180 (A / B / C) | 2181 (A / B / C) | 2150 series | dbx 202 family (DN127, 202 datasheet) |
|---|---|---|---|---|
| Control constant | Ec+ 6.0 / 6.1 / 6.2 mV/dB min / typ / max; Ec- -6.1 mV/dB, at TA 25 °C (Tchip ≈ 35 °C) | same | same, 6.1 mV/dB | 202 Black Can and THAT 202R: -6 mV/dB; 202C, 202X, XL, XT, XTC, 2001: -50 mV/dB (-20 dB/V) |
| Tempco of the constant | +0.33 %/°C, re Tchip 27 °C; gain at Ec = 0 is 0 dB at any temperature (PTAT: dn128) | same | +0.33 %/°C | +0.33 %/°C (202C / X / XL / XT); 202XTC compensated |
| Gain law | Gain(dB) = (Ec+ - Ec-) / (0.0061 (1 + 0.0033 ΔT)) | same | same | |
| Gain at Ec = 0 | ±0.1 / 0.15 / 0.2 dB | same | same | |
| Control linearity | 0.5 % typ, 2 % max, -60 to +40 dB | same | same | |
| THD 1 kHz, 0 dBV in, 0 dB gain | 0.005 / 0.010 / 0.030 % typ (max 0.010 / 0.020 / 0.050), no trim | 0.0025 / 0.004 / 0.005 % typ, trimmed | 2151 0.004 %, 2150A 0.005 % (180 µA, trimmed); 2155 0.006 % (150 µA) | 202XT: 0.003 % at 0 dB, 0.02 % at 20 dB gain |
| THD +10 dBV in, -15 dB gain | 0.020 / 0.030 / 0.040 % | 0.018 / 0.025 / 0.035 % | 0.025-0.05 % at ±15 dB | |
| THD -5 dBV in, +15 dB gain | 0.020 / 0.030 / 0.040 % | 0.018 / 0.025 / 0.035 % | | |
| Untrimmed THD (cell mismatch) | | | | DN121: typically 0.5-0.7 % for trimmable parts with no trim |
| Output noise, 20 Hz-20 kHz, Rout = 20 k | -98 dBV at 0 dB, -88 dBV at +15 dB | same | same | |
| Noise vs resistors | 10 k in / out: -104 dBV; 40 k: +6 dB noise and lower THD at high level | same | | |
| Noise modulation | -94 dBV with a 50 µA rms signal at unity (4 dB); 5534 driving the control port: -92 dBV (6 dB) | same | | |
| Off isolation | 115 dB typ at Ec+ = -360 mV, Ec- = +360 mV | same | same | |
| Idle cell current | 20 µA (core transistors) | same | same | |
| Bias | ISET 2.4 mA (5.1 k to -15 V): 570 µA biases the IC, the rest is Icell; ISET ≥ peak(Iin) + peak(Iout) + 570 µA; V- pin ≈ -2.85 V (four Vbe) | same | V- 5.1 k | |
| Signal current | ≤ 1 mA peak for best THD; 0.35 mA rms typ, 1.5 max | same | 175 / 125 µA rms typ | |
| Gain-bandwidth | 20 MHz | 20 MHz | 6 MHz | |
| Slew rate | 12 V/µs (Rin = Rout = 20 k) | same | | |
| Output pin capacitance | ~15 pF (needs a feedback cap on the I-V op-amp: 22 pF in the test circuit) | same | 47 pF in the 2150 test circuit | |
| Control-port source | < 50 Ω; 100 Ω + 1.5 nF to ground cures inductive-drive oscillation; 10 µV of audio on Ec raises THD > 0.01 % (2nd harmonic) | same | | |
| SYM pin | leave open (wafer trimmed); internal 25 Ω between pin 4 and pin 2 | trim: 50 k pot across ±15 V through 680k (A) / 220k (B) / 130k (C) into pin 4 with the internal 25 Ω; VSYM -0.5..+0.5 / ±1.5 / ±2.5 mV | 51 Ω external pin 2-4, 50 k pot via 470k (2151) / 390k (2150A) / 300k (2155); VSYM ±1.6 / ±2 / ±2.5 mV | 202: Rsym 1M + 50k pot; 202C: 1M + 50k; 202X / XL: 200k; XT / R: 100k |

Recommended application circuits:
- **2180 / 2181 (Fig. 2):**
  - input through 10 µF + 20 k into pin 1 (keep Rin ≥ 10 k: lower values raise the
    high-frequency THD);
  - output pin 8 into an OP275 I-V converter, 20 k ∥ 22 pF;
  - Ec+ pin 2, Ec- pin 3, SYM pin 4;
  - V- pin 5 through 5.1 k to -15 V; GND pin 6; V+ pin 7.
- **2150 (Fig. 3):** the same, with an LF351, 20 k ∥ 47 pF, and the 51 Ω SYM network above.
- **dbx 202 Black Can (DN127 Fig. 2):** Cin 2µ2, Rin 100 k, Rout 100 k, Cfb 10 p, a 5532
  I-V converter, Rsym 1M, Radj 50 k, -6 mV/dB.
- **202C Gold Can (Fig. 3):** Rin = Rout = 50 k (otherwise as the Black Can), -50 mV/dB.
  DN127: "the input and output impedances were cut in half ... the control voltage
  constant was changed to -50 mV/dB".
- **2001 Silver Can (Fig. 4):** class A, 13 k / 13 k, 4µ7, Cfb 68 p.
- **202X / 202XL / 202XT / 202R (Figs. 5-8):** 6k04 in, 7k32 out, 22µ, 100 p.
  - 202X: eight ICs, each with 10 kΩ in series with its input (internal 1.25 kΩ), Rsym
    200 k.
  - THAT 202R: -6 mV/dB.

## The cell at transistor level (2180-series datasheet Fig. 5; AES 4055)

**The datasheet's simplified circuit (Fig. 5):**
- an internal OTA holds pin 1 at virtual ground. It drives the emitters of Q1 (NPN, with
  diode D1) and, through the "Voltage Bias Generator", Q3 (PNP, with D3). These log the
  input current to a voltage V3;
- Q2 / D2 (NPN) and Q4 / D4 (PNP) antilog it into the output pin 8, held at virtual
  ground by the external op-amp;
- Ec+ (pin 2) is the base of Q1; Ec- (pin 3) is the base of Q2;
- an internal 25 Ω resistor runs between pin 2 and pin 4 (SYM), which sits on the PNP
  side's base node. The wafer symmetry trim is a current Iadj through it (PTAT per
  AES 4055). The external 2181 trim divides into this same 25 Ω;
- Icell from V- (pin 5) biases the core class AB.

"Q1 through Q4" in the text are the four core pairs, each a transistor plus a
diode-connected transistor in series. DN128 and AES 4055 describe it as the 8-transistor
cell of reference [8] (Welland's patent).

**AES 4055** (Hebert 1995):
- Fig. 3: Blackmer's original 4-transistor complementary cell (1971).
- Fig. 4: the 8-transistor topology the 2180 uses. Q5-Q8 plus the correction resistors
  Rc1-Rc4 cancel the parasitic base and emitter resistances. The cancellation condition
  is in Eq. 13. "the required correction resistors are each less than 1 ohm" thanks to
  very large multi-stripe devices. With them the control scaling halves (Eq. 15:
  Iout / Iin = exp(Vc / 2VT)).
- Section 2.2, mismatch: the transfer function with arbitrary saturation currents
  (Eq. 16, Appendix A). The even-order term is set by the net Vbe mismatch between the
  top and bottom pairs. The symmetry voltage that cancels it is Eq. 18: 2 VT times the
  log of a ratio of the eight saturation currents, so PTAT. The PDF's text layer garbles
  the equation; read it from the page image.
- Grades map to net Vbe mismatch: prime < 0.01 % THD at 1 V rms and unity corresponds to
  ±35 µV; the lowest grade, < 0.05 %, to ±175 µV. R1 (the internal symmetry resistor)
  is nominally 27 Ω.
- The input amplifier is a transconductance stage (Q9-Q14, Fig. 12): Q14 class A at
  ~2 mA, R5 sets gm, C2 gives a 10 MHz zero, R6 a 2 MHz zero. The process is dielectric
  isolation, with no collector-substrate capacitance.
- Section 3: the noise analysis (shot noise of the class AB core).

**The patents** carry the full circuits with element numbers: Blackmer 1973, Bergstrom
1980, Welland 1984.

## Not found

- **The dbx 202C internal (transistor-level) schematic and its control-port impedance.**
  A Pro Audio Design Forum thread reportedly shows the 200 / 202 / 202C / 2001 internals
  (https://www.proaudiodesignforum.com/forum/php/viewtopic.php?p=18726, 403 to scripts),
  and GroupDIY's dbx 160VU thread links a "dbx 200 VCA.pdf" whose host is gone. Both are
  listed for the user in `data/schematics/ssl_bus_comp/README.md`.
- **The THAT 2155 / 2159 datasheets**: not on thatcorp.com any more (the 2150-series sheet
  covers the 2155).

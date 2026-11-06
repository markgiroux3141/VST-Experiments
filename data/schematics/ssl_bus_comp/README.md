# SSL 4000 E / G bus compressor sources

Device builder B11 (docs/DEVICE_CANDIDATES.md, "Next: dynamics and EQ"), step 1, found
2026-11-06. The console's mix-bus compressor is not a card of its own. It lives on two
master-section cards of the 4000 E:
- **82E26** "Quad Bus Mix Amps, Patch Returns, VCA, Compressor Side Chain": one card per
  mix bus. Each card has the bus amp, the program VCA and its own side-chain VCA and
  rectifier.
- **82E27** "Compressor Time Constants, Quad Fader Autofader": one card shared by all
  buses. It has the attack / release network, the make-up and threshold summers that make
  the two control voltages, and the autofader.

Values in a future `config/circuits/ssl_bus_comp.yaml` should cite these as `sch26:` /
`sch27:` (by part reference on the drawing), `gyraf:` (the GSSL redraw; a DIY derivative,
not the original) or `web:`.

**The drawings carry SSL's notice:** "Copyright SSL All rights reserved. This document may
not be reproduced in any form without the written permission of SSL". The same notice is
on the 82E01 that `data/schematics/ssl_4000e/` keeps uncommitted. Nothing in this folder is
git-ignored yet, so whether to commit the files is the user's call.

## Files

| File | What | Source | sha256 | Bytes |
|---|---|---|---|---|
| `ssl_82E26.pdf` | SSL drawing T82026·71, 2 pages: the left and right halves of one sheet, 847 x 1100 px colour scans (100 dpi) | web: http://www.ka-electronics.com/images/SSL/ssl_82E26.pdf (from the index http://www.ka-electronics.com/images/SSL/ssl_drawings_index.htm) | `bc88ea008eb41dea6cbc255b2fd9cf7c6cf873f84bdda9f1ab68619cab89e696` | 157,608 |
| `ssl_82E27.pdf` | SSL drawing T82027·71, 2 pages (halves), 847 x 1102 px grey scans | web: http://www.ka-electronics.com/images/SSL/ssl_82E27.pdf | `5c8841bc05d1f4d0d6cddaa39618ec1f0b4ee8678f29b9b7bb160605feba9c8a` | 201,140 |
| `gyraf/ssl_sch.gif` | Gyraf Audio "SSL Mixbus Compressor Clone" (GSSL) schematic, rev #9, 06-2013, 4715 x 5963 px | web: https://gyraf.dk/gy_pd/ssl/ssl_sch.gif | `e0605d0ab586fdd50c3fe9e363f98b3c8ead71edc21398395ea23399e78a3041` | 389,811 |
| `gyraf/ssl.pdf` | GSSL schematic, component overlay and PCB artwork (PCB rev #9, SCH rev #7), 4 pages, A4 | web: https://gyraf.dk/gy_pd/ssl/ssl.pdf | `a295aeb63c7a98c339ece731ee2d031f6b3c5b0ef5c4a8844788471fa51984d4` | 519,880 |
| `gyraf/ssl.htm` | Gyraf's GSSL page (text: circuit description, specs, mods, errata) | web: https://gyraf.dk/gy_pd/ssl/ssl.htm | `ad1f214b45941ec3dc5b0c3c3b5f3299d32ac7749672fb64573db9031e458f9f` | 23,979 |
| `gyraf/ssl_complist.htm` | GSSL parts list | web: https://gyraf.dk/gy_pd/ssl/ssl_complist.htm | `eb700458ff8db28dd4afec42b2c85cbea86a2027cfd735c79e041c2f64785e06` | 4,870 |
| `gyraf/ssl_82e26.gif`, `gyraf/ssl_82e27.gif` | Gyraf's 800 px copies of the two SSL cards, smaller than the PDFs | web: https://gyraf.dk/gy_pd/ssl/ | `19e5203b...`, `c21b06b5...` | 129,791 / 143,602 |
| `gyraf/unity_gain.jpg`, `ratio_2180.jpg`, `thresh_red.jpg`, `error_4.gif` | Gyraf's overlay close-ups for the three 2006 mods, and a build error | web: https://gyraf.dk/gy_pd/ssl/ | see `sha256sum` | |
| `gyraf/danfield.htm` | link page (Danfield 726, an alias) | web: https://gyraf.dk/gy_pd/ssl/danfield.htm | | 742 |

Transcribed 2026-11-06 from the scans' embedded images at 2-4x zoom. Values marked (?) were
not fully legible. A `*` after a reference is SSL's own mark. On the 82E01 it means a
tolerance class ("** = 1%, * = 5%"); these two drawings print no legend, so on them `*`
probably means 1% (every `*` value is an E96 value such as 30K1, 909R, 4K32).

## The topology (settles B11 step 1's open question)

**The schematic shows a feedback loop around an auxiliary VCA, fed from a feedforward tap.
The program VCA runs open loop.** Per 82E26:

1. The bus amp's output (T2, a balanced receiver after the patch insert) feeds two places:
   - the **program VCA A1** (DBX 202C) through C9 2µ2 and R12* 15K0;
   - the **side-chain VCA A2** (also a DBX 202C) through R11 47K, then R30 47K. This feed
     is taken **before** A1, so it is a feedforward tap.
2. A2's output (I-V converter T5) goes to the rectifier (T6, T7). The rectified level, out
   through D6 to pin 42 ("D"), is the detector's output. It goes to 82E27.
3. On 82E27 the detector charges the attack / release network. T1 (LF351N) buffers the
   timed voltage, which then drives two summing amps:
   - T2 (CA324) adds MAKE UP and the master-fader / automation terms and drives **B**
     ("AUDIO VCA's", pin 15 on 82E27 = pin 16 on 82E26), A1's control;
   - T3 (LF351N) adds THRESHOLD and drives **C** ("SIDE CHAIN VCA's", pin 32 on 82E27 =
     pin 33 on 82E26), A2's control.
4. So the detector reads A2, and A2 is driven by the detector's own output: the loop closes
   through the side-chain VCA. A1 gets the same timed voltage (plus make-up) open loop. The
   threshold offset goes only to A2: in Gyraf's words, it makes "the added gain in the
   sidechain VCA look to the rectifier like there's more signal coming in".
5. For the keyed unit (B11 step 6): a key into A2's input in place of R11's feed keeps the
   loop closed around the key, so the ratio holds when keyed. That is the property the
   670 lacks.

Several buses: each 82E26 has its own A2 and rectifier. Their D6 outputs are diode-ORed on
the common pin 42 / D line into the one 82E27, so the bus with the highest level controls
the compressor ("greater of two peaks"). B and C are bussed to every 82E26, so all program
VCAs track. A forum post describes the same: "Pins 16, 33 and 42 of the 82E26 are bussed
from one board to the other and common at the 82E27 sidechain card" (web:
https://proaudiodesignforum.com/forum/php/viewtopic.php?p=61; the page returns 403 to
scripts and was read only through search snippets).

**No external side-chain input** exists on these cards. The side-chain is fed only through
R11 from the bus amp. COMP IN/OUT mutes it with a FET (TR4).

**The VCA is the dbx 202C**, printed as "DBX 202C" on both A1 and A2 of the 1984 drawing.
Gyraf says his 1985 SSL 4044E had the dbx 202XT. THAT's sources:
- THAT DN127 (`data/datasheets/that_vca/dn127.pdf`): the 202C "Gold Can" is a discrete
  Blackmer cell with dbx's correction circuitry, a recommended Rin = Rout = 50 kΩ, a
  symmetry trim and **-50 mV/dB**;
- the THAT 202 datasheet: the 202C, -X and -XL have "a control constant of -20 dB/Volt"
  (the same figure, -50 mV/dB), "with a predictable +0.33%/°C temperature drift".

SSL also used the dbx 2150 in its channel compressors (Gyraf). The 202X / 202XT modules
are 8-10 paralleled 2150-class ICs (THAT DN127; `THAT_202R_schematic.pdf` and
`THAT_202XT_schematic.pdf` show eight paralleled VCA ICs with a CV buffer).

## 82E26: drawing T82026·71

Title block: "QUAD BUS MIX AMPS, PATCH RETURNS, VCA, COMPRESSOR SIDE CHAIN", Solid State
Logic, Drg. No. T82026·71, page 8-24. Rev 8, 3.8.84, "REDRAWN" (V.B.). Scan stamp
"MY 163618 D".

### Mix bus amplifier (sheet left, top)

| Ref | Value | Notes |
|---|---|---|
| pin 5 / pin 8 | | MIX BUS SIGNAL / MIX BUS 0V (the virtual-earth bus pair) |
| C1, C2 | 470µF 16V each | in series (back to back) from the bus to the input |
| L1 | 220µH | in series with C1, C2 |
| D8, D9 | (type not printed) | anti-parallel clamp across the input pair |
| R1, C21 | 100K, (C21 value not printed) | bus 0 V line to ground |
| TR1, TR2 | LM394H | two supermatch pairs (halves a, b) as a discrete differential input stage |
| R2*, R3* | 2K43 | collector loads to the +rail |
| L2, L3 / R4, R5 | 22µH / 30R | emitter degeneration, each L in parallel with its R |
| TR3, R48 | BC184, 82R | tail current source |
| R49, D10, D11, C27 | 47K, 2 diodes, 10µ 35V | TR3's base bias |
| T1 | NE5534 | second stage ("NB": pins 5 / 8 not used); C28 100p |
| R24, R25, C26 | 1M, 100K, 10µF 35V | a bias divider at the input |
| R26, R58 | 1M, 100K | DC feedback divider |
| R50* | 15K0 + 1K0 | AC feedback |
| C29, C30, R52* | 10µ 35V, 10µ 35V, 15K0 | feedback network to T8 |
| T8 | NE5534 | R53* 15K0 ∥ 100p feedback; R54 15K at the + input; output R57 47R to pin 10 |
| R51, R55 | 100R, 100R | ±18 V decoupling |

### Insert / patch return and receiver

| Ref | Value | Notes |
|---|---|---|
| pins 10→12, 9→13 | | normalled links, drawn crossed (the patch send / return) |
| R56 | 10R | pin 9 to ground |
| R61 | 5K | across 12-13 |
| C3, C4 / C5, C6 | 2 x 10µF 35V each leg | coupling, bipolar pairs |
| R7*, R10* | 30K1, 30K1 | T2's input and feedback (C7 33p across R10) |
| R8*, R9* | 10K0, 10K0 | + leg divider (C8 100p across R9) |
| T2 | NE5534 | unity-gain balanced receiver |

### Program VCA A1 and output (sheet right, top)

| Ref | Value | Notes |
|---|---|---|
| C9 | 2U2 | T2's output to R12 |
| R12* | 15K0 | input current resistor into A1 |
| A1 | DBX 202C | "BOTTOM VIEW" pinout drawn; +15 with C23 10µ, -15 with C22 10µ |
| R13* | 909R | from pin 16 (B: the audio-VCA CV from 82E27) to A1's control pin |
| (no ref)* | 4K32 | from pin 15 to the same control node (pin 15's source is not on this card) |
| R14 | 1M5 | A1's symmetry pin to RV1's wiper |
| RV1 | 50K | "DISTORTION NULL", across ±15 |
| T3 | NE5534 | I-V converter: R16* 15K0 ∥ C10 22p; R15 470R from + to ground; CT 22p compensation |
| R49 | 47R | T3's output to pin 19 |
| pins 19→23, 20→24 | | normalled links (the second insert) |
| R17, R18 | 10R, 15K | pin 20 to ground; across 23-24 |
| C11, C12 / C13, C14 | 2 x 10µF 35V each leg | coupling |
| R19*, R22* | 30K1, 30K1 | T4's input and feedback (C15 33p across R22) |
| R20*, R21* | 10K0, 10K0 | + leg divider (C16 100p across R21) |
| T4 | NE5534 | output receiver; CT 22p |
| R23 | 10R | to pin 28 (the bus output) |

R12 = R16 = 15K0, so A1's 0 dB is unity voltage gain. That is lower than DN127's 50 k
recommendation for the 202C; peak signal current at +20 dBu is about 0.94 mA.

### Side chain (sheet left bottom, right bottom)

| Ref | Value | Notes |
|---|---|---|
| R11 | 47K | T2's output (pre-A1) to the side-chain node |
| COMP IN/OUT SW 2a | | "NOT ON PCB": +18 through 100n / 100R to pin 17 (A); 240R + LAMP to -18 |
| R28 | 100K | pin 17 to -18 |
| R29, D1 | 100K, diode | pin 17 to TR4's gate |
| TR4 | J175 | P-channel JFET from the side-chain node to ground: COMP OUT shorts the side chain |
| R30 | 47K | the side-chain node into A2 (with R11, 94K from T2: A2's input current is ~16 dB below A1's) |
| A2 | DBX 202C | side-chain VCA, "BOTTOM VIEW"; ±15; **no symmetry trim drawn** |
| R31* | 909R | from pin 33 (C: the side-chain CV from 82E27) to A2's control |
| T5 | TL081 | A2's I-V: R32 33K ∥ C17 22p; R33 470R + to ground |
| C18 | 6µ8 35V | coupling into the rectifier |
| T6 | TL081 | inverting half-wave: R34 20K in, R35 20K with D2 out, D3 clamp |
| R36 | 10K | T6's rectified output to T7's summing node |
| R37 | 20K | C18's node direct to T7's summing node |
| T7 | TL081 | summing node (pin 2) = full-wave sum (2 x half-wave minus direct) |
| R38 | 1M | T7's summing node to node X |
| D4 | diode | node X to T7's output (pin 6) |
| D5 | diode | T7's output to its summing node (clamp) |
| D6 | diode | T7's output to pin 42 (D): one bus card's vote in the diode-OR |

Ratio network (sheet right, bottom). Node X = R38 / D4 = the common end of R39, R40, R41:

| Ref | Value | Notes |
|---|---|---|
| R39 / R43 | 510 K / 1M6 | divider from X to -12 V (pin 34); tap = switch contact 38 |
| R40 / R44 | 270K / 3M9 | divider from X to -12 V; tap = contact 39 |
| R41 / R45 | 68K / 620K | divider from X to +12 V (pin 35) |
| diode | (type not printed) | anode at the R40 / R44 tap, cathode at the R41 / R45 tap |
| R42 | 1M2 | contact 37 to -12 V |
| RATIO SW | "NOT ON PCB" | common = pin 36, wired to T7's summing node (the R36 / R37 / R38 node); contacts 37, 38, 39; drawn at 38 |
| C24, C25 | 10µF 35V | ±12 V decoupling |

The switch adds a second feedback path from X (through R39's or R40's tap) to T7's summing
node, or an offset (R42) from -12 V. That changes the rectifier's gain and offset, and so
the loop gain around A2: Gyraf's "the ratio switch actually changes the threshold a bit".
**The drawing does not say which contact is 2:1, 4:1 or 10:1.** Derive it in the
simulation and check it against the panel.

Power: pins 31 / 32 +15 / -15 V (from 82E27's regulators); 49 +18 V through R46 10R with
C19 10µF 35V and 2 x 10nF; 51 -18 V through R47 10R with C20 10µF 35V and 2 x 10nF; 53, 54,
55 0 V.

## 82E27: drawing T82027·71

Title block: "COMPRESSOR TIME CONSTANTS, QUAD FADER AUTOFADER", Drg. No. T82027·71, page
8-26. Rev 7, 2.84, "REDRAWN" (V.B.); Rev 8, Dec 85, "R59, R60, C15 ADDED" (DM). "ASSY.
REV. No 8". Scan stamp "MY 151214 D".

### Attack / release (sheet left, bottom)

The front-panel switches aren't on the card. The drawing shows ATTACK on pin 46 and RELEASE
on pin 6, and both wipers join the timing node, which goes to pin 11 and then T1's + input.

| Ref | Value | Pin / panel |
|---|---|---|
| D (pin 41) | | the detector bus from the 82E26s |
| R1 | 820R | 43: ATTACK 0.1 ms |
| R2 | 2K7 | 44: 0.3 ms |
| R3 | 8K2 | 45: 1 ms |
| R4 | 27K | 46: 3 ms |
| R5 | 82K | 47: 10 ms |
| R6 | 270K | 48: 30 ms |
| C6 ∥ R12 | 0µ47 35V ∥ 180K | 5: RELEASE 0.1 s |
| C5 ∥ R11 | 0µ47 ∥ 270K | 6: 0.3 s |
| C4 ∥ R10 | 0µ47 ∥ 560K | 7: 0.6 s |
| C3 ∥ R9 | 0µ47 ∥ 1M2 | 8: 1.2 s |
| C1 ∥ R7, then C2 ∥ R8 | (0µ47 35V ∥ 91K) in series with (6µ8 35V ∥ 750K) | 9: AUTO |
| | "C3, 4, 5, 6, 0µ47 35V" | note on the drawing |
| T1 | LF351N | buffer: + input = timing node, R13 3M3 from + to ground; R14 470K output to - |
| R15, meter, D13 | 2K0, GR meter, 1V5 zener | T1's output to the meter, D13 across it |

AUTO pairs a fast section (0.47 µF ∥ 91K, τ ≈ 43 ms) with a slow one (6.8 µF ∥ 750K,
τ ≈ 5.1 s), each across its own capacitor, in series. Read off the PDF scan (C1's value is
legible on the full page, "C1 0µ47 35v", "C2 6µ8 35v"). **The GSSL pairs them the other
way round** (750K ∥ u47, 91K ∥ 6u8), and Gyraf's text says "91k+6u8 and 750k+u47". Check
with a better scan before building AUTO.

Single τ values of the RELEASE settings with 0.47 µF: 85 ms (180K), 127 ms (270K), 263 ms
(560K), 564 ms (1M2). They don't scale like the panel's 0.1 / 0.3 / 0.6 / 1.2 s. The panel
figure is presumably a recovery time in dB terms (the CV is log-domain: a linear-in-volts
discharge is linear in dB). Measure it in the profile.

### The two control voltages (sheet right, bottom)

| Ref | Value | Notes |
|---|---|---|
| T2 (pins 12-14) | 1/4 CA324 | AUDIO VCA's summer |
| R19 | 100K | T1's output (the timed CV) to T2's summing node (pin 13) |
| R25 | 100K | T2's feedback (gain -1 for the timed CV) |
| R20 | 620K | from MAKE UP's wiper (pin 12) |
| MAKE UP | 25K LIN | between pins 21 and 10, across D3 |
| D2, R16, D3 | diode, 4K7, 12V zener | from A (pin 16: the COMP IN/OUT line) to the pot's top; make-up has supply only with COMP IN |
| R24 | 33K2 | from the master-fader computer-return buffer into the same node |
| T2 (pins 8-10) | 1/4 CA324 | master-fader return buffer: R53 10K from pin 20, R54 10K ∥ C13 1µ5 50V ∥ D12 zener |
| R51, C12 | 100R, 100nF | out to B (pin 15) "AUDIO VCA's" |
| T3 | LF351N | SIDE CHAIN VCA's summer |
| R21 | 100K | timed CV in |
| R27 | 100K | feedback |
| R22 | 360K | from THRESHOLD's wiper (pin 24) |
| THRESHOLD | **value not printed** | ends "+15 dB" (pin 40) and "-15 dB" (pin 39) |
| R17, R18 | 3K9, 3K9 | pin 40 to +12 V, pin 39 to -12 V |
| R52, C11 | 100R, 100nF | out to C (pin 32) "SIDE CHAIN VCA's" |

### Supplies on 82E27

| Ref | Value | Notes |
|---|---|---|
| T12 | 7815 | +15 V (pin 30) from +18 |
| T11 | LM337 | -15 V (pin 31): R60 9K53, R59 909R, C15 100n 25V, C28 47µ 35V (Rev 8) |
| T10, T9 | 78L12, 79L12 | +12 V (pin 34), -12 V (pin 33); C27, C26 47µ 35V |
| T13 | 78L05 | +5 V to the fader (pin 28); C30 47µF 35V, C24 / C25 1µ5 35V |
| C16-C23 | 1µ5 35V | "C16-23 = 1µ5 35V" |
| R46, R47 | 10R, 10R | ±18 V in (pins 49 / 51) with C9 / C10 10µ 25V |

The autofader (sheet left, top: T4-T8, AUTO FADE switch, SET FADE TIME 250K log, SET
OFFSET 50K at TP1, MASTER FADER, BC212LB lamp driver) is not part of the compressor and
isn't transcribed. It only reaches the audio CV through the master-fader terms.

## Gyraf's GSSL (gyraf:), and how it differs from the SSL cards

Gyraf Audio (Jakob Erland), "The SSL Mixbus Compressor Clone", page dated 10-05-2006,
schematic rev #9, 06-2013. "Cloned from our good old SSL4044E desk, dating back from '85."
A free DIY design (non-commercial use only). Its stated specs:
- ratio 2:1, 4:1, 10:1;
- attack 0.1 / 0.3 / 1 / 3 / 10 / 30 ms;
- release 0.1 / 0.3 / 0.6 / 1.2 s, and 2.4 s (Auto);
- make-up 0-20 dB;
- threshold -20 to +20 dBm;
- input 50 kΩ, output 100 Ω, both electronically balanced;
- response < 15 Hz to > 35 kHz within 3 dB;
- noise < -80 dB;
- distortion "About -75dB unadjusted. Mostly 2nd harmonic."

Differences from 82E26 / 82E27:

| Item | SSL 82E26 / 82E27 | GSSL rev #9 |
|---|---|---|
| Side chain | one side-chain VCA and rectifier **per bus card**, diode-ORed | **one** side-chain VCA (THAT2181) fed by L + R summed through 47K + 47K ("SC IN" points; internal, not a key jack) |
| VCAs | dbx 202C (program and side chain) | THAT 2181 / 2180 (or dbx 202 / 2150), each with a "DBX202 emulation" buffer: CTRL through 1K / 120R into an NE5534 follower driving pin 3 (Ec-); 10K in series with pin 1; 3K9 Iset to -15; SYM pin 4 via 68R to ground and 10K to the DIST TRIM pot |
| Program VCA in / out | R12 15K0 / R16 15K0 | 27K in ("two 15K resistors changed into 27K", the 2006 unity-gain mod) / 15K ∥ 100P I-V (1/2 NE5532) |
| In / out stages | discrete LM394 bus amp, NE5534 insert receivers | NE5534 balanced input (22K x 4, 33p), 2 x NE5532 balanced output (10K, 100R) |
| Side-chain VCA I-V | R32 33K ∥ C17 22p | 33K ∥ 100P (1/4 TL074) |
| Rectifier | TL081s: 20K / 20K / 10K / 20K, 1M | the same values on TL074 sections, 1N4148 |
| Ratio network | 510K, 270K, 68K, 1M2, **1M6**, 3M9, 620K | 510K, 270K, 68K, 1M2, **1M8**, 3M9, 620K |
| Attack | 820R ... 270K | the same |
| Release | 180K / 270K / 560K / 1M2 with 0µ47 | the same values, tantalum u47 |
| AUTO | 0µ47 ∥ 91K + 6µ8 ∥ 750K (as read) | u47 ∥ 750K + 6u8 ∥ 91K (as drawn) |
| Timing buffer | LF351N, R14 470K, R13 3M3 | 1/4 TL074, 470K ∥ 10P, 3M3 |
| Audio CV summer | R19 100K, R25 100K, R20 620K, make-up 25K lin on a 12 V zener fed from COMP IN | **120K*** (100K for a dbx 2150; for the 2180 "disconnect pin 4"), 100K ∥ 100P, make-up 50KA via 620K, the BYPASS switch disconnects make-up |
| Side-chain CV summer | R21 100K, R27 100K, R22 360K, threshold pot (value unprinted) with 3K9 ends | 100K in, **56K ∥ 100P** feedback, threshold 50KA via **220K**, a 47K added at the pot's top (the 2006 "threshold de-sensitize" mod) |
| Ratio fix for THAT parts | n/a | "the 100K resistor marked has to be replaced by a 127K resistor to compensate for higher input current sensitivity on the new chips" (the page; the drawing marks 120K*) |
| Supply | console ±18 V, local 7815 / LM337 / 78L12 / 79L12 | its own ±15 V (7815 / 7915) and ±12 V (78L12 / 79L12) |

Gyraf on the sound: "the 202 may tend to be a little more transparant than the 2150", and
"the distortion ... tends to be almost exclusively second harmonic". Untrimmed THAT parts:
THAT DN121 puts untrimmed log / antilog VCA THD at "typically ... 0.5-0.7%".

## Open questions

1. **Ratio contacts.** Which of contacts 37 / 38 / 39 is 2:1, 4:1, 10:1 isn't printed.
   Derive it from the simulation's GR curves.
2. **THRESHOLD pot value.** Not printed on 82E27. GSSL uses 50K A (log); the 82E27's 3K9
   end resistors suggest a low-value linear pot. Ask for a better scan or a G-series card.
3. **AUTO pairing** (0µ47 with 91K or with 750K): the scan and Gyraf disagree. Check a
   better scan.
4. **Pin 15 of 82E26** (the 4K32* to A1's control node) is not traced on these sheets.
   Probably a master-fader or automation input. Its far end sets A1's control-divider
   ratio (909R / 4K32).
5. **The 202C's control port.** THAT gives the 202C as -50 mV/dB (-20 dB/V), but not its
   port impedance. With 909R in series, the effective constant depends on it. The 202C's
   internal schematic was not found (see "To fetch").
6. **E vs G series.** These are E-series master cards (1984-85). Whether the G series'
   bus compressor used the same 82E26 / 82E27 (or a later card with dbx 2150 / THAT parts)
   wasn't found. The reissues (Bus+, G-Comp, Bus Compressor 2) aren't sources for
   values.
7. **Not printed on these drawings:** C21's value, D-series diode types, and which bus(es)
   in a stereo desk feed the compressor.

## To fetch (the user)

Walled, or blocked to scripts:

- The dbx 200 / 202 / 202C / 2001 internal schematics, a thread on the Pro Audio Design
  Forum (403 to scripts):

  ```
  https://www.proaudiodesignforum.com/forum/php/viewtopic.php?p=18726
  ```

- "dbx 200 VCA.pdf" from GroupDIY's dbx 160VU thread. The link there is dead, and the
  Wayback Machine refused scripted access:

  ```
  http://www.acsoundstudio.com/DIY/160vu/dbx%20200%20VCA.pdf
  ```

- The GroupDIY thread itself (attachments need a login):

  ```
  https://groupdiy.com/threads/dbx-160vu-clone.30006/page-9
  ```

- The Pro Audio Design Forum post on the 82E26 / 82E27 wiring and the GSSL's differences:

  ```
  https://proaudiodesignforum.com/forum/php/viewtopic.php?p=61
  ```

- A G-series bus compressor card schematic, if the user has a source (GroupDIY's
  "SSL Logic card schematics" post):

  ```
  https://groupdiy.com/goto/post?id=1177180
  ```

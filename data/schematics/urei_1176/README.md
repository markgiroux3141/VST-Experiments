# UREI / Universal Audio 1176 sources

Device builder B12 (docs/DEVICE_CANDIDATES.md), step 2, found 2026-11-06. Two
revisions' schematics:
- **the original "blue stripe"** (Universal Audio drawing R-10743, revision A, 1967). The
  default B12 target: input transformer, FETs in the preamps, class-A output;
- **the 1176LN Rev F** (UREI drawing R11914, 3-15-73). A complete, cleanly drawn LN
  revision with the push-pull output.

The Rev D drawing found is too blurred to transcribe (see the files).

Values in a future `config/circuits/urei_1176.yaml` should cite `schA:` (R-10743) or
`schF:` (R11914) by part reference, `ua:` (UA's 2002 reissue manual, a reissue: a
reference only) or `web:`.

## Files

| File | What | Source | sha256 | Bytes |
|---|---|---|---|---|
| `waltzingbear/Urei_1176_page_1.JPG` | R-10743 rev A, left half: input, VVR, signal preamp, GR control amp, meter amp (1364 x 943 px, 125 dpi) | web: http://www.waltzingbear.com/Schematics/Urei/Urei_1176_page_1.htm ("Urei 1176 original 'blue stripe'") | `f471f6063e22f3958822a95b227d043e92078ef2a5f9beb87331c3bc273d5c0e` | 93,058 |
| `waltzingbear/Urei_1176_page_2.JPG` | R-10743 rev A, right half: preamp (overlap), line amp, ratio switch B decks, power supply, notes, title block (1426 x 976 px) | web: http://www.waltzingbear.com/Schematics/Urei/Urei_1176_page_2.htm | `7508a113274714e363ba1df1b6b9d300faa7ffd618c7d6e4f3fa650a16cd1e97` | 102,531 |
| `waltzingbear/Urei_1176LN_series_D.JPG` | R-10743, a later issue: "effective serial no. 217 & subsequently", with a hand annotation "REMOVED" at the VVR. 1259 x 961 px, **mostly illegible** | web: http://www.waltzingbear.com/Schematics/Urei/Urei_1176LN_series_D.htm | `428a0ebc1457b447ea7c69a42059f64de0b170cbc62bc7d1f6d67963103939e8` | 108,307 |
| `waltzingbear/Urei_1176LN_mod.JPG` | hand-drawn LN board (Waltzing Bear: "hand drawn schematic of LN board") | web: http://www.waltzingbear.com/Schematics/Urei/Urei_1176_LN_mod.htm | `bdbc6b6049d571c5877b2f1d6ae849a582c61c74d1ec7f414f90edc00610931a` | 36,189 |
| `waltzingbear/Urei_1176LN_series_F_page_1.JPG` ... `_page_3.JPG` | R11914, 1176LN, "effective for S/N suffix F", three pages (1040-1058 x 1322 px), clean and legible | web: http://www.waltzingbear.com/Schematics/Urei/Urei_1176LN_series_F_page_1.htm (_2, _3) | `b311affd...`, `2be42ed9...`, `ec097233...` | 79,399 / 96,682 / 71,654 |
| `2N5457-D.PDF` | onsemi 2N5457 / 2N5458 data sheet, 2N5457/D Rev. 6 (Feb 2010), 8 pp: ratings, the table (VGS(off), IDSS, Yfs, Ciss, Crss per part), Figures 1-3 (2N5457 only: noise figure, drain and transfer characteristics of one unit, VGS(off) ~-1.2 V) | web: https://www.onsemi.com/download/data-sheet/pdf/2n5457-d.pdf (fetched by the user, 2026-11-06) | `d547280c34509502772575b907afb58426da1e4795766b036d3a3e46eefcaf66` | 262,967 |
| `ua_1176ln_reissue_manual_rev1.02.pdf` | Universal Audio 1176LN (reissue) User's Guide, part 1176-M01, Rev 1.02, © 2000; 18 pages: specs, calibration, theory of operation with partial schematics (Figs 2, 3, 5); "We patterned our reproduction on the D/E versions" | web: https://c3.zzounds.com/media/1176LN_manual-1a90c9dff91ec30316551923e877c4d0.pdf | `9801ff228392f9cae460f39d1fd7f00ef4589f1a3fa7207ac9c400f247ddf786` | 120,227 |

Waltzing Bear's index: http://www.waltzingbear.com/Schematics/Urei.html ("Visit the JBL Pro
web site for more info and full manuals"). The JBL Pro service PDF that older posts cite
(`http://www.jblproservice.com/pdf/Vintage JBL-UREI Electronics/UREI-1176LNmanual.pdf`) and
Berklee's copy (`http://classes.berklee.edu/mpe/pdf_files/manuals_pdf/urei_1176ln.pdf`) no
longer resolve.

Revision history (Mix, "1176 revision history", web:
https://www.mixonline.com/recording/1176-revision-history-372048):

| Rev | Date | Serials | Changes |
|---|---|---|---|
| A | 20 June 1967 | 101-125 | Peerless 600 Ω, then UTC, input transformer; FET + bipolar preamp; 2N3053 class-A line amp; UA-5002 (later 5002A) output transformer |
| AB | 20 Nov 1967 | 125-216 | some resistor values changed; bypass capacitors around the resistor feeding the GR FET |
| B | Nov 1967 - Jan 1970 | 217-1078 | all-bipolar signal preamp |
| C | 9 Jan 1970 | 1079-1238 | first blackface, "LN" module (epoxy) and Q-bias pot on a Rev B board |
| D | into 1973 | 1239-2331 | LN on the main PCB |
| E | to 15 Mar 1973 | 2332-2611 | 110 / 220 V transformer |
| F | from 15 Mar 1973 | 2611-7052 | push-pull output (1109-style), op-amp meter driver |
| G | | 7053-7651 | differential amplifier in place of the input transformer |
| H | | 7652- | silver panel |

The R-10743 sheet here is titled "revision A". It has FET preamps (Q2, Q4) and no LN, so
it is the Rev A / AB circuit; the AB value changes aren't marked on it.

Transcribed 2026-11-06 at 2-6x zoom. (?) = not fully legible.

## Rev A: Universal Audio drawing R-10743 (schA:)

Title block: "UNIVERSAL AUDIO DIV., STUDIO ELECTRONICS CORP., 11922 Valerio St., No.
Hollywood, Calif 91605. Solid State Limiting Amplifier Model 1176". Drawing R-10743.
Revision table: "A, Revised to date, (date: 1967, day / month not legible)".

Notes printed on the drawing:
1. Q1 & 11: selected. Q5 & 6: matched to low & high hFE. Q7, 8, 9 & 10: hFE 250 or above.
   Q12 & 13: identical hFE ±10%.
2. Unless otherwise noted: all resistor values in ohms, 1/2 W, 5%; all capacitor values
   in microfarads; all switches normally opened.
3. Parts located at front panel are marked F.P.
4. Line voltage ranges: 100-130 V, 200-260 V.
5. Last parts: R82, C26, CR9, Q13. Omitted: R60, R78 (as read).

**Active parts:**
- Q1 (VVR), Q2, Q4, Q11: an N-channel JFET labelled with a house or vendor number that
  reads like "DF6021 4Q" or "DP602 14Q" (?). It is **not** a JEDEC number. See open
  questions.
- Q3, Q5, Q7, Q8, Q9, Q10, Q12, Q13: 2N3707.
- Q6: "2N3053 or 2N2270".
- CR1: 1N914.
- CR2, CR3: FD333.
- Power supply: CR4-CR7 "TS4 or equiv., 750 mA, 400 PIV"; CR8 "30V, 10W, 1N2989A or
  equiv."; CR9 "10V, 1W" (type reads "G10T5" (?)).

### Input and VVR

| Ref | Value | Notes |
|---|---|---|
| R1A | (value not printed) | "T" attenuator series pot (the INPUT control) |
| R1B | (F.P.) | the T's shunt leg |
| R2, R3 | 620, 1/4 W each | T attenuator arms |
| T1 | "UTC O-12 or equivalent" | primary 1-5, secondary 6 (GRN), 7, 8 (BRN); see transformers below |
| R4 | 270 | secondary load |
| R5 | 27K | series resistor of the VVR divider ("R5 and the FET essentially comprise a voltage divider", ua:) |
| Q1 | FET (see above) | "VVR" shunt to ground |
| C1 | .15 | from the drain node toward the gate network |
| R6 | 560K | gate network |
| R7 | 560K | gate network to the GR control line |
| C22 | .22 | on the GR control line at the gate |

On rev A the gate is fed from C1 / R6 / R7 (the drain-to-gate feedback that the LN
revisions refine with 2.2 M / 200 pF pairs). The exact node wiring at C1 / R6 is hard to
follow at this resolution. Check it against a better scan.

### Signal preamp

| Ref | Value | Notes |
|---|---|---|
| C2 | .15 | coupling |
| R8 | 10K | series into Q2's gate |
| R9, R10 | 3.9M, 2.2M | Q2 gate bias divider |
| Q2 | FET | |
| R11, R12 | 10K, 1K | Q2 source; C3 6.4 µF 40 V across R11 |
| R13 | 47K | Q2 drain load |
| Q3 | 2N3707 | |
| R14 | 22K | Q3 collector |
| R15, C5 | 20K, 80 µF 25 V | Q3 emitter |
| C4 | 80 µF 25 V | rail decoupling |
| R16, C6 | 47K ∥ 35 pF | feedback |
| R17 | 8.2K | |
| C7 | 1 µF 40 V | to OUTPUT GAIN |
| R23 | 250K, 2 W (F.P.) | OUTPUT GAIN (the ratio switch's A deck taps the line here) |
| C8 | .15 | coupling to Q4 |
| R24, R25 | 15M, 3.3M (?) | Q4 gate bias |
| Q4 | FET | |
| R26 | 33K | Q4 drain |
| R27, R28 | 12K, 560 | Q4 source; C9 6.4 µF 40 V |
| C10 | 1 µF 40 V | to Q5 |

### Signal line amp

| Ref | Value | Notes |
|---|---|---|
| Q5 | 2N3707 | R29 1.2M ∥ C11 47 pF collector-base |
| R30, CR1 | 120K* (T+C), 1N914 | Q5 base bias (T+C = test and calibrate, factory set) |
| C12 | 80 µF 25 V | |
| Q6 | 2N3053 or 2N2270 | class A |
| C14 | .033 | |
| T2 | UA-5002 | primary BRN / BLK / WHT-BLK / WHT-RED; secondary BLU, YEL-ORG strapped, RED, SLT, VIO; out to X, Y |
| R3? | 560 + C15 .0047 | series RC across T2 (reference number not legible; reads R35 (?)) |
| R3? | 8.2K | feedback (reads R36 (?)) |
| R34, C16 | 8.2K ∥ 35 pF | feedback |
| R32 | 39 (?) | T2's WHT-RED lead to ground |

### Compression ratio switch (four interlocked push buttons, two decks)

| Ref | Value | Notes |
|---|---|---|
| A deck | R21 56K 1/4 W, R20 56K 1/4 W, R19 130K 1/4 W (?), R22 56K 1/4 W | 4:1 S1A, 8:1 S2A, 12:1 S3A, 20:1 S4A: a ladder from the OUTPUT GAIN line feeding the GR control amp |
| B deck | R61 470 1/4 W, R62 470 1/4 W, R63 2.7K 1/4 W, R64 1.2K | S1B-S4B: a ladder to V10 (the 10 V rail), setting the rectifier bias (threshold) per ratio |

### GR control amp, attack / release

| Ref | Value | Notes |
|---|---|---|
| S5 | | GR DISABLE switch, "located on R55" (the ATTACK pot's OFF) |
| C17 | 1 µF 40 V | input coupling |
| R36, R37 | 1M, 560K | Q7 base bias |
| Q7, Q8 | 2N3707 | phase splitter, then emitter follower |
| R38 | 47K | Q7 collector |
| R39, R40, R41 | 4.7K, 2.4K, 270 | |
| R42, R43 | 180K, 47K | |
| R45 | 560K* (T+C) | |
| Q9, Q10 | 2N3707 | second inverter / follower |
| C18 | 80 µF 25 V | |
| R47, R48, R49, R50 | 47K, 8.2K, 2.4K, 180 | |
| R46, R51 | 22K, 8.2K | |
| C19, C20 | 6.4 µF 40 V | coupling to the two rectifier diodes |
| R52, R53 | 47K, 47K | |
| CR2, CR3 | FD333 | full-wave rectifier (anti-phase drives) |
| C21 | 80 µF 25 V | |
| R54 | 620 | in parallel with part of R55 |
| R55 | 25K, 1/2 W (F.P.) | ATTACK TIME CONTROL |
| R56 | 5M, 1/2 W (F.P.) | RELEASE CONTROL |
| R57 | 270K | across R56's end section |
| R58 | 39K (?) | |
| R59 | 2K | "Q" BIAS ADJ, P.C. board trim pot |

The timing capacitor is C22 (.22) at the VVR gate. Attack charges it through R55 (with
R54); release discharges it through R56 / R57 toward the Q-bias point.

### GR meter driver amp

| Ref | Value | Notes |
|---|---|---|
| Q11 | FET (selected) | tracks Q1 from the GR line through R65 |
| R65 | 3.9M | |
| Q12, Q13 | 2N3707 | differential pair (identical hFE ±10%) |
| R67, R79 | 3.9K, 15K | R79 to +30 V |
| R68 (T+C), 2 x 820 | | emitter network (reference numbers partly illegible) |
| R70 | 4.7K | tail |
| R71 | 2K (F.P.) | "0" set |
| R72, R73, R74, R76 | 1.5K, 680, 1K, 18K | |
| R75 | 2K | P.C. board null adj |
| R66 | 10K | |
| R77, R7? | 8200, 3600 | METER FUNCTION (F.P.): +8, +4 ranges (the 3600's number reads R18 / R78 (?)) |

### Power supply

| Ref | Value | Notes |
|---|---|---|
| T3 | UA-8?1A (?) | 115 V / 230 V strapping |
| F1 | 3AG, 1/4 A, slo-blo | |
| CR4-CR7 | TS4 or equiv., 750 mA, 400 PIV | |
| R80 | 250, 5 W | |
| C23, C25 | 2000 µF, 50 V | |
| C24, C26 | 2000 µF, 30 V | |
| CR8 | 30 V 10 W zener, 1N2989A or equiv. | |
| CR9 | 10 V 1 W zener | |
| R81, R82 | 1.5K, 1K | |
| rails | "+30 V @ 50 mA, ripple < .25 mV with load"; "10 V, ripple < 5 mV with load" (sign not legible; Rev F: -10 V) | |

## Rev F: UREI drawing R11914 (schF:)

Title block: "UNITED RECORDING ELECTRONICS INDUSTRIES, Los Angeles, California. Solid State
Limiting Amplifier Model 1176LN". Date 3-15-73, checked L.E., drawing R11914. "Rev. A,
changed for value corrections only, 7-2-75, L.E." "EFFECTIVE FOR S/N SUFFIX 'F'".

Notes printed on the drawing:
1. All resistor values are in ohms, 1/2 W ±5%.
2. All capacitor values are in microfarads.
3. Switches are normally open.
4. Q1 and Q10 are selected.
5. Q12, 13, 14 and 15: hFE 250 or above.
6. The \* symbol indicates a factory-set value.

**Active parts:**
- Q1 (VVR), Q10 (meter): "UREI 13-0027", a house number for a selected N-channel JFET;
- Q2, Q3, Q4: 2N3391A;
- Q5: "5117" (as printed; prefix not shown);
- Q6, Q7: 2N5087;
- Q8: MPS U05;
- Q9: MPS U55;
- Q12-Q15: 2N3707;
- IC1: LM301;
- CR1, CR2, CR7-CR10: 1N4003;
- CR5: 1N2989A 30 V 10 W (or equiv.);
- CR6: 1N4740 10 V;
- DS1, DS2: 1813 lamps.

### Input and VVR (LN)

| Ref | Value | Notes |
|---|---|---|
| TB1 | | input ±, C, GRD; output ±, C; remote meter BLUE, BRN |
| R1A / R1B | pots (R1B front panel) | "T" attenuator |
| R2, R3 | 620, 1/4 W | |
| T1 | UTC O-12 or equivalent | GRN 6, 7, BRN 8 |
| R5 | 270 | secondary load |
| R6 | 27K | VVR series resistor |
| Q1 | UREI 13-0027 | shunt FET |
| R8 | 10K | Q1 source to ground |
| C2 | 50 µF 6.4 V | Q1 source to Q2's emitter (R13 / R14 junction): the LN feedback |
| R7, C3 | 2.2M ∥ 200 pF | gate network to the GR / stereo line |
| R9, C4 | 2.2M ∥ 200 pF | gate network from C5 |
| C5 | .22 | coupling (from the preamp side) |
| C27 | .22 | GR line bypass |
| C1, R10 | 1.0, 1K | drain node to Q2's base |

### Signal preamp

| Ref | Value | Notes |
|---|---|---|
| Q2, Q3, Q4 | 2N3391A | |
| R11, R12 | 560K, 1M | bias |
| C6 | 27 pF | |
| R13, R14 | 180, 180 | Q2 emitter |
| R15 | 150 | |
| R16 | 100 (variable) | |
| R17, R21 | 6.8K, 6.8K | feedback |
| R18 | 22K | |
| R19, R20, C8 | 82, 1.8K, 80 µF 25 V | Q3 emitter |
| C7 | 80 µF 25 V | |
| C9 | 1.0, 40 V | to OUTPUT GAIN |
| R27 | 100K, 2 W (front panel) | OUTPUT GAIN |
| C10 | .15 | to the line amp |

### Signal line amp (push-pull)

| Ref | Value | Notes |
|---|---|---|
| R28, R29, R30 | 10K, 6.8M, 1M | Q5 bias; C11 50 µF 40 V |
| Q5 | 5117 | |
| R31, R32 | 68K, 1K | |
| R33, C13 | 4.7K, .0022 | |
| R34 | 3.9K | overall feedback from the output |
| Q6, Q7 | 2N5087 | |
| R35, R36 | 10K, 100 | |
| CR1, CR2 | 1N4003 | bias diodes |
| C12, R37 | 12 pF, 1K | |
| R38, R39 | 1.2K, 1.2K | |
| C14 | 25 µF 25 V | bootstrap |
| C27 | 47 pF | |
| Q8, Q9 | MPS U05, MPS U55 | complementary output |
| R40, R41 | 4.3, 4.3 | emitter resistors |
| C15 | 400 µF 40 V | to T2 |
| T2 | B11148 | primary BRN, RED, ORG, YEL; secondary GRN, BLU, VIO, GRY; out to X, Y |

### Compression ratio switch

| Ref | Value | Notes |
|---|---|---|
| B deck | R22 56K, R24 56K, R25 68K (all 1/4 W), R26 56K 1/4 W | S1B-S4B; a "UA4706 T+C *" factory-set part at S4B |
| A deck | R87 150 Ω, R42 470 1/4 W, R43 560 1/4 W, R44 1.5K 1/4 W | S1A-S4A to V10 |
| R46 | 10M | across the switch (Rev E's anti-pop resistor) |
| R45 | 1.5K | from V10 |

### GR control amp

| Ref | Value | Notes |
|---|---|---|
| C17 | 1.0, 40 V | |
| R60, R61, R62 | 1M, 470K, 47K | |
| Q12-Q15 | 2N3707 | |
| R63, R64, R65 | 4.7K, 2.4K, 270 | |
| R66 | 182K 1% | |
| R67, R71 | 38.3K 1%, 7.68K 1% | |
| R69 | 44.2K 1% | |
| C18 | 50 µF 40 V | |
| R70 | 4.7K | |
| R72, R73 | 2.4K, 180 | |
| R68 | 47K | |
| C19, C20 | 6.8 µF 35 V | |
| R74, R75 | 47K, 47K | |
| CR3, CR4 | (type not printed) | rectifier |
| C21 | 80 µF 25 V | |
| R76, C22 | 470 ∥ .022 | ATTACK network |
| R77 | 25K, 1/2 W | ATTACK |
| R78 | 5M, 1/2 W | RELEASE |
| R79 | 270K | |
| R81 | 2K | "Q" BIAS ADJ. |
| R82, R83 | 10K, 3.9K | to -10 V |

### GR meter driver amp

| Ref | Value | Notes |
|---|---|---|
| Q10 | UREI 13-0027 | |
| R48 | 3.9M | |
| R52, R53 | 10K, 15K | |
| R54 | 100K | TRACKING ADJ. |
| IC1 | LM301 | C16 33 pF |
| R55 | 2K (front panel) | ZERO ADJ |
| R56, R57, R58 | 10K, 470K, 100K | |
| CR11, R59 | V10, 3.9K | |
| R49 | 5.6K | to +30 V |
| R50, R51 | 8.2K (+8), 3.6K (+4) | meter function |

### Power supply

| Ref | Value | Notes |
|---|---|---|
| T3 | B11754 | input voltage select 115 / 230 V |
| F1 | 1/8 A (110-120 VAC), 1/16 A (220-240 VAC) | |
| CR7-CR10 | 1N4003 | |
| R84 | 75, 3 W | |
| C23-C26 | 2000 µF 30 V | |
| CR5 | 1N2989A, 30 V 10 W | |
| CR6 | 1N4740, 10 V | |
| R85, R86 | 1K, 1K | |
| rails | "+30 V @ 50 mA, ripple ≈ 0.5 mV with load"; "-10 V, ripple ≈ 0.15 mV with load" | |

## Transformers

- **Input, Rev A-F: UTC O-12** ("or equivalent"), a UTC Ouncer. Accounts disagree on how
  it is wired (500:200 step-down vs 1:1). Sowter's replacement 1260 is listed as
  "1:1.58 200/500 Ohms" (web: https://www.sowter.co.uk/specs/1260.php, not fetched).
  Mix: the first units used a Peerless 600 Ω transformer.
- **Output, Rev A-E: UA-5002** (later UA-5002A). Putnam's custom design and "an integral
  part of the feedback network used to stabilize the output stage" (ua:).
- **Output, Rev F: B11148.**

No datasheet for the UTC O-12, UA-5002 or B11148 was found. Their winding data would
have to come from a design (C2) or from replacement-maker sheets.

## The manual's figures (ua:, UA's 2002 reissue of the D/E circuit; a reference only)

| Item | Figure |
|---|---|
| Input impedance | 600 Ω, bridged-T control (floating) |
| Output load impedance | 600 Ω (floating) |
| Frequency response | ±1 dB, 20 Hz-20 kHz |
| Gain | 45 dB ±1 dB |
| Distortion | less than 0.5% THD from 50 Hz to 15 kHz with limiting, at the 1.1 s release setting |
| Output | +22 dBm with no greater than 0.5% THD |
| Signal-to-noise | greater than 81 dB with the input at the threshold of limiting, 30 Hz-18 kHz |
| Attack | adjustable from 20 to 800 µs (fastest fully CW) |
| Release | adjustable from 50 ms to 1.1 s (fastest fully CW) |
| Ratios | 20:1, 12:1, 8:1, 4:1; "higher Ratio settings also set the threshold higher" |
| Stereo | 1176 SA adapter; linked, "the fastest attack time is double that of a single" unit |
| Q bias | R59 (D/E numbering): fully CCW, then CW "until the output decreases 1.0 dB" with a sine at 0 dB output |

The manual doesn't define how attack and release are measured (no level step and no
percentage), so the B12 profile has to state its own definition. Its theory chapter has
partial schematics with values (Fig. 2 input, Fig. 3 GR stage and LN, Fig. 5 GR control
circuit with the ratio decks). They are useful to check a D/E reading, but the PDF's text
layer garbles them: read the figures, not the extracted text.

## Open questions

1. **The Rev A FET.** The R-10743 label (Q1, Q2, Q4, Q11) isn't a JEDEC number at this
   resolution. Rev F calls Q1 / Q10 "UREI 13-0027". Repairers' replacements: a
   Gearspace thread on a Rev A blue stripe reports NTE stand-ins for **2N5458** at Q1 and
   Q2 (web: https://gearspace.com/threads/1176-fets.6096/latest). DIY 1176LN Rev D BOMs
   use **2N5457**, matched, for Q1 / Q11 (web:
   https://dsl-man.de/download/attachments/128057461/1176LN_REVD_V2.2_DOC.pdf?api=v2, not
   fetched). A higher-resolution Rev A scan would settle the label.
2. **R-10743 values marked (?)**: R19 (130K?), R25, R32, R58, the line amp's 560 / 8.2K
   reference numbers, the meter's 3600 and 820 references, T3's number, CR9's type, the
   revision date. A better scan (the GroupDIY compilation below) should resolve them.
3. **Rev AB's changes** ("changed resistor values in the signal preamp stages ...
   bypass capacitors around the resistor feeding the gain-reduction FET") aren't on this
   sheet. They are only known from text.
4. **The Rev D sheet** found is too blurred to use. Rev F's LN front end (Q1, C2, R7 / R9
   with 200 pF) is presumably Rev D's, but its output stage is different.
5. **Q5 "5117"** on Rev F: prefix unknown (possibly a house or 2N number). Check a parts
   list.

## Readings the build takes (B12, 2026-11-06)

`config/circuits/urei_1176.yaml` (generated by `scripts/make_urei_1176.py`, whose docstring
has the whole account) reads the sources this way:
- **ua: Figure 3** (the LN gain-reduction stage and preamp) as drawn, but R23 OUTPUT as
  schF's 100K (R27): Figure 3's "10k" with C7 1 uF corners at 18 Hz, against the
  manual's +-1 dB at 20 Hz, and R88 68k from the wiper only shapes a 100K track's law.
  R86 (100 ohm variable) is the LN circuit's distortion null: it sets how much of the
  preamp's feedback node reaches Q1's gate through C9 / R6.
- **ua: Figure 5** (the GR control circuit) for values, wired as schF draws its GR CONTROL
  AMP: Figure 5's two "R46" are the 1k rail decoupler (schF R70 4.7K) and the 47k feedback
  from Q10's emitter to Q7's (schF R68); its 50 uF decoupler returns to ground (schF C18),
  not to the R49 / R50 junction as Figure 5 draws it; the rails are +30 V and ground, and
  -10 V only through R35 / R64. The B deck's "T&C" at 20:1 is where schF has R46 10M (Rev
  E's anti-pop resistor); the A (signal) deck's "T&C" (schF's "UA4706 T+C *") is left
  open: no value or criterion is known. R22's foot and the GR DISABLE switch's other
  contact are ground (schF: through U2's shield, BLK).
- **schA page 2** (the class-A line amp) for Q4-Q6 and T2: the collector winding BRN-BLK
  to +30 V, the emitter winding WHT/BLK-WHT/RED through R32 to ground, the output BLU-RED
  with YEL-ORG strapped, SLT-VIO a feedback winding (VIO to ground) through R54 || C16
  into Q4's source network, R35 + C15 from the collector to SLT. The winding polarities
  aren't marked: both feedbacks are taken as negative. The "series D" sheet (Rev B on)
  shows Q4 as a 2N3391A, values illegible, so Rev A's FET stage stands in.
- **T1** wired 500:200 (Sowter's 1260 "1:1.58 200/500"), so R4's 270 ohm reflects to the
  manual's ~600 ohm input.

## To fetch (the user)

Login-walled GroupDIY attachments:

- "Comprehensive 1176 schematic document" (every version, blue stripe to silver face):

  ```
  https://groupdiy.com/threads/comprehensive-1176-schematic-document.15028/
  ```

- "Early 1176 original service manual":

  ```
  https://groupdiy.com/threads/early-1176-original-service-manual.62598
  ```

- The Rev A vs later comparison thread named in DEVICE_CANDIDATES.md:

  ```
  https://groupdiy.com/threads/1176-plosives-looking-for-rev-a-schematic-or-high-res-internal-shots.34502/page-5
  ```

- The "UREI 1176 LN Manual (Rev G 1973).pdf" with a high-quality schematic, mentioned on
  GroupDIY:

  ```
  https://groupdiy.com/threads/urei.45449/post-1169559
  ```

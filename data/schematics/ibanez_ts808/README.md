# Ibanez TS808 Tube Screamer ("Overdrive Pro", 1979-82) sources

Collected 2026-11-12 for a TS808 model (worktree `vst-amps`, branch `amps`). The TS808 was
designed by S. Tamura at Nisshin Onpa (Maxon), who built it for Ibanez; the Maxon OD-808 is
the same circuit (ElectroSmash, Plautz). No circuit file exists yet; values going into one
should cite these as `sch:` (the factory drawing), `trace:` (a third-party redraw), `web:`
(an analysis page or a datasheet) or `provisional:`. The transcriptions below are from one
research pass (2026-11-12): recheck each against its image when it goes into the circuit
file. Only the effect-on path is to be modelled; the electronic bypass is described so the
on-state's loading is right.

## The drawings (all in this folder)

Tags used in the value lists:

| Tag | File | What it is |
|---|---|---|
| **MP** | `ibanez_ts808_factory_MP-D01201A_via_electricdruid.jpg` | The factory service drawing: board **MP-D01201A**, designators R101-R133, C101-C117, test points CP-1..CP-9, a parts list (IC101 RC4558; Q101 / 103 / 105-107 2SC1815BL; Q102 / 104 2SK44SP; D101-106 MA150), Japanese-style notes (capacitor types by symbol: "▲ ceramic, ■ mylar, NP non-polar, T tantalum, all others electrolytic; resistors 1/4 or 1/8 W, ±5 %"), and an inset "TS-9: R114 470, R115 100K". Captioned "TS-808 ORIGINAL SCHEMATIC" by whoever scanned it. No date printed; the TS-9 inset suggests the TS-9-era (c.1982) service sheet that covers both. Only 736 x 579 px: every value below is legible, but a bigger scan was not found. |
| **ES** | `electrosmash_ts808_schematic.png` (full, with the JFET switching), `electrosmash_ts808_true_bypass_schematic.png`, `electrosmash_ts808_jfet_bypass.png` | ElectroSmash, "Tube Screamer Circuit Analysis": a clean redraw of MP with designators renumbered (R1.., C1.., P1-P3; R11 used twice) and analysis figures. The true-bypass variant is ElectroSmash's own simplification (level pot to ground, an added RA 0 ohm). |
| **RGK** | `keen_tube_screamer_anatomy_1998.gif` | R.G. Keen, "The Technology of the Tube Screamer" (1998), "Tube Screamer Anatomy": the signal path of the whole TS family with the 808 / 9 values, the switching simplified. Text in `keen_technology_of_the_tube_screamer_1998.html`. |
| **SC** | `cerutti_ts808_redraw_via_ggg.jpg` | "Tube Screamer TS-808, Drawn by Steve Cerutti" (thanks to Rob Strand), "Schematic for Reference Only!", hosted by General Guitar Gadgets. A full redraw including the flip-flop; diodes drawn as 1N914, JFETs 2SK30A. |

Provenance:

- MP: web: https://electricdruid.net/images/overdrive/IbanezTS-808Tubescreamer.jpg (in Tom
  Wiltshire's "Designing a classic OD-1/TS-808/SD-1 Overdrive", web:
  https://electricdruid.net/?p=66938). sha256 `00e5ebdd58d9855cd7f507679bf9e088cbdbc5efde9a204ceaf91283e9181119`.
  The same drawing is listed (55 KB PDF) at web:
  https://www.schematicsunlimited.com/i/ibanez/ibanez-ts808-tube-screamer-overdrive-pro-schematic,
  behind a captcha: not retrieved (perhaps a sharper copy).
- ES: web: https://www.electrosmash.com/tube-screamer-analysis. **electrosmash.com did not
  resolve on 2026-11-12** (DNS); the page and images were fetched from the Wayback Machine,
  snapshot 2026-05-13 (web:
  http://web.archive.org/web/20260513101245/https://www.electrosmash.com/tube-screamer-analysis).
  Page saved as `electrosmash_tube_screamer_analysis_wayback_20260513.html` (raw `id_` copy).
  Images: `images/tech/tube-screamer/tube-screamer-block-diagram.png`,
  `tube-screamer-true-bypass-schematic.png`, `tube-screamer-jfet-bypass-switch.png`.
- RGK: web: http://www.geofex.com/Article_Folders/TStech/tsxtech.htm, image `tsxtech.gif`.
- SC: web: https://generalguitargadgets.com/wp-content/uploads/ts-808.jpg (linked from
  web: https://generalguitargadgets.com/effects-projects/distortion/tube-screamer/).

Where MP and the redraws agree the value is taken as stock. Where they differ, MP wins (it
is the only factory document) and the difference is listed.

## Values by stage

Designators are MP's; ES's in brackets. Vb is the 4.5 V bias node (drawn as a down-arrow
on MP).

### Input buffer (Q101, emitter follower; always in circuit, also in bypass)

| Part | MP | ES | RGK | SC | Pick |
|---|---|---|---|---|---|
| C101 input cap [C1] | 0.02 (■ mylar) | 0.02 | 0.02 | .02uf | 0.02 uF film |
| R101 series [R1] | 1K | 1K | 1K | 1K | 1K |
| R102 base bias [R2] | 510K to Vb | 510K to 4V5 | 510K to +4.5V | 510K to Vr | 510K to Vb |
| Q101 [Q1] | 2SC1815BL | 2SC1815 ("β=350") | 2SC1815 ("typical gain 300") | 2SC1815 | 2SC1815-BL |
| R103 emitter [R3] | 10K to ground | 10K | 10K | 10K | 10K |
| Collector | +9 V | 9V | +9V | V+ | +9 V |

- No input pull-down resistor ahead of C101 in any drawing. ES computes Zin = 446K (R102
  dominates).
- The emitter feeds two places: C102 to the clipping stage, and C111 (0.1, mylar) to the
  bypass JFET Q104 with R118 510K to Vb on that side. With the effect on, Q104 is off and
  C111 + R118 is a 510K load to AC ground on the emitter (negligible; include it or not).

### Clipping amplifier (IC101 half A, pins 1-3)

| Part | MP | ES | RGK | SC | Pick |
|---|---|---|---|---|---|
| C102 coupling [C2] | 1/50 NP (non-polar electrolytic) | 1uF/50V NP | 1/50 NP | 1uf BP | 1 uF NP electrolytic |
| R105 (+) bias [R5] | 10K to Vb | 10K to 4V5 | 10K to +4.5V | 10K to Vr | 10K to Vb |
| R104 [R4] | 4.7K | 4K7 | 4K7 | 4.7K | 4.7K |
| C103 [C3] | 0.047 (■ mylar) | 0.047 | 0.047 | .047uf | 0.047 uF film |
| R104 + C103 return | ground (as read; MP's image is small there) | ground | ground | Vr | ground |
| R106 [R6] | 51K | 51K | 51K | 51K | 51K |
| DRIVE ("DISTORTION") [P1] | 500KA, wired as a rheostat (wiper + one end) in series with R106 | "Distortion 500K Log" | "DRIVE 500KA" | 500KA | 500K, A (log) taper |
| C104 [C4] | 51P (▲ ceramic) across the diodes | 51p | 51p | 51pf | 51 pF ceramic |
| D101, D102 [D1, D2] | MA150, antiparallel, output to (-) | MA150 | "silicon signal diodes" | 1N914 | MA150 (see the diodes) |

- (-) input to ground through R104 + C103 (720 Hz, ES and RGK); R106 + DRIVE, C104 and the
  two diodes are all in parallel from pin 1 to pin 2. RGK's gain figures: 1 + (51K +
  DRIVE) / 4.7K, i.e. ~12 to ~118 above 720 Hz (ES: 12 to 118).
- C103's return: the series cap blocks DC, so ground vs Vb only changes the AC return by
  Vb's impedance (10K || 10K, 47 uF): pick ground (MP as read, ES, RGK).
- Taper letters are Japanese convention: A = audio (log), B = linear; G = an S-shaped
  taper (ES "G Taper ... also called W or S tapers"). The curves themselves aren't printed
  anywhere: provisional: model knowledge for the A law (a 10-20 % at mid-rotation log
  curve) and the G law (ES's sketch, `g-potentiometer.png` on the ES page, not digitized).

### Tone and volume (IC101 half B, pins 5-7)

| Part | MP | ES | RGK | SC | Pick |
|---|---|---|---|---|---|
| R107 [R7] | 1K, pin 1 to the (+) node | 1K | 1K | 1K | 1K |
| C105 [C5] | 0.22/35 T (tantalum) to ground | 0.22 / 35V | 0.22 35V | .22uf tant | 0.22 uF tantalum (723 Hz with R107) |
| R109 [R9] | 10K, (+) node to Vb | 10K to 4V5 | 10K to +4.5V | 10K to Vr | 10K to Vb |
| TONE [P2] | 20KG: one end (lug 7) to the (+) node / pin 5, the other end (lug 6) to pin 6 (-), wiper (lug 8) to C106 | "Tone 20 K" | "TONE 20KG" | 20KG | 20K, G taper |
| C106 [C6] | 0.22/35 T, + toward the wiper | 0.22 | tant 0.22 35V | .22uf tant | 0.22 uF tantalum |
| R108 [R8 / R10] | 220, C106 to ground | 220 | 220 | 220 | 220 ohm |
| R110 [R11] | 1K, pin 7 to pin 6 | 1K | 1K | 1K | 1K |
| R111 [R11 / R12] | 1K, pin 7 toward LEVEL | 1K | 1K | 1K | 1K |
| C107 [C7] | 1/50 NP | 1uF/50V NP | 1/50 NP | 1uf BP | 1 uF NP electrolytic |
| LEVEL [P3] | 100KB: hot (lug 5) from C107, cold (lug 3) to **Vb**, wiper (lug 4) to the switch JFET Q102 | "Level 100K" (cold to ground in ES's redraw; BOM "100K Lin") | "LEVEL 100KB", cold to +4.5V | B100K, cold to Vr | 100K, B (linear), cold lug to Vb |

- RGK's text calls LEVEL "a 100K audio control" but his drawing, MP and SC print 100KB.
  Pick MP's B. RGK: "returning the volume control 'cold' lug to ground instead of to the
  bias voltage, as some models of the TS series do": on the 808 it's Vb (MP, SC, RGK's
  drawing). That keeps the JFET switch's channel at 4.5 V DC.
- RGK: the tone network's corner is ~3.2 kHz (220 ohm / 0.22 uF); ES the same.

### Electronic switch (effect on) and output buffer (Q103)

| Part | MP | ES | RGK | SC | Pick |
|---|---|---|---|---|---|
| Q102 [Q2] (effect path switch) | 2SK44SP | 2SK44SP | "2SK30A in early pedals and 2SK118 in later ones" | 2SK30A | on: a resistance (below) |
| Q104 [Q4] (bypass path switch) | 2SK44SP | 2SK44SP | as Q102 | 2SK30A | off: open |
| R117 [R17] | 510K, switch output node (CP-6) to Vb | 510K to 4V5 | 510K to +4.5V | 510K to Vr | 510K to Vb |
| C108 [C8] | 0.1 (■ mylar), CP-6 to Q103's base | 0.1 | 0.1 | 0.1uf | 0.1 uF film |
| R112 [R12] | 510K, base to Vb | 510K to 4V5 | 510K to +4.5V | 510K to Vr | 510K to Vb |
| Q103 [Q3] | 2SC1815BL | 2SC1815 | (Q2) | 2SC1815 | 2SC1815-BL |
| R113 [R13] | 10K emitter to ground | 10K | 10K | 10K | 10K |
| R114 [RB] | 100 | 100 | 808: 100 (TS9: 470) | 100 | 100 ohm |
| C109 [C9] | 10/16 electrolytic, + toward the emitter | 10uF/16V | 10/16V | 10uf | 10 uF electrolytic |
| R115 [RC] | 10K, output to ground | 10K | 808: 10K (TS9: 100K) | 10K | 10K |

- Bypass (MP; ES section 1.1; RGK "Bypass operations"): not true bypass. Both buffers are
  always in the signal path; two N-channel JFETs pick either the LEVEL wiper (effect on,
  Q102 conducting) or the input buffer's emitter through C111 (bypassed, Q104 conducting)
  into the output buffer's coupling cap C108. Each gate is driven through a diode (D103 /
  D104, MA150) from a flip-flop (Q105 / Q106, 2SC1815; collector loads R126 / R127 56K, base
  resistors R125 / R128 56K; cross-coupling networks CR1 / CR2, which ES draws as 47K || 100
  pF each; C114 / C115 1000P; trigger R121 62K, R122 22K, R123 1M, R124 22, C113 1000P and a
  momentary dome switch; Q107 drives the LED through R131 3.6K and zener D107 RD4.7EB, with
  R130 1M, R129 100 and D106), with 1M (R116 and its twin) + 0.047 (C110, C112) RC networks
  to soften the switching. With the gate's diode reverse-biased the gate floats to the
  channel's 4.5 V (VGS = 0, on); pulling the gate to ground (VGS = -4.5 V) turns it off.
  The flip-flop starts in bypass (ES: mismatched speed-up caps).
- For the effect-on model: LEVEL wiper -> Q102's channel at VGS = 0 -> CP-6 (R117 510K to
  Vb) -> C108 -> Q103. Q102 as a resistance: RGK "look like about a 100 ohm resistor"
  (provisional: RGK's figure, not a datasheet; the 2SK44SP's sheet wasn't retrieved). Q104
  and the flip-flop can be left out; keep R118 / C111 on the input buffer's emitter or not
  (510K, negligible).

### Power supply and bias

| Part | MP | ES | RGK | SC | Pick |
|---|---|---|---|---|---|
| Battery | S-006P 9 V, its (-) switched to ground by the stereo input jack | Battery | 9V | 9V | 9 V |
| D108 [D8] | W03C, across the DC jack (shunt: reverse-polarity protection, no series diode) | W03C | (not drawn) | shunt diode | none in the model (no series part) |
| C117 [C17] | 100/10 across +9 V | 100F/10V | (not drawn) | 100uf | 100 uF |
| R133 / R132 [R33 / R32] | 10K / 10K, +9 V to Vb to ground | 10K / 10K | 10K / 10K | 10K / 10K | 10K / 10K |
| C116 [C16] | 47/10, Vb to ground | 47F/10V | 47uF 6.3V | 47uf | 47 uF |

- No series resistor or diode in the 9 V line on any drawing: the supply is the battery
  straight onto C117. A battery's internal resistance is not printed anywhere:
  provisional: model knowledge (a fresh alkaline 9 V is of the order of 1-2 ohm, a
  carbon-zinc 006P several to tens of ohms, rising as it runs down); the TS draws a few
  mA, so it matters little here (unlike the Fuzz Face).
- The op-amp runs single-supply: V+ = +9 V (pin 8), V- = ground (pin 4).
- RGK: "The exact value of the bias generation resistors varies somewhat from model to
  model"; on the 808 both are 10K.

## Semiconductors

### IC101: JRC4558D (NJM4558)

- MP's parts list prints **RC4558** (the TI / Raytheon-style generic name); ES, RGK and the
  collector literature (AnalogMan, Tonepedia) say the 808 shipped with the **JRC4558D**,
  some with TI's RC4558P / TL4558P (e.g. web: https://www.tonepedia.com/?p=2800, "TS808 (1981
  - TL4558P)", not fetched). RGK: "THE ONLY DIFFERENCES [808 / 9 / 9 reissue] ARE THE OPAMP
  TYPE AND THE TWO OUTPUT RESISTORS". Pick the JRC4558D (as asked; it is the part the 808's
  reputation rests on).
- Datasheet: `nisshinbo_njm4558_datasheet_ver20260723.pdf`, web:
  https://www.nisshinbo-microdevices.co.jp/en/pdf/datasheet/NJM4558_E.pdf (Nisshinbo Micro
  Devices, successor of New JRC; "Ver. 20260723"; the DIP8 NJM4558D is marked
  discontinued). A period (1980) JRC sheet wasn't found. At V+/V- = ±15 V, 25 C:
  - large-signal voltage gain AV 100 dB typ, 86 dB min (RL >= 2k, VO = ±10 V);
  - gain-bandwidth GB 3 MHz typ; slew rate SR 1 V/us typ (no min / max);
  - output swing VOM1 ±14 V typ (±12 min) at RL >= 10k, VOM2 ±13 V typ (±10 min) at RL >= 2k;
  - input common-mode range ±14 V typ (±12 min); input resistance 5 MOhm typ (0.3 min);
    bias current 25 nA typ (500 max); offset 0.5 mV typ (6 max); CMR 90 dB, SVR 90 dB typ;
  - supply current 3.5 mA typ (both halves); operating voltage ±4 to ±18 V (the TS's 9 V
    single supply is ±4.5 V, near the bottom);
  - curves: open-loop gain vs frequency, output swing vs supply (from ±6 V only), vs load,
    vs frequency.
- Not published, so provisional for a 9 V model: the output swing and the common-mode range
  at ±4.5 V (the sheet's swing-vs-supply curve starts at ±6 V; extrapolating its ~1 V
  headroom per rail is provisional: model knowledge), and the overload recovery RGK
  discusses. ES also has a JRC4558 page (web: https://www.electrosmash.com/jrc4558, not
  fetched).
- For the project's `opamp` macro (single pole from A0 / GBW, slew, swing clamps): A0 100 dB
  (1e5), GBW 3 MHz, slew 1 V/us from the sheet; swing at 9 V provisional.

### D101, D102: MA150 (not 1S1588)

- MP's parts list: D101-106 MA150 (Matsushita / Panasonic). ES: "MA150". RGK: "silicon
  signal diodes, which look identical to the 1N914/1N4148"; SC draws 1N914. No source found
  says a TS808 used the Toshiba 1S1588 (one hobbyist primer says TS iterations used 1N4148,
  1N914 and 1S1588 variously: web:
  https://www.guitarpedalx.com/news/gpx-blog/a-brief-hobbyist-primer-on-clipping-diodes,
  search summary only; the 1S1588 is the Boss OD-1's diode). Pick MA150.
- Datasheet: `panasonic_ma2b150_ma150_datasheet.pdf` (Panasonic "Switching Diodes,
  MA2B150, MA2B161, MA2B162, MA2B162A (MA150, MA161, MA162, MA162A)", pp. 148-149; web:
  https://elektrotanya.com/sites/default/files/forum/2017/05/MA150.pdf, a forum mirror):
  VR 35 V, IF(AV) 100 mA, VF 0.95 typ / 1.2 max V at IF = 100 mA, IR 0.025 uA max at VR =
  15 V, Ct 0.9 typ / 2 max pF at 0 V (curve: ~1.45 pF at 0 V to ~1.1 pF at 20 V), trr 10 ns
  max; curves IF-VF at -20 / 25 / 75 / 150 C (0.01 mA to 1 A) and VF vs Ta at 0.01 / 0.1 / 1
  / 10 / 20 mA.
- Against the project's `1N4148@1` (IS 2.52 nA, N 1.752, RS 0.568 ohm): read by eye off
  MA150's VF-Ta plot at 25 C, VF is about 0.40 / 0.50 / 0.61 / 0.73 V at 0.01 / 0.1 / 1 / 10
  mA (about 0.1 V per decade, n ~ 1.7); 1N4148@1 gives 0.375 / 0.48 / 0.58 / 0.69 V. So the
  MA150 sits ~20-40 mV higher at the same slope: close, but not the same part. For a
  sourced model, digitize the MA150's IF-VF curve (the 25 C trace) and fit IS / N, as
  `1N4148@1` was; until then `1N4148@1` is a provisional stand-in (provisional: the
  comparison above).
- 1S1588 (Toshiba): its sheet wasn't retrieved (Toshiba's site returns 403; one mirror
  image shows only the maximum ratings: VRM 35 V, VR 30 V, IFM 360 mA, IO 120 mA, web:
  https://www.datasheetcafe.com/1s1588-datasheet-diode-toshiba/). Not needed for the 808.

### Q101, Q103: 2SC1815-BL

- MP: 2SC1815BL (hFE rank BL, 350-700 at VCE = 6 V, IC = 2 mA). ES's analysis uses
  β = 350, RGK 300.
- Datasheet: `central_2sc1815_datasheet_r1_2018.pdf` (Central Semiconductor's 2SC1815
  series, R1 10-May 2018; web: https://www.phippselectronics.com/wp-content/uploads/2019/09/2SC1815-Datasheet.pdf,
  a distributor's copy). Toshiba's own sheet returned 403. Central's: VCBO 60 V, VCEO 50 V,
  VEBO 5 V, IC 150 mA, PD 400 mW; ICBO 100 nA max at 60 V; VCE(sat) 0.25 V max at 100 / 10
  mA; hFE at 6 V / 2 mA: O 70-140, Y 120-240, GR 200-400, BL 350-700; fT >= 80 MHz.
- SPICE card: **no Toshiba card exists** (Kaz: the 2SC1815 "reached EOL around 2012-2013
  and disappeared before any model was ever published"; Central's datasheet lists SPICE
  models as a support service, but no 2SC1815 file was found at
  central.aeminc.com/docs/ENGINEERING/CSM/, where the project's 2N3904 card came from).
  The best card found is **measured**: Kaz-electro, "2SC1815 SPICE Parameters - All Four
  hFE Ranks Measured" (2022, Toshiba parts, a pulse-mode analyzer, extraction in Micro-Cap
  Model 6.0.8; XTB from hFE at 25 and 60 C), web: https://kaz-electro.jp/lab/2sc1815-spice/,
  not kept in the repo (© kaz-electro.jp: cite the numbers,
  don't redistribute the card). Its **2SC1815-BL** card, every parameter as printed:
  IS 30.011f, BF 454.489, NF 0.99721, VAF 147.783, IKF 0.229, ISE 100.006f, NE 1.6551,
  BR 6.004, VAR 60, IKR 0.056, ISC 8.417p, NC 1.600, RE 0.523, RB 44, RBM 1.300, IRB 0.0023,
  RC 0.279, CJE 12.036p, VJE 0.591, MJE 0.310, CJC 5.456p, VJC 0.395, MJC 0.277, FC 0.890,
  TF 426.909p, XTF 1.800, VTF 2.5, ITF 0.172, TR 604.231n, XTB 1.6 (NR not given: SPICE's
  default 1). The same page has O, Y and GR cards (GR: IS 16.045f, BF 275.022, NF 0.99569,
  VAF 526.372, IKF 0.293, ISE 157.886f, NE 1.62711, BR 4.268, VAR 88, IKR 0.056, ISC
  57.614p, NC 1.8, RE 0.546, RB 34, RC 0.332, CJE 11.936p, CJC 5.046p, VJC 0.408, MJC 0.302).
  Evaluated in the project's DC subset (TNOM 27 C, VCE 6 V): hFE ~ 406 at 0.39 mA (the
  buffers' current, (4.5 - 0.6) V / 10K), 430 at 2 mA, inside BL's 350-700. The DC subset
  takes IS..NC plus RB, RC, RE, CJE, CJC (VJC / MJC for the stated-bias CJC); RBM / IRB,
  TF / XTF / VTF / ITF, TR and XTB are dropped (the bjt.py docstring). Kaz validated against
  Toshiba's published 2SC2712 card (the same die in SMD, per Kaz's assumption).
- Other cards circulating (not used): a widely copied LTspice-style "Toshiba" set with
  IS 2.04E-15, VAF 6 and BF per rank (web: https://www.usagi1975.com/01jan151055/, host
  unresolvable on 2026-11-12; the search summary says VAF = 6, which is unphysical for this
  part), and a self-tuned one (IS 130f, BF 400, VAF 100) whose author says not to rely on
  it (web: https://jhalfmoon.com/dbc/2024/05/08/spice%E3%81%AE%E5%B0%8F%E7%93%B643-%E5%8B%9D%E6%89%8B%E6%94%B9%E3%81%96%E3%82%93%E3%81%AE2sc1815%E3%82%B9%E3%83%91%E3%82%A4%E3%82%B9%E3%83%91%E3%83%A9%E3%83%A1%E3%83%BC%E3%82%BF%E3%81%A7%E5%AE%9F/,
  search summary only).

### Q102, Q104: 2SK44SP (switch only)

Not modelled (effect on: Q102 a resistance, Q104 open). RGK: on ~100 ohm at VGS = 0.
Datasheets for the 2SK44SP / 2SK30A weren't looked for.

## Versions: TS808 vs TS9 (and the rest)

- MP's inset and RGK agree: TS-9 = TS808 with **R114 470 ohm** (808: 100) and **R115
  100K** (808: 10K), and often another op-amp. RGK: the TS808, TS9 and TS9 reissue share
  the board; the effect is the output follower's negative-going drive into a load (RGK:
  the 10K shunt "halves the emitter loading ... reduces the negative going output impedance
  of the stage by half to about 5K"), the divider 100 / 10K vs 470 / 100K being 0.990 vs
  0.995.
- TS10: an extra 220 ohm into the clipping amp's (+), an extra emitter follower for the
  bypass path, another input bias (RGK). TS5: a TS9 with other op-amp and bias parts (RGK).
- Op-amps: JRC4558D (808, 9, most 9 reissues), RC4558P / TL4558P in some 808s, TA75558 in
  TS10s (RGK: "reported to sound abysmal"). MP lists RC4558.
- Pick: the **TS808** (R114 100, R115 10K) with a JRC4558D, MA150 diodes, 2SC1815-BL
  buffers, as MP draws it.

## What wasn't found

- A sharper scan of MP (Schematics Unlimited's PDF is captcha-gated; ManualMachine's copy
  is behind Cloudflare). The present 736 x 579 copy is legible for every value above, but
  R104 / C103's return point and the unlabeled 1M by D104 / C112 are read from small
  print.
- A dated Ibanez / Maxon document, or one naming the 1S1588.
- A period JRC4558 datasheet (the current Nisshinbo sheet is used), and the op-amp's swing
  at ±4.5 V.
- Toshiba's 2SC1815 datasheet and any manufacturer SPICE card for it (the measured Kaz card
  stands in); the 2SK44SP / 2SK30A sheets (not needed for the effect-on model).
- Pot taper curves (A, B, G): none published.
- ElectroSmash itself (domain not resolving 2026-11-12); everything from it here is the
  Wayback snapshot of 2026-05-13.

## File hashes (sha256, downloaded 2026-11-12)

```
ff5918b74f2406f3753e46c8f774769738d8f575bb275143003d80275e098e62  central_2sc1815_datasheet_r1_2018.pdf
22ea2b084b4248a26a303557e18c8f35968bc1fa73a2a6bcf5edce0d349a12ad  cerutti_ts808_redraw_via_ggg.jpg
334ce8b95dfcb7e30e74ba753df5ac1aee9b0e4d3fb2b57a83011d51dad55c81  electrosmash_ts808_jfet_bypass.png
74c309123b85ef89bd821b3ffc5b381b93c61890baddcdb1db644f67420cc979  electrosmash_ts808_schematic.png
87399df12eb0c2317238d363893da1eab9db44f16df353f31ddcc34b866c42a9  electrosmash_ts808_true_bypass_schematic.png
ebee6e341fc51958df77ac9c68b02026d41d74f7142d01868b722da5dc778eb6  electrosmash_tube_screamer_analysis_wayback_20260513.html
00e5ebdd58d9855cd7f507679bf9e088cbdbc5efde9a204ceaf91283e9181119  ibanez_ts808_factory_MP-D01201A_via_electricdruid.jpg
bbb567f88a26a5be0fd0837ef14a875d437ba03d9664ec8acb8f7fafe9465ca4  keen_technology_of_the_tube_screamer_1998.html
7c0d38ee4afb7035b56bc06584befd6e33e5fab10081b7fa8f8502bb4b9a3980  keen_tube_screamer_anatomy_1998.gif
9d73cf4cc7b5fa8c9fac83c0f5bd58e8571e7076fca57456a2b689cb5c39acbe  nisshinbo_njm4558_datasheet_ver20260723.pdf
cd51bf6cab12d1399da7401184b99afbe02c5c82cda219920257a00d682fc672  panasonic_ma2b150_ma150_datasheet.pdf
```

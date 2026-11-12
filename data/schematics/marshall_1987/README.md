# Marshall 1987 Lead 50 W ("Plexi", 1968-69) sources

Collected 2026-11-12 for the Plexi amp model (worktree `vst-amps`, branch `amps`). The
1987 Lead 50 W of 1968-69 is the 1959 Super Lead's preamp, tone stack and inverter with
two EL34s. No circuit file exists yet; values going into one should cite these as
`sch:` (a schematic printed by Marshall or its US distributor), `trace:` (a third-party
trace or redraw of a real amp), `web:` (a replacement part maker's or a datasheet's figure)
or `provisional:`. The transcriptions below are from one research pass (2026-11-12):
recheck each against its image when it goes into the circuit file.

## The drawings (all in this folder)

Tags used in the value lists:

| Tag | File | What it is |
|---|---|---|
| **GW87** | `gw_unicord_1987_70-19-11_jul1970.gif` | "MARSHALL 1987", GW Unicord Inc. (Marshall's US distributor), drawing 70-19-11, dated JULY 70. The only period drawing of the 50 W found. US version (110/120/200/225/245 V primary taps). Prints values only: no voltages, no designators, no tube pin numbers. |
| **JP97** | `piazza_1987_redraw_1997.gif` | "Marshall Amplifier Model # 1987 (plexi), Drawn By: Joe Piazza 1/15/97". A clean redraw of GW87 with tube pin numbers and pot names; adds nothing else and inherits GW87's values. |
| **SD68** | `sonicdeli_1987_circa1968_trace.pdf` | "Marshall Amplifier Model 1987, 50 Watt 2@(EL34) 3@(ECC83), Circa 1968, This is a stock Amp", traced by Sonicdeli / Thundertweak Amps for one Ace Pepper. A trace of a real US-voltage (117 VAC) amp; prints the part numbers 784-139 (OT), 1202-118 (PT), C1999 (choke) and the 10D8 rectifiers. Independent of GW87 in places (see differences). |
| **GW59** | `gw_unicord_1959_70-6-11_jul1970.gif` | "MARSHALL 1959", GW Unicord drawing 70-6-11, JULY 70 (100 W Super Lead, 4 x EL34). Same preamp / stack / inverter as GW87, for cross-checking. |
| **M67** | `marshall_100w_type2_c1967.gif` | "100 Watt Amplifier Type #2 c.1967", a hand drawing (Dr Tube: "Early 100W schematic, with errors, Marshall 1967"). The only drawing with node voltages (100 W, pre-1968 preamp: shared V1 cathode). Context only. |
| **RX93** | `marshall_1987x_reissue_87X-60-02_iss6.pdf` | Marshall's own drawing of the 1987X reissue, DWG 87X-60-02 issue 6 (1993-94), 2 sheets. PCB reissue; differs from the 1968-70 amps in many values. Useful for the tapers and the part numbers, which nothing older prints. |

Provenance:

- GW87: web: https://www.drtube.com/schematics/marshall/1987u.gif (also
  web: https://el34world.com/charts/Schematics/files/Marshall/Marshall_1987_jmp_lead_50watt_el34.gif,
  byte-identical; and page 1 of
  web: https://el34world.com/charts/Schematics/files/Marshall/Marshall_jmp_lead_50w_1987.pdf).
  2023 x 1304 px, sha256 `b31b70c9e9e572d312bb696102ee83c139c6cca76d6b7ebfe85ffa13d5a7444a`.
- JP97: web: https://www.drtube.com/schematics/marshall/1987pljp.gif (800 x 600 px; also page 2
  of the el34world PDF above), sha256 `8b7eab155f71cdf4af9e4a505857b1c4cdb524b84a31e2d045ed338335bc6f54`.
- SD68: web: https://el34world.com/charts/Schematics/files/Marshall/Marshall_68_1987.pdf
  (one page, embedded 2226 x 1476 JPEG), sha256 `3918bb5c4147e4a8bf4cd2d5b7f7a1cc540cc211e160cb61115e51c3b17fdca8`.
- GW59: web: https://www.drtube.com/schematics/marshall/1959u.gif, sha256
  `a38f7e6fe68e87ff7f1f5c043cd9aa301a6afb106dc6de3e835992f95b57964b`.
- M67: web: https://www.drtube.com/schematics/marshall/100w-67.gif, sha256
  `6980fb3c9d7353ad1b4f4d5fa05ceda2457f7e272e0930337f1dc995d00c0313`.
- RX93: web: https://el34world.com/charts/Schematics/files/Marshall/Marshall_plexi_superlead_reissue_50w_1987x.pdf,
  sha256 `a6ef1f1761d6be68293f7e18f2c653427b1e39e0a4a41bf4f801d889ff06dac4`.
- Index pages: web: https://www.drtube.com/marshall-jmp/ and
  web: https://el34world.com/charts/Schematics/files/Marshall/Marshall_Schematics.htm.
  No Marshall-made drawing of the 1968-69 50 W was found (Marshall's factory drawings online
  start with the 1970s MkII and the reissues). A 1987 Lead MkII (6550) drawing, GW Unicord
  70-23-11, July 70, is page 3 of the el34world `Marshall_jmp_lead_50w_1987.pdf`: not ours.

## Values by stage

"Pick" is the value proposed for the 1968-69 amp and why. Where GW87 and SD68 agree the
value is taken as stock for 1968-70.

### Inputs

- Two channels (High Treble = "bright", Normal), two jacks each. Per jack 68K to the grid,
  1M to ground on the channel (GW87, SD68, JP97; the reissue the same: R3 / R4 / R22 / R23
  68K 1/4 W, 1M 1/2 W, RX93).

### V1 ECC83 (12AX7), separate cathodes

Pins (JP97): normal triode pins 1 / 2 / 3 (plate, grid, cathode), bright triode 6 / 7 / 8.

| Part | GW87 (1970) | SD68 (c.1968) | GW59 (1970, 100 W) | RX93 (1993) | Pick |
|---|---|---|---|---|---|
| Plate loads | 100K, 100K | 100K, 100K | 100K, 100K | 100K 1/2 W | 100K |
| Normal cathode | 820 / 320 uF | 820 / 320 uF | 820 / 250 uF | 820R / 330u 6.3 V | 820 / 320 uF (both 1987 drawings) |
| Bright cathode | 2.7K / .68 uF | 820 / .68 uF | 2.7K / .68 uF | 2K7 / 680n | 2.7K / .68 uF (GW87 = GW59 = RX93; SD68's 820 is likely a trace error, or one amp's repair) |
| Normal coupling | .022 uF | .022 uF | .022 | 22n | .022 uF |
| Bright coupling | .0022 uF | .002 uF | .0022 | 22n | .0022 uF (both 1987 drawings and GW59; the reissue's 22n differs: flag) |

M67 (100 W, c.1967) has one shared cathode, 820 / 250 uF: the 1968-69 amps have separate
cathodes in every drawing above.

### Volumes and the mixer

- Volume pots 1M each (GW87, SD68, GW59); RX93 prints "A1M" for both (A = log in Marshall's
  notation: the only taper source found; the 1968 tapers aren't printed anywhere).
- Bright cap across the bright volume (top to wiper): .005 uF (GW87, GW59), 5000 pF (SD68),
  4n7 (RX93). Pick .005 uF.
- Mixing resistors 470K from each wiper to V2a's grid (all drawings). Across the bright
  channel's 470K: 500 pF (GW87, GW59), 560 pF (SD68), 470p (RX93). Pick 500 pF (GW87).
- No grid-leak resistor at V2a's grid other than the two 470K into the volume pots (all).

### V2a ECC83, gain stage (pins 1 / 2 / 3, JP97)

- Plate load 100K from the V2 node (all).
- Cathode: GW87 prints "820 (1K)" bypassed by .68 uF; GW59 the same; SD68 820 / .68 uF;
  RX93 R9 1K with no bypass capacitor drawn. Pick 820 / .68 uF (the "(1K)" in brackets is
  GW's alternative value, meaning not stated).
- Plate DC-coupled to V2b's grid (all).

### V2b ECC83, cathode follower (pins 6 / 7 / 8, JP97)

- Plate straight to the V2 node, no plate resistor; cathode 100K to ground (all; RX93 R10
  100K 1/2 W). Its cathode drives the tone stack.

### Tone stack (Marshall / TMB)

| Part | GW87 | SD68 | GW59 | RX93 | Pick |
|---|---|---|---|---|---|
| Slope resistor | 33K | 33k | 33K | 33K 1/2 W | 33K |
| Treble cap | 500 pF | 560 pF | 500 pF | 470p | 500 pF |
| Treble pot | 250K (printed rotated; JP97 "Treble 250K") | 250k | 250K | B220K | 250K |
| Bass cap | .022 uF | .022 uF | .022 | 22n | .022 uF |
| Bass pot | 1M (drawn as rheostat) | 1M | 1M | A1M | 1M |
| Middle cap | .022 uF | .022 uF | .022 | 22n | .022 uF |
| Middle pot | 25K (rheostat) | 25k | 25K | B22K | 25K |

Tapers: printed only on RX93 (treble B = linear, bass A = log, middle B = linear). For the
1968 pots: provisional: model knowledge (Marshall of the period is usually reported to use
log pots throughout; nothing found in print). The treble wiper feeds the inverter's .022
input cap (all).

### Phase inverter V3 ECC83, long-tailed pair

- Input coupling .022 uF from the treble wiper to the first grid (GW87, SD68, GW59; RX93 C8 22n).
- Grid resistors 1M from each grid to the cathode-resistor / tail junction (self-bias);
  cathode resistor 470 ohm; tail 10K (all; RX93 R15 470R, R24 10K). In GW87 / SD68 the
  tail's bottom and the second grid's .1 uF return to the feedback node (the top of the
  presence pot), not to ground; RX93 draws R16 1M / C9 100n differently (not traced here).
- Plate loads 82K and 100K from the PI node (all). JP97 puts 82K on pin 1 (the triode whose
  grid takes the signal, pin 2) and 100K on pin 6.
- 47 pF across the two plates (GW87, SD68, GW59, RX93 C11 47p).
- Coupling to the EL34s: .022 uF (GW87, SD68, GW59); RX93 100n 250 V (UK), 22n (its "USA
  changes"). Pick .022 uF.
- Negative feedback: 47K (GW87 prints "47K (100K)", the bracketed being an alternative;
  SD68 47k; GW59 47K (100K); RX93 R17 100K). Taken from the speaker side: GW87 joins it to
  the impedance selector's common (drawn on the 8 tap position), SD68 notes "Feedback tap
  tied directly to speaker jack, not transformer taps!", JP97 draws it on the 16 ohm tap. So
  the feedback comes from whichever tap is selected; with a 16 ohm cabinet that is the 16
  ohm tap. Pick 47K from the 16 ohm tap.
- Presence: 5K pot from the feedback node to ground, wiper to .1 uF to ground (GW87,
  SD68, GW59); RX93 B4K7 (linear) with 680n. Pick 5K / .1 uF.

### Output stage, 2 x EL34 (pins 3 plate, 4 screen, 5 grid, 8 cathode with g3 (pin 1); JP97)

- Grid leak / bias feed 220K per tube (GW87, SD68, GW59, RX93 R25 / R26 220K 1/2 W), their
  common end on the bias supply.
- Grid stoppers: none drawn on GW87, SD68 or JP97. GW59 (100 W) prints 5.6K per grid;
  RX93 none drawn.
- Screen resistors: none drawn on GW87, SD68 or JP97 (screens straight to the choke's
  output node). GW59 (100 W) prints 1K per screen; RX93 470R 5 W (UK) or 1K 5 W ("USA
  changes"). A forum search summary says many early Marshalls left the factory without
  screen resistors and 1K was a common later addition (web:
  https://www.marshallforum.com/threads/plexi-vintage-50w-1968-without-screen-grid-resistors-blowing-tubes.138631/;
  the thread is bot-blocked: seen in a search summary only, unverified). Pick: none, as
  drawn (two independent 1987 drawings agree); if the simulation needs damping there, a
  1K is the documented later fix.
- Cathodes and g3 to ground (fixed bias).
- RX93 lists 5881 as the UK valve with EL34 in its "USA changes" and "ADJUST BIAS TO -50V".

### Bias supply

| Part | GW87 / JP97 | SD68 | GW59 (100 W) | RX93 | M67 (100 W) |
|---|---|---|---|---|---|
| Feed from the HV winding | 220K | 220k | 27K (22K) | 180K | 33K |
| Rectifier | 10D8 | 10D8 | 10D8 | 1N4007 | diode |
| First cap | 8 uF | 8 uF | 8 uF | 10u 100 V | 8 uF |
| Series R | 15K | 15k | 15K | 15K | 15K |
| Second cap | 8 uF | 8 uF | 8 uF | 10u 100 V | 8 uF |
| To ground | 47K + 25K rheostat (bias adjust) | rheostat, value not printed | 47K + 27K rheostat | 56K + 22K preset | 56K, no pot |

The 220K is fed from one end of the HV secondary (GW87, SD68, JP97): a negative half-wave
supply. The bias node feeds the two 220K grid leaks. Pick GW87's (220K, 10D8, 8 uF, 15K,
8 uF, 47K + 25K). The setting: RX93 says -50 V for its version; for the 1968 amp it's set
for an idle current (provisional: model knowledge, see the voltages section).

### Power supply

- Mains: US versions in GW87 (primary taps 110 / 120 / 200 / 225 / 245 V) and SD68 (117 VAC;
  taps 110 / 120 / 200 / 220 / 240 V; "5 Volt tap not used"). Mains fuse 2 A (both), HT fuse
  1/2 A (both), standby switch (GW87: in both HV legs; SD68: after the HT fuse).
- Power transformer: SD68 prints 1202-118; RX93 lists 1202-324 ("MAINS TX"). No HV voltage
  printed anywhere. Replacement figure: Hammond 290GX (Digi-Key's Hammond list:
  "JMP 50 Watt", web: https://forum.digikey.com/t/marshall-jmp-50-watt-guitar-amp-replacement-transformers/26676),
  `hammond_290GX_pt.pdf`, web: https://www.hammfg.com/files/parts/pdf/290GX.pdf: 690 V CT
  at 150 mA (345-0-345 V), no-load 705.03 V; 6.3 V CT at 5 A (no-load 6.76 V); DCR 120 V
  primary 8.03 ohm (BLU-YEL; the sheet's label), HV RED-RED 91.5 ohm, heater 0.037 ohm
  (+-20 %); exciting current 473 mA max. A forum post on a JMP 50 reports the PT labelled
  "500 VAC ct" and an HV winding of about 70 ohm (web:
  https://music-electronics-forum.com/forum/amplification/guitar-amps/maintenance-troubleshooting-repair/21746-marshall-jmp-50w-voltage-question?p=317283;
  year not stated). The 1968 HV: provisional: model knowledge (Hammond's 345-0-345 V as the
  starting point; to be calibrated on the published plate voltage, below).
- Rectifier: silicon, full wave, centre-tapped HV. GW87: two diodes (type not printed, in a
  dashed box) with .22 uF across each half of the HV winding (printed "22" and ".22"; JP97
  ".22uF"); SD68: two 10D8 in series per leg; RX93: 1N4007 x 2 per leg. No GZ34 in any
  1987 drawing (the "5 Volt tap not used" in SD68 is the PT's unused rectifier winding).
- Filter chain (GW87 / JP97; SD68 in brackets):
  - Reservoir: 50 uF + 50 uF in parallel (SD68: 40 uF + 40 uF), feeding the OT centre tap
    directly (node "A" in JP97).
  - Choke from the reservoir to the screen node, which has 50 uF (SD68: 40 uF); the screens
    hang on it directly (node "B" in JP97). Choke value not printed (SD68: part C1999; RX93:
    1471-263). Hammond's replacement 194F (`hammond_194F_choke.pdf`,
    web: https://www.hammfg.com/files/parts/pdf/194F.pdf, "For JCP and JCM800", listed for the
    JMP 50 by Digi-Key above): 5 H at 120 mA DC, DCR 115 ohm +-15 %. Pick 5 H / 115 ohm
    (provisional: the replacement's, the original unmeasured).
  - Screen node to PI node: 10K/1W + 10K/1W in series (SD68: 8.2k/1W + 8.2k/1W); PI node
    50 uF (SD68: 40 uF). GW59 (100 W): 20K/1W; M67: 8.2K.
  - PI node to V2 node: 10K/1W, 50 uF (SD68: 10k/1W, 32 uF).
  - V2 node to V1 node: 10K/1W, 50 uF (SD68: 10k/1W, 32 uF).
  - Pick GW87's (20K total, 50 uF caps) with SD68's as the 1968 alternative: they differ by
    8 % in the screen-to-PI drop and in capacitance.
- Heaters: 6.3 V winding with its centre to ground (GW87), pilot lamp across it.

### Output transformer

Drake 784-139: printed on SD68 ("784-139") and in RX93's parts note ("OUTPUT TX: 784-139"),
so the 1987X reissue uses the same part number. Taps 4 / 8 / 16 ohm with an impedance
selector (GW87, SD68). Marshall publishes no figures. Replacement makers' numbers:

- Mercury Magnetics O50JM ToneClone: "Plexi/JMP Era - Drake 784 139 - 3.3 kOhm primary, 4,
  8, & 16 Ohm taps; For 2 x EL34's - bolt hole spacing is 2 1/2" x 2 1/2" - replaces
  original OT" (web: https://www.mercurymagnetics.com/mmpn/o50jm/); its spec sheet
  (`mercury_O50JM_ot_wiring.pdf`, web: https://www.mercurymagnetics.com/wp-content/uploads/shop/specsheets/O50JM.pdf)
  has the lead colours only (primary white / brown / red; secondary black COM, yellow 4,
  green 8, gray 16).
- Tube Amp Doctor M50A, "Made after specs analysed from an original transformer of an 50
  Watt Plexi Marshall from 1968": Raa 3.6k; EI96 lamination (3.75 in), stack 1 17/32 in;
  80 x 96 x 85 mm (web: https://www.tubeampdoctor.com/en/output-transf.for-marshall-50w-2x-el34-4-8-16-ohm;
  no DCR or inductance).
- Hammond 1750N (`hammond_1750N_ot.pdf`, web: https://www.hammfg.com/files/parts/pdf/1750N.pdf;
  "drop in replacement of original units such as Marshall JMP, JCM 800 (P-TM050)"; a
  retailer, not Hammond, lists it against the Drake 784-139: web:
  https://www.retroamplis.com/TRA-1750N/en): 3200 ohm CT : 4 / 8 / 16 ohm, 50 W; DCR primary
  BLU-WHT 41.74 ohm and WHT-RED 43.14 ohm, secondary BLK-YEL (4 ohm tap) 0.770 ohm; primary
  inductance BLU-RED 18.3 H (112 kOhm at 1 kHz, 1 V); leakage BLU-RED 13.41 mH (1 kHz, 1 V,
  secondary shorted); 70 Hz-15 kHz 0 / -1 dB; < 1 % THD at 70 Hz; page 2 has response,
  phase and THD+N curves (RS = 3200 ohm) for each tap. Its only DCR for the secondary is
  the 4 ohm section; the 8 and 16 ohm sections' DCRs aren't given.
- A forum post on a JMP 50 OT: "measures 3.5K" (the MEF thread above; year and method not
  stated).

Pick 3.4 kOhm plate to plate (provisional: between Mercury's 3.3k, TAD's 3.6k from a 1968
original and Mullard's 3.5k Ra-a, below), the windings from Hammond 1750N's DCRs, inductance
and leakage (web, as above) until a 784-139 is measured. Mullard's own push-pull data for
two EL34s use Ra-a 3.5 kOhm (sheet D2), the load Marshall's 3.3-3.6k sits at.

## Published voltages

Nothing prints voltages for a 1968-69 1987. What exists:

- `unicord_1959mk2_100w_voltage_chart.png`: "MARSHALL 100W. VOLT. CHART", page 2 of
  web: https://el34world.com/charts/Schematics/files/Marshall/Marshall_1959mkii_volt_chrt.pdf
  (3 pages: the GW Unicord 1959 Mark II (6550) drawing 70-6-11, this chart, the 1987 Lead
  Mark II drawing 70-23-11; the chart itself carries no maker's name, it is filed with the
  Unicord drawings; PDF sha256 `77a1fdfbb2fa48ee32a3d70a84bf116e1bbe87a9d5dd979365105154d4e86d2c`,
  not copied here; the PNG is page 2 rendered at 90 dpi and turned upright). For the 100 W with 6550s, but its preamp and inverter are the
  1987's circuit (on another supply):
  - V1 (ECC83): pin 1 135 V, pin 3 1.0 V, pin 6 195 V, pin 8 1.5 V;
  - V2: pin 1 153, pin 3 1.1, pin 6 260, pin 7 153, pin 8 153 V;
  - V3: pin 1 210, pin 3 18.5, pin 6 195, pin 8 18.5 V;
  - 6550s: pin 3 453, pin 4 450, pin 5 -51 V; "(Bias approx. -51 Vdc; primary current
    1.2-1.3 amps at 120 Vac)".
  The V1 readings fit the 1987's values: pin 3 1.0 V on 820 ohm (1.2 mA, 135 V plate) and
  pin 8 1.5 V on 2.7K (0.56 mA, 195 V plate, 100K load) on a ~250 V V1 node.
- M67 (100 W, c.1967) prints node voltages in boxes: V1 node 270 V, V2 node 300 V, PI node
  375 V, screen node 460 V (last figure hard to read).
- Forum figures (the MEF thread above): a poster quoting a chart in the Groove Tubes book:
  "expected power tube plate voltage of 380V for el34" (50 W), 395 V with 6550s, 530 V for
  100 W; 400 V called the expected minimum for 50 W Marshalls; one JMP 50 measuring 355 V
  sagging to 300 V at full power. A search summary of another thread: 353 V on a 1987
  before biasing, 375 V on a '73, 390-400 V with the heater corrected to 6.3-6.4 V. All
  secondhand; none states a mains voltage reliably.
- Pick for calibration: EL34 plates ~380-400 V at idle on 120 V / 240 V mains (provisional:
  the Groove Tubes chart as quoted plus the forum readings); idle current from Mullard's
  fixed-bias push-pull point (2 x 30 mA at 375-400 V, sheet D2) or ~70 % of 25 W
  dissipation (provisional: model knowledge, common biasing practice).

## Speaker: Celestion G12M "Greenback"

Celestion does not publish Thiele-Small parameters for its guitar speakers beyond Fs and
Re (Dickason, Voice Coil, Feb 2015: "Celestion, like most guitar speaker manufacturers
(e.g., Eminence, Weber, and others) do not publish full T-S parameter on their guitar
speaker products"). What Celestion publishes:

| | Heritage G12M (1960s spec recreated) | G12M Greenback (25 W, current) |
|---|---|---|
| File | `celestion_heritage_g12m_2006.pdf` | `celestion_g12m_greenback_25w_2006.pdf`, `celestion_g12m_greenback_current.pdf` |
| URL | web: https://c3.zzounds.com/media/G12M-bfc794c27a9aa184c14dd6baa7c0e830.pdf (Celestion sheet, 2006) | web: https://im.static-thomann.de/pics/atg/atgdata/document/specs/g12m20greenback.pdf (2006); web: https://celestion.com/productpdf.php?id=899 (current) |
| Power | 20 W | 25 W |
| Impedance | 8 and 15 ohm | 8 and 16 ohm |
| Sensitivity | 96 dB | 98 dB |
| Fs | 75 Hz | 75 Hz |
| Re | 6.57 and 12.13 ohm | 6.7 and 13.1 ohm |
| Voice coil | 1.75 in / 44.5 mm, round copper | same (current sheet: 44 mm) |
| Magnet | ceramic, 35 oz / 0.99 kg | same |
| Frequency range | 75-5000 Hz | 75-5000 Hz |
| Frame | pressed steel; diameter 309 mm, cut-out 283 mm, depth 130 mm, magnet structure 150 mm, 3.6 kg | same |

- Curves: each sheet has the 8 ohm frequency response (20 Hz-20 kHz, 70-110 dB SPL); no
  impedance curve. In the 2006 sheets the curve is not a raster image (the only images are
  the logo and the photo), so it is probably vector paths, readable exactly like the Jensen
  P12R's (`scripts/digitize_jensen_p12r.py`); not checked yet. Measurement conditions
  (baffle, distance, voltage) aren't stated on the sheets.
- History (Dickason, below): the G12M (T1221) was rated 20 W and was in most Marshall
  4 x 12s from about 1966; "by approximately late 1968, the G12M shifted from 20 to 25 W".
  So a 1968-69 cabinet may have either; the Heritage G12M is Celestion's recreation of the
  1960s 20 W version (15 ohm). Pick the Heritage figures (Fs 75 Hz, Re 12.13 ohm for the 15
  ohm unit, 96 dB).
- Not published, so provisional (to be fitted to the response curve the way `P12R@1`
  was): Le, Qms, Qes, Qts, Vas, BL, Mms (Mmd), Cms, Sd. The nearest measured relative is the
  Heritage G12H(55) (the G12M's heavy-magnet, 55 Hz sibling: 50 oz magnet, same family of
  frame and cone), measured by Vance Dickason, "Test Bench", Voice Coil, February 2015,
  `voicecoil_2015-02_g12h55_testbench.pdf`, web: https://celestion.com/wp-content/uploads/2019/10/141.pdf
  (two 16 ohm samples, LEAP 5 LTD and TSL fits, 1 V free air): Fs 54.7-67.4 Hz, Revc
  12.17 / 12.54 ohm, Sd 0.0543 m^2, Qms 9.48-15.48, Qes 0.39-0.53, Qts 0.37-0.51, Vas
  51.45-71.3 L, SPL 99.1-99.5 dB at 2.83 V, Xmax 0.7 mm; Celestion's factory Fs 55 Hz, 100
  dB. Its Figure 16 is the G12H(55)'s 1 V free-air impedance curve. Usable for the G12M:
  Sd 0.0543 m^2 (same 12 in frame and cone diameter; provisional: model knowledge that the
  G12M and G12H share it) and the order of magnitude of Qms; the G12M's lighter magnet
  means a lower BL and a higher Qes than the G12H's.

## Cabinet: Marshall 1960A / 1960B 4 x 12, closed back

- Outer dimensions (current production, which keeps the 1960s size): 770 mm W, 755 mm H,
  365 mm D, 37 kg for the 1960BX (straight, 4 x G12M-25 16 ohm, 100 W, unit 16 ohm): web:
  https://www.marshall.com/ae/en/product/1960bx-4x12-base-cabinet; the 1960B the same 770 /
  755 / 365 mm (web: https://www.marshall.com/us/en/product/1960b-4x12-base-cabinet). The
  1960A (angled) has the same width, height and depth with the upper half's baffle slanted
  (per a Reverb listing of a 1960AX: 770 / 755 / 365 mm; a retailer's figure, not Marshall's).
  1968 cabinets' dimensions weren't found in a period source.
- Internal volume: not published. Dickason (above) simulates "four G12Hs in a 4.6-ft3
  sealed enclosure ... the size of a Marshall half stack" (130 L), his choice, not a
  measurement. Provisional: from the outer dimensions with 18 mm panels (provisional: model
  knowledge, Marshall's birch ply thickness not sourced) the straight box is 0.734 x 0.719 x
  0.329 m = 174 L gross, less the drivers and baffle bracing; the angled 1960A less still
  (~150 L). Use 130-150 L as a genome range.
- Wiring: a 16 ohm cabinet of four 16 (or 15) ohm drivers is two series pairs in parallel
  (the 1960BX: four 16 ohm G12M-25s, unit impedance 16 ohm, Marshall's page above; the
  topology follows from the arithmetic, the page doesn't draw it). The amp's 16 ohm tap
  then drives it. Period cabinets with 15 ohm G12Ms come out at 15 ohm.

## EL34 data

- **Mullard** (in the repo: `data/datasheets/sources/mullard_el34.pdf`, 19 pages; provenance
  `data/datasheets/mullard_el34.provenance.yaml`, scan web: https://frank.pocnet.net/sheets/129/e/EL34.pdf).
  Page map (PDF page = sheet): 1 = D1 (ratings, characteristics), 2 = D2 (push-pull
  distributed load and fixed bias), 3 = D3 (cathode bias, triode), 4 = D4 (continuous sine,
  design-centre ratings), 5 = D5 (base), 6 = C1, 7 = C2, 8 = C3, 9 = C4 (triode plate, already
  digitized as `mullard_el34_triode_plate.csv`), 10-19 = C5-C14 (performance curves).
  - **Pentode plate curves: one figure only, C2 (PDF p. 7, drawing 3936)**: Ia against Va
    at **Vg2 = 250 V**, Vg1 = 0, -5, -10, -15, -20, -25 V; Va 0-500 V, Ia 0-300 mA; the
    Pa = 25 W hyperbola; no screen current.
  - C1 (PDF p. 6, drawing 4130): Ia and Ig2 against Vg1 at Va = Vg2 = 250, 325, 400 V
    (Vg1 0 to -60 V, I to ~400 mA): the only Mullard screen-current data, and the only one
    at a screen voltage near the Marshall's.
  - D2 fixed-bias push-pull (two valves): Vb 375 / 400 V, Rg2 600 / 800 ohm (common), Vg1
    -33 / -36 V, Ra-a 3.5 kOhm, Ia(0) 2 x 30 mA, Ig2(0) 2 x 4.7 / 2 x 4.5 mA, Vin(g-g) 46.7 /
    50 V rms, Pout 48 / 54 W, Dtot 2.8 / 1.6 %, Ia(max sig) 2 x 107.5 / 2 x 110.5 mA. C9 / C10
    (PDF pp. 14-15) plot that performance against drive.
- **Philips** (`philips_el34.pdf` in this folder, 21 pages, web:
  https://frank.pocnet.net/sheets/030/e/EL34.pdf; sheet dates 1952-1961 in its index):
  - PDF p. 10, sheet B: Ia against Va at **Vg2 = 250 V**, Vg3 = 0, Vg1 = 0, -5, -10, -15,
    -20, -25 V; Va 0-500 V (the same family as Mullard's C2).
  - PDF p. 11, sheet C (dated 2.2.1952): Ia against Va at **Vg2 = 360 V**, Vg3 = 0, Vg1 = 0,
    -4, -8, -12, -16, -20, -24, -28, -32 V; Va 0-750 V, Ia 0-500 mA. The highest-screen
    pentode family found, nearest the Marshall's ~400-450 V screen.
  - Other pages: transfer and performance curves (not inventoried here).
- JJ's and Svetlana's EL34 sheets weren't retrieved (the URLs tried returned HTML pages).
- **Published model parameters** (marked as such; not fits of ours):
  - Norman Koren's pentode model, Table 1 as corrected in his errata ("ERRATA AND MORE ON
    PSPICE TUBE MODELS", a mirror: web: https://wdv.com/Electronics/Software/SpiceVacuumTubes/errata.txt):
    EL34: MU 11, EX 1.35, KG1 650, KG2 4200, KP 60, KVB 24, CCG 15 pF, CGP 1 pF, CCP 8 pF,
    RGI 1K. Koren's article (web: https://www.normankoren.com/Audio/Tubemodspice_article.html)
    says "EL34 data came from the Audiomatica Sofia web page" and calls Table 1's numbers
    rough estimates.
  - Ayumi Nakabayashi's generic pentode model has an EL34 file (version 3.10, 2008),
    referenced in the diyAudio "Vacuum Tube SPICE Models" thread (web:
    https://www.diyaudio.com/community/threads/vacuum-tube-spice-models.243950/page-138);
    its parameters weren't retrieved. Adrian Immler's EL34 model is in the same thread
    (its author: the grid-current model "just guessed"). Duncan Munro's: not looked for.

## Year-to-year differences, summarized

- 1967 (M67, 100 W) to 1968-70: V1 from one shared cathode (820 / 250 uF) to separate ones
  (820 / 320 uF, 2.7K / .68 uF); treble cap 250 pF (M67, as read) to 500 pF.
- c.1968 (SD68) against July 1970 (GW87): V1 bright cathode 820 vs 2.7K; mixer and treble
  caps 560 vs 500 pF; screen-to-PI dropper 16.4K vs 20K; filter caps 32 / 40 uF vs 50 uF;
  bias pot without / with a 47K. Everything else is the same.
- 1993 reissue (RX93) against both: 22n bright coupling (vs .0022), 4n7 bright cap, 470p
  mixer and treble caps, treble 220K linear, middle 22K linear, V2a 1K unbypassed, 100K
  feedback, 4K7 / 680n presence, 100n PI coupling (UK), 470R screen resistors (UK), 5881s
  (UK), -50 V bias.
- 50 W against 100 W (GW59): only the output stage (4 x EL34, 5.6K grid stoppers, 1K screen
  resistors, 20K dropper, a bridge rectifier (4 x A10D10) into 100 + 100 uF in series with
  56K balancing resistors, as read) differs; preamp, stack and inverter are identical.

## File hashes (sha256, downloaded 2026-11-12)

```
9d9c6f97e3ba38424e2cbd282db2ba5d4ac59fa341097df8761f533181651b1e  celestion_g12m_greenback_25w_2006.pdf
ef746bedc84763b7c3869152eb1709d5327538ed6caf8f1d2135d851a01409aa  celestion_g12m_greenback_current.pdf
0eddf4161750c24b762777da21797e9354d2dd53edefdf50a9df1df7ced73f12  celestion_heritage_g12m_2006.pdf
a38f7e6fe68e87ff7f1f5c043cd9aa301a6afb106dc6de3e835992f95b57964b  gw_unicord_1959_70-6-11_jul1970.gif
b31b70c9e9e572d312bb696102ee83c139c6cca76d6b7ebfe85ffa13d5a7444a  gw_unicord_1987_70-19-11_jul1970.gif
ed9ba9c858f40d75b8744d91c72662cbad4ce5f36b9ae2d00f3c32db55a90f15  hammond_1750N_ot.pdf
e8e062a0900c5ea6d51bdaf7dbc215d561016a40775e095d31ac4e7a33d7d667  hammond_194F_choke.pdf
445b0c9448d00be4e7d04ff95aeee6604939cd9043ad9a912fc7d0f859aa3615  hammond_290GX_pt.pdf
6980fb3c9d7353ad1b4f4d5fa05ceda2457f7e272e0930337f1dc995d00c0313  marshall_100w_type2_c1967.gif
a6ef1f1761d6be68293f7e18f2c653427b1e39e0a4a41bf4f801d889ff06dac4  marshall_1987x_reissue_87X-60-02_iss6.pdf
4989ba566220018e32c1e05abd9e53a2ca9832dd570ee4a3e1c7f47542583f92  mercury_O50JM_ot_wiring.pdf
0d2d73430a7584bd5576e17aa98c1c9c1958d18634b0768e2571b169f9002a21  philips_el34.pdf
8b7eab155f71cdf4af9e4a505857b1c4cdb524b84a31e2d045ed338335bc6f54  piazza_1987_redraw_1997.gif
3918bb5c4147e4a8bf4cd2d5b7f7a1cc540cc211e160cb61115e51c3b17fdca8  sonicdeli_1987_circa1968_trace.pdf
5a908d251127a2a49faf3b87c45af3c76042fa456fc4ca708bdca17f43dd732a  unicord_1959mk2_100w_voltage_chart.png
b0590f732a25b640b64942c4002c6dc61e3a3f00cc1be854d24b7b76f8cbcb23  voicecoil_2015-02_g12h55_testbench.pdf
```

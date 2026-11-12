# Fender 5F1 Champ sources

Collected 2026-11-12 for the tweed Champ model (worktree `vst-amps`, branch `amps`): one 12AX7,
one single-ended 6V6GT (cathode bias), a 5Y3GT, an 8 in speaker. No circuit file exists yet;
values going into one should cite these as `sch:` (printed on Fender's schematic K-EE), `lay:`
(printed on Fender's layout K-EE only), `trace:` (a third-party drawing of the circuit), `web:`
(a replacement part maker's or a datasheet's figure) or `provisional:`. The transcriptions below
are from one research pass (2026-11-12): recheck each against its image when it goes into the
circuit file.

## The drawings (all in this folder)

| Tag | File | What it is |
|---|---|---|
| **SCH** | `schematic_k-ee.png` | "Fender "Champ-Amp" Schematic, Model 5F1", marked **K-EE**. Prints values, no designators, no voltages, no tube pins, no speaker or transformer data. |
| **LAY** | `layout_k-ee.png` | "Fender "Champ-Amp" Layout, Model 5F1", **K-EE**. Eyelet board, sockets with pin numbers, lead colours, and **DC voltages** at eight points ("voltages read to ground with electronic voltmeter, values shown + or - 20 %"; no mains voltage). |
| SCH-L, LAY-L | `schematic_k-ee_large.jpg`, `layout_k-ee_large.jpg` | The same two drawings at 2721 / 2390 px (Vero's blog). Same content; whether they are independent scans or upscales wasn't checked. |
| **RR** | `robinette_5f1_annotated_schematic.gif`, `robinette_5f1_power_flow.png` | Rob Robinette's annotations of SCH (designators R1-R13, C1-C7; his B+ figures and a 4 ohm speaker) and his DIYLC layout of the 5F1 ("325-0-325V 70ma", "8K:4ohm", "Volume 1M Log", "Optional V1A Bypass Cap 25V"). A third party's: `trace:` at best. |
| **MJ13** | `mojotone_5f1_layout_2013.pdf` | Mojotone's 5F1 kit layout, Steve Snyder, rev 1.0, 1/22/2013, with DC voltages ("values shown + or - 10 %"). |
| **MOD25** | `modelectronics_k-5f1_schematic_2025.pdf` | Mod Electronics' 5F1 chassis kit schematic (2025-06-11), the kit Amplified Parts sells (K-5F1), drawn with its transformers P-TGP-001 / P-TGO-001 and their lead colours. A modern kit, not a 1950s amp. |

Provenance:

- SCH and LAY: page 1 and 2 of web: https://www.thetubestore.com/lib/thetubestore/schematics/Fender/Fender-Champ-5F1-Schematic.pdf
  (copied as `fender_5f1_k-ee_thetubestore.pdf`, 2 pages, Acrobat 5 image conversion 2002); the PNGs are
  the PDF's embedded images extracted losslessly (`pdfimages -png`), 1306 x 994 and 1147 x 988 px.
- SCH-L, LAY-L: web: https://vero-p2p.blogspot.com/2024/07/fender-champs-schematics-layouts.html
  (the full-size Blogger images linked there: `.../s2721/Fender%20Champ%205F1%20Schematic.jpg`,
  `.../s2390/Fender%20Champ%205F1%20Layout.jpg`). The same Fender images are on Robinette's
  web: https://robrobinette.com/images/Guitar/HowAmpsWork/5F1_Schematic_Fender.png and `5F1_Layout_Fender.png`
  (1000 px, not copied).
- RR: web: https://robrobinette.com/How_Amps_Work.htm, images
  web: https://robrobinette.com/images/Guitar/HowAmpsWork/5F1_Annotated_Schematic.gif and
  web: https://robrobinette.com/images/Guitar/HowAmpsWork/5F1_Power_Flow.png (his layout PDF is
  `.../HowAmpsWork/5F1_Layout.pdf`, also MEF attachment 874307; not copied).
- MJ13: web: https://music-electronics-forum.com/filedata/fetch?id=832046
- MOD25: web: https://www.amplifiedparts.com/sites/default/files/associated_files/k-5f1_schematic.pdf
  (kit page web: https://www.amplifiedparts.com/products/amplifier-kit-mod-electronics-5f1-5w-amp-tweed-era;
  its assembly manual `k-5f1_instructions.pdf`, 44 pages, has no voltage chart; not copied).
- Only one Fender drawing of the 5F1 was found (K-EE). No 5F1 schematic with other values turned up.

## Values by stage

The pick is SCH / LAY wherever Fender printed the value. Tube pins from LAY's sockets, which agree
with RR and MOD25: 12AX7 input triode pins 1 / 2 / 3 (plate, grid, cathode), second triode 6 / 7 / 8;
6V6GT pin 3 plate, 4 screen, 5 grid, 8 cathode; 5Y3GT pins 4 / 6 plates, 2 / 8 filament (B+ from 8).

### Inputs (SCH, LAY)

- Two jacks, "1" and "2" (RR labels 1 Hi, 2 Lo). Each tip through **68K** to V1A's grid; **1 MEG**
  from jack 1's tip to ground. Jack 1's switch contact grounds its tip when nothing is plugged in;
  jack 2's switch contact joins its tip to jack 1's tip when nothing is plugged in (as drawn on SCH;
  LAY wires the same). So:
  - jack 1 alone: the two 68K in parallel (34K) into the grid, 1 MEG to ground;
  - jack 2 alone: 68K in, the other 68K from the grid to ground (jack 1 shorted): a 2:1 divider,
    input impedance 136K.
  (The two cases are this transcription's reading of the switch contacts; check against SCH.)

### V1A, 12AX7 (pins 1 / 2 / 3)

| Part | SCH | LAY | Others | Pick |
|---|---|---|---|---|
| Plate load | 100K | 100K | RR, MJ13, MOD25 100K | 100K |
| Cathode | 1500 | 1500, "+1.5 V" | | 1500 |
| Cathode bypass | **none drawn** | **none** (only one 25 uF on the board, at the 6V6) | RR "Optional V1A Bypass Cap 25V" 25 uF; MOD25 25 uF 50 V fitted; Vero's blog calls the missing cap "a schematic error" and says "many vintage amps have the bypass fitted from the factory, as the photos show" | **none** (both Fender drawings agree); 25 uF as the documented alternative (see differences) |
| Coupling to the volume | .02-600 | .02 MFD 600 VOLTS | RR, MJ13, MOD25 .022 uF | .02 uF |

### Volume

- **1 MEG** pot (SCH "1 MEG.", LAY "1 MEG."): top from V1A's coupling cap, wiper to V1B's grid
  directly (no grid stopper, no other grid leak), bottom to ground. Taper not printed; RR and MJ13
  print "1M Log", MOD25 "1M" (provisional: log, the kit drawings' value).
- The AC switch is on the volume pot (LAY: the black mains leads run to the pot; RR "Power Switch").

### V1B, 12AX7 (pins 6 / 7 / 8)

| Part | SCH | LAY | Pick |
|---|---|---|---|
| Plate load | 100K | 100K | 100K |
| Cathode | 1500 | 1500, "+1.5 V" | 1500 |
| Cathode bypass | **none** | none | none: the feedback returns here |
| Feedback | **22K** from the speaker's hot terminal (the OT secondary's hot end, also the jack's tip) to V1B's cathode | 22K from the cathode eyelet to the speaker jack | 22K, unbypassed cathode |
| Coupling to the 6V6 | .02-600 | .02 MFD 600 VOLTS | .02 uF |

The OT secondary's other end is grounded (SCH). With a tapped replacement OT the feedback comes from
the tap the speaker uses (MOD25: the 4 ohm, yellow).

### Output stage, 6V6GT, single ended, cathode bias

- Grid leak **220K** (SCH, LAY); **no grid stopper** drawn (SCH, LAY, RR, MOD25).
- Cathode **470** bypassed by **25 uF 25 V** (SCH "25-25", LAY "25 MFD. 25 VOLTS"); LAY "+18 V" at the
  cathode. Wattage not printed (RR 5 W, MOD25 3 W).
- Screen (pin 4) straight to B+2, **no screen resistor** (SCH, LAY).
- Plate to the OT primary; primary's other end to B+1 (SCH).

### Power supply (SCH, LAY)

- Mains: AC switch (on the volume pot), **2 AMP FUSE**, **.05-600** from the mains to chassis, pilot lamp
  on the 6.3 V winding. Mains voltage not printed. MJ13 draws a 1 A fuse and two 100 ohm resistors as an
  artificial heater centre tap: kit details, not Fender's.
- **5Y3GT**, full wave, HV centre tap to ground (LAY: red-yellow lead to the ground lug); B+ taken from the
  filament (pin 8).
- **No choke** (SCH: a 10K where the 5E1 had a choke; Digi-Key's Hammond list gives a choke, 194A 4 H at
  50 mA, for the 5E1 only).
- Nodes:

| Node | Feeds | Cap (SCH / LAY) | Dropping R (SCH) | LAY voltage | MJ13 voltage |
|---|---|---|---|---|---|
| B+1 | OT primary | 16-450 / 16 MFD 450 VOLTS | | **+340 V** | 370 V |
| B+2 | 6V6 screen | 8-450 / 8 MFD 450 VOLTS | 10K from B+1 | **+295 V** | 325 V |
| B+3 | both 12AX7 plate loads | 8-450 / 8 MFD 450 VOLTS | 22K from B+2 | **+250 V** | 275 V |

  Resistor wattages not printed (RR and MJ13 2 W; MOD25 10K 3 W).
- Heaters: 6.3 V winding, one side grounded (LAY: a green lead to the ground lug; SCH draws a ground on
  the winding) "to all 6.3 volt filaments and pilot lite". The replacements have a 6.3 V centre tap.

## Published voltages

| Point | LAY (Fender, +-20 %, electronic voltmeter) | MJ13 (Mojotone kit, +-10 %) | RR (his figures) |
|---|---|---|---|
| B+1 | 340 | 370 | 360 |
| B+2 (screen) | 295 | 325 | 325 |
| B+3 | 250 | 275 | 250 |
| 6V6 cathode | 18 | 19 | |
| V1A plate / cathode | 150 / 1.5 | 165 / 1.65 | |
| V1B plate / cathode | 150 / 1.5 | 165 / 1.65 | |

No mains voltage is stated anywhere. LAY's readings agree with its own resistors: 45 V across the 10K
(4.5 mA: the screen plus the preamp), 45 V across the 22K (2.05 mA: two 1 mA triodes, each 100 V across
its 100K and 1.5 V on its 1500 ohm), the 6V6 at 18 V / 470 ohm = 38 mA (plate plus screen).

Other figures:

- ClassicTone 40-18019 (`classictone_40-18019_champ_pt.pdf`, MEF attachment
  web: https://music-electronics-forum.com/filedata/fetch?id=832034; Magnetic Components drawing, rev A
  10/27/11): "MEASURED B+ VOLTAGES @ 70mA DC: 5Y3GT 383V DC, 5AR4/GZ34 392V DC" (mains not stated, the
  primary is 120 V 60 Hz).
- An Amplified Parts customer review of P-TGP-001 (David Adams, 2024-02-29, on
  web: https://www.amplifiedparts.com/products/transformer-power-325275v-63vct-5v-fender-champ): on the
  325 V taps "B+ was way too high and cathode current was over 45 milliamps"; used the 275 V taps. Anecdote.
- Pick for calibration: LAY's voltages (Fender's own), the PT's HV fitted so B+1 reads 340 V with the
  6V6 at ~38 mA (provisional: the mains of LAY's measurement unknown; 117-120 V assumed).

## Transformers

### Power transformer

Original: a Triad, Fender part 66079B in a 1959 5F1 (retrofret listing, below: "Both the power and output
transformers are the original Triads, reading 66079B and #106"). Later Fender numbers 125P1B and 022772
(Amplified Parts / Hammond cross-references). No original data found. Reproductions:

| | HV | Heaters | DCR (+-20 %) | No-load | File / URL |
|---|---|---|---|---|---|
| Amplified Parts P-TGP-001 (for 125P1B, 022772, 66079B; "Tweed 5F1 Champ") | 650 / 550 V CT at 100 mA (325 / 275 V taps) | 6.3 V CT 2.25 A, 5 V 3 A | primary 3.965, HV red-red 283.4, 6.3 V 0.134, 5 V 0.111 ohm | red/yel-red 351.25 V, red/wht-red/yel 297.7 V, 6.3 V 6.84 V, 5 V 5.42 V (+-2 %); Iex 146 mA at 120 V 60 Hz | `amplifiedparts_p-tgp-001_champ_pt.pdf`, web: https://www.amplifiedparts.com/sites/default/files/associated_files/p-tgp-001.pdf |
| Hammond 290AX (for 125P1B, 022772; Digi-Key's Hammond list: Champ 5F1) | 650 / 550 V CT at 100 mA | 6.3 V CT 2.25 A, 5 V 3 A | primary 3.927, HV red-red 277.1, 6.3 V 0.108, 5 V 0.091 ohm | 351.2 / 297.3 V per half, 6.841 V, 5.416 V (+-2 %); Iex 184 mA max | `hammond_290AX_pt.pdf`, web: https://www.hammfg.com/files/parts/pdf/290AX.pdf |
| ClassicTone 40-18019 ("Champ, Bronco, Vibro-Champ, Princeton, Princeton Reverb") | 650 V CT at 70 mA | 5 V 2 A, 6.3 V CT 2 A | not given | not given; B+ 383 V at 70 mA with a 5Y3GT | `classictone_40-18019_champ_pt.pdf` |
| Tube Amp Doctor 6500 ("for Fender Tweed Champ 5E1, 5F1") | 275-0-275 V at 50 mA | 6.3 V 2 A, 5 V 2 A | not given | not given | web: https://www.tubeampdoctor.com/en/mains-transf.-for-fender-tweed-champ-5e1-5f1 (230 / 240 V primary) |

Digi-Key's cross-reference: web: https://forum.digikey.com/t/fender-champ-guitar-amp-replacement-transformers/25845.
RR draws 325-0-325 V at 70 mA. Pick: 325-0-325 V (P-TGP-001's 325 V taps, the only reproduction with
both DCRs and no-load voltages), its DCRs as published, the HV calibrated on LAY's 340 V (provisional:
which of a reproduction's two taps the original matched is not known; the 275 V taps give MJ13-like or lower
voltages only with a different load).

### Output transformer

Original: a Triad, "#106" in the 1959 amp (retrofret). Fender part numbers for the Champ OT in the
cross-references: 125A35A, 125A3A, 022905. The original's primary impedance is disputed: a forum
summary (ampgarage, poster rp, 2013-01-25: "the word on the web seems to be 5K on the tweeds and 7-8K on
BFs", web: https://ampgarage.com/forum/viewtopic.php?p=348419) and the reproductions split between 5k
and 8k. No measurement of an original found. Reproductions:

| | Primary | Secondary | DCR | Inductance (1 kHz, 1 V) | Leakage (1 kHz, 1 V SC) |
|---|---|---|---|---|---|
| **Amplified Parts P-TGO-001** (for 125A35A, 125A3A, 022905; "Champ (Tweed, 5C1, 5E1, 5F1 ...)"; 5 W) | red B+; brown 5000, blue 8000 | black COM, yellow 4, green 8 | red-brown 374.7, brown-blue 122.1 (so red-blue 496.8); blk-yel 0.299, blk-grn 0.414 ohm | red-brown 7.8 H (57.2 k), "brown-blue" 11.9 H (80.7 k) (printed so; 11.9 H on the 122 ohm section can't be right: read red-blue); blk-yel 10.44 mH, blk-grn 20.48 mH | red-brown 13.9 mH, red-blue 20.2 mH |
| Hammond 1750C ("drop in replacement"; 125A35A, 022905, 125A3A) | 5000 / 8000 | 3.2 ohm | primary red-brown 255.84, brown-blue 73.89; sec 0.295 ohm | red-brown 14.25 H (84.12 k), red-blue 20.42 H (122.68 k); sec 64.53 mH (154.90 ohm) | red-brown 54.28 mH, red-blue 74.48 mH |
| Hammond 1760C (same cross-reference) | 5000 / 8000 | 3.2 / 8 / 16 | blue-red 359.90, brown-red 272.08; sec 0.278 / 0.624 / 1.491 ohm | blue-red 23.0 H (132 k), brown-red 16.2 H (92 k); sec 76.70 / 170.65 / 305.10 mH | blue-red 719.5 mH, brown-red 583.0 mH (as with the 1750E in the 5E3 README, Hammond's leakage figures look inconsistent with the rest) |
| Mojotone "Tweed Champ 5F1 Style NOS" 125A35A | 5000 | 4 ohm | | | (search summary only: the page returned 429) |
| Tube Amp Doctor 125A3A ("for Fender Champ 5F1", 5 W, max 35 mA) | 8.2 k | 4 ohm | | | web: https://www.tubeampdoctor.com/en/output-transf.-for-fender-champ-5f1 |

Files: `amplifiedparts_p-tgo-001_champ_ot.pdf` (web:
https://www.amplifiedparts.com/sites/default/files/associated_files/p-gto-001.pdf; the sheet calls itself
P-GTO-001, the shop's SKU is P-TGO-001; product page
web: https://www.amplifiedparts.com/products/transformer-output-5w-5k-8k-primary-fender-champ),
`hammond_1750C_ot.pdf` (web: https://www.hammfg.com/files/parts/pdf/1750C.pdf),
`hammond_1760C_ot.pdf` (web: https://www.hammfg.com/files/parts/pdf/1760C.pdf). The Hammond PDFs'
text layer is scrambled; the figures above were checked on the rendered pages (2026-11-12). The P-TGO-001's secondary inductances (10.44 / 20.48 mH, ratio 2) don't scale with its
taps' impedance ratio (4): copied as printed.

Pick: P-TGO-001 (the only reproduction with leakage figures that fit its own impedances), primary
**8k (red-blue)** into the **4 ohm** tap with a 4 ohm speaker, as MOD25 wires it (provisional: RR also
draws "8K:4ohm"; the 5k tap is the alternative the user may prefer; the original's ratio is unknown).

## Speaker

- Originals: "1 x 6" or 1 x 8", 4 ohms", models "Jensen P8T, Oxford 8EV or CTS AlNiCo" (Mojotone's field
  guide, web: https://mojotone.com/blogs/fender-field-guide/fender-narrow-panel-tweed-champ). The 1959
  amp above: "the original Oxford 8EV-29, dating to the 47th week of 1958 (465-847)", "the larger cabinet
  and 8" speaker, an upgrade from earlier models" (retrofret,
  web: https://retrofret.com/products/fender-champ-5f1-tube-amplifier-1959-10014). A 1956 5F1 at retrofret
  has "the larger cabinet but still a 6" speaker" (search summary only: the page returned 429). TubeDepot's
  PCB notes: "In 1958, the Fender Champ with it's 8" speaker and 5 watts" (web:
  https://www.hkjdwchip.com/image//files/tubedepot-pcb5e15f1-datasheets-2372.pdf). Hammond's 1750C
  ("drop in replacement") has a 3.2 ohm secondary, so period speakers may be 3.2 ohm nominal. So: 6 in
  until about 1958, 8 in from then; 4 (or 3.2) ohm.
- No data for a period P8T, Oxford 8EV or CTS was found. Jensen's reissue **P8R** (alnico, 25 W, 4 or 8 ohm;
  Jensen: "installed in thousands of Champ and Princeton style amps") is the only one with data:
  web: https://www.jensentone.com/vintage-alnico/p8r (`jensen_p8r_product_page.html`) and its spec sheet
  web: https://www.jensentone.com/specification-sheet/44 (`jensen_p8r_spec_sheet.html`):

| | 4 ohm | 8 ohm |
|---|---|---|
| Re | 3 ohm | 6.6 ohm |
| Fs | 129 Hz | 135 Hz |
| Qms | 8.67 | 8.67 |
| Qes | 1.71 | 3.09 |
| Qts | 1.43 | 2.28 |
| Mms | 9.3 g | 8.8 g |
| Cms | 164 um/N | 159 um/N |
| BL | 3.72 T m | 3.99 T m |
| Vas | 10.5 L | 10.3 L |
| Xmax | +-1 mm | +-1 mm |
| Efficiency | 1.27 % | 0.95 % |
| Sd | 213.8 cm^2 | 213.8 cm^2 |
| Res | 16 ohm | 27 ohm |
| Le (1 kHz) | 0.21 mH | 0.36 mH |
| Sensitivity (1 W, 1 m) | 94.1 dB | 91.8 dB |

  Also: overall diameter 207 mm, voice coil 25 mm, magnet 200 g (7 oz) alnico, flux density 0.96 T, coil
  winding depth 4 mm, gap depth 6 mm, copper coil, Epotex former, paper cone, integrated paper surround,
  solid paper dust dome, pressed steel basket, 1.2 kg. A search summary of a Full Compass copy of the PDF
  sheet (dated 03/08/2017) gave an 8 ohm Qes of 2.30; Jensen's own table says 3.09, which agrees with its
  Qms and Qts (1 / (1 / 2.28 - 1 / 8.67) = 3.09). The PDF itself (web:
  https://www.fullcompass.com/common/files/29324-JensenLoudspeakersP8RSpecSheet.pdf) returned 403 and isn't here.
- **Curves as numbers.** Jensen's product page carries its chart as data (Drupal settings,
  `frequency_response_charts`, a Plotly chart titled "Frequency Response on IEC Baffle (DIN45575) @ 1W,
  1 m - Free Air Impedance"), so nothing needs digitizing: `jensen_p8r_curves.json` is that object copied
  verbatim from `jensen_p8r_product_page.html`. Four series, "Sound Pressure - 4 Ω", "Impedance - 4 Ω",
  "Sound Pressure - 8 Ω", "Impedance - 8 Ω", each 121 points from 20 Hz to 20 kHz on a 1/12-octave grid;
  SPL in dB, impedance in ohm (log axis), so unlike the P12R's sheet the impedance has an ohm scale.
  Read off it: impedance peak 30.7 ohm (8 ohm unit) and 16.1 ohm (4 ohm) at the 126 Hz point (the grid's
  neighbours are 119 and 134 Hz), 7.4 / 3.6 ohm at 500 Hz, rising to 16.5 / 9.4 ohm at 10 kHz; SPL
  (8 ohm) 99.5 dB at 126 Hz, 95.7 dB at 1 kHz, 104.3 dB at 3 kHz, 81.4 dB at 10 kHz. The drive level
  behind "1 W" (2 V into 4 ohm or a fixed voltage) isn't stated. The baffle is the IEC 60268-5 one
  described in the 5E3 README.
- `jensen_p8r_drawing.svg`: Jensen's dimensional drawing (207 mm, 178.5 mm, 98.5 mm depth, 4 holes 8 x 5
  on 197 mm).
- Pick: P8R 4 ohm data (provisional: a reissue's figures stand in for a 1958 P8T / Oxford 8EV, whose
  magnets and cones differ).

## Cabinet

Tweed "narrow panel" Champ, open back. Outer dimensions:

- 1959 5F1 (retrofret, above): height 11 3/4 in, width 13 1/4 in, depth 6 1/2 in (29.8 x 33.7 x 16.5 cm).
- Mojotone's field guide: 5F1 "12 1/2" x 13 1/2" x 8"" (5E1 11 x 12 x 7 1/4), axes not named.
- Fender's '57 Custom Champ reissue: 12.5 x 13.5 x 7.6 in (H x W x D; zzounds, seen in a search summary
  only). A 1956 5F1 at retrofret: 12 x 13 1/2 x 7 1/2 in (search summary only).
- Amplified Parts' reproduction cabinet (CABINET-5F1): depth 8.875, height 13, width 14.5 in, "Pine and
  baltic birch construction", fits 8 in speakers (web:
  https://www.amplifiedparts.com/products/amplifier-cabinet-5f1-5w-amp-tweed-era).
- Wood, panel thickness, back panel sizes and the speaker's position on the baffle weren't found in a period
  source. Provisional: model knowledge (tweed cabinets are finger-jointed solid pine with a pine or ply
  baffle, open back with two partial back panels); take the speaker as centred and the back as open, as for
  the 5E3. Use 13.25 x 12 x 7 in (W x H x D, about the retrofret 1959 and field-guide figures) with the depth
  as a genome range 6.5-8 in.

## Version differences, summarized

- **V1A's cathode bypass:** none on SCH or LAY (K-EE); Robinette calls a 25 uF "optional", Vero's blog
  calls its absence a schematic error and says many vintage amps have it from the factory, and every kit
  drawing here (MOD25, RR's) fits it. Pick: none, as Fender drew it twice; the 25 uF is the first
  alternative to try (about +6-8 dB of first-stage gain, provisional: model knowledge).
- **Voltages:** Fender's 340 / 295 / 250 V against modern kits' 370 / 325 / 275 V (MJ13) and ClassicTone's
  383 V at 70 mA: today's mains (120 V and up) and reproduction PTs. Pick Fender's.
- **Speaker:** 6 in before about 1958, 8 in after; Jensen P8T, Oxford 8EV or CTS, 4 (3.2?) ohm. The model
  has only the reissue P8R's data.
- **OT primary:** 5k (Mojotone's "NOS", Hammond's 5000 tap) or 8k (TAD 8.2k, RR, MOD25); unknown for the
  original. Pick 8k.
- 5E1 against 5F1 (Vero's blog, Mojotone's field guide): the 5E1 has a choke where the 5F1 has the 10K, and
  V1A bypassed (1k5 with 25 uF).

## Not found or not read

- No measured data of an original 5F1 OT or PT (DCR, inductance, ratio). A tdpri thread on the OT ("5F1 OT
  primary impedance: 8K vs 4K speaker") is bot-walled (tollbit) and wasn't read; a metropoulos.net thread
  returned 403.
- Mojotone's transformer pages and several retrofret listings returned HTTP 429; their figures here come
  from search summaries and are marked so.
- No period Jensen P8T / Oxford 8EV data. Jensen's P8R PDF sheet (Full Compass copy) returned 403; the same
  figures and the curves are on Jensen's HTML pages, saved here.

## File hashes (sha256, downloaded 2026-11-12)

```
a847edfa79fc53fa5817364b87f2fadc8f4b6a34fe54c768f1c1f59c27c45468  amplifiedparts_p-tgo-001_champ_ot.pdf
ab601170d5b407a7fb1ee5b6ff1efb7edd0969c8933b7e8318b38dc452252c00  amplifiedparts_p-tgp-001_champ_pt.pdf
46133f80603a46502d6b997d464c4e58edacab29f5cb7d5182768b9f6021c19f  classictone_40-18019_champ_pt.pdf
a690a917217d5675edca0d15ec6c11c947d1bed935f5660c0e1695be197c4ca8  fender_5f1_k-ee_thetubestore.pdf
0b746ca926ba47aa5b82a00faa2bf93660784341757e5d95ce85e77009fa990c  hammond_1750C_ot.pdf
7ed7cb233d212c2c4066527da7736033d7f3e0620758ad19315950731cf8dcd5  hammond_1760C_ot.pdf
6bc87245f356701a563e75da5240b172bb710f2fc16b009ee44a317f294334d5  hammond_290AX_pt.pdf
937bf48bc21bc0100c069d3ab1f3ff38d22811e2c4e8b2d9ba7df0e2b358c228  jensen_p8r_curves.json
8f502a590457d38b2a25510c17af06933be7740ddae3088dbc0b959405afa620  jensen_p8r_drawing.svg
a05f48e648ad0dd90a8ff6691cfbdc7c71a04f78881548a09db83da844cd2a7d  jensen_p8r_product_page.html
eb81af9c3f1290fa2d9a31f63713a9f3e430c971f5697212408a45da8e1186d0  jensen_p8r_spec_sheet.html
a4d0d2b667ad20755ac07ce3bfa809112a253a540fb03f97e3477800a505b770  layout_k-ee.png
65469a7592a05e5ecfa9d8b7ff64c16786c9e20f29585429ac24b3b6e2b56918  layout_k-ee_large.jpg
33712132ba72da697b59028b70542febfbe973223bdd69445b08692701f6374c  modelectronics_k-5f1_schematic_2025.pdf
53c693774f491f6a3629d1fbc7b8bf5fbade93905a70755ae62b2d955e7740ff  mojotone_5f1_layout_2013.pdf
0c47ee2bf34062d42db0a1910e3709823be0e68b392a2ad6c8a7bb5591556e24  robinette_5f1_annotated_schematic.gif
84633a716af9a51c567252d3b5f209b1d77f2eea1461af116f96d250a439def7  robinette_5f1_power_flow.png
461cd50b4b4faa2640c7709d3dc925367a46dc2ee62679cc0237e965c55eabcb  schematic_k-ee.png
431bcf6fde91caed0c8ae75425d5c5d9d2232ad00fb37ff47802f7e4a31f4245  schematic_k-ee_large.jpg
```

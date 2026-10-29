# Fender 5E3 Deluxe sources

The device builder's B9 (docs/DEVICE_BUILDER_PLAN.md), collected 2026-10-29. Values in
`config/circuits/fender_5e3.yaml` (not written yet) will cite these as `sch:` (printed
on Fender's drawing), `lay:` (printed on the layout only), `meas:` (a published
measurement of a built amp) or `web:`. The transcriptions below come from a research
pass on 2026-10-29; recheck each against its image or URL when it goes into the
circuit file.

## Fender's drawings

"Fender 'Deluxe' Schematic, Model 5E3" and "Fender 'Deluxe' Layout, Model 5E3", both
marked F-EE. No designators; no DC voltages (the layout's notice box, "voltages read
to ground with electronic voltmeter, values shown + or - 20 %", has no values); no
mains voltage.

- Source: web: https://www.thetubestore.com/lib/thetubestore/schematics/Fender/Fender-Deluxe-5E3-Schematic.pdf
  (2 pages, downloaded 2026-10-29; sha256
  `18e5e653c3b653067840f19604c9421cd1a45553f873bd4fa8b21ceeef890a38`, 104 kB, not committed)
- Rendered at 200 dpi grayscale (pdftoppm) on 2026-10-29:

| File | Shows |
|---|---|
| `schematic_f-ee.png` | The circuit with printed values (below) |
| `layout_f-ee.png` | The eyelet board, pots, jacks and tube sockets with wiring; the V2A-to-inverter coupling capacitor's value (.02 MFD 600 V) is printed here only |

An annotated copy of the same schematic (Rob Robinette):
web: https://robrobinette.com/images/Guitar/5E3P_Build/5E3_Schematic_Annotated.gif
(sha256 `67e56603b7ce3293721fa60c99aadf717b0505e7be4b0f749f86e57d9a1e7f79`, not committed).

### What the schematic prints

- **Inputs:** two channels (Normal, Bright), two jacks each; per channel 1 MEG to ground
  and two 68K to the grid.
- **V1 12AY7:** both triodes on one cathode resistor, 820 ohm bypassed by 25 uF 25 V;
  100K plate loads; .1 uF 400 V coupling to each 1 MEG volume pot.
- **Volumes and tone:** the two volume wipers tied directly to V2A's grid (no mixing
  resistors). Tone pot 1 MEG: top through .0005 uF (500 pF, mica on the layout) to the
  top of the Bright channel's volume, bottom through .005 uF 600 V to ground, wiper to
  V2A's grid. Tapers not printed.
- **V2A (12AX7):** cathode 1500 ohm bypassed by 25 uF 25 V; plate 100K; coupling to the
  inverter .02 uF 600 V (layout).
- **Phase inverter V2B (12AX7):** cathodyne (split load): plate 56K, cathode 1500 then a
  56K tail to ground; its 1 MEG grid leak returns to the 1500 / 56K junction.
- **Output:** .1 uF 400 V (plate side) and .1 uF 200 V (cathode side) coupling, 220K grid
  leaks, 1500 ohm grid stoppers; two 6V6GT on one 250 ohm 5 W cathode resistor bypassed
  by 25 uF 25 V; screens straight to B+2 (no screen resistors); no negative feedback.
  Output transformer to the speaker jack and an "extra 8 ohm spkr" jack.
- **Supply:** 5Y3GT (B+ taken from its filament) -> B+1, 16 uF 450 V and the output
  transformer's centre tap; 5000 ohm to B+2 (16 uF 450 V, the screens); 22K to B+3
  (16 uF 450 V, V1, V2A and the inverter). No choke, no standby switch. Mains: AC switch,
  2 A fuse, ground switch with .05 uF 600 V, pilot lamp; 6.3 V for all heaters.
- **Pinouts** (from the tube datasheets, layout agrees): 12AY7 / 12AX7 pins 1/2/3 plate,
  grid, cathode of unit 2, 6/7/8 of unit 1; 6V6GT pin 3 plate, 4 screen, 5 grid,
  8 cathode; 5Y3GT pins 4 and 6 plates, 2 and 8 filament.

Modern kits differ in places (B+1 to B+2: Weber 4.7K 2 W, Amplified Parts 5.1K; tone
cap: Weber .0047 uF). No documented changes within 1955-60 production were found.

## Published voltages (no mains voltage stated in any)

- `typical_voltages_weber.png`: Weber's "typical voltages" (credited to Telenut62),
  web: https://robrobinette.com/images/Guitar/5E3P_Build/5E3_Voltages.png (sha256
  `770fc36f1b2dcdc5e96314871300b3488c1d6e3f0e055bfb2804bfaac007bce0`): B+1 / B+2 / B+3
  370 / 318 / 247 V; 6V6 plates 362, screens 317, cathodes 20 V; V2A plate 164, cathode
  1.2 V; inverter plate 200, cathode 45 V; 12AY7 plates 138 / 135, cathodes 1.9 V. (Its
  inverter grid reading, 17 V, is the meter loading the 1 MEG grid leak.)
- Amplified Parts (JJ tubes, their transformers): web:
  https://www.amplifiedparts.com/sites/default/files/associated_files/p-tgp-002_voltages.pdf:
  B+ 370 / 325.5 / 240.8 V; 6V6 cathodes 21.1 V; inverter 195.1 / 45.9 V; V2A
  157.7 / 1.22 V; V1 plates 136.2 / 128.5 V, cathode 1.76 V.
- Rob Robinette, web: https://robrobinette.com/How_The_5E3_Deluxe_Works.htm: B+ about
  370 / 295 / 250 V; idle currents 1.1, 1.1, 0.83, 0.84 mA (preamp, inverter) and
  38 + 38 mA (6V6s). His own build is modified (5881s, fixed bias): not a reference.

## Transformers (no original data; reproductions' figures)

- **Output:** original Triad 50246 (Fender 108; a 1961 Schumacher 125A1A per one
  listing). 8 k CT : 8 ohm in reproductions.
  - Amplified Parts P-TGO-002, web:
    https://www.amplifiedparts.com/sites/default/files/associated_files/p-tgo-002.pdf:
    8 k CT : 8 ohm 15 W; primary DCR 147.2 / 195.3 ohm per half; secondary 0.493 ohm;
    inductance per primary half 3.67 H (1 kHz, 1 V); secondary 16.7 mH; leakage
    40.47 / 19.31 mH per half.
  - Hammond 1750E, web: https://www.hammfg.com/files/parts/pdf/1750E.pdf: 8.5 k CT :
    8 ohm 15 W; DCR 150 / 150 ohm and 0.450 ohm; primary 24.0 H; its leakage (469.2 mH)
    and secondary inductance (822 mH) figures look inconsistent with its own impedance.
  - Construction: frame outlines only (Mercury FTDO-59, ClassicTone 40-18022:
    2-3/4" x 2-1/4", 3-1/8" mounting centres; Tube Amp Doctor quotes a 1" stack). No
    lamination, wire or interleaving data anywhere.
- **Power:** original Triad 6452; no original data. Reproductions disagree (HV
  330-0-330 to 380-0-380 V). Amplified Parts P-TGP-002 (120 V primary): 660 V CT at
  120 mA, 350.7 V per half unloaded; 6.3 V CT 2 A, 5 V 2 A; DCR primary 3.4, HV 174,
  6.3 V 0.098, 5 V 0.085 ohm (+-20 %).

## Speaker

Jensen P12R (some units P12Q), 8 ohm (inferred from the drawing's 8 ohm jack). Only the
reissues have data: web:
https://cdn.shopify.com/s/files/1/0543/2003/8061/files/Specification_Sheet_-_P12R___Jensen_Loudspeakers.pdf
(P12R: Re 6.05 ohm, Fs 80 Hz, Qms 13.07, Qes 2.50, Qts 2.1, Mms 25.2 g, Cms 157 um/N,
BL 5.53, Vas 54 L, Le 0.5 mH, Sd 490.9 cm^2, 93.7 dB) and the matching P12Q sheet
(Re 5.6, Fs 90.5, Qts 2.03, Mms 26.8 g, Cms 115 um/N, BL 5.88, Le 0.67 mH). The P12R
sheet has a response curve and an impedance curve (the latter without an ohm axis:
shape only).

Since component editor C3 (2026-10-29) the speaker is the component `P12R@1`
(`config/components/p12r/1.yaml`): the sheet's Thiele-Small figures
(`data/datasheets/published_points.yaml`, P12R), the voice coil's eddy-current pair and
eight breakup modes fitted to both curves. The curves are vector paths in the PDF, read
exactly (`scripts/digitize_jensen_p12r.py`, `data/datasheets/jensen_p12r.provenance.yaml`;
local copy `data/datasheets/sources/jensen_p12r_2022.pdf`); the plot runs to 20 kHz
though the page clips it at 8.5 kHz. The response was measured on the IEC 60268-5
(DIN 45575) standard baffle, 1650 x 1350 mm with the driver 225 / 150 mm off its centre
lines: web: https://psqca.com.pk/cs/newitems2021/electronics/28-PS%20IEC%2060268-5-2014_FINAL.pdf
(PS: IEC 60268-5/2014, Figure 2), the size also in Klippel's "The infinite baffle", web:
https://www.klippel.de/fileadmin/klippel/Files/News/ALMA2016%20-%20The%20infinite%20baffle.pdf.

## Cabinet

The tweed Deluxe's open-back pine combo cabinet, outer dimensions: a 1956 5E3 19 7/8 in
wide, 16 1/4 in tall, 9 1/2 in deep (web:
https://retrofret.com/products/fender-deluxe-5e3-tube-amplifier-1956-10761); a 1960 one
20 x 15 3/4 x 9 1/2 in (web:
https://retrofret.com/products/fender-deluxe-5e3-tube-amplifier-1960-8386); a
reproduction cabinet 20 x 16 x 9.5 in (web: https://www.cedist.com/node/47924). The
speaker's position on the baffle and the back panels' sizes weren't found: the speaker is
taken as centred (provisional; its vertical offset is the genome parameter
`fender_5e3.speaker.offset_y_m`) and the back as fully open (the panels aren't modelled).

## Tube datasheets (all with curves to digitize)

Digitized and fitted 2026-10-29 (B9 step 2): local copies in `data/datasheets/sources/`,
curves and provenance in `data/datasheets/` (`rca_12ay7`, `tungsol_12ay7`, `ge_6v6gt`,
`ge_5y3gt`), printed figures in `published_points.yaml`, components `12AY7@1`, `6V6GT@1`,
`5Y3GT@1`.

- 12AY7: RCA web: https://frank.pocnet.net/sheets/049/1/12AY7.pdf (250 V, -4 V: mu 40,
  rp 22.8 k, gm 1750 umho, 3 mA) and Tung-Sol web:
  https://frank.pocnet.net/sheets/127/1/12AY7.pdf (same point: mu 44, rp 25 k; the two
  disagree).
- 12AX7-A: RCA web: https://frank.pocnet.net/sheets/049/1/12AX7A.pdf (the project's
  12AX7 uses Koren's published parameters).
- 6V6-GT: GE ET-T914 web: https://frank.pocnet.net/sheets/093/6/6V6GT.pdf (plate,
  screen, grid-current, triode and transfer curves; push-pull AB1 285 V, -19 V: 70 mA,
  8 k plate to plate, 14 W).
- 5Y3-GT: GE ET-T965 web: https://frank.pocnet.net/sheets/093/5/5Y3GT.pdf (diode plate
  curve to 440 mA; regulation curves; 50 V drop at 125 mA).
- Koren's tables have no 12AY7 or 6V6; a forum fit for the 12AY7 exists (diyAudio,
  from Electro-Harmonix data; seen in a search summary only).

## Guitar level (for the input convention)

Rod Elliott, web: https://www.sound-au.com/articles/guitar-voltage.htm (into 10 MOhm,
~700 pF of cable): Strat-style single coils 250-450 mV peak on chords; a humbucker up to
850 mV peak; a hard strum at least 6 dB more.

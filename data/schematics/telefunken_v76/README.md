# Telefunken V76 sources

The device builder's B10 (docs/DEVICE_BUILDER_PLAN.md), found 2026-10-29. Values in
`config/circuits/telefunken_v76.yaml` (not written yet) will cite these as `sch:`
(printed on IRT drawing S 1176, by position number), `bb:` (the Braunbuch's text or
specs, by sheet) or `web:`. The transcriptions below come from a research pass on
2026-10-29; recheck each against the drawing when it goes into the circuit file.

## The IRT Braunbuch V 76

"Braunbuch-Beschreibung V 76", Institut für Rundfunktechnik, Ausgabe 1, 16 Jan 1959,
11 sheets: description (sheets 1-4), acceptance specs "Abnahmebedingungen" (5-9),
response curves for the 80 Hz and 120 Hz versions (10), and drawing S 1176
"Mikrofonverstärker" (11).

- Source: web: https://web.archive.org/web/20041218020142/http://www.irt.de:80/IRT/publikationen/braunbuch/V76.PDF
  (irt.de is gone; downloaded 2026-10-29; sha256
  `a609c2ea69831b1e814709d99c20be7247ec201685d0b34c14697bd0f1b9811d`, 5.7 MB, a plain
  image scan, not committed)
- `s1176_circuit.png`: sheet 11 at ~300 dpi, rotated upright. Every value, position
  number, DC voltage and current is legible.
- `braunbuch_sheet01.png` ... `braunbuch_sheet10.png`: sheets 1-10 at 150 dpi, 4-bit
  grayscale (pdftoppm, then ImageMagick).

Also in the same archived folder: the V76m (measurement version: TAB's preliminary
datasheet, factory drawing "V76m 01-25" of 13 Oct 1959, two filled-in factory test
reports), web:
https://web.archive.org/web/20041218020856/http://www.irt.de:80/IRT/publikationen/braunbuch/V76M.PDF
(sha256 `45c6aca99d82c1f943c7030a43100b9d8509c31163f32d5b631d52fde474f115`; its input
transformer is "V 372, 1:10", not BV 511). A redraw by Supersonic Communications
(web: https://wagner-microphones.com/images/v76.gif) has the values but shifted position
numbers on the feedback ladder: use the IRT scan.

### What S 1176 shows

- **Tubes:** V1, V2, V3 EF804S (V2 triode-connected), V4 E83F. Pinouts on the sheet.
- **Input:** an RF trap ("HF-Sperre", a dashed box: **not drawn**; sheet 4: tuned to
  about 173 kHz), then the gain switch's pad (3.4 k / 1.6 k / 450 ohm per leg, 200 ohm
  shunt), then T85 **BV Nr. 511, 1:30**, split primary, with the 40 Hz high-pass between
  the primary halves (C5-C8 4 x 2 uF, C9 2 uF with R54 300 ohm trimmed).
- **Gain:** 34-76 dB in 6 dB steps by feedback from V2's plate to V1's cathode (C15
  2 uF, R53 40 k, ladder R45-R52: 98, 108, 224, 470 ohm, 1 k, 2.4 k, 6.7 k, 19 k);
  3 / 9 / 18 / 24 dB by the pad.
- **V2's anode load:** choke BV Nr. 514, 400 H. **V4's:** choke BV Nr. 515, 250 H.
- **Filters:** 3 kHz cut (C20 1 nF + R68 25 k); bass cut 80 (or 120) / 300 Hz / both
  (C21-C24 and choke BV 516 100 H or BV 516a 62 H, by version, the drawing's table);
  15 kHz low-pass (C25 100 pF, L84 BV Nr. 517a 0.85 H, C26 100 pF).
- **Overall feedback:** R75 80 k (trimmed) + C31 2 uF from V4's anode to V3's cathode.
- **Output:** C35 4 uF into T89 **BV Nr. 512, 9:1** (parafeed).
- **Supply:** T90 BV Nr. 513; selenium bridge B450 C80, 300 V at 21 mA; filter 32 uF /
  1 k / 32 uF / 6 k / 32 uF (all 350 V); heaters 6.3 V, V1 on its own winding with a
  250 ohm hum pot.
- **Printed operating points** (e.g. V1 plate 67 V 0.6 mA, screen 97 V, cathode 11 V;
  V2 anode 175 V 3.6 mA; V4 anode 170 V 11.7 mA): the DC check's targets.

No winding data (turns, core, DCR) for any BV 511-517a part was found.

### Published specs (Abnahmebedingungen; 0 dB = 0.775 V; 200 ohm source, 300 ohm load)

Gain 3-76 dB (steps +-0.5 dB); input impedance >= 600 ohm 60 Hz-8 kHz (>= 300 ohm at the
band edges); output impedance <= 40 ohm (<= 30 ohm at 1 kHz); response +-0.5 dB
60 Hz-15 kHz, >= 12 dB down at 15 Hz, >= 20 dB down 40-200 kHz; bass-cut and 3 kHz
filter limits; distortion k2 / k3 <= 0.1 / 0.1 % at +12 dB out and 76 dB gain
(1 kHz, 5 kHz), <= 0.2 / 0.2 % at +22 dB, up to 1.0 / 1.5 % at 40 Hz with 34 dB gain;
noise <= -120 dB unweighted (-121 weighted) re input at 76-52 dB gain; 16 W.

## The V72's input transformer: a construction to validate against

NWDR Bauvorschrift Nr. 191, "Eingangsübertrager CTV 72/1" for the V76's predecessor,
web: https://web.archive.org/web/20120424210901/http://www.irt.de:80/IRT/publikationen/braunbuch/V72_EUE.pdf
(sha256 `cb36dd6b2f80eb1cb1fe63652f800f2c98fca9cbc6a1377005a661ecb4032d76`), rendered as
`v72_bv191_input_transformer_p1.png` ... `p5.png` (150 dpi, 4-bit gray): Hyperm 702
core (initial permeability ~12,000), EI 48, no gap (overlapped stacking), 0.35 mm
sheets, 16 mm stack, ~43 sheets / 210 g, disc winding with the section layout and
insulation drawn; primary 2 x 400 turns of 0.13 mm Cu, secondary 4 x 2000 turns of
0.06 mm Cu (per the research pass; check the later pages). A full construction: the
component editor's C2 can check its formulas against it.

The V72 itself: web:
https://web.archive.org/web/20041218015431/http://www.irt.de:80/IRT/publikationen/braunbuch/V72.PDF
(drawings S 843) and its datasheet
web: https://web.archive.org/web/20041218015535/http://www.irt.de:80/IRT/publikationen/braunbuch/V72_DB.PDF.

## Tube datasheets

- EF804 (Telefunken), web: https://tubedatabase.co/api/media/file/EF804.pdf
  (sha256 `1f14937c7a0285f765aceca175b55e7d4439663caeb79c99e91ce5d3b6353948`): plate
  curves at a 140 V screen (grid 0 to -4.5 V), transfer curves at 250 V for screens at
  60 / 100 / 140 / 180 V; no screen-current curves. The EF804S is the same system with a
  170 mA heater (web: https://www.radiomuseum.org/tubes/tube_ef804s.html).
- E83F (Philips, 1968), web: https://frank.pocnet.net/sheets/009/e/E83F.pdf (sha256
  `ae2bb7646e17c8232938f62cf1c1351c3f7141deca4d00d08ddf29e47beddcc4`): plate curves at
  120 and 150 V screen; Ia, Ig2 and gm vs grid voltage.

## A built unit's measurements

GroupDIY "V76 tube preamp build" (web: https://groupdiy.com/threads/v76-tube-preamp-build.68498/,
Jensen transformers): plate voltages 63 / 166 / 90 / 193 V against the drawing's
67 / 175 / 80 / 170 V; chokes measured about 416 H and 257 H at 100 Hz.

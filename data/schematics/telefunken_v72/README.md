# Telefunken V72 sources

The chains build-out's WP1 (docs/CHAINS_PLAN.md), found 2026-11-05. Values in
`config/circuits/telefunken_v72.yaml` cite these as `sch:` (printed on IRT drawing S 843,
sheet 2, by position number), `bb:` (the Braunbuch's text or acceptance specs, by sheet),
`ds:` (the Siemens datasheet) or `web:`.

## The IRT Braunbuch V 72

"Braunbuch-Beschreibung V 72, Studioverstärker", Institut für Rundfunktechnik, Ausgabe 1,
15 Dec 1953, 8 sheets: use and maker (1: Maihak, Hamburg, and Siemens & Halske, after an
NWDR design, in service from 1952), technical description and tube complement (2), the
acceptance specs "Elektrische Daten" (3-5), mechanics and operation (6), drawing S 843
sheet 1 "valid up to unit no. 300" (7) and sheet 2 "valid from unit no. 1001" (8).

- Source: web: https://web.archive.org/web/20041218015431/http://www.irt.de:80/IRT/publikationen/braunbuch/V72.PDF
  (downloaded 2026-11-05; sha256
  `95d8219d4b4706e021760faaa95e09d55dba2a09744d2c16a12d49b2fb785715`, 3.8 MB, an image
  scan, not committed)
- `braunbuch_sheet01.png` ... `braunbuch_sheet06.png`: sheets 1-6 at 150 dpi, 4-bit gray.
- `s843_sheet2_from_1001.png`: sheet 8 (S 843 sheet 2, from unit 1001) at 300 dpi,
  rotated upright: **the drawing the circuit file models**. `s843_sheet1_to_300.png`:
  sheet 7 (S 843 sheet 1, up to unit 300), the early version, for comparison.

### What S 843 sheet 2 shows

Read at full resolution on 2026-11-05. The drawing prints **no operating voltages**
(unlike the V76's S 1176).

- **Tubes:** V41, V42 EF804S, both pentodes with the suppressor (and the internal shield)
  to 0 V, not to the cathode as in the V76.
- **Input:** CT V72/1 (= NWDR Bauvorschrift Nr. 191, "2 x 1:20"; its construction below):
  EP1 and EP2 to the connector (pins 1, 2), the primary halves in series through C30 1 uF
  (between AP1 and AP2; its terminals also on the connector, to short it: sheet 2's text),
  the secondary ES to V41's grid, AS to 0 V, R11 400 k across it ("bedämpfter
  Übertrager", sheet 2), the shield S and the double mumetal can to the case.
- **V41:** cathode R12 1.25 k to 0 V; screen R15 800 k from the decoupled rail, R14 800 k
  to 0 V, C31 0.05 uF to 0 V; anode R16 200 k from that rail; R13 50 k from the choke's
  rail to it, C34 8 uF. C32 0.025 uF to V42's grid, R21 3 M grid leak.
- **V42:** cathode R22 500 ohm to 0 V; screen R24 30 k from the choke's rail and R23 200 k
  from the screen to the cathode; anode on the choke CK V72/1 (pos. 3, from the rail),
  C33 2 uF to the output transformer CT V72/2's AP (EP and its shield S to 0 V; AS, ES
  to connector pins 3, 4): parafeed ("gleichstromentlasteter Ausgangsübertrager mit
  Zylinderwicklung", sheet 2).
- **Feedback:** R18 80 k + R20 5 k ("abgegl.", trimmed at the factory to the gain: sheet
  2) from V42's anode to V41's cathode, C39 50 pF + C40 ~40 pF (a trimmer, set for the
  15 kHz response: sheet 2) across both; R19 50 k between the two cathodes (current
  positive feedback, lowering the output impedance: sheet 2). No capacitors in either
  path (sheet 2): V42's anode voltage biases V41.
- **Supply:** CT V72/N (mains on 1-2, a screen 3, heaters 6-7 with the 250 ohm hum pot 6
  and the 12 V pilot lamp 46, HV on 4-5) into an AEG selenium bridge 45 ("Trocken-
  gleichrichter in Graetz-Schaltung", sheet 2), C36 8 uF, R26 2.5 k, C37 8 uF, R27 2.5 k,
  C38 8 uF, then R25 2 k to the choke's rail (C35 8 uF), and R13 50 k on to V41's (C34).
  Fuse 44 80 mA.

Sheet 1 (up to unit 300) differs: R11 250 k, R12 1 k, R15 1 M, R14 700 k, R16 200 k,
R18 100 k with R17 5 k (no capacitor), R19 4 M from V41's anode to V42's anode (the
V77's "4 MOhm plate-to-plate link", GroupDIY below), R20 50 k between the cathodes.

### Published specs (sheets 3-5; 0 dB = 0.775 V; 200 ohm generator, 300 ohm load)

Gain 34 dB +-0.2 at 1 kHz, +6 dB out; input impedance >= 2 k (40 Hz-15 kHz); response
flat +-0.3 dB 60 Hz-10 kHz, 40 Hz down 0.3-1 dB, 15 kHz down 0-0.6 dB (15 Hz >= 6 dB and
40 kHz >= 6 dB "entfällt": dropped); distortion at +12 dB out k(40 Hz) <= 0.4%, k(1 kHz)
<= 0.1%, k(5 kHz) <= 0.1%; at +17 dB k(1 kHz) <= 0.3% (+13.8 / +14.5 dB points dropped);
output impedance <= 35 ohm, 40 Hz-15 kHz; noise <= 100 uV unweighted, 75 uV weighted
(I 77); mains 220 V 50 Hz, about 35 mA.

## The Siemens datasheet

"Der Studiovorverstärker V 72" (Siemens 6 S Ela 2303), web:
https://web.archive.org/web/20041218015535/http://www.irt.de:80/IRT/publikationen/braunbuch/V72_DB.PDF
(sha256 `7fe4ec03bc121445e4901cac309b65a67336cbc6b046d55dabbb3dbfe7a083b6`), rendered as
`siemens_datasheet.png`: the same specs, plus a maximum output of 5.5 V into 300 ohm at
0.3% THD (1 kHz), about 40 mA from the mains.

## The input transformer CT V72/1 (BV 191)

NWDR Bauvorschrift Nr. 191: the construction and its compiled versions are in
`data/schematics/telefunken_v76/README.md`, `config/designs/v72_bv191.yaml` and
`config/components/bv191/` (`BV191@3`: the field leakage and the facing capacitances,
docs/COMPONENT_EDITOR_PLAN.md C2 steps 5-6).

## The other wound parts (no NWDR data found)

- **Output transformer CT V72/2:** 11.2:1, 76 k / 600 ohm "original ratio" (E. A. Sowter's
  reproduction 1275, web: https://www.sowter.co.uk/acatalog/VINTAGE-RECORDING-AMPLIFIER-TRANSFORMERS-J-to-Z.html,
  checked 2026-11-05; also "the 11:1 V72 original", CJ on GroupDIY,
  web: https://groupdiy.com/threads/understanding-v72s-and-changing-gain.52362/). DC
  resistance of an original: 960 ohm / 12.1 ohm (smilan), ~1 k / 10 ohm on another unit
  (mjrippe), web: https://groupdiy.com/threads/v72-transformer-restoration.76310/.
- **Plate choke CK V72/1:** Sowter's 9375 ("similar to CKV72/1"): ~750 H with no DC,
  18.4 k, up to 7 mA (Sowter, above). CJ, rewinding one: "the stock turns for the Tele
  V72 plate choke" 22,500 in a 3-chamber bobbin; he also quotes 250 H (web:
  https://groupdiy.com/threads/telefunken-v72-choke-rewind.51676). The V76's 400 H
  choke's provisional construction scaled to 750 H gives 22,260 turns.
- **Mains transformer CT V72/N:** no figures. B+ "245" (CJ, the choke thread above).

## Published operating points

None from an original V72 was found (2026-11-05): GroupDIY's "V72 canonical voltages"
(web: https://groupdiy.com/threads/v72-canonical-voltages.86119) finds the voltages "all
over the map" between units and points to the V76's printed ones. CJ: the feedback path
raises the input tube's bias to "about 2.7 volts" (web:
https://groupdiy.com/threads/telefunken-v72-diy.6272/page-2), B+ about 245 V (the choke
thread).

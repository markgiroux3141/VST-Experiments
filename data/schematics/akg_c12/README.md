# AKG C12 sources

The chains build-out's WP3 (docs/CHAINS_PLAN.md: the C12 into the clean preamp and the UA
610), found 2026-11-05. This is the original C12 (1953-63: CK12 capsule, the 6072, T14/1,
the N12 supply and the S12 remote pattern unit), not the C12A, the C12VR or the ELA M 250 /
251. Values in `config/circuits/akg_c12.yaml` should cite these as `sch:` (the 1957 drawing,
by position), `br:` (AKG's English brochure), `desc:` (the early bilingual description),
`haufe:` (Haufe's T14/1 specification) or `web:`. Forum figures are marked as such and are
provisional at best. Transcribed 2026-11-05; recheck a value against its image when it goes
into a circuit file.

The PDFs and the drawing's JPEG are not committed (as for the U47's). Their URLs, sha256 and
sizes are below. The PNGs here are 16-level gray copies (the brochure pages are the PDF's
own page images, extracted, not resampled).

## The circuit: AKG drawing "C 12 + Power Supply C12" (1957)

A.K.G. drawing Z-Nr. 1231/5ch (reading uncertain), "Ersatz für: 1331/D", "Gezeichnet
11.3.1957", "Geprüft 11.3.57". The title "C 12 + Power Supply C12" is handwritten on the
title block. It draws the microphone (the 6072, the capsule, T14/1), the cables (Kabel 1,
connectors 8B26Ci / 6S26Ca; Kabel 2, 6S26Ci; Kabel 3 / NF 12, 3S17B), the supply **N12K**
and the remote unit **U2** (the S12's pattern switch). Typed note: "Attention: For No.1 cable
lengths of over 65 ft. the Heater Voltage requires adjustment as explained in the
'Operating Instructions'." Handwritten notes at the top: "Fil 6.3 DC", "10,000 pF
(0.01 µF)" (what it refers to isn't marked) and "plate $120+" (B+ 120 V or more). Some
lines are circled or annotated by hand ("8:1" next to the capsule, "RED", "GRÜ"); the
circled ones are illegible.

- Source: web: https://coutant.org/akgc12/c12schem.jpg (from the page
  https://www.coutant.org/akgc12, "Download the AKG C 12 schematic", courtesy of John
  Warshaw; 990 x 660 JPEG, 109,052 bytes, sha256
  `c1a9d2fa04929b6af103fda81d4061f83e2bd70571b16adaa76e050697a209f7`).
- `c12_n12k_circuit.png`: the JPEG as 16-level gray. Every value is legible at this size;
  the wiring was read by eye on 2x-3x zooms. **No voltages are printed.**

### The microphone (sch:)

| Pos. | Value | Where |
|---|---|---|
| Kapsel | CK12 | three terminals: front diaphragm, the backplate (centre), rear diaphragm |
| R12, R13 | 0.5 MΩ, 0.5 MΩ | divider from B+ (pin 5) to ground |
| R14 | 250 MΩ | the divider's tap to the backplate (its polarization) |
| C13 | 1000 pF | the backplate to the grid |
| R15 | 250 MΩ | grid leak, the grid to the bias node |
| R11 | 30 MΩ | pin 4 (the supply's bias) to the bias node |
| C10 | 5000 pF | the bias node to ground (the cathode line) |
| R16 | 30 MΩ | pin 3 (the pattern voltage) to the rear diaphragm |
| C11 | 5000 pF | the rear diaphragm to ground |
| 6072 | | one section: the cathode to ground; the heater "6.3 V" from pin 8 |
| R17 | 100 kΩ | B+ (pin 5) to the anode |
| C12 | 0.5 MF (µF) | the anode to T14/1's primary (its other end to ground) |
| T14/1 | | two secondaries strapped series / parallel, "200 Ω" (and 50 Ω) to pins 1, 2 |

The front diaphragm's terminal is wired to ground (pin 6). The second triode section's
electrodes are drawn tied together inside the envelope; the brochure's 175 mA heater (below)
is one section's (the 6072: 6.3 V, 150 mA per section, or 12.6 V / 150 mA in series), so
only one section is heated. My reading, not printed.

The pattern principle (br:, "By means of suitable polarizing voltages to both half-systems
of the capsule, the polar diagram can be selected"; the wiring above): the backplate sits at
half of B+ (R12 / R13) and carries the signal; the front diaphragm is at 0 V; the rear
diaphragm is set between 0 V (both halves polarized alike: omni) and B+ (polarized opposite:
figure-8), cardioid at the backplate's voltage (the rear unpolarized).

### The supply N12K (sch:)

- **Mains:** T 24657, primary taps 110 / 125 / 145 / 200 / 220 / 245 V; fuse R1 1 A; switch
  S.
- **Heater supply (pin 8):** bridge G1 B25/20-0,250 (selenium), a pilot lamp 30 V 0.01 A
  across the winding, R3 5 Ω 10 W, R2 20 Ω 4 W (adjustable), C1 1000 µF 30 V, C2, R4 5 Ω,
  G3 "YB24-101/17P" (a regulating diode), C3 2000 µF 12.5 V. Output 6.3 V DC (br: "6.3 vdc
  at 175 ma").
- **HV (pin 5, B+):** G2 "VR24-101/5 (E125 C5-12?)", a selenium half-wave; C4 2 x 50 µF
  350 V, R5 5 kΩ ½ W, R6 5 kΩ ½ W, C5 2 x 50 µF 350 V, R8 27 kΩ ½ W; the four capacitors
  alternate with the resistors (C4a, R5, C4b, R6, C5a, R8, C5b). br: "Plate voltage 120 vdc
  at 0.7 ma".
- **The bias (pin 4):** the HV winding's return and C4's two capacitors go to ground
  through **R7 1 kΩ ¼ W**; C5's return to ground directly. So the return node sits below
  ground by the HV's whole current times 1 kΩ. R10 1 MΩ ¼ W from it to C6 2 µF 160 V, whose
  node goes to pin 4 (a heavy hand-drawn line on the drawing). The grid's bias is that
  voltage (arithmetic, not printed: about -1 V at ~1 mA).
- **R9** 300 kΩ ½ W from B+ to the remote cable's pin 4, which ends unconnected in U2.

### The pattern unit U2 / S12 (sch:)

A nine-position switch on a ladder "R21-R29, 0.4 MΩ lin. (0.5 MΩ / Wid.)" from B+ (pin 5)
to ground (pin M); its wiper through R20 1 MΩ, C20 2 µF to ground, to pin 3 (the rear
diaphragm's voltage). The positions are marked figure-8 (top, B+ end), cardioid (middle)
and omni (bottom, ground end). R20 / C20 (2 s) and R16 / C11 (0.15 s) make the pattern
change slow (br: "without clicking or changes in level").

## AKG's published data

### Brochure, English (br:)

"Condenser Microphone Type C12 / with remote control of directional characteristics",
Akustische u. Kino-Geräte GmbH, Wien. Two leaflets in one 12-page PDF: pages 1-6 the later
one (its N 12 "entirely stabilized by a transistor amplifier and a Zener diode"), pages 7-12
an earlier one (printed in Austria, "1023 W 39"). Undated.

- Source: web: https://cieri.net/Documenti/AKG/Cataloghi/AKG%20-%20C12%20(Depliant)%20(English).pdf
  (1,652,939 bytes, sha256
  `108378385e06690265d084220c91474583943160bb53661257d3b8f1e6ecb00b`).
- `akg_c12_brochure_curves.png` (PDF p.3): **"Frequency response curves"**: omni at 0°;
  "cardioid / 8" at 0° (one curve) with cardioid 180° and figure-8 90°; 40 Hz-15 kHz (the
  rear curves to ~12 kHz). **"Polar diagrams"**: omni (100 / 1000 / 5000 Hz one line, 10 kHz
  dotted), cardioid and figure-8 (100, 1000, 5000, 10000 Hz). The polar scale: rings
  labelled 0-25 dB, the on-axis direction at the 20 ring (my reading: the curves meet there
  at 0°). The curves look drawn smooth; the text says "Each microphone supplied with a set
  of actual frequency response curves". Digitized: `data/datasheets/akg_c12_response.csv`
  (provenance in `akg_c12.provenance.yaml`); the polars not yet.
- `akg_c12_brochure_n12_s12.png` (p.2): the N 12 and S 12 text: 6072, cable up to 300 ft
  (65 ft supplied), the S 12 up to 600 ft from the supply.
- `akg_c12_brochure_data.png` (p.6): **Technical data**: 30-20 000 cps; response "see
  curve"; cardioid better than 20 dB front-back; bi-directional 20 dB discrimination;
  **sensitivity 1.0 millivolt per microbar at no load (200 ohms)**; equivalent noise level
  less than 22 dB; output impedance 50 / 200 ohms (change solder lugs); 1 x 6072; filament
  **6.3 vdc at 175 ma**; **plate voltage 120 vdc at 0.7 ma**; the C 12 255 mm (shell only),
  42 mm diameter, 520 g.
- `akg_c12_brochure_early_data.png` (p.11, the earlier leaflet): 30-20 000 cps;
  discrimination 0° / 180° (cardioid) about 15 db; output level -33 dbs re 1 mW for 10
  dynes/cm²; **sensitivity (for 200 ohms) 1 millivolt per microbar ±1.5 db**; output
  impedance 50 / 200 ohms; 1 x 6072; "Each microphone is delivered with its actual frequency
  response curves for 0° omni-directional, cardioid and bi-directional, and 180° cardioid".

Another copy of the technical data is on coutant.org's page (above): "Frequency Response:
± 2 dB related to published curve", "Sensitivity: 1.0 mV/µbar (-60 dB re 1 V/dyne/cm²),
unloaded (200 ohms)", "Equivalent Noise Level: less than 20 dB", "6.3 volts DC filament
voltage, 120 volts DC plate voltage".

### The early description (desc:)

"Für FM- und Fernsehen / FM, TV, High Fidelity", AKG, German and English, 3 pages: the
first C12, **with a 12AY7** ("eine Röhre 12AY7 und den Ausgangstransformator"), output
impedances 40, 250 and 500 ohm, the N 12 K (portable) and N 12 G (rack) supplies.

- Source: web: https://coutant.org/akgc12/akg-c12.pdf (250,670 bytes, sha256
  `0450f5eef72ecd72f670ce519f53d676c5b93abe17c172c8a579b6d49449a292`; scanned pages, no
  text layer).
- `akg_c12_description_p2.png`: photographs (the capsule on its head, the amplifier), the
  pattern dial (nine positions: omni, four intermediate, cardioid, ..., figure-8).
- `akg_c12_description_p3.png`: data: 20-15 000 Hz, deviations 50-10 000 Hz ±2.5 db, 30-15
  000 Hz ±3 db; cardioid 0° / 180° 15 db; **1 mV/µbar on 250 ohm**; output impedances 40,
  250, 500 ohm; C 12 258 mm, 42 mm, 0.65 kg.

The model is the 1957 drawing's (the 6072, T14/1, 50 / 200 Ω), with the later brochure's
data. The early 12AY7 version had another transformer (40 / 250 / 500 Ω).

## The output transformer T14/1

No AKG data. AKG's T14/1 (CTM 14/1 on Telefunken's drawings) was later made by Haufe; a
GroupDIY thread says the genuine first-generation Haufe T14/1 (1958 to ~1970) is 20.3 mm
long, and that the Haufe unit wasn't what AKG first used (forum, Klaus Heyne quoted;
web: https://groupdiy.com/threads/haufe-t14-1.54620). Taken as the C12's (the drawing
names T14/1).

- **Haufe's specification** (haufe:), "Type T 14/1", dated 18.7.07: web:
  https://www.don-audio.com/mediafiles//datasheets/Haufe-Specification-t14-DatasheetSun.pdf
  (136,915 bytes, sha256 `3edc9f9510a04d47cd6f9d412b62b3f8c98459cced10c16712945dbec1a659a0`),
  `haufe_t14_1_spec.png`:
  - turns ratio **11.5 : 1**; frequency range 40-20 kHz ±2 dB;
  - impedance 1 kHz **400 kΩ bu-bu** (the primary); inductance 1 kHz **350 mH rd-rd
    (gn/gn)** (a secondary);
  - coil resistance **bu-bu 3.08 kΩ; rd-rd 61 Ω** (±10%);
  - physical dimensions max **20.5 x 12 x 13 mm**; pinning bu, bu (primary), rd, rd, gn, gn
    (two secondaries).
- Forum figures (provisional): "0.5 + 0.5 : 11.5", primary DCR ~3 kΩ, secondaries 30 Ω
  each (Klaus Heyne, quoted on R/E/P; web:
  https://repforums.prosoundweb.com/index.php/topic,2525.0.html, refused to scripts); the
  Braunbuch's ELA M 251 drawing names "CTM 14/1" at 10:1 (the same thread). Primary
  inductance: ~160 H (vmanj, a reproduction), and "it appears it is the Haufe datasheet
  that is in error" (MagnetoSound) (web: https://groupdiy.com/goto/post?id=1100278).
  Haufe's 400 kΩ at 1 kHz is 64 H; its 350 mH x 23² (one secondary half at 0.5 : 11.5)
  is 185 H.

## The capsule CK12

No AKG drawing or measured geometry was found.

- **Austrian Audio, "The CK12 Capsule Demystified"** (Christoph Frank, on AKG's 1954
  patent and original capsules; web: https://austrian.audio/the-ck12-capsule-demystified/):
  two almost identical halves, each a membrane ring (the membrane glued on, 12 screws) on
  an isolator holding the electrode (drilled holes, pressed into the plastic isolator) and a
  resistance disk; the two resistance disks' offset holes joined by **a slit between the
  disks**, the gradient path's acoustic resistance ("most critical for the frequency
  response and polar pattern"); **membrane resonance "800-1500 Hz"** (varied across
  production); **the isolating distance ring 30-50 µm** (the membrane-electrode gap); **the
  slit's distance ring "around 50 µm"**, customized per microphone at the factory; rear
  rejection about 20 dB at 180°, "very consistent". Its figure "CK12 frequency response
  relative to resistance disk configuration" (web:
  https://static.wixstatic.com/media/748547_e970029522274c0aad07542708914aa6~mv2.png): a
  tuned capsule's 0° sensitivity about **-46 to -47 dBV/Pa** from 100 Hz to 3 kHz, a rise to
  about -43 dBV/Pa at 6-14 kHz, its 180° about -62 dBV/Pa at 100 Hz and -67 to -70 at
  0.5-2 kHz (read by eye; polarization and load not stated).
- **Mix** (web: https://www.mixonline.com/recording/vintage-microphones-part-3-akg-c-12-c-24-and-telefunken-250251-377062,
  a restorer's article): the first CK12 used 10 µm "Styroflex" film, later 9 µm then 6 µm
  Mylar; two perforated brass electrodes, the inner hole patterns offset (at least 1.25 mm
  apart); early capsules had small chambers, a later change enlarged them and the air gap
  ("about 3 dB" more sensitivity); a resonance near 12 kHz.
- coutant.org (above): "hand-tensioned, edge-terminated"; "a small dip at around two kHz
  and a well-chosen presence rise".
- Forum (provisional): diaphragms "about 1 inch", gold over the whole film; a CK12 clone
  maker's 27 mm diaphragm and 34 mm capsule (search results, not checked); a replica
  measured 105 pF diaphragm to backplate and 52 pF between its backplate halves, 4 µm film
  (kingkorg, "has nothing to do with real CK12"; web:
  https://groupdiy.com/threads/new-ck12-capsule-measurements.84671).

## The patent on the brochure

"Patents: Austria Pat.no. 180313, Western Germany DGM 1714870" (br:). AT 180313 B
"Kondensatormikrophon", Akustische u. Kino-Geräte, filed 1953-04-30, published 1954-11-25
(web: https://patents.google.com/patent/AT180313B/de: no text or drawing there; DEPATISnet
refuses scripts). Not read.

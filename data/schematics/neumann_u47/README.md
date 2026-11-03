# Neumann U47 sources

The mic plan's A3 (docs/MIC_ROOM_PLAN.md: the U47 in free field, then U47 -> cable -> V76),
found 2026-11-03. This is the original U47 (VF 14 M, BV 08, M 7 / K 47 capsule), not the
U 47 fet. Values in a future `config/circuits/neumann_u47.yaml` should cite these as `sch:`
(the 1959 factory drawing U 47-00-00-00, by position number), `ds58:` (Neumann's March 1958
data sheet), `man58:` / `man59:` (the operating instructions), `br:` (Neumann's undated
U 47 / NG brochure), `fs48:` (Funkschau 1/1948, the VF 14's data), or `web:`. Forum and
vendor statements are marked as such below and are provisional at best. Transcriptions were
made on 2026-11-03. Recheck each value against the image when it goes into a circuit file.

The PDFs are not committed (the same as the V76's). Their URLs, sha256 and sizes are listed
below. The PNGs here were rendered from them with PyMuPDF and reduced to 16 gray levels.

## Where the documents come from

Neumann's current site has a download API behind its "file finder" (the product page
https://www.neumann.com/en/products/historical/u-47 has a Downloads link). The historical
U 47 documents are served from `assets.sennheiser.com/download/assets/<file>/<id>`. They
were found by POSTing `{"searchQuery": "U 47", "pageSize": 100, "pageNumber": 1}` to
`https://www.neumann.com/api/neumann/downloads/assets` (headers `Accept-Country: DE`,
`Accept-Language: en`). The full URLs are given per document below.

## The circuit: factory drawing U 47-00-00-00 (1959)

"Georg Neumann, Kondensatormikrophon U 47", drawing U 47-00-00-00. Its title block reads
"Georg Neumann Laboratorium für Elektroakustik, Berlin SW 61, Segitzdamm 2". On
radiomuseum's 500 px thumbnail 2529392, one date field reads about "28.1.59" (uncertain
at that resolution).
Jogi's copy (below) is cropped above the title block and carries the marks "3.6.59 Ga."
and "10.9.59 dü".

- Source: web: https://jogis-roehrenbude.de/Roehren-Geschichtliches/Neumann-Mikro/U47/u47_sch.jpg
  (from the page https://jogis-roehrenbude.de/Roehren-Geschichtliches/Neumann-Mikro/U47/U47.htm,
  credited there to Dieter Kühne; 1400 x 960 JPEG, 118,237 bytes, sha256
  `2d29caf0aac19baba16ea4416127bb348a50edf837a51d2ad9d283fec8c8d2d6`). The same drawing
  with its title block is radiomuseum's schematic 2529392, web:
  https://www.radiomuseum.org/images/schematic-medium/neumann_georg/kondensatormikrofon_u47_2529392.png
  (a 500 px thumbnail). The full resolution needs radiomuseum's free registration.
- `u47_circuit_1959.png`: the JPEG converted to 16-level gray PNG. Every value is legible.
  The drawing notes "Alle Spannungswerte statisch gemessen" (all voltages measured
  statically). The voltages in ovals below are the printed ones.

### Transcribed (sch:)

| Pos. | Value | Where |
|---|---|---|
| KK47 | capsule, "2 x 78...83 pF" | two halves, each 78-83 pF |
| R1 | 100 MΩ | polarization feed from the R7/R8 tap to the backplate |
| C1 | 0.01 µF, 500 V | backplate to ground (AC ground of the backplate) |
| R2 | 60 MΩ | grid leak, front diaphragm / g1 to ground |
| Rö 1 | VF 14 M | g2 and g3 tied to the anode (triode connection) |
| R3 | 29 Ω | cathode (joined to heater f1) to ground: bias by the heater current |
| R4 | 1780 Ω | heater dropper, +105 V to heater f2 |
| R5 | 100 kΩ | anode load |
| R6 | 30 kΩ | anode decoupling, +105 V to R5 |
| C3 | 1 µF, 160 V | R5/R6 junction to ground |
| R7 | 2 MΩ | polarization divider, +105 V to tap |
| R8 | 3 MΩ | polarization divider, tap to ground |
| C2 | 0.5 µF, 250 V | anode to BV 8 primary |
| Ü1 | Bv. 8 | output transformer (below) |
| S1 | 200 Ω / 50 Ω | secondaries in series / parallel |
| St 1 | Tuchel T 2045, 6 pins | pin 1 ws and pin 2 bl: audio; 3: joined to 4; 4: -A -H (ground); 5: +A 105 V; 6: housing |

The resistor symbols are marked 0.25 W "nach MIL" or 0.1 W "nach DIN 41399".

Printed DC values: +105 V at St 1/5, about 40 mA; anode about +34 V at about 0.55 mA;
cathode +1.1 V; heater f2 +36 V; backplate +63 V (105 V x 3 / 5 = 63 V).

These agree with Ohm's law (my arithmetic, a check only):

- the anode is 105 V - 130 kΩ x 0.55 mA = 33.5 V;
- the heater current is (105 - 36) V / 1780 Ω = 38.8 mA, so the heater runs at about
  35 V (36 - 1.1) and 38.8 mA;
- the cathode is (38.8 + 0.55) mA x 29 Ω = 1.14 V. The grid sits at 0 V DC, so the bias
  is about -1.1 V.

**The pattern switch (KK47).** The switch is drawn between the rear diaphragm and the front
diaphragm (the grid side). The backplate is the capsule's center electrode, polarized at
+63 V through R1 and AC-grounded by C1. The front diaphragm is at 0 V DC through R2 and
carries the signal to g1. The switch's two symbols are cardioid (up) and omni (down).
Neumann's brochure (`br:`, "Wirkungsweise") says the side facing the source sits at the
grid with a fixed polarization ("festliegende Ladespannung"). The other side gets, through
the switch, a polarization of the same sign for omni, and "das Potential Null" (no
polarization) for cardioid. Neumann's "General information about the U 47" (docu0067,
below) agrees. With one membrane connected the capsule is a cardioid. With both halves in
parallel it is omni.

**Open question.** On this 1959 drawing the cardioid position just opens the contact, so
the rear diaphragm floats (no DC path drawn). A redraw of unknown origin on Jogi's page
(web: https://jogis-roehrenbude.de/Roehren-Geschichtliches/Neumann-Mikro/U47/wiring-u47.jpg,
sha256 `a5eff71108bf6e2dcbec09fe36854ae03a0e8e16b806edbd94af6caa267a714a`) is labelled
"contact = omni" and draws the same. Check this on a unit or a later drawing: it decides
the rear diaphragm's electrostatic force in cardioid.

### Earlier revision (about 1953)

Radiomuseum has three Neumann factory drawings as 500 px thumbnails:

- "Schaltung f. U 47", S 03 Tz 3, web:
  https://www.radiomuseum.org/images/schematic-medium/neumann_georg/stromversorgung_netzgerat_ng_fur_3265453.png
  (sha256 `078f27e0811fbaa7a37f839dfbeb1f8653455e5fef8e1157fa2a83851fe611f9`),
  `u47_circuit_early_drawing_thumbnail.png`;
- the NG drawing (below);
- a hand-drawn variant (3265454).

They are listed under the NG on web: https://www.radiomuseum.org/r/neumann_stromversorgung_fuer_neumann_typ_u47_ng.html.
Partly legible: 100 MΩ (two), 0.01 µF, 30 Ω cathode, 1780 Ω, 2 M / 3 M, 100 k, 30 k,
1 µF (coupling) and 1 µF. So early units had a **100 MΩ grid leak and a 1 µF coupling
capacitor** where the 1959 drawing has 60 MΩ and 0.5 µF. The redraw above has the same
early values. A GroupDIY post reports two 100 MΩ resistors to the capsule in some units
against 100 / 60 MΩ in others (web: https://groupdiy.com/goto/post?id=1144490, forum).
Pick one revision and say which one.

The circuit description in Phædrus Audio's VF14M manual (below) has a further redraw:
30 k / 100 k, 2 M / 3 M, 100 M / 100 M, 1800 Ω dropper, 25 Ω cathode, 0.05 µF backplate
capacitor, C2 1 µF. It is a vendor redraw. Use it only as a cross-check.

## Neumann's published data

### Data sheet, March 1958 (ds58:)

"Kondensatormikrophon U 47 u. U 48 mit Zubehör", März 1958, 2 pages (the data and plots,
then the description).

- Source: web: https://assets.sennheiser.com/download/assets/cata0080_u47-u48-03-1958-deutsch.PDF/6f1c26c0dc0011f0b5fb16ac7ce906bd
  ("Brochure U 47, U 48, 03/1958 German"; 190,032 bytes, sha256
  `ef7326588ceda3df87815cd6830907764d0a4952ed3317db6a3979cce743e3ec`). Byte-identical
  to Jogi's copy, web: https://jogis-roehrenbude.de/Roehren-Geschichtliches/Neumann-Mikro/U47/Neumann-U47.pdf.
- `neumann_u47_u48_datasheet_1958_p1.png`:
  - polar plots of the U 47 (omni, cardioid) and the U 48 (figure-8) at 100, 1000, 5000,
    10000 and 15000 Hz;
  - frequency responses (dB, 40 Hz-15 kHz, -10...+10 dB) for the U 47 "Stellung" omni and
    cardioid and the U 48's figure-8;
  - the technical data.
- `neumann_u47_u48_datasheet_1958_p2.png`: the description, operating notes, the NG and
  the UC 4 cable.

Transcribed (ds58:):

- **Sensitivity** at 1 kHz into 1000 Ω: U 47 cardioid about 2.5 mV/µbar (= 25 mV/Pa),
  omni about 1.4 mV/µbar; U 48 cardioid about 2.0 mV/µbar, figure-8 about 1.4 mV/µbar.
- **Equivalent loudness** (DIN 5045): cardioid about 15 phon, omni about 20 phon (U 48:
  18 / 20).
- **Frequency range** 35-15000 Hz.
- **Output impedance** 200 / 50 Ω, switchable.
- **THD** < 0.8 % up to 110 phon (1000 Hz).
- **Tube** VF 14 M (Telefunken). **Supply** 100 V, 40 mA DC.
- **Size and weight** 240 mm long, 63 mm diameter, 0.7 kg.
- **NG:**
  - mains 110 / 220 V; fuses 0.3 / 0.125 A; 15 W max;
  - "Fremdspannung" (hum and noise at the output) about 5 µV;
  - neon lamp 110 V E 14; 220 x 100 x 120 mm, 2 kg.
- **UC 4 cable:** 10 m (max. 50 m), 1.3 kg; stand thread 1/2 in.
- Text:
  - the amplifier holds "einen Ausgangsübertrager mit zwei symmetrischen
    Sekundärwicklungen";
  - "Der Übertrager ist für einen stetigen Abfall der Frequenzkurve unterhalb 35 Hz
    dimensioniert" (the transformer is designed for a steady roll-off below 35 Hz);
  - dynamic range about 100 dB;
  - UC 4 has 4 shielded conductors;
  - Tuchel connectors: a 6-pin socket "similar to T 3039" on the mic, T 3038, T 3037,
    T 3040, and T 3081 / T 3080 for the modulation;
  - the VF 14 M needs about 30 s to warm up;
  - the load should be at least 5x the source impedance;
  - the mic may run unloaded.

### Brochure, undated (br:)

"Mikrophon U 47", Georg Neumann Laboratorium für Elektroakustik GmbH, Berlin-Schöneberg,
Geneststrasse 5, 2 sheets (fold-out).

- Source: web: https://assets.sennheiser.com/download/assets/cata0217_U47_D.PDF/28e91dc4dc0111f0887916ac7ce906bd
  ("Brochure U 47, German"; 317,684 bytes, sha256
  `ba05e3f29046fae6cc3f4680686a67edcb61e4a4e78dec6a03398451a7c2e1bf`).
- `neumann_u47_brochure_p1.png`: the NG's electrical data; cardioid and omni responses
  (30 Hz-18 kHz, dB); polar plots (cardioid at 100 / 1000 / 5000 / 10000 / 15000 Hz, omni
  at 1000 / 5000 / 10000 / 15000 Hz). The response curves look smoothed (idealized).
- `neumann_u47_brochure_p2.png`: construction, operating principle, electrical and acoustic
  data, the NG's construction.
- The date isn't printed. Its NG still has a choke ("Siebdrossel"), which radiomuseum
  dates before about 1955 (below), so it is probably early 1950s. That date is my inference.

Transcribed (br:):

- **Microphone:**
  - 30-15000 Hz; 200 or 50 Ω; about 2.5 mV/µbar; cardioid or omni;
  - noise voltage at the output about 1.5 µV; equivalent loudness < 18 phon;
  - THD < 1 % up to 120 phon; supply 100 V, 40 mA DC; 240 mm long, 63 mm diameter,
    0.7 kg;
  - connector Tuchel T 2045 / T 2046;
  - "e0 bei 1000 Hz: Niere = 2,5 mV/µb - Kugel = 1,6 mV/µb" (on the response plot).
- **Operating principle (verbatim):** "Das Mikrophon U 47 arbeitet nach dem
  Druckgradientenprinzip in niederfrequenter Schaltung. Das Doppelmembransystem stellt
  dabei eine Kombination von zwei Nierenmikrophonen dar, die entgegengesetzt gerichtet
  sind. Die der Beschallungsrichtung zugekehrte Systemseite liegt am Gitter der Röhre und
  hat im Betrieb eine festliegende Ladespannung. Die andere Systemseite erhält mittels des
  Schalters für die Richtcharakteristik eine gleichnamige Ladespannung für die Kugel und
  das Potential Null für die Niere."
- **NG (electrical):**
  - power 15 W loaded, 4 W unloaded;
  - mains current 85 mA at 220 V, 160 mA at 110 V;
  - DC out 40 mA at 100 V;
  - hum ("Brummspannung") about 5 µV.
- **NG (construction):**
  - mains transformer, full-wave rectifier ("Doppelweggleichrichter"), reservoir
    capacitor, a smoothing choke and **four RC filter sections**;
  - 220 x 100 x 120 mm, 2.8 kg;
  - Tuchel flange T 3040 B (mic), T 3081 M (3-pin modulation).

### Telefunken U 47 M brochure, 1952

"Kondensatormikrofon U 47 M", Telefunken Geschäftsbereich Elektroakustik (printed 1.52).

- Source: web: https://assets.sennheiser.com/download/assets/cata0081_u47m-1952-deutsch.PDF/6f03528adc0011f0bd88aa72af6619c2
  (86,856 bytes, sha256 `60218a5a2df089669c258d8abe3065ccd4c82de91b50ee5de06d1915dff5f086`).
- `telefunken_u47m_brochure_1952.png`: data, pinouts, mains wiring of the supply, a small
  response plot (30 Hz-20 kHz, +-1 dB grid).
- Values:
  - 200 Ω (50 Ω on request);
  - response re 1 kHz: down to 30 Hz +-1 dB, to 15000 Hz +-3 dB;
  - sensitivity at 1 kHz: cardioid 2.8 mV/µbar (-49 dB), omni 1.7-2 mV/µbar (-53 dB);
  - "Rauschgrenze" (0 dB = 2 x 10^-4 µbar) 24 dB; distortion <= 1 %; VF 14;
  - 60 mm dia., 240 mm, 0.8 kg;
  - supply "U 47 N": 110 / 220 V 40-60 Hz, 245 x 100 x 125 mm, 3.3 kg.
- Mic pins (solder side): 1-2 audio ("Ton"), 4 minus supply, 5 plus supply, 3 and 6 line
  ground. Supply's 3-pin out: 1-2 audio, 3 shield.

### Factory response and polars, 1952 (thumbnail)

"Mikrofon U 47", Georg Neumann Laboratorium f. Elektroakustik, Berlin-Schöneberg. Dated
1952 (the day is not legible). Radiomuseum schematic 3265455.

- Source: web: https://www.radiomuseum.org/images/schematic-medium/neumann_georg/kondensatormikrofon_u47_3265455.png
  (500 px, sha256 `c79a4258501f3dda04c268390d8b291499daccb584eea038c4daac50ea035d74`),
  `u47_response_1952_thumbnail.png`.
- "e0 bei 1000 Hz = 2,8 / 1,7 mV/µb". Responses 30 Hz-20 kHz. The cardioid rises to a
  presence peak of about +3 dB near 9-10 kHz. The omni dips around 4 kHz, then peaks near
  8 kHz. Polars: cardioid at 100 / 1000 / 5000 / 10000 / 15000 Hz, omni at 1000 / 5000 /
  10000 / 15000 Hz.
- These are **measured-looking curves**, unlike the brochure's smooth ones. The
  full-resolution scan is behind radiomuseum's free registration (worth getting for A3's
  targets).

### Catalogue, 1949

"Georg Neumann, Laboratorium für Elektroakustik", 1949 (German / English / French), 6 pages
(U 47 and MM 2, capsules, P 2, AM 31, pistonphone).

- Source: web: https://assets.sennheiser.com/download/assets/cata0218_U47_MM2_M5-9_P2_AM31_Pisto_D_E_F_1949.PDF/2c1be986dc0111f0887916ac7ce906bd
  (946,928 bytes, sha256 `ead8015c564b5894010cf312f68077d740edba5797f1524fe78a17924fd98ea3`).
- `neumann_catalogue_1949_u47.png`:
  - U 47: 200 Ω symmetrical; response re 1 kHz to 30 Hz +-2 dB, to 15000 Hz +-3 dB;
  - sensitivity -50 dB re 1 V/µbar; lower limit 24 dB (0 = 2 x 10^-4 µbar);
  - THD < 1 %; 15 VA; 0.8 kg, supply 3.3 kg; "9 octaves", 30-120 phon.
- `neumann_catalogue_1949_capsules.png` (the CMV 3 capsules M 5, M 7, M 8, M 9): "Die
  Kapazität dieser Kapseln beträgt etwa 100 pF und die erzeugte Modulationsspannung bei
  einer Ladespannung von etwa 50 V ungefähr 1 mV pro Mikrobar". M 7 = cardioid. A capsule
  weighs 175 g.

### Operating instructions (man58:, man59:)

English, May 1958, web: https://assets.sennheiser.com/download/assets/opin0044_u47-u48-englisch-05-1958.PDF/b5f31992dc1311f08c187ec57e6db003
(103,139 bytes, sha256 `d1648d29220bbbf69d52b8e88dd8a6f8f6ce4332c029ca8d4c33a482f771e355`),
`neumann_u47_u48_manual_1958_en.png`.

German, Aug. 1959, web: https://assets.sennheiser.com/download/assets/opin0043_u47-u48-deutsch-1000859-08-1959.PDF/b5031078dc1311f089cc26996c1245dc
(103,926 bytes, sha256 `b7f45498fd01ba684cba48b6e8397ddd4fe1319a8cd6bf83713d834e9c5d9b6f`),
`neumann_u47_u48_manual_1959_de_p1.png`, `_p2.png`.

Transcribed:

- **Data:**
  - 35-15,000 Hz; 200 or 50 Ω;
  - U 47 about 2.5 mV/µbar (cardioid), U 48 about 2.0;
  - THD < 0.8 % (1 kHz) up to 110 dB SPL (man58);
  - 1 VF 14 M (selected);
  - NG 105 V DC (40 mA), "the heater voltage is taken from the 105 volt supply";
  - UC 4 standard length 33 ft (10 m), "lengths up to 300 feet" (man58), "bis zu 100 m"
    (man59).
- **Load:** designed into 250 Ω or 1000 Ω. The source is set to 1/5 of the load: 50 Ω for
  250 Ω, 200 Ω for 1000 Ω (supplied strapped for 1000 Ω).
- **Gain (man58 D.5):** "For microphones adjusted to a source impedance of 200 ohms, the
  gain of the amplifier amounts to approximately 3 db". The test capsule Z 9 (a capacitor
  standing in for the capsule): "A voltage of 100 mv at the test capsule Z 9 is equivalent
  to a sound pressure of 70 µbar (110 phon) at the microphone capsule". **This is a
  measurable target for the VF 14 + BV 8 model.** The load during the measurement isn't
  stated.
- **D.6:** without a microphone, the supply voltage is **about 300 V** (open-circuit).
- **C.11:** warm-up about one minute, "due to the 55 volt heater voltage".

### Nuvistor conversion notices (the NG's filter)

Neumann U 47-960-01-00 (German, June 66) and U 47-960-02-00 (English, July 66), one PDF.

- Source: web: https://assets.sennheiser.com/download/assets/docu0033_conversion-u47-u48-nuvistor-13cw4-englisch-und-deutsch-u479600200-07-1967.PDF/63c76864dc0211f0864e26996c1245dc
  (108,730 bytes, sha256 `c98bf2d276ff950eb63bf57e933958423b8fd7cb0a85f0f8bbb436d3effb666c`),
  `neumann_nuvistor_conversion_1966_de.png`, `_en.png`.
- Also, English 06/1968 (U 47-960-02-01), web:
  https://assets.sennheiser.com/download/assets/docu0032_conversion-u47-u48-nuvistor-13cw4-englisch-u479600201-06-1968.PDF/63cbb824dc0211f0910426996c1245dc
  (139,815 bytes, sha256 `72084192af39a901d92dc24249024134fbcef1e3455d34e42156c0e2f0fef094`).
  The same text is reproduced in Phædrus Audio's manual.
- **NG's output filter (the version in service in 1966):** bridge Gr 1 -> C1 -> R2 -> C2 ->
  R3 -> C3.
  - R2 is "1 kΩ power resistor coming from + terminal of rectifier".
  - R3 is "an identical resistor next in the RC filter chain" (so 1 kΩ).
  - Capacitor values are not given.
- The conversion moves R2 parallel to R3 (500 Ω) for the nuvistor's heater current, or adds
  1.5 kΩ, 3 W in series at pin 5 of an unconverted mic. After conversion the output is
  2-3 dB lower.

### General information about the U 47 (Neumann)

"U 47 – The Legend", Neumann historical collection, 1 page, web:
https://assets.sennheiser.com/download/assets/docu0067_historical_collection_U47.PDF/702de75edc0211f0ba6b7ec57e6db003
(109,819 bytes, sha256 `f66e1e183424c13cbbb049c8c9b2e6f1fbcbb160fe9371bba06e2b3175e469d1`).

Not rendered. Its text, transcribed:

- **The M 7:** "two equal diaphragms fixed on both sides of a perforated center electrode
  which is also provided with a number of cavities on both sides".
- **The cardioid:** sound from the front reaches the inner side of the rear membrane
  through the perforations and the outside of it around the capsule. "The acoustic
  properties of the center electrode cause the forces acting on the rear membrane to be
  equal in size, but opposite in direction", so the rear membrane doesn't move.
- **Omni:** both halves are cardioids. Connected in parallel they give omni. One membrane
  connected gives a cardioid.
- **The tube:** "A steel vacuum tube VF 14 M ... a pentode being operated as triode". The
  heater is fed from the one supply through a wire-wound resistor in the amplifier housing.

## VF 14 (VF 14 M)

The VF 14 is the EF 14 pentode with the 50 mA series ("V") heater (Funkschau 12/1947,
below; radiomuseum). Neumann selected tubes for low grid current, noise and microphony and
marked them "M". The U 47 runs it **triode-connected** (g2, g3 to the anode: `sch:`;
docu0067), with the heater underrun at about 35 V / 39 mA (sch:, computed above).

### Funkschau 1/1948, pages 6-8 (fs48:)

"VF 14, Daten und Kennlinien" (Telefunken's data, compiled by Funkschau after F. Kunze's
article in 12/1947).

- Source: web: https://www.worldradiohistory.com/INTERNATIONAL/Funkschau/1948/Funkschau%201948-01.pdf
  (16 pages, 8,034,881 bytes, sha256
  `ce1b208ccb2d94ce7792bdccad562236bb716fd769d4830b2f996542e10c6d4c`; the VF 14 pages are
  PDF pages 8-10). A second scan of the same issue:
  https://www.worldradiohistory.com/INTERNATIONAL/Funkschau/1948/Funkschau-1948-01.pdf
  (3,856,370 bytes, sha256 `733ab2ea2d86bef3a44db0bfaef94f0043e7e4c22aaaeefff2271d0aff9c9997`).
  The scans are about 150 dpi.
- `funkschau_1948_vf14_p6.png`: heater, pentode / tetrode operating points a)-f),
  Kennlinienfeld 1-4 and 9 (pentode Ia, Ig2 vs Ug1 and Ua; screen current).
- `funkschau_1948_vf14_p7.png`: operating points g)-p) (RC-coupled pentode and triode
  stages, mixers, audion), Kennlinienfeld 5-6.
- `funkschau_1948_vf14_p8.png`: **Kennlinienfeld 7 and 8, "Triodenschaltung, Schirmgitter
  und Bremsgitter an Anode"**: Ia = f(Ug1) at Ua = 100 / 150 / 200 V, and Ia = f(Ua) for
  Ug1 = 0 ... -8 V, Ua 0-280 V, Ia 0-40 mA, with the dissipation limit. Also Kennlinienfeld
  10 (screen current), the output-stage operating points q)-s) and the limits.

Transcribed (fs48:):

- **Heater:** 60 V, 50 mA, indirectly heated, AC / DC. Neumann's 1958 manual says "55 volt
  heater voltage" and radiomuseum records both 55 and 60 V. The U 47 underruns it at about
  35 V either way.
- **a) RF pentode (g3 at the cathode):**
  - Ua 200 V, Ug2 200 V, Ug1 -4.5 V, Rk 300 Ω;
  - Ia 12 mA, Ig2 1.7 mA, S 7 mA/V;
  - screen Durchgriff 3.5 %; Ri 200 kΩ; equivalent noise resistance 1000 Ω.
- **b) tetrode (g3 at the anode):** Ia 18 mA, Ig2 1.6 mA, S 9.5 mA/V, D 3.6 %, Ri 50 kΩ,
  noise resistance 600 Ω.
- **s) output triode (g2, g3 at the anode):**
  - Ua 200 V, Ug1 -4.5 V, Rk 225 Ω, Ia (with Ig2, Ig3) 20 mA;
  - Ra 5 kΩ, 1 W at 5 % distortion.
- **Limits:**
  - Ua max 300 V; Ug2 max 200 V; Qa 5 W; Qg2 0.7 W; Ik 30 mA;
  - grid leak max 0.5 MΩ (Qa >= 2 W) / 1 MΩ (Qa < 2 W);
  - **grid current onset Ig1 <= 0.3 µA at Ug1 = -1.3 V**;
  - heater-cathode 100 V, 20 kΩ;
  - "Die VF 14 darf nur mit automatischer Gittervorspannung betrieben werden" (cathode
    bias only).
- **Derived (my arithmetic):** a screen Durchgriff of 3.5 % suggests a triode-connected µ
  of about 1/0.035 ≈ 29. This is a starting value for a fit, not data.

**Caveat for the fit.** The triode curves are drawn on a 0-40 mA scale. The U 47's point
(about 34 V, 0.55 mA, -1.1 V) sits in the bottom-left corner, where the curves can't be
read. Fit the curves for the shape and anchor the low-current end on the drawing's static
point. Grid current matters here: the U 47 runs the grid at -1.1 V through 60-100 MΩ,
against the sheet's 0.3 µA at -1.3 V. That is why Neumann selected tubes "M" for low grid
current (Phædrus, below).

### Funkschau 12/1947, "Neue Röhren: VCH 11 und VF 14" (F. Kunze)

- Source: web: https://www.worldradiohistory.com/INTERNATIONAL/Funkschau/1947/Funkschau%201947-12.pdf
  (4,523,306 bytes, sha256 `210d6e3bba6e7e28f1f7200bd02be80e49930ea742858420ea32161d5c8876b2`).
- Not rendered: the VF 14's curves follow in 1/1948.
- Text:
  - the VF 14 is the EF 14 with the 50 mA series heater;
  - its operating data differ from the EF 14's in places because they refer to 200 V
    anode;
  - steel bulb, 36 mm diameter.

### Telefunken EF 14 sheets (the same system)

Telefunken EF 14, "Vorläufige Daten", sheets 011144, 021144 (1944) and 170839, 180839
(1939), 8 pages plus Frank Philipse's index page.

- Source: web: https://frank.pocnet.net/sheets/076/e/EF14.pdf (446,049 bytes, sha256
  `842cd8108d874f3f0604a82c769a0399fbbc59eb024bf3988e79e2de9939cfa5`; identical to
  https://r-type.org/pdfs/ef14.pdf).
- `telefunken_ef14_p1.png` ... `_p8.png`:
  - 6.3 V / 470 mA heater; operating points at 250 V;
  - pentode Ia / Ig2 vs Ug1 and vs Ua (g3 at the cathode and at the anode);
  - capacitances: input 9-10 pF; with g3 at the anode, output 9.4-10.6 pF and g1-anode
    < 0.15 pF;
  - the base (Y8A, pins g1, k, m, g2, f, f, g3, a).
- No triode-connected curves.
- RFT (VEB Funkwerk Erfurt) EF 14, 1953, web: https://frank.pocnet.net/sheets/082/e/EF14.pdf
  (89,956 bytes, sha256 `28492d3e9dd355ddb0b2d66295fbea1e92d3a230608c026833dedb2286a45777`):
  data only, no curves. Not rendered.

### Other VF 14 notes

- Radiomuseum, web: https://www.radiomuseum.org/tubes/tube_vf14.html:
  - Vf 60 V, If 0.05 A; base Y8A;
  - equivalent noise resistance 850 Ω;
  - in the U 47, about 35 V / 40 mA heater, supply about 105 V.
  - References: Telefunken-Röhrentaschenbuch 1955 pp. 64, 98f, 109; Funk-Technik 21/1947
    p. 6 and 22/1947 p. 7f; Ratheiser 1949 p. 314.
- Phædrus Audio, "VF14M Product Manual" v3.0 (2016), web:
  https://www.phaedrus-audio.com/Phaedrus%20VF14M%20Electronic%20Tube%20Products%20Manual_Ver3.pdf
  (560,703 bytes, sha256 `2b9a1c417888405c92fbff49f957ca2e2760b4fcd17ae7f6ceea7c37d17353f4`).
  A vendor of a solid-state VF 14 replacement.
  - Operating conditions:
    - heater 35 V, 40 mA via 1800 Ω; HT 90 V at the top of R5; anode load 100 k;
    - anode about 35 V; grid 0 V; grid resistor 60-100 MΩ; cathode about 1 V across R3.
  - Statements (vendor, unverified):
    - Neumann rejected about 2/3 of VF 14s for grid current, noise and microphony;
    - about 27,000 VF 14 were made.
  - The Neumann nuvistor notice is reproduced in its appendix.
- TAB-Funkenwerk (Oliver Archut, a vendor), "Telefunken Steel Tubes", web:
  http://web.archive.org/web/20200220141847/http://www.tab-funkenwerk.com:80/id139.html.
  It says the VF 14 was built 1946-1957 in three runs, about 27,500 pieces. Lore.

## The output transformer BV 8 (BV 08)

No Neumann winding specification was found. What exists, best first:

1. **The factory drawing (sch:).**
   - Ü1 "Bv. 8": the primary is two halves in series (rt - gn | gn - sw). The secondary is
     two windings (ws - ws, bl - bl).
   - S1 puts the secondaries in series for 200 Ω and in parallel for 50 Ω. The core is
     grounded. It is fed through C2 0.5 µF (parafeed: no DC in the primary).
2. **Haufe T-7853 data sheet** (a reproduction BV-08, Werkstätte für Studio-Technik
   Dipl.-Ing. Helmut Haufe, dated 26.09.2003).
   - Source: web: https://www.don-audio.com/bilder/HAUFE-BV-08_T-7853.jpg (linked from
     https://www.don-audio.com/Haufe-BV-08-BV8-microphone-audio-transformer; 91,643 bytes,
     sha256 `a2bbc382c7e6db609c15b9eb22c06ceae09c3df1f58035a0e95c6134f31a5b7b`),
     `haufe_t7853_bv08_datasheet.png`.
   - **Ratio 3.25 + 3.25 : 0.5 + 0.5** (6.5 : 1 with the secondaries in series, 13 : 1 in
     parallel).
   - Source 10 kΩ, load 200 Ω, primary level 20 dBu.
   - 20 Hz-20 kHz +-0.5 dB re 1 kHz; THD < 0.3 % at 40 Hz.
   - **Impedance 570 kΩ at 1 kHz, 1 V, rt - sw.** If purely inductive and unloaded, that
     is about 91 H (my arithmetic: 570 kΩ / 2π·1 kHz).
   - **Winding resistance 628 Ω : 17 Ω +-10 %.**
   - Test 0.5 kV AC; 40 x 35 x 22 mm; impregnated.
   - The diagram has the same colour codes as Neumann's (rt / gn / gn / sw primary,
     bl / bl, ws / ws secondary) plus electrostatic screens (br).
   - This is a reproduction, not an original.
3. **TAB-Funkenwerk / AMI (Oliver Archut), "BV08 Transformer"** (a vendor that rewinds and
   remakes BV 8s; "Neumann ... provided us with all documentation that they had left").
   - Source: web: http://web.archive.org/web/20200220141842/http://tab-funkenwerk.com:80/id146.html
     (original http://tab-funkenwerk.com/id146.html, gone).
   - Statements (vendor):
     - "40 to 20kHz +/-0.5 dB at 0dB (0.775V) at 2kOhm load";
     - **"a 6.5 to 1 ratio with 2600 to 400 turns"**, 200 Ω (50 Ω by a screw terminal);
     - a **four-chamber** bobbin (section winding, primary in four sections, secondary on
       top); "the two outer chambers have fewer turns than the inner two";
     - **block stacking** of the core ("a five and five lamination pattern"), which with
       the chambers rolls off below about 40 Hz;
     - radio-station units often have a 1/3 stack that cuts the lows up to about 120 Hz;
     - lamination **DIN UI 30** (side ratio 1 : 1.16, 30 / 35 mm), developed by NWDR
       Zentraltechnik with Krupp, retrofitted to the U 47 from about winter 1951-52 (an 8 : 1
       mantle-wound version first);
     - core a "Mu-Metal similar type of alloy" (Krupp, Vacuumschmelze); GN 8 / GN 8b export
       versions (Gotham, from about 1958), some on 49 % Ni-Fe with 4100 : 630 turns;
     - Neumann's manuals list 200 / 50, 50 / 12 and 600 / 200 Ω versions;
     - GN 8b has a built-in low cut from 100 Hz (from the same vendor's "U47 Rebuild",
       http://web.archive.org/web/20200219184722/http://tab-funkenwerk.com:80/id64.html);
     - inside a running U 47 it is 55-65 °C (same page).
   - The AMI product list (http://web.archive.org/web/20200219210832/http://tab-funkenwerk.com:80/id53.html)
     calls the lamination size "German DIN 30".
   - A photo of BV 8 / GN 8b labels "with the winding info right on the label" is on
     id146 (`bvgn.jpg`). The archive rate-limited the download: fetch it later.
4. **Forum figures (unverified):**
   - "Original BV08 is 6.5 to 1" (GroupDIY, web: https://groupdiy.com/goto/post?id=1108955);
   - an original BV08 "has 150H inductance", questioned in the same thread as possibly
     copied from AMI's site;
   - a builder's BV08-style part: each primary half 300 Ω, 600 Ω in series, 122 H in series;
   - Marik (a transformer maker): the BV 8 "lowish inductance" can give a resonant bass
     boost with the coupling capacitor; dual-bobbin "humbucking" connection as original
     (web: https://groupdiy.com/threads/transformers-for-u47-u67-m49-m50-and-other-microphones.57644/).
   - Clones: Sowter 1303 9 : 1, 220 H, 980 / 17 Ω (web: https://sowter.co.uk/specs/1303.php);
     Triad A-BV8 6.4 : 1, 700 / 17.6 Ω. Different parts, not data on the original.

Consistency check (my arithmetic): with 6.5 : 1 into the 1000 Ω load Neumann specifies for
the 200 Ω setting, the anode sees about 42 kΩ (AC) in parallel with R5's 100 kΩ.

## The capsule (M 7, K 47)

Published facts, with their sources:

- **Neumann's capsule overview (June 1999).** "Overview of microphones and capsules built
  by NEUMANN, Berlin", Georg Neumann GmbH, Berlin, June 1999, 8 pages.
  - Source: web: http://web.archive.org/web/20001027100756/http://www.neumann.com:80/document/files/capsules.pdf
    (the original http://www.neumann.com/document/files/capsules.pdf is gone; 39,109 bytes,
    sha256 `a79ddd9d971e33ab588edd8bf094d4fbb469f2f4149892138a0a1e8c36825c78`).
  - `neumann_capsule_overview_1999_p1.png`, `_p2.png`.
  - **U 47, 1949-1965:**
    - capsule **M 7**: pressure gradient (PG), membrane **PVC/G** (PVC, gold), 1932,
      O / C, one slide switch, VF 14, 105 V, "usable with CM 8 and CM 5 of CMV 3a";
    - later **K 49**: PG, **Pe/G** (polyester, gold), 1960, O / C, "polyester membrane,
      screwed".
  - U 47 N: Nuvistor 13CW4, 105 V, "successor for VF 14". U 47 P (1955): the M 48
    pressure capsule.
  - U 48 (1957-1965): "see M 7 and K 47/49". The U 47 fet: "see K 47". The M 147 Tube
    (1998-): "see K 47/49".
  - Neumann's own name for the M 7 is CM 8 (broadcast M 7, Telefunken ElaMZ 032/2, 1932,
    cardioid, for the CMV 3a).
  - So Neumann's list calls the U 47's polyester capsule "K 49" (1960) and the family
    "K 47/49". Forums and Neumann's web page say "K 47".
- **Construction (Neumann docu0067):** two equal diaphragms on both sides of a perforated
  center electrode "also provided with a number of cavities on both sides". Each half is a
  cardioid (above).
- **Material (Neumann):**
  - the U 47 began with the M 7, a dual-diaphragm capsule "developed back in the 1930s";
  - "Towards the End of the 1950s, the M7 capsule was replaced by the K 47 ... a
    re-engineered version using same capsule acoustics";
  - "the use of time-stable polyester diaphragms instead of the previously used PVC
    material"; "Sonically, both capsule variants are very similar";
  - (web: https://www.neumann.com/en/products/historical/u-47).
  - Peus (below): PVC was cast on glass plates from granules; it loses plasticizer, turns
    brittle and cracks the evaporated gold; polyester (PE, Mylar) films came in the 1950s.
- **Capacitance (sch:):** 2 x 78...83 pF (each half). The 1949 catalogue gives about
  100 pF for the CMV 3 capsules generally.
- **Polarization:** +63 V on the backplate (sch:, measured statically). Front diaphragm at
  0 V; rear at 0 V (omni) or floating (cardioid). The 1949 catalogue: about 1 mV/µbar at
  about 50 V polarization (CMV 3 capsules generally). A builder's article (below) cites
  60 V as recommended for M 7 / K 47, and 52.5 V for the U 48. Unverified.
- **Diameter:**
  - Peus (below): large-diaphragm studio capsules are "approximately 34 mm"; the U 87's
    K 67 / K 87 double-diaphragm capsule is 34 mm, its diaphragms 8 mm apart. That is
    **not** the K 47's figure.
  - Forum: M 7 32 mm outer diameter, K 47 33 mm (GroupDIY,
    https://groupdiy.com/threads/is-this-an-m7-or-k47-holder.77452); M 7 diameter without
    the middle rim 29.85 mm (GroupDIY, forum).
  - David Bock (a capsule maker, Tape Op #46, 2005, web:
    https://tapeop.com/tutorials/46/microphones-classic-condenser-capsules): the KK47 is
    "a 1" diameter membrane ... metalized (conductive) to a diameter of 0.9"", fixed at a
    center electrode, with "a relatively low resonant freq". He gives no other numbers.
- **Backplate holes:** "153 precisely hand-drilled and critically placed holes, some of
  which went through to the opposite side". Source: Science Museum Group, BBC Heritage
  Collection object 2012-5118/405, an M 7 (web:
  https://collection.sciencemuseumgroup.org.uk/objects/co8355881/neumann-m7-microphone-capsule).
  A museum label, not a drawing.
- **Diaphragm thickness (forum lore only):**
  - "original M7, as manufactured by Neumann (Berlin/Gefell), were diaphragmed with
    9-11µ PVC"; polyester diaphragms "average 6µ";
  - Klaus Heyne (a restorer, R/E/P forum): the ideal backplate for a 10 µ PVC diaphragm
    differs from one for 6 µ polyester; Neumann switched the K 47 / K 49 to polyester
    around 1960.
  - (R/E/P threads, e.g. https://repforums.prosoundweb.com/index.php/topic,33278.0.html;
    the forum blocks scripted fetches, so these come from search snippets.)
- **The principle's patent:** H. J. von Braunmühl and W. Weber, "Condenser microphone",
  US 2,179,361 (priority DE 4 April 1935, filed 30 March 1936, granted 7 Nov 1939), web:
  https://patents.google.com/patent/US2179361A/en, PDF
  https://patentimages.storage.googleapis.com/dd/eb/53/667df19b808297/US2179361.pdf
  (685,690 bytes, sha256 `4d4913b82564d1a7d9248e36bfeb18c02df22b18b7fe5f0de811b20a839f3e93`).
  - It gives the diameter as "preferably ... about 3 cm" (the limit set by the wavelength
    at 10 kHz) and the diaphragm resonance "in the middle range of frequencies".
  - No spacing, hole sizes or tension. German counterpart DE 705 827 (per Mix, web:
    https://www.mixonline.com/?p=78631, unverified).

**Not found anywhere published:** diaphragm thickness (from a primary source), tension or
resonance frequency, the diaphragm-to-backplate gap, backplate thickness, the hole pattern
(diameters, depths, which go through), the cavity volumes, the gold area. A3 needs these.

## Condenser-microphone theory (titles and what each gives)

- A. J. Zuckerwar, "Theoretical response of condenser microphones", J. Acoust. Soc. Am. 64
  (5), 1278-1285 (1978), doi:10.1121/1.382112 (NTRS record web:
  https://ntrs.nasa.gov/citations/19790041577):
  - frequency response and the equivalent lumped elements from geometry and materials
    (membrane, gap, backplate holes, back volume);
  - checked against B&K 4134 / 4146.
  - The A2 small omni's reference, and the per-element formulas for a K 47 model.
- A. J. Zuckerwar, "Principles of operation of condenser microphones", in G. S. K. Wong and
  T. F. W. Embleton (eds.), AIP Handbook of Condenser Microphones (AIP, 1995). The book
  version, with noise and the backplate's viscous terms.
- Z. Škvor, "On the acoustical resistance due to viscous losses in the air gap of
  electrostatic transducers", Acustica 19 (1967/68). The gap and hole resistance of
  perforated backplates. The citation is from memory, not checked online: confirm it.
- J. Esteves, L. Rufer, D. Ekeom, S. Basrour, "Lumped-parameters equivalent circuit for
  condenser microphones modeling", J. Acoust. Soc. Am. (October 2017),
  doi:10.1121/1.5006905 (PubMed 29092579; volume and pages to confirm). A general lumped circuit for several capsule configurations, validated
  on measured microphones.
- G. Torio and J. Segota (Shure), "Unique Directional Properties of Dual-Diaphragm
  Microphones", AES 109th Convention (Sept. 2000), preprint 5179 (AES e-library 9159; the
  AES Chicago section's summary, web: https://aes.org/sections/chicago/AES_LA_6_21_00.PDF).
  A lumped model of the dual-diaphragm (Braunmühl-Weber) cardioid against prototypes. The
  cardioid's working distance depends on the diaphragm compliance and the front-back delay
  relative to the cavity compliance. **The closest published model to the K 47.**
- R. S. Grinnip III, "Advanced Simulation of a Condenser Microphone Capsule", AES
  convention paper (AES e-library 12911; year to check). A BEM / FEM capsule model.
- S. Peus, "Modern Acoustic and Electronic Design of Studio Condenser Microphones", AES
  116th Convention, Berlin 2004, preprint 6131, web:
  https://assets.sennheiser.com/download/assets/lect0045_Peus_AES-2004_Modern-acoustic-and-electronic-design.PDF/a847da68dc0d11f0a0b34a591c6843d5
  (660,295 bytes, sha256 `4f53480c749a6ce1bec3865a5baaf98cb9747b130d1cf499067371db2a1ad5c9`).
  - The M 7 response (cardioid flat with a 3-4 dB presence boost; omni up to +6 dB at HF);
  - PVC vs polyester;
  - a 34 mm double-diaphragm capsule's transient (diaphragms 8 mm apart);
  - self-noise per generation.
- G. Boré and S. Peus, "Microphones: Methods of Operation and Type Examples" (Neumann, 1999),
  web: https://assets.sennheiser.com/download/assets/docu0002_BoreBuch_E-1999.PDF/5574009cdc0211f0887916ac7ce906bd
  (942,111 bytes, sha256 `751c758d8a546329db83848a883dfb50757f36d81a64aee60386098e97ba1385`).
  - Diaphragms 1-10 µm, gaps 5-50 µm;
  - gradient capsules have through-holes, pressure capsules blind holes; a cardioid mixes
    both, or makes the backplate an acoustic low-pass;
  - DC polarization: R >= 1 / (2π fu C0), C0 20-100 pF;
  - pattern switching by the second diaphragm's polarization (Fig. 19).
- H. F. Olson, Acoustical Engineering (Van Nostrand, 1957). The impedance-analogy networks
  for gradient and cardioid microphones.
- The Braunmühl-Weber patent above. H. J. von Braunmühl, W. Weber, "Kapazitive
  Richtmikrophone", Hochfrequenztechnik und Elektroakustik 46 (1935) is the usual citation
  (not found online; title and volume to confirm).
- A builder's article on the U 47 with an M 7 / K 47 and a BV 8 ("Journey into the legend
  of the U47", author not stated in the PDF, web:
  https://medias.audiofanzine.com/files/journey-into-the-legend-of-the-u47-477708.pdf,
  2,251,985 bytes, sha256 `d95b682354112b570b9aa6b9b6cba9a77f53fd4b0f5be9d9e17b596815ef940e`).
  - "original U47 (Ia = 0.5 mA, Va = 35 V, Vg = -1.1 V)";
  - polarization 60 V for M 7 / K 47, 52.5 V for the U 48;
  - the NG's output rises 15-20 V when the mains goes from 220 to 250 V.
  - A builder's statements, not data.

## The supply NG and the cable UC 4

- **Factory drawing "Schaltung f. Netzgerät U 47", S 03 Tz 2 (about 1953).** Radiomuseum
  schematic 3265452, web:
  https://www.radiomuseum.org/images/schematic-medium/neumann_georg/stromversorgung_netzgerat_ng_fur_3265452.png
  (500 px, sha256 `c7c0d2ddacb8745defd5bbfc1742380a9ca76e22cd9fcdc41aa4083abd266c34`),
  `ng_supply_drawing_thumbnail.png`.
  - Partly legible:
    - mains switch; neon lamp; 0.125 A fuse (220 V) / 0.3 A (110 V); the transformer's
      220 / 110 V strapping;
    - a bridge "Gl";
    - "5 x 40 µF";
    - "2 x 8 Hy" (choke) and 2 k and 1 k resistors in the filter;
    - output pins to the mic and the amplifier;
    - a handwritten note: cables up to 100 m, voltage drop 0.4 V.
  - Not legible: the transformer's secondary voltage, the exact topology (which rail the
    choke is in), the element positions. The full-resolution scan needs radiomuseum's free
    registration: **get it next.**
- **Radiomuseum's NG page** (above):
  - 100-105 V at 40 mA; rectifier "250B60 or B250C75";
  - the early version with mixed C-L-R filtering, pure RC filtering from about 1955;
  - 235 x 105 x 120 mm, 2.7 kg; cites Radio-Magazin 6/1950 p. 184 for the schematics;
  - page author A. Dassow.
- **Neumann's figures** (br:, ds58:, man58:, the conversion notice, all above):
  - 105 V / 40 mA loaded, about 300 V open-circuit;
  - 15 W loaded, 4 W unloaded; mains current 85 mA (220 V) / 160 mA (110 V);
  - hum about 5 µV at the mic output;
  - transformer, full-wave rectifier, reservoir capacitor, choke and four RC sections
    (early);
  - the 1966 filter: C1, R2 1 kΩ, C2, R3 1 kΩ, C3.
- **Rough check (my arithmetic, not data):** 300 V open-circuit falling to 105 V at 40 mA
  is about 4.9 kΩ of total source resistance (filter resistors, rectifier, windings).
  That is consistent with a few 1-2 kΩ sections.
- **UC 4:**
  - 10 m standard, up to 100 m (man59) / 300 ft (man58);
  - 4 individually shielded conductors (ds58, br); Tuchel T 3037 / T 3038.
  - **No per-metre capacitance or resistance found.**

## What A3 still needs

1. **The capsule's geometry.** Nothing primary was found:
   - diaphragm thickness and tension (or resonance);
   - the gap; backplate thickness;
   - the hole pattern (count, diameters, depths, through vs blind);
   - the cavity volumes; the metallized area.

   Options:
   - (a) ask Neumann's service for the K 47 / K 49's drawing or data (the 1999 overview
     lists the capsule under the U 47 fet and the M 147 Tube, so it stayed in
     production);
   - (b) a restorer's or capsule maker's drawing (Thiersch, Neumann service, Microtech
     Gefell, who made M 7s);
   - (c) make them bounded provisional genome parameters, fitted to Neumann's measured
     1952 curves and the 1958 data sheet. The 1959 drawing's 78-83 pF per half and the
     sensitivities (2.5-2.8 mV/µbar cardioid, 1.4-1.7 omni, at 63 V and 1 kΩ) constrain
     the gap-to-area ratio and the compliance.
2. **Full-resolution factory scans from radiomuseum** (free registration):
   - the NG drawing S 03 Tz 2;
   - the early U 47 drawing S 03 Tz 3;
   - the 1952 response and polars (3265455);
   - the Radio-Magazin 6/1950 article (pages 184 ff., "Neue Kondensatormikrofone für
     höchste Ansprüche"; thumbnail
     https://www.radiomuseum.org/images/schematic-medium/neumann_georg/kondensatormikrofon_u47_1633605.png),
     which may describe the capsule.
3. **BV 8 measurements on an original:**
   - leakage inductance, winding capacitances;
   - primary inductance vs level (and its test frequency);
   - the core's B-H data (or take the project's mumetall with the UI 30 stack and block
     stacking).

   The Haufe reproduction's 628 / 17 Ω and about 91 H are the best numbers so far. The
   label photo on TAB's id146 page may give turn counts.
4. **The VF 14 at low current:** curves near 0.5 mA, and the grid current at -1.1 V.
   Fitting Funkschau's curves anchored on the drawing's static point is the plan.
5. **The NG's transformer** (secondary voltage, winding resistance), capacitor values,
   which version (LC or RC), and the cable's capacitance and resistance per metre.
6. **The cardioid position's rear diaphragm** (floating per the 1959 drawing; check).
7. Digitize Neumann's response and polar plots (1952 thumbnail at full resolution, 1958
   data sheet) as A3's targets. Stated tolerances:
   - 1949: 30 Hz +-2 dB, 15 kHz +-3 dB;
   - 1952 (Telefunken): 30 Hz +-1 dB, 15 kHz +-3 dB.

## Where to look next

- Radiomuseum (free account): the schematics above at full resolution, and the U 47 model
  page web: https://radiomuseum.org/r/neumann_u47_u_47.html (its notes say the capsule is
  the M 7).
- Neumann's download API (above) for more documents: try `searchQuery` "NG", "Netzgerät"
  (only noise so far), "K 47", "U 47 fet" (the K 47 reissue's data).
- The archived Neumann list `ku_liste.pdf`, web:
  http://web.archive.org/web/20001006110035/http://www.neumann.com:80/document/files/ku_liste.pdf
  (and `kapseln.pdf`, the German capsule overview). Not downloaded: the archive
  rate-limited this machine. `capsules.pdf` is above.
- TAB's BV 8 / GN 8b label photo (`bvgn.jpg` on the archived id146 page), for turn counts.
- worldradiohistory.com's Funkschau (1947-1960) and Funk-Technik for U 47 / M 7 articles.
  The Telefunken-Röhrentaschenbuch 1955 for the VF 14's page.

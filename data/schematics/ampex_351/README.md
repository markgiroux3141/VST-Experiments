# Ampex 350 / 351 tape recorder sources

Gathered 2026-10-31 for a physics-based tape machine (electronics, heads, transport). All
files were retrieved on **2026-10-31** with curl. "p N" is the **PDF page index** (what a
PDF viewer shows, and the Read tool's `pages`), and "(2-3)" is the page number printed on
the page. The facts below were checked against the page images, not only the OCR text.
Recheck each value against the drawing before it goes into a circuit file.

The PDFs are large (about 152 MB in all). The repo's other schematic folders commit PNG
extracts and leave the source scans uncommitted. These PDFs aren't committed or git-ignored
yet: decide which before the next commit.

## Files

| File | What it is | Source URL | Revision | Pages |
|---|---|---|---|---|
| `Ampex351.pdf` | **Ampex 351 / 351-2 instruction manual**, TM-2002A, 89-0144 Issue A, **May 1962** (OCR text layer, clean) | web: https://bh.hallikainen.org/uploads/harold/Ampex351.pdf (listed on https://bh.hallikainen.org/index.php/Ampex) | Electronics **cat. 02-30960** (notes on the differences from 30750 / 30950) | 103 |
| `Ampex-351-Manual-1959.pdf` | **Ampex 351 manual**, TM 2002, **October 1959** (response curves dated 28 Sept 1959) | web: https://www.worldradiohistory.com/Archive-Catalogs/Ampex/Ampex-351-Manual-1959.pdf | **Three electronics schematics**: 30960-01..-04 (drawing 30961 E), 30750-01..-08 (drawing 30802 L), 30950 (drawing 30925 D), with a parts list for each | 88 |
| `Ampex350.pdf` | **Ampex 350 (350C) operation and maintenance manual**, pages dated 6/1/53 to 4/11/56 (image scan, OCR unusable) | web: https://bh.hallikainen.org/uploads/harold/Ampex350.pdf | Electronic assembly **cat. 5701R3** (drawing ED-5701R3, 9-20-54); octal tubes | 79 |
| `Ampex354_TM-2011B.pdf` | **Ampex 354** (two-channel, compact) manual, TM-2011B, 89-0131 Issue A, copyright 1960. The original file name was `20140710132548.pdf` (renamed here) | web: https://bh.hallikainen.org/uploads/harold/20140710132548.pdf | 354 electronic assembly, schematic sheets 1-2 | 115 |
| `350heads.pdf` | Minneapolis Magnetics "Picstallation Notes": replacing the heads on Ampex 300 / 350 / 400 / 450 / 3100, with alignment hints | web: https://bh.hallikainen.org/uploads/harold/350heads.pdf | undated (1960s-70s) | 6 |
| `AE-4908-Stolaroff-Ampex_300.pdf` | M. J. Stolaroff, "Low-Cost Precision Magnetic Recorder for Professional Use", *Audio Engineering*, Aug 1949 (the Ampex 300) | web: https://bh.hallikainen.org/uploads/HaroldHallikainen/AE-4908-Stolaroff-Ampex_300.pdf | article | 4 |
| `350-2_setup_instructions_rev1_1.pdf` | D. Dintenfass (Full-Track Productions), "Introduction to the Ampex 350-2, Rev 1.11", plus noise-balance removal bulletins for the 300 / 350 / 400 (redistribution allowed only unaltered and in full) | web: https://fulltrackproductions.com/service%20bulletins/350-2%20setup%20instructions%20rev%201_1.pdf | 2005-2020 | 20 |
| `AmpexAg600b.pdf` | Ampex AG-600B operation and maintenance manual, Sept 1971. **Solid-state** (not a tube machine); kept only for comparison | web: https://bh.hallikainen.org/uploads/harold/AmpexAg600b.pdf | 4890302-01 | 88 |

sha256 (first 16 hex digits): Ampex351 `9f4dd38b80ee32c1`, Ampex-351-Manual-1959
`f4963f4573a316cf`, Ampex350 `ad16bad720fbeaea`, Ampex354_TM-2011B `f53db5d04589f7c0`,
350heads `b9542f3b455c702b`, AE-4908 `4669d21f95f3a85b`, 350-2 setup `ca1a184f8e7215c3`,
AmpexAg600b `8295574e0b7af34f`.

## Ampex 351, from `Ampex351.pdf` (1962, electronics 30960)

### Electronics schematic: p 95 (8-23/8-24), "Electronic Assembly Schematic Diagram"

A 300 dpi JBIG2 line layer: render it with `pdftoppm -r 300` and every value is legible.
It prints DC voltages (circled; 20 kOhm/V meter, record mode, 117 V line, oscillator tube
removed, 1 kOhm in place of the record head) and signal voltages (boxed; dB re 0.78 V,
500 Hz in, 7-1/2 ips EQ, level controls full up, 600 ohm load). Its equalization tables are
"Table 1 NAB" (C46, C7, C8, R29, R30, C15, R18 for the 3-3/4/7-1/2 and 7-1/2/15 boards) and
"Table 2 CCIR". The response curves (record / reproduce, 3-3/4 120 us, 7-1/2 NAB, 15 NAB)
are on p 94 (8-21/8-22). The parts list is on p 88-93 (8-15..8-20).

**Tubes per stage** (schematic p 95; parts list p 93 (8-20); text p 76-78 (8-3..8-5)):

| Ref | Type | Stage |
|---|---|---|
| 1V1 | 12AX7 / ECC83 | record amp 1st stage (mic / balanced-bridge input, after input transformer 6T1) and 2nd stage (after RECORD LEVEL 4R9). Unbalanced bridge bypasses 6T1 and the 1st stage |
| 1V2 | 6201 (premium 12AT7) | record amp 3rd stage (pre-emphasis: 1C46 LOW / 1C7 HIGH trimmers, 1R17; LF +3 dB from 1R18 / 1C8) and 4th stage, the "constant current" head driver (1R19 22 k 1 W plate load, 1R21 220 / 1R22 2200 unbypassed cathode; CCIR adds 1L1 20 mH + 1C11). It feeds the head through 1C10 0.47 uF; bias joins it through 5C13 BIAS ADJUST 15-130 pF (and 5C39 33 pF) |
| 2V3 | 12AX7 / ECC83 | reproduce 1st stage (2R25 330 k head load; EQ 2C15, 2R29-2R31; 2R31 HIGH / 2R30 LOW variable) and 2nd stage |
| 2V4 | 12AX7 / ECC83 | 2V4a amp after PLAYBACK LEVEL 4R36, 2V4b phase inverter |
| 2V5 | 12AU7 | push-pull output into 6T3 (common cathode 2R46 1 k; plates 295 V; a feedback winding goes to 2V4a's cathode and the MONITOR jack) |
| 1V6 | 12AU7 | bias / erase oscillator, push-pull cross-coupled (1C35 / 1C32 350 pF, 1R61 / 1R62 4.7 k, NOISE BALANCE 1R63 10 k), bias transformer 1T5; ERASE ADJUST 5C33 100-550 pF |
| 3V7 | 6X4 | full-wave HV rectifier |
| 6CR1 | selenium bridge | 12.6 V DC heaters for 1V1, 1V2 and 2V3 (3C28 4000 uF 15 V); 2V4 and 2V5 run on 12.6 V AC |

- **Bias / erase frequency: "approximately 100 kc"** (p 78 (8-5); also p 38, Section 5 page 9: "the
  bias frequency is normally 100 kc"). B+ to the oscillator and the record 4th stage comes
  only in record mode (relay 3K1C).
- **Supply** (schematic p 95): 6T4 HV winding into the 6X4, about **330 V** at the
  rectifier's filter input, **300 V** after 3R54 / 3R55, through RC filters (3C16 a-d
  15 / 15 / 20 / 75 uF) down to 250 / 220 / 215 / 190 V for the earlier stages. 3K1B shorts
  3R54 in record "to provide a nearly constant B+" (p 78). Line 117 V AC, 2.0 A (single /
  half track) or 2.5 A (two track) (p 11 (2-3)).
- **Selected DC voltages** (p 95): 1V1b plate 170 V, cathode 1.4 V; 1V1a plate 170 V,
  cathode 1.6 V; 1V2b plate 75 V, cathode 26 V; 1V2a plate 150 V, cathode 6 V, B+ 275 V;
  2V3b plate 100 V, cathode 1 V; 2V4a plate 110 V, cathode 1 V; 2V4b plate 90 V, cathode
  0.6 V; 2V5 plates 295 V, cathodes 13 V; oscillator plates 300 V. Signal: record head
  "-12 dB to A".
- **Metering:** a 4 in VU meter, **0 VU = +8 dBm (+-1 dB)**, strappable to +4; the line
  output delivers +14 VU into 600 ohm (p 11 (2-3)). The meter reads bias (across 5R24 BIAS
  CALIBRATION, 1 k) and erase current via METER AND OUTPUT switch 4S3 (p 75-78).
- **Inputs:** mic 150 / 250 ohm (strappable 30-50 ohm), 200 uV for operating level; bridge
  200 k / 100 k, -10 dBm (p 11 (2-3)).

### Performance and transport (p 10-11 (2-2..2-3), p 51-52 (6-3..6-4), p 35 (5-6))

- Speed pairs 3-3/4 / 7-1/2 or 7-1/2 / 15 ips, 1/4 in tape, full track, half track or
  two-track stereo (351-2). CCIR EQ on request.
- Response: 3-3/4 ips +-2 dB 50-7,500 Hz; 7-1/2 ips +-2 dB 40-10,000 and +-4 dB 30-15,000;
  15 ips +-2 dB 30-15,000.
- S/N (peak record level = 3% THD at 400 Hz, to unweighted noise, 50-15,000 Hz, bias,
  erase and amplifier noise included): 3-3/4 ips 50 dB; 7-1/2 ips 60 dB full track, 55 dB
  half / two track; 15 ips the same as 7-1/2.
- Flutter and wow (0.5-250 Hz, ASA Z57.1-1954): 0.18% / 0.14% / 0.11% rms at
  3-3/4 / 7-1/2 / 15 ips.
- Start < 0.1 s; stops within 2 in at 15 ips; timing accuracy +-0.2%.
- Capstan: "hysteresis synchronous capstan drive motor (B501)" whose extended shaft is the
  capstan, two windings for the two speeds; induction torque reel motors B502 / B503; a
  rubber capstan idler (p 51-52). The 1959 manual's parts list (p 43) has Bodine or
  Ashland motors, 31210-01..-04 per speed pair and mains frequency. **The capstan diameter
  isn't printed.**

### Heads (p 69-72 (7-1..7-4); Section 5 p 41-42, printed 12-13)

- Three heads, left to right: erase, record, playback. "In typical playback heads the gap
  is **.00025 inch**" (6.35 um) (p 70 (7-2)). Head assemblies: 351 full track 02-0475-18,
  half track 02-0475-17, 351-2 two-track 02-30028-02 (p 72 (7-4)).
- **Track widths** (p 41, the head configuration figure, in mils): full track **234**;
  half track **82** (70 to the unused lower half); two-track stereo **75 + 84 guard + 75**
  (= 234; the text says an 85 mil spacing); three track 100 / 85 on 1/2 in.
- Spacing loss "54.6 dB per wavelength separation" (p 42).
- The record and playback heads' inductance, the record head's bias current, the
  record-to-playback gap distance and the record gap length **are not printed**.
- From `350heads.pdf` p 4: the head stack height is "a nominal .273 in" on 0.250 in tape.

### Equalization (p 12-14 (2-4..2-6); p 39, Section 5 page 10)

- 15 ips NAB: 6 dB/oct with **3180 us** low-end and **50 us** high-end time constants
  ("50 microsecond time constant, which places the +3 db point at 3,180 cycles", p 39).
- 7-1/2 ips "NAB": the same as the 15 ips NAB curve (industry practice, no NAB standard).
- 3-3/4 ips: 3180 us + **120 us** (was 200 us before the cartridge).
- 15 ips AME (Ampex Master Equalization): more record level in 2-6 kHz, about 8 dB more
  apparent S/N; for in-house mastering only.
- CCIR: 7-1/2 ips **100 us**, 15 ips **35 us**, no low-end time constant.

### Alignment (p 79-85 (8-6..8-12))

- Test tapes: Ampex standard alignment tapes 31331-01 (3-3/4), 31321-01 (7-1/2), 31311-01
  (15 NAB), 31312-01 (15 AME). The first tone is the reference level: 700 Hz at 7-1/2 / 15,
  500 Hz at 3-3/4. Then the azimuth tone (15 kHz; 7.5 kHz at 3-3/4), then a sweep from
  15 kHz to 30 Hz. On the 15 ips tape all tones are at operating level; on the slower
  tapes a later tone at operating level sets PLAYBACK LEVEL to 0 VU = **+8 dBm (1.95 V)**.
- Playback EQ: adjust 2R31 (7-1/2 / 15) or 2R30 (3-3/4) for flattest HF; "not moved more
  than 2 db from the standard curve". Full-width test tapes read high at LF on narrower
  tracks (fringing): don't correct for it.
- Erase: ERASE ADJUST for +1 VU (full track) or -1/2 VU (half track and stereo) on the
  ERASE meter position at 117 V.
- **Bias** (with the tape that will be used): 7-1/2 ips, **500 Hz** (1000 Hz to set it at
  15 ips: "bias is set at a specific wavelength"), about 1 V in. Peak the output with BIAS
  ADJUST, go clockwise until the output drops 1/2 dB and read the BIAS meter, go
  counterclockwise until it drops 1/2 dB and read it again, and set the bias at the median
  of the two readings (that is, at the peak). Then BIAS CALIBRATION 5R24 for 0 VU on the
  BIAS position.
- Record level calibration (500 Hz, 0 VU in playback, then RECORD CALIBRATE for 0 VU on
  RECORD LEVEL), record azimuth (15 kHz at about -20 VU), record EQ trimmers 1C46 / 1C7.
  Response checks at -10 dB (15 ips, -2 dBm) or -20 dB (slower speeds, -12 dBm) below
  operating level. Noise balance: by ear for minimum noise.
- **Operating level** is defined by distortion, not flux: "the VU meter reads zero level
  when reproducing a steady 400 cycle tone the level of which produces 1% total rms
  distortion"; the 3% level is 6 dB higher (p 84 (8-11)). **No fluxivity (nWb/m) is
  printed.** The 350's 1953 alignment tapes (#5563, #4494) "are recorded at 10 db below
  Operating Level" (`Ampex350.pdf` p 40 (5-3)). Dintenfass's 2020 notes say 0 VU at the
  "standard reference fluxivity (normally 250 nW/m)" (`350-2_setup...pdf` p 5), a modern
  practice, not Ampex's.

## Earlier and related revisions

- **`Ampex-351-Manual-1959.pdf`**: the record amp's 1V2 is a **12AT7** (the 1962 issue has
  a 6201). There are three schematics: p 85, 30960-01..-04 (drawing 30961 E, "1 of 2");
  p 86, 30750-01..-08 (30802 L), with an optional low-impedance playback head input
  transformer 5T-2 and an LC record peaking network (1L1 20 mH, 1C11 / 1C12) instead of
  1C46 / 1C7; p 87, 30950 (30925 D). Fixed playback EQ on 30750 / 30950. Each has
  per-speed EQ tables. Parts lists: p 74 (30960) and p 82 (30750). Record / reproduce
  response curves for 30960: p 83. Bias "approximately 100 kc" (p 57). Board layouts: p 84.
- **`Ampex350.pdf`** (350, electronics 5701R3, schematic p 61 "Fig. 1", drawing
  ED-5701R3 9-20-54; the 3-3/4 / 7-1/2 version p 62; transport control p 63 and p 78-79;
  power supply p 64; EQ curves p 66-67). Text p 38-39 (5-1..5-2): the record amp is a
  12SJ7 pentode preamp (V401), two triode-connected 12SJ7s (V402, V403) and a
  constant-current **6C5/6J5** output (V404). The playback amp is three stages: **12SJ7
  (V405, "select"), 12SJ7 (V406), 6F6 (V407, single-ended output)**, with RC playback EQ
  in V405's feedback loop (R435, C417). The oscillator is **6SN7** (V408), push-pull,
  "a 100 KC signal". The supply is a separate chassis: a **5Y3G** full-wave rectifier, a
  selenium bridge for 12.6 V DC heaters, and 6.3 V AC. The schematic shows about +385 V
  at the oscillator and +310 / +320 V on the output stage; 0 VU = +4 VU line out.
  Specs p 7-8 (1-1..1-2): the same response figures as the 351; S/N 60 dB peak (full
  track, 7-1/2 and 15); flutter 0.3 / 0.25 / 0.2% (0-300 Hz, peak-reading).
- **`Ampex354_TM-2011B.pdf`**: a different, two-channel design. Tubes from the heater
  string on schematic p 102 (8-29/8-30): 1V1 and 1V2 **6AW8A**, 1V3 and 1V5 **12AX7**,
  1V4 and 1V6 **6DJ8**, oscillator 1V7 **12BH7A**, silicon rectifiers (1N607). It has the
  same theory chapter as the 351. Response curves: p 101 (sheet 2: 15 AME, 7-1/2 and 15 CCIR) and the page before it.
- `AE-4908-Stolaroff-Ampex_300.pdf`: the Ampex 300 (1949): 15 / 7.5 ips, a dual-speed
  synchronous capstan motor, 6SN7-type dual tubes, playback +25 dBm at 1% THD,
  +-2 dB 50-15,000 Hz at 15 ips, S/N > 60 dB, flutter < 0.1% at 15 ips (p 2-3). No
  schematic.

## Head spacing and the Sun Records slapback (not printed by Ampex)

The record-to-playback gap distance is **not printed** in any of these manuals. Secondary
figures (unverified; measure a real head block before relying on one):

- About **2.0 in** (implied): Waves "MPX Master Tape" (modelled on "an Ampex 350 transport
  and 351 electronics") gives **266 ms at 7.5 ips, 133 ms at 15 ips**; web:
  https://www.prosoundweb.com/waves-audio-introduces-mpx-master-tape-plug-in/ (1 June 2011).
  266 ms x 7.5 ips = 2.0 in.
- **2.0625 in** and "2.1 in" ("0.14 s at 15 ips"): forum posts on TDPRI, "How many ms
  delay do you use for slap-back echo?", page 2; web:
  https://www.tdpri.com/threads/how-many-ms-delay-do-you-use-for-slap-back-echo.188584/page-2
  (seen only in a search snippet; the page sits behind a bot paywall). 2.0625 in gives
  137.5 ms at 15 ips and 275 ms at 7.5 ips.
- Sun: "a couple of Ampex 350 recorders, one a console model and the other rack mounted",
  the rack unit used mainly for the slapback; Sun recorded "at 7 1/2 ips ... due to the
  high cost of tape" (said of the earlier Presto 900P period); web:
  https://scottymoore.net/studio_sun.html (James V. Roy, citing M. Cunningham, *Good
  Vibrations*). Wikipedia, "Delay (audio effect)": "Sam Phillips created a slapback echo
  effect with two Ampex 350 tape recorders in 1954", citing *Sound on Sound* ("Sam
  Phillips: Sun Records"), *Popular Mechanics* (Blitz, 2016) and Grove (Bowman); web:
  https://en.wikipedia.org/wiki/Delay_(audio_effect).
- No primary source found gives Sun's slapback speed: 7.5 ips (about 270 ms) or 15 ips
  (about 135 ms) are both claimed.

## Not printed anywhere here (gaps)

Record-to-playback gap distance; capstan diameter and motor rpm; head inductances and DC
resistances; record gap length; erase head gap; record bias current in mA (only meter
readings); exact bias frequency (only "approximately 100 kc"); reference fluxivity of the
Ampex test tapes (only "operating level" = 1% THD at 400 Hz, and the 1953 tapes at
"-10 dB"); transformer data (6T1 input, 6T3 output, 1T5 bias, 6T4 power: part numbers
only); tape formulation used for the specs.

## Other tube machines (links, not downloaded)

- Studer J37 operating and service instructions (20.6 MB): web:
  https://www.worldradiohistory.com/Archive-Catalogs/Studer/Studer-J37-Op-Serv.pdf
- Studer C37 operating and service instructions (28.7 MB): web:
  https://worldradiohistory.com/Archive-Catalogs/Studer/Studer-C37-Op-Serv.pdf; early
  edition (19.2 MB): web:
  https://www.reeltoreel.nl/studer/Public/Products/Recording_Analog/C37/Manuals/C37_early_OpServ.pdf
- Magnecord PT6-6 service manual (3.6 MB): web:
  https://bh.hallikainen.org/uploads/MagnecordPT6-6service.pdf
- Echoplex EP-2: schematics by serial range exist only behind elektrotanya's download gate
  (e.g. web: https://elektrotanya.com/echoplex_ep2_2750-5499_sch.pdf/download.html);
  owner's instructions at web:
  https://soundgas.com/resources/market-electronics-maestro-echoplex-ep-2-instructions
- Ampex 300: Sel-Sync and 300-2 slave schematics listed at web:
  https://www.historyofrecording.com/Schematics.html; a service manual section behind
  elektrotanya's download gate.
- The Ampex legacy manual archive (http://www.ampexdata.com/Support/Legacy_Manuals/legacy_manuals.html)
  returned 404 on 2026-10-31.

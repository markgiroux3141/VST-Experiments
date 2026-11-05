# Universal Audio 610 sources

The chains build-out's WP2 (docs/CHAINS_PLAN.md), found 2026-11-05. Values in
`config/circuits/ua_610.yaml` cite these as `sch:` (printed on the drawing below, by
reference designator), `utc:` (UTC's catalog and terminal sheet), `clone:` (a builder's
measured voltages) or `web:`. The model is the microphone preamplifier of Bill Putnam's
610 console (1960, United Recording, 6050 Sunset; modular, a mic pre with gain, echo send
and EQ per chassis), not the reissues (2-610, SOLO/610, LA-610, 6176), which differ in the
input transformer, the output stage, the EQ and the supply (Brian Roth, quoted by Hinson,
GroupDIY thread 7707 p. 4).

The GroupDIY attachments are behind the forum's login: the user downloaded them on
2026-11-05. The site worldradiohistory.com refuses scripted downloads; the user fetched
its file too.

## The drawing

John Hinson ("Winston O'Boogie" on GroupDIY; he did the reverse engineering for the new
UA) redrew UA drawing **C-10068**, "Modular Amplifier Model 610-A", from two original
1960s modules (one from Neil Young's desk, one of Bill Putnam's; GroupDIY threads 47543,
72736). Two copies, the same drawing (vector PDFs, one page; the second marks the gain
link "(Internal Link)"):

- `610-A UA 610 Preamp Schematic.pdf` (sha256
  `4717d439a536f12f41b6f7a001f12bef09e6f8eceb6bf04e7a308ab9b0d7b142`): web:
  https://groupdiy.com/attachments/610-a-ua-610-preamp-schematic-pdf.68356/ (thread "UA 610
  Microphone Preamplifier Help thread", 72736). **The drawing the circuit file models.**
- `ua_610_micpre.pdf` (sha256
  `96f5551e485879c0747f4c7b8e6bc5fa92403ce09c645f19d9c0cc685a9134b0`): web:
  https://groupdiy.com/attachments/ua_610_micpre-pdf.11664/ (thread "UA 2-610
  Troubleshooting", 47543).
- `610inputstagevariation.png` (sha256
  `5f9de7bfaf4228bc2cfe6ae23824a6a42968aacc6fa0629eb049cedd989781a6`): web:
  https://groupdiy.com/attachments/610inputstagevariation-png.11666/ (thread 47543):
  Hinson's "Alternative 610 Input scheme" from an earlier module: R27 2K2 (not 4K7), no
  C8, no C15, 100K between V1's cathodes, R25 270K across C13. Not modelled.

### What C-10068 shows

Traced from the PDF's vector paths on 2026-11-05 (wires join at endpoints and T's, not
at crossings). The drawing prints **no operating voltages** and no tolerances; it shows
neither the amphenol wiring nor the console's bus switching (its note).

- **Input:** S1 selects LINE (a 15K / 27R / 27R / 15K pad, R1-R4, centre grounded) or
  MIC: Mic In + through R5 47R to T1 (UTC O-1) pin 4, Mic In - to pin 3; pins 1, 2, 5
  unused. Secondary 7 to V1-A's grid with R26 1M2, 6 to ground.
- **V1 (12AX7):** V1-A cathode R27 4K7 1W (unbypassed), plate R6 270K 1W from C1-B's
  rail; C3 .047 to V1-B's grid (R28 1M2); V1-B cathode R10 1K 1W with C8 .002 across it,
  plate R8 100K 1W from C1-A's rail; C4 .047 out. Feedback R11 68K + R9 39K from C4's
  output to V1-A's cathode. The Lo / Hi gain link (internal) takes C14 (.2uF 200V) from
  the R11 / R9 tap (Lo) or from C4's output (Hi).
- **LF switch S3** (two decks): the lower deck passes C14 straight to the LEVEL pot R13
  250K at 0 and +6, through R25 270K || C13 .0047 at -6; the upper deck shorts R21 || C9
  (V2-A's cathode to R21 / R22's junction) at -6 and 0.
- **V2 (12AY7):** V2-A grid on R13's wiper, cathode R15 4K7, plate R14 470K from C2-B's
  rail; C5 .047 to V2-B's grid (R16 1M2); V2-B cathode R18 560R (unbypassed), plate on
  T2 (UTC PA-5946, "30K ohm", "600 ohm", "L = 55HY Min.", a tertiary "not used on 610";
  primary centre tap unused) from B+. The echo send C7 .047, R19 82K, R20 10K pot, R33
  10K to Echo Out.
- **Feedback and HF switch S2:** C6 .047 from V2-B's plate, R22 220K, R21 270K || C9
  .0047 to V2-A's cathode; from C6's end a ladder R23 100K, C10 100pF, C12 47pF, C16 .01,
  C11 .01 || C17 .002, R24 2K2 to ground; S2 puts C10 / C12's junction (-6), C12 / C16's
  (+3) or C16 / C11's (+6) on V2-A's cathode, nothing at 0. C15 82 pF between V1-B's
  and V2-A's cathodes (doubted on GroupDIY, 47543; drawn on both copies).
- **Supply:** B+ (from the console) at C10 10uF/400V (the drawing names two parts C10),
  R17 10K to C2-B's rail, R12 10K to C1-A's, R7 82K to C1-B's (10 uF each).

## UTC's data on the transformers

- `UTC O Series.pdf` (sha256
  `56d8aa53cb8edab85e293ec772397c9c1120607cc9dd068e9dd3795a482b7f2e`): web:
  https://groupdiy.com/attachments/utc-o-series-pdf.86955/ (thread "UA 1108 transformers",
  79165, mjrippe: "The 610 did use the O-1"). UTC's "Ouncer Audio Units" catalog page: O-1
  "Low imp. to grid", primary 50, 200/250, 500/600 ohm, secondary 50,000 ohm, +-1 dB
  30-20,000 Hz, maximum level +8 dBm (6.3 mW), primary resistance 52 ohm; the Ouncer case
  7/8 in dia x 1-3/16 in high, 1 oz.
- `UTC-Terminal-Arrangements-1952.pdf` (sha256
  `05840ebd21c4c2ec12020e0c576b64d61b5599827654cf571c1dca473e6f0e65`): web:
  https://www.worldradiohistory.com/Archive-Catalogs/Miscellaneous-Manufacturers/UTC-Terminal-Arrangements-1952.pdf.
  Page 5 lists the O-1 as primary combination 9, secondary 29, schematic AC; page 4,
  "Terminal connections, type 'O' transformers", input combinations for the O-1: "500
  ohms connect to 1 and 5 (3 is center tap). 200 ohms connect to 2 and 4 (3 is center
  tap). 50 ohms connect to 3 and 4"; output: "Connect grid to 7; grid return to 6". So
  **the 610 runs the mic into the O-1's 50 ohm tap** (a 1:31.6 step-up).
- PA-5946: no UTC data found. The drawing's "30K ohm / 600 ohm / L = 55HY Min."; "30k ct :
  600R", a tertiary, "Modified basic 1008 transformer", used in the 1008, the 610 and
  others (jhaible quoting a UA manual, thread 2999); "50:1 impedance / 7:1 turns" (Jean
  Clochet, 47543); made by Electro-Engineering Works, whose successor Magnetica no longer
  has the winding data; "get a gapped 7:1 and you will be very close to the original",
  "the core gets about 4 k gauss at 20 hz" (CJ, thread 37944); a reproduction wound 2 x
  3500 turns primary, 826 ohm, 98-105 H, secondary 118 ohm (Spencerleehorton, 37944).

## A clone's measured voltages

- `610 - Final Voltage.png` (sha256
  `b93c901ecd7f88679d3c1aa213b1bd341d588a1da77d9eeb752f88557ef90cbe`): web:
  https://groupdiy.com/attachments/610-final-voltage-png.69783/ (thread "UA 610 Preamp -
  Transformer Substitute", 73280, page 2): the drawing annotated with a clone's readings
  (its own transformers: a UTC A25 output, thread 73280). B+ 298, rails 277 / 260 / 221;
  V1-A plate 101, cathode 0.98; V1-B 156 / 1.13; V2-A 89 / 1.9; V2-B 287 / 3.4 V. V1-A's
  pair disagrees with itself (0.21 mA in R27, 0.44 mA in R6, 0.48 mA in R7): the idle test
  leaves it out.
- `610 - Nate Voltages #2.png` (sha256
  `7c5b42af314994ca745d010eef06da3e55e8480e25ac7b41e01b70640e13cffa`): web:
  https://groupdiy.com/attachments/610-nate-voltages-2-png.69751/: an earlier state of the
  same clone, B+ 347 / 305 V with LEVEL at either end (the DC moving with the pot: a fault
  being chased in the thread). Not used.

## What the forum pages say (thread text, no login)

- B+: "around the 275V range on the original desk", "the operating points don't really
  change much from 250 to 300V" (Hinson, thread 72736 #6); ~300 V (Hinson via mitsos,
  58564); 270 V loaded in another clone (mrclunk, 13038 p. 3).
- Gain: "a bit north of 60dB" with a clone's transformer set (Hinson, 72736 #6); Hi / Lo
  "about 9 dB" (Jean Clochet, 47543); the link is "an internal link, NOT a switch" (same).
- V2-B's plate current ~7 mA on the schematic, ~5 mA per Hinson (47543), ~6.5 mA measured
  in a clone (73280).
- Heaters 6 V on the old 610 and the 2-610 (12 V on the 6176: Brian Roth via Hinson,
  7707 p. 4).
- A public copy of the drawing, http://www.revolutionrecording.com/images/610A-Schematic.pdf
  (thread 7707 p. 4), is gone (404; the Internet Archive holds only 404s). Hairball's
  "Lola" is a JH-990 op-amp design, not a 610.

## The 2-610's published specifications (UA's manual)

"2-610 Dual Channel Tube Preamplifier" manual, Universal Audio, 15 pages; web:
https://cf3.zzounds.com/media/2-610-manual-4274585670d809dcc49c7026bda3c532.pdf
(downloaded 2026-11-05; sha256
`24929be46ffe613eb1a7c3b41599ad81bce6d52b31cb110eec8ffae6a6ebf889`, not committed; UA's
own copy is linked from https://help.uaudio.com/hc/en-us/articles/206356253).
`ua_2610_manual_p6.png` (specifications), `ua_2610_manual_p8.png` (input select, gain,
level) at 110 dpi.

Mic input 500 or 2 k selectable; line input 13.8 k; Hi-Z 2.2 M or 47 k; maximum mic
input +3.5 dBu; maximum output +20 dBm; internal output impedance 60 ohm; recommended
minimum load 600 ohm; response 20 Hz-20 kHz +1 dB; maximum gain 61 dB; S/N > 82 dB; the
Gain switch in 5 dB steps by the input stage's feedback; LEVEL not in dB. Its tube
complement reads "one 12AX7 and one 12AT7 per channel", against 12AX7 + 12AY7 / 6072
everywhere else (the SOLO/610's listings, the drawing). The reissue's specs are no
measurement of the original's: the profile reports them as a reference only.

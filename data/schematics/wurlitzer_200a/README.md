# Wurlitzer 200A: sources

What the model (docs/WURLITZER_PLAN.md) is built from, gathered 2026-11-20. Every value in the
config files must cite one of these, or be marked `provisional`. The documents themselves are
git-ignored (not ours to redistribute); their URLs and sha256 are below.

## The documents

| File | What | Where from | sha256 |
|---|---|---|---|
| `wurlitzer-200-200a-service-manual.pdf` | Wurlitzer, *Electronic Pianos Service Manual, Models 200, 203, 203W, 206, 207 & 207V, 214 & 214V*, P-1-2000-742; scanned by Tropical Fish; 77 pages | web: https://static1.squarespace.com/static/581b462f5016e14ae76bd275/t/5ebb550ed544905f3db1d03a/1589335321798/wurlitzer-200-200a-service-manual.pdf | `80e3a7c9933350c92b512e2bf4f52a60ed55523bf897a6439614a96d9c21da85` |
| `wurlitzer_200a_schematic_p76.png` | The manual's page 76 (PDF page numbering) rendered at 200 dpi: the **Model 200A** schematic (starting serial 102905, assembly 203730-3) | rendered from the PDF above | `98dae0317efd4957937c99314f35742d89e9bd9caa437e86d3f798ca0670fdd1` |
| `vintage_vibe_installing_and_tuning_reeds.pdf` | Vintage Vibe, *Installing & Tuning Wurlitzer Reeds*, 3 pages | web: https://cdn.shopify.com/s/files/1/0666/2821/files/Installing_and_Tuning_Reeds.pdf | `6ea3ad4addde84aba3ce3af324290bf874ba432729ef3fec1c9b420ec10d5582` |
| `pfeifle_dafx17_paper_79.pdf` | F. Pfeifle, "Real-time physical model of a Wurlitzer and Rhodes electric piano", DAFx-17, Edinburgh, 2017 | web: https://dafx.de/paper-archive/2017/papers/DAFx17_paper_79.pdf | `fd287f6f5e751f62b0c98a5df42a58de8599902d4e0ea164d9149f6591894301` |
| `wurlitzer-200-200a-schematics-diagrams.pdf` | Tropical Fish's high-resolution scan of the manual's diagrams and schematics, 25 pages; **p. 23 is the Model 200A schematic** (the drawing WZ2 is traced from: "the drawing" in `config/circuits/wurlitzer_200a.yaml`) | web: https://www.tropicalfishvintage.com/s/wurlitzer-200-200a-schematics-diagrams.pdf (index: https://www.tropicalfishvintage.com/schematics) | `80ffb43aac93596ead892a1b03e5b60d26f9eaad6a0aaae2881d32f5f4db141c` |


Not yet in hand (WURLITZER_PLAN.md WZ0):
- F. Pfeifle, M. Muenster, "Tone production of the Wurlitzer and Rhodes e-pianos", in A.
  Schneider (ed.), *Studies in Musical Acoustics and Psychoacoustics*, Current Research in
  Systematic Musicology 5, Springer, 2017, pp. 75-107 (FEM of the reed and pickup, high-speed
  camera measurements; cited by the DAFx paper as [18]).
- Vintage Vibe's reed cutting chart, if one exists: https://www.vintagevibe.com/products/wurlitzer-200-series-reed-blanks
  (rate-limited when tried).
- A per-note recording set of a real 200A (DI from the AUX OUTPUT and through its speakers).

## The service manual (page numbers are the manual's own; PDF page in brackets)

The text pages describe the **200** (1968-73 amplifiers). The 200A differs in its electronics
(page 76's schematic below); keys, action, reeds and pickup are the same series.

- **Keyboard** (p. 1 [3]): 64 notes, A-13 through C-76 (the 88-key numbering: A1 to C7).
- **Action** (p. 2 [4]): "Wurlitzer manufactured action, employing conventional action parts such
  as whips, butts, flys (jacks), dampers, etc. Regulates like a conventional piano action."
  Pfeifle calls it a miniaturized London-style action.
- **Hammers** (p. 2 [4]): "Three ply maple covered with mothproofed felt."
- **Tone source** (p. 2 [4]): "Hammers strike Swedish Sandvik steel reeds, causing them to vibrate
  in a polarized electrostatic field."
- **Speakers** (p. 2 [4]): the Model 200, two 4" x 8" oval (the 200A differs: page 76).
- **Power** (p. 3 [5]): Models 200 ... 214, 40 W from 117 V 50/60 Hz.
- **The 200's amplifier** (p. 4-5 [6-7]): six sections (low-voltage supply, regulator,
  high-voltage polarizing supply, preamp / vibrato modulator, vibrato oscillator, power stage).
  - "The reed pickups, mounted on the reed bar are 160 to 170 volt DC above ground. This is a
    polarizing voltage used to develop a capacitive type input signal pickup." A half-wave
    rectifier off a step-up winding, a pi filter and a bleeder; "Because of R-56, a 560K OHM
    resistor in series with the output, the supply can deliver only a very small amount of
    current to the reed bar."
  - TR-1 converts the reed bar's high impedance; on the 200, TR-2 / TR-3 are a vibrato
    modulator whose degenerative feedback is shorted to ground at the oscillator's rate via
    D-5 (amplitude modulation). "The vibrato oscillator is preset to a frequency of 5.75 cycles
    per second" (TR-4, a Darlington, and a phase-shift network). The 200A does it differently
    (an LED / LDR, below).
- **Regulation** (pp. 11-20 [15-24]):
  - key height 2", key dip ~3/8" at the naturals' front, after touch ~1/32" (p. 14, 17-18);
  - hammer blow distance "1 5/64" measured from the tip of the hammer to the under surface of
    the reed" (p. 17 [21]); let-off "when it is 1/8" from the reed" (p. 17);
  - too little after touch: the hammer bobbles and may double strike; too much: it may block on
    the reed (p. 18 [22]);
  - the striking point is factory set; a hammer is moved by heating its shank's glue (p. 16 [20]);
  - dampers: ~1/32" between the damper levers and the damper rail felt (p. 19 [23]), damper
    regulating screws ~.035" over the grommets (p. 20 [24]); the sustain pedal lifts the damper
    rail, 1/32"-1/16" lost motion (p. 20).
- **External amplifiers** (p. 21 [25], the 200): the external output jack, ~0.5 V.
- **Trouble shooting** (pp. 39-44):
  - "Check to be sure reeds are centered in pickup slots" (noise, p. [43]);
  - "One or more notes that are extra loud or harsh": "the reed involved is slightly off center in
    the pickup or electrode ... If the reed is centered and still too loud, bend the ends of the
    pickup up slightly (1/32" to 1/16")" ([47]);
  - "Do not bend the reeds, this makes them go flat in pitch";
  - "Duds" (short ringers): a slight twist of the reed bar when its four screws are tightened;
    shim .010"-.025" under the bar ([48]).
- **Index of schematics** (p. 45 [49]): 11-0783 (1968, 1969), 11-1305 (1971), 201904 (1973) for
  the 200; the 200A's is the last page.

## The 200A schematic (PDF page 76)

Read from `wurlitzer_200a_schematic_p76.png` (legible except a few values, marked "?"; trace it
fully in WZ0). Printed DC voltages are on the drawing for most transistor nodes.

- **Reed bar preamp** (a board between the reed bars):
  - +150 V through **R2 1 MEG** to the pickup ("mounting screw to pickup"); the reeds are at ground
    through the reed bar casting ("GND mounting screw to reed bar casting");
  - the pickup node through **R1 22K** and **C1 .022 µF** to TR-1's base; **D1** (25 PIV, 1 mA,
    142136) and **C2 220 pF** at the base; **R3 470K**;
  - TR-1 and TR-2 direct-coupled with **R4 150K** feedback, **R6 1.8K**, **C3 / C4 100 pF**,
    **R5 33K**, **C5 4.7 µF**, **R7 270 Ω**, **C7 22 µF**, **R8 820 Ω**, **R10 56K**; out
    through **C6 4.7 µF** and **R9 6.8K**; +15 V supply;
  - printed: TR-1 base 2.45 V, emitter 1.95 V, collector 4.1 V; TR-2 collector 8.8 V, emitter
    3.4 V.
- **Vibrato** ("used on 200A, 214A & 214VA"):
  - oscillator TR-3 / TR-4 with a twin-T-like network: **C16, C17 .12 µF**, **R12 27K**,
    **R13, R14 680K**, **C18 .12 µF**, **R15 680K**, **R16 10K**; printed 1.25 V, 5.9 V, .68 V;
  - **R17 4.7K** (a trimmer, 203717-2) into **LG-1, an LED / LDR (142312)**; "typical wave form
    11.5 V p-p"; **R18 680 Ω**;
  - the LDR shunts the preamp's output to ground through the **50K VIBRATO** control (201812) and
    an **18K** resistor (the depth control); no rate control on the panel.
- **Volume:** a 25K reed bar volume (203717-1) and a 10K main volume (203643-001) appear on the
  drawing; which feeds what is to trace (WZ0).
- **Headphone & AUX output** (200A, 214A and 214VA; early and late production drawn): TR-15 /
  TR-16 (R42 120K, R43 1.8K, R44 15K, R45 680 Ω, R46 120 Ω, R47 56K, R48 180 Ω, C23 1 µF, C24 /
  C25 39 pF, C26 4.7 µF, C27 47 µF, R41 27K) fed from the main volume through the **AUX VOLUME
  100K** (203755), out through a **1K screwdriver-adjusted pot** (204524) to the **AUX OUTPUT**
  jack: "Maximum output signal level approx. .4 V AC." It taps the signal after the preamp, the
  vibrato and the main volume, before the power amplifier.
- **Power amplifier:** TR-7 / TR-8 (input pair, 142083-1), TR-14 pre-driver (203719), TR-9 bias
  control (137159-1; **R34 160 Ω**, **R35 220 Ω**, R28 selected for 0 V DC at the output),
  drivers TR-10 (203719) / TR-12 (203718), outputs **TR-11 PNP (507661-1 or 203735)** and **TR-13
  NPN (507664-1 or 203734)** on heat sinks; **R37 / R38 .47 Ω 2 W**; fuses F-1 / F-2 "1.5 A for
  200A"; feedback **R31 15K** to **R30 220 Ω** with **C10 22 µF**; R32 / R33 1.8K, R36 / R39 270 Ω,
  C11-C14 100 pF; output network **R40 12 Ω** + **C15 .1 µF**; rails **±22.5 V** (test points).
- **Output:** the earphone jack switches the speakers off and loads the amplifier with an
  **8 Ω 5 W** resistor, the phones through **470 Ω**. **Speakers, Model 200A: two 16 Ω 4" x 6"
  P.M.** (202243) in parallel.
- **Low-voltage supply:** power transformer 203715; bridge D2-D5 (142350); **C28, C29 2200 µF**
  (±22.5 V); regulator **IC-1 (142349)**, a 14-pin package with a +7.2 V reference pin
  (provisional: model knowledge, a µA723-type), **R53 4.7 Ω 1 W**, **R54 / R55 10K 1%**, C32 .05,
  C33 470 pF, C35 .1 -> **+15 V** to the preamp.
- **High-voltage supply:** **D6** (600 PIV, 1 A, 202050) half-wave off its own winding; **R49
  56K**, **C30 .33 µF**, **R50 8.2 MEG**, **R51 1 MEG**, **C31 .33 µF**, **R52 22 MEG**, **R56 1
  MEG**, **C34 .33 µF** -> **+150 V** to the preamp (the 200's text says 160-170 V at the pickup).
- **Mains:** SLO-BLO .5 A, on / off switch on the volume control, neon lamp, .01 µF.
- **Transistors** are Wurlitzer house numbers: TR 1, 2, 5, 6, 15: 142083-3; TR 3, 4: 142083-2;
  TR 7, 8: 142083-1; TR 9: 137159-1; TR 10, 14, 16: 203719; TR 12: 203718. Their JEDEC
  equivalents are to source (WZ0); until then, stand-ins from our fitted BJTs, marked provisional.

## The reeds

- **Blanks** (Vintage Vibe, "Case Study: Wurlitzer Electric Piano Reeds", web:
  https://vintagevibe.com/blogs/news/wurlitzer-electric-piano-reeds-case-study). For the 200A
  series:

  | Blank | Reeds | Thickness | Width | Ground |
  |---|---|---|---|---|
  | Lower | 1-14 | .020" | .155" | no |
  | Upper Lower | 15-20 | .020" | .129" | no |
  | Middle | 21-42 | .032-.034" | .120" | yes |
  | Upper Middle | 43-50 | .032-.034" | .110" | yes |
  | Treble | 51-64 | .032-.034" | .097" | yes |

  The 200 has .031" for the three upper blanks; the 200A "changed its steel stock and increased
  the thicknesses of the Middle, Upper Middle and Upper blanks". The same page also says the tongue
  went "from around .020" on a 200 to .026" on the 200A", inconsistent with its own table:
  settle it in WZ0. **No reed lengths are published there.**
- **Tuning** (Vintage Vibe, *Installing & Tuning*, p. 1-2):
  - lead (solder) at the tip in a pyramid shape; filing it off raises the pitch, adding lowers it;
  - the reed screw's hole is oversize: moving the reed to the FRONT "will drop the pitch (from 2
    to 5 cents)"; tightening the screw after tuning makes it sharp; the screw's washer is dished;
  - tolerance -2 to +3 cents;
  - a lop-sided tip "can affect the motion of the reed as it vibrates".
- **Position and voicing** (the same, p. 3):
  - "When a reed at rest is positioned inside the pickup, a very strong undesirable harmonic will
    be generated. Reeds should be positioned as close to the center as possible"; centred sideways
    with a feeler gauge; "Unequal spacing makes a reed too close to one side of the pickup and
    will give an undesirable loud tone";
  - "Voicing can be accomplished, in part, by changing the relative position of the pickup to the
    reed ... Moving the pickup up or down adjacent to the reed will change tone characteristics";
  - the reed's head under the screw "is also an electrical ground. If you lose the ground, you will
    lose the volume. Any foreign material on the head of the reed will dampen the oscillation";
  - the strike point moves by shifting the reed bar, then the hammer.

## Pfeifle, DAFx-17

- The pickup (3.2): a time-varying capacitor, "a loaded static plate and a moving plate, called a
  reed, having zero potential (connected to ground)"; the plate "has cutouts at the position of the
  reed for each note"; the reeds "vibrate freely between the symmetric cutouts".
- "According to the manual, the high potential has a voltage 170V which has been found to be
  considerably lower (130V) in the measured instrument used in this work."
- Measurements (4.3): a high-speed camera on the reed: "approximately sinusoidal motion"; the voltage
  behind the pickup before the amplifier (Fig. 5, first 12 ms).
- The reed model (5.5): a non-uniform cantilever with a large-deflection term, one polarization;
  "the influence of higher modes are comparably small or non-existent even under extreme playing
  conditions" (camera measurements).
- The hammer (5.2): Stulov's hysteretic felt.
- The pickup model (5.6): i(t) = u0 dC/dt, C from 2D electrostatic slices through the geometry
  (Fig. 8). The paper names a geometrically accurate electrostatic pickup as future work.

## Traced from the high-resolution drawing (2026-11-20, WZ2)

The sharp scan (p. 23 of the diagrams PDF) settles what page 76 of the manual couldn't:

- **The preamp's feedback node x** (the drawing's bus to point 1): TR-1's emitter returns to it
  through R5 33K and C5 4.7 uF in parallel, D1 (anode on x) and C2 220 pF go from TR-1's base
  to it, and R10 56K comes back to it from the output: a non-inverting amplifier whose input is
  bootstrapped (TR-1's base, x and its emitter move together), gain ~1 + 56K / Z(x).
- **x to ground** is the VIBRATO control's network: the 50K control with x on its top and
  ground on its bottom, 18K from x to its wiper, the wiper to LG-1's cell (pin 4; pin 3
  grounded). VIBRATO at 0 shorts the cell (Z = 50K || 18K); fully up shorts the 18K (Z = 50K ||
  the cell). The 206A / 207A's assembly 203722 adds R57 12K from point 1 to ground.
- **LG-1's LED** (pin 2 anode, pin 1 cathode) is the oscillator Darlington's collector load:
  +15 V, R18 680 ohm, the LED, R17 (the 4.7K trimmer, its wiper on one end), the collector.
- **R28 10K** feeds the power amp's PNP pair from the +15 V line, not a rail.
- **TR-8's collector** runs off the drawing's lower edge past the -22.5 V line (drawn hopping
  over it); read as going to ground (provisional: the line's end isn't legible).
- **The AUX output** is fed from point 13, the main volume's top ("from main volume"), through
  the 100K AUX volume: the AUX level doesn't follow the VOLUME knob on this reading (to confirm
  against an owner's 200A).
- **Printed voltages** (VTVM readings, conditions unstated): TR-2, the AUX stage and the power
  amp agree with the model within ~30% (`tests/test_wurlitzer_200a.py`); TR-1's base (2.45 V)
  and emitter (1.95 V) are ~0.7 V below the model's, as if x sat at ~0 V, which the VIBRATO
  network's 13K to ground doesn't allow; read as a meter loading the 470K node or a reading
  under other conditions (open).

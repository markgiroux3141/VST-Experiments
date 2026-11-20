# General Electric RP1560 stereo portable (1961-62): sources

The record player of docs/PHONO_PLAN.md's "The 1960s record player": a US AC/DC (transformerless)
stereo portable with two swing-out "wing" speakers, a V-M record changer and a Sonotone ceramic
stereo cartridge. The local copies here are git-ignored; this README is the citation.

## The schematic

- **Beitman / Supreme, *Most-Often-Needed 1963 Radio Servicing Information*, Vol. R-23**, printed
  page 57 (PDF page 59): web: https://www.worldradiohistory.com/Archive-Rider/BEITMAN-SUPREME/Beitman-1963.pdf.
  It covers the RP1560, RP1561, RP1570, RP2050A and RP2051A. Local copy: `beitman_1963_p57.png`
  (rendered at 400 dpi, rotated upright). "Unless otherwise noted, capacitors more than 1 = MMF
  [pF], less than 1 = MF; DC voltage at 120 V line to B- w/ 20,000 ohm/volt meter."
- Radiomuseum, RP1560A: web: https://www.radiomuseum.org/r/general_el_rp1560a.html. It gives
  1961, "Musaphonic", 2 x 6 in speakers and Sams 596-5, and lists 35C5 output tubes where the
  Beitman sheet shows 35EH5. This model follows Beitman.
- An owner's thread, RP-1570A: web: https://www.classichificare.com/viewtopic.php?p=23641. It
  says "custom V-M record changer", that the original cartridge was the G.E. C-100, and that the
  cabinet and speakers are steel.

### The amplifier, transcribed (right channel; left channel in [ ])

- **Supply.** The line (105-120 V, 60 Hz AC) goes through the changer's switch (plug pins 2-3).
  - The V-M motor (marked 33 ohm) sits from the switched line to the return.
  - **V4 35W4** is a half-wave rectifier. Its plate (pin 5) is on the switched line (115 V
    marked), and its cathode (pin 7) is **+120 V** on **C13B 200 uF 150 WV**.
  - **R16 1500 ohm 1 W** feeds the **+105 V** node on **C13C 100 uF 150 WV**.
  - B- is the return. It goes to the metal chassis through **C12 0.033 uF**, and to the changer
    frame through **R18 68 k** (plug pin 4).
- **Heaters.** A series string at 0.15 A, AC volts to B- as marked:
  - the 35W4 (pins 4-3, pilot tap pin 6, 105 V);
  - a 35EH5 (pin 3 at 78 V, pin 4 at 46.5 V), then the second 35EH5;
  - the 12AX7 (pins 5-4, 12 V), then B-.
- **Input.**
  - The ceramic cartridge's two elements share a common lead, which goes through **C1 0.047 uF**
    to B-.
  - Each element's hot lead goes to one end of **VOLUME R19A [R19B] 2 M**, whose other end is B-.
  - **BALANCE R20A [R20B] 2 M** runs from the volume's wiper to B-. Its sections are ganged in
    opposite senses.
  - The balance wiper goes through **R2 [R1] 220 k** to the grid.
  - No tapers are printed; arrows mark clockwise.
- **V1A [V1B] 12AX7.**
  - Grid pin 7 [2], 0 V.
  - Cathode pin 8 [3], 1.05 V [1.15 V], to B- through **R4 [R3] 390 ohm**, unbypassed.
  - **R6 [R5] 39 k** from the cathode to +105 V: a bleeder that sets the bias.
  - Plate pin 6 [1], 85 V, through **R8 [R7] 220 k** to +105 V.
- **Coupling and tone.**
  - **C4 [C5] 0.02 uF** from the plate to node X.
  - From X: **C6 [C7] 0.0039 uF** to the BASS end of **TONE R21A [R21B] 500 k**. The pot's wiper
    is on B- and its TREBLE end is open, so it is a rheostat in series with C6: at BASS the
    treble is cut most.
  - From X: **R10 [R9] 390 k** bypassed by **C8 [C9] 100 pF**, to the output grid.
  - From the grid: **C10 [C11] 0.0033 uF** in series with **R12 [R11] 150 k** to B-, and the grid
    leak **R14 [R13] 470 k**.
- **V2 [V3] 35EH5.**
  - Grid pins 2 and 5, 0 V.
  - Screen pin 6, 105 V.
  - Plate pin 7, 118 V [115 V].
  - Cathode pin 1, 2.7 V. The cathodes are joined on **R15 33 ohm 1 W**, bypassed by
    **C13A 30 uF 25 V**.
- **Output transformers.**
  - Each primary runs from the +120 V node (red) to its plate (blue).
  - On the RP1560 / RP1561 each wing holds its own transformer (T1, T2) and one speaker.
  - The RP1570 has two speakers per channel on the chassis's T3 / T4.
  - The sheet prints no transformer impedances.
- **Speaker phasing**: 1.5 V across the output, negative on black, and the cones move out.

## The output tube

- **RCA 35EH5**, August 1960: web: https://frank.pocnet.net/sheets/049/3/35EH5.pdf.
- Typical class-A1 operation:

| Plate | Screen | Cathode R | Peak grid | Plate current | Screen current (zero / max signal) | Plate resistance | gm | Load | THD | Output |
|---|---|---|---|---|---|---|---|---|---|---|
| 110 V | 115 V | 62 ohm | 3 V | 32 mA | 7.2 / 12 mA | 14 k | 12,000 umho | 3000 ohm | 8 % | 1.2 W |

- Heater: 35 V, 0.15 A. Maximum grid-circuit resistance with cathode bias: 0.5 M.
- Basing 7CV: pin 1 cathode and g3, pins 2 and 5 g1, pins 3-4 heater, pin 6 g2, pin 7 plate.

## The cartridge: Sonotone 16T-S

- Named on the schematic's table: Sonotone 16T-S with stylus (RP1560, RP1561, cat. RS3476).
  Later production used the G.E. C-100, for which no data were found.
- **Sonotone's 1966 list for the 16TAF** (the same body family), reproduced by Roger Russell, a
  Sonotone engineer from 1959: web: http://www.roger-russell.com/sonopg/sonopc.htm.

| Item | Value |
|---|---|
| Type | stereo / mono turnover ceramic |
| Response | 20 Hz - 12 kHz; within 1.0 dB from 20 Hz to 10 kHz |
| Output | 0.65 V (velocity not stated) |
| Compliance | 2.4e-6 cm/dyne |
| Separation | 25 dB |
| Load | 2 M |
| Tracking force | 5-7 g in changers |

- **Construction**, also from Russell's page:
  - lead zirconate titanate bars at 90 degrees to each other and 45 degrees to the vertical,
    driven by a pantograph "resolver";
  - the bars clamped between high-durometer rubber pads, the cavity filled with silicone
    damping compound;
  - a butyl-rubber link from the lever to the needle shank (the "Sono-Flex");
  - amplitude-responding, flat into 1 M or more.
- **V-M's catalogue**: 16T at 0.65 V, 4-7 g; the 16T-SD with 0.7 mil diamond LP / 3.0 mil
  sapphire 78 tips. Web: https://www.thevoiceofmusic.com/catalog/part_detail.asp?PNumberBase=16T&SearchType=MfgNameCartridges&MfgName=Sonotone.
- **Electronics World, September 1961, pp. 18-20**, a lab review of the sibling Sonotone 9T
  (the same Sono-Flex needle family): web: https://www.worldradiohistory.com/Archive-Electronics-World/60s/1961/Electronics-World-1961-09.pdf.
  It gives separation of 26 dB at ~3 kHz (Sonotone measured 30), response 3 dB down from
  Sonotone's curve between 11 and 15 kHz, and 3-5 g in changers. It has a response /
  separation graph.

## Not found

- **The changer.** The V-M's model number, motor, platter, arm geometry and speed figures.
  Leads: Sams Photofact 596-5 (paid), and V-M's 1200 / 1201 service manuals.
- **The speakers.** Impedance, resonance, the wings' volume.
- **The cartridge.** The 16T's capacitance, tip mass and resonance.

The model's values for these are provisional, with their reasoning in the config files.

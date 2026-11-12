# Vox AC30/6 Top Boost (JMI, 1962-64, copper panel) sources

Collected 2026-11-12 for an AC30 Top Boost model (worktree `vst-amps`, branch `amps`). The amp
meant is the JMI AC30/6 Twin of 1962-64 with Top Boost: four EL84s in push-pull parallel on one
shared cathode resistor, a GZ34, no negative feedback, the Brilliant channel's ECC83 triode into
the Top Boost's ECC83 (gain stage, cathode follower, treble / bass network), mixed with the
Normal channel into the long-tailed-pair inverter. No circuit file exists yet; values going into
one should cite these as `sch:` (a drawing printed by JMI / Vox: give the tag and the issue),
`trace:` (a later or third-party drawing of a real amp), `web:` (a replacement part maker's or a
datasheet's figure) or `provisional:`. The transcriptions below are from one research pass
(2026-11-12): recheck each against its image when it goes into the circuit file.

**No JMI drawing of the copper-panel AC30 with Top Boost integrated exists** (voxac30.org.uk:
"No JMI circuit diagram is currently known for the AC30TB. The earliest we have is OS/013 ...
1969", web: https://www.voxac30.org.uk/vox_ac30_top_boost_integrated.html). JMI's own
documentation of a Top Boost AC30 of the period is the pair **AC30/6 Normal (OS/065 = A/026)
plus the add-on Top Boost unit (OS/010)**: OS/010's note reads "This unit to be used in
conjunction with AC30/36 amplifier circuit [Drg. No. A/026] to produce Top Boost amplifier", and
OS/065's issue 2 adds "Note: for Top Boost amplifier see Drg. No. OS/010". The integrated
copper-panel chassis (Westrex, late 1963 to late 1964, ~300 made) "corresponds with JMI OS/010"
(same page). So the model is OS/065 issue 4 + OS/010 issue 3, cross-checked against the later
integrated drawings (OS/013 1969, EME 1968, VSL 1971, Dallas 1974).

## The drawings (all in this folder)

| Tag | File | What it is |
|---|---|---|
| **N64** | `jmi_ac30-6_normal_os065_iss4_sep1964_voxac30.jpg` | JMI "'Vox' AC.30.36 Amplifier Circuit, Normal", Drg. No. OS/065, drawn RD (Dick Denney) 29-4-60, modifications to **issue 4, 11-9-64** (the date from which the mods are in the body of the drawing, per voxac30.org.uk). 3600 x 2492 px copy "probably from Modern Music in Dudley". Prints node voltages. **A later hand added a negative feedback loop in blue ink (1M + .1 mfd from the 16 ohm tap to V1's plate area, "NEG FEED BACK", and a sketch at right): not JMI's, ignore it**; one illegible value (25 uF in the vibrato oscillator's cathode) was supplied in red by the site. |
| **N64d** | `jmi_ac30-6_normal_os065_iss4_sep1964_drtube.gif` | The same sheet, another copy (Dr Tube, 1669 x 1365 px, lower resolution; secondary lead colours BLUE / GN / BLK hand-written; no blue NFB). |
| **MOD** | `jmi_os065_modifications_panel.jpg` | Close-up of OS/065's "Modifications" panel (520 x 1800 px). |
| **A61** | `jmi_ac30-6_normal_c1961-62.jpg` | The same circuit as an earlier issue without sheet number (dated 29-4-60, mods to 8-5-61), "likely produced in the second half of 1961 or early 1962 ... AC30s with serial numbers in the range c. 4600-5500 were generally built to the scheme represented" (the site's caption). Prints .05 / .005 (WIMA Tropydur) where later sheets print .047 / .0047; R24 80 ohm 5 W; HT 285 V; R74 fitted. No voltages. Clean, 2600 x 2334 px. |
| **TB65** | `jmi_ac30-6_topboost_os010_iss3_feb1965.gif` | JMI "Optional Brilliance Unit and Connections to AC30/6 (Circuit)", **Drg. No. OS/010**, drawn J. Bell 11-12-61; changes: issue 1 (11-12-61) "Note added. .022 uF cap. was .03 uF value"; issue 2 (14-6-63) "Voltages & pin nos added"; **issue 3 (15-2-65)**. The copy circulating on the web; the large title "VOX TOP BOOST MOD" was added in the 1990s (voxac30.org.uk). Prints voltages and pin numbers, HT "320V". 1570 x 976 px. |
| **TB63** | `jmi_ac30-6_topboost_os010_iss2_jun1963_wallet_thumb.jpg` | OS/010 **issue 2** (June 1963) from a JMI wallet of service sheets; only the site's 1000 x 806 px watermarked thumbnail could be retrieved. Same circuit; prints the HT as "**H.T. 230v**" and no other voltages; designators (R1-R6, C1-C5, VR) hand-added later. |
| **T64** | `jmi_ac30-6_treble_os056_sep1964.jpg` | OS/056, AC30/6 **Treble**, 10-9-64 (Thomas Organ service manual). Differs from Normal in C2, C3, C5, C6, C7, C9, C10, V1's cathode and a 330K / 220 pF at each volume (the site's summary; values below). |
| **B64** | `jmi_ac30-6_bass_os057_sep1964.jpg` | OS/057, AC30/6 **Bass**, 11-9-64. Differs from Normal in C2, C3, C5, C6, C7, C9, C10 only. Its supply routing is the clearest of the JMI copies. |
| **RV65** | `jmi_reverb_addon_os075_jan1965.jpg` | OS/075, the add-on reverb unit, 15-1-65 (Thomas Organ manual page): confirms "320V + HT, connect to junction of R10-R11". Context only. |
| **OS13** | `vsl_ac30tb_os013_1969_detail_thumb.jpg` | OS/013 "AC30 Amplifier Treble & Bass", Vox Sound Ltd, 20-11-69 (detail, 800 x 1513 px): the earliest drawing of the integrated Top Boost. Prints voltages (1.65 V, 180 V, 290 V, HT 320 V). |
| **EME68** | `eme_ac30-36_1968.jpg` | "Amplificatore AC.30.36", E.M.E. Recanati (Italy), 17-11-68, stamped 28-2-72. Integrated Top Boost; part list numbering continues JMI's (V11 = the TB valve, R74-R79, C42-C46). |
| **VSL71** | `vsl_ac30-6tb_feb1971.jpg` | Vox Sound Ltd AC30/6 Top Boost, 12-2-71, no information panel. Same values as EME68. |
| **DA74** | `dallas_ac30tb_sc-v-1313_jun1974.jpg` | Dallas Music Industries "Vox AC30 (Treble & Bass)", SC/V/1313, re-drawn 24-6-74. Clean and legible; silicon rectifiers (BY133) in place of the GZ34. |
| **RX94** | `vox_ac30tb_reissue_ac30-60-02_iss5_1994.pdf` | Vox's own drawing of the 1990s reissue, AC30-60-02 issue 5 (06/12/94), 2 sheets. PCB reissue; different values in many places. Useful for tapers and part numbers only (OT 784-413, mains 789-102, choke 292-767). |

Provenance (all downloaded 2026-11-12):

- N64: web: https://www.voxac30.org.uk/images/schematics/closeups/large_os_065.jpg; T64:
  `.../closeups/large_os_056.jpg`; B64: `.../closeups/large_os_057.jpg`; A61:
  `.../closeups/ac30_online_02.jpg`; MOD: `.../closeups/os065_panel_03.jpg`; RV65:
  `.../closeups/manual_05.jpg`; EME68: `.../closeups/eme_ac30.jpg`; VSL71:
  `.../closeups/vsl_top_boost_1971.jpg`; DA74: `.../closeups/large_dallas_1974.jpg`; all from the
  page web: https://www.voxac30.org.uk/vox_ac30_circuit_diagrams.html (its notes on each issue
  are quoted above).
- TB63: web: https://www.voxac30.org.uk/images/schematics/thumbs3/top_boost_wallet.jpg (page
  web: https://www.voxac30.org.uk/vox_ac30_top_boost_circuit.html, which describes the four
  issues of OS/010; the closeup URL pattern returned nothing). The Thomas Organ copy of issue 2
  (`.../thumbs3/top_boost_thomas.jpg`, "HT 230v", "Mods to amplifier AC30/6 Drg No. A/026") was
  seen but not copied.
- OS13: web: https://www.voxac30.org.uk/images/top_boost_panel/thumbs3/vsl_013.jpg (page
  vox_ac30_top_boost_integrated.html; the whole sheet is `.../schematics/closeups/vsl_os013.jpg`,
  800 x 1133 px, not copied).
- N64d: web: https://www.drtube.com/schematics/vox/ac30-6-os065.gif; TB65: web:
  https://www.drtube.com/schematics/vox/ac30-tbmod-os010.gif (voxac30.org.uk's
  `closeups/top_boost_circuit.jpg`, 1567 x 976 px, is the same drawing re-encoded); RX94: web:
  https://www.drtube.com/schematics/vox/ac30-60-02-iss5.pdf; index web: https://www.drtube.com/vox/.
  Dr Tube's OS/057 GIF (`ac30-6-bass-os057.gif`) and its "AC30 Reverb amp (L.G.P., 1978)" were not
  copied.
- Not found: the JMI wallet's earlier OS/010 issue 1 (no copy known, per the site); any Jim
  Elyea portfolio sheet (his sheets 18-20 and 57 are cited by the site, not online); GroupDIY /
  el34world AC30 drawings were not needed (drtube and voxac30.org.uk carry the JMI sheets).

## Values by stage

"Pick" is the value proposed for a 1963-64 Top Boost AC30 and why. Designators are JMI's
(OS/065 for the amp, OS/010's later hand-written ones in brackets for the TB unit, EME68's
R74-R79 / C42-C46 numbering where cited). Pins: ECC83 1/2/3 = plate / grid / cathode of one
triode, 6/7/8 of the other; EL84 2 grid, 3 cathode + g3, 7 anode, 9 screen (all drawings).

### Inputs and V1 (ECC83, shared by Brilliant and Normal)

- Inputs: per channel two jacks, 68K to the grid each (R1 / R2 Brilliant, R12 / R13 Normal),
  1M to ground (R3, R14) (A61, N64, DA74).
- V1: Brilliant triode grid pin 2 / plate pin 1, Normal triode grid pin 7 / plate pin 6;
  **one shared cathode**, pins 3 + 8.

| Part | A61 (c.1961-62) | N64 (Sep 1964) | DA74 (1974) | Pick |
|---|---|---|---|---|
| R4 shared cathode | 1.5K (MOD: "was 2.2K" before 8-5-61) | 1.5K | 1K5 | 1.5K |
| C1 cathode bypass | 25 uF 25 V | 25 uF 25 V | 25 MFD 25 V | 25 uF |
| R5 Brilliant plate load | 220K (was 100K) | 220K | 220K | 220K |
| R6 Normal plate load | 220K (was 100K) | 220K | 220K | 220K |
| Plate supply | 290 V node, C4 8 uF | same | same | as drawn |
| C3 Brilliant coupling to VR2 | 500 pF | 500 pF | 500 pF | 500 pF |
| R74 across C3 | 150K (added 8-5-61) | deleted (MOD issue 2, 14-6-63); OS/010: "removed when fitting unit" | none | none |
| C2 Normal coupling to VR1 | .05 (was .01) | .047 | .047 | .047 uF |

N64 voltages: plates 170 V, cathode 1.6 V (0.55 mA a triode).

### Volumes and the mixer

- VR1 Normal volume, VR2 Brilliant volume: **500K LOG** each (A61, N64; EME68 / VSL71 470K log).
  No taper law beyond "LOG" is printed; RX94 prints "A470K" (A = log).
- Mixing: R7 220K from VR1's wiper and R9 220K from the Brilliant path to the junction with
  C5, which couples to V2's first grid (pin 2). MOD: R7 and R9 "was 270K" (before 8-5-61). In
  N64d the R7 value reads "270K" at its low resolution; N64 and A61 read 220K, and OS/010 prints
  "R7 220K", "R9 220K": pick 220K.
- C5: .05 (A61), .047 (N64, OS/010, DA74); MOD "was .01". Pick .047 uF.
- **Top Boost insertion** (OS/010 inset "Mods to amplifier AC30/6, Drg No. A/026"): the link
  between VR2's wiper and R9 is broken (points A / B); A (VR2's wiper) goes to the TB valve's
  grid, B (the TB's treble wiper) to R9. "ADD 100pF" across VR2, from its top to its wiper (the
  bright cap; EME68 / VSL71 100 pF, DA74 C41 100 pF, OS13 100 pF).
- The vibrato-tremolo channel enters V2's second grid (pin 7) through C7 (.05 A61, .047 N64)
  from VR4 (500K LOG, the Vib-Trem volume). With that channel unused, pin 7 sees VR4's wiper:
  for the Top Boost path model V7 / VR4 at rest or VR4 at zero (provisional: the drawing does
  not say what an idle channel's VR4 is set to).

### Top Boost unit (OS/010; one ECC83, "connect heaters to V2")

| Part | TB65 (OS/010 iss. 3, 1965) | TB63 (iss. 2, 1963) | OS13 (1969) | EME68 / VSL71 | DA74 (1974) | Pick |
|---|---|---|---|---|---|---|
| Gain stage grid (pin 2) | from VR2's wiper, no grid stopper | same | same | same | same | as drawn |
| Plate load (pin 1) | 100K from the TB node | 100K (R5) | 100K | R74 100K | R75 100K | 100K |
| Cathode resistor (pin 3) | 1.5K | 1.5K (R1) | 1.5K | R76 1.5K | R77 1K5 | 1.5K |
| Cathode bypass | **25 uF 25 V** | 25 uF 25 V (C1) | **none drawn** | C42 25 uF in a dashed box "A": "Solo sullo schema elettrico originale" (only on the original drawing) | **none** | 25 uF (the only period drawings; flag) |
| Cathode follower | plate pin 6 to the TB node, grid pin 7 DC-coupled to pin 1, cathode **56K** to ground (pin printed "3" in TB65: a slip for 8; TB63 "8") | 56K (R2) | 56K | R77 56K | R78 56K | 56K |
| Node supply | 10K from "C: junction of R10, R11" (the 320 V rail), node 32 uF | 10K (R6), 32 uF (C5) | 10K, 32 uF | R75 10K, C46 32 uF | R76 10K, C42 32 MFD | 10K / 32 uF |
| Treble cap (CF cathode to treble pot) | **50 pF** | 50 pF (C2) | 50 pF | **47 pF** (C43*) | 50 pF (C43) | 50 pF |
| Treble pot | 1M LOG | 1M LOG | 1M LOG | VR6 1M log | 1M LOG | 1M log |
| Series caps after the treble pot | .022 uF, .022 uF (issue 1: ".022 uF cap was .03 uF"; TB63's note may read ".02") | .022, .022 (C3, C4) | .022, .022 | C44, C45 0.022 | C44, C45 .022 | .022 / .022 uF |
| R from the caps' junction to the CF cathode | 100K | 100K (R3) | 100K | R78 100K | R79 100K | 100K |
| R from the second cap to ground | 10K | 10K (R4) | 10K | R79 10K | R80 10K | 10K |
| Bass pot | 1M LOG: one end at the treble pot's bottom, the other at ground, wiper at the second cap / 10K junction | same | same | VR7 1M log | same | as drawn |
| Output | treble wiper to B, then R9 220K to the C5 junction | same | same | same | R9 220K | as drawn |

Topology, as printed in all of them: CF cathode -> 50 pF -> treble pot (top) ; treble pot
bottom = node X ; X -> .022 -> Y -> .022 -> Z ; Y -> 100K -> CF cathode ; Z -> 10K -> ground ;
bass pot X to ground with its wiper on Z ; treble wiper = output. voxac30.org.uk: the circuit was
"a lift from a circuit adopted by Gibson in the mid 1950s for its Vanguard GA-77" (Glen Lambert).

TB65 voltages: TB node 290 V; gain-stage plate 180 V, cathode 1.65 V (1.1 mA; with 100K from
290 V: 1.1 mA, consistent); CF cathode 180 V (3.2 mA in 56K). TB63 prints only "H.T. 230v" at C:
a slip for 320 V (TB65, RV65, N64 all 320 V; 230 V is V2's plate voltage in N64). Derived:
4.3 mA through the 10K from 320 V gives 277 V, 4 % under the printed 290 V.

### Phase inverter V2 (ECC83, long-tailed pair; also the Vib-Trem mixer)

| Part | A61 | N64 | B64 / T64 | DA74 | Pick |
|---|---|---|---|---|---|
| Grid 1 (pin 2) coupling | C5 .05 | .047 | B .047 / T .01 | .047 | .047 uF |
| Grid 2 (pin 7) coupling | C7 .05 | .047 | B .047 / T .01 | .047 | .047 uF |
| Grid leaks R8, R17 | 1M, 1M, to the tail junction | same | same | 1M, 1M | 1M |
| Cathode resistor R16 | 1.2K | 1.2K | 1.2K | 1K2 | 1.2K |
| Tail R15 to ground | 47K | 47K | 47K | 47K | 47K |
| Plate loads R18, R19 | 100K, 100K | 100K, 100K | same | 100K, 100K | 100K / 100K (equal: no rebalancing) |
| Plate supply | R11 22K from the 320 V rail, C8 8 uF | same | same | same | as drawn |

N64 voltages: cathode 56.5 V, tail junction 55 V (1.17 mA total), plates 230 V. **No negative
feedback** in any JMI, EME, VSL or Dallas drawing (the blue loop on N64 is a later hand-made
addition; voxshowroom: "eliminating the traditional negative feedback circuit in the power amp
became a major contribution to Vox tone", web: https://voxshowroom.com/uk/amp/ac30_6_hood.html).

### Couplings, Cut and the output grids

| Part | A61 | N64 | T64 | B64 | DA74 | Pick |
|---|---|---|---|---|---|---|
| C6, C9 to the EL84 grids | **.15**, .15 (was .01 before 8-5-61) | .15, .15 | .047, .047 | .15, .15 | .15 uF, .15 uF | 0.15 uF |
| Grid leaks R21 (V3 / V5), R20 (V4 / V6) | 220K, 220K | 220K | 220K | 220K | 220K | 220K, to ground |
| Grid stoppers R22, R27, R23, R28 | 1.5K each | 1.5K | 1.5K | 1.5K | 1K5 | 1.5K per EL84 |
| Cut: VR3 + C10 between the two grid lines | 250K LOG (as a rheostat) + .005 | 250K LOG + .0047 | 250K + .0022 | 250K + .01 | 250K log + .0047 | 250K log + .0047 uF |

The ".15" is clearly printed in A61, N64, B64 and typed "0.15 uF" in EME68 / VSL71 / DA74: 0.15
uF, not a misread .1. The Cut control is VR3 wired as a variable resistor in series with C10
from V3 / V5's grid line to V4 / V6's (the tone-cut: more resistance, less cut).

### Output stage, 4 x EL84

- V3 + V5 anodes (pin 7) together to one end of T1's primary, V4 + V6 to the other (all).
- Screens (pin 9) each through **100 ohm** (R25, R26, R29, R30) to the 320 V rail after the
  choke (A61, N64, B64; DA74 100 ohm). Their wattage isn't printed; Don Butler (Toneman) replaces
  them with "1/2 watt 100 ohm carbon film" (web: https://www.mercurymagnetics.com/?s=AC30, a
  ToneQuest article "Transformer Originality" reproduced there).
- Cathodes and g3 (pin 3) all together on **R24 50 ohm**, bypass **C11 250 uF 25 V** (N64;
  DA74 50 ohm / 250 MFD 25 V). MOD issue 2 (14-6-63): "R24 was 80 ohm"; A61 prints "80 ohm 5 W".
  voxac30.org.uk: "As far as can be determined all copper panel chassis with integrated Top Boost
  controls have 50R bias resistors"; one copper-panel AC30X Top Boost example has "an 82 ohm
  cathode resistor" (web: https://www.voxac30.org.uk/vox_ac30_expanded_frequency.html). Pick
  50 ohm (wattage not printed: provisional 5 W, A61's for the 80 ohm).
- N64 prints "12.5 V at 30 watts, quiescent 10 V" at the cathodes: 200 mA total at idle (50 mA
  a valve, anode + screen), 250 mA at full output.

### Output transformer T1

- `sch:` "Primary imped. anode to anode 4K" (A61, N64, B64, DA74); secondary taps **15 ohm,
  8 ohm, com.** (A61 "15 ohm / 8 ohm / com", N64 "15 ohm / 8 ohm / com", lead colours
  hand-written on N64d: BLUE 15, GN 8, BLK com). The centre tap goes to the reservoir C39 (GZ34
  side, before the choke): traced on B64 and N64 (the CT line runs to C39's node), and Don
  Butler: "The center tap is always soldered onto the main supply filter can" (Mercury page
  above).
- Makers (voxac30.org.uk, web: https://www.voxac30.org.uk/vox_ac30_transformers.html and
  `vox_ac30_woden_transformers.html`): Haddon (mains OH114, output OH083; 1960-63, Westrex
  chassis), Albion (same JMI numbers), Woden (Burndept chassis from August 1962: mains 66309 / J/82,
  output 66310 / J/83, choke 66311 / J/84; mains 72318 from September 1963, "the suspicion is
  that JMI asked for the secondaries to be adjusted - specifically the main HT voltage"; a
  simplified, cheaper set 76852 / 76853 / 76854 from late summer 1964, "the four primary windings
  ... reduced to two" per the AC100 site). The same site: "an anode to anode impedance of around
  4K ohms, though in practice this might vary between 3.3K and well over 4K". Don Butler: "A
  Haddon output transformer has a different primary reading than a Woden and different from an
  Albion as well." No JMI-era winding data (DCR, inductance, leakage) was found published.
- Replacement makers:
  - Mercury Magnetics **VXO-30H**: "Haddon version - circa 1963 - 3.7 kOhm primary, 8 & 16 (15)
    ohm taps" (web: https://www.mercurymagnetics.com/mmpn/vxo-30h/); its sheet
    `mercury_VXO-30H_ot_wiring.pdf` (lead colours only: primary yellow / red / yellow; black
    com, green 8, blue 16). **VXO-30M**, "Woden - 4, 8 & 16 ohm taps" (no impedance given;
    `mercury_VXO-30M_ot_wiring.pdf`, web: https://www.mercurymagnetics.com/mmpn/vxo-30m/). Mercury
    also lists O45RS-L ("found in early AC30s", Radiospares, 3.4K / 6.6K / 8K primaries): the
    AC30/4 era, not ours.
  - Hammond **1750V** (`hammond_1750V_ot.pdf`, web: https://www.hammfg.com/files/parts/pdf/1750V.pdf):
    "drop in replacement of original units such as VOX AC30 Vintage (P-TVO30V)"; 4000 ohm CT : 8 /
    16 ohm, 30 W, 70 Hz-15 kHz 0 / -1 dB, < 2 % THD at 70 Hz; DCR primary YEL-RED 70.37 ohm,
    RED-WHT 70.30 ohm, secondary BLK-BLU (16 ohm) 0.720 ohm; inductance (1 kHz, 1 V, OC) primary
    YEL-WHT 6.30 H (40 kOhm), secondary BLK-GRN 19.66 mH, BLK-BLU 35.32 mH; leakage YEL-WHT 5.14 mH
    (1 kHz, 1 V, SC); pages 2-3 are response / THD curves. Which original it was copied from is
    not stated.
  - Hammond **1750T** (`hammond_1750T_ot.pdf`, the 1990s reissue's 784-413): 4000 ohm CT : 8 / 16;
    DCR RED-BRN 54.00, BRN-WHT 60.00, BLK-BLU 0.520 ohm; primary 15.2 H (102 kOhm, 1 kHz 1 V);
    leakage 4.61 mH. For comparison only.
  - Tube Amp Doctor "output transformer for VOX AC 30 ... for VOX AC30 of 60s + 70s modelled after
    a Wooden [Woden] 76853", EI96 (3 3/4 in), secondary 8 + 16 ohm; no impedance or winding
    figures (web: https://www.tubeampdoctor.com/en/output-transformer-for-vox-ac-30).
- **Pick:** 4.0 kOhm plate to plate (`sch:`), 15 ohm and 8 ohm taps (`sch:`). Windings
  provisional: DCRs, inductance and leakage from Hammond 1750V (web, as above) until an original
  is measured; Mercury's 3.7 kOhm (Haddon c.1963) bounds the impedance from below.

### Power supply

- Mains transformer T2 (`sch:` A61, N64): primary taps 115 / 160 / 205 / 225 / 245 V on a
  selector, electrostatic screen; HT **280-0-280 V, 160 mA** (MOD issue 2, 14-6-63: "280V was
  285V"; A61 prints 285 V); 5 V 2 A (GZ34); 6.3 V 6 A (valve heaters). DPST mains switch, 3 A fuse;
  **no standby switch** (A61, N64). voxshowroom repeats "280 VAC, 160 ma ... 6.3 volt 6A ... 5 VAC
  2 amp".
- Replacement PTs: Hammond **290NX** (`hammond_290NX_pt.pdf`, web:
  https://www.hammfg.com/files/parts/pdf/290NX.pdf; "VOX AC30 (60's Vintage Vertical)" per a
  retailer, web: https://nextgenguitars.ca/products/hammond-290nx-power-transformer.html; the
  sheet itself names no amp and is a 15-05-2026 redraw): 290-0-290 V at 265 mA; no-load at 240 V,
  60 Hz: 295.7 V a half (591.4 V RED-RED), 5.238 V, 6.667 V; DCR (20 C, +-20 %): HV RED-RED
  68.30 ohm, 5 V 0.060 ohm, 6.3 V 0.040 ohm, primary BLK-BRN 1.200 / BRN-BLU 0.250 / BLU-WHT 3.410
  / WHT-RED 0.690 / RED-GRY 0.350 ohm; exciting current 212 mA max. Tube Amp Doctor's "Mains
  transf. for Vox AC30 till 1969 supports GZ34": secondary 285-0-285 V, 6.3 V, 5 V; EI126; "the
  original PT with 5" lamination" (web:
  https://www.tubeampdoctor.com/en/mains-transf.-for-vox-ac30-till-1969-supports-gz34-rectifier).
  Pick: HT 280-0-280 V (`sch:`), winding resistance from 290NX's 68.3 ohm (provisional), the
  primary tap at 245 V for UK 240 V mains (provisional: the selector's position isn't drawn).
- Rectifier GZ34 (V10; plates pins 4, 6, cathode / heater pins 2, 8).
- Filter: **C39 16 uF 450 V** on the GZ34 (the reservoir; the OT centre tap), choke **CH1
  "10-20 HY. 100 MA."** (A61, N64, B64), **C40 16 uF 450 V** after it (the "dual 16 uf 450 volt
  filter cap (C39 and C40)", voxshowroom; Don Butler "dual 16uf @ 500v can"). C40's node is the
  **320 V rail** (N64, B64, TB65, RV65): the screens (through 100 ohm each), R10, R11 and the TB's
  10K.
  - R10 22K from 320 V to the **290 V** node, C4 8 uF: V1 (N64; DA74 22K, 8 MFD). Don Butler's
    "dual 8uf can in the pre-amp" is C4 / C8.
  - R11 22K from 320 V to V2's node, C8 8 uF (A61, N64). V2's node voltage isn't printed;
    derived from the printed 230 V plates and 1.17 mA tail: about 294 V.
  - The TB's own 10K / 32 uF (above).
  - The vibrato-tremolo's 32 uF C19 and its droppers: not traced (not on the TB path).
- Choke: JMI prints "10-20 HY, 100 MA" (no DCR). voxshowroom: "a 10 henry choke straddled by
  two 16 uf, 450 volt smoothing capacitors". EME68 prints "15H 100MA [1 or 2]50 ohm" (the first
  digits of the inductance and the DCR are not clearly legible at the scan's resolution; VSL71's
  label is illegible). Replacements: Tube Amp Doctor AC30D "Choke 100mA, 19H, 500 Ohms for almost
  all JMI Product and VOX Product AC30", lamination 3 in, stack 1 in (web:
  https://www.tubeampdoctor.com/en/choke-100-ma-19-h-vox-ac-30); Hammond **194E** 30 H +-15 % at
  50 V 60 Hz 100 mA DC, DCR 517.2 ohm +-15 % (`hammond_194E_choke.pdf`; retailers disagree on
  whether it is Hammond's "AC30 vintage" or "reissue" choke: Parts Connexion says "original VOX
  AC30 reissue units"); Hammond **194D** 5 H at 150 mA, 107.2 ohm (`hammond_194D_choke.pdf`, the
  reissue's). **Pick:** 15 H at 100 mA (provisional: the middle of JMI's printed 10-20 H, which
  EME68 also prints), DCR 300 ohm (provisional: between EME68's 150 / 250 ohm reading and TAD's
  500 ohm; a genome range 150-520 ohm).
- Heaters: 6.3 V 6 A winding, all valves (the TB valve's "connect heaters to V.2", OS/010).

## Published voltages

All on N64 (OS/065 issue 4) and TB65 (OS/010 issue 3); no mains voltage is stated on either.

| Point | Volts | Source |
|---|---|---|
| C40 / screen rail ("HT") | 320 | N64 (top rail), TB65 ("XT 320V" at C), RV65, OS13 |
| V1 node (C4) | 290 | N64 |
| V1 plates (pins 1, 6) | 170, 170 | N64 |
| V1 cathode | 1.6 | N64 |
| V2 plates (pins 1, 6) | 230, 230 | N64 |
| V2 cathode / tail junction | 56.5 / 55 | N64 |
| TB node | 290 | TB65, OS13 |
| TB gain stage plate / cathode | 180 / 1.65 | TB65, OS13 |
| TB cathode follower cathode | 180 | TB65 |
| EL84 cathodes | 10 quiescent, 12.5 "at 30 watts" | N64 (also A61's text, DA74) |

- Not printed: the reservoir (C39, the EL84 anodes' supply). Derived (provisional): 320 V plus
  the choke's drop at the screen + preamp current (some 30-40 mA; 5-15 V over 150-500 ohm), so
  about 330-335 V at the anodes, about 320-325 V anode to cathode at idle. Forum figures seen
  only in a search summary (unverified): "Plate voltage is 335 and 333 volts. Cathode is 10
  volts", and one GZ34 amp at 312 V (web:
  https://music-electronics-forum.com/forum/amplification/guitar-amps/maintenance-troubleshooting-repair/50071-?p=765448;
  web: https://thefretboard.co.uk/discussion/comment/3305622/). The AC30 runs past the EL84's
  limiting values (Mullard D3: Va max 300 V, pa max 12 W): about 45 mA x 320 V = 14 W anode
  dissipation per valve at idle (derived from the printed 10 V / 50 ohm; screen current
  subtracted roughly, Mullard D1's 5.5 mA at 250 V).
- Calibration pick: the HT winding and the choke DCR set so that C40 is 320 V and the EL84
  cathodes 10 V at the drawing's idle (both `sch:`).

## Year-to-year differences, summarized

- Before 8-5-61 (MOD): R4 2.2K, R5 / R6 100K, R7 / R9 270K, C2 / C5 / C6 / C7 / C9 .01; R74 then
  added (150K across C3), C16 deleted, C41 changed.
- c.1961-62 (A61, serials ~4600-5500): the 8-5-61 values, capacitors .05 / .005 (WIMA Tropydur),
  R24 80 ohm 5 W, HT 285-0-285 V, R74 150K.
- Issue 2, 14-6-63: R74 deleted, **R24 80 -> 50 ohm**, fuse modified, **HT 285 -> 280 V**, the
  Top Boost note added; .05 / .005 silently became .047 / .0047. Autumn 1963: Woden's new mains
  transformer 72318 (suspected HT change, the site's surmise). Late summer 1964: Woden's
  simplified transformers (76852 / 76853 / 76854).
- Top Boost (OS/010): drawn December 1961 (Super Twins first, then Twins; kits from 1963); issue 1
  changed a .03 to .022 uF; issue 2 (June 1963) printed HT 230 V (a slip); issue 3 (Feb 1965)
  voltages and pins. Integrated in the copper panel from late 1963 (Westrex, components dated
  June-August 1963), no JMI drawing.
- Treble / Bass models (T64 / B64, Sep 1964) against Normal: Treble C5 / C7 .01, C6 / C9 .047, C10
  .0022, a different V1 cathode circuit (a 1.5K with a 0.1 uF drawn at the Brilliant side; not
  traced) and 330K / 220 pF at the volumes; Bass C3 1000 pF, C2 .1,
  C10 .01, C5 / C7 .047, C6 / C9 .15. Which voicing a copper-panel TB chassis was built on isn't
  documented; OS/010 names the Normal (A/026). Pick Normal.
- Later integrated drawings (EME68, VSL71, OS13, DA74): the TB first stage's cathode bypass gone
  (EME68 marks it "only on the original drawing"); treble cap 47 pF in EME68 / VSL71 (50 pF in
  DA74); volumes 470K (EME68); DA74 silicon BY133 rectifiers with 47 ohm and 32 uF caps.
- 1990s reissue (RX94): A1M treble / bass, A470K volumes, A220K cut with 4N7, 100N PI couplings,
  47 pF treble cap, cathode 2 x 100 ohm 5 W with 220 uF, 47 uF + 22 uF filter, choke 292-767, OT
  784-413, two 8 ohm Celestion T4437 in series. Not our amp.
- **Picks:** OS/065 issue 4 + OS/010 issue 3 throughout, with the TB gain stage bypassed (25 uF),
  50 pF, .022 / .022, R24 50 ohm, HT 280-0-280.

## Speakers: two Celestion G12 T530 "Blue" (alnico, 15 W)

- History (voxac30.org.uk, web: https://www.voxac30.org.uk/vox_ac30_celestion_blue.html): in
  Celestion's "T Numbers" book the T530 is "G12 - As CT.3757. Sprayed Oyster. Fitted with cone
  H.1668", "Sprayed Oyster" later overwritten "Blue"; the blue version appears between late
  November 1960 and mid January 1961; cones from RIC and Pulsonic. Impedance per unit is not
  stated there.
- Wiring: voxac30.org.uk documents 15 ohm pairs wired in parallel for 8 ohm and 8 ohm pairs in
  series for 16 ohm in AC30/4s (web: https://www.voxac30.org.uk/vox_ac30_speakers.html), and 15 ohm
  15-inch pairs in parallel "for a total of 8 ohms" in AC30Xs. Pick: **two 15 ohm T530s in
  parallel on the 8 ohm tap** (provisional: the period pattern for 15 ohm drivers; JMI prints no
  speaker wiring and Celestion's Blue comes in 8 and 15 ohm).
- Celestion's current Blue (its recreation of the T530) - `celestion_blue_current.pdf` (web:
  https://celestion.com/productpdf.php?id=896) and `celestion_blue_2019.pdf` (web:
  https://cf3.zzounds.com/media/Spec_Sheet-5077c09b6f4f4da47e61a0dc28110cc4.pdf, a 2019 Celestion
  sheet): 15 W; 8 or 15 ohm; **Fs 75 Hz; Re 6.4 / 11.8 ohm**; **sensitivity 100 dB** (conditions
  not stated); voice coil 44.5 mm (1.75 in) round copper; alnico; frequency range 75-5000 Hz;
  pressed steel; diameter 309 mm, cut-out 283 mm, magnet structure 128 mm, overall depth 165 mm,
  4.2 kg. "In its original incarnation as the G12 T530 ... it was the Blue version, fitted as
  standard into Vox AC30 amps". The 8 ohm frequency response (20 Hz-20 kHz) is a **raster image**
  in both (886 x 367 px in the current sheet, 398 x 198 px in 2019's), not vector paths: digitizing
  it is a pixel job. No impedance curve. Celestion's 2015 guitar speaker catalogue (p. 8) repeats the
  same figures (web:
  https://www.toutlehautparleur.com/media/catalog/product/datasheet/celestion/Guitar_Speaker_Catalogue.pdf,
  not copied).
- Thiele-Small parameters: none published for the Blue (searched; Celestion publishes Fs and Re
  only). The nearest measured relative is the Heritage G12H(55) Test Bench in
  `../marshall_1987/voicecoil_2015-02_g12h55_testbench.pdf` (Sd 0.0543 m^2 for the same 12 in
  frame and cone diameter). Provisional, to be fitted to the response curve as `P12R@1` was: Le,
  Qms, Qes, Vas, BL, Mms, Cms (Sd from the G12H(55): provisional: model knowledge that the frame
  and cone diameter are shared).

## Cabinet: AC30 Twin combo, open back

- Construction (voxac30.org.uk, web: https://www.voxac30.org.uk/vox_ac30_cabinets.html): baffles
  3/4 in; top 3/4 in; sides and bottom 1/2 in, thickened to 3/4 in at the front from mid 1962;
  back panels 3/8 in ply, a back board pencilled "JENNINGS AC. 30. BACKS. 26 3/16" x 8" x 3/8"
  PLY"; birch ply until late 1963, then Gla-Rev chipboard baffles (1964). The back is open: split
  boards with the chassis on a slider board above the speakers.
- Outer dimensions: not found for a 1960s Twin. The hand-wired reissue AC30HW2X (Vox's layout of
  the 1960s cabinet): 705 x 550 x 260 mm (W x H x D), 32 kg (the AC30HW2X manual, web:
  https://www.manualslib.de/manual/1037689/Vox-Amplification-Ac30Hw2X.html, seen in a search
  summary only). Provisional: 705 x 550 x 260 mm outside, open back with the back boards'
  openings as the leak.

## EL84 data

- **Mullard** EL84 (`data/datasheets/sources/mullard_el84.pdf`, 22 pages, web:
  https://frank.pocnet.net/sheets/129/e/EL84.pdf; sha256 below). Page map (PDF page = sheet):
  - p. 1 = D1 (Jan 1964): pentode Va 250, Vg2 250, Ia 48 mA, Ig2 5.5 mA, Vg1 -7.3 V, gm 11.3
    mA/V, ra 38 kOhm, mu g1-g2 19; triode-connected Va 250, Ia 34 mA, Vg1 -9.0, gm 10, ra 2.0k,
    mu 19.5; heater 6.3 V 760 mA; cin 10.8 pF, cout 6.5 pF, ca-g1 < 0.5 pF.
  - p. 2 = D2 (Jan 1964): push-pull pairs, e.g. Va = Vg2 = 300 V, Rk 270 ohm a valve, Ra-a 8 kOhm,
    Ia(0) 2 x 36 mA, Ig2(0) 2 x 4.0 mA, Pout 17 W at 4 % (pentode); distributed-load and triode
    tables.
  - p. 3 = D3 (Feb 1961): continuous-sine-drive conditions and **limiting values**: Va(b) 550 V,
    Va 300 V, pa 12 W, Vg2(b) 550 V, Vg2 300 V, pg2 2 W, Ik 65 mA, -Vg 100 V, Rg1-k 300 kOhm,
    Vh-k 100 V.
  - p. 4 = D4: base and dimensions.
  - p. 5 = C1 (drawing 6895): Ia, Ig2, gm and ra against Vg1 at **Va = Vg2 = 250 V** (Vg1 0 to
    -15 V).
  - p. 6 = C2 (drawing 6896): **Ia against Va, Vg2 = 250 V**, Vg1 = 0, -2, -4, -6, -8, -10 V; Va
    0-450 V, Ia 0-160 mA; pa = 12 W hyperbola.
  - p. 7 = C3: screen current against Va, Vg2 = 250 V (caption read on a thumbnail: verify).
  - p. 8 = C4 (drawing 6893): **Ia against Va, Vg2 = 300 V**, Vg1 = 0, -2, -4, -6, -8, -10 V; Va
    0-450 V.
  - p. 9 = C5: screen current against Va, Vg2 = 300 V (thumbnail: verify).
  - p. 10 = C6: triode connection, mu, gm, ra against cathode current; pp. 11-21 = performance
    curves (single valve 4.5k / 5.2k loads, push-pull, distributed load, triode); p. 22 (Aug 1964):
    triode-connected Ia against Va.
- **Philips** EL84 (`data/datasheets/sources/philips_el84.pdf`, 21 pages, web:
  https://frank.pocnet.net/sheets/030/e/EL84.pdf; the last page indexes the sheets' dates,
  1953-11-11 to 1957-10-10):
  - pp. 1-6: tables (characteristics, class A / B, triode, limiting values).
  - p. 7 = sheet A (3.3.1955): Ia and Ig2 against Vg1 at Va 250 / Vg2 250 V and Va 250 / **Vg2
    210 V**.
  - p. 8 = sheet B: Ia against Va at **Vg2 = 250 V**, Vg1 = 0 to -10 V in 2 V steps, Va 0-300 V.
  - p. 9 = sheet C (10.10.1957): Ia against Va at **Vg2 = 300 V, Vg1 = 0 to -14 V in 1 V steps,
    Va 0-600 V, Ia 0-200 mA**: the densest family, the widest Va range and the nearest screen
    voltage to the AC30's (~310 V screen to cathode). Fit the pentode here.
  - p. 10 = sheet D: triode connection, Ia against Va, Vg1 0 to -15 V in 2.5 V steps.
  - pp. 11-19 = sheets E-M, performance curves.
  - Another Philips EL84 scan (web: https://frank.pocnet.net/sheets/010/e/EL84.pdf, 15 pages) and
    Brimar, Mazda, Ei, JJ and Tesla sheets are on the same site (not copied).
- **Published model parameters:** Norman Koren's Table 1 has **no EL84** (its pentodes are
  6L6GC, 6550, EL34, KT88; checked in the errata mirror, web:
  https://wdv.com/Electronics/Software/SpiceVacuumTubes/errata.txt, and his parameter page, web:
  https://www.normankoren.com/Audio/Tube_params.html; his libraries Tube.lib / Tube97.lib on the
  mirror have no EL84 either). Ayumi Nakabayashi's generic pentode model has an EL84 file
  (`EL84_AN`, version 3.10, 2003-2008), quoted in a diyAudio post (web:
  https://www.diyaudio.com/community/goto/post?id=4042909); the page is bot-blocked and its
  parameters weren't retrieved. An unattributed gist has a triode-connected `6BQ5_EL84_T` (mu 18.8,
  ex 1.5, kg1 540, kp 165, kvb 174; web: https://gist.github.com/chanmix51/6947361): no author or
  data source, not usable as a citation. So the EL84 is to be fitted by us to the sheets above.

## Not found / open

- The JMI drawing of the integrated copper-panel Top Boost (none known); the TB first stage's
  bypass in those chassis (period drawing: yes; 1969-74 drawings: no).
- Any period winding data for the Haddon / Albion / Woden output transformer, mains transformer
  or choke (impedance only: "4K"; choke "10-20 HY 100 MA"; HT "280V 160 m/A").
- The reservoir / anode voltage (not printed); any period measurement with its mains voltage.
- Thiele-Small parameters and an impedance curve for the T530 or its recreation; the T530's
  original impedance; the 1960s Twin cabinet's outer dimensions.
- Pot taper laws beyond "LOG" (500K volumes, 1M treble / bass, 250K cut).

## File hashes (sha256, downloaded 2026-11-12)

```
4a46836b589662249f7de517112003ac4c0f8273d87369a3f8485c81b391dc92  celestion_blue_2019.pdf
e44ca77a9b6861245cc65b77c919c533a21486cfce7d48cde5920defed419111  celestion_blue_current.pdf
a526c9ec0cdbd6c0454a2490a0758c2232bd70e29aa59c8f9a22d0722a2a04b0  dallas_ac30tb_sc-v-1313_jun1974.jpg
044d13be1b08ffa3f8da7fca6c356d496032bd9b3505f8696c4c8453e94db052  eme_ac30-36_1968.jpg
510d27d6e30c990b97bd2e92ca8318377cac21a5bc89bd7782833bcf6d53e3e7  hammond_1750T_ot.pdf
5199c5210e565ca5f325a577c6fde2cdf920a58fbe08cae53626d33914c22451  hammond_1750V_ot.pdf
1affa8920b5d65aaa722a8a28fd01635a9864e2ff46267c8d6c7dfdd301cbd03  hammond_194D_choke.pdf
1df5122c700b2bc8d8a7d4a75ca404b01cbceaf33806f486bcc5066861f601b3  hammond_194E_choke.pdf
80c176d28df316321762445a60543dbb0515a978eae7a38ec5cc95a38a37b952  hammond_290NX_pt.pdf
b3e09a04653b729f72c7ad1d722bfee29d6deac10ea3ff0323408df96a66b5a4  jmi_ac30-6_bass_os057_sep1964.jpg
460987db8528c351a46b1f75c0e87a18078c80c7b781dd821334170cb3b45afd  jmi_ac30-6_normal_c1961-62.jpg
dc2e2478d0a7bc6568f1855d289ef16423df49b3879977da954cbda89e022e0b  jmi_ac30-6_normal_os065_iss4_sep1964_drtube.gif
109938416f62043cf024fc43b07879f34a45145d6d17df034a0eea54de6f440e  jmi_ac30-6_normal_os065_iss4_sep1964_voxac30.jpg
457d1d1b86a1f65e591aac7b7abe8cd230a61079c0fd7b3392b9e9079b5a8523  jmi_ac30-6_topboost_os010_iss2_jun1963_wallet_thumb.jpg
55126e115737cecdc53c1fdc92a62a52ca6a3e26e288c3be2333b599949cd97b  jmi_ac30-6_topboost_os010_iss3_feb1965.gif
232124641daac619b7d784a742d61ebe3c40a40351117f5afb8bedd6770d5c1b  jmi_ac30-6_treble_os056_sep1964.jpg
baad25f69287caf960a4be1c6c77e981fe8e5fcd40e7d0a9cddafb711c22dce8  jmi_os065_modifications_panel.jpg
d7a65a8e9247a29119b53ed9705302f3af40b80047b17877b82eba88bdbe7c4c  jmi_reverb_addon_os075_jan1965.jpg
65620d97af14c7c2515bd426019209a04ec10be2199c466f5d860fe4620fc32f  mercury_VXO-30H_ot_wiring.pdf
3cdeed0abf88bc07d3ea68ba11d4b7466e909cf3bb514320fb4e7f352f7c20b1  mercury_VXO-30M_ot_wiring.pdf
f8d190b6783bbdb9866819ed124d2458ee5808ff666db8f2e4fde1b6baa66117  vox_ac30tb_reissue_ac30-60-02_iss5_1994.pdf
15726268fbe9dad362a7f2165d30262b6e9b332f5dd85afbeda8df56f702f005  vsl_ac30-6tb_feb1971.jpg
55deb931af7a1ff94576d7ea5098bfce8e77fef57c7007c32c782ed2c000919b  vsl_ac30tb_os013_1969_detail_thumb.jpg

../../datasheets/sources/:
0b2aa07751925e9ff1ef4c55a774d58b5ea7066e3a8d14c95b4327aec5d935f6  mullard_el84.pdf
904e635333f1b39e14289479a3fd5d520e6fa539c2566955bb2f8e6346a069d9  philips_el84.pdf
```

# Fairchild 670 schematic crops

Crops of drawing A-96039, "670 Dual Limiter Schematic", from the Fairchild 670
instruction manual (Fairchild Recording Equipment Corp., dated Dec 1959).

- Source: http://thehistoryofrecording.com/Manuals/Fairchild/Fairchild_670_stereo_limiting_amplifier_instructions_Schematics.pdf
- sha256 of the downloaded PDF: `0ede9ed8d1294ada7b3e05a6f8ef89e7487a7530a2c7a36481c5c297bac7c535`
  (24 MB, scanned images, not committed; the drawing is page 16 of 16)
- Rendered at 300 dpi and cropped on 2026-10-13. Values were read by eye.
- `rails*.png` added 2026-10-21 (300 dpi, grayscale) for the Phase 3 survey below.

| File | Shows |
|---|---|
| `audio_path.png` | AT101, T101, the four-triode 6386 banks, R103-R105 cathode network, C101/C102, T102, R107/R108/R111 |
| `sidechain_1.png` | T102 secondaries, R145-R150 pads, T103, R113-R119 threshold networks, 12AX7 (V105), 12BH7A (V106) |
| `sidechain_2.png` | 6973 pair (V107/V108), T104 with feedback winding, CR101-104 bridge, S102 time constant network, R142 ZERO |
| `psu_1.png`, `psu_2.png` | Rectifier, L301, C304-C306, EL34/6084/5651 regulator, bias supply |
| `notes.png` | Drawing notes, control list (AT101 input gain, R105 balance, R115 AC threshold, R117 DC threshold, R142 zero) |
| `rails_psu.png` | The six supply lines leaving the PSU along its top edge, into the right-hand corridor |
| `rails.png` | The right-hand corridor: the six lines rising to both channels, and their branches |
| `rails_top.png` | Channel 1's top band: which line feeds R116/R118/R120, R126, T104's centre tap and the 6973 screens |

`config/circuits/fairchild_670.yaml` cites these values as `sch:` (printed on the
drawing) or `sch-interp:` (wiring read off the scan, where it isn't certain).

## Supply rails (Phase 3 survey, 2026-10-21)

The rails were traced on the full drawing rendered at 200-300 dpi, across the
crops. Six lines leave the PSU along its top edge (`rails_psu.png`) and rise
in the right-hand corridor (`rails.png`), nested, so the top PSU line is the
innermost riser. The thick line beside them is ground. At channel 1's top
band (`rails_top.png`) and the band below channel 1 they branch off as follows:

| Line (PSU end) | Approx. voltage | Feeds (channel 1; channel 2 the same) |
|---|---|---|
| EL34 anode, "(420V TO 450V)" after L301 | unregulated, 420-450 V printed | R126/R127 (12BH7 plate loads), T104 centre tap (6973 plates), the EL34 anode, g2 and g3 (pins 3, 4, 1), R309 |
| EL34 cathode (pin 8), "(ADJ. TO 240 V.)" | 240 V regulated | R111 (T102 centre tap, 6386 plates), R116, R118, R120/R121 (12AX7), the regulator's dividers |
| C307B: tap of R315 27K / R316 100K | ~189 V unloaded | R132/R133 (6973 screens) |
| C303 (after L302) | -6.2 V (web, below) | the BALANCE pot wiper: the 6386 cathode return |
| C108 (bias supply; the designator repeats the sidechain's C108) | ~-18.6 V (calc., below) | top of R142 (ZERO); its other end is ground |
| R303 top, "-13V. TO -14.5V." | -13 to -14.5 V printed | midpoint of R130/R131: the 6973 grid-leak return |

**Main supply (sch, psu_1).** T302 (no voltages printed): centre-tapped HV
winding (R, R-Y, R) into V301, a 5 V 1.9 A rectifier filament winding, and
6.3 V heater windings. V301 is printed "6234". It is the GZ34: the manual's
tube complement (p.5) lists "1-GZ34 (5V4)" and the chassis photo (p.2)
labels it "GZ34 (5AR4)". Then C304 4 uF 440 VAC (capacitor input), L301
(no value printed), C305 + C306 140 uF 350 V in series with R305/R306 100K
1W balancing resistors, which is the unregulated rail.

The HV centre tap and C304's return go to the 5651's pin 2. Its pin 7
(cathode) is grounded, so the CT returns through the tube's internal pin 2-7
jumper (sch-interp: a safety interlock, and electrically the CT is ground).

The regulator: V302 EL34 triode-connected as the series pass tube (anode
pins 3, 4, 1 on the unregulated rail, cathode pin 8 the 240 V output), with
R309 470K 1W from its anode to its grid (pin 5). V303 6084 (pentode) is the
error amplifier: anode (pin 6) on the EL34 grid; pins 2, 3, 8 tied (cathode,
suppressor, shield); screen (pin 1) from R310 100K off 240 V; R311 270K from
the screen to the 5651 anode; grid (pin 9) through a shielded lead (shield
grounded; no component) to the wiper of R313 250K (B+ ADJ). R313 sits in the
divider R312 150K 1W (from 240 V) / R313 / R314 100K 1W (to ground). V304
5651 reference: anode (pin 5) on the 6084 cathode, cathode (pin 7) to ground.
C307A 80 uF 450 V is on the 240 V output, and the R315 27K 1W / R316 100K 1W
divider has C307B 60 uF 350 V on its tap. T304 (heaters of V302/V303) has its
centre tap on R307/R308 100K 1W across 240 V (heater elevation; a 1.2 mA load).
The manual (p.7) says to adjust R313 only if pin 8 of V302 deviates from 240 V.

**Bias supply (sch, psu_2).** T301 (no voltage printed) into GR301 (a
selenium bridge) with "+" to ground. From "-": C302 250 uF 50 V, then two
branches.

- L302 (no value) to C303 1000 uF 15 V. The C303 riser crosses the
  bridge-to-R301 line without a junction dot (zoomed on psu_2), so L302 is
  its own branch.
- R301 1K 1W from C302 to C108 250 uF 50 V, then R302 10K 5% to C308 25 uF
  25 V and R303 27K 5% to ground.

**Checks against published measurements (web).**

- web: https://groupdiy.com/threads/fairchild-670-questions.32169/ (Dave P,
  measured on his build, 2009): "about 120mA running from ground to -6.2V",
  "the ground end of the cathode resistors is just stuck on this flow", about
  26 mA through each 680 ohm, -2.5 V at the 680s' ground end. So the 6386
  cathode current of both channels flows through L302, whose DC resistance
  sets C303's voltage. The figure -6.2 V also appears as a Drip 670 check
  value (search result snippets, 2026-10-21).
- web: https://www.dafx12.york.ac.uk/papers/dafx12_submission_9.pdf
  (Raffensperger, DAFx-12) models the stage with a -7.2 V grid bias from
  ZERO, and the balance network as -3.1 V behind 705 ohm per side. Our 6386
  fit gives about 21 mA per bank for that bias (scratch calculation,
  2026-10-21), against the 26 mA measured above.
- Consistency of the drawing (calc.): with both channels' ZERO pots
  (2 x 2500 ohm) and R302 + R303 on C108, the printed -13 to -14.5 V at R303
  needs C302 at about -32.6 to -36.3 V. Dave P's design figure in the same
  thread is 34 V. A Sowter replacement bias winding of 26.8 V rms (below)
  gives about that after the selenium drop and ripple. Then L302's DC
  resistance is about (34 - 6.2) V / ~0.11 A ~ 250 ohm.

**Replacement-part specs (web, not the originals).** Sowter, vintage
compressor transformers A to K:
https://www.sowter.co.uk/acatalog/VINTAGE-COMPRESSOR-TRANSFORMERS-A-to-K.html

| Part | Sowter spec |
|---|---|
| T302 (0526) | 375-0-375 V at 200 mA, 6.3 V CT at 5 A, 5.0 V at 2 A (https://www.sowter.co.uk/specs/0526.htm) |
| T301 (0531) | 26.8 V tapped at 24 V; "26.8V should be used if the original Selenium bridge rectifier is used" (https://www.sowter.co.uk/specs/0531.htm) |
| L301 (1172) | 10 H, 200 mA, 71 ohms |
| L302 (1221) | 5 H at 200 mA, 85 ohms. A GroupDIY search snippet says Drip's bias choke is 1.5 H. 85 ohm doesn't give -6.2 V at C303 with the current above, so the original's resistance is a genome parameter |
| T103 (8345E) | 600 ohms/170k ohms, ratio 17+17:1+1. This bears on the slice's provisional T103 ratio |

**Legible vs genome parameters.**

- Printed (sch): R301-R316, C302-C308, C108 (bias), C304-C307B with ratings,
  the tube types, "(420V TO 450V)", "(ADJ. TO 240 V.)", "-13V. TO -14.5V.".
  Mains 117 V, 50-60 cycles, stable from 100 to 127 V (manual p.4).
- Not printed, so they become genome parameters (bounded; provisional or web
  sourced):
  - T302's HV voltage, winding resistance and leakage;
  - T301's voltage and resistance;
  - L301 and L302 inductance and DC resistance;
  - the selenium cells' characteristic;
  - the regulator tubes' spreads (EL34, 6084, and the 5651's burning voltage);
  - electrolytic tolerance and ESR.
- R313 (B+ ADJ) is a factory trim set for 240 V. It is modeled as a trim
  position, like ZERO and BALANCE.

**Not modeled (no effect on the audio path).** The heater windings and loads
(T302's 6.3 V windings, T303, a constant-voltage transformer with C301 for
the 6386 heaters, T304), the pilot lamp, S302, F301.

## Open questions

- Resolved 2026-10-21 (rails above): the 12BH7 grid leaks (R122/R123) and
  cathode resistors (R124/R125) return to ground. Their line ends at the 6973
  cathodes and R134/R135, which go to ground; it breaks before the 12AX7
  cathode node (zoomed on sidechain_1). The 6973 grid leaks return to the
  bias supply's -13 to -14.5 V end. The 12BH7 plate loads are on the
  unregulated rail, not 240 V.
- How the dual-gang BALANCE pot's two wipers connect. Modeled as one pot with
  its wiper on the cathode return (now C303, not ground).
- C114, the trimmer between the grid lines, has no printed value and is omitted.
- The AC THRESHOLD pots (R115A/B) are tapped pots with R113/R114 "hanging off
  the taps to ground" (web: https://groupdiy.com/threads/whats-this-symbol-in-the-fairchild-670-diagram.35361/,
  Walrus, reading the original manual), not resistors in series below the
  pots as the slice has them. The same thread says R115B's "180K" reads as
  100K on some prints.
- A search snippet (2026-10-21) reports a builder's note that one resistor on
  the 240 V dividers "reads 27K where the redrawn schematic shows 100K",
  possibly R315. Unverified: the drawing's 27K is used. It sets the 6973
  screen supply.
- What the meter's ZERO position measures (S101; ZERO is adjusted for a
  meter reading of zero, manual p.7). Decoding it would give ZERO a physical
  calibration criterion.

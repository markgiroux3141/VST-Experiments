# Wurlitzer Side Man (Model 5000) sources

The drum machine of docs/DRUM_PLAN.md's D2. Values in `config/circuits/sideman_bd.yaml` cite
these as `dwg 501648` / `dwg 501649` (printed on Wurlitzer's drawings) or the patent. The
service documents are commercial: cite them, don't copy them into the repo (no scans are
committed here).

## The service schematics

"Wurlitzer 5000 Side Man, Tube/Motorized Rhythm Unit, Schematic", MusicParts.com document
51329 (2006 distribution of Wurlitzer's 1960 drawings), 10 PDF pages:

| PDF page | Shows |
|---|---|
| 3 | The controls (VOLUME 0-10, RHYTHM START / STOP, the pattern dial, the push buttons, tempo 36-195) |
| 4 | Block diagram: the tone generators on ground-out key lines, the pattern selector on the tempo wheel, preamp, amplifier, speaker |
| 5-6 | Schematic 501648 "Generator", issue 1, 5/1/60, serial 320000 on: every voice (bass drum V100-A, tom toms V100-B / V101-A, temple blocks, wood block, clave, the shimmer generator, maracas, brush, the 6BA6 cymbal, the 6C4 noise generator), the 6AV6 preamp, the tempo light; typical voltages |
| 7-8 | Schematic 501649 "Amplifier": 12AX7, push-pull 6BQ5s, T2 into 3.2 / 3.2 / 8 ohm speakers; the supply (T1, D1-D4, CH1 26 H; +305 V, -22 V, -42 V lines) |
| 9-10 | Rhythm switching: SW 401's 24 wafers, the contact plate, the switching schedule |

- Source: web: https://www.smemmusic.ch/sites/default/files/2025-12/wurlitzer_side-man_service_manual.pdf
  (downloaded 2026-11-04)
- sha256 of the PDF: `e41c884aeb8814f1c6bdcc06d27bd97d1f3d8a02260862af8f3f21c2f1c6d569`
  (624 kB, scanned 1-bit pages)
- Read at 400 dpi (pymupdf) on 2026-11-04.

### The bass drum as drawn (V100-A, 12AX7)

R107 270K plate load from B+; plate +174 V; C104 .0016 plate to node A; R103 470K A to C;
R102 100K C to ground; C102 .0016 A to B; R104 470K B to ground; C103 .0016 B to the grid;
the grid leak 680K (printed "R104" a second time); cathode +1.5 V on R106 5K, whose wiper is
grounded (the cathode sees the track between them); C101 .068 C to the key junction J; R100
680K J to the -22 V line; C100 .047 J to ground; R101 10K J to the key line K1. Output: R108
680K plate to O, C105 .01 O to ground, C106 .047 and R109 470K to the collector line, which
R213 10K terminates at the preamp: C170 .068 into V107 (6AV6; R214 270K grid, R215 1.5K
cathode +2.2 V, R217 100K plate +205 V, R216 10K and C168 20/300 from B+), C171 .18 to R400
100K (VOLUME, on the control panel), its wiper by cable to the amplifier's input (R1 1M).

The tom toms are the same circuit: Tom I 750 pF ladder and 1.5M / .0047 / .001 output tap,
R112 47K, R110 330K to the -22 V line, plate +170 V, cathode +1.45 V; Tom II 560 pF, its
grid leak R125 470K, R129 2.7M to the collector line, plate +150 V, cathode +1.25 V. The voltages are "typical values" (501649's note).

## The patents

- US 3,358,069 (the tone generators; "generator 10" is the bass drum, values printed as
  "illustrative": the same as 501648's), web: https://patents.google.com/patent/US3358069
- US 3,207,835 (the commutator, the tempo drive, the pattern switching), web:
  https://patents.google.com/patent/US3207835

## Audio

A restored 1959 unit: Circles Drum Samples, web: https://vimeo.com/509979954 (no published
measurements were found).

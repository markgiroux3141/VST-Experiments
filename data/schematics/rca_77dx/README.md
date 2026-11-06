# RCA 77-DX sources

The chains build-out's WP7 (docs/CHAINS_PLAN.md), found 2026-11-05: the RCA Type 77-DX
polydirectional ribbon microphone (MI-4045-F broadcast, MI-11006-C television; c. 1954-
the 1970s), not the 77-A / B / C or the 77-D. Values that go into its component and circuit
cite these as `ib:` (the coutant.org instruction book), `ib2:` (IB-24884-2, the other
edition) or `web:`. Transcribed 2026-11-05; recheck a value against its image when it goes
into a file.

The PDFs and photos are not committed (a copy is kept in the git-ignored
`cache/sources/rca_77dx/`). Their URLs, sizes and sha256 are below. The PNGs here are
16-level gray renders of their pages.

## ib: RCA, Instructions for the Type 77-DX Polydirectional Microphone (coutant.org)

The eight-page instruction book coutant.org scanned ("circa 1955" on its page), images only
(1273 x 1630 per page, no text layer). web: https://www.coutant.org/rca77dx/77dxinst.pdf
(1,612,273 bytes, sha256 `5d452d13520c8217315175f98bc69e7db5a00c5b051cbf763bd24679a0718938`);
linked from web: https://coutant.org/rca77dx/index.html.

- `ib_fig2_schematic.png` (p 3): Figure 2, "Schematic and Connection Diagram", drawing
  M-149778-1 (MI-4045-E and MI-4045-F, MI-11006-B and MI-11006-C). The ribbon (its leads
  ENAMEL / FORMEX) on the transformer's primary; the secondary's leads GREEN, RED, BLACK,
  YELLOW, BLUE to the terminal strip; the reactor (its own can) on the M / V1 / V2 switch.
  The cable table: 150 ohm GRN + RED to the two outer posts, BLK free; 30 ohm BLK + RED;
  250 ohm BLK + RED with GRN on the ground (read the image again before wiring it in).
- `ib_fig3_patterns.png` (p 4): Figure 3, "Directional Patterns" (T-163143): UNI-, BI-,
  NON-DIRECTIONAL, L-1, L-2, L-3, each in dB (0 to -20) at several frequencies (400 or
  1000 cps, 4000, 10,000 cps; 50 cps on some). L-1 is a cardioid with a small rear lobe
  (between U and B), L-2 a wider one with a rear lobe ~-5 dB, L-3 a narrower one with a
  rear lobe ~-12 dB (between N and U): read them on the image.
- `ib_fig4_response.png` (p 5): Figure 4, "Frequency Response Curves" (472178-0), "OPEN
  CIRCUIT RESPONSE OF A TYPICAL TYPE 77DX MICROPHONE", 60-15,000 cps, for the
  UNIDIRECTIONAL, BIDIRECTIONAL and NONDIRECTIONAL positions, each with M, V1, V2
  (digitized from ib2's sharper copy: see "Digitized" below). Read roughly here: U, M flat within ~1 dB from 60 Hz to ~6 kHz, a rise to
  ~+2 dB at ~7 kHz, then -5 at 15 kHz; B, M rising from -3 at 60 Hz to ~+2 at 300-500 Hz,
  a dip near 6 kHz, a peak ~+1 at ~9 kHz, -10 at 15 kHz; N, M flat to ~2 kHz, a broad rise
  to ~+4 dB at 5-6 kHz, -3 at 15 kHz. V1 and V2 cut the bass below ~300 / ~500 Hz.
- `ib_fig5_parts.png` (p 6): Figure 5, the parts location diagram of MI-4045-F (C-176350-3):
  the ribbon #45385 between its clamps at the top, the ACOUSTIC LINE ASSEMBLY #93981A (the
  body below the ribbon: the labyrinth), the transformer #215992 and the reactor #207115 in
  the lower shell, the SHUTTER #50910 and its INDICATOR #56702 / PLATE #50909 in the motor
  assembly's rear view.

The text (p 1-2): "Instead of being open on both sides as in the conventional velocity
microphone, the ribbon element in this microphone is coupled to an acoustic labyrinth which
forms the body portion of the microphone. The tube connecting the back of the ribbon to the
labyrinth is slotted directly behind the ribbon and fitted with an adjustable shutter to
secure various areas of opening. When the opening is completely closed, the microphone
operates as a non-directional pressure microphone; at the wide-open position the microphone
becomes bi-directional. With the proper size opening the pattern becomes a cardioid by
virtue of the phase shift which occurs. Openings smaller or larger than this critical size
produce directional patterns with various sized rear lobes." "Stops are provided on the
continuously-variable pattern selector at the six marked positions, although the shutter may
be set at any intermediate position." "The voice positions connect a reactor across the
entire secondary or part of the secondary of the output transformer." V1 "for distances down
to 1 foot", V2 "for still shorter distances"; N needs no bass cut "even for very small
distances". Phasing: "the red cable lead is electrically positive when the sound pressure on
the front of the microphone is in the positive half of the cycle."

## ib2: RCA IB-24884-2, Instructions for Polydirectional Microphone Type 77-DX (MI-4045-F, MI-11006-C)

RCA Engineering Products Division, Camden, a later edition with a text layer (13 pages; the
figures numbered one higher: Fig. 3 the schematic, Fig. 4 the patterns, Fig. 5 the
response). web: https://worldradiohistory.com/Archive-Catalogs/RCA/RCA-BCA-77-Mic.pdf
(520,204 bytes, sha256 `4bc60769ed32dd610928af12c60e637d93a7f414efa355844d021b7ab235821b`).

`ib24884_2_technical_data.png` (p 5), as printed:

| Item | Value |
|---|---|
| Output impedance | 250 ohms, may be changed to 30 or 150 ohms |
| Load impedance | Unloaded input transformer |
| Effective output level (all output connections), sound pressure 10 dynes/cm^2 | Bi-directional (B) -50 dbm, G_M -144 db; Uni-directional (U) -53 dbm, G_M -147 db; Non-directional (N) -56 dbm, G_M -150 db; L-1, L-2, L-3 between -50 and -53 dbm (G_M = RETMA rating) |
| Hum pick-up level | -128 dbm (hum field 1 x 10^-3 gauss) |
| Dimensions, weight | length 11-1/2 in, width 3-3/4 in, depth 2-1/2 in; 4-1/2 lb total, 3 lb less cable |
| Cable | MI-43-C, 3 conductor, shielded, 30 ft, no plug |

As for the 44-BX (data/schematics/rca_44bx/README.md), "effective output level" is the
RETMA's power into a matched load: at 250 ohm, -50 / -53 / -56 dBm are open-circuit EMFs of
3.16 / 2.24 / 1.58 mV/Pa (derived: E = sqrt(4 R P)).

`ib24884_2_parts_list.png` (p 12), as printed:

- "Reactor, iron core, impedance at 50 CPS, 0.5 v, 91 ohms, +7%, -5%; D.C. res. 28 ohms,
  round can" (97504): L = sqrt(91^2 - 28^2) / (2 pi 50) = 0.276 H at 50 Hz, 0.5 V
  (derived).
- "Transformer, microphone, tapped for 30, 150, 250 ohms, output impedances; turns ratio
  1:23.5 +-2%, round can" (97503).
- "Ribbon, microphone, corrigated aluminum foil, 2" lg. x .054 wide" (45385): 50.8 mm x
  1.37 mm (its thickness isn't printed).
- "Shutter, acoustic tube, .005 thick phos. bronze, cam shaped" (50910); "Plate, shutter
  pressure, .012 thick phos. bronze 2-1/16" lg. x 7/16" wide" (50909).
- "Switch, rotary, single circuit, 3 pos. screw driver slotted shaft, music-voice" (50915).

## The B sheet (coutant.org)

web: https://www.coutant.org/rca77dx/77bsheet.pdf (428,248 bytes, sha256
`440f6ff8f7d30280f2dc4b737a7dee6b07b4b076c517ca66f3520baf0b11d5ac`), RCA's two-page catalog
sheet; not read yet.

## Photos (coutant.org, the 77-DX's pages)

Not committed; in `cache/sources/rca_77dx/`: `77open.jpg` (the magnet), `u.jpg` (the
shutter at U), `wiring.jpg`, `freq77.jpg` / `direc77.jpg` (the curves again, 300 dpi crops:
559 x 938 and 581 x 939), `freqrespset.jpg` (the M / V1 / V2 selector), `77chart.gif`.

## Digitized (2026-11-05)

`scripts/digitize_rca_77dx.py` reads ib2's Figs. 4-5 on the PDF's own 1-bit masks (~262 dpi;
coutant's scan is ~150 dpi gray) into `data/datasheets/rca_77dx_response.csv` (U / B / N x M /
V1 / V2, 50 Hz-15 kHz, whole curves) and `rca_77dx_polar.csv` (key angles: each pattern's
curves at 90 and 180 degrees, B's 10 kHz rear lobe; the curves told by the labelled arrows);
provenance `data/datasheets/rca_77dx.provenance.yaml`. Read on the patterns: L-2 and L-1 lie
between U and B (their 90-degree levels -7.4 and -10.4 dB at 400-1000 cps against U's -5.9,
rear lobes -6.2 and -1.8 dB), L-3 between N and U (90 degrees -5.2 dB, N's -1.7; rear lobe
-7.2 at 400 cps), as ib's text says (corrected 2026-11-06: an earlier note had all three
between U and B). The shutter's order from closed to open: N, L-3, U, L-2, L-1, B.

## olson1944: H. F. Olson, "Polydirectional Microphone", Proc. I.R.E. 32, pp. 77-82 (Feb. 1944)

RCA Laboratories (written 1941; the Varacoustic, the 77-D's forerunner, "developed by L. J.
Anderson"). web: https://www.worldradiohistory.com/Archive-IRE/40s/IRE-1944-02.pdf (the whole
issue, 19,081,965 bytes, sha256 `46c4986f4436dbcaf97b8a8d928f5af7f43f3fd9b1767fe1d71650e69954d50b`;
the paper is PDF pp. 55-60, with a text layer; a copy in `cache/sources/rca_77dx/`).

- Fig. 1 / 2: "a single ribbon, the back of which is coupled to a damped folded pipe and an
  inertance in the form of an aperture"; "The entire one side of the ribbon is covered by the
  labyrinth connector. The connector, in turn, is coupled to a damped pipe or labyrinth. The
  type of directional characteristic is governed by the size of the aperture in the labyrinth
  connector."
- The acoustic circuit (his eqs. 6-8): the ribbon Z_A1 = r_A1 + j w M_1 (the air load's
  resistance r_AA and inertance M_A plus the ribbon's inertance M_R; the slit between ribbon and
  pole pieces, r_AS / M_S, "very large compared to" the ribbon's impedance, and the ribbon's
  compliance C_AR, its resonance below the audible range, both neglected) between the front
  pressure p1 and the node behind it; from that node the damped pipe, a pure resistance r_A3,
  and the aperture Z_A2 = r_A2 + j w M_2 to the pressure p2 at the aperture. The ribbon's
  volume current X = [p1 (Z_A2 + Z_A3) - p2 Z_A3] / (Z_A1 Z_A2 + Z_A1 Z_A3 + Z_A2 Z_A3).
  Aperture wide (Z_A2 = 0): the velocity microphone; closed (Z_A2 infinite): the pressure
  ribbon, X = p1 / (Z_A1 + Z_A3), resistance controlled by r_A3. "The values of the impedance
  can be determined from the mass and dimensions of the ribbon, the area of the damped pipe or
  labyrinth, and the diameter of the aperture" (no numbers printed).
- Measured (Fig. 6, the Varacoustic): nondirectional "independent of frequency up to 3000
  cycles", then up to 10 dB between 0 and 180 degrees (< 3 dB within 45); cardioid more than
  30 dB at 180 degrees from 100 to 4000 cycles, > 25 dB 40-100, > 20 dB 4-14 kHz.

## watts: L. M. Watts, "The Polyribbon Story" (L M Watts Technology, web archive)

A ribbon designer's account (web:
https://web.archive.org/web/20230329103029/http://lmwattstechnology.com/ via the Museum of
Microphones' PDF, https://res.cloudinary.com/museum-of-microphones/image/upload/v1787487118/ThePolyribbonStory_pt3n8g.pdf,
600,354 bytes, sha256 `28a09ae4df3178d72c82b634d48acdb751d28e977c58daec2b21422f807796e1`;
a copy in `cache/sources/rca_77dx/`). Not RCA's figures: a practitioner's, cite as
`web:` with care.

- The labyrinth is a transmission line used as the pressure ribbon's resistance: "The right
  loading for the ribbon was found to result in a pipe of 6-9 mm diameter"; "about a meter was
  the maximum practical length"; the open pipe's resonance suppressed "by stuffing the tube with
  fibrous sound absorbing media resulting in a lossy transmission line", which "gives the line a
  reactive impedance but does suppress reflections". In the 77 "created either as stacked
  spiral plates or a phenolic block drilled with many interconnected holes".
- "corners where the labyrinth turned around abruptly still caused some pretty bad resonances,
  particularly in the RCA 77 series, that created a very large midrange response hump".
- The rear port: "a rear port resistance/inertance opening that formed a constant group delay
  low pass filter to sound presented to the back of the ribbon"; the labyrinth and port
  "create a longer front to back path and thus reduced high frequency response particularly in
  the figure eight setting".

## Still to find

- The labyrinth's own dimensions on the 77-DX (its pipe's section and length, its stuffing)
  and the slot's opening at each stop: not printed by RCA or Olson; Watts's 6-9 mm and <= 1 m
  bound them. Fitted instead (scripts/fit_77dx.py, CHAINS_PLAN.md WP7's Notes): the
  labyrinth's radius 5.67 mm, the openings as narrow gaps of the shutter's printed 0.127 mm
  thickness. A drawing or measurement of the cam and the slot would replace the openings.
- The ribbon's thickness and the magnet's flux (fitted: 0.436 T with the 44-BX's 1.8 um
  foil; the 44-BX's fit gave 0.29 T on its pole pieces).
- The head's real shape for the body's BEM (the fit's equivalent disc is 18.6 x 5.7 mm; the
  head is 3-3/4 x 2-1/2 in, ib2): the 4 and 10 kHz patterns miss with the disc.

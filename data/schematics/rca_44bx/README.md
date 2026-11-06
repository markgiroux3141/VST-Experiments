# RCA 44-BX sources

The chains build-out's WP5 (docs/CHAINS_PLAN.md: the ribbon kind `ribbon_motor`, whose first
instance is the 44-BX's ribbon) and WP6 (the 44-BX itself), found 2026-11-05. This is the
44-BX (MI-4027-H, -J, -K; 1938-55), not the 44-A or the 44-B. Values in the component
`RIBBON_44BX` (data/datasheets/published_points.yaml), the design
`config/designs/rca_44bx_ot.yaml` and `config/circuits/ribbon_test.yaml` cite these as `ib:`
(RCA's instruction book), `aea:` (AEA's R44 sheet), `sbe:` (the SBE handbook's chapter) or
`web:`. Transcribed 2026-11-05; recheck a value against its image when it goes into a file.

The PDFs are not committed. Their URLs, sha256 and sizes are below. The PNGs here are
16-level gray renders of their pages.

## ib: RCA IB-24267-5, Instructions for the Type 44-BX Velocity Microphone (c. 1951)

Radio Corporation of America, Industrial Electronic Products, Broadcast Audio Equipment
Instructions, IB-24267-5 (the page coutant.org quotes as "IB-24267-5(-5A), circa 1951").
Two parts on coutant.org:

- web: https://coutant.org/rca44bx/44bx.pdf (the first page, "TECHNICAL DATA"; 103,747
  bytes, sha256 `784cf499ef440fb8f0c42531c99e572d5ad26067b6750a3de7289ac4ff3a158f`):
  `ib24267_5_technical_data.png`.
- web: https://coutant.org/rca44bx/jumpers.pdf (Figs. 3-8; 655,017 bytes, sha256
  `01d64116b0f184ea38cfd25f18987bca129028f5c4b4289053486688ea810a93`):
  `ib24267_5_fig3_fig4.png` (Fig. 3, the directional pattern about the horizontal axis at
  100-1000, 3000, 6000, 10,000 cps, S-350752; Fig. 4, the frequency response for M, V1, V2,
  50-15,000 cps, S-350753), `ib24267_5_fig5_mi4027h.png`, `ib24267_5_fig6_mi4027j.png`,
  `ib24267_5_fig7_mi4027k.png` (the schematic diagrams B-148305-1, B-149905-1,
  B-149906-0), `ib24267_5_fig8_parts.png` (the parts location diagram C-175467-1).
- The page that links them: web: https://www.coutant.org/rca44bx/index.html (quotes the
  book's description: "essentially flat" 50-15,000 cycles with the source at least three
  feet away; the M / V1 / V2 jumper: V1 to about 12 in, V2 to about 7 in "without
  objectionable low-frequency boost").

Technical data (the first page, as printed):

| Item | Value |
|---|---|
| Output impedance | 30, 150 or 250 ohms (connected for 250 ohms when shipped) |
| Recommended load impedance | Unloaded input transformer |
| Effective output level at 1000 cycles | -55 dbm (sound pressure = 10 dynes/cm^2); G_M = -149 db (RTMA rating) |
| Directional characteristics | Bi-directional about horizontal and vertical axes (Figs. 2 and 3) |
| Hum pickup | -115 dbm (terminal-board link in M position; hum field 1 x 10^-3 gauss) |
| Dimensions, weight | length 12 in (including mounting), width 4-5/8 in, depth 3-1/8 in; 8 lb 10 oz (unpacked) |
| Cable | 3-conductor shielded, MI-43B, 30 ft, no plug |

"Effective output level" is the RTMA's: the power into a matched load, so -55 dBm at 1 Pa
into 250 ohm is an open-circuit EMF of 1.78 mV/Pa (derived: P = 10^(-55/10) mW = 3.16 nW,
E = sqrt(4 R P)), against aea's 2.25 mV/Pa for its reproduction.

The schematic (Fig. 5, MI-4027-H; Fig. 6, -J, the same circuit with the ribbon's leads
crossed; Fig. 7, -K, M / V only): the ribbon's ends (YELLOW, BLACK) across the transformer's
primary; one secondary with a tap: its ends to terminal A (BLACK) and C (GREEN), the tap to
B (YELLOW); the REACTOR (its own core, drawn left of the transformer inside the shield's
dashed outline) from the secondary's A end to terminal D (RED) on the jumper strip D / E.
The cable table (at the terminal board):

| Wire | 30 ohm | 150 ohm | 250 ohm |
|---|---|---|---|
| GREEN | G | G | G |
| BLACK | A | B | A |
| RED | B | C | C |

So 250 ohm is A-C (the whole secondary), 150 ohm B-C, 30 ohm A-B. Jumper connections for
M / V1 / V2: "D only" / "D and B" / "D and E" (-K: M "D only", V "D and E"). "Phasing":
"when the sound pressure on the front of the microphone is in the positive half of the
cycle the red cable lead is electrically positive". "CAUTION: Rotating a velocity
microphone 180 degrees reverses the phase." Parts (Fig. 8): ribbon #20935, magnetic screen
#58874, upper / lower pole bridges #44657 / #44652, ribbon clamp #44653, transformer #58871
(H and J) / #55273 (K), guard assembly #55836 (front and back guards).

## aea: AEA R44 Series technical one-sheet (version 2.1)

Audio Engineering Associates' sheet for the R44C, "an accurate reproduction of the original
RCA 44 B/BX design to its original specifications", "using only ribbon material originally
manufactured for RCA". web: https://recordinghacks.com/pdf/aea/aea_r44_technical_onesheet_2.1_web.pdf
(222,616 bytes, sha256 `64ec8ec3a3ca853f8b51964111efcc52e9c6c6e385d65424858751aa6a2b94ea`):
`aea_r44_specs.png` (page 2).

- Transducer element: "Ribbon Thickness: 1.8 microns ( .0000018 meter ) of pure aluminum",
  "Ribbon Width: 4.7 mm", "Ribbon Length: 59.7 mm".
- "Output Sensitivity: 2.25 mV / Pa into unloaded circuit"; "Output Impedance: 270 ohms
  broadband"; "Recommended Load: 1.2 K ohm or greater". The X option: "6 dB more output
  than original RCA 44B/BX".
- "It is a pure undamped ribbon design"; "The internal ribbon element is by far the longest
  and its resonance tuning the lowest of today's ribbon microphones."
- Its response plot (0 dB = 2.5 mV/Pa, from 100 Hz: "measurement room size limitations").

## sbe: the SBE handbook, chapter 4.1 Microphones (Sank, Streicher, Dooley)

Jon R. Sank, Ronald D. Streicher, Wesley L. Dooley, "Microphones", chapter 4.1 of the SBE's
audio handbook. web: https://sbe.org/handbook/fundamentals/Audio/Audio-Microphones.pdf
(920,908 bytes, sha256 `a0ebf08e2b86aa304782ef7c6a346bb578ac6b2bb9e1a09f706163415181a0c1`):
`sbe_4_1_3_p19.png`, `sbe_4_1_3_p20_circuit.png`, `sbe_4_1_3_p21_response.png` (pages
4-19 to 4-21, sec. 4.1.3 "Pressure-Gradient (Velocity) Microphones").

- The RCA BK-11A (a later RCA ribbon, used where the 44-BX's figures aren't published): "an
  air gap 0.125 in (3.2 mm) wide with a flux density of 6500 G (0.65 Wb/m2)", "pure
  aluminum foil weighing 0.56 mg/cm2 ... a thickness of 0.000082 in (2 um)", "1.4 in (36
  mm) long and corrugated transversely", "Magnetic fine-mesh steel screens on both sides of
  the ribbon to provide resistance damping", "The ribbon resonance is approximately 30 Hz",
  "The 0.2-ohm ribbon impedance is stepped up to 30/150/250 ohm by the transformer. The
  reactor and switch provide low-frequency rolloff for the proximity effect."
- Olson's complete mechanical circuit (Fig. 4.1.11): F1 = P1 A_R -> R_L/2 -> M_L/2 -> [M_R +
  C_R (the ribbon) in parallel with M_S + R_S] -> M_L/2 -> R_L/2 -> F2 = P2 A_R; "R_L and
  M_L, the mechanical resistance and mass of the air load on the ribbon, imposed by the
  damping screens; M_R and C_R, the mass and compliance of the ribbon; and M_S and R_S, the
  mass and mechanical resistance of the slits formed by the ribbon to pole-piece
  clearance, which is nominally 0.005 in (125 um)". Above resonance: x' = (P1 - P2) A_R /
  (j w (M_R + M_L)) (Eq. 4.1.6); E = B l x' (Eq. 4.1.7). "The ribbon-to-polepiece clearance
  forms a leak which, if excessive, will reduce sensitivity."
- The path length D around the baffle: at D = lambda / 2 the gradient is 65% of the linear
  value, zero at D = lambda (Fig. 4.1.12, after Olson); "A practical microphone may have
  small ripples in response in the region just above resonance frequency, plus dips or
  peaks at high frequencies due to pole-piece shape or transverse resonances of the ribbon."

## Leckschat & David, DAGA 2010

Dieter Leckschat, Julian David, "Analysis of Ribbon Microphone Output Transformers and their
Influence on the Microphone's Sound", DAGA 2010 Berlin, pp. 787-788. web:
https://www.pub.dega-akustik.de/DAGA_2010/data/articles/000342.pdf (804,842 bytes, sha256
`f9ecf2b3c4708ef370682e2a776578aa136aab826d098a329b850d7aa713cf6d`):
`leckschat_david_daga2010_p1.png`.

- Fig. 1: the ribbon's equivalent circuit, the EMF behind the motional impedance Ce || Le ||
  Re and the ribbon's resistance Rr, into the transformer.
- "The mechanical resonance of the ribbon is tuned to be at the low end of the audio
  spectrum. Above resonance, the impedance of the ribbon is mass-controlled. The electrical
  impedance of the ribbon is a function of frequency and approaches a magnitude of up to
  five times its DC resistance at resonance depending on the ribbon motor design."
- The transformers "exhibit a second-order filter behavior at both the low and the high
  frequency extremes"; the low end set by the source's reactance and the primary inductance.

## Forum and other figures

- emrr (GroupDIY, "RCA 44-BX / MI-4027-E wiring", forum): web:
  https://groupdiy.com/threads/rca-44-bx-mi-4027-e-wiring.78095 (the strapping of a 5-terminal
  version: 250 / 30 / 150 ohm by straps). Superseded for the 44-BX by ib's cable table.
- Olson's 1931 paper (H. F. Olson, "Mass Controlled Electrodynamic Microphones: the Ribbon
  Microphone", J. Acoust. Soc. Am. 3(1) Part I, July 1931, p. 56) and his Elements of
  Acoustical Engineering (1940, sec. 9.2-9.3: the air load, the slit, eq. 9.23) weren't
  readable online; the handbook's circuit is the one used.

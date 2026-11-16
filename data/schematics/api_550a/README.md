# API 550A sources (docs/EQ_PLAN.md EQ3)

## Files

| File | Source | Shows |
|---|---|---|
| `schematic_613-759.png` | "MODEL 550A EQUALIZER SCHEMATIC", drawing 613-759, Automated Processes Inc.: hyperspasm.com's rescan (`550a.pdf`, "the cleanest copy of the 550A schematic I've seen", GroupDIY thread 42596), via the Wayback Machine: web: https://web.archive.org/web/2010id_/http://www.hyperspasm.com/hyperblog/wp-content/uploads/2009/03/550a.pdf, downloaded 2026-11-15, sha256 `b917387dc4e99c3e7a8e4c7f098dd1835fab1879c8002732843849e5ccc904cc` (a 400 ppi scan stored rotated; here upright at 200 ppi). A softer copy: web: https://audiocircuit.dk/downloads/api/API-550A-eq-sch.pdf (sha256 `d63d3b82...dfc2`) |
| `sm550-1.png` ... `sm550-4.png` | API's **Model 550** sheets and the **550A installation** page: web: https://audiocircuit.dk/downloads/api/API-550-eq-sm.pdf (sha256 `2cf48625...92f6`), 150 dpi | p1 the 550's features and description; p2 the 550's **peaking and shelving families** and its specifications; p3 the **550A installation** (terminals, the gain-trim table between terminals 8 and 11); p4 a schematic (the 550's, too small to read) |

Not a source for the original: API's 2004 reissue brochure (web: https://www.apiaudio.com/docs/brochures/br550a.pdf: 7 frequencies per band, "21 points").

## Readings so far (2026-11-15)

**Specifications (the Model 550's sheet, p2):** input 15k high level / 6k low level; output
< 85 ohm; insertion loss none (bridging); +-0.5 dB 30 Hz-20 kHz flat; +28 dBm maximum, transformer
isolated; < 0.35% THD 30 Hz-20 kHz at +28 dBm; noise -85 dBm (high-level strapping); boost / cut
2, 4, 6, 9, 12 dB; band-pass 50 Hz-15 kHz; LF and HF peak / shelf. The 550's frequencies (LF 50,
100, 200; MF 400, 800, 1500, 3000, 5000; HF 7k, 10k, 15k) are not the 550A's: its drawing has five
capacitors per band, so its frequencies come from the circuit.

**The drawing's structure:**
- **A1** (AP2520), the HF band: + input = the input (HI-1 through R1 11K, HI-2 direct; R2 7.5K
  HI-2 to LOW). − input through R71 1K to node N1; R78 2.2M output to − input; C37 68 pF − input
  to output.
- **S8A**, HF boost / cut (positions 1-11, 6 = 0 dB), API's stepped reciprocal bridge: A1's output
  -> R7 6980 -> contact 7, then R6 3480, R5 3320, R4 4530, R3 4870 to contact 11's end, which is
  N1. The other string: contact 5 <- R8 6980 (from a line to the right, to trace), R9 3480, R10
  3320, R11 4530, R12 4870 to contact 1's end (a line to the right, to trace). Contact 6 to R48
  10K (its other end to trace). The rotor feeds the HF network. Same ladder values on S6A (LF:
  R28-R37, R32 / R33 6980, R53 1K) and S10A (MF: R54-R63, R58 / R59 6980).
- **Proportional Q:** S8B (R38 4530, R39 2100, R40 1780, R41 1180) and S8C (R43 8060, R44 5360,
  R45 3830, R47 2740; R42 3920, R47 6650 below) tap resistor chains on positions 1-5, their
  positions 7-11 wired to the same taps in mirror (the frames), so the network's resistors follow
  |gain|. LF: S6B (R18 4530, R19 2100, R20 1780, R21 1180), S6C (R23 9310, R24 4420, R25 3920,
  R26 2550; R22 3920, R27 6340, C14 22 uF). MF: S10B (R64 4530, R65 2100, R66 1780, R67 1180),
  R68 3920. S6D / S6E / S8D / S8E / S10C / S10D use only their end contacts.
- **The frequencies** (twin-T networks, API's 5500 manual: "the Twin T topology"): HF S9A C31
  .001, C34 680p, C33 330p, C32 330p, C45 .0012; S9B C46 .001, C49 680p, C48 330p, C47 330p, C50
  .001; S9C C51 .0018, C52 .0015, C53 680p, C54 470p, C55 .0022 (S5 PEAK / SHELF). LF S7A C6 .15,
  C8 .082, C10 .027, C17 .015, C18 .039; S7B C5 .15, C7 .082, C9 .027, C19 .015, C20 .039; S7C C11
  .047, C12 .022, C13 .0068, C15 .0047, C16 .01 (S4 PEAK / SHELF). MF S11A / S11B with C21 / C22
  .022, C23 / C24 .01, C25 / C26 .0056, C27 / C28 .0022, C29 / C30 .0033 (pairs).
- **Band-pass** (S2): C1 4.7 uF / R13 910, C2 .47 uF / R14 9.1K (high-pass), R16 560 / C3 .01, R17
  5.6K / C4 .001 (low-pass), R15 330K, R107 18K, R99 1K into **A6**, R51 2.2M.
- **A2** (AP2520), LF and MF bands: R72 1K, R80 15M, C40 120 pF, C61 10 pF; C35 / C36 10 uF / 25 V
  rail decoupling. **A3, A4, A5** in the bands' networks; R49 / R81 / R82 2.2M, R73 / R75 / R77
  1K, R50 10K, R52 10(0?), C39 / C43 / C56 47 pF.
- **A3-A6:** the drawing's inset: a discrete follower (Q 2N5088 NPN with a PNP, 39K, 3K, 430,
  100, 2.7K; C57-C60 33 pF).
- **Output:** A2 -> C41 500 uF || R101 47 -> T1 (AP2503) pin 1, pin 2 to R76 56 -> terminal 11;
  R106 200; secondary 3-7, terminals 2 HI-1, 3 HI-2, 4 LOW. **Rails:** CR1 / CR2 series diodes,
  R100 3.9K, LED DS1, S1 the EQ IN / OUT (also S1's contacts in each band).

## The trace, complete (2026-11-15; built as config/circuits/api_550a.yaml by scripts/make_api_550a.py)

Read from the 200 ppi PNG (the 400 ppi PDF's Wayback copy now answers bots with a block page).
Corrections to the readings above: the followers' capacitors C57-C60 read 39 pF in the inset (not
33); the "twin-T" is not a twin-T (below); the two S8C parts both labelled R47 are 2740 (in the
chain, called R46 in the circuit file) and 6650 (the chain's end).

- **The signal path.** Input -> A1 (+ input; HF boost in its feedback) -> C1 / C2 ... the band-pass
  -> R99 -> A6 -> the HF cut string (R8 at A6's output ... contact 1's end) -> R75 1K -> A4 (R81
  2.2M to LOW) -> the MF cut string (R59 ... R63) -> R73 1K -> A3 (R49 2.2M) -> the LF cut string
  (R33 ... R37) -> R53 1K -> A2's + input (R79 2.2M, C40 120 pF to COM). A2's feedback: A2's output
  -> R106 200 -> node X -> the MF boost string (R58 ... R54) -> R77 1K -> A5 (R82 2.2M) -> the LF
  boost string (R32 ... R28) -> R72 1K -> A2's - input (R80 15M and C61 10 pF from A2's output).
  A1's boost string: R7 at A1's output ... contact 11's end -> R71 1K -> A1's - input. X -> R76
  56 -> terminal 11 (the gain trim). A2 -> C41 500 uF || R101 47 -> T1 pin 1; pin 2 to terminal 5
  (power common); secondary pin 3 terminal 2 (HI-1), pins 4-5 strapped, pin 6 terminal 3 (HI-2,
  the tap), pin 7 terminal 4 (LOW).
- **Across strings:** C37 68 pF A1's output to its - input (the HF boost string and R71); C43 47
  pF X to the MF boost string's end; C56 47 pF A4's output to the MF cut string's end; C39 47 pF
  A5's output to the LF boost string's end. None across the HF and LF cut strings.
- **A band** (HF named; LF S6x / S7x / S4, MF S10x / S11x): S8A's rotor W taps the boost string
  (contacts 7-11) or the cut string (1-5); contact 6 -> R48 10K -> M. The drive decks S8D (contact
  1 -> A6's output, the cut source) and S8E (contact 11 -> A1's output, the boost source) put M on
  a source; their arcs, drawn from one template in all three bands, overlap at position 6 by a few
  degrees: read (the user's call, 2026-11-15) as S8D on 1-6, S8E on 7-11. LF: S6D -> A3's output,
  S6E -> A5's; R50 10K. MF: S10C -> A4's output, S10D -> X; R52 10K.
- **PEAK:** W -> S1 (the band's EQ IN deck) -> S5 common -> PEAK (4) -> S9B's rotor -> S9B's
  capacitor -> the bus P; S9A's rotor is M, its capacitor M to P; S8B's rotor is P, onto its chain
  (contact 5's node ... contact 1's node -> R42 3920) -> HF's B (C38's +). MF has no S5: S1 ->
  S11A's rotor (W side), S11B's rotor is M; S10B's chain ends R68 3920 to ground. LF: S7B W side,
  S7A M side, S6B's chain R22 3920 to ground.
- **SHELF:** HF: S5's SHELF (6) -> S9C's rotor -> its capacitor -> S8C's rotor (the chain to R47
  6650) -> B: a high shelf. LF: S4's SHELF (6) -> the S7C capacitors' bus, which is also S6C's
  rotor (its chain to R27 6340 -> C14 22 uF + ; C14 - to ground), and S7C's rotor is M: a low
  shelf (the resistor to ground in parallel with the capacitor to M).
- **B, ground:** C38 125/4V from HF's B to ground (its - plate on LOW); the LF and MF Q chains'
  return and C14's - plate run along one line to C38's - plate, ground.
- **The arcs:** every frequency deck (S7A-C, S9A-C, S11A-B) and drive deck is drawn with an arc
  rotor, a progressive shorting contact: each step clockwise adds the next capacitor in parallel
  (S9A at position 1 C45, then + C32, + C33, + C34, + C31; S11A / S11B the pairs C29 / C30, + C27
  / C28, + C25 / C26, + C23 / C24, + C21 / C22). So position 1, the most counter-clockwise (Note
  8), is each band's highest frequency.
- **The band-pass's ground:** the shunt elements' bus G -> S2 contact 3 -> a line to the S1 deck
  beside C38 -> B; R107 18K from A1's output to G, R15 330K from G to B. S2's contact 1 is open.
- **The proportional-Q decks** (S8B / S8C, S6B / S6C, S10B) join positions k and 12 - k to the
  same tap (the frames); 6 is open.
- **The followers** (inset): IN -> Q1 2N5087 base (emitter -> R85 39K to +V and Q2's base;
  collector to -V); Q2 2N5088 (collector R83 430 to +V, emitter OUT); Q4 2N5088 sink (collector
  OUT, base on R102 36K / R86 2.2K, emitter R84 200 to -V); C57 39 pF IN to Q4's emitter; C62 22
  pF IN to Q4's base (A5 only).

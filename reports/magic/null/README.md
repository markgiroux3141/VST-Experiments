# AM2: the two-pass null

2026-11-13, `scripts/two_pass_null.py` -> `summary.json`, `null.png`, residual WAVs in
`audio/` (each also at +20 dB, marked in the name). 10 s of Dry Guitar and of the drums at -18
dBFS rms, production quality, 1 s of settling. Levels are dB re pass A's rms after aligning:
`gain` = a - g b (one gain), `audio` = the same within 20 Hz-20 kHz (both band-passed),
`dewarped` = the character part after the time base is removed (`null.dewarp`).

**Two fixes during the night, before these numbers** (the first run's summary is in
`cache/magic/am2_summary_before_fix.json`):
- `null.delay_track` windowed only one signal. Its peak wandered by up to 2 ms on drums, so
  "dewarped" made pairs with no time-base difference *worse* (the 670's P1 -93 -> -23 dB). Both
  signals are now cut by the same window: a pair with no wander dewarps to itself, and 0.1 %
  flutter on drums goes -13 -> -40 dB (checked by hand; `tests/test_magic_toolkit.py`).
- The `audio` stage: the noise builds carry **sub-audio drift**. The 6G15's noise floor is -2 dB re
  its program by plain rms, but almost all of it is below 5 Hz; in 20 Hz-20 kHz it is -57 dB.
  The plate's floor is likewise below 0.5 Hz (-18.5 dB plain, -56 audio).

## Liveness (guitar / drums)

| Device | floor (audio) | P1 mains phase | P2 noise seeds | P2 if additive | P3 another moment |
|---|---|---|---|---|---|
| fairchild_670 | -114 / -109 | -79 / -95 | **-60 / -56** | -111 / -105 | -60 / -58 |
| pultec_eqp1a | -94 / -94 | -77 / -91 | -77 / -84 | -91 / -91 | -77 / -85 |
| telefunken_v76 | -111 / -107 | -81 / -88 | **-50 / -30** | -108 / -104 | -52 / -32 |
| fender_5e3 | -75 / -72 | -85 / -95 | **-41 / -40** | -72 / -69 | -41 / -42 |
| fender_5e3_mods | -75 / -72 | -85 / -95 | -41 / -41 | -72 / -69 | -41 / -42 |
| urei_1176 | -82 / -75 | **identical** | -78 / -78 | -78 / -72 | -78 / -78 |
| ssl_bus_comp | -97 / -96 | **identical** | **-61 / -63** | -94 / -93 | -61 / -63 |
| plate_reverb | -56 / -65 | -81 / -97 | -36 / -37 | -53 / -62 | -38 / -39 |
| fender_6g15 | -57 / -57 | -82 / -90 | -55 / -54 | -54 / -54 | -58 / -56 |

(`audio` levels; `gain` and `dewarped` are in summary.json and agree with `audio` within ~2 dB
except where the sub-audio drift dominates: the plate's and 6G15's `gain` column.) P0 (noise
off, twice, the second uncached) is **bit-identical on every device**. P4 (the 5E3 mods, warm
against just switched on): -1.5 / -1.1 dB. Ten seconds after power-on the tubes barely emit,
so this is a different sound, not a nuance (the doc's stated limit).

Readings:
- **The seeded noise does far more than add noise.** On the compressors, the V76 and the 5E3,
  P2 is 30-74 dB above what independent additive noise would give. The residual follows the
  program's envelope (log-level correlation 0.76-0.84 per 50 ms) and has the same level in every
  band. It is a multiplicative change, and "noise on vs off" moves the output as much as
  "seed 1 vs seed 2" (V76 drums -28 dB, the 670 -56, the 5E3 -42). The candidate is the
  **mains wander** (0.5 % rms, a 1/f process below 2 Hz, provisional): two seeds give two
  different slow supply offsets over a render, and supplies set the gain reduction (670, SSL),
  the sag (5E3) and the clip point (the V76 is overdriven by these drums: its output peaks at
  2.4x full scale). **Confirmed** (`p2_without_mains_wander.json`, `scripts/p2_without_mains_wander.py`:
  the wander's rms set to 0 in that process only, uncached):

  | | P2 with the wander | without | additive expectation |
  |---|---|---|---|
  | V76, drums | -30.4 | **-87.7** | -104.4 |
  | 5E3, guitar | -41.0 | **-78.8** | -71.5 |

  The wander is 58 and 38 dB of it. What the V76 keeps (17 dB over additive) is its noise
  meeting the clipping. The 5E3 lands *under* additive: a cranked amp compresses its own noise,
  as the triode stage does under a big swing (tests/test_magic_null.py).
- **The EQP-1A, the 1176 and the 6G15 are near additive**: their noise doesn't reach the gain.
  The 1176 and the SSL have ideal rails (P1 identical), so the wander has nothing to act on in
  either. **The SSL's P2 is still 33 dB above additive, so the wander isn't the whole story:**
  its own noise reaches its gain. Presumably that is through the sidechain into the Blackmer
  cell's control port, a log-domain gain where a microvolt is a fraction of a dB (not checked).
- **P3 ≈ P2 everywhere**: "the same unit at another moment" differs as much as two units with
  different noise. The noise's slow part dominates, not the instant.
- **P1 (the mains' phase against the music) is -77 to -97 dB**: hum and ripple are locked to
  the mains, not the program. The EQP-1A's is the largest (-77, its 6X4 supply).

## The tape (the idealized machine, grain and transport apart)

| Pair | gain | dewarped |
|---|---|---|
| T1 grain (seed 1 vs 2) | -33 / -33 | -33 / -33 |
| T2 transport (seed 0 vs 1) | -21 / -10 | **-51 / -37** |
| T3 both | -21 / -9 | -33 / -32 |

- **T2 against the estimate** `20 log10(2 pi f sigma)`. The measured relative displacement
  between the two passes is sigma = 76 us (guitar) / 78 us (drums): ~54 us per pass, more than the
  doc's 32 us for 0.1 % at 5 Hz, so the model's slower wow dominates.

  | f | guitar measured | estimate | drums measured | estimate |
  |---|---|---|---|---|
  | 100 Hz | -26.5 | -26.4 | -22.6 | -26.2 |
  | 250 Hz | -18.5 | -18.4 | -18.9 | -18.2 |
  | 500 Hz | -13.3 | -12.4 | -13.1 | -12.2 |
  | 1 kHz | -10.4 | -6.4 | -7.2 | -6.1 |
  | 2-8 kHz | -4 to +3 | 0 to +12 | -3 to +2 | 0 to +12 |

  It matches within ~1 dB where the estimate holds (2 pi f sigma << 1). Above ~1 kHz the
  residual saturates toward +3 dB (two decorrelated copies), as it must. **Tape nulls badly
  above a few hundred hertz and well in the bass, and dewarping recovers 25-30 dB**, as the doc
  predicted. What's left after dewarping (-37 to -51 dB) is the grain's level (T1, -33 dB) and the
  dewarp's own floor.
- T1: the grain alone nulls at -33 dB, consistent with AM7's -37 dB re signal (the residual of
  two independent realizations is +3 dB over one).

## The Ampex 351 (the literal machine, aligned)

`two_pass_null.py --only ampex_351` (14 renders, 89 min). The same pairs on the whole machine
(tubes, the literal bias, the tape's grain and transport). A run's origin (P1) moves every
deterministic process that runs from the start: the mains sines, and also the transport's
flutter and the grain's position along the tape. So on the 351, P1 is not only "the mains'
phase".

| Pair (guitar / drums) | audio | dewarped | delay track rms |
|---|---|---|---|
| floor (noise alone, audio band) | -53 / -50 | | |
| P0 noise off twice | **identical** | | |
| P1 origin 0 vs 7.3 s | -15 / -7 | **-45 / -37** | 141 / 140 us |
| P2 noise seeds | -20 / -9 | -33 / -31 | 96 / 163 us |
| P2 if additive | -50 / -47 | | |
| P3 another moment | -16 / -6 | -33 / -31 | 151 / 215 us |

- **The time base is almost all of it.** Every pair's plain residual is -6 to -20 dB, as the
  idealized machine's T2 was, and dewarping takes 13-30 dB off it. The relative displacement
  is 100-200 us rms, more than the idealized machine's 76 us. The literal machine's transport
  also hunts with its motor.
- **After dewarping, P2 and P3 still sit ~16 dB over additive** (-33 / -31 against -50 / -47).
  That is what AM6 found too (`reports/magic/levels/`: a -27 dB floor that scales with the
  signal). Flutter faster than the tracker follows (~25 Hz) and the grain's modulation noise
  both scale with the signal, and this measurement can't split them. P1 dewarps deeper (-45 /
  -37). There the grain is the same realization, only shifted, so what's left of P1 is
  mostly fast flutter.
- **P0 is bit-identical** with the noise off, like every other device: the literal 351 is
  deterministic at a fixed origin and seed.

## More deterministic than hardware (pairs below -120 dB)

| Pair | What a real unit would vary that the model holds fixed |
|---|---|
| P0 on every device (noise off) | Everything a `noise:` block switches on: no circuit file here has one, so **every default render is frozen**: Johnson and tube noise, flicker, the mains wander. |
| P1 on urei_1176, ssl_bus_comp | Their supplies are ideal rails: no ripple, no hum, no mains at all. A real 1176's supply has both. |
| (all) | Thermal state: the heaters model runs only where asked (`heaters=`), and nothing else is temperature-dependent at run time. Pots and switches are exact between passes. |

These are candidates, not changes. Adding a `noise:` block to a circuit moves its renders, and
that is your decision (the doc's rule). The table above suggests that the mains wander, not the
hiss, would be the audible part of such a block on the compressors and the V76. Its 0.5 % rms is
provisional, so it should be sourced first.

## The numerical floor

`tests/test_magic_null.py` (the doc's tests on `triode_stage`): P0 is bit-identical, and at a
linear level P2 is the stage's own noise + 3.0 dB, as independent additive noise must be. On a
hot signal (2.7 V rms out) production tolerances add a numerical part ~103 dB under the output
(the noise moves the error-controlled steps). It vanishes at 100x tighter tolerances. Every
residual above is at least 25 dB over that.

## Limits

One program per clip, 10 s. The mains wander is provisional (0.1-2 % bounds). Levels say how
deep the passes cancel, not whether a difference is audible.

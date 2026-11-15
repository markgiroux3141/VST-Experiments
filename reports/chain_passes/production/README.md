# Chain caricatures by repeated passes (2026-11-14)

`uv run --extra fast --extra listen python scripts/chain_passes.py` (production quality, about 10 min on
this desktop; the passes are cached in `cache/chain_passes/`).

Each stem of `stems/Did she mention my name/sample/` (its mid) is the free-field pressure at the chain's
capsule, on axis, as a plane wave. It is recorded through the chain, and the output is fed back the same
way 1-8 times.

**Staging, as an engineer would set it.** Each pass's input is set to 100 dB SPL sounding rms (the carbon
gets 90, a telephone's level). It is turned down wherever the chain's measured response H predicts an
output peak above pass 1's. The preamp gains were set so pass 1 peaks near -12 dBFS on the vocal:
V76 24 dB, 610 LEVEL 0.4, API 312 GAIN 0.4, clean pre 30 dB (20 dB for the carbon).
At the chains' default gains, the peaks reached the output stages' rails, and the "character" measured
was clipping.

**Per chain and stem**, in `<stem>/<chain>/` (every file loudness-matched to -23 LUFS; a file whose peak
would pass 0 dBFS was turned down instead, and the run's log lists them):

| file | what it is |
| --- | --- |
| `pN.wav` | N passes as they come out: N passes of tone and N passes of character |
| `pN_tone.wav` | one pass, then H^(N-1): N passes of tone, one pass of character (pure EQ caricature) |
| `pN_eqnull.wav` | N passes, then H^-(N-1): one pass of tone, N passes of character (character caricature) |

`../../<stem>/dry.wav` is the dry mid. `responses.png` shows each chain's H^N, and `summary.json` has
every number.

## The chains' tone (H re 1 kHz, one pass)

| chain | 50 Hz | 100 | 2k | 5k | 10k | 15k | 20k |
| --- | --- | --- | --- | --- | --- | --- | --- |
| U47 -> V76 | +0.2 | +1.0 | -0.1 | +0.2 | +2.7 | +0.5 | -7.6 |
| 44-BX -> 610 | -0.9 | +1.0 | +0.3 | +0.9 | -3.0 | -6.5 | -26.5 |
| SM57 -> API 312 | -10.9 | -1.5 | +0.9 | +6.3 | +6.9 | -2.2 | -12.8 |
| F1 carbon -> clean | -17.8 | -15.6 | +10.8 | -4.6 | -23.5 | -36.6 | -77 |
| 4134 omni -> clean (control) | -0.1 | -0.1 | +0.2 | +1.9 | +6.3 | +10.6 | +10.4 |

## Correction (2026-11-14, later the same day)

The first version of this report measured "character" with `difference.decompose`: a least-squares
filter fitted between the input and the output, 0.34 s long and 1/12-octave smoothed. **On these
chains that fit's own floor is as large as what it reported.** Pure EQ (the dry stem through the
measured H^N, no nonlinearity at all) reads the same numbers through it: on the U47 -> V76, bass
-28 / -23 / -19 / -13 against -28 / -23 / -18 / -13 reported. The chains have several steep
low-frequency high-passes with time constants the fit can't follow. So the earlier claims "the bass
gets the most character" and "+5 dB per doubling" were the measure, not the chains.

The figures below are a **residual** instead (`chain_passes.residual_db`): the output against
g H^N x, where H is the multisine-measured response applied exactly (no fit) and g is a
least-squares gain. It is taken in a brick-wall 40 Hz-20 kHz band; below 40 Hz the stems' rumble
meets the correction's fade to unity. Its floor:
- the omni control: -82 to -90 dB;
- the U47 -> V76 at 80 dB SPL: -59 to -64.

The real chains' residual rises with level as distortion does: the U47 -> V76 is -59 to -64 at 80 dB
SPL and -44 to -48 at 100. The old figures stay in `summary.json` (`vs_dry`, `eqnull_vs_p1`) but
shouldn't be used.

## What one pass adds (residual, dB re signal, 40 Hz-20 kHz)

| chain | bass | guitar | harmonies | lead vocal |
| --- | --- | --- | --- | --- |
| U47 -> V76 | -44.0 | -45.6 | -45.6 | -47.8 |
| 44-BX -> 610 | -45.1 | -41.1 | -45.0 | -48.9 |
| SM57 -> API 312 | -54.6 | -52.5 | -74.2 | -61.5 |
| carbon -> clean (90 dB SPL) | -13.8 | -13.2 | -10.7 | -10.7 |
| omni -> clean (control) | -86.0 | -81.7 | -90.2 | -87.7 |

That is 0.4-0.9 % for the two tube chains at 100 dB SPL, less for the SM57 -> API 312. No stem
stands out. The carbon transmitter (and its clipping) is in another class.

**Growth with passes** (`residual_vs_dry`, passes 1 / 2 / 4 / 8):

| chain | bass | guitar | harmonies | lead vocal |
| --- | --- | --- | --- | --- |
| U47 -> V76 | -44.0 / -40.9 / -38.7 / -34.2 | -45.6 / -41.0 / -36.7 / -30.9 | -45.6 / -46.2 / -40.2 / -34.1 | -47.8 / -46.3 / -40.1 / -34.6 |
| 44-BX -> 610 | -45.1 / -42.3 / -40.2 / -37.2 | -41.1 / -37.9 / -33.4 / -27.8 | -45.0 / -34.2 / -28.4 / -22.3 | -48.9 / -44.2 / -38.1 / -31.4 |

- **The U47 -> V76 grows about 4 dB per doubling**, a little more than independent distortions
  adding (3 dB). Each pass itself adds a steady -46 to -50 dB (`residual_this_pass`).
- **The 44-BX -> 610 on the harmonies grows faster.** From pass 2 on, each pass adds -35 dB instead
  of pass 1's -45: the compounded tone drives its preamp harder.
- The SM57 -> API 312's late passes were turned down by the peak staging, so they distort less (its
  pass-8 figures fall).
- The omni's and the carbon's pass-8 figures are n/a: their H^8 boosts past the correction's
  +60 dB limit somewhere in the band.

## Where the EQ null works

`eqnull_residual_vs_p1` compares `pN_eqnull` with `p1`. Ideally only the extra passes' distortion is
left between them.
- U47 -> V76 at 4 passes: -40 to -43 dB, the extra three passes' worth.
- At 8 passes: -17 to -32, where the compounded band edges can't be restored.
- So `p4_eqnull` against `p1` is still the cleanest "distortion only" listen.

## Caveats

- Edge artifacts removed: the metrics leave out 0.1 s at each end, because each pass's fades and the
  truncation of its delay are time-varying. Without that, every chain, the control included, measured
  about -30 dB of "character".
- The old fitted measure is unreliable here (the correction above); the residual's floor is -59 to
  -64 dB on the U47 -> V76 at 80 dB SPL and -82 to -90 on the omni control.
- The carbon: its best linear approximation can't predict its peaks, so from pass 2 on, the vocal and
  harmonies still reach the clean pre's rails. Its passes are the carbon plus clipping.
- No noise here: `../production_noise/` is the same with B5's noise.
- A mic pass is a plane wave on axis. Polar pattern, proximity and the room don't compound here.
- Draft quality runs the cores in their linear limit; use production for anything about iron.

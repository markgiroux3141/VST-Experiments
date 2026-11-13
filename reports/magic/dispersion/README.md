# AM5: dispersion before saturation

2026-11-13, `scripts/dispersion_study.py` -> `summary.json`, `dispersion.png`,
`chain_allpass_fir.npy`, ABX pairs in `abx/` (the realistic ones by
`scripts/dispersion_abx_pairs.py`). Tests: `tests/test_magic_dispersion.py`.

## Step 1: the chain's phase

Each stage's small-signal response from a -40 dBFS sweep, checked at -50 dBFS:

| Stage | -40 vs -50 dBFS | group delay 20 / 40 / 80 / 160 Hz (ms) |
|---|---|---|
| telefunken_v76 | 0.025 dB / 0.36 deg | 13.3 / 7.7 / 2.1 / 0.49 |
| pultec_eqp1a (flat) | 0.004 dB / 0.03 deg | 1.5 / 0.36 / 0.09 / 0.02 |
| fairchild_670 (below threshold) | 0.002 dB / 0.03 deg | 5.2 / 1.8 / 0.46 / 0.11 |
| ampex_351 (literal, aligned) | 0.33 dB / 1.0 deg | 13.1 / 4.0 / -0.55 / 1.1 |

The 351 is the only stage outside the doc's 0.1 dB / 1 deg check, and only on the dB side.
Its transport's flutter moves a sweep between two passes (its sweep took 75 min). Its curve is
not monotonic: the head bump's phase sits between 80 and 160 Hz, and a ~1.2 ms remainder at
1 kHz is a pure delay the 1-5 kHz slope didn't fully take out. A pure delay doesn't change any
waveform.

**The chain** (V76 -> EQP-1A -> 670 -> 351 -> 351 -> 670; no lathe or cartridge, not built):

| f (Hz) | 20 | 30 | 40 | 60 | 80 | 120 | 160 | 250 |
|---|---|---|---|---|---|---|---|---|
| group delay (ms) | 51.4 | 28.5 | **19.7** | 8.5 | 2.1 | 4.4 | 3.0 | -0.1 |

A fit of n first-order high-pass poles at one f0 to the cumulative phase below 200 Hz gives
**n = 15.5 at 14 Hz** (rms error 9.9 deg; the tape's head bumps aren't high-pass poles). The
doc's estimate of 20 poles at 10 Hz predicted 18.7 ms at 40 Hz; measured 19.7 ms. The 40 Hz
delay is near the one-to-two-cycle rule of thumb (25 ms), which is itself extrapolated.

## Step 2: the all-pass

The chain's phase as a 65,536-tap FIR at unit magnitude: flat within **0.067 dB** from 20 Hz to
20 kHz. That is a hair outside the doc's 0.05 dB. Both orders get the same FIR, so it cancels
in the comparison.

What it does to the programs' crest factor (broadband, dB): drums 20.4 -> **19.5**, voice 12.4
-> 13.1, bass 12.7 -> 12.9. Asymmetry (peak ratio): drums 0.71 -> 0.46 dB, bass 0.98 -> 0.38
dB, voice 0.34 -> 0.75 dB. The drums lose 0.9 dB of peaks; the published demonstration the
doc cites lost 1.6 dB with a purpose-made rotator. The voice *gains* 0.7 dB. A 1960s chain's
rotation is not a broadcast rotator: it symmetrizes the drums and the bass, not the voice.

## Step 3: the commutator

`difference.levels(y1, y2)["character"]`, y1 = S(AP(x)) (the historical order), y2 = AP(S(x)),
dB re the output. The linear parts of both orders are identical, so this is purely what the
order does to the nonlinearity. The stage's own character (x against S(x)) is given beside it.

| Stage | drums | voice | bass |
|---|---|---|---|
| tape, 0 dB drive | -11.9 (own -11.2) | -21.6 (own -21.5) | -19.9 (own -19.2) |
| tape, +6 dB | -8.7 (-7.7) | -15.1 (-14.3) | -13.9 (-13.0) |
| tape, +12 dB | -6.6 (-5.3) | -11.1 (-10.2) | -10.0 (-9.1) |
| 670, +6 dB in | -10.0 (-8.2) | **-24.0 (-14.2)** | -22.5 (-15.0) |
| 670, +12 dB in | -7.9 (-5.5) | -22.3 (-11.6) | -16.1 (-11.2) |
| 5E3 at volume 0.7 | **-3.2 (-4.1)** | -4.2 (-9.0) | -7.2 (-3.4) |

- **They don't commute, and on the tape the interaction is as large as the tape's whole
  character.** Rotating the bass's phase before the tape changes its distortion about as much as
  the distortion itself, at every drive. It's not the measurement: the idealized tape is
  time-invariant to -67 dB (the same voice printed twice, shifted 4801 samples; checked this
  morning). Neither is it the time base (flutter off; y1 and y2 track each other at zero
  delay). Most of the tape's character at these levels is its level-dependent HF loss, driven
  by the waveform's peaks, and the rotation moves the peaks.
- **The 670 is the most order-insensitive.** On the voice and the bass the interaction is
  7-11 dB under its own character. Its gain reduction follows the envelope, which the rotation
  hardly changes. On drums it is 2 dB under.
- **The 5E3 is the most sensitive.** On the voice the interaction (-4.2) is *larger* than the
  amp's character (-9.0): a clipper hears the phase directly.
- **What the numbers don't say:** a character level is a level, not an audibility. Two orders
  can differ by -12 dB and sound alike if the difference is distortion of the same kind.

## Step 4: listening (yours)

`abx/`: each pair LUFS-matched, `*_historical_S_of_AP.wav` against `*_AP_of_S.wav`:
- **realistic first:** `tape_0dB_voice_*`, `tape_0dB_drums_*`, `670_in+6dB_voice_*`;
- **the largest:** `5e3_vol0.7_drums_*` (drums through a cranked guitar amp: not a 1960s record
  path, the upper bound).

The doc's done-when: if you can't tell the realistic pairs apart, the package closes as
"verified: subtle".

## Limits

No lathe or cartridge in the chain. One rotation (the chain's at its default panels). The
tape in step 3 is the idealized machine (`print_audio`, flutter off, no grain); the 351 is
the literal one in step 1 only. Each character level is from `difference.decompose`'s fixed
filter, so it is an upper bound where the stage's linear response is long (the tape's own).

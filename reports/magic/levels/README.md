# AM6: noise-forced gain staging

2026-11-13, `scripts/noise_forced_levels.py` -> `summary.json`, `levels.png`. A 6 s excerpt of
`vocal_longwayhome.wav` (its loudest 6 s) at -40 to +5 dBFS rms in 3 dB steps, production
quality. Noise: the stage on silence with the builder's `noise=1` (Johnson, tube, flicker, the
mains wander; no circuit file has a `noise:` block, so this is switched on for the run only).
Character: `difference.decompose(input, output)`'s part no fixed filter explains, referred to
the output. Both A-weighted (`varimu/magic/levels.py`, IEC 61672-1's poles; tests in
`tests/test_magic_levels.py`).

**Two corrections to the doc's recipe, both in the script:**
- **The 351 is dewarped before decomposing** (AM2's `null.delay_track` / `dewarp`). Without it,
  its transport's wow and flutter counted as character at every level: -6.5 dB re signal flat,
  so the first pass's L* (-32.1) was meaningless.
- **L* is found on the character over its floor.** After dewarping, the 351 keeps a
  level-independent floor of -26.9 dB re signal from -40 to -22 dBFS: flutter faster than the
  tracker follows (~25 Hz) and the grain's modulation noise. A part of the impairment that
  scales with the signal can't move the optimum, but it buries the trend in wobble. The floor is
  the least character / signal ratio on the grid; L* is the minimum of
  (noise^2 + character^2 - floor^2 signal^2) / signal^2. The floor is reported beside it.
  On the EQP-1A this moves L* by < 0.1 dB, and it changes nothing on the V76 and the 670.

## Results

| Stage | L* (dBFS rms in) | noise x0.5 / x2 | at L*: noise / character over floor (dB re signal) | floor | operating level | at 0 VU (-19 on the grid): noise / character |
|---|---|---|---|---|---|---|
| pultec_eqp1a | **-21.8** | -23.1 / -20.3 | -89.6 / -90.6 | -86.5 | -18 | -92.6 / -83.9 |
| ampex_351 | **-30.8** | -32.0 / -29.4 | -49.4 / -47.7 | -26.9 | -18 (aligned: 400 Hz at 0 VU plays 1 % THD) | -61.1 / -24.6 (over floor -28.5) |
| telefunken_v76 | **below -40** (the grid's edge) | the same | -90.1 / (all floor) | -72.3 | see below | -111.0 / -32.3 |
| fairchild_670 | **below -40** | the same | -94.4 / (all floor) | -87.6 | -18 | -112.7 / -21.1 |

**The claim** (L* within a few dB of the historical level, noise ≈ distortion there):
- **The EQP-1A confirms it.** L* is 3.8 dB under 0 VU, and at L* its noise and level-dependent
  character are within 1 dB of each other. Halving or doubling the provisional noise moves L*
  by 1.4 dB.
- **The 351 contradicts it as stated.** L* is 12.8 dB under its aligned operating level, but
  at L* noise and distortion are equal (-49 / -48). The miss is built into the alignment. The
  manual sets 0 VU at 1 % THD at 400 Hz (-40 dB). The 351's noise is -61 dB re a 0 VU vocal,
  so at the period's level the tape runs ~20 dB distortion-heavy. On a tone the least-
  impairment level would be ~7 dB lower (third harmonic falling 2 dB per dB, noise rising 1). On
  the vocal it is 13 dB lower: the character there is intermodulation and HF compression, which
  rise faster than a 400 Hz tone's THD. Read either way: **the period's tape level is 7-13 dB
  hotter than equal weighting asks for**, so engineers chose saturation over hiss, or the ear
  weighs distortion masked by the music far less than A-weighted rms does (the doc's stated
  limit: METHODOLOGY_REVIEW.md W5's masked metric isn't built). The second seems the likelier
  reading, and this measurement can't separate them.
- **The V76 and the 670 aren't forced by their noise at all.** Their modeled noise sits 90-113
  dB under the signal at every level tried, so the least impairment lies under -40 dBFS rms.
  - **The V76 at its 34 dB gain:** -18 dBFS rms in is -15 dBu (its full scale is 0 dB = 0.775 V
    rms, IRT sheet 5), so the output reaches ~+19 dBu and the vocal's peaks clip (character -32 dB
    at -19 in, rising ~10 dB per 3 dB). Its historical point is its *output* near 0 dBu, which
    the grid's bottom (-40 in, about -4 dBu out) already reaches. So "below the grid" agrees
    with history when referred to the output. The doc's "0 VU in" is the wrong reference for a
    mic preamp.
  - **The 670's character at operating level is its gain reduction** (-21 dB re signal: a
    compressor's envelope is "what no fixed filter explains"). The model's 670 noise is known to
    be 49 dB under its spec (COMPONENT_DEPTH_PLAN.md), so noise cannot force its staging
    until that is fixed.

**For the headless mix** (the doc's "if it holds"): a rule "set each stage where noise equals
distortion" gives the EQP-1A's period level. On the tape it gives a level ~13 dB cooler than
the period's, and so *less* tape character than a 1960s record. Period-typical drive on the
tape needs the period's alignment (0 VU = 1 % THD at 400 Hz), not this optimum. The
compressors and the V76 need their own references (threshold, output level).

## Limits

A-weighted rms is a crude ear: distortion products masked by the music count fully here (W5's
masked metric would be the right one). One vocal excerpt, 6 s. The noise's flicker constant and
mains wander are provisional; L* is given at half and double the noise. The 351's character
floor (-26.9 dB) holds whatever the tracker can't follow, so the 351's absolute character is an
upper bound. Only its level-dependent part (the column "over floor") is distortion.

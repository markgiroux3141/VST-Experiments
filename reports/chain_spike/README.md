# Spike: the U47 -> V76 with every gap filled, through repeated passes (2026-11-14)

`uv run --extra fast --extra listen python scripts/chain_spike.py` (production; 23 min of renders on
14 threads at about 20-30x real time per pass, plus a 1.5 min calibration; cached in
`cache/chain_spike/`). This is the experiment of `../chain_passes/production/` (its README covers
the staging, H, the EQ null and the file meanings), on one chain with everything we know it lacks.
Every value and its source is in the script's constants. Each mechanism is a switch.

## What was added

| mechanism | how | level set by |
| --- | --- | --- |
| noise | B5: Johnson noise (resistors, windings, the capsule's acoustic resistances), the tubes' shot and flicker noise, mains wander; a seed per stem and pass | physics (checked below) |
| mismatch | the chain's tolerance draws at spread 1 (R 5 %, film 10 %, electrolytics -20 / +50 %, tubes' emission 10 %, mu 3 %), unit seed 1 | the circuit files' tolerance classes |
| hum: the U47's supply | the NG's 100 / 200 / 300 Hz ripple on its output | 3 uV at the U47's output, inside the NG's published "hum and noise about 5 uV" |
| hum: the V76's heaters | 6.3 V into each cathode through 5 pF and 100 MOhm, centre-tapped windings 2 % off null | typical heater-cathode figures (provisional) |
| hum: T90's field into T85 | 50 / 150 / 250 Hz induced in T85's secondary | fills the V76's noise budget: -121 dB re 0.775 V, 1 dB inside its -120 dB acceptance limit |
| excess noise | carbon-film current noise, 1/f, from each resistor's DC (noise index -20 dB at 1 kOhm, +5 dB per decade) | provisional (application-note figures) |
| capsule | the K47's electrostatic second order: a membrane bulges parabolically, so at constant charge the output has a (x / h)^2 term, 0.215 E0 (x / h)^2 for its 94 % backplate | the capsule's geometry (K47@3) |
| microphonics | three electrode modes of the VF14 (2.2 / 5.1 / 8.7 kHz, Q 40-80) driven by the sound field into its grid | **invented**: each mode's peak 50 dB under the capsule's signal |

Hum, excess noise, the capsule term and microphonics enter the circuit as control inputs: series
EMFs, or Norton sources across the resistors. The capsule term and the microphonic voltage are
computed from the linear capsule. The capsule's electrical back-reaction is negligible, so this is
a first-order perturbation, not a new device.

### Checked against the published figures first

- The V76 with B5's noise: -127.5 dB re 0.775 V (input shorted), -126.7 dB with the 200 Ohm source.
  The acceptance limit is -120.
- **The heaters as first wired failed that limit.** With V2-V4's winding grounded at one end, typical
  heater-cathode figures alone gave -120.7 dB. A unit that passed must have had it balanced, so
  it is centre-tapped here (the drawing shows a hum pot only for V1).
- The excess noise in the V76 is negligible (-143 dB). The T90 field then gets the rest of the
  budget, -122.4 dB (26 uV at 50 Hz in T85's secondary).
- The U47 with B5's noise: 12.8 uV unweighted at its output, mostly below 200 Hz (the 60 MOhm grid
  leak against ~80 pF). That is about 27 dB SPL equivalent; Neumann's "Rauschgrenze" is 24 dB.

## What each one adds, alone, in one pass

At 100 dB SPL, the V76 at 24 dB. The figures are the difference from the nominal, noiseless pass 1,
in dB re the signal over 20 Hz-20 kHz.

| mechanism | bass | guitar | harmonies | lead vocal |
| --- | --- | --- | --- | --- |
| mismatch (a real unit) | -37.0 | -38.2 | -43.1 | -39.6 |
| hum | -73.1 | -72.2 | -60.9 | -64.7 |
| noise | -69.5 | -71.2 | -69.9 | -70.8 |
| capsule second order | -73.5 | -76.3 | -71.6 | -74.6 |
| microphonics (invented level) | -74.6 | -74.8 | -72.7 | -73.5 |
| excess noise | -95.1 | -96.4 | -94.2 | -95.6 |
| *for scale: the chain's own character* | *-28.4* | *-38.8* | *-48.3* | *-41.7* |

The mismatch difference is mostly tone: a different unit is a slightly different EQ and level. The
rest are 20-50 dB under the character the iron and tubes already make. At idle (silence in, the
V76 at 24 dB) the floor is -97.8 dBFS with noise alone and -97.1 with everything. The 50 and 100 Hz
lines stand just above the U47's low-frequency hiss (`idle_spectrum.png`).

## Through 8 passes

The residual (`../chain_passes/production/README.md`, "Correction"; the first version of this report
used the fitted "character", which on this chain was its own floor). Against the dry stem, passes
1 / 2 / 4 / 8:

| stem | nominal | all | all, quiet source (80 dB SPL, V76 at 46 dB) |
| --- | --- | --- | --- |
| bass | -44.0 / -40.9 / -38.7 / -34.2 | -44.0 / -40.9 / -38.7 / -34.1 | -50.1 / -46.0 / -41.8 / -36.4 |
| guitar | -45.6 / -41.0 / -36.7 / -30.9 | -45.9 / -41.3 / -37.0 / -31.3 | -51.4 / -47.2 / -42.6 / -36.9 |
| harmonies | -45.6 / -46.2 / -40.2 / -34.1 | -45.5 / -45.7 / -39.3 / -30.8 | -50.5 / -46.8 / -41.0 / -29.9 |
| lead vocal | -47.8 / -46.3 / -40.1 / -34.6 | -47.0 / -44.6 / -38.5 / -32.0 | -50.4 / -46.0 / -40.8 / -32.6 |

`all_but_microphonics` is within 0.1 dB of `all`. Microphonics as modelled are linear (the tube
rings with the sound), so they are tone, not residual.

## Findings

1. **Filling the gaps at realistic levels doesn't change the result.** Everything together
   moves the 8-pass residual by 3 dB at most, the hum's and noise's share growing on the quieter
   stems.
2. **The mismatched unit's difference (-37 to -43 dB) is mostly a level difference.** Eight units
   of this chain have the same response shape within a quarter dB and the same distortion within
   0.5 dB, but gains 1.2 dB apart (`../chain_study/`). A loudness match removes it. (The UA 610 is
   the exception: its units' distortion spreads 14 dB.)
3. **Noise matters where the source is quiet.** At 80 dB SPL with 22 dB more gain, a pass distorts
   about 5 dB less (-50 against -44 to -48), but the per-pass residual climbs with each pass (the
   harmonies: -50 at pass 1, -45 by pass 8). The early passes' hiss gets every later pass's EQ:
   the omni's generation loss from `../chain_passes/production_noise/`, in a darker chain.
4. **The distortion is the tubes and the BV8** (`../chain_study/`: on bass and guitar the iron
   matches the tubes, on vocal and harmonies the tubes do it). The sourced transformer values move it
   by 2 dB at most. More physics at the micro level doesn't change it; the source level does
   (+10 dB at 115 dB SPL).

## Caveats

- One unit seed (1). Others will differ by a similar amount, in their own direction.
- The microphonics' level and modes are invented. The heater figures and the noise indices are
  provisional. Hum is calibrated to the published limits as a share, not measured.
- The stems' quietest 50 ms blocks are 35-45 dB under their level, so chain noise never shows
  even in the gaps. A floor-growth measure would read the recordings' own floor, so there is none.
- The capsule term and microphonics are first-order perturbations computed from the linear capsule.

## Files

- `<variant>/<stem>/pN.wav`, `pN_tone.wav`, `pN_eqnull.wav`: as in `../chain_passes/`. The variants
  are `all`, `all_but_microphonics` and `quiet_all`. Every file is loudness matched to -23 LUFS.
- `<stem>/dry.wav`, `<stem>/nominal_p1.wav`: the nominal, noiseless pass 1.
- `<stem>/alone/<mechanism>_added.wav`: each mechanism's difference from the nominal pass 1,
  **raised to -30 dBFS rms** (its nature, not its level: the table above has the level).
- `idle_noise.wav`, `idle_all.wav`: the chain's floor with silence in, also raised to -30 dBFS rms.
  The hum lines are audible in `idle_all`.
- `idle_spectrum.png`, `summary.json` (every number, the calibration included).

### Listening path

1. `lead vocal/alone/*_added.wav`: what each gap sounds like by itself.
2. `idle_noise.wav` against `idle_all.wav`: the hum on top of the hiss.
3. `quiet_all/lead vocal/p8.wav` against `all/lead vocal/p8.wav`: noise compounding.
4. `all/<stem>/p8.wav` against `../chain_passes/production/<stem>/u47_v76/p8.wav`: everything filled in
   against the nominal chain. Expect little.

# Sidechain: a keyed 670, a filtered sidechain, a split-band ducker

Drafted 2026-11-01 from a brainstorm with the user. It is parked until the user picks it up,
and nothing in it is built. The user asked two things: how sidechain compression would work
on our 670, and whether a variant could duck only the bass, with a low-pass filter. The order
below is a recommendation; the choices are the user's (Open decisions).

## How the 670 listens today

The 670 is a **feedback** compressor: its sidechain hears its own output. The path, in
`config/circuits/fairchild_670.yaml` (sections "sidechain input" to "rectifier and time
constant"):

`out` (T102's 600 ohm secondary) -> the pad R145 / R147 (150 ohm legs), R149 (1360 ohm
shunt) -> T103 (600 ohm : 170k step-up, centre-tapped) -> AC THRESHOLD (R115A / B) -> 12AX7
-> 12BH7 -> 6973 push-pull -> T104 -> the bridge -> the time-constant network -> the
control voltage on the 6386 grids.

There is no external sidechain input on the original.

## The key input: switch T103's primary

T103's primary is already a 600 ohm line input. So the most plausible mod is a switch on
what feeds it:

- **INT**: the stock pick-off from `out`;
- **EXT**: a KEY jack, a line-level signal at 600 ohms.

That is one `switch` part ahead of T103. Everything after it is unchanged.

**What changes in behaviour.** With an external key the feedback loop is open, so the 670
becomes **feed-forward**:

- Its "ratio" disappears. In the stock unit the ratio comes from the feedback around the
  6386's remote-cutoff curve. Keyed, gain reduction depends only on the key's level.
- AC THRESHOLD becomes a sensitivity control. The time constants become the duck's attack
  and release (TC1's ~0.3 s release suits pumping).
- **Thumps.** The 6386 pair is push-pull, so a moving control voltage mostly cancels. Hard
  ducking at a fast TC lets any imbalance through as thumps. The per-tube mismatch draws and
  the BALANCE setting produce that on their own. It is real character; measure it rather
  than hide it.

## Two meanings of "duck the bass with a low-pass"

### (a) A filter in the sidechain: the bass triggers, the whole signal ducks

- The filter goes at the pick-off, in the 600 ohm world ahead of T103, so one filter covers
  both push-pull legs. (At the 12AX7 grids it would need a matched pair.)
- A first estimate at 150 Hz: a 2nd-order Butterworth between 600 ohm terminations, about
  **0.9 H in series and 2.5 uF shunt** (provisional: to be redesigned against the real
  terminations, T102's secondary as the source and the pad plus T103 as the load).
- The inductor is iron-cored. Model it as one winding on a Jiles-Atherton core (the
  `transformer` macro), so loud bass saturates the detector's own filter. The 670 never
  had this physics; a real mod would.
- A rotary switch: **FLAT / LP / HP**. The HP position (the common pro mod: stop the bass
  from pumping the whole mix) costs almost nothing extra.

### (b) Split-band: only the bass gets ducked

- A passive crossover at 600 ohms splits the input.
- The low band goes through channel 1's 6386 stage, keyed.
- The high band goes through channel 2's 6386 stage at a fixed bias (its sidechain
  disconnected), so both bands get the same tube and transformer colour.
- The bands are summed (a summing transformer or a resistive mixer).
- Push-pull transformers make polarity inversion free (swap a winding's ends), so an LR2
  crossover with one band inverted sums flat at 0 dB of gain reduction.
- Under ducking, the crossover region shifts in phase and dips. That is the real artifact
  of doing this in hardware: worth hearing, not hiding.
- A real engineer could build it from a stereo 670, a passive crossover and a summing
  transformer.

### Which one when

For "the kick ducks the bass": **(a) on the bass track, keyed from the kick, with the LP on
the key.** A bass track is mostly lows anyway, and the LP makes the key respond to the
kick's thump rather than its click or bleed. (b) is for ducking only the low end of a full
mix or a dense bus.

Related, period-correct: the stereo 670's LAT / VERT mode compressed the sum and difference
for vinyl cutting. The vertical (L-R) channel's job was largely to tame out-of-phase bass
that would throw the cutter. It needs the full stereo unit (the matrix), so it isn't a
first step.

## What it costs in this codebase

- **New circuit files.** `fairchild_670_keyed.yaml`, later `fairchild_670_splitband.yaml`.
  `fairchild_670.yaml` stays as it is, so its goldens and fixtures stay byte-identical. They
  could also be drawn in the native editor from `fairchild_670_drawn`.
- **The key as an input.**
  - The quick path is the existing control inputs (`cv_inputs`, S3). They work now with no
    engine change. They interpolate linearly between samples, which is fine for a detector,
    especially a low-passed one (production's 5th-order input interpolation isn't needed
    there).
  - The catch: ngspice runs no control inputs, so the keyed path wouldn't be cross-checked.
    The fix is small: a second filesource in `io.run_transient`.
- **Split-band.** Channel 2 is lumped onto the rails today ("channel 2 (idle, lumped)"); it
  would become a full signal path. DK's cost grows with the square of the states, but the
  N-way partition fits well: the two channels share only the supply rails, so channel 1 |
  channel 2 | supplies, each on its own thread. Measure with `examples/load_profile.rs`.
- **The native app.**
  - Session inserts need a "key from track X" route (SESSION_FX_PLAN.md).
  - A print's cache key must include the key track's audio hash.
  - The live timeline source feeds two streams.
  - The web app gets nothing.
- **Measurement (a profile for the keyed unit).** Gain reduction vs key level; duck depth
  and recovery per TC; thump level vs BALANCE and mismatch; for (b), the sum's flatness at
  0 dB of gain reduction and the crossover dip under ducking.

## Proposed milestones

- **K1: the keyed 670.** The INT / EXT switch on T103's primary, the key as a control
  input, one channel. Done when a kick-keyed bass ducks in a render and the profile above
  measures it.
- **K2: the sidechain filter.** FLAT / LP / HP at the pick-off, the inductor on a JA core,
  values sourced or provisional with bounds.
- **K3: the key in the app.** The insert's key route, prints keyed on both inputs, live play
  of a keyed insert.
- **K4: split-band** (only if (a) on a bass track isn't enough). Channel 2 as a full path,
  the crossover and the summing, partitioned for real time.
- **Optional:** the key in ngspice (a second filesource) for the cross-check.

## Open decisions (the user's)

- **Which meaning:** (a), (b), or (a) first (recommended)?
- **The key:** from another track (kick -> bass), or the same signal filtered?
- **The filter's frequency:** fixed at ~150 Hz, or a switch of a few frequencies, as a real
  mod would have?
- **Where it goes in the order** relative to the other parked tracks.

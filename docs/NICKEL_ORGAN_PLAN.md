# The Nickel Organ

An invented magnetostrictive bar organ (docs/INVENTED_DEVICES.md, I1), built 2026-11-06 at
the user's request ("build the first one in the list so I can hear what it sounds like").
Every part existed by 1955; only the topology is invented. It is offline Python for now
(the RH1 / D1 pattern): `varimu/nickel/`, `config/nickel/organ.yaml`, `tests/test_nickel.py`.

## The manual

**What it is.** Sixty-one brass bars (C2-C7), each clamped at one end like a Rhodes tine. A
strip of laminated nickel is bonded to each bar's top face at the clamp, inside a coil. The
coil both drives the bar and hears it:

- **Driving (magnetostriction).** Nickel shrinks when magnetized either way (lambda_s = -35
  ppm). Shrinking the strip bends the bar.
- **Hearing (the Villari effect).** Bending stresses the strip, and stress changes its
  magnetization. The coil sees that as an EMF.

Each key has its own tube loop: the bar's EMF in, amplified, and back into the same coil.
The loop sets the note ringing, or keeps it ringing. A #327 pilot lamp in the drive line is
the AGC: as the drive heats it, its resistance rises and the loop's gain falls.

**The panel.**

| Control | What it physically is | What it does |
|---|---|---|
| SUSTAIN | an audio-taper pot setting the loop's gain | below ~0.6 a struck bell with a longer ring; above it the note sustains like an organ, blooming as the lamp catches the level (the lamp's thermal lag); near full, the lamp glows past its rating and the driver clips |
| POLARIZE | a DC winding on the shared yoke, every strip's bias | low (0.05-0.25): loud, growly, a strong 2nd harmonic (nickel's square law half-linearized); default 0.35: cleaner; high: quieter (the strip near saturation couples less); zero: silent on a demagnetized strip (no first-order coupling), see "Remanence" |
| velocity | the felt hammer's speed (0.02-0.25 m/s) | harder strikes ring brighter (shorter contact) and swing the strip's stress further, where nickel loses coupling and gains loss: a hard strike rings as a bell, then settles onto the sustained tone |

**Inside, per key** (config/nickel/organ.yaml has every value and its source):

- **The bar.** Brass, 3 x 8 mm, 33-170 mm long (tuned by length). The nickel strip (five
  0.1 mm laminations) covers a quarter of it from the clamp, 10-40 mm.
- **The coil.** 400 turns. Its twin is wound alike on an identical strip on a blocked bar.
  The two sit in a bridge (1.5k arms, 100 ohm across the top), so the twin cancels the
  coil's own hysteretic inductance and only the bar's motion comes through.
- **The amplifier.**
  - The bridge's difference through a 1:1 input transformer and a 26 dB pad.
  - Two 12AX7 stages, 100k plates, 0.01 uF / 1M couplings (16 Hz).
  - SUSTAIN, a per-key voicing trim, then a two-section RC ladder voiced to the key (its
    pole at 2.5x the note, at most 4 kHz).
  - A 12AU7 driver into a triode-connected 6V6GT and a 5:1 output transformer.
  - The #327 in series to the bridge.
- **Its line out.** V1b's plate, through the key's mixing resistor.

**Voicing (the factory procedure, `organ.voicing`).** Each key is struck softly twice, its
loop open and slightly closed. The gain at which its fundamental stops decaying is its
onset, and its trim puts that onset at SUSTAIN 0.6. C2 needs more than a passive trim can
give: its onset is at ~0.66. The same soft strike sets the key's mixing resistor, because
the Villari EMF falls with frequency and the bass is ~13 dB down unvoiced.

## The physics (what's modeled)

- **One coupled system per key** (`voice.py`): the bar's modes, both strips, both coils, the
  bridge, every tube stage at its plate, the lamp's filament heat, the hammer and the
  damper. Stepped at 192 kHz.
- **The bar.** Euler-Bernoulli FE (varimu.rhodes.beam's elements), composite over the strip.
  Q 1500 on the fundamental, falling as (f1 / f)^0.5 over the bell partials (1 : 6 : 17).
- **Nickel.** varimu.devices.core's Jiles-Atherton form, fitted to handbook figures (the fit
  can't meet all four: mu_max and Hc +53%, Br -34%).
- **The magnetoelastic coupling.** From one energy, 1/2 E V (eps - lambda(M))^2: a force on
  each mode and Sablik & Jiles' stress field on the strip. It is reciprocal and even in M.
- **Two numerical guards.**
  - core.py's DEN_FLOOR on JA's pole. Big stress swings move nickel's effective field by
    kA/m, and the pole was crossed.
  - A direction consistency rule: each step's JA direction must match the step's own change
    of M, else the reversal's reversible susceptibility. Without it, delta chattered every
    step and drained M to zero.

## Status (2026-11-06)

Built and heard offline:

- `scripts/nickel_organ_study.py` -> reports/nickel_organ/first_experiment/: the POLARIZE
  sweep, remanence and the strip's memory, with WAVs.
- `scripts/nickel_organ_render.py --demo | --midi F` -> reports/nickel_organ/renders/.

Speed: ~11x slower than real time per sounding key (scalar Python at 2x oversampling).

**The first experiment's findings** (A4, SUSTAIN 0.75, velocity 100; summary.json,
study.png):

| POLARIZE | M / Ms | held | fundamental | 2f | lamp |
|---|---|---|---|---|---|
| 0 (virgin) | 0 | silent (noise, 7.5 mV) | -81 dB | -80 dB | 300 K |
| 0.02 | 0.03 | 1.45 V | +2.5 dB | -14.5 dB | 2386 K |
| 0.05 | 0.11 | 24 V | +25.2 dB | +21.1 dB | 2576 K |
| 0.10 | 0.27 | 25 V | +26.7 dB | +16.6 dB | 2898 K |
| 0.18 | 0.44 | 22 V | +26.4 dB | +9.3 dB | 2674 K |
| 0.25 | 0.54 | 17 V | +24.0 dB | +4.2 dB | 2655 K |
| 0.35 (default) | 0.64 | 3.1 V | +8.0 dB | -23.0 dB | 2593 K |
| 0.50 | 0.73 | 0.52 V | -6.2 dB | -44 dB | 2384 K |
| 1.00 | 0.85 | 0.14 V | -18.4 dB | -62 dB | 1470 K |

(dB re 1 V rms at the line out, the held note's last half second.)

- **POLARIZE is a timbre and level control.** Near zero bias the loop is weak. Around
  0.05-0.25 the strip is half-linearized: loud, with a 2nd harmonic within 4-21 dB of the
  fundamental (the growl). Toward saturation the coupling falls: quieter and purer.
- **No sub-octave.** The brainstorm's guess, a parametric loop at half the bar's pitch at
  zero bias, doesn't happen in this design: f/2 sits at the noise floor at every setting,
  even with SUSTAIN full and a hard strike. At zero bias the drive goes as i^2 and the
  Villari signal as M sigma, so the loop's gain vanishes at small amplitudes and nothing
  starts it.
- **Remanence is real but can't sustain.** Played at the default bias, then POLARIZE to
  zero: the strip keeps M = 0.098 Ms. It still hears a strike (1.1 V against 7.5 mV for a
  virgin strip), but the note decays (the loop is below its onset there). A second, hard
  strike at full SUSTAIN was near-silent. The likely reason (not measured) is that the
  first zero-bias note's AC drive walked the remanence down: an AC demagnetization.
- **The strip's memory of strikes is a one-time shift.** The first strike after power-on
  moves M from 0.638 to 0.656 Ms (stress cycling pulls it toward the anhysteretic, Jiles'
  magnetomechanical effect), at any velocity, and later strikes move nothing. "It
  remembers how it was just played" isn't there with JA. Preisach's return-point memory is
  the candidate (below).

**Design changes the experiment forced** (each in the config's sources):

- The loop motorboated at ~5 Hz. The bar's stiffness passes the Villari signal below its
  fundamental, so the high-passes were raised to 15-16 Hz, three of them.
- It oscillated at ~44 kHz (the live and twin strips' inductances differ). Fixed by the
  drive ladder.
- The bass's higher modes won the loop. Fixed by the ladder voiced per key.
- The 6V6GT as a pentode is a current source, so a series lamp can't regulate it.
  Triode-connected now.
- The 20 dB pad overdrove V1a and V1b; 37 dB starved the loop. A 26 dB pad and the 12AU7
  driver now.
- A soft felt only pushed the bar statically. Its K is now a hard felt's.

## Not built yet (next, the user's call)

- **The shared yoke.** One note biasing its neighbours; chords interacting magnetically and
  through the rail.
- **The mounting rail as a modal medium.**
- **A live tier.** A magnetoelastic device in circuitsim, the bar a medium like the harp's.
  Only if the instrument earns one.
- **Preisach instead of JA for the strip.** JA's minor loops ratchet (S1's open problem);
  the strip's memory of strikes is exactly a minor-loop question.
- **Smaller items.**
  - The 6V6GT's grid current: left out.
  - Tube capacitances: left out. The amplifier is solved at its plates with one step of
    loop delay.
  - Per-strike variation.

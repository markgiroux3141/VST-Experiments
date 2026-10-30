# The tube synth's low end: findings and options

Exploration only (2026-10-30): nothing here is built, and no file in the repo was changed
to produce it. The circuit is `config/circuits/tube_synth.yaml`; the plan is
[TUBE_SYNTH_PLAN.md](TUBE_SYNTH_PLAN.md) (S4).

**The question:** the synth doesn't sound like it has much bass. **The goal:** a lower
playable range that stays reasonably in tune.

## What was measured

All at draft quality with the app's four-thread partition, JA cores, a key held
(gate -1 V), the panel at its defaults unless noted. The scripts were throwaway (session
scratchpad); the method is below so it can be redone.

**The voice passes bass.** Tones of 0.1 V peak into the external input, levels read by a
lock-in over the last 1 s of 2.5 s. Output (`out`), dB re 1 kHz:

| Hz | 20 | 30 | 50 | 70 | 100 | 150 | 220 | 330 | 1000 |
|---|---|---|---|---|---|---|---|---|---|
| dB | +5.9 | +6.9 | +7.6 | +7.9 | +8.2 | +8.5 | +8.5 | +7.9 | 0 |

That's the reactor low-pass at cutoff 0.3. Every coupling capacitor and both transformers
(TIN, TOUT) pass the low end; nothing between the mixer and the output removes bass.

**Low notes are as loud as mid notes.** Held notes, external input silent:

| Pitch input | Note | Out, dBFS rms (WAVE 0.5) | Out, dBFS rms (WAVE 1.0) |
|---|---|---|---|
| -23 V | 59 Hz | -15.2 | -6.8 |
| -21 V | 128 Hz | -14.7 | -6.8 |
| -15 V | 477 Hz | -15.1 | -9.4 |
| -10 V | 870 Hz | -20.1 | -15.8 |

At WAVE 0.5 the bottom notes are mostly fundamental (H2 ~11 dB under it, H3 ~15 dB).
At WAVE 1.0 the oscillator's V1A plate is a clean, sharp-edged pulse (~25% duty at 59 Hz)
and the output a filtered, saw-like wave. (Lock-in readings of H5 and up weren't reliable:
the pitch wanders slightly over the window and smears them; the waveforms are the better
evidence.)

## Why it sounds light on bass

1. **The floor is ~59 Hz (B♭1).** The app's tuning table (`TUBE_SYNTH_TUNING` in
   `crates/varimu-app/src/panel.rs`, from `reports/tube_synth/vco/synth_tuning.json`)
   starts at -23 V; every key below holds there. Below -23 V the tank's swing saturates
   the reactor cores and the pitch law isn't monotonic. The lowest bass octave (E1 is
   41 Hz) doesn't exist.
2. **At the default panel, low notes are near-sines.** A near-sine at 60-120 Hz is felt
   more than heard; on headphones or near-fields, "bass tone" is mostly harmonics 2-5.
3. **The output is fairly quiet (~-15 dBFS rms).** Hearing loses bass faster than mids as
   the level drops.

Quick check with no changes: WAVE towards 1, cutoff opened a little.

## What decides tuning at the bottom

Two separate things:

- **The tuning table is coarse (deterministic).** One point per volt; at the bottom one
  volt spans 59 → 88 Hz, ~7 semitones, interpolated in log frequency. Measuring at
  0.1-0.25 V steps fixes it.
- **The pitch law is steep (physical).** Measured slope: ~7 semitones/V near 60-90 Hz,
  ~5 near 150 Hz, ~2.7 near 450 Hz, under 1 at the top. A steep law turns small
  grid-voltage movements (noise, supply sag, mains wander) into pitch: ~10 mV is ~7 cents
  at the bottom. The noise study found the lowest note moved most for this reason.

Pitch goes as 1/√(LC), so log f = -½ log L - ½ log C: the slope in semitones per volt
doesn't depend on the tank capacitor. Changing C shifts the whole law without changing
its shape; the steep part moves down with it.

## Options

| | Option | What it does | Tuning at the bottom | CPU |
|---|---|---|---|---|
| A | Finer tuning table | Re-measure -23..-15 V in fine steps | Fixes interpolation error only | None |
| B | Larger tank capacitor (`osc_c_tank_f` 56 → 224 nF) | Whole range one octave down: ~29-870 Hz | Same steep law, an octave lower | No new parts; per-step cost unchanged |
| C | Octave switch (56 / 224 nF, or another value) | Keeps the top on one range, adds a low one; a tuning table per range | Low range can be chosen so bass notes land on its gentler middle | As B; flipping it restarts or rewires the stream (a brief gap), fine between notes |
| D | Less tank drive (`osc_r_tail_ohm` 100k → larger) | Delays saturation, so the law may continue below -23 V | Probably steeper still (nearer the 6V6GT's cutoff) | None, maybe slightly less |
| E | Sub-octave divider (a 12AU7 flip-flop) | Plays f/2 or f/4 of a note the oscillator plays higher | The oscillator's own tuning; f/4 puts 29-59 Hz on its 118-236 Hz stretch | The only one with real cost |

**B and C in more detail.** 4x C halves the frequency and halves the tank's impedance
(√(L/C)), so the same drive current gives about half the voltage. Flux per cycle goes as
voltage over frequency, so it should stay about the same and the cores shouldn't saturate
sooner (estimate, not measured). The risk is the halved impedance: going from 2000 to 1000
turns per core also halved it, and the oscillation stopped above ~100 Hz. One large
capacitor probably trades away the top end; C keeps both. The drive coupling (`osc_c_drive_f`,
0.47 µF, "below the sweep's bottom") would need checking at the new bottom.

**E in more detail.** Period-correct: the Novachord, whose keying the synth already
borrows, built its notes from tube divider chains. Its tone is a square, good bass
material through the filter.

## CPU load

- **A-D:** no new tubes and no new energy-storage elements, so the cost per step is
  unchanged. The oscillator's cost comes from the two cores swinging around their loops
  each cycle and rises with pitch (vco_lc: ~0.5 of a core at mid pitch, ~1.0 at the top),
  so a range shifted down is if anything cheaper. Unknown: Newton's iteration count if the
  low range runs the cores nearer saturation. Needs a measurement.
- **E:** two more tube sections (44 → 46 device ports) and a few more states (~80 → ~84).
  DK's linear algebra grows roughly with the square of the states, so ~+10% on the thread
  that holds it, plus extra solver work at each switching edge (only 60-120 edges a second
  at bass rates). The synth runs at ~62-88% load with worst blocks at 99-133%, so this is
  the one option that could cause dropouts.

## Recommended next step

A first, since it combines with anything. For the range, C: an octave switch whose low
capacitor is chosen by measurement rather than fixed at 4x.

The study to run (outside the repo, or as a `scripts/vco_study.py` option): sweep
`osc_c_tank_f` over 56 / 112 / 224 / 470 nF and report, per value:

- the range and the monotonic floor
- semitones per volt at each note
- whether the top still oscillates
- the oscillator thread's time per step (`examples/load_profile.rs`)

That shows which value puts E1-A1 on a usable stretch of the law, and whether the divider
(E) is needed at all.

## How the measurements were made

`builder.build_ir(spec, spec.resolve(spec, overrides), cores="ja")` with probes on the
nodes of interest; `io.TransientSettings.from_sim_settings(engine="circuitsim",
quality="draft")` with `full_scale_volts_peak=1.0` and the app's partition
(`input, filter, resonance, cutoff | oscillator, pitch | power supply, bias supply`);
`fast.run_transient(ir, x, settings=..., controls={"gate": -1 V held, "pitch": V held})`,
as `tests/test_tube_synth.py` does.

- **Response:** a 0.1 V peak sine into `in` (faded in over 0.2 s), pitch -15 V, 2.5 s,
  lock-in at the tone over the last 1 s, per node (mix, s, f, k2, a6d, tp, g3a, out).
- **Notes:** input silent, 2 s, pitch from `vco.frequency` on `o_t` over the last 1 s,
  out rms in dBFS at 3.5 V full scale.

# Master quality: the tube synth rendered with compute to spare

Drafted 2026-11-04 from a conversation with the user. They asked what a high-quality
offline mode would spend its compute on, then said: "I'd want to incorporate all of this
for a production setting." Its decisions are settled (below). Nothing is built.

## Why

The tube synth was shaped by real time:
- **The partition.** Six threads that see each other one sample late, with leaks and
  coupling capacitors added to hold the cut nodes (`tube_synth.yaml`'s `numerical:`
  sources and the partition notes in its values).
- **Features off.** Both oscillators at once are over budget, and PULSE was parked for
  CPU (SYNTH_IDEAS.md #5).
- **A minimal circuit.** DK's cost grows with the square of the states, so every part
  that only adds texture was left out.
- **The saw on event kernels** (K), which read sharp of the full model in the bass
  (HYBRID_PHYSICS_PLAN.md, H4).

[MIDI_TAKES_PLAN.md](MIDI_TAKES_PLAN.md) makes a take its notes, rendered offline, so the
final render's only budget is wall-clock time. This plan says what to spend it on.

**The principle: spend the compute on physics, not on numerics.** Draft is ~-50 dB from
production and production ~-64 dB from the converged solution (sim_settings.yaml), and
the waveform residuals at that level are below audibility. What real time couldn't
afford is the physics: parts, coupling and features that were cut. The exception is
self-oscillating circuits, where numerical error shows up as pitch and waveform, not as a
small residual (Q2).

**Measured and dropped:** capacitor dielectric absorption and leakage. On the synth, DA
moves the held pitch by a fixed -3 cents (the tuning absorbs it) and the envelope shows
no audible memory, at 1.5x the render time (DEVICE_BUILDER_PLAN.md B6, "Capacitor
leakage and dielectric absorption"). It belongs with aging (B7), not here.

## What master is

A quality, `master`: a `circuitsim_master` block in sim_settings.yaml on top of
`circuitsim`, read by Python's renders and varimu-app's render (and so by takes and
prints). Production keeps its meaning for every device (decision 2). Master has three
layers:

1. **The solver.** Production's method (esdirk4 with error control) unless Q2's study
   says otherwise. No partition: one coupled solve, the poly circuit too (decision 3).
   The saw as its multi-rate island (M1) at the substeps where its pitch converges.
2. **Render-only features.** Panel features that can't run live are available: both
   oscillators, PULSE with a sharp core, ring and saw together. The panel still decides
   whether they're on. The MIDI takes plan marks them "heard in the render only".
3. **Detail.** Parts that build only at master: stray coupling, ground impedance,
   distributed windings, fuller core loss, noise sources still missing. A circuit file
   marks them, and builds at other qualities are unchanged (Q4).

**Tuning follows the quality.** A take stores keys, not volts, and the render maps each
key through the tuning table measured at the render's own quality. Detail shifts the
pitch (strays load the tank), so master gets its own tables: `vco_study.py --tuning
master` and `saw_884_tuning.py`. Otherwise a take played at draft renders out of tune at
master, as the saw's K-vs-M1 bass offset already does at production.

## The levers

| # | Lever | What it does to the sound | Cost | Where it's built |
|---|---|---|---|---|
| 1 | One coupled solve (no partition) | Sag, ripple and pulling between blocks with no sample of latency; voices pulling on one supply in poly | 1 thread; ~16x a voice for 4 voices | Q1, Q8 |
| 2 | Render-only features | Both oscillators, PULSE's buzzy magnetic PWM, ring + saw | Each a thread's worth live; in one solve, states | Q3 |
| 3 | Oscillator numerics | Pitch drift after a glide (production still drifts ~4 c), cycle-to-cycle jitter, edge shape, the saw's bass pitch | Higher oversampling or tighter error control; the saw at >= 16x substeps | Q2 |
| 4 | Stray magnetic coupling | The power transformer's field into the reactor cores (the reactor is a magnetometer): buzz in the cutoff and the pitch that grows with supply load | An external-field term per core; a layout | Q5 |
| 5 | Ground network | Charging pulses through shared returns: program-modulated buzz, interaction between blocks | A few R / L per return path | Q5 |
| 6 | Stray capacitance | Oscillator bleed through a closed VCA, HF crosstalk, the Q multiplier's top end | A capacitor per named pair | Q5 |
| 7 | Distributed windings | Each winding as a ladder of sections: the reactor's, ring's and output transformer's top end, the ring's carrier leak | States per section | Q6 |
| 8 | Core loss beyond classical eddy | Excess loss and lamination skin effect: the filter's Q and the oscillator's high end | Per core | Q6 |
| 9 | Minor loops: Preisach reactor cores (decision 4) | No more ratchet scoop after each move; closed loops with return-point memory, so the pitch and cutoff depend on the direction a setting was approached from | Preisach costs more than JA | Q6 |
| 10 | Missing noise | Carbon resistors' excess noise, heater hum through heater-cathode leakage and capacitance (AC heaters) | ~+0.15x real time each, as B5's | Q7 |
| 11 | Unit variation | Per-voice tolerance draws (voice cards that differ), chassis warm-up drift through tempcos | ~0 at run time | Q7 |

**Not levers** (measured, or below anything audible): exact tube sections instead of
tables (~1e-7), tighter Newton tolerance (production's is -74 dB from 10x tighter),
ngspice, more output oversampling, capacitor DA and leakage.

## Milestones

Every lever is measured before it becomes a default, the way B5 and B6 were measured:
- the difference re output and octave levels;
- the synth's own metrics: cents, jitter, the hum spectrum, bleed with the gate closed;
- render time;
- then a blind A/B, loudness-matched.

Results go to `reports/tube_synth/master/`. The user's rule applies: a difference too
subtle to prefer counts as verified, and we move on.

**Q1. The quality and its reference.**
- `circuitsim_master` and `--quality master`: Python's render, `varimu-app`'s render,
  prints and takes. The app's master render equals Python's bit for bit
  (`app_render_agreement.py --quality master`).
- No partition at master, so the `partition` lists don't apply.
- The saw's M1 substeps as a quality setting.
- Master tuning tables (above), and keys mapped through the render quality's table.
- A fixed test take, `scripts/master_take.py`, as data: held notes at both RANGEs,
  glides, ring on, both oscillators, a release tail, and (for Q8) chords.
- The converged reference render of it: radau5 at 8x, tight tolerances, the saw at 32x.

*Done when:* the test take renders at master in both builders bit for bit, the converged
reference exists, and its render time per second of audio is reported. Nobody has
measured the whole synth at production yet (MIDI_TAKES_PLAN.md N6), so this also gives
the baseline.

**Q2. The numerics study** (`scripts/master_study.py`).
- Production, and production at 4x and 8x, against the converged reference:
  - pitch track after glides;
  - cycle-to-cycle jitter;
  - phase noise around the fundamental;
  - aliasing (the square, the ring's products);
  - edge rise time;
  - envelope times.
- The partition against one solve on the same take, which states lever 1's size.
- **The saw's bass first:** the whole circuit's KCL at `n` doesn't close by ~0.3 uA at
  16x (HYBRID_PHYSICS_PLAN.md H4). That may be a bug rather than physics. Find it before
  choosing substeps.

*Done when:* master's solver settings are chosen from the numbers (oversampling, error
tolerances, substeps), and each setting's distance from the reference and its cost are
in the report.

**Q3. Render-only features.**
- PULSE built into tube_synth with the sharp core, which runs only at production (3 mm^2:
  16x slower than real time; SYNTH_IDEAS.md #5). Behind its switch, so other qualities
  build without it.
- A device's render-only panel features, so the app marks them for the MIDI takes plan.

*Done when:* a take with both oscillators, PULSE and ring on renders at master, and
PULSE's pulses and PWM are measured as in the prototype.

**Q4. Detail in circuit files.**
- A part or section marked `detail: master` builds only at master. Both builders support
  it, with the same precedent as `events:` swapping kernels for islands.
- An IR without detail is unchanged, so `export_circuit_fixtures.py --golden` shows no
  diff.
- `varimu check` runs the pre-flight checks with detail built too.

*Done when:* a test circuit builds with and without detail in both builders
(`tests/agreement.rs`), and the golden fixtures don't move.

**Q5. Strays** (FUTURE_DIRECTIONS.md section 4's design, applied to the synth).
- A **layout** block: positions, orientations and shields (mu-metal cans) of the
  magnetic parts, as physical, bounded parameters with sources. Its default is a
  well-built unit (realistic first). Bending it, such as a reactor next to the mains
  transformer, is a later panel or condition dial.
- **Stray magnetic coupling** by a dipole law into the cores. This needs an
  external-field term on the JA core node in `varimu/devices/core.py` and circuitsim's
  `devices/core.rs`, with an agreement test. Linear inductors use IR `Coupling`.
- A **ground network** replacing the ideal node: star versus daisy chain as a layout
  choice.
- **Stray capacitances** between named nodes: the oscillator's wiring past the VCA, the
  mixer, the Q multiplier.

*Done when:* the idle hum and buzz spectrum at the output, its growth with a chord's
supply load, and the oscillator's bleed with the gate closed are measured. Each is
compared with period figures where a source exists (a vs_670-style comparison, never a
rejection), and the options come to the user with numbers.

**Q6. Magnetics.**
- **Distributed windings:** the reactor's, ring's, output and power transformers' windings
  as n-section ladders. C2's compiler already has the geometry and the layer
  capacitances (`varimu-components`), so a design compiles a section count, and the hand
  values of tube_synth's transformers become designs.
- **Core loss beyond classical eddy:** excess loss and lamination skin effect for the
  reactor cores, as a material option.
- **Minor loops: a Preisach core for the reactor at master** (decision 4).
  - A new core kind on the tape's continuous ensemble (`varimu/devices/preisach.py`),
    fitted to mumetall's figures and its Rayleigh region (`config/magnetics.yaml`), as the
    JA fit was.
  - The Python reference and circuitsim, with an agreement test.
  - Opt-in per core and built only at master (`detail: master`), so the live JA cores
    and every existing render are unchanged.

*Done when:*
- each item's effect on the filter's response, the oscillator's range and top end, and
  the ring's carrier leak is measured;
- the Preisach reactor's minor loops close within a few cycles and show return-point
  memory (tests);
- the master tuning tables are re-measured on it;
- a blind A/B of JA and Preisach on the test take is in front of the user.

**Q7. Noise and variation.**
- Carbon composition resistors' excess noise (1/f, current-dependent).
- Heater hum through heater-cathode leakage and capacitance, with the heater supply as
  AC.
- **Tolerance draws in Rust:** lift varimu-circuit's nominal-only rule by porting the
  seeded draws (SYNTH_IDEAS.md #17; MIDI_TAKES_PLAN.md decision 13). Each poly voice
  draws its own parts.
- **Chassis warm-up:** a chassis temperature that rises over minutes, acting through the
  parts' tempcos (FUTURE_DIRECTIONS.md, thermal: static ambient and warm-up first).

*Done when:* each one is measured on the test take, Rust's draws equal Python's for the
same seed, and a 4-voice chord's voices measurably differ.

**Q8. Poly at master.** `tube_synth_poly` (MIDI_TAKES_PLAN.md N6) as one solve, all
detail on.

*Done when:* a poly take renders at master reproducibly, its cost per voice is
reported, and production's per-voice partition is checked against it (N7's check, with
master as the reference).

## Order

Q1 and Q2 first: they set the baseline and the reference, and may find a bug (the saw).
Then Q3 and Q7, the cheap wins. Then Q4-Q6, the expensive physics. Q8 last, after
MIDI_TAKES_PLAN.md's N6.

## Decisions

1. **The user's (2026-11-04): incorporate every lever into the final render.** Each is
   built and measured. Any that is costly and inaudible comes back as an option rather
   than a default.
2. **The user's (2026-11-04): a new quality `master`, production unchanged.**
   - Production stays what every device renders at, Python and the app agree on it bit
     for bit, and its caches stand.
   - Master is production's solver settings (adjusted by Q2) plus detail and no
     partition.
   - Raising production itself for the synth was the alternative, not taken.
3. **The user's (2026-11-04): poly runs as one solve at master only.**
   MIDI_TAKES_PLAN.md decision 8 (per-voice partition) stands for draft and production.
4. **Minor loops: Preisach for the reactor cores at master.** The user delegated this
   ("whatever would sound cooler"); this is Claude's pick. Why:
   - JA's ratchet is a model artifact. Every control move (a new note's pitch, a cutoff
     turn) scoops and settles for 0.3-3 s, and real nickel-iron's loops close within a
     few cycles (TUBE_SYNTH_PLAN.md S1).
   - A Preisach core has what real magnetic amplifiers have: return-point memory, where
     the pitch and cutoff land depending on the direction a setting was approached from,
     and accommodation over a few cycles.
     That's character no other synth has, and it is the realistic one (realistic first,
     then bend).
   - The tape's continuous ensemble (`varimu/devices/preisach.py`) already exists, with a
     closed-form step and a discrete oracle for tests. That makes it less work than a JA
     minor-loop correction with nothing to fit it to.
   - Its extra cost doesn't matter offline.

   Live (draft) keeps JA, so the master render's settling after a note differs from what
   was played. Q6's A/B puts the two side by side. If Preisach sounds duller, the
   ratchet comes back as a deliberate bend (a panel choice at master), not as the default.

## Cost

Unknown until Q1 measures it, but plan for slow:
- The VCO alone runs 3.4x real time at production.
- The whole synth with both oscillators is more.
- Detail adds states, and DK's cost grows with their square.
- 4 voices in one solve are ~16x a voice.

A minute's poly take may take hours. That's acceptable offline: takes render in
parallel on separate cores, and the render behind keeps the user playing on the draft
meanwhile. If it's too slow, the fallbacks are parallel in time (TAPE_SPEED_PLAN.md P3)
and the per-voice partition at master too (the user's call).

## Risks

| Risk | Answer |
|---|---|
| Master sounds unlike what was played (draft or proxy) | Tuning per quality; the take's lane says which quality it plays; an A/B of draft and master in Q2's report. The Preisach reactor (decision 4) is the biggest such difference: Q6's A/B |
| Strays invent hum a good unit wouldn't have | Sourced layout values, shielding as built; the default is a well-built unit |
| Detail breaks convergence (sharp PULSE cores at reversals, a stray capacitance closing an oscillating loop) | The pre-flight checks with detail; the plausibility screen's oscillation check on the test take |
| The saw's bass offset is a bug, not physics | Q2 looks at the KCL mismatch before choosing substeps |
| Render times make iteration painful | Draft renders behind for iteration; master on demand (MIDI_TAKES_PLAN.md N3's badge) |

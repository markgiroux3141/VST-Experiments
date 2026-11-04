# Hybrid physics: exceptions for physics too fast to simulate

Drafted 2026-11-01 with the user, after a brainstorm about the tube synth's missing
sawtooth. Nothing in it is built.

## The idea (the user's)

Everything keeps being synthesized "the pure way": the circuit's physics, one coupled
simulation. Some physics is too hard for the audio solver's grid: an event far shorter
than a sample, a carrier far above Nyquist, a field spread through space. Only that
piece becomes an **exception**: a cheap stand-in *derived from a full-physics simulation
of the same part*, coupled to the rest of the circuit through its ports. The instruments
become hybrids: real physics, plus measured exceptions where the physics is out of
reach. The gas-tube sawtooth is the first one. Others will follow (see Candidates).

**What an exception is not:** a behavioural model tuned to sound right. Its content
comes from a reference simulation of the physics, never from a target waveform. If the
part's design changes, the exception is regenerated from the new reference. Nobody
retunes it.

## Why some physics is hard here

At 96 kHz a sample is 10.4 us. A relaxation oscillator (sawtooth, multivibrator,
flip-flop) spends most of its cycle on a slow ramp, which is easy, and then resets in
roughly 1-10 us (provisional: model knowledge, to be measured in H2). That reset causes
three problems:

1. **Newton.** During a regenerative flip the device is extremely nonlinear and feeds on
   itself. One step can't follow it. Newton fails at the clamps, or error control splits
   the step hundreds of times. S4's diode multivibrator ran ~80x slower than real time at
   production for this reason (TUBE_SYNTH_PLAN.md, S4 (a)). The draft's step can't
   resolve the flip at all.
2. **Timing.** The reset's moment sets the pitch. At 2 kHz the period is 500 us. A reset
   that lands up to a sample late varies the period by up to ~2% from cycle to cycle:
   tens of cents of jitter, heard as roughness and spurious tones. The event has to be
   placed between samples, to a small fraction of a microsecond.
3. **Aliasing, even with exact physics.** An ideal sawtooth's harmonics fall only as
   1/n. At 1 kHz the 48th harmonic (48 kHz) is only ~34 dB down, and everything above
   Nyquist folds back as inharmonic tones. A real reset of finite length rolls the
   harmonics off, but a 2 us reset does so only around 150 kHz. So even a perfect
   simulation of the real tube aliases at our rate. Something must band-limit it, and
   the reference has to be judged with the band-limiting in mind.

**What isn't hard:** slow physics (the heater's 7 s lag, sag, drift) is cheap. Large
but smooth linear systems (a plate's 26,000 modes, a speaker's delay line) are a *cost*
problem, since DK's cost grows with the square of the states. That cost is also handled
by deriving something offline (see Precedents, and technique S).

## Rules (proposed)

1. **Pure by default.** An exception is a measured decision, never the first resort.
   It needs numbers showing the direct simulation is too slow or can't resolve the
   physics. The options and numbers go to the user, who decides (as with physics refits).
2. **Every exception has a reference:** the same part simulated directly, offline (high
   oversampling, tight tolerances, error control). This is the exception's ground
   truth, the way ngspice and circuitsim's converged solution are for the circuit.
3. **Smallest scope.** An exception covers the hard event or region, not the whole
   device. A thyratron's ramp phase (leakage, grid control, grid current) stays an
   ordinary device in the netlist. Only strike, discharge, extinction and deionization
   are the exception.
4. **Coupled at the ports.** An exception talks to the circuit only through port
   currents and state jumps, like the plate (`media.rs`). The rest of the circuit sees
   the event through its own physics: a filter, a VCA or a supply downstream responds
   to a band-limited current at the port, not to audio added at the output. Charge and
   energy are conserved through the port.
5. **Generated and versioned.** A script generates an exception's tables from the
   reference. The tables' source names the reference run (component version, settings,
   code hash). They belong to the component version (COMPONENT_EDITOR_PLAN.md C1:
   versions are immutable), so a new component version means regenerated tables.
6. **Switchable.** Any circuit with an exception can be rendered with the reference in
   its place (a build option, like `cores=` or `noise=`), slowly, for verification and
   possibly for production (see Open decisions).
7. **Two implementations**, like media: a Python reference of the exception and
   circuitsim's port, tested to agree. Separately, both are tested against the
   full-physics reference on behaviour: pitch in cents, harmonic levels up to 20 kHz,
   the state after the event, the supply current per cycle, and aliasing below a stated
   floor.

**The hard rule.** "One coupled simulation" bends where an exception sits, as the
draft's partition bent it (one sample of latency across the rails). Proposed addition
to CLAUDE.md's Hard rules, once the first exception is built and the user agrees:
*"Physics exceptions (HYBRID_PHYSICS_PLAN.md): where an event is far faster than a
sample, or a field is spread in space, that part alone may be replaced by a stand-in
generated from a full-physics reference simulation of the same part, coupled at its
ports, with an agreement test and the reference selectable in its place."*

## Precedents already in the code

The pattern exists already, without the name. This plan gives it rules:

- **The plate** (REVERB_PLAN.md): its modes come from dimensions, steel and tension,
  and become an impulse response coupled at the exciter and pickup ports, one sample
  later (`Plate`, `circuitsim::convolve`). That's technique S.
- **The tape's bias** (TAPE_PLAN.md): a closed-form Preisach formula over the bias
  peaks only, instead of simulating each ~100 kHz cycle. The physics is exact; only its
  sampling is clever.
- **The draft's tube tables** (`triode_table.rs`): the exact Koren model tabulated to
  9e-8. A cheaper form of the same physics.
- **The draft's partition**: the supplies on their own thread with one sample of
  latency. A bend of the coupling that was measured (-103 dB) and decided by the user.

## The toolbox

**K. Event kernels.** This is the user's idea from the brainstorm, made concrete for
fast, repeatable transitions.
- Offline: run the reference across a grid of the conditions the event sees (the
  voltage at strike, the grid voltage, supply, load, heater temperature). From each run,
  record:
  - the port current during the event;
  - the state afterwards (the capacitor's voltage at extinction, the deionization time
    before the tube can strike again);
  - the event's length.
- Runtime: the circuit simulates the ramp. Each step checks the strike condition.
  - On a crossing, solve for the crossing time between samples (interpolating the
    step's states).
  - Inject the event's charge at the port as a band-limited pulse at that offset. The
    pulse is **minimum-phase** (causal, as in minBLEP): in a coupled loop the solver
    can't look ahead.
  - Apply the state afterwards. Deionization is a time-varying conductance from the
    table.
- The pulse integrates exactly to the discharged charge, so the ramp's next start is
  physical.
- Open questions for H2/H3:
  - how the solver's interpolation of an injected current between samples shapes the
    pulse (control inputs are linear between samples);
  - interpolation across the condition grid.

**M. Multi-rate islands.** Run a small section (the oscillator alone) at a high rate on
its own thread, with a decimating anti-alias filter where it meets the rest.
- The purest option: the real tube, just at a fine step.
- The partition's threads exist; running a group at a different rate doesn't, so it's
  new engine work.
- Cost: unknown until measured. A one-tube section at a few MHz may be affordable for
  rendering, if not for real time.

**E. Envelope and carrier.** A carrier far above the audio band travels as its
amplitude and phase at the audio rate, and is regenerated where it acts. This is
TAPE_PLAN.md TM5's second option for the bias oscillator.

**S. Offline spatial solves.** Field or mechanical physics spread in space (a plate, a
room, a cone, a grid wire) is solved offline into linear modes or impulse responses at
its ports. This is already the plate's method and the component editor's C8 (field
solvers offline, tabulated).

**N. Stochastic event libraries.** Random fast events (contact arcs, crackle, flashover):
- a physical event model, simulated offline into a library of kernels;
- fired at run time by a rate process that depends on the circuit's state (the voltage
  across a dirty contact, a pot's wiper speed);
- every draw seeded, as the Reproducibility rule requires.

## Candidates

| # | Where | The hard physics | Technique | When |
|---|---|---|---|---|
| 1 | Gas-tube sawtooth (SYNTH_IDEAS #23, S4 (c)) | A thyratron or neon lamp striking, discharging and deionizing in microseconds | K | **First** (H1-H4) |
| 2 | Multivibrators and flip-flop dividers (S4 (a), SYNTH_IDEAS #10, #24) | Regenerative flips of two triodes, sub-microsecond | K (a flip as a state transition) or M | After 1 |
| 3 | Dekatron step sequencer (SYNTH_IDEAS #25) | Glow transfer between cathodes | K, as a discrete state machine with measured transfer times | Needs 1's gas model |
| 4 | The Ampex 351's bias oscillator (TAPE_PLAN.md TM5) | A 12AU7 at ~100 kHz, above Nyquist | M or E (TM5 already plans to measure one against the other) | TM5 |
| 5 | Glow references in supplies (the 670's and tube_synth's 5651s) | Ignition at power-on, negative resistance, relaxation with too much capacitance, glow noise. Today a burning diode with no ignition (`varimu/circuit/netlist.py`) | K | With 1's gas model; matters for "Power on (cold)" |
| 6 | Gas and mercury-vapour rectifiers (866A, 83) | Ionization at each conduction start, RF "hash" bursts | K | If a device uses one |
| 7 | Switches, relays, pots | Contact bounce, arcs, wiper scratch: microsecond events | N | With the aging / condition dials (FUTURE_DIRECTIONS.md; tape condition dials) |
| 8 | The spring reverb's "boing" (REVERB_PLAN.md) | Coils colliding and magnets hitting their limits when the tank is kicked | K (collision events) on the spring's scheme | With the spring |
| 9 | Grooves: vinyl, 78s, cylinders (PHONO_PLAN.md) | The stylus losing groove contact (mistracking), Hertz contact, dust impacts | K (contact events) | With PHONO_PLAN.md G1 |
| 10 | The diode ring modulator (SYNTH_IDEAS #14) | Diodes switching sharply at the carrier | M (an oversampled island) | If it aliases at draft |
| 11 | Hard clipping at draft (the 5E3's draft-1x aliased at -8 dB) | Sharp corners of overdriven stages | M, for just the clipping stage | Only if draft-2x stops being enough |
| 12 | Tube microphonics (COMPONENT_EDITOR_PLAN.md C8) | Grid wires and electrodes ringing when the chassis or speaker shakes them | S (modes) | Later |
| 13 | Rooms, echo chambers, microphones (SEPARATION_PLAN.md, REVERB_PLAN.md) | 3D waves | S | Later |
| 14 | Tube and transformer fields (COMPONENT_EDITOR_PLAN.md C8) | Space charge, fringing | S (already C8's rule) | Only if needed |

**Not candidates:**
- Hysteresis: the JA ratchet is a model's flaw, not a resolution problem. Preisach is
  the answer there.
- Thermal and slow drift: cheap as they are.
- Noise: already band-limited at its spectral density (B5).

## Milestones

**H1. The gas tube and its reference.** A thyratron model, 2D21 or 884 (SYNTH_IDEAS
#23), fitted to an RCA sheet:
- the critical grid voltage against the plate voltage (the control characteristic);
- the glow's drop, extinction and deionization time.

It gets a Python reference and circuitsim's port. Then the sawtooth oscillator is
simulated directly as the reference (production at high oversampling, error control).
*Done when:*
- the reference oscillator runs;
- its pitch is checked against the textbook charge-to-strike formula;
- its reset waveform and its cost are in `reports/hybrid/`.

*Status 2026-11-03: done-when met, in the worktree `../VST-Experiments-gas-tube` (branch
`gas-tube`, uncommitted).*
- **The tube: the 884** (the user's call, after hearing the 2D21 prototype: "worth it").
  RCA's argon triode for sweep oscillators: a control ratio ~10 (the 2D21's is ~250, its
  strike moves ~25 V per 0.1 V of grid), argon (faster deionization), and RCA's own sweep
  circuit with a frequency table. Its sheet gives no ionization or deionization times, so
  **the 2D21 is the model's validation tube** (the only sheet found that publishes the
  event's physics) and the 884 takes its structure.
- **Data.** 2D21: RCA (6-15-48, `sources/rca_2d21_1948.pdf`): ionization 0.5 us,
  deionization 35 us at -100 V / 75 us at -10 V, drop 8 V (`published_points.yaml` "2D21");
  Sylvania (11-54, 300 dpi) digitized by `scripts/digitize_2d21.py`
  (`sylvania_2d21.provenance.yaml`): the control family (its "+3" is RCA's "+8"), grid current
  before conduction (41 pS leakage, the knee into the strike) and during (~3% of the anode
  current). 884: RCA (12-15-44, `sources/rca_884_1944.pdf`): the control characteristic
  (`scripts/digitize_884.py`, `rca_884.provenance.yaml`: -30 V -> 300 V .. -4 V -> 30 V), the
  16 V drop, capacitances, the sweep circuit and its frequency table (`published_points.yaml`
  "884"). The table is "approximate": its f x C implies a ~69 V sweep where the control
  curve at the circuit's -4.6 V bias gives a ~36 V strike, so it is a check, not a target.
- **The model** (`varimu/devices/thyratron.py`; a tetrode's pins a, g2, g1, w, k, a triode's
  a, g, w, k; w = ln of the ion density on a 1 F node, like the lamp's temperature): the
  grid's barrier lowered by the ions until the plasma screens it, a space-charge supply the
  ions neutralize, single-step ionization above the gas's ionization potential and stepwise
  through its lowest metastable (the arc's drop; NIST levels for xenon and argon), ambipolar
  diffusion plus the grid's sheath collecting ions (deionization). The strike is the ion
  balance's tangency; extinction, the grid regaining control at low current.
- **The fits** (`varimu/devices/thyratron_fit.py`; `varimu fit-devices --only 2D21 884` ->
  `2D21@1`, `884@1`): the 2D21 in full (the strike as a smooth margin's root; 80 evaluations
  from the prototype, cost 339 -> 208): control 0.29 V rms, grid current in the arc +-0.004 of
  Ig / Ia, pre-conduction ion current within ~2.5x, drop 8.68 V (8), deionization 78 / 38.6 us
  (75 / 35), ionization 0.30 us (0.5: no fit moved it, a gap in the model's structure, not
  its values). The 884 from it with argon: its control curve to 0.09 V rms (mu_a 10.7), the
  16 V drop exactly; transport scaled by argon's ion mobility over xenon's (x2.64,
  provisional): deionization 24 us at -20 V, 12 us at -100 V; ionization 0.54 us.
- **The 2D21 sawtooth (scipy Radau prototype, `scripts/prototypes/thyratron/`)**: heard by the
  user ("a good start", 2026-11-02): reports/hybrid/audio/saw_*.wav, 95-540 Hz; the charge-to-
  strike formula 117.4 Hz against 116.4 simulated; 100k and 47k latch (the tube stays lit).
- **Built and tested:** the Python IR type (`pins_of`), the SPICE subcircuit (a series
  softplus tail: SPICE has no log1p), both builders' loaders and preflight (the state node's
  DC path), circuitsim's `devices/thyratron.rs` (analytic Jacobian; a triode drops the shield
  grid's row; a sheath that vanishes has no derivative). Rust against Python 2-5e-14
  (fixtures), Jacobians against finite differences, SPICE against Python (1e-8, the state
  from its physical floor w ~ -25 up; `tests/test_spice_agreement.py`), the Rust builder's IR
  equal to Python's (`rca_884_sweep.json`), `tests/test_rca_884_sweep.py`.
- **The reference** (`config/circuits/rca_884_sweep.yaml`, RCA's oscillator literal; the
  timing capacitor and the plasma state held off for the DC point: a relaxation oscillator
  has no stable DC state, and an off tube's state is flat in w, a singular DC Newton;
  `scripts/thyratron_study.py` -> `reports/hybrid/rca_884_sweep.{json,png}`, audio in
  `reports/hybrid/audio/`): circuitsim production, output at 3.072 MHz (no decimation), every
  S1 range at both ends of R6. All 14 oscillate, 52 Hz-18.7 kHz, a 13-22 -> 41-50 V sweep:
  - pitch 2.2-2.6x RCA's table, as the table's own f x C predicted (a ~69 V sweep against the
    control curve's ~45 V);
  - the strike: on slow ramps a few volts below the static characteristic (the grid's 50k
    with the pre-conduction ion current: the sheet's "the critical grid voltage depends on
    the grid resistor"), on fast ramps above it (C8: 49.8 V, the ionization delay);
  - the charge-to-strike formula with the run's levels is 8-9% high below 2 kHz, the reset's
    time (C2: ~0.6 ms per cycle, ~5.5 R4 C, the discharge's tail into the arc's extinction),
    up to 40% at 18.7 kHz (~15 us lost per cycle to deionization; RCA's table implies ~29);
  - the reset (90 -> 10%): 206 us at C2 down to 3.3 us at C8, peak 9-59 mA; the plasma decays
    with ~6 us; each strike kicks the grid up ~1.6 V through the 6 pF grid-to-anode;
  - cost 9-16x slower than real time (output 3.072 MHz, error control).
- Since this plan was written, circuitsim gained multi-rate sections (`substeps:`, built for
  the 351's bias oscillator): technique M is no longer new engine work. H2 should measure it
  against K.

**H2. The event study.**
- How long the reset is.
- How much it changes over the conditions (strike voltage, grid, supply, heater).
- How much of its spectrum lies above 48 kHz.
- How much the direct simulation aliases at 96 kHz.

*Done when:* the numbers pick K or M, brought to the user with options.

*Status 2026-11-03: measured, options to the user (nothing of K or M built).*
`scripts/thyratron_event_study.py` -> `reports/hybrid/event_study.{json,png}` (`_timing`: one
job at a time), runs cached in `cache/hybrid/h2/`. On H1's reference circuit, every S1 range at
both ends of R6, plus at C4 / C6 / C8: B+ 350 / 550 V, R11 1000 / 2200 ohm (the bias), R4 350 /
500 ohm. The reference is H1's: production at 3.072 MHz. It is converged: error control never
triggers there, 6.1 MHz moves the pitch 0.16 cents, and its period varies 0.014 cents cycle to
cycle. The slow capacitors (C9: 0.75 s) are preset from a 4 s run, or the pitch drifts 0.1%
over the window. The heater isn't in the 884's model: not studied. C8 with R11 1000 ohm (bias
about -3 V) latches.
- **The reset's length** (strike to the ramp's restart, its 90 -> 10% fall, strike to peak
  current), from C8 to C2:
  - strike to restart 9 -> 486 us (0.9 to 47 samples at 96 kHz), 90 -> 10% 3.4 -> 206 us;
  - it scales with C (the discharge through R4 and the arc);
  - the current's rise (the ionization) takes 1.6 -> 11 us;
  - the plasma decays in 4.4-6 us after extinction (9.5 us at C8 with B+ 350 V);
  - at a fixed C the conditions move the fall +-25% (R4 350-500 ohm: 57-83 us at C4) and the
    rise 2-3x (the bias: C6 1.6-5.6 us; C8 1.0-2.3 us).
- **The pulse against a delta of its charge** (|I(f)| / Q of the anode current; Q = 1.03-1.26
  C dV, the excess being the charging current during the reset):
  - within 1 dB up to 20 kHz only for C <= 5 nF (C6-C8: -0.3 to -1.2 dB; -3 dB at 35-110 kHz);
  - C5 (15 nF) -2.5 dB at 20 kHz, C4 -7, C3 -14, C2 -22 (-3 dB at 1.5 kHz).
  So for C >= ~15 nF the reset's shape is in the audio band: a kernel must carry it, or the
  circuit must simulate that discharge itself (it is 3-47 samples long there).
- **Spectrum above 48 kHz:**
  - the sweep's AC power above 48 kHz: -64 dB at 133 Hz (C2), -41 at 834 Hz, -30 at 2 kHz, -21
    at 4.6 kHz, -10 at 18.8 kHz;
  - against an ideal sawtooth's 1 / n, the harmonics near 48 kHz are 31 dB down at C2, 15 at
    C4, 8 at C5 and only 3-5 dB down at C6-C8: the short resets barely band-limit themselves.
- **The direct simulation at 96 kHz.** Every candidate is compared with the reference
  band-limited by a 120 dB FIR. "Inharmonic" is the power off the harmonics in 20 Hz-20 kHz,
  re the harmonics'; the reference's own floor is -75 to -104 dB.
  - **Point-sampling the exact waveform** (`ideal-96k`): -88 dB at 54 Hz, -73 at 133 Hz, -50
    at 834 Hz, -38 at 2 kHz, -27.5 at 4.6 kHz, -16 at 18.8 kHz. This is the limit of anything
    that hands on one sample per sample. At 192 kHz plus decimation it is -27 to -93 dB, at
    384 kHz -42 to -95, at 768 kHz -66 at 18.8 kHz and at the floor below 9 kHz
    (renders' Kaiser-5 decimator matches a 120 dB filter here).
  - **The draft (96 kHz, trbdf2, no error control) and draft-2x** (identical in the band) are
    broken above a few hundred Hz, not just aliased:
    - pitch errors of tens of cents (+85 at 834 Hz, -77 at 3.9 kHz, +42 at 18.8 kHz);
    - 50-250 cents rms of cycle-to-cycle jitter;
    - harmonics off by up to 25 dB;
    - inharmonic power at or above the harmonics' from ~800 Hz up.
    Below 140 Hz they hold within 3-6 cents, -37 to -71 dB. The cause is the strike's timing
    error, which depends on where the event falls on the fixed step grid: a fixed-step rate
    sweep isn't even monotonic (at 4.6 kHz, 16x is -29 dB where 8x is -55). Draft-1x is
    worse still.
  - **Production** (esdirk4 at 192 kHz, error control): pitch within 1.4 cents everywhere,
    inharmonic -84 dB at 54 Hz but -21 to -49 dB from 1.8 kHz up (the 192 kHz point-sampling
    limit). It costs 1.2-3.3x real time (one job).
  - Fixed 8x through renders' decimator: with esdirk4 (`production-8x`) the pitch is within
    0.5 cents and inharmonic power is -70 dB or better below 2 kHz, -50 to -59 at 4-9 kHz,
    -40 at 18.8 kHz, at 2.8-6.9x real time (seven jobs at once). With trbdf2 (`direct-8x`)
    the pitch is off -5 to -9 cents above 1.8 kHz.
- **Technique M as built** (partition.rs's multi-rate part: the oscillator at M steps per
  sample on its own thread, B+ and the cathode's divider at 96 kHz):
  - **The cut matters.** A cut through C9 into the 6J7's grid (a high impedance behind a
    coupling capacitor) makes the island's Newton diverge at the first strike, at every M,
    with the coupling extrapolated (the 351's lesson again). Cut at B+ and the cathode's
    25 uF, it runs.
  - **Pitch:** esdirk4 at 8x within 0.5 cents (32x: 0.0); trbdf2 at 8x -5 to -9 cents above
    1.8 kHz, 4x -13 to -27.
  - **Aliasing:** the island's nodes come out point-sampled, so every M is exactly
    `ideal-96k`: worse than production. What a multi-rate part hands the rest is its current
    averaged per sample (`-avg`, the cut through C9 with the coupling held): about 13-20 dB
    better (-35 to -41 dB from 1.8 kHz up), but holding costs -4 to -14 cents.
  - **Cost** (one job): trbdf2 4x 0.74-1.29x real time, 8x 1.15-1.91x, 16x 2.1-3.2x;
    esdirk4 8x 3.1-4.7x. The reference costs 9-19x.
- **What K would cost** (not built; an estimate): the ramp alone (the tube held off) runs at
  0.085x real time at the draft (one job). The draft with the events costs 0.25-0.54x, so even
  at 96 kHz the events are most of the cost. K replaces them with a crossing time and a table
  lookup per event plus a kernel of some tens of taps. Estimate: ~0.1-0.15x real time,
  independent of pitch.

**Options (the user's call):**
- **K, event kernels (H3 as planned).** The only one measured or estimated that could play
  live. Live needs well under 1x on one thread; the synth's other threads are ~62% loaded.
  - Aliasing is set by the kernel's design (its stopband), not by the rate. Pitch comes from
    the crossing time and the table's dead time (target < 1 cent).
  - New engine work (detection, sub-sample crossing, injection at the port, the state
    after, the deionization), in Python and Rust.
  - From the numbers: below ~5 nF a charge-only kernel suffices (the pulse is a delta to
    20 kHz). Above that, the kernel carries the pulse's in-band shape, or K becomes two
    events, strike and extinction, with the arc simulated by the circuit between them.
  - Its tables are generated from the instrument's circuit (H4), not RCA's: a fixed C per
    range leaves a small grid (strike voltage, charging current).
- **M0, M as built (no engine work).** Pitch good (esdirk4 8x), but its output aliases like
  point sampling at 96 kHz (-16 to -38 dB from 2 kHz up), and it costs 1.15-4.7x real time.
  It beats production on nothing measured here: not recommended.
- **M1, M plus a decimating anti-alias filter where the island meets the rest** (a small
  engine change: a polyphase low-pass on the island's published currents, a few samples of
  latency, fine for a one-way oscillator output).
  - Expected (production-8x is the same thing for this circuit): pitch within 0.5 cents;
    inharmonic -70 dB or better below 2 kHz, -50 to -59 at 4-9 kHz, -40 at 18.8 kHz.
  - Cost 3.1-4.7x real time on the oscillator's thread.
  - Pure physics, no tables: a candidate for production renders, not for live play.
- **Production at a higher oversampling for the whole circuit** (no work; 8x: as M1, 2.8-6.9x
  real time) is a stopgap for renders while the circuit is only the oscillator. In a synth
  voice every other stage would pay the 8x too.

**Listening samples** (the user's request, to decide by ear; `scripts/thyratron_scale_demo.py`
-> `reports/hybrid/audio/h2_scales/`): four major scales, A1-A2 on C2 (the circuit's lowest,
~52 Hz with R6 at its top), D3-D4 on C3, G5-G6 on C5 and B7-B8 on C7, tuned with R6. Five
versions, all at -16 LUFS: the reference band-limited (what K and M1 aim at), production-8x
(M1's stand-in), production, the island as built (M0), draft-2x (today's Play quality).
Pitch from the reference (spectral; the draft's ringing fools a midpoint-crossing count):
production-8x and M0 within 0.2 cents, production within 0.4. Draft-2x is +1 to +5 cents up
A1-A2, +8 to +28 up D3-D4, -4 to -87 up G5-G6 (erratic from note to note) and +4 to -83 up
B7-B8: it can't be played in tune above the bass. There is no K sample: it isn't built, and a stand-in would be a target
sound, not a reference.

**Proposed:** K for live play (H3), and M1 or the reference for production renders. The latter
is the plan's open decision "production: exception or reference?", now with numbers. K's
agreement test would run against M1 / the reference, which H3 needs anyway.

**H3, as decided (2026-11-03, the user's call after H2):** K as the live quality you play and
record with, M1 as the render (pure physics, no tables). Takes are re-rendered through M1
(RECORDING_PLAN.md's events), so K's table ranges bound only the monitor. Order:
- **H3a, M1:** a multi-rate part behind a decimating anti-alias filter. Two engine changes,
  both opt-in per section, so the Ampex 351 doesn't move:
  - `decimate: fir`: a linear-phase Kaiser low-pass (unity DC: charge conserved; passband
    0.25 fs, stopband from 0.75 fs, 100 dB) over the part's per-step values. It applies to
    everything the part hands on: the currents into nodes it doesn't own, the voltages of
    nodes it owns, its probes. It replaces the per-sample average (a box filter: -35 to -41
    dB at H2's high pitches).
  - `owns: [node, ...]`: a multi-rate part may own shared nodes. Then the island's
    low-impedance output is published as a voltage and the load's current comes back. The
    reverse (the slow part holding a high-impedance node the island drives) diverged at the
    6J7's grid in H2. A loop of ownership (the island uses B+, the slow part uses the island's
    output) needs the DC start's currents from every part with every shared node held at the
    whole circuit's DC voltages.
  - Done when: RCA's sweep as an island (`owns: [out]` or the 6J7's grid side) matches the
    reference within H2's ideal-768k-aa floor (pitch < 0.5 cents) at 8x, its cost is
    measured, and partition tests cover ownership and the filter (DC point, charge per
    sample, a sine through the filter).
  - *Status 2026-11-03: done.* circuitsim's `partition::Decimator` (Kaiser, odd taps, 103
    dB design for the 100 dB target, delay (taps - 1) / 2 steps = 6.5 samples at 8x) and
    `Section::{decimate, owns}`. Both IRs, both circuit-file loaders and builders take them,
    and IRs without them are unchanged. With `owns`, the DC start holds every part's shared
    nodes at the whole solve's voltages, owned ones through 1 mOhm (a source of the part's own
    may hold them). Tests: `partition::tests` (passband within 2e-5, stopband below -99 dB at
    m 4-32), `tests/partition.rs` (a decimating part's alias 4.0 mV -> 0.2 uV; an island
    owning its output in a loop of ownership, DC equal to the one solve, the load within 1%
    at the delay; ownership errors), `tests/test_circuit_ir.py` (round trips, refusals, a
    circuit file).
  - **What the decimator's delay costs.** In a two-way coupling that loads a node ~5%, the
    1 kHz there is 0.34% off. Cut at RCA's `out` with the 6J7's 1 Mohm input outside, the
    input's current (~4% of the charging current) returned a sample and the delay late:
    +7 cents at 18.8 kHz, -45 dB at any M. **Cut where nothing comes back**: stiff rails, or a
    grid the island owns.
  - **RCA's sweep as M1** (the whole oscillator, the 6J7's input included, in the island; B+
    and the cathode's divider outside; heard through its decimated probes;
    `thyratron_event_study.py`'s `m1-*`, `reports/hybrid/event_study_m1.json`). Inharmonic
    dB, from 54 Hz to 18.8 kHz:
    - 8x esdirk4: -92 .. -50, -39.5 at 18.8 kHz, pitch within 0.12 cents (0.52 at 18.8 kHz);
    - **16x esdirk4: -95 .. -77, -70 at 18.8 kHz**, within ~6 dB of the 768 kHz floor
      everywhere, pitch within 0.11 cents;
    - 32x: at the reference's floor (-85 at 18.8 kHz), pitch within 0.03 cents.
    Cost (one job): 8x 2.1-4.4x real time, 16x 3.6-7.6x, 32x 7-13x; the decimator adds nothing
    measurable over M0. **The render default: 16x** (32x for a top octave at the reference).
- **K's design (2026-11-03, from H2's numbers):**
  - **The unit.** The exception is the tube with what it discharges: the capacitor C at its
    anode and the series resistance R_s (RCA's R4), the grid returned through R_g (the grid
    network's DC resistance). Tables are per unit (C, R_s, R_g: one per range of an
    instrument), generated from reference runs of the unit alone in circuitsim at 3.072 MHz:
    C charged by a near-constant current (10 kV through a large R: slope S), the grid held
    at V_g through R_g.
  - **The tables**, over (V_g, log S) (the conditions at the strike, both known to the
    circuit):
    - the strike voltage V_s (the anode-to-cathode voltage when the anode current passes
      a threshold; slow ramps strike below the static characteristic, fast ones above);
    - the event's anode current from that moment, as charge per step of the audio rate at
      P fractional offsets: q_k = the integral over step k of the pulse convolved with a
      minimum-phase low-pass (causal: the solver can't look ahead). These are exactly the
      increments of the band-limited capacitor voltage, so no droop correction is needed;
    - the event's length (to extinction) and the dead time before the next strike can
      start (the plasma's decay).
  - **At run time (the circuit at the audio rate):**
    - the tube between events is its capacitances and leakage (smooth);
    - before each step, the margin m = V_ak - V_s(V_gk, S) at the last three samples
      (S from the anode's difference) is extrapolated quadratically. A zero within the
      step gives the strike's offset phi;
    - the event's charges, interpolated over (V_g, log S) and phi, are injected a -> k as
      a current held over each step (exact charge per step);
    - no new strike until the dead time has passed. A strike the prediction missed starts
      at the next step (counted).
  - **Engine (H3c).** A new element: it senses (a, g, k) after each sample and injects a
    current between a and k held over the next step. Media (`media.rs`) drive a voltage,
    linear between samples (charge per step would zigzag); noise currents (`NoiseRun`) are
    DK current columns. Extend one of them.
  - *H3b status 2026-11-03: K's Python reference built and validated against the reference
    (no engine work yet).* `varimu/devices/thyratron_events.py` (the unit's IR and runs, the
    minimum-phase kernel, step charges, the tables, `predict_crossing`, the `Emulator`),
    `scripts/thyratron_kernels.py` -> `reports/hybrid/k_unit_{fine,coarse}.json`, audio in
    `reports/hybrid/audio/k_unit/` (reference / K / direct per check),
    `tests/test_thyratron_events.py`. The unit: RCA's C6 (5 nF), R4 (450 ohm), grid return
    49.5k; tables over V_g -4 .. -8 V x S 0.003-0.3 V/us (9 x 13, 33 phases x 19 steps);
    ~2-3 min to generate, cached in `cache/hybrid/k/`.
    - **Result.** K at 96 kHz against the unit's 3.072 MHz reference, 8 checks on and off the
      grid (150 Hz-5.9 kHz):
      - pitch within 1.8 cents (most within 1);
      - inharmonic -79 to -95 dB, at the reference's floor;
      - harmonics within 0.1 dB, jitter at most 0.85 cents;
      - no missed strikes.
      The direct draft on the same unit: -89 to +39 cents, inharmonic at or above the
      harmonics.
    - **What it took** (each a measured miss):
      - the grid axes ascending: a descending one read the wrong row;
      - the pulse to 1e-4 of its peak: cut at 1%, the arc's tail lost ~1% of the charge, 15-45
        cents sharp;
      - the margin on the physical voltage (the band-limited voltage plus the filtered less
        the raw charges so far, over C): on the band-limited one, the kernel's Gibbs ringing
        (several volts for ~10 samples) broke prediction at fast ramps;
      - the pre-conduction (what the tube passes on the ramp before the strike: 0.2-0.7% of
        the charge) lumped into the event's first sample, with the strike at 1 mA. Modelled
        instead as a current between events (the quasi-static plasma), its exponential knee
        bent the ramp, the prediction missed by fractions of a sample, and the strikes
        aliased at -50 to -65 dB;
      - tables from steady oscillation (the last of four strikes), not a first strike: the
        previous event's leftover ions lower the strike (first-strike tables ran 2-12 cents
        flat at 4 kHz). A first note after silence is a cycle's few cents off;
      - the 9 x 13 grid: at 5 x 7, off-grid checks were 1.5-10 cents off near the latching
        boundary (-4 V, fast ramps).
    - **Latching** is in the tables as a marked point (no event): at -4 V and 0.3 V/us the
      charging current (1.5 mA) holds the arc. K doesn't play a latched state yet; the
      instrument's design (H4) is to avoid it.
    - **For the engine (H3c):** the "off" tube needs only its capacitances and leakage (no
      nonlinear device between events). It needs a current held over each step, a -> k
      (charge per step exact), and senses of (a, g, k). It also keeps the margin's
      correction, the filtered less the raw charges, which is the unit's C (part of the
      exception's definition).
  - *H3c status 2026-11-03: K in circuitsim, built and checked on the unit (in the worktree,
    uncommitted).*
    - **The element:** IR `ThyratronEvents` (both languages, kind `thyratron_events`, prefix
      X; validation in both), on the device's pins (a, g, w, k), triodes only:
      - between events it is the off tube: C_gk, C_ga, C_ak, the grid's leakage, and w held to
        k by a numerical 1 S;
      - it carries the unit (C, R_s, R_g) and its tables: V_s, dead time, latched points, and
        **each point's raw pulse at 3.072 MHz**. The engine band-limits them for its own step
        (m = 3.072 MHz x h reference samples, a whole number: 32 at 96 kHz, 16 at production's
        192 kHz; anything else is refused). So the IR doesn't depend on the rate;
      - SPICE gets the off tube only.
    - **The engine** (`crates/circuitsim/src/events.rs`, the port of
      `thyratron_events.Events`; the arithmetic matches op for op):
      - the min-phase kernel (Kaiser firwin + cepstrum, rustfft), the step charges, the
        crossing, and the tables' lookup (split: only V_s per sample, the charges only on a
        strike);
      - after each sample (`Transient::step_events`, beside `step_media`), the current held
        a -> k over the next step goes in as a DK current column after the noise's
        (`Mna::current_columns`), constant at every stage and substep.
      - **Why not media:** a medium drives one row with a voltage, linear between samples. The
        noise's columns are two-node currents already; a held value is all K adds.
      - **The step's carried derivative** (`F = C x'`, which TR-BDF2 and ESDIRK4 start from)
        moves by the current's jump on the a and k rows. Without that, the first stage
        averaged the old and new currents: harmonics 1.1-1.8 dB off at the draft, +4 to +21
        cents and inharmonic up to -9 dB at production.
      - The DK solver only (as noise); `update` carries the kernels' state; stats `events`,
        `late_events`, `latched_events` (circuitsim.simulate's, `fast.run_transient(...,
        stats=)`).
    - **The senses:** the unit's capacitor is v_ak + R_s i (its own current). The grid's
      coordinate is v_gk - R_g C_ga S: measured on the reference, the 6 pF grid-to-anode
      coupling lifts the grid 0.003-0.09 V above the bias during the ramp (x mu ~10 =
      up to ~1 V of strike, ~35 cents). The tables' bias axis already holds it.
    - **Latched points:** where the latched corners weigh half or more, the condition latches.
      It plays no event (the ramp runs on) and is counted once per crossing. Below half, the
      other corners' weights are renormalized (the charge stays whole). Python's `lookup` does
      the same (it used to give a NaN dead time).
    - **Builders:** a `devices` entry's `events: NAME` names its tables,
      `config/events/NAME.json` (`scripts/thyratron_kernels.py --write NAME`). With
      `build(..., events=True)` (Rust: `build_ir_events`), a thyratron's `device` part becomes
      its element and its model leaves the IR. A thyratron without tables, tables of another
      component version, or a tetrode is refused. Preflight (both languages) knows the
      element's DC paths. The unit as a circuit: `config/circuits/thyratron_unit.yaml`
      (`events: 884_unit_c6`); its events build is an app-fixture case, and the Rust builder
      builds it bit for bit.
    - **Tests:**
      - Rust against Python (`crates/circuitsim/tests/events.rs`, fixtures from
        `export_circuit_fixtures.py`): kernels and step charges within 4e-12 of the peak (the
        cepstrum takes the log of a 100 dB stopband: roundoff in numpy's and rustfft's FFTs);
        crossings exactly; lookups; four per-sample runs (96 and 192 kHz, a late strike, a
        latched condition) with exact counts and currents within 1e-9;
      - `tests/test_thyratron_unit_k.py`: the events build, refusals, preflight, SPICE, and
        circuitsim against the Emulator within 0.5 cents;
      - `tests/test_thyratron_events.py`: latched corners, fixtures current, IR round trip.
    - **Against the unit's 3 MHz reference** (`scripts/thyratron_kernels.py --timing` ->
      `reports/hybrid/k_unit_fine.json`, audio in `reports/hybrid/audio/k_unit/`; 8 checks
      150 Hz-5.9 kHz, on and off the grid):
      | | pitch | harmonics (to 20 kHz) | inharmonic | late |
      |---|---|---|---|---|
      | K, circuitsim draft (trbdf2, 96 kHz) | -1.64 .. +0.18 c | within 0.10 dB | -80 .. -95 dB | 0-4 per 75-2944 strikes |
      | K, circuitsim production (esdirk4 2x) | -1.15 .. +0.56 c | within 0.11 dB | -82 .. -95 dB | |
      | K, Python (H3b) | -1.83 .. +0.10 c | within 0.10 dB | -79 .. -95 dB | 0 |
      | direct draft (today) | -89 .. +39 c | | -147 .. +12.5 dB | |
      - The reference's own floor is -71 to -85 dB.
      - circuitsim's K and Python's agree within 0.32 cents. The unit's off-tube capacitances
        and its numerical ramp are the difference.
      - The sweep's mean and peak-to-peak are in the JSON (`mean_err_v`, `ptp_err_v`). The
        unit's supply current per cycle is C times the sweep: a real check only in a circuit
        with a supply (H3d).
    - **Cost at the draft** (one job at a time): **0.093-0.099x real time at every pitch**. The
      ramp alone cost 0.085x in H2, so the events add ~10%. The direct draft costs 0.13-1.6x;
      H2's estimate for K was 0.1-0.15x.
    - **The kernel's delay.** The min-phase kernel delays the charge by 2.12 samples (its DC
      group delay: 22 us at 96 kHz, 11 us at production). K's waveform is the reference's
      delayed by d plus a DC shift of S d: the sweep's mean is high by 0.03-6.5 V on the unit
      (`mean_err_v`, half at production). Pitch and harmonics don't see it.
      - In a circuit whose charging current depends on the capacitor's voltage, they do. For
        d after each strike the capacitor sits a sweep high, so its charging resistor passes
        less: a deficit of about d / (R C) of each cycle's charge, which the margin's
        correction doesn't see (it isn't the kernel's).
      - On the unit (10 kV) that is d S / 10 kV, at most ~1 cent flat (likely part of K's
        -1.8 c at fast ramps).
      - Estimated for RCA's sweep (R5 + R6 from 450 V): ~16 cents flat at C6, ~100 at C8.
  - *H3d status 2026-11-03 (in progress; decisions delegated by the user):*
    - **Decided:**
      - the tables' and the event study's cache keys skip `events.rs`
        (`thyratron_events.engine_hash`): K's code moves only K's runs;
      - one tables file per range (not built yet: only C6's exists);
      - measure before choosing a fix for the kernel's delay.
    - **K in RCA's sweep** (`thyratron_event_study.py --only 6,0 6,1 --candidates k-draft
      k-production m1-16x-esdirk4 --tag k` -> `reports/hybrid/event_study_k.json`;
      `K_TABLES` maps a range to its tables). The first run was **-430 cents**
      (-94 / -39 by the study's spectral pitch, the inharmonic power 74-84 dB *over* the
      harmonics). Two causes, found sample by sample:
      - **The grid's charge.**
        - Each arc drives ~3.5 nC of ions out of the grid (~1.9% of the anode's charge)
          through R3 into C1 (0.25 uF), which R2 bleeds with 12 ms. That is a standing
          grid-leak lift: the reference's grid sits at -5.10 V against its -5.87 V bias.
        - Through the control ratio that is ~8 V of strike. K injected no grid charge, so it
          struck at ~54 V against the reference's 46.4.
        - Now the tables carry the **grid's pulse** too: the model's own grid current, less
          its leakage, over the anode pulse's samples (IR `grid_pulses_a`). It is injected
          g -> k as a second held column, with the same kernel and phase interpolation.
        - **The anode's pulse is now the model's anode current**, not R4's: R4's carried the
          tube capacitances' displacement, which the K circuit has itself.
        - **The unit's grid return is R3 (2.5k)**: the impedance the arc and the ramp see, C1 a
          short at those speeds. The grid's charge depends on it (a grid held low collects
          more ions). On the unit this changed little: V_s 46.3 against 45.7 V, no latched
          point left.
        - Unit check after the change (`k_unit_fine.json`): K draft -1.91 .. +0.17 c,
          production -1.42 .. +0.67, harmonics within 0.11 dB. The 6 kHz corner is -69 dB
          inharmonic in Python's K as well: the tables, not the port.
        - With the grid charge, RCA C6 (R6 at 0 / 1): **K draft -11.2 / -4.5 c**, production
          -3.0 / -0.8, harmonics within 0.02 dB, inharmonic -55 / -66 dB (the reference's
          floor is -78 / -75). M1 at 16x: +0.04 / +0.03 c, -85 dB.
      - **The kernel's delay**, as estimated in H3c: the error is ~3x at the draft (d = 22 us)
        what it is at production (11 us), and less at R6's 1.48 M than at its 0.48 M.
        - Built: **the trim** (`Events._trim`, `events.rs` `Run::trim`, both identical). G is
          measured from the ramp's curvature (G = -C dS/dv over the last three samples). The
          deficit G (v - v_phys) summed over the event's lag is taken off the event's charges
          (band-limited and raw scaled alike: the shape and the aliasing unchanged).
        - **Isolated** (the unit charged from 450 V against its own 3 MHz reference, Python's
          K, scratch study): without the trim -10.8 / -2.0 / -21.6 c at the draft and -3.7 /
          0.0 / -8.5 at 192 kHz; with it **+2.0 .. +3.7 c at both rates**. The delay's rate
          dependence is gone; a rate-independent +2-4 c is left (the 10 kV unit's tables
          don't exactly describe a resistive charger).
        - **In RCA** the trim measures G exactly (2.746 uS against 2.750 from R5 + R6 and
          R7 + R8; 1.340 against 1.342 at R6 1.48 M), and Python's Events replaying the
          circuit's senses fires the same 922 strikes as Rust. But RCA C6 with it is **K draft
          +13.3 / +6.1 c, production +9.2 / +4.5** (jitter up to 1.07 c, inharmonic -50 /
          -47 dB). So RCA has a further ~+6-10 c error the isolated unit doesn't, still
          partly rate-dependent.
    - **Found (2026-11-03, later):**
      - **The trim's routing** was the error.
        - Diagnosis: Python's Events replaying K's draft run logged K's strikes against the
          reference's (scratch studies, not in the repo). K's grid sat 15 mV high relative to the
          cathode (-5.0875 against -5.1024 V), so it struck 0.14 V early.
        - The grid's absolute lift was right (0.8084 against 0.8074 V). **The cathode sat
          13.5 mV low** (5.8531 against 5.8666 V).
        - RCA's cathode is self-biased: it sits on its divider (~1.5k) carrying the tube's
          average current. The trim took the network's deficit off the tube's charge, so the
          cathode got ~10 uA less than in physics.
        - Fixed: the event keeps its tube charge whole. The deficit is delivered as its own
          current, **from ground into the anode** (a third held column per element, `(None,
          a)`; `Events._deficit`, `Run::deficit`), in the event's band-limited shape. The
          capacitor's sense through R_s uses the tube's current less it.
      - **The tables' charger:** the unit gets a charging voltage (`Unit.v_charge_v`; 10 kV by
        default, a constant current). The slope axis is now the slope at 40 V
        (`V_SLOPE_REF`, about the strike). Tables from a unit charged like RCA (its Thevenin
        equivalent: 343.5 V over the cathode at R6 0, 237.6 V at R6 1; B+ through R5 + R6 and
        C9's 34.9 V through R7 + R8) take ~2 c off.
      - **RCA C6 now** (draft / production; a scratch study on `thyratron_event_study`'s runs):
        | tables | R6 0 (4.6 kHz) | R6 1 (1.8 kHz) |
        |---|---|---|
        | 10 kV unit | +6.3 / +5.7 c | +4.5 / +3.7 c |
        | RCA-charged unit | **+4.1 / +3.5 c** | **+2.8 / +2.1 c** |
        - The draft and production agree within 0.6-0.8 c: the kernel's delay is handled.
        - Harmonics within 0.02 dB. **The inharmonic floor is poor**: -41 to -65 dB, erratic
          between runs and tables, against -75 / -78 dB for the reference and -85 for M1. On
          the unit, K reaches the reference's floor.
      - **Why RCA is hard for K:** two loops feed a strike error back into the strike.
        - The grid's lift on C1 is the tube's grid charge times the pitch (gain ~0.25: an
          error x1.33).
        - The self-biased cathode is the tube's average current (the other way).
        - The strike moves ~10.7 V per volt of either, so K must match the tube's charge per
          event to ~0.1% and its strike to ~0.02 V for 1 c.
      - **The unit's floor regressed at fast ramps** (`k_unit_fine.json` after the tables
        were republished with R3, the grid pulses and `V_SLOPE_REF`):
        - pitch still -1.6 .. +0.5 c (K draft), harmonics within 0.11 dB;
        - but inharmonic -55 dB at (-6 V, 0.3 V/us) and -62 at (-7.5, 0.25), where H3c had
          -79 / -83 and the first R3 tables -69 / -82. Python's K is the same, so it's the
          method or the tables, not the port.
        - Isolated (Python): without the deficit -62 / -76 dB, with it -55 / -62. G is measured
          exactly (0.151 uS, no spread), so it isn't noise in G.
        - Below 0.15 V/us the floor is -78 to -90 dB.
    - **Option A (the user's, 2026-11-03):** RCA stays the documented hard case (RCA C6 with
      the fixes below: +2-5 c; its floor -63 .. -68 dB at production, -47 .. -61 at the draft:
      its two loops amplify jitter). The unit's floor first, then H4's voice.
    - **The floors, fixed (2026-11-03):**
      - **The deficit's lag from the pulse's continuous centroid** (`Events._deficit`,
        `Run::deficit`): it was the raw step charges' centroid, which jumps with the strike's
        phase by up to half a step, so the deficit wobbled +-25% from event to event (-55 dB
        of sidebands at 6 kHz). Now the band-limited charges' centroid less the strike's
        phase, the pulse's own centroid (per table point, interpolated as the dead time) and a
        held current's half step.
      - **The slope at the crossing** (both languages): the slope from the last interval sits
        up to a step before the strike, by the phase; on a curved ramp V_s(S) moved with it
        (~1e-5 of the period of jitter: -60 dB sidebands at 6 kHz). One refinement: the slope
        from the margin's own quadratic at the predicted crossing, V_s there, the crossing
        again.
      - Cubic (4-point Lagrange) interpolation between the phase rows of the band-limited
        charges (the rows past the ends are the end rows a step on, the charge kept). It
        didn't move the floor (the sideband was the slope's); kept, it costs nothing
        measurable.
      - **The unit (C6) after both:** K draft -1.44 .. +0.55 c, harmonics within 0.10 dB,
        **inharmonic -89 .. -92 dB at every check** (the reference's floor -81 .. -90),
        0.14-0.20x real time; production the same.
    - **Charge-exact pulses (2026-11-03):** the reference's charge balance didn't close: per
      cycle the charger delivered 543.60 nC and the tube's current summed at the 3.072 MHz
      samples 547.45. The arc's peak (~0.25 A rising in ~0.5 us) is sharper than the samples,
      so the rectangle sum missed or overcounted up to ~1% by where the peak fell, and every
      table point carried its own error (the voice's unit: +-14 c). The pulse is now what left
      the capacitor over each reference sample (its charge lost, plus the charger's over the
      sample; `run_unit`'s `iq`); the strike and the extinction still use the model's
      current. Likely part of RCA's residual too (its tables predate it).
    - **Open:** the voice's unit at its top (5 kHz, 0.6 V/us): inharmonic -41 dB at the
      draft, where its reference's own floor is -48 (the reference less steady there).
- **H3b, K's design and Python reference** (the kernel tables generated from the reference;
  the event logic as pure functions), then **H3c** circuitsim's port, then **H3d** K against the
  reference and M1 (pitch, harmonics up to 20 kHz, supply current per cycle, aliasing floor),
  and K as a live quality.

**H3. Event kernels in the engine** (if K): the Python reference and circuitsim (event
detection, the crossing time between samples, the minimum-phase charge pulse, the state
afterwards, the switch to the reference). *Done when:* the sawtooth with the exception
matches the reference within stated bounds (pitch, harmonics up to 20 kHz, supply current
per cycle, aliasing floor), and its draft and production costs are measured.

**H4. The sawtooth in the synth.** A device of its own, then S5's second oscillator.
*Done when:* the user plays it live, at a load measured with a key held (`examples/play.rs
--hold`).

*Status 2026-11-03 (in progress, the worktree):*
- **The voice:** `config/circuits/saw_884.yaml`, an invented circuit.
  - CT (5 nF, the unit's C) from B+ (300 V) to `n`; a 6V6GT sinks a constant current from
    `n` (its plate at 175-300 V, above its knee). Its grid is the `pitch` control input
    through a 10k stopper, its cathode returned to -150 V through 68k.
  - The 884 across CT: anode at B+ through RS (450 ohm), cathode at `n`; its grid on a -12 V
    cell (the cathode moves) through 2.2k, no capacitor, so no grid lift across cycles. It
    strikes at ~113-126 V: a ~110 V sweep, RCA's ~33.
  - A 12AU7 follower off `n` through a 100k stopper, its plate on a 450 V rail of its own,
    AC-coupled to `out` (the sawtooth inverted; `saw` until 2026-11-03). **Its own rail matters:** with its plate
    on B+ it ran out of headroom when `n` leapt to near B+ at each strike, its grid
    conducted, and the charge it put back into CT made the oscillator 11% sharp (the unit
    has no follower, so K was 14-39 c off the voice).
  - The pitch input runs from about -250 V (~10 Hz) to 0 V (~4.5 kHz): the 6V6GT's model
    conducts to ~-70 V grid-to-cathode. A keyboard's tuning table will map it. The input
    has a 1 Mohm load (a CV input's; it keeps the node in the first part).
  - Ideal supplies for now (as RCA's reference circuit's B+).
- **Renders (M1):** the oscillator section is an island (`substeps: 16`, `decimate: fir`),
  cut at the follower's cathode (`owns: [kf]`: a low impedance into the output's 1 Mohm).
  Everything whose current the ramp feels is inside:
  - the charger (its current is the ramp);
  - its grid stopper: a cut at its grid, the stopper outside, turned each strike's edge
    through the grid-to-plate capacitance into a kick on the grid a sample late (+3 c at
    565 Hz);
  - the follower.
  The pitch input's node stays in the first part (control inputs live there).
- **Live (K):** an events build of a section holding event kernels drops its `substeps`,
  `decimate` and `owns` (both builders): one file renders with M1 and plays with K.
  - `config/sim_settings.yaml`'s draft block has `events: true` (the live qualities). The
    native app builds every circuit with its quality's flag (`Circuit::with_events`;
    production, renders and prints, without), only for a file that names tables. Python's
    settings take the key; its builds take `events=` themselves.
- **Its tables:** `config/events/884_saw.json` (`thyratron_kernels.py --unit saw --write
  884_saw`). The unit: C 5 nF, R_s 450, R_g 2.2k, a constant current; its grid over -14 ..
  -10 V, its slopes over 0.002-0.8 V/us. The reference runs' length scales with the bias
  (the strike ~10.7 V per volt). The steady strike is the last one whose plasma decay is
  seen within the run (a strike at the run's end gave a NaN dead time).
- **The unit check** (`reports/hybrid/k_unit_saw_fine.json`), 28 Hz-5 kHz: K draft within
  -2.9 .. +0.6 c, harmonics within 0.06 dB, inharmonic -89 .. -95 dB from 90 Hz to 4 kHz,
  0.13-0.16x real time. At 28 Hz everything reads -40 dB, the reference included (half a
  second holds too few cycles). At 5 kHz see H3d's open item.
- **The voice against its reference** (the whole circuit as one solve at production, 16x;
  converged: 32x moves it 0.05 c, and production at 2x is within 0.23 c at 4.3x real time):
  | pitch input | reference | K, the draft (live) | M1, production (render) |
  |---|---|---|---|
  | -200 V | 565.2 Hz | +2.6 c, 0.32x real time | +0.66 c, 7.7x |
  | -100 V | 2533.2 Hz | +1.4 c, 0.35x | +0.46 c, 10x |
  | 0 V | 4524.1 Hz | -1.0 c, 0.40x | +0.85 c, 10.5x |
  - **Measure M1's pitch on `n`, not `out`:** the band-limited edge's ringing crossed the
    middle of a 21-sample period and read +42-50 c at 4.5 kHz (periods down to 1.1
    samples).
  - K's cost here is the voice's tubes: the 6V6GT and the 12AU7 at the draft; the unit
    alone was 0.14x.
- **The keyboard tuning** (`scripts/saw_884_tuning.py` -> `reports/hybrid/saw_884_tuning.json`
  / `.png`, 2026-11-03): K at the draft, the pitch on `n`, the input 5 V apart from -250 to
  0 V, bisected wherever the keyboard's interpolation (linear in log2 Hz) missed the law by
  more than 1 c (to 0.31 V): 100 points, **13.2 Hz to 4.52 kHz**, monotonic. Cycle-to-cycle
  spread (2.5-97.5 %) 0.1 c at the bottom, 1-3 c at 0.5-1.5 kHz, 8-13 c at the top (periods
  of ~21 samples). Below ~17 Hz (-248.75 V and down) the ramp is slower than the tables'
  0.002 V/us: K holds their end there (the monitor; a take re-renders through M1).
- **K against M1 in the bass (open):** at the same input K reads sharp of M1, by a nearly
  constant ~0.3 uA of charging current (cents ~ 1/f): -0.7 c at 4.5 kHz, +1.3 at 2.5 kHz,
  +2.3 at 567 Hz, +7 at 179 Hz, +23 at 47 Hz, +77 at 13 Hz (out of the tables). A take
  played on K and re-rendered comes out flat by that much. What's known:
  - Not the quality: K at the draft and at production agree within 3 c (at 2x and 4x
    oversampling within 0.1 c).
  - **The reference isn't converged in the bass:** the whole circuit as one solve reads
    46.49 / 46.55 / 46.67 Hz at 2 / 4 / 8x and 45.91 / 45.92 at 16 / 32x (-240 V); 179.3 ->
    178.6 Hz (-225 V), 566.8 -> 566.1 Hz (-200 V). The jump between 8x and 16x is the same
    ~0.3 uA at every pitch, and below it the reference agrees with K (within ~1 c). K at 8x
    jumps the other way (+15 c at 47 Hz). Each run is steady (0.1-0.2 c cycle to cycle):
    the period lands in step-dependent places, not noise. (The earlier "32x moves it
    0.05 c, production at 2x within 0.23 c" at -200 V doesn't hold now: 2x is 1.6 c off.)
  - It is the voice's, not the solver's: the unit (K's own) with its ground floated on a
    5000 V/s triangle moves 0.03 c, and K matches it within 0.2 c at 46 Hz. In the voice
    the 8x-16x jump is 28 c as is, 3.6 c without the follower (its grid stopper cut), 3.0 c
    with an ideal charger in place of the 6V6GT, -10 c with both.
  - The KCL at `n` in the 16x reference doesn't close by ~0.3 uA against the probed paths
    (the charger's cathode current, CT, the leak, the follower's grid, the 884 through RS);
    K's closes within ~25 nA.
  - Leads: the strike's ~120 V edge into the charger near its cutoff and the follower's grid
    (each resolved differently by the step); the error control's step choice over the
    pre-strike runaway (the reference tube's anode current rises from ~20 nA to ~0.7 uA
    in the last ~10% of the ramp, K's off tube has only its leakage; integrated that is
    ~0.5 nC a cycle, too little for 23 c, ~8 nC).
  - Left for later (timeboxed; it doesn't block playing: what is played is tuned on K).
- **The app's device** `saw_884` (`panel::DEVICES`, after the kick): pitch from the keys
  through `SAW_884_TUNING`, no gate, no panel controls, draft-2x (96 kHz internal: 32 of
  K's 3.072 MHz samples a step), no cores. The app plays a circuit's `out`: the output
  node is now `out` (was `saw`; the app fixtures re-exported, the agreement test passes).
- **Its load with a key held** (`examples/play.rs --device saw_884 --hold NOTE`, the UA
  Twin, 30 ms buffer): A3 (220 Hz) 16% (worst block 27%) over 20 s; C8 (4186 Hz) 24%
  (worst 40%); A0 (27.5 Hz) 15% (worst 25%); no dropouts. Output ~-3 dBFS (A0 -12.7).
- **The gate (2026-11-03, the user's ask: it sounded with no key down).** `saw_884` now has
  a `gate` input and a VCA; the oscillator runs all the time, as a real one would, and the VCA
  opens onto it.
  - The envelope is tube_voice.yaml's: the keyboard bus (-110 V up, -1 V down) through
    ATTACK / RELEASE rheostats and a 6X4's two sections onto 0.47 uF.
  - The VCA is tube_kick.yaml's: a 12AU7 pair whose tail (a third section) has 0.8 of the
    envelope on its grid, then a 12AX7 differential stage on a 12AU7 current sink, so the
    envelope's own step cancels. The saw goes in through 2.7M / 100k (~+-2 V at the grid:
    the pair nearly linear, the ramp kept). The VCA's rails are ideal, like the oscillator's.
  - **Cross-neutralization:** 2.2 pF from V5A's grid to V5B's plate (the 12AU7's C_gp).
    Without it the saw leaked past the shut pair through C_gp, -82 dB at 179 Hz to -67 dB at
    4.5 kHz; with it, closed is -114 .. -129 dB.
  - The draft (K, one solve): open ~18 V rms, peaks 28-34 V (A0 ~43 V: the saw tilts
    through the couplings; `full_scale` 50 V). The envelope's own step is -50 dB re the
    peaks (0.1 V, the saw disconnected). Gating the saw at a fast attack gives a ~1.2 V sub-20
    Hz edge, as any VCA would. The pitch is unchanged (the tuning table stands, to 0.01 Hz).
    M1 at production: the same levels, closed -124 dB, the pitch -1.4 c from K.
  - **Two threads** (`panel::Device::partition` `["vca"]`): the VCA | the rest. Control
    inputs stay in the first part, and a shared node belongs to the highest-numbered part,
    which needs a DC path there. So the envelope stays with the keys, and the cuts are the
    VCA's high-impedance inputs: `ga` (2.7M into 100k) and the tail's grid `gt` (5.6M into
    22M, with a new 100 pF CGT: ~50 samples of time constant against the sample of lag).
    - A cut at `ba` (the envelope's bus resistor) went singular with the key up: both
      diodes off, the node held by an injected current only.
    - A cut at `saw` (through CO) would diverge (CLAUDE.md's coupling-capacitor note).
  - **Edges need `hold` coupling.** The draft's `extrapolate` doubled the saw's one-sample
    edge for a sample at `ga`: peaks 49 V against 34, rms +0.3-1.3 dB. With `hold` it matches
    the one solve. `panel::Device::coupling` (new, None = the quality's) sets it per device;
    saw_884's is "hold".
  - Load with a key held: A3 28% (worst block 49%), C8 51% (79%), A0 26% (41%), 0 dropouts.
    Ungated it was 16-24%: the VCA's seven sections on one thread took it to 45-71% (worst
    116%) before the split, and the envelope's 6X4s sit on the oscillator's thread.
- **Next: the saw as tube_synth's second oscillator** (the user, 2026-11-03: with the
  synth's mods; SYNTH_IDEAS.md #9 and #23). The decisions so far (the user delegated H4's):
  - **A copy of the oscillator in tube_synth.yaml** (the format has no includes; tube_kick
    copies the LC oscillator too), into the synth's mixer, its filter, envelope and VCA (its
    own VCA isn't needed there). The 884's values stay the tables' unit (5 nF, 450 ohm, 2.2k).
  - **SAW ON / OFF** (`saw_on`, a checkbox, off at first: the synth as before). Off empties
    its sections, as LFO ON and RING ON do: no thread, no CPU.
  - **Its own supply**, a winding of its own as the LFO has (the 6X4 is at its rating):
    silicon into a reservoir for the follower's plate (~450 V), an RC to its B+ (~300 V),
    and the charger's cathode return on two 5651s (-174 V; no OA2 component). At the bottom
    the charger's current is ~1.7 V over 68k, so that rail sets the low notes' pitch: it is
    regulated, and the tuning is re-measured on it.
  - **Its pitch from a second keyboard string** (a control input of its own; the app's
    `panel::Device` gets a second `Pitch`, its own measured tuning): the saw's law (~linear
    in the charger's grid) isn't the LC's, so one pitch line can't tune both.
  - **GLIDE** a second gang of the GLIDE rheostat onto its own 4.7 uF, ahead of the
    charger's stopper. The charger's grid gets 0.1 uF, as the LC's 6V6GT has: the strike's
    kick through C_gp is then millivolts, and the draft can cut there.
  - **VIBRATO** the same pot's wiper summed into its pitch line. The saw's law is linear,
    so a fixed vibrato voltage is deeper at low notes in cents: set for ~+-1 semitone near
    C4, it is ~+-8 c at the top and ~+-2 semitones at 47 Hz. A constant-cents vibrato would
    move the strike (the 884's grid bias: ~9.5% of pitch per volt), but that grid floats on
    the ramp's cathode (120 V swings), and an LFO at 0.08-19 Hz can't be coupled in there.
    Left as the linear oscillator's character.
  - **Its level** a SAW pot into the mixer beside OSC (1M, as the oscillator and the ring).
  - **Its thread** of its own in the draft's partition. Its edge crosses into the mixer: the
    `hold` coupling above (for the synth's other cuts, the rails, extrapolation is better:
    per-node coupling, or measure the synth under `hold`).
  - Later, one at a time: DETUNE (a fine pot on its pitch line), COUPLING (SYNTH_IDEAS #9:
    the LC's signal into the 884's grid loop through a small transformer, so it pulls and
    locks: the sweep circuits' sync input; within K's grid range, +-2 V), the ring's carrier
    from the saw (#14's "waits for #9"), its own supply's ripple and sag as character.
- **Built (2026-11-03): the saw in tube_synth.yaml** (its header says how; sections `saw`
  (the M1 island), `saw pitch`, `saw supply`; values `saw_*`; the app's `pitch2`):
  - **Switches** (the user's ask, CPU): SAW ON (`saw_on`, off at first) and OSC ON
    (`osc_on`, on at first) for the LC. Off, a section is empty: no thread. With OSC OFF,
    1 ohm holds what others took from the LC (its buffer, at the mixer and the ring) and its
    probed nodes. Both builders: a section its switches leave empty is no island (it owned
    a node it didn't have).
  - **Its supply**, as built after two flaws showed in a key change from a high note to a low
    one (the low note started ~24 c flat and recovered over ~2 s):
    - The charger's cathode return straight off the two 5651s, an RC *ahead* of them (an RC
      after them made the rail follow the charger's current with a 0.22 s lag).
    - The charger's screen on two 5651s of its own (+174 V): on B+, which moves ~15 V with the
      charging current, the screen moved the cathode ~1/9 as much.
    - The vibrato follower's plate on that regulated rail too (on B+ its output moved ~1/mu as
      much), its standing current 0.45 mA (it only sources the summing network's <= 1.1 mA).
    - What's left: ~-8 c after a five-octave leap down (2 kHz -> 65 Hz), back within ~1.5 s
      (the 5651s pass ~4% of their prefilter's slow movement, and only ~3 V sits across the
      charger's cathode resistor at the bottom: a resistor-set current over 60:1 has a
      hypersensitive bottom). Smaller leaps less. Left as drift (the user's "drift fine").
    - From power on (SAW ON restarts the stream) it settles within ~2 s, -10 c at the bottom
      in the first 0.3 s.
  - **Its tuning** (`scripts/saw_884_tuning.py --target synth` ->
    `reports/hybrid/synth_saw_tuning.json`; the app's `SYNTH_SAW_TUNING`): 114 points, 10.8 Hz
    to 3.99 kHz over `pitch2` -310 .. 0 V (the screen's 174 V moved the law: its bottom near
    -310 V). Spread 1.4-1.9 c in the bass, up to 13 c at the top. K against M1: +0.4 c at
    1.9 kHz, +0.7 at 4 kHz, +33 c at 39 Hz (the bass item above).
  - **The mix:** through 2.2M (the ring's), the saw ~+-12 V across its 100k pot (390k): alone
    -9.3 dBV out at the panel's defaults (the LC alone -7.3: the filter takes more of the
    saw's harmonics), both -7.8. A passive mix: SAW ON pulls the LC's share down ~1.5 dB
    (through 1M, ~3 dB, and the saw came in 6.4 dB under).
  - **Coupling:** the synth keeps `extrapolate`. Unlike saw_884's VCA grid, the saw reaches
    the mix through 0.1 uF, 2.2M, the pot and 2.2M into the node's stray capacitance; the
    mix's peaks match the one solve (0.56 against 0.55 V), levels within 0.3 dB.
  - **Its thread:** `saw pitch` + `saw` (it owns `s_kf`, the follower's cathode), its supply
    with the synth's supplies (placement measured: the saw's thread, the supplies' or its
    own, within 5%; the LFO's or the envelope's thread no better, the LC's worse).
  - Tests: tests/test_tube_synth.py (the switches; the saw at its table's pitch through the
    VCA with the LC off); the synth's scripts and tests give `pitch2` (0 V with the saw off).
- **CPU (measured 2026-11-03; Python, one run at a time, a held C7, the LFO on; the app's
  meter reads lower):** the synth as before 1.25x real time; LC + saw 1.49x; LC + saw at SAW
  level 0 1.39x (the filter and VCA work ~+0.1x on the saw's edge); the saw alone (OSC OFF)
  0.96x, 0.90x at SAW level 0. In the app (30 ms buffer): before 71-74% load (worst block
  92%); LC + saw 81-110% with dropouts at high keys (C7: ~100 per 12 s); the saw alone
  77-100%, worst blocks 104-142%, a few dropouts per 15 s (this desktop's drift is +-35%).
  One oscillator at a time is the budget; both is over it on this machine. The saw alone's
  dropouts: docs/SYNTH_REALTIME_PLAN.md (2026-11-04).
- Later for the voice itself: its own supply instead of ideal rails; the bass agreement
  above; the unit's 5 kHz floor (H3d's open item).

**H5. The second exception.** Generalize the machinery only once a second user exists,
likely candidate 2 or TM5's bias oscillator. Until then, keep it specific to the first.

## Open decisions (the user's)

- **Production: exception or reference?** Renders are offline, and for tape the user
  chose quality before real time. Production could run the reference (pure, slow) and
  draft the exception, or both could use the exception once H3 shows it's
  indistinguishable.
- **The hard rule's wording** (above), when H3 is done.
- **Where H1-H4 go in the order** relative to the synth's other ideas, tape TM5 and the
  reverbs.

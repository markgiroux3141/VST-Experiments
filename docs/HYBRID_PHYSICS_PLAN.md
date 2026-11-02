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

**H2. The event study.**
- How long the reset is.
- How much it changes over the conditions (strike voltage, grid, supply, heater).
- How much of its spectrum lies above 48 kHz.
- How much the direct simulation aliases at 96 kHz.

*Done when:* the numbers pick K or M, brought to the user with options.

**H3. Event kernels in the engine** (if K): the Python reference and circuitsim (event
detection, the crossing time between samples, the minimum-phase charge pulse, the state
afterwards, the switch to the reference). *Done when:* the sawtooth with the exception
matches the reference within stated bounds (pitch, harmonics up to 20 kHz, supply current
per cycle, aliasing floor), and its draft and production costs are measured.

**H4. The sawtooth in the synth.** A device of its own, then S5's second oscillator.
*Done when:* the user plays it live, at a load measured with a key held (`examples/play.rs
--hold`).

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

# Tape speed: a faster literal print, and a fast tier trained on it

Drafted 2026-11-02 from a brainstorm with the user, parked until picked up; nothing built.
It continues TAPE_PLAN.md's "Speed: the GPU" (levers 1-4; lever 1, the stream's recording
worker, is done) and feeds TM7 (real time) and DELAY_PLAN.md's "Real time". Milestones P1-P6
(the literal machine faster) and F1-F5 (a fast tier), each finished only when its "done when"
is met, as in the other plans.

## Where it stands (2026-11-02)

- The literal Ampex 351 prints at **~84x slower than real time** (0.5 s of drums at +6 dB,
  production, one job alone, the 1 s settle counted; `scripts/speed_351.py`).
- It runs as two coupled parts:
  - the record side, five triodes plus the bias oscillator at 20 steps per sample
    (3.84 MHz), was 62.7x alone with the old heads;
  - the tape part (the recording kernel, the demag fixed point, the reproduce side) was
    36.3x alone.
- Together they are slower than the record side alone: they meet every sample, and the
  threads spin while they wait.
- Measured and closed:
  - 10 substeps is under-resolved for the 92.9 kHz oscillator, whatever the integrator does
    (TAPE_PLAN.md "Gaps" 4);
  - tube tables everywhere are exact but give only ~10%;
  - multi-rate parts already step without local error control.
- **The rule from those studies:** judge every record-side numerical change on the noiseless
  machine's floor (`scripts/tape_snr_study.py --cells`), not only on band levels of music. A
  -78 dBFS line is invisible in drums. The bound (the user's): the floor at least 14 dB under
  the real noise, <= -89.4 dBFS.

## What is not the limit

- **The language.** Rust compiles through LLVM, as C and C++ do, and hand-written assembly
  rarely beats it on this code. The DK solver's linear algebra already uses AVX2 (the
  circuit-sim plan's "Speed after Phase 3").
- **What does limit us:** time steps are sequential, at 3.84 MHz in the fast part. Gains come
  from doing less work per step, fewer steps, overlapping the parts, or running independent
  pieces of time at once.

## The literal machine faster (P1-P6)

Each P-milestone is a measured setting against production: the drums' band levels against 40
substeps, the noiseless floor, the profile's specs. The alignment is re-run whenever a change
can move it.

**P1: measure the split with the new heads.**
- The record side alone, the tape part alone, the whole, and the threads' idle (spin) time.
- Use `--features timing` and `examples/profile.rs`, or a part-only variant in
  `speed_351.py`.
- Done when the table is in this plan and says which part bounds the wall time.

**P2: the parts decoupled.**
- The record side meets the rest only at the input and the 330 / 250 / 220 V reservoirs,
  which move slowly. Couple them with a block of lag (e.g. 32-128 samples) instead of one
  sample, and park the threads instead of spinning.
- Expected: the wall time near the slower part's (~84x -> ~60x), and cores freed for P3.
- Done when the floor and the profile hold, and the block's lag is measured against the
  one-sample coupling.

**P3: parallel in time.**
- A print split into chunks, each with a warm-up (1-2 s: the supplies, the reproduce EQ's bass
  tail, the 133 ms head gap), run on separate cores and joined.
- It's offline, and the noise streams are already a pure function of the sample index. The
  670's compression curve does the same (chunks with a warm-up step, equal to a continuous run
  within 3e-6 dB).
- The free oscillator's phase differs at a seam: compare in band levels and the floor, not in
  waveforms.
- Expected: ~2-4x wall clock for one long print; it also makes F-milestone training data
  cheaper.
- Done when a 3-minute print in chunks equals the continuous print in band levels within
  0.05 dB, with no seam audible or visible in a spectrogram.

**P4: a cheaper method in the fast part.**
- esdirk4 runs ~5 implicit stages a step; an L-stable 2-stage method (trbdf2) at the same or
  more substeps may hold the floor at less cost.
- Also tube tables scoped to the multi-rate parts (a per-part option in `stream.rs`; global
  tables would move every circuit's renders).
- Expected: 1.5-2x on the record side.
- Done when the cheapest setting that meets the floor bound is measured and adopted.

**P5: the tape kernel on the GPU, and SIMD.**
- The kernel (every cell times 8 orientations over every bias peak in its zone) is
  independent over cells. On the RTX 3080 that means f32: f64 there runs at about this CPU's
  rate.
- An f32 tier validated against the f64 kernel (the user's rule: keep a CPU reference).
- Also SIMD on the CPU kernel: check it vectorizes over cells and orientations, and try f32
  lanes.
- Expected: 5-10x on the tape part (GPU), 1.5-3x (SIMD); it pays only once P2-P4 make the
  tape part the bound.
- Done when the f32 print is within -80 dB of the f64 print and its floor holds.

**P6: the draft tier (TAPE_PLAN.md TM5's option B).**
- The bias carried as an amplitude at the audio rate (a table against 1C2c's voltage, its lag,
  NOISE BALANCE's asymmetry): no 3.84 MHz part at all.
- It misses the bias inside the 6201 (measured: -34 dB at +12 dB drive, negligible to +6).
- For auditioning; the literal machine stays the print.
- Done when it is measured against the literal print across drives.

**Exotic, not planned:**
- Envelope following / multi-time methods from RF simulation: simulate the 93 kHz carrier's
  envelope, not each cycle. But audio to 15 kHz is only ~6x below the carrier, where these
  methods need ~20x: perhaps 2-3x, at real risk.
- Parareal (iterated coarse and fine solves in time): P3 gets most of its gain for offline
  prints without the complexity.

Together, P2-P5 might bring a single print to ~15-25x, and a 3-minute song to roughly 20-40
minutes on all cores (estimates until measured). Real time needs F.

## A fast tier trained on the literal machine (F1-F5)

The literal 351 is the ground truth: it can make unlimited, perfectly aligned input / output
pairs at any panel setting and condition, which modelling real hardware never has.

**This doesn't break the project's rules.** Nothing in it is a curve chosen to sound like
tape. It's a learned stand-in for the physics model, measured against it, as the draft
quality is measured against production. The literal machine stays the reference and the final
print; the fast tier is for real time (live play, TM6's audition slot, DELAY_PLAN's slap).
Main-plan Phase 7 (the 670's neural surrogate: a TCN or RNN with FiLM conditioning,
`varimu/surrogate/`, a stub) shares the infrastructure.

**F1: split what a deterministic model can't learn.**
- **Wow and flutter:** the transport's speed trajectory is already a cheap physical model.
  Reuse it as a variable delay.
- **Noise:** hiss, modulation noise growing with level, hum. A small generative model, its
  spectra and level dependence measured off the literal machine (`tape_snr_study.py`).
- **The deterministic core:** the literal machine with its noise and flutter off. This is what
  F2-F3 learn.
- Done when the core's renders plus the cheap transport and noise reproduce the literal
  print's spectra and flutter within the profile's measures.
- Mikkonen, Wright, Välimäki et al., "Neural modeling of magnetic tape recorders" (DAFx 2023,
  as recalled; check it) split a real tape machine the same three ways.

**F2: a grey-box core (TM7's reduced medium, DELAY_PLAN.md "Real time").**
- Record EQ, then a hysteresis operator (Preisach on the bias's envelope, per layer), then the
  gap and spacing losses as a FIR, then the playback EQ. Each block fitted to the literal
  machine, the electronics kept as circuits at the audio rate (the reproduce side runs ~2.5x
  alone at production, far less at draft).
- Interpretable, it behaves sensibly outside its training data, and TAPE_PLAN's condition
  dials map to fitted parameters.
- Done when it plays in real time and an ABX against the literal print doesn't tell them apart
  at the default panel (the user's rule: realistic differences too subtle to choose between
  count as verified).

**F3: a neural core, if F2 can't match closely enough.**
- A GRU / LSTM of 32-64 units conditioned on the panel and conditions (FiLM). About 1 GFLOP/s
  at 48 kHz: one core, 10-100x faster than real time.
- Tape's long memory (the head gap's 133 ms, the 3180 us bass EQ, supply sag) needs the
  delay outside the network and care with the bass.
- A TCN (WaveNet-like) as the more accurate, heavier alternative.
- Done as F2.

**F4: training data.**
- A grid over drive, bias, speed and the condition dials, on program material and test
  signals.
- Minutes per setting; maybe 30-60 minutes of audio in all. At today's speed that's a day or
  two of machine time, less after P2-P3 (chunked renders).
- Seeds and settings recorded so the set is reproducible (Hard rules).

**F5: in the app.**
- The fast tier as varimu-app's live device (TM6), with "print" rendering the literal machine.
- Done when the user plays through it live and the print replaces it on render.

## Order (proposed)

1. P1, then P2 and P3: cheap, and they speed up everything after, F4's data included.
2. Then F1-F2, the grey box first, for real time.
3. P4-P5 when a literal print's wait matters more than real time.
4. P6 if auditioning is needed before F2 is ready.

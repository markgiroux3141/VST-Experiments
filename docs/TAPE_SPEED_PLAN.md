# Tape speed: a faster literal print, and a fast tier trained on it

Drafted 2026-11-02 from a brainstorm with the user. Picked up 2026-11-08 (the user away,
every call delegated): P1-P3 built and measured, P4 measured; see "Status (2026-11-08)".
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

## Status (2026-11-08): P1-P3 built and measured; the kernel is the bound

The harness throughout: `scripts/speed_351.py` (0.5 s of drums at +6 dB, production, noise
off, one job alone, the 1 s settle counted; `--alignment` takes a cached alignment's panel,
since `tape_align.aligned()` re-aligns, ~32 min, after any change to the Python it hashes).
`CIRCUITSIM_PART_TIMING=1` makes circuitsim print each part's busy and waiting time and the
tape worker's (`stream.rs`, `tape_stream.rs`).

**P1, the split (done).** Lockstep, 76-79x real time (137 s wall):

| thread | busy | waiting |
|---|---|---|
| part 0: supply, tape, reproduce side | 21 s | 117 s |
| part 1: the record side at 3.84 MHz | 117-122 s | 15-16 s |
| the tape's recording worker (its kernel on 12 threads) | ~120 s | the stream waited on it 9-11 s |

The kernel's threads (`ttN`, `CIRCUITSIM_TAPE_THREADS`, a new override; the output doesn't
depend on it), with the process's CPU time:

| kernel threads | wall | x real time | process CPU | record side busy |
|---|---|---|---|---|
| 12 (default) | 137 s | 79 | 1500 s | 117 s |
| 8 | 161 s | 93 | 1351 s | 114 s |
| 4 | 244 s | 141 | 1115 s | 97 s |
| 2 | 444 s | 256 | 1055 s | 93 s |

- **The recording kernel is ~90% of the CPU work** (~900 thread-seconds for 1.7 s of audio,
  ~500 per second of audio). The record side looks like the bound only because the kernel is
  spread over 12 threads; alone, without the kernel's threads beside it, it runs ~54x.
- So the machine is saturated by one print: a 3-minute song is ~3-4 hours whatever P2-P4 do
  to the circuit. **P5 (the kernel on the GPU) comes first now**; P4 and P3 multiply after it.

**P2, the record side decoupled (built, measured: no gain now).** A multi-rate section's
`lag_samples: N` (IR `Section.lag_samples`, both builders, absent = lockstep; refused on a
section that owns nodes or decimates): its part reads the others' couplings N samples late,
interpolated between published samples, and runs up to N samples ahead (rings of 2N + 3
samples; a lagged stream refuses `update`). Tests: `crates/circuitsim/tests/partition.rs`
(`a_lagged_multirate_part_sees_the_rest_late`: the fast part sees the stiff node N - 1
samples late, within 3.9% of the prediction; bit for bit from run to run),
`tests/test_circuit_ir.py`. On the 351:

| lag | x real time | waveform vs lockstep | bands vs lockstep |
|---|---|---|---|
| lockstep | 76-79 | | |
| 16 | 81 | -85.8 dB | 0.000 dB |
| 64 | 78 | -74.0 dB | 0.001 dB |
| 256 | 77 | -57.6 dB | 0.006 dB |

The record side still waits 13-15 s: part 0 stalls on the tape worker a whole 16 mm block
(~8000 samples) at a time, more than any lag across the rails should absorb (256 samples is
already 1.3 ms of the supply). Nothing in config uses it; revisit after P5, when the
worker no longer stalls part 0. The spin-wait (`Shared::wait`) is not the cost: the
waiting threads are the cheap ones.

**P3, prints in pieces (built; not useful until P5).** `Options::origin_samples` (circuitsim;
Python `simulate(origin_samples=)`, `fast.run_transient(origin_s=)`): a run starts as sample
K of a longer run from t = 0 in everything that depends on time alone: the sine sources'
phase (at the DC point too), the noise streams (white ones jump there, flicker and the mains
wander walk), a tape's transport (flutter's phase, its random parts) and grain (from the cell
the nominal speed has brought to the gap; `TapeStream::set_origin`, `tape_stream_run(origin=)`).
`fast.run_transient_chunked` runs pieces at once on threads: each starts `warmup_s` early at
its place (the input faded in over 50 ms or half the warm-up), runs 20 ms past what it keeps
(the resamplers' edges), and hands over through a raised-cosine crossfade. Tests:
`crates/circuitsim/tests/origin.rs` (a piece from origin K equals the whole run from K to
1e-9 V, noise and mains wander included), `tests/test_chunked.py` (pieces rebuild a noisy RC's
continuous run to 1e-6 rms), `tests/test_tape_stream.py` (the origin moves only grain and
flutter). `scripts/chunk_351.py` compares the 351 in pieces with the whole print (band levels
overall and around each seam, waveform at the seams). On this machine it can't be faster
than the whole print until the kernel leaves the CPU: one print already uses 11 cores.
Measured on 8 s of the drums at +6 dB (4 s pieces, 2 s warm-up, 2 at once; with noise):
- the whole excerpt's band levels within **0.030 dB** of the continuous print (the done-when
  asks 0.05 on 3 minutes: that run waits until the pieces are worth running, after P5);
- at the seams the waveform differs -46 / -53 dB re rms and 200 ms windows' bands 0.14-0.15
  dB, the same as in the pieces' middles (-46 dB, 0.06-0.20 dB): the free bias oscillator's
  phase and the grain's cells, not the seams;
- 138x real time against the whole print's 95x (Rust tests ran beside both): as expected,
  no faster while the kernel saturates the CPU.

**P4, a cheaper method in the record side (measured; adopt after P5).** circuitsim's
experiment switches `CIRCUITSIM_MULTIRATE_METHOD` / `_TABLES` (`speed_351.py` variants
`mtrbdf2`, `mtables`), the floor on the noiseless machine (`--floor`) and the drums:

| record side | floor line | noiseless noise | record side busy (drums) | drums x real time | bands vs 40 substeps |
|---|---|---|---|---|---|
| esdirk4 (production) | -114.0 dBFS | -95.16 dBFS | 117 s | 79 | 0.061 dB |
| **trbdf2** | -113.7 | -95.18 | **65 s** | 69 | **0.043 dB** |
| trbdf2 + tube tables | -113.7 | -95.18 | 59 s | 68 | 0.043 dB |
| tube tables | -114.0 | -95.16 | ~6% less | | |

trbdf2 at 20 substeps holds the floor (bound <= -89.4) and halves the record side's cost
(1.8x), closer to 40 substeps than esdirk4 is. The wall moves only 79 -> 69x: the kernel is
the bound. Adopting it is a per-section method (an IR field like `lag_samples`, both
builders, instead of the switch), then the 351 re-aligned and profiled: worth it once P5
makes the record side the bound.

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
- Expected: 5-10x on the tape part (GPU), 1.5-3x (SIMD). P1 (2026-11-08) found the kernel
  ~90% of the CPU: this is now the first lever ("Order").
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

## Order (revised 2026-11-08, after P1's measurement)

1. **P5's GPU kernel first**: it is ~90% of the CPU (Status above). With it the record side
   (~54x alone) becomes the bound.
2. **Then P4** (a cheaper method in the record side: its measurement is in the Status), and
   **P3** (pieces at once: each piece is then about one core, so ~6 at a time on this
   machine): together perhaps a 3-minute song in ~30-60 minutes instead of 3-4 hours.
3. Then F1-F2, the grey box first, for real time (DELAY_PLAN.md's reduced tape is most of
   F2 already: tables of M_x per layer, recording apertures and D(k), measured off the
   literal machine and playing live in the echo).
4. P6 if auditioning is needed before F2 is ready.

### P5's design (2026-11-08, not built)

- **What runs:** `tape::record` per 16 mm block: every (layer, cell) a backward pass over
  the bias peaks in its zone (`s_rec`, `hg`, the head field from `FieldTable` or
  `head_field`), 8 orientations each a `Corner` (a branch and a bicubic `q_diff` on the
  Preisach table at each new maximum), then `finish` and the orientation sum. Independent
  over (layer, cell, orientation): ~50 M threads per second of audio, each a loop of a few
  hundred peaks. On the GPU: one invocation per (layer, cell, orientation) (or per cell with
  the 8 orientations in registers, which shares the field lookups), the peaks and the
  Preisach / field tables in storage buffers.
- **Precision:** f32 (the 3080's f64 is ~1/64 rate). `up` sums positive increments of O(1):
  ~1e-6 relative after a pass, near -120 dB of the magnetization; the field arithmetic is
  benign. Done when the f32 print is within -80 dB of the f64 print and the noiseless floor
  holds (P5's done-when above). The f64 CPU kernel stays the reference and the default
  without a GPU (the user's rule: keep a CPU reference).
- **Where:** a crate beside `roomsim` (whose wgpu device setup, buffers and "f64 CPU
  reference per kernel" tests it copies), used by circuitsim behind a cargo feature so the
  Python extension and the app opt in; `Recording` gets the switch (a setting, like
  `threads`; the output differs from the CPU's by the f32 rounding, so prints say which).
  The worker already records a block at a time off the circuit's threads: the GPU call goes
  there.
- **Then measure again:** the kernel's GPU time per block against the record side's per
  block; if the GPU leaves the worker idle, P4 and P3 are next.

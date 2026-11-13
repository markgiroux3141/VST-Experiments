# Tape: the Fable review

2026-11-12, at the user's request: a read-only review of the tape emulation by Claude Fable 5
(the model, its studies and its plans were built in sessions on Claude Opus). The question:
is there more to do, in better physics or in speed on the CPU and the GPU?

**Nothing was run and nothing in the model, the engine or the circuits changed.** What was
read: TAPE_PLAN.md, TAPE_SPEED_PLAN.md, TAPE_HEAD_RESEARCH.md, the verdicts of TAPE_PARTICLES.md
and TAPE_PARTICLE_RESEARCH.md, PERIOD_GEAR_BACKLOG.md's chirp section, the over-bias study's
logs in `reports/tape/`, `varimu/devices/preisach.py`'s docstring, circuitsim's `tape.rs`
(the kernel) and `tape_stream.rs` (the recorder and its fixed point), and `crates/tapegpu`.
Not read: `varimu/devices/tape.py` and `tape_machine.py` line by line, `varimu/delay/reduced.py`,
the stream's playback path, the record island's circuit.

Tags on each item:
- **[docs]**: already in the plans (this review only reports it);
- **[connected]**: the facts are in the plans or the code, the connection between them is this
  review's;
- **[new]**: not in the docs as read;
- **[estimate]**: a figure derived here from the plans' measurements, not measured.

Every proposal below is a hypothesis until it is measured. Model changes that move renders are
the user's call (options with numbers first), as always.

## Short answer

- **Physics.** One finished correction is waiting for a decision (the exact record gap), and
  three cheap terms have not been tried: the coating's reversible magnetization, the noise a
  biased tape makes on a real machine, and the mechanics between channels (azimuth and skew).
  Print-through has been recommended twice and is not built.
- **Speed.** The GPU kernel is no longer where the tape's time goes. What surrounds it is: the
  demagnetization's transforms on one CPU thread, the buffers and readbacks of each pass, and
  a fixed point that takes nine kernel passes per block. Since the cells were halved the tape's
  worker probably bounds a print again. For the four-track deck the bound is one thread
  carrying four record amplifiers.

## 1. The second round of the over-bias study (another session's, in progress)

TAPE_PLAN.md's last status block stops at step 1b. The exact record gap (commit b671b69) and
the astroid on top of it have been measured since; the numbers below are read from
`reports/tape/overbias_exact.log`, `overbias_round2_no21.log`, `overbias_round2_o3d.log`,
`overbias_round2_iso.log`, `overbias_round2_l.log` and `level51_wide_base.log`. **A parallel
session was still running the 51 um knee runs when this was written (22:55; `level51_wide_*.log`),
so its own write-up in TAPE_PLAN.md supersedes this table.** [docs, not yet written up]

The checks are the over-bias study's (Sound Talk No. 21: one bias scale and an offset per
curve; the knee: the 3% THD level over the 1% at 400 Hz; Bulletin 14: the permissible level
at 7 kHz re 400 Hz, at the -40 / -30 dB criteria).

| variant | No. 21 rms 1k / 15k | 1k rise at 3 mA | 1k / 15k at 8 mA | 15k - 1k at 8 mA | peaks 1k / 15k, dB of bias | knee 12.7 / 51 um | Bulletin 14 |
|---|---|---|---|---|---|---|---|
| **the data** | | -11.0 | -3.3 / -7.1 | -10.4 | 0 / 0 | ~4.1-4.5 | +4 |
| base (SCOTCH111@3) | 2.25 / 1.74 | -5.5 | -3.2 / -5.1 | -6.6 | -1.3 / -0.8 | 3.33 / 4.00 | -1.8 / -1.0 |
| exact gap | 1.49 / 1.37 | -7.2 | -1.6 / -2.9 | -11.4 | -0.3 / +0.2 | 3.42 / 3.92 | -1.8 / -0.9 |
| exact + astroid, kappa 1.5 | 1.20 / 2.63 | -7.6 | -1.1 / -8.9 | -17.2 | 0.0 / -2.7 | 3.96 / 5.77 | +1.5 / +0.2 |
| exact + astroid, kappa 0.5 | 1.13 / 1.62 | -7.9 | -1.4 / -7.2 | -13.2 | 0.0 / -1.6 | | |
| exact + astroid, kappa 1 / 3 / 5 | 1.18 / 2.15, 1.23 / 3.56, 1.30 / 4.09 | -7.7 / -7.4 / -7.2 | 15k: -8.2 / -10.0 / -10.3 | -15.4 / -20.2 / -21.8 | | | |
| exact + astroid, 3D isotropic | 1.46 / 1.44 | -6.6 | -1.4 / -6.7 | -10.7 | 0.0 / -1.6 | 3.30 / running | +0.2 / -1.1 |
| exact + astroid, 3D kappa 0.75 / 1.5 (lam 0) | 1.40 / 1.67, 1.38 / 1.93 | -6.8 / -6.8 | 15k: -7.0 / -7.4 | -11.8 / -12.9 | 0.0 / -1.6 | | |
| exact + astroid, 3D kappa 1.5 / 3 (lam 3) | 1.29 / 2.62, 1.28 / 3.02 | -7.0 / -7.1 | 15k: -8.3 / -8.7 | -16.0 / -17.5 | | | |
| exact + astroid kappa 1.5, no head image | 2.67 / 4.53 | -4.0 | -2.4 / -10.9 | -17.4 | -1.0 / -3.7 | | |

The exact gap's cost in the study's measure (one 1 kHz No. 21 recording): 8.7-9.0 s against
the base's 3.0-3.3 s (`overbias_cost_*.json`). The GPU kernel takes it through its field
tables, so a print pays for the tables, not per sample.

This review's reading:
- **The exact gap alone** is a correction of an approximation with no free parameter, and it
  moves nearly every No. 21 figure toward the data: both rms values, both peaks onto the
  data's, the 15k - 1k spread. It does not reach the rise (-7.2 of -11.0), its over-bias
  falls are smaller than the base's (-1.6 / -2.9 against -3.3 / -7.1), and it leaves Bulletin
  14 where it was. It is the one change here that looks ready for the user's decision (new
  head-field tables, the 351 family re-aligned, the reductions regenerated).
- **The astroid on top** fixes the 15 kHz fall only with nearly unoriented axes (kappa 0.5
  in the plane, or 3D isotropic), where the spread also lands (-10.7 to -13.2). More
  orientation overshoots it badly. Bulletin 14 moves the right way but stays 2.5-4 dB short.
  Its knee on the 351's 51 um gap is the open figure: 5.77 dB at kappa 1.5 is past #111's
  range, and the isotropic run didn't bracket 1% THD at first (`overbias_round2_l51.log`,
  `iso51_diag.log`: 1.8% THD already at 0.05 Hc). Not ready to adopt.
- Still missing in every variant: 3-4 dB of the 1 kHz rise at 3 mA.

## 2. Physics not yet tried

### 2.1 The coating's reversible magnetization [connected]

`varimu/devices/preisach.py`'s docstring (line 38): "The reversible (rotational) part of a
particle's magnetization isn't modelled: it vanishes with the field, so recorded remanence
doesn't depend on it (it would act through demagnetization)". The tape is therefore a medium
of permeability 1 that carries only its irreversible pattern, and only the audio band of that
pattern demagnetizes. The term never appears in the candidate lists for No. 21's misses.

Why it may matter where the model still misses:
- TAPE_HEAD_RESEARCH.md 1.4: at the recording point the bias field is 50-89 degrees from the
  tape's plane. TAPE_PARTICLES.md and the over-bias study both end at the same place: the
  over-bias fall and the treble's loss are decided by how the coating answers a nearly
  perpendicular field, and the coating's own perpendicular field is what doesn't converge
  with particles. Tjaden and Leyten measured M_y "substantially reduced" by demagnetization.
- A permeable coating changes exactly that field. Its reversible response is linear, so it
  needs no fixed point: for each wavenumber the head's potential, a slab of thickness delta
  with permeabilities (mu_x, mu_y) at the spacing, and air behind it is a closed-form
  three-region problem (inside the slab the decay constant is k sqrt(mu_x / mu_y)). The
  normal component of B is continuous, so the perpendicular field inside the coating drops
  roughly as 1 / mu_y at long wavelengths while the longitudinal one doesn't: the field's
  angle at the freezing point turns toward the plane, and the deeper layers are screened by
  the ones above (a wider sweep of bias through the depth: the direction the rise needs).
- The same transfer functions change the audio-band demagnetization kernels and, by
  reciprocity, the playback spectrum (the thickness and spacing losses at long wavelengths).

How it would enter, and its cost: the record head's field tables per layer (built from the
spectrum times the slab's transfer; the exact gap's field goes through the same step), the
demagnetization kernels (`demag_kernels`), the playback spectrum (`hx_spectrum`). All three
are tables or kernels built once, so **no cost per sample**, on the CPU, the GPU or the
reduced live tier (whose tables would be regenerated).

What has to be sourced before anything is built:
- mu_x and mu_y for an oxide coating of the period. `provisional: model knowledge (about 2,
  perhaps 1.5-3, anisotropic for oriented tape; unverified)`. Bertram 1994 treats
  reproduction from a permeable medium [memory, not checked]. Sound Talk No. 22's loops give
  the slope at remanence, but TAPE_PARTICLES.md notes they carry no type labels.
- The Bulletin 20 fit is a remanence curve and doesn't move; the loop's coercivity check
  (Eilers' 270 Oe) moves slightly with a reversible slope.

The checks: No. 21's full row (with the exact gap, with and without the astroid), Bulletin 14,
the knee at both gaps, and Sound Talk No. 31's coating-thickness trends (described in
TAPE_PLAN.md "Gaps" 2, no baseline numbers recorded there: the natural out-of-sample check
for a term that changes thickness loss). Risk: it may move the rise by less than the 3-4 dB
missing; it is proposed because it is first-order physics both overnight studies point at
and it is cheap, not because the size is known.

### 2.2 The noise of a biased tape [connected]

The figures, all in TAPE_PLAN.md:
- the tape alone, recorded silent with bias: S/N 72.9 dB at 15 ips (TM3), against R-e/p
  1974's 66 dB for #111 (its reference conditions aren't stated in the plan);
- Bulletin 34 Fig. 4: a normal machine's erase and bias put the noise ~10 dB over bulk-erased
  tape; Fig. 2: DC at the 3% level is ~15 dB over the erased noise (the fitted packing field);
- the 351's S/N study ("Gaps" 4): the reproduce side's tube hiss and flicker dominate, "the
  grain, the record amplifier, the bias section and the supply are each 15+ dB under it".

So the machine meets its 60 dB spec (61.0), but what one hears as hiss is the reproduce
tubes; the tape's own noise is far under it, and nothing in the nominal machine excites the
modulation-noise mechanism the model already has. Two reasons, both properties of the nominal
unit rather than of the physics:
- the oscillator is perfectly balanced (nominal units only, matched 12AU7 halves; the
  alignment leaves NOISE BALANCE centred), so the bias has no DC or even-harmonic part to
  record against the packing field. The bias study measured the control's reach: -1.05 to
  +1.05 dB of +/- asymmetry over its rotation;
- erasure is complete (no erase head field), so nothing is left under the bias either.

A cheap check before any model work (a few noise renders on the existing machine): the
profile's noise measurement with NOISE BALANCE at 1/4 and at 0 rotation, and with the
oscillator's two triodes mismatched within tube tolerance, its spectrum against Bulletin 34's
Fig. 4. If a realistic asymmetry brings the biased-tape noise up toward the published ~10 dB,
the "tape hiss" is a matter of a per-unit draw and a condition dial (an unbalanced oscillator,
magnetized heads), not a new model. Caveat: this review doesn't know how a real 351's noise
splits between tape and tubes; the published figures above are the only evidence.

### 2.3 Print-through [docs]

TAPE_PARTICLE_RESEARCH.md (3.4, verdict) and the over-bias study (item 6, recommendation)
both conclude the same: clearly audible (pre- and post-echo at -40 to -55 dB), the period
data give its laws (time, temperature, wavelength, level), it needs no new physics risk and
costs nothing per sample (a filter on the recorded tape per storage condition). It is the
cheapest audible addition on the list and it is not built.

### 2.4 Azimuth and dynamic skew [docs for the gap, new for the proposal's priority]

"Known approximations" lists "no azimuth"; the condition dials list azimuth error under
"trash". As built, a stereo print's two channels (the 351-2, a dual-mono print) and the
deck's four share one speed trajectory and differ only in grain. On a real machine the tape
also weaves across the heads, so the tracks slide in time against each other and each track's
treble breathes. It is what tape does to a stereo image, and it is cheap:
- within a track of width w at a skew angle theta, the readout is the pattern averaged over
  w tan(theta) along the tape: a factor sinc(pi w tan(theta) / lambda), a short box filter in
  the readout [derived];
- between tracks whose centres are D apart, a time shift D tan(theta) / v [derived].

Illustrations of the size (the angles are examples, not data: `provisional`, to be sourced
from guiding and slitting tolerances): the full track's 5.94 mm at 15 kHz and 15 ips
(lambda 25.4 um) loses 0.07 dB at 1 arc minute and 1.7 dB at 5; at 7-1/2 ips, 5 minutes cost
8 dB. Tracks ~4 mm apart shift ~3 us per arc minute at 15 ips (11 degrees at 10 kHz).
theta(t) would be a transport quantity like the speed: a slow wander from the tape's edge
and the guides, seeded, with a realistic default and a condition dial.

### 2.5 Head contact [docs for the gap]

The spacing is one constant (0.5 um). TAPE_PLAN.md's condition dials name head wear and
dropouts; Sound Talk No. 34 notes the noise at the top rose when a smoother base improved
contact. A spacing that varies along the tape (surface roughness with a correlation length,
dust as rare large excursions; seeded) acts twice: on playback as a slowly varying spacing
loss (treble amplitude modulation, dropouts), and in the record zone, where it moves the
depth the bias reaches (level modulation at every frequency). Playback is a time-varying
filter in the readout; recording needs the field tables at two or three spacings and an
interpolation per cell. After 2.2-2.4 in audible payoff.

### 2.6 A second tape [docs]

SM911 with EMTEC's stated gaps (TM2's second part, "Gaps" 5) is still the only planned test
of the physics on data it was never fitted to, and it is the hotter stock a mix bus may want.
Not started.

### 2.7 Smaller notes

- The repro head's gap is Karlqvist's too: its null sits at the gap length where the exact
  head's is at 1.135 g (TAPE_HEAD_RESEARCH.md 1.5). Negligible at 15 ips with a 6.35 um gap,
  a few tenths of a dB at the top of the band at 7-1/2 ips. [docs]
- The transport's mechanisms are sized as a set to the 351's 0.11% (nothing printed
  separates them). A tape path from its mechanics (the tape's elasticity between guides,
  reel inertias, friction at the heads) would give the flutter's spectrum from parts. Low
  priority: the total is already the spec's. [docs]

## 3. Speed

### 3.1 Where a print's time goes now

TAPE_SPEED_PLAN.md's last table for one print (0.5 s of drums plus the 1 s settle, the GPU
kernel, TR-BDF2 with tables in the record side, 0.5 um cells): 27x real time, 47 s of wall;
the record side busy 42 s, the tape's recording worker 30.7 s, "one block's recording (up to
9 kernel calls: the demag fixed point) costs ~0.8 s of worker time, mostly the CPU's FFTs and
transfers".

Since then the 351 family and the deck went to 0.25 um cells, which doubles the worker's
cells. [estimate]: per 16 mm block the record side takes about 1.2 s of wall (42 s over ~36
blocks) and the worker now about 1.6-1.7 s (0.85 s doubled), so **the worker probably bounds
a single print again**; TAPE_PLAN.md's "95 s vs 53 s per probe" between 0.125 and 0.25 um
cells scales the same way. In pieces the limit is the machine's total CPU (six pieces fill
it), and there the worker would be roughly 40% of the work. Not measured: the first step is
`CIRCUITSIM_PART_TIMING=1` with `scripts/speed_351.py ... gpu` on the current circuit.

### 3.2 The tape worker: what surrounds the kernel

All from reading `tape_stream.rs`'s `Recorder` and `crates/tapegpu/src/lib.rs`; the split of
the worker's time between these items is not measured.

1. **The transforms** (`demag_fields`, tape_stream.rs:934). [new]
   - Each demag iteration runs 2 x 6 forward and 2 images x 2 x 6 inverse transforms: 36,
     so up to 288 per block. Each is a full complex f64 FFT (`rfft` / `irfft` build the whole
     complex array) of n = next_fast_len(2 x cells), about 136,000 points for a block's
     68,000 cells at 0.25 um, on the worker's one thread.
   - Only the bins with wavelengths over `lam_min_m` (three bias wavelengths, 11.4 um at 15
     ips) are kept: j < n ds / lam_min, about n / 46. The fields that come back are
     oversampled ~23 times.
   - Exact options: real-to-complex transforms (half the work), the twelve layers'
     transforms in parallel, the forward transforms' kept bins only multiplied.
   - A larger option with a small, controlled error: the demagnetizing field computed on a
     grid decimated ~8 times (an anti-alias decimator in, a short interpolator out; -100 dB
     is reachable at that oversampling) cuts the transform work about tenfold. The Python
     reference would take the same change so the two still agree.
2. **The transfers** (`tapegpu::record`, lib.rs:254; `record_gpu`, tape.rs:830). [new]
   - Every one of the up to nine passes of a block creates ten buffers and a bind group,
     uploads all of them, and reads back layers x axes x cells floats (13 MB at 0.25 um) to
     sum the eight axes on the CPU.
   - Between the passes of one block only the steady fields change. The cells, the peaks,
     the zones' ranges, the field tables and the axes are the same; circuitsim also rebuilds
     the field tables and the per-cell peak ranges (a binary search per layer and cell) each
     pass.
   - Keep the block's buffers across its passes, upload only `steady`, and sum the axes in
     the shader (an f32 sum of eight terms: its rounding is in the class of the kernel's
     -117 dB, to be held to P5's -80 dB bound).
   - Minor: one invocation per (cell, axis, layer) repeats the head field's interpolation
     for each of the eight axes; P5's design noted the per-cell alternative.
3. **The fixed point** (`Recorder::record`). [new]
   - Eight Anderson iterations end -58.5 dB from converged (TAPE_PLAN.md "Speed") at nine
     kernel passes per block.
   - The recording is local: a cell's (M_x, M_y) depends on its own two steady-field vectors
     (through the pass, after it), and the demagnetizing fields are linear in the pattern.
     The kernel can return each axis's derivative with respect to those two projected fields
     in the same backward pass (the bicubic's derivative weights on the same sixteen taps).
     That is the whole Jacobian of the map, block-diagonal in space, so Newton's linear
     solves (GMRES on I - J K) cost transforms only, no kernel pass.
   - [estimate] about three kernel passes instead of nine, and a tighter result than -58 dB.
     Risks: the map is only piecewise smooth (the set of record extrema changes with the
     field), so it needs damping and Anderson as the fallback; the two implementations would
     agree to a tolerance rather than step for step.
4. **The whole fixed point on the GPU.** [new] With 1-3 done, the transforms are the last
   thing on the CPU. Moving them (f32, power-of-two lengths) leaves nothing to cross the bus
   until the block's final pattern, and uses a GPU that is mostly idle during a print today.
   The f64 CPU path stays the reference.

### 3.3 The record side

Its steps are sequential at 3.84 MHz; TAPE_SPEED_PLAN.md has spent the per-step levers
(TR-BDF2, tables, no error control). What is left is how much circuit sits in the fast part.

1. **The deck: an island per channel.** [new] The Ampex 300-4's record island is the master
   oscillator and four record amplifiers on one thread: 122x real time against the 351's
   27x, and the song's print took 2 h 58 min. The channels meet the oscillator only at the
   bias feeds (each BIAS ADJUST ~46.6 pF) and each other at the coupled record heads.
   Per-channel islands on their own threads, linked to the oscillator every substep, could
   bring the deck's bound toward one channel's ([estimate] up to 3-4x on that part), which
   would also pay for the chirp fix (40 substeps or esdirk4 there, each ~2x: the user's
   pending call). The pieces exist separately: the tape's remote sense already publishes per
   substep, named multi-rate groups give an island a thread (the Minimoog), and W1's
   transmission-line cuts are the stable way to cut. Unproven: a link at the substep rate
   (a hand-off every 260 ns against ~7 us of work per substep), the heads' coupling across
   islands, stability.
2. **The 351: the first two record stages at the audio rate.** [connected] The cut at 1V2b's
   plate diverged in 52 samples (TAPE_PLAN.md, Option A) and was not pursued. W1's line cuts
   were built after that and haven't been tried there. Two of the island's five triodes
   would leave it: [estimate] 1.2-1.4x on the record side if a line cut holds.
3. **Know where the island's step goes.** `--features timing` with `examples/profile.rs` on
   the island alone (Newton iterations and factorizations per step) before either of the
   above.

### 3.4 The cost of iterating on the model

Every physics change in section 2 is followed by an alignment (~55 min, on the CPU kernel)
and, for the live tier, the reductions (~3 h per machine). Both are sets of independent runs.
If several model changes are coming, running the alignment's sweeps on the GPU kernel (its
results held to the CPU's within the alignment's own resolution) and the reduction's points
at once is what shortens each round. [connected]

## 4. What is new here and what isn't

The user asked whether this review surfaced things the earlier sessions hadn't. By the tags:
- **Reported, not found:** the exact gap and astroid results, print-through, SM911, azimuth
  and dropouts as gaps.
- **Connected:** the reversible magnetization as a candidate for the over-bias misses; the
  balanced oscillator and complete erasure as the reason the tape's noise is far under the
  tubes'; the alignment and reductions as the cost of iterating; W1's cuts for the 351's
  record amplifier.
- **New:** the transforms' count and kept bins, the per-pass buffers and readbacks, Newton
  on the fixed point, the worker as the probable bound since the cells' change, per-channel
  islands for the deck.

Two cautions. It is not a like-for-like comparison: the earlier sessions were building one
feature at a time, and this was a review of the whole with every plan open. And none of the
new items is tested: the estimates above could be wrong, and 2.1 could do little for No. 21.

One correction to what was said in the conversation before this file: the kept bins are
about 1 / 46 of the transform's length (lam_min is three bias wavelengths, 11.4 um), not
1 / 60.

## 5. A suggested order

1. Measure: `CIRCUITSIM_PART_TIMING=1` on the current 0.25 um machine (is the worker the
   bound?), and the split inside the worker. An hour.
2. The second round written into TAPE_PLAN.md by the session running it; then the user's
   call on the exact gap.
3. The exact worker fixes (3.2 items 1's exact options and 2), measured against 1.
4. The noise check (2.2: a few renders), then print-through (2.3) and skew (2.4).
5. The permeability study (2.1): source mu first, then an opt-in variant measured on the
   over-bias study's checks, as that study did.
6. For the deck: the island's profile, then per-channel islands (3.3), before its reprint.
7. Later: Newton on the fixed point and the fixed point on the GPU (3.2 items 3-4), head
   contact (2.5), SM911 (2.6).

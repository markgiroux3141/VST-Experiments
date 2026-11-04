# The synth's real-time load

Drafted 2026-11-04 (the user's ask: the gas-tube saw sounds right, but live it drops out even
alone; optimize without making it sound worse). Nothing built. **Run it when nothing else
uses the CPU** (no other Claude sessions, no renders, no prints, rust-analyzer idle).

## The problem

From HYBRID_PHYSICS_PLAN.md H4, "CPU (measured 2026-11-03)", tube_synth in the app at a 30 ms
buffer, a held C7:

| configuration | load | worst block | dropouts |
|---|---|---|---|
| LC only (as before the saw) | 71-74% | 92% | 0 |
| saw only (SAW ON, OSC OFF) | 77-100% | 104-142% | a few per 15 s |
| LC + saw | 81-110% | | ~100 per 12 s at C7 |
| `saw_884` alone (its own device) | 28-51% | 79% | 0 |

The saw alone costs less than the LC alone in Python (0.96x against 1.25x real time, one run),
yet the app's load is higher and its worst blocks pass 100% while the average doesn't. A
spread like that looks like **scheduling** (a thread losing its core) more than **compute**.
This plan measures which, then fixes that one.

What the code does today:

- **Lockstep per sample.** Every partition waits for *every* other one at every sample, not
  only the ones it reads (`circuitsim/src/stream.rs`, `Shared::feeds`; rings of 3 samples).
  The voice runs at the slowest thread's pace sample by sample, and one thread preempted
  for a millisecond stalls all of them.
- **Threads.** With SAW ON, OSC OFF, RING OFF and the LFO on, tube_synth runs about seven
  solver threads (`panel.rs`, tube_synth's `partition`: the VCA with the keys | resonance |
  input, filter, cutoff | envelope | saw pitch, saw | lfo | the supplies), plus the player's
  worker, the audio callback and the UI. Each spins between samples (`Shared::wait`).
- **Priority.** The process is at HIGH_PRIORITY_CLASS (`player::raise_priority`); the
  threads are at normal relative priority, not in MMCSS, and not pinned.
- **The CPU.** i9-9900K: 8 cores, 16 logical processors (hyper-threading). The power plan is
  already High performance. Windows may put two spinning partitions on one core's two
  siblings, where each runs at roughly 60% speed.

## The rule: the sound doesn't change

Every step falls in one of two classes, and says which:

- **Bit-identical.** The output is the same bit for bit (scheduling, pinning, priorities,
  ring depth). Checked by the bit-identity check below.
- **Within tolerance.** The output moves only within the solver's tolerance, and toward the
  one-solve reference, not away. The bar is what the partition has today: within 0.1 cent
  and 0.01 dB of the one solve (`panel.rs`'s tube_synth comment), the saw's tuning table
  (`SYNTH_SAW_TUNING`) unchanged within 0.1 cent.

Out of scope, since each changes the sound: a lower internal rate, looser Newton
tolerances, linear cores, dropping parts, a different event-kernel resolution.

## Before each session

1. Nothing else running: close other Claude sessions, stop `varimu listen` and any renders
   or prints, check Task Manager for `rustc` or `ngspice` (rust-analyzer recompiles for ~2
   minutes after a Rust edit: wait it out).
2. Build first, then measure (`cargo build --release -p varimu-app --examples`), so the
   build doesn't run during the measurement.
3. This desktop drifts +-35% between runs (CLAUDE.md, "Benchmarking on this desktop"): run
   every measurement three times, report the best and the worst, and compare before and
   after back to back in the same session, never against old numbers.

## Step 0: the baseline

The configurations, each 60 s with a key held, at the 30 ms buffer:

```sh
# the saw alone (the case to fix)
cargo run --release -p varimu-app --example play -- --device tube_synth --set saw_on=1 --set osc_on=0 --hold 96 --for 60 --buffer 0.03
# the same at A0 (21), A3 (57), C8 (108)
# the LC alone (the control) and both (the stretch)
cargo run --release -p varimu-app --example play -- --device tube_synth --hold 96 --for 60 --buffer 0.03
cargo run --release -p varimu-app --example play -- --device tube_synth --set saw_on=1 --hold 96 --for 60 --buffer 0.03
```

Keep each summary line (dropouts, worst block load) in a table in this file's Status.

## Step 1: measure where the time goes (scheduling or compute)

Add per-partition timing to `Stream`'s threads behind circuitsim's existing `timing`
feature (off by default, so default builds are unchanged). Per partition, per audio block:

- **busy**: time stepping (from reading its feeds to publishing);
- **waiting**: time in `Shared::wait`, and the longest single wait;
- **stalls**: waits over 200 us (a sample is 10.4 us at the draft-2x's 96 kHz: a 200 us wait
  is another thread that lost its core, not a slower step);
- the OS's view, once per block: the thread's CPU time against wall time
  (`GetThreadTimes`) and, if needed, its context switches.

Report it from `examples/play.rs` (`--features timing`): per partition, mean and worst busy
per block as a share of the block, and the stall count.

How to read it:

- **Scheduling.** The worst blocks line up with stalls; every partition's busy time stays
  well under the block. Do A first.
- **Compute.** One partition's busy time reaches the block on its own (most likely the saw's
  thread, or the filter and VCA threads at every strike). Do B first.
- Both are possible. Do whichever explains more of the worst blocks first.

## A. Scheduling (bit-identical)

Each change is measured alone against the baseline, back to back, before the next goes in.

- **A1. One physical core per partition.** Pin each solver thread to its own physical core
  (`SetThreadAffinityMask`, or `SetThreadIdealProcessor` as a softer first try), one
  logical processor per core so no two spinners share a core's siblings. Read the
  sibling map from `GetLogicalProcessorInformationEx` (don't assume 2k and 2k+1). Leave
  core 0 for the audio callback, the worker and the UI. With seven partitions on eight
  cores this just fits; a configuration that needs more partitions than cores falls back
  to no pinning.
- **A2. MMCSS "Pro Audio".** Register the solver threads, the worker and the audio callback
  with `AvSetMmThreadCharacteristicsW("Pro Audio")` (avrt.dll), which DAWs use so their
  audio threads aren't preempted. The process is already HIGH, so expect less from this
  than A1; measure it alone.
- **A3. Wait only on the parts that are read.** `Shared::feeds` waits for every part so a
  3-sample ring is never overwritten while read. With a deeper ring (say 64 samples) and a
  wait only on the parts whose values it reads (plus a bound on how far any part may run
  ahead), parts that aren't neighbours (the LFO and the VCA, say) can drift apart and
  absorb each other's jitter. Directly coupled parts stay one sample apart: this gives
  slack, not parallelism. Bit-identical by construction: each part reads the same values
  at the same sample.
- **A4. Spinning.** After 2^14 spins a waiter yields (`Shared::wait`). Measure whether
  yielding sooner, or never yielding while the stream plays, changes the stalls. Only with
  A1 in place: an unpinned spinner that never yields can starve the callback.
- **A5. The UI while playing.** In the app (not `play.rs`, which has no window): cap egui's
  repaint while a device plays (the meters at ~30 fps) and measure the app's own load meter
  before and after.

## B. Compute (within tolerance)

- **B1. Newton's first guess from the previous period.** The saw repeats every period. On
  the samples just after a strike, start Newton from the solution one period earlier at
  the same phase (shifted by the drift since then) instead of from the previous sample.
  Those are the samples with the most iterations, in the saw's thread and in the filter and
  VCA threads. Newton still converges to the same tolerance; the gain is fewer iterations.
  It also applies to the LC oscillator and the kick. Measure the iterations per strike
  (`DkNewton`'s counters) before and after.
- **B2. Merge light partitions.** Fewer threads means less lockstep and fewer chances of a
  stall. Candidates: the LFO with the supplies, or the envelope with the VCA's part.
  Merging removes a one-sample coupling, so the output moves toward the one solve. Check
  it against the bar above. Try with `load_profile`'s `--partition` before changing
  `panel.rs`.
- **B3. Rebalance.** If Step 1 shows one heavy part, move sections between parts (as the
  supplies' placement was measured in H4: "within 5%" there). The same bar.

## C. The fallback: latency

The average already fits; only the spikes don't. A larger buffer (`--buffer 0.05`) absorbs
them without touching the sound; the cost is key-to-ear latency (+20 ms). Use it only if A
and B don't get there, and say so to the user: it's their trade.

## The bit-identity check

Every A step must leave the output byte-equal. Write a check that runs tube_synth's
partitioned `Stream` offline (no audio device): saw only, a held C7 for 3 s with the gate and
`pitch2` as `--hold` sets them, the device's partition and coupling, at draft-2x. It writes the
`out` probe's sha256. Run it before the change and after, and once more with other load on
the machine (the result must not depend on timing). B steps instead compare with the
one-solve run of the same input (the same check without the partition) against the bar.

## Done when

The saw alone (SAW ON, OSC OFF) held at A0, A3, C7 and C8 for 60 s each, three runs each, at
the 30 ms buffer: **0 dropouts and worst block under 90%**, with the bit-identity check (A)
or the tolerance bar (B) passing. Stretch, not required: both oscillators at C7 without
dropouts.

## Status

Not started.

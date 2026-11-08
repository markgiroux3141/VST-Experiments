# The Suitcase's real-time load

Written 2026-11-08 (the user's ask: the live Rhodes Suitcase, `rhodes_suitcase`, sounds right;
find what would cut its dropouts **without changing the sound**). Nothing built. Ideas only,
ranked; each is measured alone before the next goes in.

**Where it stands:** the user found that a 50 ms buffer instead of 30 ms clears most of the
dropouts in normal playing (2026-11-08). The cost is ~20 ms more from key to ear. So this plan
is for when a smaller buffer is wanted back, or the remaining dropouts matter.

[SYNTH_REALTIME_PLAN.md](SYNTH_REALTIME_PLAN.md) (2026-11-04, tube_synth, also not started)
has the same problem in general form and the method this plan reuses: its rule (each change
is **bit-identical** or **within tolerance, toward the one solve**), "Before each session"
(an idle machine, build first, three runs, back to back), Step 1's per-partition timing and
its bit-identity check. Its levers A1-A5 apply here too; this file lists them by reference
and adds what is specific to the Suitcase.

## What the code does today

- **Five partition threads in lockstep every sample** (`panel.rs`, `rhodes_suitcase`'s
  `partition`: the preamp with the harp | the speakers | output amp A with power amp A |
  output amp B with power amp B | the mains supply). Each waits for *every* other part at
  every sample (`circuitsim/src/stream.rs`, `Shared::feeds`), spinning between samples. The
  first partition runs on the player's worker thread.
- **The harp renders inline in partition 0** (`circuitsim/src/keyed.rs`, `Medium::render`):
  every `CHUNK` = 256 samples it renders the next chunk on that thread, waking its three
  "keys" workers when more than `INLINE_VOICES` = 4 voices are awake. For the whole chunk
  partition 0 stops, and the other four partitions spin waiting for it: four cores burned
  spinning while the harp needs four of its own, on an 8-core i9-9900K.
- **Priority:** the process is at HIGH_PRIORITY_CLASS (`player::raise_priority`); every
  thread (partitions, keys workers, the worker) is at normal relative priority, not pinned.
- **The wait's fallback** (`Shared::wait`): spin 2^14 times, then yield for 2 ms, then
  `sleep(100 us)` in a loop.
- **The release profile** is Cargo's default (no LTO, 16 codegen units).
- **The evidence it's scheduling, not compute** (RHODES_PLAN.md, "Every key struck and
  re-struck", measured 2026-11-07): each partition is busy 1.2-6.3 us of a 10.4 us sample;
  the maxima of 0.1-2.7 ms are the OS descheduling a spinning thread.

## Ideas, ranked

1. **The harp on its own thread, rendering ahead** (bit-identical). The harp senses nothing
   in the circuit (the module docs: "One way"), so a producer thread can fill a ring ahead of
   the circuit up to the last known event (`Medium::known_until`), and partition 0 only reads
   its next sample. The chunk stall leaves the lockstep chain and the harp's work overlaps
   the circuit's. The voices stay summed in the same order, so bit for bit the same. Biggest
   structural win; it targets the burst at re-strikes. Same machinery serves the Clavinet
   (`clavinet.rs` on `keyed.rs`) and the Stage (`harp.rs`).
2. **Thread priority above normal** (bit-identical). `THREAD_PRIORITY_TIME_CRITICAL` (level
   15 inside the HIGH class) on the partition threads and the worker, so they win against
   nearly everything else on the desktop; the keys workers one step lower once idea 1 gives
   them slack. **Caveat on MMCSS** (SYNTH_REALTIME_PLAN.md A2): "Pro Audio" throttles a thread
   that looks 100% busy for part of each period (SystemResponsiveness, 20% by default), and a
   spinning thread always looks 100% busy. Measure it before trusting it for the spinners;
   it fits the audio callback.
3. **One physical core per spinning thread** (bit-identical; SYNTH_REALTIME_PLAN.md A1). Two
   spinners on one core's hyper-threaded siblings each run at ~60%. Pin the five partitions
   to five physical cores (one logical processor each, siblings from
   `GetLogicalProcessorInformationEx`), the keys workers on the rest, one core left for the UI,
   the callback and the OS. `SetThreadSelectedCpuSets` is the soft form, an affinity mask the
   hard one.
4. **The wait's fallback** (bit-identical). After 2 ms of waiting a thread sleeps 100 us at a
   time; depending on Rust's `sleep` and Windows' timer resolution that can be ~1-15 ms, turning
   one stall into a dropout. Either `timeBeginPeriod(1)` while a stream plays, or replace the
   sleep with `WaitOnAddress` on the ring's counter (woken the moment it's published). Check
   first: count waits that reach the sleep at all (Step 1's timing).
5. **Wait only on the parts read** (bit-identical; SYNTH_REALTIME_PLAN.md A3). A deeper ring
   and a wait on the neighbours only: the mains supply and the speakers can run a little ahead
   and absorb each other's jitter. Directly coupled parts stay one sample apart.
6. **Compiler settings** (bit-identical). A release profile with `lto = "fat"`,
   `codegen-units = 1`, and profile-guided optimization (`cargo-pgo`, trained on `play.rs
   --mute`). **Not** `target-cpu=native`: it lets LLVM use fused multiply-adds, which change
   rounding (inaudible, ~-300 dB, but it breaks the bit-for-bit agreement with Python).
7. **The machine** (no code). Core parking off (the power plan is already High performance),
   rust-analyzer and pytest closed while playing: the runs varied 5x with what else ran
   (RHODES_PLAN.md).

## Out of scope (each changes the sound)

- A block of lag on the rails or the speakers' cut (RHODES_PLAN.md's option (c), TAPE_SPEED_PLAN.md
  P2's idea): only slow sag crosses there, but it moves the sound.
- A looser Newton tolerance, or tighter `tol_scale` on the shared diode model `DSI` (moved the
  sound -16 dB, most likely the pan's phase: RHODES_PLAN.md "A channel latched").
- Tried and worse (RHODES_PLAN.md, 2026-11-07): the speakers in the first partition (223%),
  the supply folded into amp B's part (129%), each channel's speakers on its amp's thread.

## Measuring

```sh
# the stress case, no sound in the room
cargo run --release -p varimu-app --example play -- --device rhodes_suitcase --strike-all 127 --restrike 3 --mute --for 30 --buffer 0.03
# normal playing's buffers: 0.03 and 0.05
# the live device offline, deterministic, both channels and the amps' nodes (for bit-identity)
cargo run --release -p varimu-app --example suitcase_latch -- --scenario chords --seconds 10 --velocity 80 --dump DIR
```

A bit-identical change leaves `suitcase_latch --dump`'s `out.f32` / `out_r.f32` byte-equal.

## Done when

The stress case at a 30 ms buffer, three runs on an idle machine: 0 dropouts in 30 s, worst
block under 100%, every change bit-identical. Softer goal: normal playing clean at 30 ms.

## Status

Not started. 50 ms buffer in use (the user's, 2026-11-08).

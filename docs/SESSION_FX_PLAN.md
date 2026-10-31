# Devices in the session: inserts, sends and printing

Drafted 2026-10-30 at the user's request: apply reverb to what's recorded in the Session
view, and move the compressor, the EQ and the other processors from the Play view into
the Session view, where they're used. It is a track of the native app
([NATIVE_APP_PLAN.md](NATIVE_APP_PLAN.md)) on top of recording
([RECORDING_PLAN.md](RECORDING_PLAN.md): it takes over T5's "a track's device feeding
another device"), and it is where the reverb track ([REVERB_PLAN.md](REVERB_PLAN.md))
gets used. Native only; nothing goes into the web app. Work the milestones in order, each
ending with its "done when" met and covered by tests.

**Status (2026-10-30): F1 done; F2 and F3 built** (F2 tried once by the user, F3 after
their feedback; each milestone's status below it). The reverb for F4 is REVERB_PLAN.md's plate (decision 1).

## The idea: print, don't play

A device can't play live on every track. The 670 alone takes ~85% of the machine at
draft-1x and tube_synth ~62% at draft-2x, so one live device at a time is all there is
(RECORDING_PLAN.md already plays every track but the armed one as audio). Processing in
the session works the same way:

- **A track's processors are printed.** Each insert's output is rendered offline, in the
  background, and kept as audio, as a studio prints a track through an outboard box onto
  another track. Playback plays the prints, so a session with a 670 on every track costs
  what a session of plain audio costs.
- **One device runs live: the one being adjusted** (F3). Opening an insert's panel plays
  that device live on its input at the playhead while the knobs turn; the rest of the
  session plays prints. Closing it (or a pause in the knob moves) prints it again.
- **Prints are reproducible and cached** by what they're made from: the input audio, the
  device's IR (circuit, pinned component versions, panel values), the quality, the gains
  and the code version. A change re-prints only what is downstream of it. Prints can
  always be made again (unlike takes), so they can be cleaned up.
- **Draft while iterating, production on demand**, as RECORDING_PLAN.md's T4 decided for
  takes: prints use the device's play quality (draft-1x for the 670 and the EQP-1A), and
  Render session renders the chains at production after the takes.

**Physical honesty.** Each box stays one coupled simulation; a chain is boxes connected by
cables, printed in turn (REVERB_PLAN.md decision 2). Faders, pans, sends and bus sums are
console arithmetic, as the mix already is. A trim ahead of a box is a fader, as the Play
view's input normalization is.

## What exists (2026-10-30)

- **The Session view** (`session_view.rs`, `session.rs`): tracks of takes (lanes, one
  active take per track), faders, balance, mute, solo, arm, record and loop record, undo,
  `session.json` and `takes/<id>/` in a folder of the user's. The armed track's device
  plays live; the others play their active take's draft audio (`Mix`).
- **The Play view** (`play_view.rs`): one device on a file or live input, its front panel
  (`panel::Knob`), input normalization (the file's loudest stretch to -18 dBFS) and trim,
  bypass and gain compensation (`monitor`), Record, Render (production).
- **`render`**: a device on audio offline at a quality's settings, bit for bit with
  Python's render, progress and cancel.
- **Speeds** (NATIVE_APP_PLAN.md, R2): the 670 at draft-1x ~0.7-0.9x real time on two
  cores (HF-rich blocks 3-4x); the EQP-1A ~25-30%; production 14-18x slower than real
  time for the 670. So printing a 3-minute track through the 670 takes ~3 minutes at
  draft and ~45-55 minutes at production (one core per job, jobs in parallel).

## Design

### Signal flow

```
take lane ──► trim ─► [insert 1] ─► [insert 2] ─► ... ─► fader / balance ─► mix
                                                    └─► send (pre or post fader) ─┐
                                                                                  │
 FX track:  Σ sends ─► [insert: the reverb] ─► return fader / balance ─► mix  ◄───┘
```

- **A track's signal** is its active take(s) on the timeline, silence between: the box
  sees the tape from where the track starts. A print covers the track's extent plus the
  device's tail and is one continuous run (a compressor's state crosses from take to
  take; a reverb's tail runs past the last one).
- **An insert slot**: the device and its pinned versions, the panel values, a trim in
  front (dB), a make-up gain after it (dB), bypass, and the quality it prints at. The
  trim starts at the Play view's normalization (the input's loudest stretch to -18 dBFS),
  computed once when the insert is added and then fixed, so a louder take upstream drives
  the box harder, as with real gear. The make-up starts at the monitor's loudness match.
- **Sends** (F4): a level per track per FX track, pre or post fader, mono (devices are
  mono). The FX track's input is the sum; its inserts print like a track's; its return
  has a fader and balance. A reverb as a send prints wet only (its own mix control fully
  wet); as an insert it uses its own mix.
- **No master-bus device yet.** The 670 on the stereo bus needs a two-channel device
  (RECORDING_PLAN.md T5's open question). Two unlinked mono 670s aren't a 670.

### Printing (F1)

- **A print job**: input audio at the session's rate, a device, its values, its quality,
  trim, make-up, tail. The input in front of the device is the trim times the audio; to
  the quality's rate; `render::render` (the settle, the oversampling, the partition, as
  any render); back to the session's rate; the make-up; float32.
- **The key** is a sha256 over everything that changes the output: the input samples, the
  session rate, the device's IR as built for the values (so circuit and component
  versions and every value are in it), the quality's settings, trim, make-up, tail, and
  circuitsim's `SOURCE_HASH`. A chain's keys chain: insert k's input is insert k-1's
  print.
- **On disk**: `prints/<key>/print.wav` (mono float32 at the session's rate) and
  `print.json` (what it was made from, wall time, real-time factor) in the session
  folder. A key found on disk is never rendered again.
- **Jobs** run on background threads with progress and cancel. A newer edit of the same
  slot cancels the older job. Playback never waits: a slot whose print is stale plays its
  last print (shown as stale), or the input if it has none.
- **Live and print.** A print starts at a defined state (the render's settle, input held),
  so it is reproducible; a live audition starts settled at the playhead and so differs
  from the print until the device's memory runs out (the 670's release: up to 25 s at
  TC6). F3 measures it.

### The view (F2-F4)

```
│ 1 Bass  tube_synth  ● M S ━━●━ ◐ │ ▁▃▅▃▁▁▃▅▃▁   ▁▃▅▃▁▁▃▅▃▁                   │
│   [EQP-1A ✓] [670 ◔ 40%] [+]   → Plate ━●━ post                                  │
│ 2 Lead  tube_synth  ● M S ━●━━ ◑ │      ▂▅▇▅▂     ▂▅▇▅▂▂▅▇▅▂                  │
│   [670 stale] [+]              → Plate ━━●━ post                                 │
│ FX Plate                ━━●━ ◐  │ (the return's print)                          │
│   [Plate ✓] [+]                                                                  │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 2 Lead · 670   trim -4.2 dB  make-up +3.0  ⏻ bypass  ▶ audition  ⎙ print  draft │
│ (the 670's front panel: the Play view's knobs)                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

- Insert chips under each track's strip: the device, its print state (printed, stale,
  rendering n%, failed), a click selects it, a drag reorders, right-click removes.
- The bottom panel is the selected insert's front panel: the Play view's knob widget,
  moved to a module both views use.
- The Play view stays for playing one device standalone (designing a sound, live input,
  testing a circuit).

## Milestones

**F1. Printing** (library only, no view). `varimu-app`'s `print` module: print jobs, keys,
the cache in a session folder, chains, background jobs with progress and cancel.
*Done when:*
- a print equals `render::render` of the same input at the same rate, bit for bit, and
  a cached print reads back bit for bit;
- a key changes when any input to the print changes (audio, a value, a version, the
  quality, a gain) and not otherwise;
- in a chain, a change to insert k re-prints k and what follows, and nothing before;
- a cancelled job leaves nothing in the cache;
- the cost is measured: a 30 s take through the EQP-1A and the 670 at draft-1x and at
  production, as a real-time factor.

*Status (2026-10-30): done.* `varimu-app`'s `print` (`Slot`, `Prepared`, `key`, `print`,
`print_chain`, `Job`; prints in `<session>/prints/<key>/`), `Quality::from_name`,
`audio::loudest` / `level_dbfs` (moved from the Play view). The tests cover the first four
points (`print::tests`, on `triode_stage_drawn`; the 670 only keyed). Print threads run
below normal priority. `examples/print.rs` prints a file through a chain. The cost, 30 s of
`vocal_longwayhome.wav` at 48 kHz, one job at a time, the 670 at AC threshold 0.7:

| Device | draft-1x | production |
|---|---|---|
| EQP-1A | 0.27x real time (8.5 s) | 3.43x (105 s) |
| 670 | 0.42x (13.3 s) | 11.37x (353 s) |

So a 3-minute track prints through both in about 2 minutes at draft and about 45 minutes
at production. The draft 670 prints faster than it plays (0.42x against ~0.85x live):
offline, no block has to meet its deadline.

**F2. Inserts in the Session view.** Insert slots on tracks, the bottom panel, trim and
make-up, bypass, prints on edit (debounced), badges, playback of prints, `session.json`
carries the slots, undo covers them.
*Done when:*
- the EQP-1A and the 670 in a track's chain; a knob change prints again in the background
  while playback continues, and the new print is heard when ready;
- a session reopens to the same mix bit for bit (prints found in the cache);
- no action loses a take; removing an insert keeps its prints until a clean-up.

*Status (2026-10-30): built, not yet tried by the user.*
- **The model** (`session.rs`): `Track::inserts` (saved in `session.json`, so undo covers
  them), `Track::printed` (not saved; found again in the cache), `chain_signature` (the
  active take, the rate, the inserts not bypassed), `playing` (the print of the active
  take, stale or not, else the take) and `print_current`. The mix plays `playing`. A state
  restored by undo keeps the prints that still fit. Tested in
  `session::tests::inserts_are_saved_and_the_mix_plays_their_print`.
- **The view** (`session_view.rs`): a row of insert chips under each strip (the track is
  taller, 102 px), + lists the devices that take audio in (not the ones with their own
  oscillator), right-click bypasses or removes. The bottom panel shows the selected
  insert: trim, make-up, Match (on the last insert: the print as loud as the take), bypass,
  the quality (play or production), ◀ ▶ in the chain, Remove, and the device's knobs as
  sliders and menus (`panel::knobs`). Prints run two at a time, start when no mouse
  button is down and no recording runs, and are cancelled when their chain changes. The
  lane draws the print (with its tail) when the track plays it.
- **Not yet:** the knob widget is plain egui, not the Play view's knobs; levels and
  gain-reduction meters in the panel; clean-up of unused prints; a print's progress in
  the lane.
- **The user's first try (2026-10-30):** the 670 added, then the Play view's Start device
  pressed: the print ran, but there was no way to hear it while turning its knobs, and
  the session couldn't play without a live device. That pulled F3 forward, and the
  session now plays without a device (below).

**F3. Audition.** The selected insert plays live on its input at the playhead (a source
in the player locked to the timeline). One live device in the session at a time: an
audition takes the armed instrument's place while the panel is open.
*Done when:*
- knob to ear is no worse than the Play view's (~0.3 s; rewiring selectors 0.3-0.55 s);
- the live audition and the print are measured against each other after the settle;
- the load is measured with the rest of the session playing prints.

*Status (2026-10-30): built; the user to try it.*
- **The player** (`player.rs`): `Source::Timeline { audio, start }`, a track's audio read
  at the positions the transport gives each block (`timeline_block`, tested), and
  `Source::Mix` / `Player::start_mix`, the session's tracks and click with no device. The
  worker's last stage is now the `Emitter` (was a closure), shared by every source.
- **The view**: an open insert panel is an audition (`sync_audition`): the Play view's
  device stops (`PlayView::adopt` / `release`), the insert plays live on its input (the
  prints of the inserts before it, `Printed::stages`, else the take), the track leaves the
  mix and the live device plays through its strip (`Session::mix_audition`); knob,
  trim, make-up and bypass changes go to the player as they happen. The track isn't
  printed while auditioned; closing the panel prints it, and a session that was playing
  plays on without a device. ▶ (Space) with nothing playing starts the mix-only player;
  record still starts the Play view's device (an instrument). No recording while
  auditioning.
- **Measured** (`examples/audition.rs`, 12 s of `vocal_longwayhome.wav`, the 670 at
  draft-1x, AC threshold turned 0.3 -> 0.9 halfway): started in 0.53 s, load 53% mean,
  126% worst block, 0 dropouts, knob to ear 284 ms. Mix-only: 0% load, 0 dropouts.
- **Not yet:** the audition against its print (done-when 2), the load with many tracks
  of prints playing.

**F4. Sends and FX tracks.** FX tracks, send levels pre / post fader, the bus sum, prints
with tails, the return strip.
*Done when:*
- two tracks sent to one FX track with a reverb print and play;
- a send level change re-prints only the FX track's chain;
- the reverb's tail plays past the session's last take.

**F5. Production.** With RECORDING_PLAN.md T4: Render session renders the takes, then the
chains, at production, as background jobs (one per core; none while a device plays live);
the draft / production switch covers prints; bounce and stems include them.
*Done when:* a bounce at production is reproducible from the session folder on the same
code version, and its prints equal Python's renders of the same inputs.

## Decisions (2026-10-30, the user's, taking Claude's recommendations)

1. **The plate first** (REVERB_PLAN.md, "2026-10-30: the session's reverb"): printed sends
   take real time out of the question that put the spring first.
2. **An audition takes the live slot.** Opening an insert's panel stops the armed
   instrument playing live until it closes: one live device in the session at a time.
3. **The trim is set once, not re-normalized**: at the input's loudest stretch to
   -18 dBFS when the insert is added, then fixed, so a hotter take upstream drives the box
   harder.

## Open

- **Faster draft prints** (later, an option): split a long print into overlapping chunks
  on several cores, each warmed up on what precedes it (the compression curve's method,
  `slice_report.py`). It isn't bit for bit with one run and its warm-up must outlast the
  device's memory, so it would be for iterating only, never for production.

## Risks

| Risk | What we'd do |
|---|---|
| A 670 print at production takes ~15x the track's length | Production on demand only (F5), jobs in parallel; draft prints while iterating |
| Prints pile up on disk (a 3-minute mono print is ~35 MB) | Clean-up removes prints no state in the undo history refers to |
| An audition sounds different from its print at the start | Expected (a defined start vs. the playhead); measured in F3, shown |
| Draft-1x's double resampling (48 kHz session -> 96 kHz -> 48 kHz host) | Correct and Python's path; skip the round trip later if it costs |

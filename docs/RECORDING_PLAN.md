# Recording: a click, takes and tracks in the native app

Drafted 2026-10-30 at the user's request: record what's played (the tube synth from the
keyboard, against a metronome click), play it back, and layer more tracks on top, as in
a DAW. **Nothing here is built. Where it goes in the order is the user's call** (below,
open decision 1). It is a track of the native app ([NATIVE_APP_PLAN.md](NATIVE_APP_PLAN.md)):
native only, nothing goes into the web app. When it's started, work the milestones in
order, each ending with its "done when" met and covered by tests, like the other plans.

## What it is, and what it isn't

- **It is:**
  - a transport with a metronome click;
  - takes recorded through one device, from a MIDI keyboard or an audio input;
  - tracks layered and overdubbed;
  - every take re-renderable at production;
  - a mix, stems and MIDI out.
- **It isn't (for now) a general DAW.** No plugin hosting, no time-stretching, no audio
  editing beyond moving and trimming clips, and no note editor until T6. Whatever we
  don't build, the export hands to any DAW (stems from bar 1, MIDI). This follows the
  user's "build our own tools" preference: build what's ours to do (the devices, their
  takes), and use interop for the rest.

## The idea that shapes it: a take is a performance, not audio

The live path is deterministic:
- `Stream` run block by block equals a whole run, bit for bit.
- Noise is a pure function of the sample index from the run's start (B5).
- A knob change is applied at a sample (`Transient::update`).

So a take stores what went **into** the device:
- the device and its pinned versions (`NAME@N`, C1);
- the quality it was played at;
- the front panel at the take's start and the state the run started from;
- the events (keys, controllers, knob changes, restarts), each at the sample where it
  took effect;
- for an input take, the dry input audio.

The audio heard is kept too. It is what a track plays back while the session is being
built (the user's way of working, 2026-10-30):
- lay a track down live at draft;
- play the next one over it while the first plays as audio, at almost no CPU;
- never wait for production while iterating.

Production is the final render, from the same events, when the user asks for it.
Replaying the events offline at the same quality gives the draft audio back bit for
bit (so it's also never lost), and replaying them at production renders it right.

Why this way:

1. **The synth plan already asks for it.** Decision 3 of
   [TUBE_SYNTH_PLAN.md](TUBE_SYNTH_PLAN.md) says: a take played live is recorded as
   events and re-rendered at production. S3's done-when is still open on exactly this
   (T2 below closes it).
2. **A layered session can't run its devices live.** The tube synth alone uses ~62% of
   the machine at draft-2x (four threads). Only the armed track runs a device live. The
   other tracks play rendered audio, which costs almost nothing.
3. **Reproducibility (Hard rules).** Every track is reproducible from (circuit version,
   events, settings, code version).

**Physical honesty.**
- Each device stays one coupled simulation. Tracks are separate boxes, summed afterwards
  as a console's bus sums them: the same argument as the reverb plan's decision 2.
- Volume, pan and the sum are plain arithmetic, a console's job. The input normalizer
  already works that way (a fader ahead of the device).
- A physical console or tape machine on the bus would be a device, later (T5;
  FUTURE_DIRECTIONS.md's tape medium).

## What exists (2026-10-30)

- **`player`.**
  - A worker thread computes blocks of 480 samples (10 ms at 48 kHz) into a lock-free
    ring. A cpal output callback copies them out.
  - Sources: a file's loop, live input, MIDI keys.
  - **Record** keeps a dry input take: float32 WAV at the device's rate, in
    `cache/app_takes/`. It then opens as the file.
  - Latencies come from cpal's timestamps (`Status::latency_s`).
- **`midi`.**
  - `Keys` holds the keys held and each controller's last value.
  - The worker polls it once per block (`keys.sounding()`), so notes start and stop on
    10 ms block boundaries.
  - A note shorter than a block can be missed.
  - S3's "not yet" list has this.
- **`live`.**
  - A knob change is built on a background thread and applied when the build is ready,
    so the sample it lands on isn't deterministic.
  - A change of structure restarts the stream with a crossfade.
  - Renders never update (B6).
- **`render`.** Production offline with progress and cancel, bit for bit with Python
  (`scripts/app_render_agreement.py`), on a file input with a fixed panel.
- **Control inputs (S3)** fed per sample, partitions, seeded noise (B5), and warm or
  cold heaters (B6).
- **Speeds.**
  - tube_synth: ~62% load live at draft-2x, worst block ~99%, at a 50 ms buffer.
  - The LC oscillator at production: 3.4x slower than real time. The whole voice will be
    slower (T4 measures it).
  - So a 3-minute track takes minutes to tens of minutes to render at production: a
    background job.

## Design

### Clock, transport and click

- **One clock.** The session position counts the samples the worker computes, at the
  host rate. The timeline is kept in samples at the session rate (decision 2), with
  tempo and meter (a tempo map later).
- **The click.**
  - Generated in the worker and mixed into the output after the devices and the monitor
    (bypass, gain compensation). It never goes through a device and never into a take.
  - Sample-accurate, a short band-limited blip with an accented downbeat.
  - Its own level, a count-in (1-2 bars) and pre-roll.
  - Later: the click on a separate output pair (headphones only).
- **What the player hears is late.**
  - By the queue ahead of the output plus the output device's latency (already measured
    from cpal's timestamps).
  - Latency compensation places a take where the player heard the click, not where the
    worker computed it.
  - A loopback calibration (an output cabled to an input; the app plays clicks and finds
    them) measures the round trip once per interface, as DAWs do. cpal's estimate is the
    default until then.

### Takes

A take is a folder, `takes/<id>/`:

- `take.json`:
  - the device, the circuit and component versions pinned;
  - the quality played at, the panel at the start, the run's start (settled warm, or
    cold) and the noise seed;
  - where the take sits on the timeline and the latency used;
  - the code version (`git describe` plus circuitsim's `SOURCE_HASH`).
- `events`:
  - note on and off with velocity, controllers, knob changes and restarts, each at the
    stream sample where it took effect;
  - our own format, because a standard MIDI file counts in ticks, not samples; exported
    to `.mid` on demand (T4).
- `input.wav` (input takes): the dry input, as Record keeps it now.
- `draft.wav`: the device's output as heard, before bypass and gain compensation (the
  monitor's job, not the take's).
- `production.wav`: written when it has been rendered.

**What exact replay needs** (T2):

- **Events at samples, live and offline.**
  - `Keys` becomes a queue of timestamped events (midir gives microseconds), not a state
    polled once per block.
  - The worker computes ahead of the output, so a key can only land in a block not yet
    computed: live, a key is always late by the queue. Placing each key inside that
    block at its timestamp's offset keeps the player's timing (no 10 ms quantization) at
    a constant latency.
  - Whatever the live path does, the take records the sample where the key took effect,
    and the replay applies it there.
- **Knob changes and restarts logged where they landed.**
  - The background build lands at a non-deterministic sample. The log keeps that sample,
    not the moment the knob moved.
  - A restart's crossfade is replayed at the same sample.
  - Renders gain updates at samples: B6's "renders never update" changes, and the
    first-order restart after an update applies to them as it does live.
- **A defined start.**
  - Arming a track restarts its device during the count-in: a settled warm run as a
    render starts, or a cold start (power on).
  - It is not a snapshot of whatever the device was doing before. circuitsim can't save
    and restore a run's state, and a defined start is what a render can reproduce.
  - The cost: each take starts from the same warm-up, so drift accumulated across a
    session's takes is lost. Drift within a take is kept (decision 4).
- **The test.** A take re-rendered offline at its own quality equals the audio heard,
  bit for bit. At production it is the same events through the production solve.

**Input takes** (a guitar into the 5E3, a voice into the 670) are the same thing with
audio as the source:
- the dry input placed on the timeline by the input latency;
- knob changes logged;
- re-rendered through the device at production. This is NATIVE_APP_PLAN decision 3's
  "record the take while it monitors, then render that recording", now aligned to a
  timeline.

### Tracks and the session

- **A session is a folder the user chooses** (prefs remember recent ones; never in the
  repo, like clips). It holds `session.json` (rate, tempo, meter, tracks, clips on the
  timeline, mixer), `takes/` and `renders/`.
- **A track.**
  - Has one device (or none: an audio file placed as it is).
  - Its takes are stacked in lanes, one of them active.
  - It has volume, pan, mute, solo and arm.
  - Tracks are mono (devices are mono, the project's convention); the mix is stereo,
    through pan (decision 3).
- **Playback.**
  - The worker sums each audible track's audio (production if rendered, else draft),
    panned, plus the armed track's live device and the click.
  - Memory: a 5-minute mono track at 96 kHz float32 is 115 MB, so 8 tracks is ~1 GB.
    T3 measures it and streams from disk if that's too much.
- **Overdub.** Record a new take on the armed track while the others play. Loop
  recording: each pass over a loop region is a new take in the lane.
- **One live device at a time** (CPU). Two armed tracks only if the load allows, later.
- **Nothing is lost.** A new take never replaces an old one: it is added to the lane,
  like C1's immutable versions. Session edits have undo.

### Production

- **The final render is on demand** (the user's call, 2026-10-30). While iterating,
  every track plays its draft audio and nothing renders at production. **Render
  session** (or one track) renders the active takes at production:
  - one take per core;
  - cached by a key (events, circuit, settings, code version), as renders are now, so
    only changed takes render again;
  - progress per track, and a badge for what each track plays (draft, production,
    rendering n%);
  - a production render isn't started while a device plays live, because the live
    device needs the cores (decision 5).
  - A switch picks what playback uses, draft or production, so the two can be compared.
- **Bounce:**
  - the mix of production audio to a stereo WAV (float32; 24-bit as an option);
  - stems: each track as a mono WAV from bar 1;
  - MIDI export of the event takes;
  - each bounce records what it was made from.
- **Python replays takes too:** `varimu render --take DIR`, and
  `app_render_agreement.py` extended to takes, bit for bit as in R2. Then the lab
  (reports, studies) can measure what was played (decision 6).
- **Another code version.** A take rendered by an older code version keeps its audio
  and is marked as older; re-rendering is the user's choice. A bit-for-bit replay holds
  only on the same code version.

### The view

A third view beside Editor and Play, "Session":

```
 ◀◀  ▶  ■  ●   ⟲ loop   | 012.3.1 |  ♩ 96  4/4  | click ● count-in 1 bar |  load 61%
┌──────────────────────┬──────────────────────────────────────────────────────────┐
│ 1 Bass   tube_synth  │ ▁▃▅▃▁▁▃▅▃▁   ▁▃▅▃▁▁▃▅▃▁                       PROD   │
│   ● M S  ━━━●━ ◐     │                                                          │
│ 2 Lead   tube_synth  │      ▂▅▇▅▂     ▂▅▇▅▂▂▅▇▅▂                   draft 40%  │
│   ● M S  ━━●━━ ◑     │      ┄ take 2 ┄  ┄ take 1 ┄                              │
│ 3 Guitar fender_5e3  │ ▃▃▅▅▃▃▅▅▃▃▅▅▃▃▅▅                             ARMED   │
│   ● M S  ━━━━● ◐     │                                                          │
├──────────────────────┴──────────────────────────────────────────────────────────┤
│ the armed track's front panel (the Play view's, reused)          queue: 2 takes │
└─────────────────────────────────────────────────────────────────────────────────┘
```

The look follows the studio direction. R4's artwork is paused, so this view starts as
plain egui, as the Play view did.

## Milestones

**T1. Transport and click.** Session position, tempo, meter, a sample-accurate click
mixed after the devices, count-in, pre-roll, the latency shown, loopback calibration.
*Done when:*
- a loopback recording of 10 minutes of click finds every click within one sample of
  where it should be, with no drift between the transport and the output;
- the cpal estimate and the loopback measurement are both shown and compared;
- the click adds no dropouts while a device plays (load measured with and without it).

**T2. Takes as events** (closes S3's open done-when).
- Timestamped key events placed within the block, not polled at its boundaries.
- Knob changes and restarts logged at the sample they landed.
- Arming restarts the device at a defined start.
- Renders apply events and updates at samples.
- The take folder.
- Input takes the same way, the dry input placed by the input latency.

*Done when:*
- a take played live on tube_synth (notes, controllers, knob moves, a structural
  restart) re-renders offline at its quality bit for bit equal to the audio heard, and
  renders at production;
- an input take does the same on the 5E3;
- key events injected at known click times through the player's event path land on
  their beats within one sample of the compensated position;
- the user plays to the click and the take sits on the beat by ear;
- a note shorter than a block is no longer lost.

**T3. Tracks and overdub.** The session format, lanes, the playback mix, overdub, loop
recording, mute / solo / volume / pan, save and load, undo.
*Done when:*
- 8 tracks play back with tube_synth armed and played live, with no dropouts beyond what
  tube_synth alone has at the same buffer (the mix's cost measured);
- a session reopens to the same mix bit for bit;
- no action loses a take.

**T4. The final render and export.** Render session / track at production on demand,
its cache, badges, the draft / production switch, bounce, stems, MIDI export, Python's
`--take`.
*Done when:*
- takes rendered at production in the app equal Python's bit for bit;
- a bounce is reproducible from the session folder on the same code version;
- stems and MIDI open in another DAW lined up at bar 1;
- the production speed of a tube_synth take is measured and reported.

**T5. Chains and the bus.**
- A track's device feeding another device, offline: the synth into a spring tank once
  the reverb plan has one; a guitar through the 5E3 and on.
- The mix through a device: the 670 on the bus. That needs a stereo or two-channel
  device; today's 670 circuit is one channel with channel 2 lumped, so that's its own
  decision when T5 comes.

*Done when:* a chain renders reproducibly at production and plays back in the session.

**T6. Editing.**
- Move, trim, split and loop clips; comp across takes.
- A note editor for event takes (timing, velocity, quantize).
- Knob automation drawn as lanes.
- Edited events re-render offline (no live device is needed to hear an edit).

*Done when:* an edited take re-renders reproducibly, and the edit is undoable.

## Open decisions (the user's; Claude's recommendation first)

1. **Where it goes in the order.** T1-T2 when the synth is next picked up: T2 is S3's
   open done-when, and the user's example is the synth. T3 onwards after that. Or park
   the whole track like the reverb plan until asked.
2. **Session rate.** 96 kHz, the project's rate and production's, so production audio
   is never resampled. Draft audio (48 kHz) is upsampled once when saved, and the mix
   is resampled to the host rate for playback. Alternative: 48 kHz, half the memory,
   with production resampled down.
3. **Mono tracks, a stereo mix through pan.** Yes. Stereo devices come with T5's bus
   question.
4. **A take's start.**
   - Recommended: restart at a defined state (reproducible now).
   - The alternative: save and restore a running device's state in circuitsim, so a
     take continues from the session's warm-up and its drift. That keeps "drift as
     character" across takes, at the cost of an engine feature. It could come later as
     an option.
5. **Production renders and live play.** Decided: the final render is on demand, never
   automatic. Still open: whether one may run while a device plays live. Recommended:
   no (it waits or asks), because the live device needs the cores. The alternative is
   idle priority, accepting the risk of dropouts.
6. **Python replays takes.** Yes, so reports and studies can measure what was played,
   and R2's bit-for-bit standard extends to takes.

## Risks

| Risk | What we'd do |
|---|---|
| **Playing feel.** tube_synth needs a 50 ms buffer, so a key is heard ~60-80 ms late; playing tight to a click is hard at that latency | Recording compensates placement, not feel. The latency is shown. The fix is the engine's speed (the synth's draft, partitions), outside this plan. |
| A production render competes with live play | On demand only, not while playing (decision 5) |
| Draft audio isn't what production will sound like | Expected: draft is for iterating. The draft / production switch compares them once the final render is done |
| Memory in long sessions | Measured in T3; stream from disk past a limit |
| Replays depend on the code version | Each take records it; older renders are kept and marked, re-rendering is the user's choice |
| Knob builds land late live | Logged where they landed, so the take is still exact; the knob-to-ear time stays NATIVE_APP_PLAN's ~0.3 s |
| Takes from a defined start lose the session's drift history | Decision 4; state save / restore later |

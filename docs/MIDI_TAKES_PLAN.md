# MIDI takes: record notes, hear a proxy, render offline, polyphony

Drafted 2026-11-04 from a brainstorm with the user. Nothing built. What the final render
spends its compute on is [SYNTH_MASTER_PLAN.md](SYNTH_MASTER_PLAN.md) (the `master`
quality).

## Why

Most of our instruments are heavy, and some barely run in real time. That's fine:
accuracy comes first. But today the Session view can only record a device's live audio,
so a device that doesn't fit can't be recorded at all, and one that just fits can't have
its CPU-parked features on (both of tube_synth's oscillators, PULSE, noise and heaters,
production quality). And polyphony was never on the table, because one voice was
already at the limit.

The change: **a take is the notes, not the audio.** You play and hear something cheap.
The take records the events and the instrument's panel. The real instrument renders the
take offline, at draft right after the take and at production on demand. Offline,
polyphony becomes possible.

This builds on [RECORDING_PLAN.md](RECORDING_PLAN.md): its T2 (takes as events) and T4
(the final render) already store a take as events and render production on demand. What's
new here:
- the monitor is a choice, separate from the instrument (the proxy);
- the take's audio comes from an offline render behind the recording;
- a piano roll, pulled forward from T6;
- polyphony.

## Decisions (the user's, 2026-11-04)

1. **The proxy is a manual choice, never automatic.** A track monitors through the proxy
   or through the real device, and the user switches between them by hand at any time.
   The device is offered wherever it can play live (a device Play has an entry for);
   an offline-only instrument monitors through the proxy only. Nothing picks a monitor
   from the measured load.
2. **The proxy follows the panel.** It must be cheap, not dumb. The panel's settings
   (cutoff, glide, the envelope, ...) carry over to the render, so the user needs to hear
   them while playing. The proxy reads the same panel, through tables measured on the
   real device.
3. **Polyphony starts with the most organic version: voices share.** One supply for all
   voices (a chord sags every voice), one LFO, one output stage. Independent voice copies
   (faster, parallel) are a later option, not the first.
4. **Voice allocation:** reuse the voice already on that note, else round-robin, else
   steal the oldest. GLIDE is per voice: a voice glides from the last note it played (the
   Prophet-5's poly glide).
5. **A piano roll** the user opens on a take and edits.
6. **Ring mod's proxy:** the user isn't sure one can sound similar. See "The proxy",
   ring mod; judged by ear after N2.

## Concepts

- **Instrument:** the device the take renders through, and its panel at the take's start.
  Example: `tube_synth`, its panel snapshot, the quality it renders at.
- **Monitor:** what the user hears while playing: `proxy` or `device` (decision 1).
  Per track in the Session view, and in Play. The take doesn't depend on it: the same
  events are recorded either way.
- **Event take:** a take folder holding:
  - `events.json`: keys (note on and off with velocity), pressure, knob changes and
    restarts, each at its sample from the take's defined start (T2);
  - `panel.json`: the panel at the start;
  - `take.json`: the instrument, the quality, the allocator's settings (poly), the code
    version;
  - `renders/<key>/audio.wav` once rendered. The key is sha256 of the events, the panel,
    the built IR, the settings and `SOURCE_HASH`, like F1's prints.

  A take monitored live also keeps its live draft audio (T2's bit-for-bit replay check).
- **Proxy audio is never a take's audio.** It's never bounced or exported. A lane may play
  it as a stand-in until a render exists (see N3), marked as such.

## The proxy

A digital synth per instrument, written in Rust as a `player::Source` like the sampler
(64-sample blocks, the Emitter). It runs at the host rate, aliasing accepted.
Target: all 16 voices together under 1% of one core.

**Per voice:**
- one oscillator per real oscillator (LC, SAW). The waveform is a single cycle captured
  from a draft render of the real oscillator, one per octave per RANGE, played as a
  naive wavetable. The cost is a table lookup, and the tone is closer than a textbook saw
  would be;
- a resonant 2-pole filter (cutoff, Q);
- an ADSR on the filter and the VCA;
- a one-pole glide on the pitch.

**Shared:** one LFO (sine / triangle), as in the poly circuit (decision 3).

**What it follows:** every knob has a measured table from the real device. Most studies
exist already:

| Knob | Measured by |
|---|---|
| Pitch per key, both RANGEs, glide time | The tuning tables, `glide_study.py` |
| CUTOFF, resonance, KEY TRACK, ENV AMOUNT, PRESSURE | The cutoff and key-track studies; a new sweep where missing |
| ATTACK / DECAY / SUSTAIN / RELEASE | `adsr_study.py` |
| LFO RATE (both ranges), VIBRATO, WOBBLE | `lfo_study.py` |
| OSC / SAW / RING levels, velocity | The mixer's gains, `velocity_study.py` |

A new `scripts/proxy_tables.py` gathers these into `config/proxy/<instrument>.json`, with
a source line per table (Hard rules: the proxy's numbers are measurements of our own
device, not invented).

**Not proxied:** knobs the proxy ignores (HEATER, RESERVOIR, noise) are marked on the
panel as "heard in the render only".

**Ring mod:**
- What a proxy gets exactly right: the ring is oscillator × LFO, so a plain multiply puts
  the sidebands (f_osc ± f_lfo) where the real ones are, if the LFO's rate table is right.
  At LFO rates it's a tremolo through zero, exactly.
- What a multiply lacks: the carrier bleed of the selenium ring, the two transformers'
  band limits, the followers' clipping.
- The proxy adds the measured bleed level and a high-pass / low-pass pair fitted to
  `ring_study.py`'s response.
- Expected: right pitches and roughly the right balance, wrong texture. That's enough to
  play to, but the user judges it (decision 6).

## Polyphony

**Voice-bridging features stay; each becomes per voice or shared.** No mode turns them
off:

| Feature | In the poly circuit |
|---|---|
| GLIDE | Per voice (decision 4) |
| ADSR, gate, keyboard bus, KEY TRACK, velocity | Per voice |
| Pressure | Channel pressure to every voice; poly aftertouch per voice if the keyboard sends it |
| Key priority | Mono only; the allocator replaces it |
| LFO, VIBRATO / WOBBLE source | Shared: one LFO, loaded by every voice's inputs |
| Ring mod | Per voice, all fed by the shared LFO (its follower drives four ring transformers: real loading) |
| Supplies (HV, bias, the saw's regulated rails, the LFO's) | Shared, sized for four voices (decision 9) |
| Output | Shared: one output transformer (decision 10) |
| Chain ends (plate, 351 echo) | After the sum, as prints are now |

**The circuit.** `tube_synth_poly`, generated from `tube_synth.yaml` by a script
(`scripts/make_poly_synth.py`), like the 351 echo is generated from the 351:
- the per-voice sections are replicated with a voice prefix (`v1.`, `v2.`, ...);
- the shared sections stay once;
- each voice gets its own control inputs (`gate1`, `pitch1`, `pitch2_1`, `key1`,
  `pressure1`, ...).

Rerun the script after a change to tube_synth. The mono `tube_synth` is untouched.

Noise streams are keyed by part name, so each voice's drift differs by itself. Per-voice
tolerance draws (voice cards that differ) would need the app's nominal-only rule lifted:
decision 13.

**The supply has to be redesigned for four voices.** The mono synth's rectifier already ran
the LFO past its rating. The design has sourced or provisional values like any circuit,
and a reservoir that still sags audibly on a full chord: that's the organic part.

**Cost.**
- DK's cost grows with the square of the states, so one solve with four voices is roughly
  16 times one voice per step.
- Partitioned per voice, each voice is a solve of mono size on its own thread, coupled to
  the shared rails, the LFO and the output one sample late. The partition machinery
  already does this.
- Draft already partitions. The poly circuit partitions at production too
  (decision 8).
- A shared supply means no voice can be skipped while idle. Every voice renders the whole
  take. Independent copies could skip idle voices; not built (decision 14).

**The allocator** runs on the take's events before a render. It turns one stream into four
voice streams and stores its settings with the take, so a render reproduces it. The proxy
uses the same allocator, so glide sources match between the proxy and the render.

## The piano roll

- Opens on an event take, in a pane under the lanes: double-click the take or its button.
- Shows keys down the left and the grid in bars and beats from the session's tempo. Notes
  are bars, with a velocity lane underneath, plus a pressure lane.
- Knob automation lanes come from the recorded knob changes, as steps, editable: this is
  T6's "knob automation drawn as lanes".
- **Edits:** select, move, resize, draw, delete, transpose, quantize (grid and strength),
  velocity.
- Events stay stored in samples; the roll shows beats and writes samples.
- Clicking a note previews it on the proxy.
- In a poly take, notes can be coloured by the voice the allocator gave them (where a
  glide comes from).
- **Undo:** every edit is one step in the session's history (nothing lost, as in T2
  step 1).
- **Re-render:** an edit marks the take's render stale. A new render starts once editing
  pauses (~1 s), and until it lands the lane plays the proxy (decision 12).
- **MIDI files:** importing a `.mid` makes an event take. Export is T4's.

## Milestones

**N1. Event takes** (RECORDING_PLAN.md T2 steps 2-3, unchanged in substance). Keys and
knob changes at their samples, the take folder above, a defined start, renders that
apply events and updates at samples.
*Done when:* T2's done-when: a take monitored live re-renders offline bit for bit equal
to what was heard, and renders at production.

**N2. The proxy (mono).**
- `player::Source::Proxy`;
- the monitor switch (per track, and in Play);
- `scripts/proxy_tables.py` and `config/proxy/tube_synth.json`;
- the wavetables from draft renders;
- ring mod as above;
- the "render only" marks.

*Done when:*
- 16 voices run under 1% of a core;
- against the real device at the same panel: pitch within 5 cents, glide and envelope
  times within 20%, cutoff within a third of an octave, the ring's sidebands at the right
  frequencies and their levels within 3 dB;
- the user plays it and records a take through it.

**N3. Render behind.**
- A take recorded through the proxy renders at the instrument's draft quality in a
  background `Job`, automatically after every take (decision 11; below normal
  priority, paused while a device plays live, RECORDING_PLAN.md decision 5).
- The lane's badge shows proxy, rendering n%, draft, stale or production.
- The render replaces the proxy's stand-in when it lands.

*Done when:*
- a 1-minute tube_synth take with both oscillators on (over budget live) records through
  the proxy and plays back rendered;
- a re-render from the folder is bit for bit the same.

**N4. The piano roll** as above, its edits undoable, re-rendering behind.
*Done when:*
- an edited take re-renders reproducibly (T6's done-when);
- a quantize lands every note on its grid sample;
- a `.mid` imports as a take that renders.

**N5. The allocator and the poly proxy.** Voice streams from one take's events
(decision 4), stored with the take; the proxy plays four voices with per-voice glide (it has 16, so more voices stay a
setting).
*Done when:* the allocator's tests pass (same note reuse, round-robin order, stealing,
glide sources), and the user plays chords through the proxy.

**N6. The poly circuit.**
- `make_poly_synth.py` and `tube_synth_poly`: the per-voice / shared split, the shared
  supply (a 5U4GB, decision 9), the output transformer the voices share (decision 10),
  both builders, idle tests;
- the app's per-voice key feeds;
- a per-voice partition.
- First, measure the mono voice at production and at offline draft: T4 asks for it, and
  nobody has measured it yet. Then 2 voices, then 4.

*Done when:*
- a 4-note chord renders at draft;
- a chord's supply sag shows on every voice's rails;
- the cost per voice is reported.

**N7. Poly at production.** The poly take renders at production in the session,
partitioned per voice (decision 8).
*Done when:* a poly take renders at production reproducibly, and the partitioned run
is checked against one solve on a short excerpt (as M8 checked the 670's draft: -103 dB).

## Decided after the draft (2026-11-04)

The user set the voice count and delegated the rest to Claude, so items 8-14 are Claude's
recommendations, adopted. They continue the numbering of "Decisions" above. The user's later calls override any of them.

7. **Four voices** (the user's; the Oberheim Four Voice's count). N6 still measures the
   cost per voice; more voices only if the user asks later.
8. **The poly circuit partitions per voice at production too.** Each voice is a part of
   its own, and the shared sections (supplies, LFO, output) are owned by the last part
   (the partition rule: list the stiff drivers last). It is checked against one
   unpartitioned solve on a short excerpt (N7's done-when). One solve with 4 voices would
   cost ~16x a voice. This bends "one coupled solve" at production for this circuit only,
   as M8's draft bent it. The final render's `master` quality
   ([SYNTH_MASTER_PLAN.md](SYNTH_MASTER_PLAN.md), the user's 2026-11-04) runs poly as one
   solve, at master only, and N7 checks against it.
9. **The shared supply's rectifier: a 5U4GB**, period-appropriate and sized for four
   voices. The reservoir is chosen so a full four-note chord still sags audibly. Values
   are sourced from the sheet or provisional, as any circuit's.
10. **The voices sum on one output transformer:** every voice's push-pull VCA in parallel
   onto its primary, so loud chords interact through the core.
11. **Render behind runs automatically after every take,** at draft, below normal
   priority, paused while a device plays live.
12. **An edited take plays the proxy until its re-render lands** (the proxy has the new
   notes; the old render has the old ones).
13. **Per-voice tolerance draws wait.** They need the app's nominal-only rule lifted; the
   voices differ by their noise streams meanwhile.
14. **Independent voice copies are not built** unless the shared circuit proves too slow
   for long takes after N7.

## Risks

| Risk | Answer |
|---|---|
| The proxy misleads: a part sounds right on the proxy and wrong rendered | Render behind (N3) puts the real thing in the lane within minutes; "render only" marks |
| Poly renders take hours | Draft first; the cost per voice measured in N6; decision 14 as the fallback |
| The shared supply's design dominates the sound | It's meant to (decision 3); its values are sourced or provisional like any circuit |
| A change to tube_synth leaves the poly circuit stale | Generated by script; a test compares it with a fresh generation |
| Proxy tables go stale after a circuit change | `proxy_tables.py` records the circuit's hash; the app warns when it differs |

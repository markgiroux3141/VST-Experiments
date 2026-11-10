# The Session view as a DAW: mixer, clips, editing, deliberate renders

Drafted 2026-11-05 from the user's review of the Session tab ("let's see if there's any
gaps"); the same day the user took every recommendation and made insert prints manual too
("Decisions" below). Built 2026-11-07 (SE1-SE7; "Status" below has what is open). It continues RECORDING_PLAN.md's T6 (editing), MIDI_TAKES_PLAN.md's
N4 (the piano roll) and SESSION_FX_PLAN.md's F2-F4 (inserts, sends), and doesn't redo them:
where one of those already plans a piece (knob automation lanes, `.mid` import, sends), this
plan says where it fits and leaves it there.

The user's list: a mixer with sliders for balancing, pan, inserts; cutting audio and moving
it around; quantized or free placement; copy and paste of audio and MIDI; a point to play
from; the piano roll playing a note when one is added or edited; and a synth's render after
a MIDI edit as a deliberate step, not automatic. The rest (marked *added*) is what the survey
below turned up.

## Status (2026-11-07, built in one session, the user away and delegating every call)

Branch `session-editing` (worktree `../VST-Experiments-session`), commits SE1-SE7. Every
milestone is built. The exceptions are listed per milestone and under "Open". Tests:
`cargo test -p varimu-app` (the view's tests drive a scratch session, never the user's).
The app was looked at on a scratch copy of `sessions/beat1` with a scratch `APPDATA`
(`varimu-app --session` / `--mixer`, new flags).

**SE1, deliberate renders: built.**
- Prints and MIDI renders start only when asked: Print on the insert row and panel;
  Print inserts (n), Render edits (n) and Render all (n) in the session line; the roll's
  Render and ⤓ PROD; the take menu; Ctrl+R.
- A chain that isn't current is looked up in the print cache by itself, never rendered
  (`print::Job::lookup`, `NOT_PRINTED`), so undo and a reopened session find old prints.
- An edited take plays its revision through the device's proxy, made offline at once
  (`proxy::render_performance`, `TakeRender::proxy`, `Plays::Proxy`; decision 1). With no
  proxy it plays its last render, stale.
- Badges: `edited, not rendered (Ctrl+R)`, `render queued`; on inserts ○ `inserts changed ·
  not printed` (the last print plays stale, or the lane dry).
- Export waiting offers "Render them and export"; Export final… asks for what it needs.
- Tests: `session_view::tests::a_chain_change_prints_nothing_until_asked`,
  `an_edit_renders_nothing_until_asked_and_plays_the_proxy`.
- Not built: a render button on the track strip itself (Ctrl+R and the take menu cover it).

**SE2, the cursor and snap: built.**
- `TransportSettings::cursor` (samples) replaces `start_bar`; old sessions' start bar
  becomes the cursor (`transport_from(.., rate)`).
- Count-in and pre-roll count back from the cursor's bar, and the take records from the
  cursor. With neither, play starts at the cursor itself.
- Stop: back to the cursor or stays where it stopped (the "return" toggle); Shift+Space
  plays from where it stopped. Moving the cursor while playing plays on from it. The
  cursor isn't an undo step.
- Snap: Bar, Beat, 1/8, 1/8T, 1/16, 1/32, Off; Alt inverts it. Moves keep their offset
  from the grid (`Grid::snap_delta`); locators sit on beats (bars with the Bar snap).
- Markers: M, or the ruler's right-click (add, rename, delete); a click on a flag jumps
  there.
- Changed: the right locator moved from Alt+click to Shift+click, since Alt now inverts
  the snap.

**SE3, piano roll previews and editing: built.**
- Every edit kind sounds the note. Drawn notes sound briefly, a move each semitone
  crossed, transpose / resize / velocity briefly on release; the keys column plays its
  key. The "preview" toggle turns them off.
- Previews go through the device when Play plays it from keys, else its proxy, else the
  test oscillator. A preview voice in the player's emitter rides on any player
  (`Player::set_preview_voice`, `preview_key`).
- Decision 8's middle option (the track's device started live for the roll) is not built:
  devices without a proxy preview on the test oscillator.
- Editing:
  - Ctrl+C / X / V / D on notes; paste lands at the session's cursor, which a click on
    empty roll space sets.
  - ← / → nudge; Ctrl+↑ / ↓ octave; Shift+drag copies.
  - Drawing uses the last drawn or resized length; quantize "ends".
- Not built: quantize-on-record per track.

**SE4, the Mixer and meters: built.**
- A Mixer tab (X toggles). Each strip has name, arm / M / S, the insert chips (the same
  panel; reorder by their menu's "Earlier", not by drag), a reserved sends row, a pan
  knob, a vertical fader and a stereo meter (peak, hold, RMS).
- The fader's law (`mixer::fader_pos`) puts 75% of its travel between −30 and +6 dB.
- The master strip has a fader on the sum (`Session::master_db`, saved; the mixdown
  and stems follow it), a meter and a clip light.
- The player meters per block, post-fader: each clip on its track, the live device on the
  armed track, and the master (`Meters`, `Player::take_meters`).
- The arrangement's strip fader is a slider with the meter behind it.

**SE5, clips: built.**
- The model:
  - `Clip { id, take, src_start, len, position, gain_db, fade_in, fade_out, muted }`; a
    track's `clips` are its lane, later ones on top.
  - `Track::pieces` takes out what later clips cover; the earlier clip crossfades under
    their fades.
  - Cut edges get 2 ms. A take's own ends and an untouched split get none, so a split
    plays bit for bit as before.
- Gestures: split (S), trim by the edges, move (to another track too: the take joins
  its pool), fade handles, gain handle, mute, delete, comping by dragging across a take
  row. ‹ › and a take row's click put that take in the lane whole.
- Prints, auditions, sidechains and bakes take the lane as arranged (`Track::lane`). A
  lone whole clip is the take's own audio, so old prints keep their cache keys.
- Bounce lays audio clips where the MIDI clips were and mutes those (decision 7).
- The session file is version 2. A version-1 session opens as one clip per track, and
  its `session.v1.json` is kept on the first save.
- **All 24 sessions in `sessions/` play the same mix bit for bit**
  (`session::tests::every_session_opens_to_the_same_mix`, ignored; run with
  `VARIMU_SESSIONS=<sessions dir>`).

**SE6, clipboard and MIDI clips: built except decision 6.**
- A drag on empty lane space selects a range across tracks. Ctrl+C / X / V / D copy, cut,
  paste (at the cursor on the armed track, with the tracks' offsets) and duplicate
  (repeats) a range or a clip. Delete deletes a range.
- Clips share their take: no audio is copied.
- Insert / delete time between the locators, from the ruler's menu.
- MIDI clips copy, trim and move as clips of their event take. **Decision 6 (a track's
  MIDI clips rendered as one performance) is not built.** Each event take still renders
  whole and its clips play stretches of that render, so a pasted bar repeats the same
  audio rather than continuing the device's state.

**SE7: built, except editing the lanes.**
- Punch in / out (`TransportSettings::punch`, `Clock::record_to`,
  `Recorder::capture_until`).
- The ? overlay.
- Tracks: moved up / down (the strip's menu, not by drag); height by Ctrl+wheel over the
  strips.
- The roll follows the playhead, shows ghost notes and lights a scale.
- Aftertouch and pedal are drawn under the velocities, shown but not editable (knob lanes
  stay with N5).

**Normalize (2026-11-08, the user's ask):** a clip's right-click menu normalizes its peak (either
channel, -1 dBFS by default) or its level (its loudest 8 s, as an import's, -18 dBFS by default)
by setting the clip's gain (`Track::normalize_clip`); the take is untouched, Undo or "Reset gain
and fades" takes it back.

**SE8, audio editing tools and bounce: built 2026-11-10** (in main, the user's ask: "add
these features now" after a brainstorm of what the Session view still lacked; the user hadn't
found SE5-SE6's editing behind keys and right-click menus, so the first item is a toolbar).
- **A toolbar** over the arrangement: the tools, Cut / Copy / Paste / Duplicate / Delete /
  Split, the switches Zero crossings and Ripple (both kept in `recording.json`), the Clip
  menu and Bounce, ? for the keys. Undo / Redo stay in the bottom bar.
- **Tools** (keys 1-5 with the pointer off the roll, as the roll's 1-3): Pointer; Blade (a
  click splits there, the cut previewed as a line); Erase (a click deletes); Slip (a drag
  slides the audio inside the clip, `src_start` only: the pointer does it with Ctrl+drag);
  Envelope (a click adds a point or removes the one under it, a drag moves one).
- **Pointer additions:** Shift+drag drags a copy of the clip; ← / → nudge the selected clip,
  or the clips wholly inside the selected range, a snap step (10 ms with the snap off; Alt:
  one sample).
- **The clip** (`session::Clip`) gained `invert` (polarity), `curve` (`FadeCurve`: linear or
  equal power; a cut it makes in a clip under it crossfades in its shape) and `env` (a gain
  envelope: points (samples from the clip's start, dB), linear in dB between, -48 to +12 dB;
  it belongs to the clip, so a slip moves the audio under it; splits, trims, range copies and
  strip silence keep it where it was on the timeline). Written to `session.json` only where
  set and added to the lane's signature only where set, so every existing session and print
  key is unchanged (`every_session_opens_to_the_same_mix` passes on all of `sessions/`).
- **Clip menu** (a clip's right-click and the toolbar's): Invert polarity; fades linear /
  equal power; Crossfade into the next clip (the clip starting within 50 ms of its end; both
  stretched over the join as far as their takes have audio, the later one on top), either
  as a **tape splice** (`edit::splice_s`: 1/4-inch tape cut at 45° or 60°, at 15 or 7.5 ips:
  16.7 / 9.6 / 33.3 / 19.2 ms; a diagonal splice crossing the head's gap is a linear
  crossfade in amplitude of that length) or over a set length, linear or equal power;
  **Reverse** and **Varispeed** (pitch and time together, as a capstan does it: `edit::
  varispeed`, the ratio as a fraction of numbers up to 1000 through `resample_poly`'s Kaiser
  filter, so speeding up doesn't alias; no time-stretching, deliberately) into a **new take**
  (`Session::process_clip`: fades and envelope follow the audio); **Split at transients**
  (`edit::onsets`: the first difference's level in 2.5 ms hops rising a set number of dB over
  the quietest of the 30 ms before, at least 50 ms apart; the cut 3 ms ahead so its 2 ms fade
  ends before the attack; the slices end up selected); **Quantize** to the snap (each clip's
  attack, the first sample at a quarter of its first 50 ms' peak, onto the nearest line; the
  selected range's clips, else the clip); **Strip silence** (10 ms windows under a level,
  silences under 250 ms kept, 20 ms of room each side); **Consolidate** (the selected range on
  each track it covers, else the clip, rendered as it plays before inserts into one new take);
  Clear envelope. "Reset gain and fades" also resets the shape.
- **Bounce** (`Session::bounce_audible`): what plays, the soloed tracks or else every unmuted
  one, each as the mix plays it (its print, fader and pan; not the master's chain or fader),
  over the selected range, else the loop when it's on, else everything, into a stereo take on
  a new track at the end ("Bounce of A + B"), or a mono take of (L + R) / 2 ("Mono bounce of
  A + B": a centred track comes back as its own samples, the pan having no centre dip; one
  panned hard at -6 dB); optionally the sources muted and unsoloed. It
  waits like Export: a stale print or an unrendered edit on an audible track is refused with
  the reason. Its `take.json` holds the export record of what went into it.
- **Ripple** (the switch): Delete, Cut and Erase move what follows on that track earlier by
  what was taken out (`Track::delete_clip`, `delete_range_ripple`); markers and other tracks
  stay (Delete time between the locators is the all-tracks version).
- **Zero crossings** (the switch): S and the Blade move a split to the nearest zero crossing
  within 5 ms (`Track::zero_crossing`; a stereo clip's mid).
- Tests: `edit::tests` (onsets within a ms, silences, zero crossings, varispeed's pitch and
  length, splice lengths), `session::tests` (polarity, shapes and envelopes as they play, a
  split inside an envelope seamless, a crossfade over a split of one take equal to the take,
  ripple, a drum take sliced and quantized onto beats, strip silence, reverse / varispeed /
  consolidate / bounce as new takes), `session_view::tests::the_editing_tools_split_ripple_
  nudge_process_and_bounce` (with undo). The toolbar was looked at in a window capture on a
  fresh session.
- Not built: envelope segments are straight in dB (no curves); quantize has no strength or swing; nothing fills the gaps quantized
  slices leave (pulling audio in would double the next hit); Blade and Erase on MIDI clips
  act as on audio clips (Reverse / Varispeed of one makes audio from what it plays).

### Open

- SE8 as a whole: the user's first try.
- Decision 6, a track's MIDI as one performance (see SE6), and quantize on record.
- Dragging to reorder tracks and inserts.
- Editing the pressure and pedal lanes.
- The user's first try: the plan's milestones each ended with one, and none has happened
  yet.

## What exists (2026-11-05)

Read from `crates/varimu-app/src/session_view.rs`, `session.rs`, `piano_roll.rs`,
`transport.rs`:

- **A track plays one take.** `Track::takes` with `Track::active`: a lane is the active take
  whole, from its `position`. Other takes are alternatives, switched (◀ ▶) or shown in rows
  (`show_takes`), not parts of an arrangement. A `Take` has no offset, length, gain or fades:
  nothing can be cut, trimmed or comped. `Session::mix` builds one `MixClip` per audible track.
- **Moving takes:** a drag moves the active take by whole beats (Alt: freely), within its
  track only (`session_view.rs` ~2737). The beat is fixed: no bar / 1/8 / 1/16 / off choice
  for the arrangement.
- **Mixing** sits in each strip in the arrangement: fader and balance as drag values (−60 to
  +12 dB, L100-R100), mute, solo, arm, the insert chips (+ adds, click opens the panel at the
  bottom, right-click bypasses / moves / removes). No meters anywhere, no master fader, no
  vertical faders, no view showing all strips side by side. Sends are F4 (not built).
- **Where play starts:** a bar (`TransportSettings::start_bar`): a click on the ruler moves
  it; Space plays from it (after pre-roll and count-in); Stop keeps the position but the next
  play starts from `start_bar` again. No cursor at a beat or sample, no click-in-the-lane to
  place one, no markers.
- **Clipboard:** none, in the arrangement or the roll.
- **The piano roll** (N4): Select / Draw / Erase, move (grid, Alt free, semitones), resize,
  box select, transpose ↑ ↓, quantize with strength, velocity lane, Ctrl+A, Delete. A note is
  previewed (`Out::Preview` -> `PlayView::preview_key`) when clicked, or drawn with the Draw
  tool; **not** when drawn by a double-click in Select, dragged to another pitch, transposed
  with ↑ ↓, resized or its velocity changed. And `preview_key` only reaches a keyboard device
  playing live in the Play view: with nothing playing, a preview is silent.
- **Renders after edits are automatic.** `poll_take_renders` (~3876) starts a draft render of
  an edited take's revision once editing has paused 1 s (N3), one at a time while a device
  plays live. Insert prints are automatic too (`poll_prints`): every change to a chain, a
  take or a knob re-prints in the background.

## Gaps and what this plan builds

### 1. Renders as a deliberate step (the user's)

Nothing renders on its own: not an edited MIDI take, not an insert chain. An edit makes a
new revision (or a changed chain) and nothing else. The take or track shows that it's
edited and not rendered, and the user renders when they choose.

- A take's badge: `edited · not rendered` (revision n, the render plays revision m) beside
  today's draft / PROD / stale.
- **Render** where the user looks for it: the roll's header (Render this take: draft, or
  ⤓ PROD), the take's context menu, the track strip (every edited take on the track), the
  session line (`Render edits (n)`, next to today's ⤓ Production (n)), and a key (Ctrl+R
  over the roll or with a take selected).
- Renders still run below normal priority, cancellable, one at a time while a device plays
  live, none while recording: only the trigger changes. Export keeps refusing a session
  whose audible takes aren't rendered (`export_problems`), and now offers "Render them and
  export" in the same line.
- **What plays before the render** (decision 1): the proxy where the device has one (it
  follows the edited notes at once, at ~2% of a core), else the last render marked stale.
- **Insert prints are manual too** (decision 2, the user's). `poll_prints` stops starting
  prints by itself. A track whose chain, take or clips changed since its print shows
  `inserts changed · not printed` on its insert row and plays its last print (marked stale)
  or, with none, its dry lane (marked `dry`). It prints from the same places: **Print** on
  the track's insert row and in the insert panel, `Print inserts (n)` in the session line
  (beside `Render edits (n)`; one button, `Render all (n)`, does both), and Ctrl+R with a
  track selected. A knob turned while auditioning is heard live (F3, unchanged); closing the
  panel no longer prints. A keyed track (SIDECHAIN_PLAN.md K3) whose key track's print is
  stale says so and prints after it when asked. Export's "Render them and export" prints
  and renders whatever is stale first.

### 2. A point to play from (the user's)

- A **cursor** at any timeline sample, separate from the loop locators: a click on the ruler
  or on empty lane space puts it there (snapped, section 3; Alt: free). The cursor replaces
  the start bar (decision 3): one place play starts.
- Space plays from the cursor. Pre-roll and count-in count back from it in bars (the click
  stays on the grid: a cursor mid-bar counts in from the bar's start before it and starts the
  timeline audio there, the take starts at the cursor).
- Stop: the playhead returns to the cursor (default) or stays where it stopped (a toggle;
  Shift+Space plays from where it stopped). Home to bar 1, End to the session's end,
  Ctrl+← / → by bars.
- Recording from the cursor places the take there (pre-roll as today).
- `TransportSettings::start_bar` becomes a start position in samples, the session file read
  either way (old sessions: `start_bar` -> its bar's sample).
- *Added:* **markers** (M drops one at the cursor, named, on the ruler; a click jumps there),
  so a song's sections can be found.

### 3. Snap: quantized or free (the user's)

- One **snap** setting in the transport bar: Bar, Beat, 1/8, 1/8T, 1/16, 1/32, Off. Every
  timeline gesture uses it: moving and trimming clips, splits, the cursor, locators, pasting.
  Alt inverts it for the gesture (free when on, the beat when off), as Alt does today.
- Moves keep their offset from the grid (a take recorded 12 ms late and moved by a bar stays
  12 ms late; decision 4).
- The piano roll keeps its own division (it edits notes, finer), its default the session's
  snap when the roll opens.

### 4. Clips: cutting audio and moving it around (the user's)

The model change everything below depends on. A lane becomes a list of **clips**; a take
becomes a source that clips play from.

```
Clip { id, take, src_start, len, position, gain_db, fade_in, fade_out, muted }
```

- A recording makes one clip spanning its take. An old session loads as one clip per track
  (its active take, whole): `session.json` keeps a version, migration in `Session::load`.
- **Split** at the cursor (S) or with a click of a Split tool; **trim** by dragging a clip's
  left or right edge (the audio under it stays, a trim is reversible); **move** by dragging,
  to another track too (vertical drag); **delete** a clip (its take stays in the session's
  pool: `Take` files are never deleted by an edit, as today).
- **Fades:** every clip edge gets a short default fade (2 ms, decision 5: a cut never
  clicks), a handle at the top corner drags it longer; overlapping clips on one track
  crossfade (the later clip wins outside the overlap).
- **Clip gain:** a handle on the clip (drag vertically), shown in dB.
- **Comping** (T6's "comp across takes"): with the take rows shown, a drag across a take row
  selects a range and promotes it into the lane as a clip (the lane's clips cut around it).
  Today's ◀ ▶ (switch the active take) becomes "replace the lane with this take whole".
- **Playback:** `Session::mix` builds a `MixClip` per clip with its offset, gain and fades;
  `Mix::add` applies the fades per sample (a gain ramp, cheap). Mixdown and stems the same.
- **Inserts:** a track's chain prints the track's lane as arranged (its clips summed, gaps
  silent), keyed on the clips' signatures, instead of its active take. The print cache key
  gains the arrangement; nothing else in `print` changes.
- Undo: each gesture one step, as now.

### 5. Copy, cut, paste, duplicate (the user's)

- **Selection** in the arrangement: a click selects a clip, Shift adds, a drag on empty lane
  space selects a range (time x tracks): its clips, cut at its edges on a copy.
- Ctrl+C / Ctrl+X / Ctrl+V: paste at the cursor on the selected track (a range keeps its
  track offsets); Ctrl+D duplicates right after the selection (a 4-bar loop repeated with
  four presses). Audio is never copied on disk: clips share their take.
- MIDI clips copy the same way (section 6). In the piano roll, Ctrl+C / X / V / D on notes:
  paste at the roll's cursor (or right after the selection for D), keeping their spacing.
- *Added:* **insert / delete time** across all tracks between the locators (make room for a
  bridge, cut a chorus), clips and markers shifted.

### 6. MIDI as clips

An event take's notes become a MIDI clip in the lane, cut, trimmed, moved, copied and
duplicated like audio. One thing differs from audio and shapes the design: **a device is a
stateful circuit.** Its envelope tails, a sagging supply, the LFO's phase and drift carry
across a cut. Rendering each MIDI clip on its own from a cold device would make every
pasted bar sound like the first note after power-on and cut tails off at clip ends.

- So a track's MIDI renders **as one performance**: its clips' events laid out on the
  timeline (a clip's notes cut at its edges, a note held across a trim ended there), the knob
  log merged the same way, replayed through one fresh device from the track's first event
  (decision 6). The render is the track's, cached by its arranged events; the lane draws the
  clips over it.
- A track records audio or MIDI (today's `rec MIDI | AUDIO` per track). A bounce makes an
  audio clip on the same track, the MIDI clips it came from muted beside it (decision 7;
  "to a new track" as an option), so a track can hold both kinds; muted MIDI clips are left
  out of the track's performance.
- The piano roll opens on a clip (its notes, the others on the track greyed for context)
  or on the whole track.
- `.mid` import (N5) lands as a MIDI clip; MIDI export of a track (T4) writes its arranged
  events.

### 7. The piano roll (the user's preview, plus gaps)

- **Preview every edit:** a note sounds when drawn (both ways), when dragged to a new pitch
  (each semitone crossed, the old one released), when transposed with ↑ ↓ (the selection's
  notes, briefly), when resized (on release) and when its velocity changes (on release, at
  the new velocity). A click on the keys column plays that key. A **preview** toggle in the
  header turns it off.
- **Preview with nothing playing:** today it's silent unless the Play view's device runs.
  Previews go through the take's device proxy (instant, cheap) where there is one, else the
  track's device is started live for the roll's lifetime (it takes the live slot, as an
  insert audition does), else the test oscillator (decision 8).
- **Audition the edit in context:** Space in the roll plays the session from the roll's
  cursor with the edited take heard through the proxy (decision 1), so an edit is judged
  against the other tracks before it's rendered.
- Copy / cut / paste / duplicate (section 5). Draw uses the last drawn or resized length
  instead of one grid step. Shift+drag a note copies it. Ctrl+↑ / ↓ moves the selection by
  an octave too (Shift is taken), ← / → nudges by a grid step.
- **Quantize ends and lengths** as well as starts (a choice in the header), and a "quantize
  on record" setting per track (default off: free, the user's "quantize or free").
- **Lanes beyond velocity:** aftertouch (`Ev::Pressure`) and the sustain pedal (`Ev::Pedal`,
  the Rhodes) are recorded but not shown or editable: add them as lanes under velocity.
  Knob automation is N5's and fits the same lane strip (the knob log's values drawn as steps,
  edited as breakpoints; a knob change in a take still means a restarted build: N5 says how).
- *Added:* ghost notes of the other MIDI tracks (faint, off by default), a scale highlight
  on the keys (off by default), the roll following the playhead while playing.

### 8. The mixer (the user's)

A **Mixer** tab beside Session (Play | Session | Mixer | Room ...; X toggles it; decision 9),
one vertical strip per track left to right, the master at the right:

- name and colour; arm, mute, solo; a **vertical fader** with a dB scale (a fader law with
  most of its travel between −30 and +6, Ctrl+click to 0 dB, a double-click to type);
- a **pan** knob (today's balance law, `session::balance`);
- **meters**: peak with hold and RMS per track, post-fader, stereo; the master's with a clip
  light. The player measures them (per `MixClip` and the sum, per block, published through
  atomics like `Status`); the UI only reads;
- the **insert slots** as in the arrangement's strips (the same chips, the same panel at the
  bottom; drag to reorder);
- **sends** reserved: the strip's layout has their row, filled when F4 builds them;
- the **master strip**: a fader and meter on the stereo sum (export follows it); master
  inserts wait for T5's stereo bus.

Strips in the arrangement stay (fader, pan, mute, solo there too; the same values).
*Added:* the arrangement's strip fader becomes a horizontal slider with a meter behind it,
so balancing doesn't need the mixer.

### 9. Smaller gaps (*added*)

- **Track order:** drag a strip to reorder; tracks' height adjustable (Ctrl+wheel over the
  strips), so the roll and lanes can be read.
- **Moving across tracks:** comes with clips (section 4).
- **Punch in / out:** record only between the locators, playing the rest (the tracks and the
  armed track's existing clips); recorded audio outside is discarded.
- **Keyboard map:** a `?` overlay listing the Session and roll keys (the editor has one).
- **Tempo changes** stay out: one tempo per session (a tempo map moves every take and every
  render; not asked for).

## Milestones

Small and asked-for first; the clip model, which the rest of the editing builds on, once the
quick wins are in. Each milestone: unit tests for the model, the GUI paths driven once on a
scratch APPDATA and session (never the user's), then the user's try.

**SE1. Deliberate renders.** Section 1; decisions 1-2.
*Done when:* neither an edit nor a chain change starts a render or a print (a test on the
view's job queue after a revision, a knob change, an insert added, moved, bypassed and
removed); the badges say what plays (proxy, stale, dry); Render / Print (take, track,
session, Ctrl+R) run exactly what was asked for; export with stale takes or prints offers to
render them; existing renders and prints are found in their caches as before.

**SE2. The cursor and snap.** Sections 2-3 (markers included); decisions 3-4.
*Done when:* Space plays from a cursor mid-bar with count-in and pre-roll, the click on its
grid; a take recorded from the cursor lands there; Stop returns to the cursor or stays per
the toggle; every arrangement gesture follows the snap and Alt inverts it; old sessions open
with their start bar as the cursor.

**SE3. Piano roll previews and editing.** Section 7 except the lanes (SE7) and the MIDI
clip pieces (SE6); decision 8.
*Done when:* each edit kind in section 7's first bullet sounds the note (a test on `Out`);
with no device playing, a preview is heard through the chosen fallback; copy / paste /
duplicate of notes, last-length drawing, nudges and quantize of ends work and are one
revision each.

**SE4. The mixer and meters.** Section 8; decision 9.
*Done when:* every track's and the master's meters read the mix (a test: a −6 dBFS sine on
one track reads −6 dBFS peak post-fader at 0 dB, the master the same panned centre minus the
balance law's centre gain); faders and pans in both views are one value, undoable; the
master fader moves the export.

**SE5. Clips.** Section 4; decision 5. The session format's version and migration.
*Done when:* every existing session in `sessions/` opens to the same mix bit for bit (one
clip per track); split, trim, move (across tracks), fades, clip gain and comping work and
undo; a split clip with the default fades plays without a click (no sample step above the
signal's own); a track's print follows its clips.

**SE6. Clipboard and MIDI clips.** Sections 5-6; decisions 6-7.
*Done when:* copy / cut / paste / duplicate of clips and of a range across tracks, audio and
MIDI; a MIDI track's arranged clips render as one performance, reproducibly (the same
arrangement, the same render bit for bit) and a note held across a trim ends at it;
insert / delete time.

**SE7. Lanes and the rest.** Pressure and pedal lanes in the roll (knob lanes with N5);
track reorder and height; punch in / out; the `?` overlay; ghost notes, scale highlight,
follow.

**SE8. Audio editing tools and bounce** (added 2026-11-10, the user's ask): a toolbar with
tools (Pointer, Blade, Erase, Slip, Envelope), polarity, fade shapes, crossfades as tape
splices, reverse and varispeed into new takes, slicing at transients and quantizing, strip
silence, consolidate, ripple, splits on zero crossings, nudges, and the soloed tracks bounced
to a new track. *Done when:* each works on a scratch session in tests, existing sessions play
bit for bit, the user has tried it.

## Decisions (2026-11-05, the user's)

The user took Claude's recommendation on each, except decision 2, where they went further
(prints manual, no automatic option).

1. **What plays after an edit, before it's rendered:** the proxy where the device has one
   (tube_synth today), marked `proxy`; elsewhere the last render, marked stale.
2. **Insert prints are manual**, like MIDI renders: nothing prints until the user asks
   (section 1). No "auto-print" setting.
3. **The cursor replaces the start bar:** one place play starts.
4. **Snapped moves keep their offset from the grid:** a late take stays late, as played.
5. **A 2 ms default fade at every clip edge.**
6. **MIDI renders per track as one performance** (section 6): the device's state carries
   across clips.
7. **A bounce goes onto the same track** as an audio clip, the MIDI muted; "to a new track"
   as an option.
8. **Previews with no device playing:** the proxy, else the track's device in the live slot
   while the roll is open, else the test oscillator.
9. **The mixer is its own tab** (Play | Session | Mixer | Room ...), X toggles it.
10. **Order as listed:** SE1, SE2, SE3, SE4 (small, independent), then SE5 (the clip
    model), SE6 on it, SE7.

## Risks

| Risk | Answer |
|---|---|
| The clip migration loses or moves a take | Bit-for-bit mix check on every session in `sessions/` (SE5's done-when); takes are never deleted by an edit; the old `session.json` is kept beside the new one on first save |
| Prints re-run for every clip gesture (minutes each at production) | Prints are manual (decision 2); the key is the lane's clip signature, so undo finds the old print in the cache |
| A one-performance MIDI render re-renders the whole track for a one-note edit | Expected (the device is stateful); draft first, production on request; a long track could later render from a saved device state (RECORDING_PLAN.md decision 4's alternative) |
| Meters cost the real-time thread | Peak / sum of squares per clip per block, a few adds per sample; measured with `examples/play.rs` before and after |
| Previews through a device started for the roll steal the live slot | The same rule as an insert audition (one live device); the roll says which device previews |

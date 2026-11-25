# Presets: saving and recalling a device's settings

Drafted 2026-11-25 at the user's request: the Play view lets you pick instruments and
devices and turn their panels, but nothing saves a panel you like. This plan adds
presets: named, saved panels that load back later, in the Play view first, then on the
Session view's inserts. It is a track of the native app
([NATIVE_APP_PLAN.md](NATIVE_APP_PLAN.md)). Native only; nothing goes into the web app.
Work the milestones in order, each ending with its "done when" met and covered by tests.

**Status (2026-11-25): drafted, nothing built.** The user's decision so far: everything
lives in this repo, nothing in `%APPDATA%` (decision 1).

## What exists (2026-11-25)

- **A panel is a flat list.** Each device's front panel is a `Vec<panel::Knob>` built
  from its circuit file's `controls` (`panel.rs`'s `knobs`): a key, a label, a kind
  (range, steps or choices), a default and a value. `panel::values` turns the knobs into
  the `Values` (`Vec<(String, Value)>`, `live.rs`) a build and `Live::set` take.
  So the heart of a preset is that list, named and saved.
- **Takes already carry a panel.** A MIDI take's `performance::Performance` holds the
  device id, the `values` it started with, the `Playing` settings (the test oscillator's
  wave, the range mode, the velocity range, retrigger, low-note priority), the input gain
  and noise. Every recorded take is a preset already, just not one you can load.
- **Settings kept per user, outside the repo today:** `%APPDATA%\varimu\app.json`
  (`prefs.rs`: source folders, input normalization, each keyboard's touch, the devices
  played with the precise solver, the devices heard through their speakers),
  `sampler.json` (the sampler's kit) and `recording.json` (the Session view's prefs).
  None of them holds a panel.
- **What else shapes the sound in the Play view:** the chain end and its knobs
  (`play_view.rs`'s `end_knobs`, `Player::set_end_values`), the quality, Noise, Precise
  solver, Hear the speakers, the input trim. For devices with a unit, the unit's own
  controls are knobs too (the Clavinet's UNIT # and AGE, the Suitcase's IMPERFECTION and
  UNIT #).
- **Some knobs restart the stream.** A change of structure (a section's `when:` gate,
  OSC ON / SAW ON, a selector that rewires) restarts a live stream instead of updating it
  in place; value changes update in place.

## Decisions

1. **Everything in the repo (the user's, 2026-11-25).** Presets live in the repo, not in
   `%APPDATA%`. The user's own presets go in `presets/<device>/<name>.json` at the repo
   root; factory presets in `config/presets/<device>/<name>.json` (decision 3).
2. **The user's presets are committed** (proposed; the user's call). They are small
   text, the user's own sounds, and git gives them history for free. The app never
   commits; it only writes the files. The alternative is a git-ignored `presets/` like
   `sessions/` and `samples/`.
3. **Factory presets carry sources.** A factory preset reproduces a documented setting
   (a manual's patch chart, a service manual's factory adjustment), and as every value in
   `config/` it says where it comes from: a `source` (a manual's page, `web: <url>`), never
   invented. Factory presets are read-only in the app ("Save as" makes a copy of yours).
4. **One format for both: JSON**, written and read by the app (serde_json, already a
   dependency), the factory ones with their `source` field required.
5. **The last state per device is not a preset.** Each device reopens as you left it, kept
   in `presets/.state/<device>.json`, git-ignored (it changes with every knob move, so it
   would churn the history).
6. **What a preset includes by default** (open, the user's call). Proposed: the knobs
   always; the Play settings (wave, range mode, velocity range, retrigger, low-note) on by
   default; the chain end and the solver / speakers / noise switches off by default; each
   a checkbox in the Save dialog, remembered per device.
7. **The rest of the per-user settings** (open, the user's call): with decision 1's rule,
   `app.json`, `sampler.json` and `recording.json` could move into the repo too (a
   git-ignored `settings/`, or committed). Not part of this plan unless the user says so;
   PR6 is where the sampler's kit would become a preset if it moves.

## The format

```json
{
  "format": 1,
  "device": "tube_synth",
  "name": "Fat bass",
  "saved": "2026-11-25",
  "circuit": {"file": "tube_synth", "controls_sha256": "…"},
  "values": {"cutoff": 0.33, "range": "AUTO", "osc_on": 1, "lfo_on": 0},
  "playing": {"wave": "off", "velocity_db": 18.0, "retrigger": true, "low_note": false},
  "chain_end": {"device": "plate_reverb", "values": {"decay": 0.5}, "wet": 0.3},
  "switches": {"noise": true, "precise_solver": false, "speakers_heard": false},
  "tags": ["bass"],
  "notes": "",
  "source": "factory presets only: where the setting comes from"
}
```

- `device` is `panel::Device::id`; a drawing played from the editor is
  `drawing:<name>`.
- `values` are the **knobs' values**, not `panel::values`' output: a range switch is saved
  as its mode (AUTO, LOW, HIGH), not as the 0 / 1 the circuit gets.
- `playing`, `chain_end` and `switches` are optional; absent, loading leaves those
  settings as they are.
- `controls_sha256` is the hash of the circuit file's `controls` block when saved; it
  tells when the panel has changed since (below).
- File names are the name's slug (`fat_bass.json`); the name itself is in the file.

## Loading a preset onto a changed circuit

Circuits change all the time (new knobs, renamed keys, new versions), so a preset never
fails to load; it says what drifted:

- a knob the preset doesn't mention gets its default;
- a key the panel no longer has is ignored;
- a value out of a knob's range is clamped, a choice not in the list falls back to the
  default;
- each of these is listed in a note under the preset bar ("2 settings no longer exist:
  …; 1 clamped: …"), and a changed `controls_sha256` with nothing to report says nothing.

Re-saving the preset writes it against the current panel.

**One rebuild per recall.** A preset is applied in one `Player::set` (and one
`set_end_values` for the chain end), so a load restarts the stream at most once, never
once per knob.

## Milestones

### PR1: the format and the store

`varimu_app::presets`: list, load, save, rename and delete a device's presets (the user's
and the factory's, the factory's read-only); the tolerant apply above, returning the new
knobs and the notes; the last state (decision 5). The repo root is found as the app
already finds `config/` and `sessions/`.

**Done when:** every device in `panel::DEVICES` saves its default panel and loads it back
equal; a preset with a missing key, an extra key, an out-of-range value and a stale
choice loads with exactly those four notes; tests on a scratch folder.

### PR2: the preset bar in the Play view

At the top of the panel: the preset's name in a dropdown (yours, then the factory's), ◀ ▶
to step through them, Save, Save as (with decision 6's checkboxes), Rename, Delete, a ●
when the panel differs from the loaded preset, and Revert. Each device reopens at its last
state.

**Done when:** tweak tube_synth, save, switch to another device and back, load: the panel
and the sound are the saved ones, with one restart at most (Live's restart log);
stepping through presets while playing has no dropout beyond a restart's.

### PR3: compare and undo

- **A / B compare**, as on a hardware synth: two working slots per device to flip between
  while tweaking, nothing saved until asked. The flip is loudness-matched (the Hard rules'
  "loudness lies"): the B slot's level is matched to A's over the last few seconds.
- **Panel undo / redo** (Ctrl+Z / Ctrl+Y on knob moves, a drag one step).

**Done when:** A / B flips the panel and its sound in one restart at most, matched
within 0.5 dB LUFS; undo walks back a session of tweaks to the loaded preset.

### PR4: takes and inserts

- A MIDI take's panel loads into the Play view ("Panel from this take") and saves as a
  preset ("Save take's panel as preset"), from its `Performance::values` and `playing`.
- The Session view's insert panels get the same preset bar: a preset made in the Play view
  loads onto an insert of the same device. Loading changes the insert's print key, so the
  insert re-prints when asked (SESSION_EDITING_PLAN.md SE1: nothing prints until asked).

**Done when:** a take's panel saved as a preset reloads as the take's start values; an
insert loads a Play view preset and its print key changes accordingly.

### PR5: factory presets

Device by device, as sources turn up, each preset citing its page:

- the Minimoog: the Model D operation manual's sound charts;
- the 670: the manual's factory adjustment and its Time Constant settings;
- the Pultec EQP-1A: the manual's settings (and the boost-and-cut trick where a source
  documents it);
- the Novachord: Hammond's tone-selection chart;
- the others as their manuals give settings.

**Done when:** each factory preset loads with no notes on its current circuit, its
`source` is filled, and a test loads every file under `config/presets/`.

### PR6: finding and recalling

Tags and notes per preset, a search box in the dropdown, and MIDI program change
recalling presets from the keyboard (in the dropdown's order). If decision 7 moves
`sampler.json`, sampler kits become presets of the device `sampler` here.

**Done when:** a program change from the MasterKey loads the matching preset live.

### Later (unordered, nothing promised)

- **Recall sheets:** a preset exported as a picture of the panel with every knob's
  position, as a period studio's recall sheet or a Moog patch sheet; printable, or kept
  beside a mix.
- **Morph:** a slider between two presets moving every continuous knob together
  (switches and choices flip at the midpoint, a restart each). Heard live only where the
  knobs update in place.
- **Nudge:** small random moves of every knob around the current preset, inside each
  knob's range (realistic first; bending past it is a separate, deliberate control), from a
  seeded generator so a nudge can be repeated.
- **Unit or patch:** for devices with a unit (UNIT #, AGE, IMPERFECTION), a "patch only"
  load that leaves the unit's controls as they are, so a patch plays on whatever unit is
  loaded.

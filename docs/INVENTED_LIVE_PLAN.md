# The invented instruments, playable live (plan, 2026-11-21)

The user, after hearing the seven sketches of INVENTED_DEVICES.md's "Second brainstorm"
(`reports/invented/`): "these are all amazing... let's get these playable in the app,
realtime if possible and built properly." Multiple sessions; the decisions were delegated
(each is written here as **decided** so the user can overrule it).

## What "built properly" means here

The project's pattern for a keyed instrument (the harp, the Wurlitzer's reeds, the Clavinet's
strings, the Nickel Organ's keys) is followed:

1. **A Python reference** that plays a performance (note on / off, velocity, pedal and
   controllers at their samples), streaming, from the sketch's physics. The sketches in
   `varimu/invented/` become references; the sketches' renders stay as they are.
2. **A circuitsim medium** (`crates/circuitsim/src/<name>.rs`) on the generic keyed machinery
   (`keyed.rs`), agreeing with the reference to ~-120 dB on a performance
   (`crates/circuitsim/tests/<name>.rs` and a pytest through the PyO3 binding).
3. **A component** `NAME@1` (`config/components/<name>/1.yaml`, its own kind) holding the
   physical values with their sources, pinned by the circuit.
4. **A part in both builders** (Python `varimu/circuit/builder.py`, Rust `varimu-circuit`),
   bit for bit (`tests/agreement.rs` fixtures).
5. **A circuit file** `config/circuits/<name>.yaml`: the medium plus what reads it (for now a
   simple output stage at the instrument's full scale; pickups and tube preamps are later
   bends, the "realistic first, then bend" rule).
6. **An app device** (`varimu-app` `panel::Device`): MIDI keys, velocity and controllers
   mapped to the physical controls, event takes, renders, a chain end like every keyed
   instrument; its load measured (`examples/play.rs`).

**Decided:** each acoustic instrument is a keyed medium; the Arc Organ is a new **device
kind** (`arc`, the Mayr / Ayrton arc) in a real circuit, because it is one (both builders,
SPICE, a Python reference, circuitsim: the Hard rules' two implementations).

**Decided:** the media run at the stream's own rate (the project's 96 kHz internal rate at
draft-1x / draft-2x), not the sketches' 48 kHz; numerics that depended on the rate (the
zither's grid, the arc's substeps) are re-derived from it.

## Milestones (in order)

Each milestone's done-when: plays from a MIDI keyboard in the app without dropouts at a
50 ms buffer with ~12 keys (or its stated polyphony), its Rust medium within -120 dB of the
reference on a recorded performance, its tests, and a render of the sketch's demo through
the app's path.

| | Instrument | Voice | Controls (decided) | Cost estimate |
|---|---|---|---|---|
| IL1 | Rosin Wheel Organ | ~6 bar modes + a scalar friction contact | velocity -> press force, aftertouch -> force live, mod wheel -> WHEEL SPEED | tiny |
| IL2 | Buzz Zither | FD string (~370 points at 96 kHz) + implicit bridge contact | velocity -> pluck amplitude; JAWARI knob; drone strings on a pedal | ~3-6 % of a core per ringing string |
| IL3 | Rijke Organ | 8 Galerkin modes + a delay line, gauze lag | velocity -> heater power; aftertouch -> heater | tiny |
| IL4 | Aeolian Keyboard | ~40 string modes + 6 wake oscillators | mod wheel -> WIND; velocity -> slot opening | small |
| IL5 | Bubble Organ | bubble events in closed form | velocity -> flow (pitch bends flat); STRUCK / HELD mode | tiny |
| IL6 | Siren Organ | rings on one shaft + bellows (global state) | mod wheel -> SPEED; stops FLUTE / REED | tiny |
| IL7 | Arc Organ | device kind `arc` in a circuit, condensers keyed | CURRENT, SPEAK, ARC GAP knobs; mono (a duet = two arcs) | a small circuit |

**Decided order:** IL1 first because its voice is the simplest and it sets up the shared
plumbing every later one reuses; IL2 next (the likeliest favourite); the rest in table
order. The user may reorder.

## Shared work (IL0, done with IL1)

**Decided: one generic IR element, `invented_keys`**, for every acoustic instrument (the
per-instrument glue of a keyed medium is ~550-650 lines over ~20 files; one element saves
300-400 of them per instrument after the first). Its fields: `name, out, instrument, data,
sha256, rate_hz, max_keys, k0, k1, k2, k3`. `instrument` names the voice kind, `data` +
`sha256` the compiled keyboard (a component of kind `invented_keys`), and `k0`-`k3` are the
panel (0-1, each instrument saying what they are; they play on, optional in a circuit file
and 0 when absent). It senses nothing and drives `out` a sample late, like `nickel_keys`.

## How to add the next instrument (the recipe IL1 set up)

1. **Reference:** `varimu/invented/keys/<name>.py`, written like `rosin.py`: `model()` gives
   the data dict (with `"instrument": KIND` and `"source"`), and a `Voice` class with
   `asleep / on(vel) / off / pedal(down) / pressure(v) / step() -> float`, in plain scalar
   Python. Its arithmetic must be in the Rust's exact order: sums in a loop, no numpy in the
   step. Shared pieces are in `common.py` (`Gauss`, `key_seed`, `bandpass`, `modal_step`,
   `play`).
2. **Register it** in `varimu/invented/keys/compile.py`'s `models()` (component name ->
   `model`), then run `uv run python scripts/compile_invented_keys.py` to save `NAME@1`.
3. **Rust:** in `crates/circuitsim/src/invented.rs`, add:
   - a `Model` variant and its serde struct;
   - its arm in `Model::from_json` and `notes()`;
   - a voice struct;
   - a `Voice` variant, and its arms in `awake / set_knobs / event / step / silence` and
     `voices()`.

   Nothing else in circuitsim changes.
4. **Agreement test:** in `tests/test_invented_keys.py`, a performance through
   `circuitsim.invented_render` against `common.play` with the reference (target:
   bit-exact or < -120 dB).
5. **Circuit file:** `config/circuits/<name>.yaml` (copy `rosin_wheel.yaml`). Then run
   `uv run python scripts/export_app_fixtures.py` and
   `cargo test -p varimu-circuit --release --test agreement`.
6. **App:** a `Device` in `crates/varimu-app/src/panel.rs`:
   - copy `rosin_wheel`'s, with `mod_wheel` naming a control;
   - bump `DEVICES`' length;
   - add it to the menu-order test.

   Then a test in `crates/varimu-app/tests/live.rs` (copy
   `the_rosin_wheel_plays_from_note_events`).
7. **Measure:**
   - the load: `cargo run --release -p varimu-app --example play -- --device <id>
     --strike-all 100 --for 8 --mute`. Its gain and out columns are meaningless for keyed
     instruments (gain compensation chases the silent input); read load and dropouts.
   - the level: `uv run --extra fast --extra listen python scripts/invented_live_render.py
     --only <name> --quality draft`, after adding a demo phrase to its `DEMOS`. This sets
     the circuit's output full scale.

## Status

### Session 1 (2026-11-21): IL0 and IL1 built

- **Built:**
  - `varimu/invented/keys/` (`common.py`, `rosin.py`, `compile.py`) and
    `scripts/compile_invented_keys.py` -> `ROSIN_WHEEL@1`;
  - `crates/circuitsim/src/invented.rs` (the medium on `keyed.rs`), the IR element
    `invented_keys` in circuitsim (ir / media / mna / stream) and both builders (Python ir /
    parts / builder / spice / preflight / kicad symbols; Rust varimu-circuit builder /
    devices / symbols / preflight);
  - the binding `circuitsim.invented_render`, `config/circuits/rosin_wheel.yaml`, the app's
    `rosin_wheel` device, and `scripts/invented_live_render.py`.
- **Agreement:** the Rust medium is **bit-exact** with the Python reference on a
  performance (overlapping keys, a re-strike of a ringing bar, aftertouch, the pedal), and
  the same on 0 and 3 worker threads (`tests/test_invented_keys.py`). Rust builds
  rosin_wheel's IR bit for bit (`agreement.rs`).
- **Live:** every key struck at velocity 100 (16 sounding, the cap) runs at 13-17 % worst
  block, 0 dropouts at a 30 ms buffer (`examples/play.rs --strike-all`). The app's test
  `the_rosin_wheel_plays_from_note_events` covers the knobs playing on, a key sounding and
  aftertouch.
- **Found:** a held bar takes ~3-4 s to reach its stick-slip limit cycle. The friction
  curve's slope against the bar's mass gives a growth time constant of ~0.7 s, from the
  catch, ~5 mm/s, to ~0.25 m/s (the wheel's speed). So short notes are much quieter than
  held ones: a slow swell, as in the sketch. Full scale 4 V. **Option for the user:**
  lighter bars (e.g. 4 x 12 mm: ~5.7x less mass at the same pitch) speak ~5x faster; that
  is a new component version.
- **Not done yet for IL1:**
  - the user's first play;
  - a pass over the mod wheel's feel (WHEEL 0.1-0.5 m/s);
  - the touch range: `Circuit::key_velocity_span_db` has no law for this element, so the
    Play view's Touch sliders don't know its span.

**Next:** IL2, the Buzz Zither (the FD string with the implicit bridge contact; the
recipe above; the drone strings on the pedal or a key range), then IL3-IL7 in the table's
order.

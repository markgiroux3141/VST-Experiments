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
   Python. Its arithmetic must be in the Rust's exact order: sums in a loop, no numpy
   reductions in the step. Elementwise numpy (`2.0 * u - c1 * u1`, slices) is exactly
   rounded, as Rust's scalar loop is, so a grid's update may be vectorized (the zither's
   string). Shared pieces are in `common.py` (`Gauss`, `key_seed`, `bandpass`, `modal_step`,
   `play`). A voice that the pedal or pressure must wake (the zither's tanpura) says so with
   `KeyVoice::wakes_on_broadcast` in the Rust; keyed.rs skips asleep voices otherwise.
2. **Register it** in `varimu/invented/keys/compile.py`'s `models()` (component name ->
   `model`), then run `uv run python scripts/compile_invented_keys.py` to save `NAME@1`.
3. **Rust:** in `crates/circuitsim/src/invented.rs`, add:
   - a `Model` variant and its serde struct;
   - its arm in `Model::from_json` and `notes()`;
   - a voice struct;
   - a `Voice` variant, and its arms in `awake / set_knobs / event / step / silence` and
     `voices()`.

   Also add its arm in `Model::velocity_span_db` (what velocity sets, for the Play view's
   Touch sliders). Nothing else in circuitsim changes.
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

### Session 2 (2026-11-21): IL2 built

- **Built:** `varimu/invented/keys/zither.py` (the reference), the zither's voice in
  `invented.rs` (`JawariString`, `ZitherVoice`), `BUZZ_ZITHER@1`,
  `config/circuits/buzz_zither.yaml`, the app's `buzz_zither` device, its demo in
  `scripts/invented_live_render.py` (`melody_over_tanpura`: the sketch's melody over the
  pedal's tanpura; demos may hold the pedal now).
- **Shared:** `keyed.rs`'s `KeyVoice::wakes_on_broadcast` (default false: every other
  medium bit for bit unchanged); `invented::Model::velocity_span_db`, read by the app's
  `key_velocity_span_db`, so the Touch sliders know both instruments' laws (IL1's open
  item: the rosin's press force spans 19.9 dB, the zither's pluck force 19.4 dB).
- **Agreement:** bit-exact with the reference on a performance (a re-pluck of a ringing
  string, a release, the tanpura on the pedal at a raised tonic, the jawari's contact), and
  the same on 0 and 3 worker threads (`tests/test_invented_keys.py`; also: JAWARI 0.6 keeps
  the energy above 1.5 kHz >6 dB over a sharp bridge a second after the pluck, the sketch's
  finding). Rust builds the circuit's IR bit for bit (`agreement.rs`). The app's test
  `the_buzz_zither_plays_from_note_events`.
- **Live:** cheaper than estimated. 16 strings ringing in the bass (C2 up, ~360-720 points
  each) run at 18 % load, worst block 27 %; every key struck with the pedal down (the top 16
  and the tanpura) 18 %, worst block 30 %; 0 dropouts at a 30 ms buffer.
- **Level:** full scale 6 V. A pluck at velocity 127 peaks 1.0-1.3 V on any string; a
  six-note chord struck at once 5.7 V; the demo -14.5 dBFS peak.
- **Decided (IL2):**
  - **Strings C2-C6** (49 keys), each a finite-difference string on the stream's 96 kHz grid,
    which is the sketch's own (48 kHz x 2): h = c k / 0.98, so ~0.98 fs / (2 f0) points
    whatever the length. Lengths 1 m at C3 as 1 / f, capped to 0.2-1.4 m (the sketch's
    formula gave 2 m at C2).
  - **Velocity is the finger's force** (0.1-1 N, linear), not the pluck's displacement: the
    displacement law made the short, tense treble strings ~30 dB louder at the bridge than the
    bass (bridge force T A / p). With A = F p (L - p) / (T L) the bridge feels ~F (1 - p / L)
    on every string.
  - **A pluck replaces the string's state** (the finger catches a ringing string and plucks
    it again); a key up drops the felt damper (sigma0 x 60, the sketch's), the voice sleeps
    1 s later. No sustain pedal for the keys.
  - **The sustain pedal runs the tanpura's cam** (the plan's "drone strings on a pedal"):
    four more strings (Pa, Sa, Sa, low Sa) on notes 0-3, which no key plays, plucked in turn
    every 0.95 s (the sketch's cycle), damped by the cam's felt when the pedal lifts. The cap
    on voices never silences them (it then lets up to four more keys sound).
  - **The panel:** JAWARI (k0; the mod wheel), the bridge's drop 6 um / JAWARI over its
    12 mm (the sketch's best, 10 um, at the default 0.6; 0 a sharp bridge, no contact; the
    old linear map put the sharp bridge next to the flattest); PLUCK POINT (k1, 0.1-0.5 of the
    length); DRONE (k2, the cam's pluck force 0-0.45 N); DRONE TONIC (k3, Sa C3-B3 in
    semitones, each drone string re-strung at its next pluck).
  - **The soundboard in each voice:** the sketch's four body resonances as RBJ band-passes
    (scipy's `iirpeak` in the sketch), read off the bridge force by a piezo at 1 V/N
    (provisional).
- **Not done yet for IL2:** the user's first play; the cotton thread (the jawari's tuning aid)
  and sympathetic strings (the sketch's "next if picked"); per-key variation (every string
  is nominal).

### Session 2, continued: IL3 built

- **Built:** `varimu/invented/keys/rijke.py` (the reference), `invented.rs`'s `RijkeVoice`,
  `RIJKE_ORGAN@1`, `config/circuits/rijke_organ.yaml`, the app's `rijke_organ`, its demo
  (`melody_over_drone`: the sketch's legato melody over a D3).
- **Agreement:** bit-exact with the reference on a performance long enough for two pipes to
  start and fall silent (aftertouch, the pedal holding a released key's heater, then
  lifting; GAUZE off the sketch's place). `test_a_rijke_pipe_starts_late_and_holds_below_its_start`:
  a pipe blooms 0.3-1.5 s after its key, sings on with its heat lowered from K 0.60 to 0.36,
  and a pipe heated at 0.36 from the first never starts.
- **Live:** every key struck with the pedal down (16 pipes heated) 11 % load, worst block
  14 %, 0 dropouts at 30 ms.
- **Level:** full scale 6 V. A pipe at velocity 127 peaks 0.8 V on any key, at velocity 1
  0.5 V; six at once at 127 4.3 V; the demo -11.2 dBFS peak.
- **Found:** at 96 kHz the start (the subcritical Hopf point) is at K ~0.40, not the sketch's
  ~0.55 at 48 kHz: the lag tau / dt rounds to a different number of samples, and the
  breath's noise is now a one-pole (the sketch's: a 2nd-order Butterworth). Every key sounds
  at HEAT >= 0.5 (K 0.6-1.2); at HEAT 0, soft keys (K 0.30-0.40) stay silent, as a weak
  heater would.
- **Decided (IL3):**
  - **Pipes C2-C6** (2.6 m-0.16 m), the sketch's eight modes, King's law and constants; the
    lag a delay line of round(tau / dt) samples at the stream's rate (C6 +13 cents, the
    rounding; the rest within ~1 %).
  - **Bores scaled as 1 / f** (area; the diameter halves every second octave), so every
    pipe radiates alike: the outflow's derivative alone put C6 24 dB over C2. Organ builders'
    normal scale halves the diameter at the 17th note, a little steeper.
  - **Velocity is the heater's power** K 0.6-1.2 (the sketch's key 0.8), aftertouch adds up
    to 0.4, the pedal holds released keys' heaters on (no damper: a pipe falls silent as its
    gauze cools, ~0.7 s after the heat goes).
  - **The panel:** HEAT (k0; the mod wheel) 0.5-1.5x, GAUZE (k1) the gauze's place 0.15-0.45
    of the pipe (a stop of gauzes; 0.29 the default), BREATH (k2) the plume's turbulence 0-4x.
  - **The sound:** the ends' outflow differentiated by a backward difference (the sketch's
    `np.gradient`, a central one, can't stream), at 2e-4 V per unit at A3's bore (~0.5 V rms a
    held pipe; a microphone, provisional).
- **Not done yet for IL3:** the user's first play; the thermophone choir (I7's variant);
  per-pipe variation.

### Session 2, continued: IL4 built

- **Built:** `varimu/invented/keys/aeolian.py` (the reference), `invented.rs`'s
  `AeolianVoice` and `Chest`, `AEOLIAN_KEYBOARD@1`, `config/circuits/aeolian_keyboard.yaml`,
  the app's `aeolian_keyboard`, its demo (`melody_over_drone`: the sketch's melody over A2 +
  E3 at the nominal wind).
- **Shared:** `keyed.rs`'s `KeyVoice::chunk_start` (the internal sample a chunk starts at,
  given to a voice before it renders; default nothing: other media unchanged), and the
  reference's `common.play` sets `voice.now` before each step. A voice struck mid-chunk sets
  its clock from the chunk's start plus its render's offset.
- **Agreement:** bit-exact with the reference (two strings, one struck mid-chunk; aftertouch;
  the pedal; the chest's gusts), and the same on 0 and 3 worker threads.
  `test_the_wind_picks_the_harmonic`: 2.5 m/s speaks the 4th harmonic, 3.6 m/s the 6th (the
  sketch's finding; 1.5 m/s here speaks the 2nd, the sketch's the 3rd).
- **Live:** the costliest invented voice so far. 12 strings in the bass (the cap) 29 % load,
  worst block 41 %, 0 dropouts at 50 ms; with the cap at 16, 16 bass strings ran 36 %, worst
  block 52 % at 30 ms, and bursts of six strikes peaked at 93 % (the medium rendering ahead
  for every newly woken string at once).
- **Level:** full scale 10 V. A string at velocity 127 and the nominal wind peaks 1.5-3.2 V
  at its lock-in (rms ~0.4-0.6 V), up to 5.5 V at 5 m/s; six at once 12 V at the lock-in; the
  demo -6.3 dBFS peak.
- **Decided (IL4):**
  - **Strings C2-C6**, all 0.7 m, diameters voiced so 2.5 m/s speaks the 4th harmonic
    (1.9 mm at C2, 0.12 mm at C6; the treble finer than real gut).
  - **Modes to the 40th harmonic** below 14.4 kHz (the sketch's 63 at 48 kHz: ~35 % of the
    cost, the wind locks to the 2nd-8th), and **each segment's turbulence drawn every 8th
    sample** (a one-pole at fs / 8, held: the Gaussians were a large share of the cost).
  - **The wake substepped where omega h > 0.5**: C6 at 5 m/s with full gusts diverged
    (omega h ~1 at ~9 m/s on a 0.12 mm string); one step everywhere else.
  - **The chest's gust is shared:** a smooth noise of absolute time (value noise on a seeded
    Gaussian lattice every half period of 1.5 Hz, smoothstep between), so a chord wavers
    together; each segment's 30 Hz turbulence is the key's own.
  - **Velocity is the slot's opening** 0.3-1 (the jet's width along the string, i.e. the
    lift: the chest's pressure sets the jet's speed through any opening, so velocity is
    loudness, not pitch); aftertouch opens it the rest of the way; the pedal holds released
    keys' slots open; the felt damper (Q 30) falls once a slot is shut, the voice sleeps 1 s
    later.
  - **The bridge piezo voiced per string as f1 / 220 Hz** (the lift goes as the diameter,
    1 / f1: unvoiced, the treble fell ~6 dB an octave), 300 V/N at A3.
  - **The panel:** WIND (k0; the mod wheel) 1.0-5.0 m/s, GUST (k1) the blower's gusts 0-0.25.
  - **The cap at 12 strings**, not 16.
- **Not done yet for IL4:** the user's first play; a second slot height per key (the
  sketch's "choose the harmonic per key"); the soundboard as modes.

**Next:** IL5, the Bubble Organ, then IL6-IL7 in the table's order.

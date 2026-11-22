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
   `KeyVoice::wakes_on_broadcast` in the Rust; keyed.rs skips asleep voices otherwise. State
   every key shares that follows the events alone (the Siren Organ's shaft and bellows) is a
   `shared` object in the reference (`common.play`'s) and `KeyVoice::prepare` in the Rust,
   stepped per chunk before the voices into buffers they read (`invented::Shaft`).
   **Check evenness first:** play C2, A3 and C6 at velocity 127 and 1 through the
   reference before compiling. Every sketch so far was 20-30 dB uneven across the keyboard,
   and each needed a physical voicing (IL2-IL5's "Decided").
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

### Session 2, continued: IL5 built

- **Built:** `varimu/invented/keys/bubbles.py` (the reference), `invented.rs`'s
  `BubbleVoice` and `Bubble`, `BUBBLE_ORGAN@1`, `config/circuits/bubble_organ.yaml`, the
  app's `bubble_organ`, its demo (`single_bubbles`: the sketch's struck tune and chords).
- **Agreement:** bit-exact with the reference in both modes (STRUCK: single bubbles, a
  chord, their pops; HELD: streams, aftertouch, the pedal holding a valve, then lifting).
  `test_a_bubble_bends_flat_with_the_flow`: a struck A4 rings within half a semitone of its
  key at velocity 64, and 2.5-3.8 semitones flat at FLOW 1.6x.
- **Live:** every key streaming with the pedal down 14 % worst block, 0 dropouts at 30 ms.
- **Level:** full scale 8 V. A bubble struck at 127 peaks 1.1-1.2 V on any key, at velocity
  1 0.4 V; six at once 6.2 V; HELD at full FLOW and RATE a bass stream 6 V; the demo
  -12.0 dBFS peak.
- **Decided (IL5):**
  - **Nozzles C2-C6**, each at depth max(8 cm, 3 r) (the bass's 5.5 cm bubbles need room to
    rise: C2 at 17 cm) and voiced so the pitch at pinch-off is the key's with the surface's
    image included (the sketch voiced without it: its bass rang sharp).
  - **Velocity is the air flow** over 0.9-1.1 (in tune at velocity 64, +-3/4 semitone; the
    sketch's swell 0.7-1.4 put velocity 100 ~9 % flat); aftertouch adds up to 0.4 (bends ~2.5
    semitones flat), FLOW (k1; the mod wheel) scales it 0.6-1.6x. r ~ q^0.4, the held rate ~
    q^0.8 (the sketch's laws).
  - **MODE** (k0, a switch): STRUCK releases one bubble a key (excitation 0.5 + velocity, the
    sketch's), HELD streams while the key or the pedal holds the valve (RATE, k2, 3-24 Hz;
    interval and size jitter the sketch's). DEPTH (k3) scales the nozzles' depths 0.5-2.5x.
  - **The hydrophone voiced per nozzle** as r(A3) / r (a bubble's pressure goes as its
    radius: unvoiced, C2 rang 25 dB over C6), 50 V per unit at A3.
  - **Bubbles in closed form, streamed:** up to 16 per key (a new one takes the first free
    slot, else the oldest's); the envelope as two decaying exponentials; the pop band-passed
    by an RBJ band-pass at 3.2 kHz, Q 0.59 (the sketch's 1.5-7 kHz Butterworth).
- **Not done yet for IL5:** the user's first play; per-nozzle variation.

### Session 3 (2026-11-21): IL6 built

- **Built:** `varimu/invented/keys/siren.py` (the reference: `Valve`, `Shaft`, `Voice`),
  `invented.rs`'s `SirenVoice`, `Valve` and `Shaft`, `SIREN_ORGAN@1`,
  `config/circuits/siren_organ.yaml`, the app's `siren_organ`, its demo
  (`harmonic_melody_and_chord`: the sketch's harmonic melody, then its 4:5:6:7 chord entering
  a key at a time).
- **Shared:** `keyed.rs`'s `KeyVoice::prepare(ctx, start, n, events)`: called on the calling
  thread before a chunk's voices render, with the chunk's events at their offsets (default
  nothing: every other medium bit for bit unchanged, its tests and the five instruments' agreement
  rerun). `invented.rs`'s context is now `Ctx { knobs, shaft }`. The reference's `common.play`
  takes a `shared` object (its `event` gets every event, its `step` runs once a sample after
  them, before the voices).
- **Agreement:** bit-exact with the reference on both stops (three keys overlapping, two struck
  mid-chunk, aftertouch, the pedal holding a released valve, then lifting, a re-strike;
  off-centre SPEED / WIND / MOTOR), and the same on 0 and 3 worker threads.
  `test_a_chord_drags_the_shaft_and_the_wind`: one key at full opening runs the shaft at its
  nominal speed within 0.5 cent; three more pull every pitch down 59 cents (MOTOR 0.25: 107;
  MOTOR 1.0: 16); the idle shaft runs 20 cents sharp; the wind 894 -> 712 Pa (a bass chord: 342
  Pa).
- **Live:** every key struck (24 rings sounding, the cap) 16-17 % load, worst block 21 %, 0
  dropouts at 30 ms.
- **Level:** full scale 8 V. A key at 127 peaks 1.4-1.6 V on any key and either stop (FLUTE rms
  ~1 V, REED ~0.3 V: narrow holes, no chamber), at velocity 1 0.3 V; six at once 5.2 V, eight
  6.7 V; the demo -7.0 dBFS peak.
- **Decided (IL6):**
  - **The shared state exact, not a chunk late** (none of the open design's three options):
    the motor and the bellows depend only on the valves, and the valves only on the events, so
    the medium steps the shaft per sample over the chunk before the voices render, into
    per-sample buffers (the shaft's angle, the jet's speed) every ring reads. Exact coupling,
    independent of where chunks start, the same on any number of threads; costs one valve step
    per key per sample on the calling thread (small). A key silenced by the cap still draws on
    the shaft while held.
  - **The keyboard is the harmonic series on A** (C2-C6): each pitch class a harmonic 16-30 of a
    3.4375 rev/s shaft (A 16, A# 17, B 18, C 19, C# 20, D 21, D# 22 (the 11th, ~half a semitone
    flat), E 24, F 25, F# 27, G 28 (the 7th, -31 cents), G# 30), each octave doubling the holes
    (C2 19, A3 64, C6 304). The sketch's 13.75 Hz shaft (A3 = 16) gave duplicates below A3;
    the shaft's dynamics are normalized, so the slower shaft keeps the sketch's sag.
  - **One key at full opening is in tune at any MOTOR** (the sketch's: the no-load speed
    `w_nl` from the motor's slope); the idle shaft runs ~20 cents sharp, so a staccato note
    scoops down ~0.35 s (the siren's character; MOTOR sets how far).
  - **Velocity is the valve's opening** 0.2-1 (13.6 dB), aftertouch opens it the rest of the
    way, the pedal holds released keys' valves; valves open over 12 ms and close over 20 ms
    (the sketch's); a key sleeps 0.3 s after its valve shuts.
  - **The ring's area voiced as 1 / holes** (the radiated pressure goes as dU/dt, so the
    sketch's sqrt(16 / holes) left the treble ~6 dB an octave over the bass): FLUTE within 1 dB
    C2-C6.
  - **The turbulence's band as the holes** (4 kHz at A3's ring; 2nd-order low-passed noise,
    unit rms): every ring at the sketch's one radius, so a slot's width goes as 1 / holes and the
    band (U / w) as holes. The sketch's fixed 4 kHz band put 84 % of a C2 REED's energy above 5
    kHz (8 dB over A3, crest factor ~8); now REED is within 0.5 dB C2-C6.
  - **Each ring drilled at its own angle** (its note's golden-ratio fraction of a hole pitch):
    the sketch's rings all had a hole at angle 0, so a chord's pulses lined up once a
    revolution (a 3.4 Hz accent; six keys peaked 8.6 V at 1.6 V rms, now 5.2 V).
  - **The sound:** the pressure 1 m from the ring as a monopole, rho / (4 pi r) dU/dt (a
    backward difference: the sketch's central `np.gradient` can't stream), a microphone at
    2 V/Pa (provisional). The motor's hunting and wander as the sketch's, the wander a seeded
    Gaussian lattice at 0.5 Hz (the Aeolian chest's value noise) of absolute time.
  - **The panel:** SPEED (k0; the mod wheel) the no-load speed 0.5-2x (1x at 0.5), STOP (k1)
    FLUTE / REED, WIND (k2) the blower's stall pressure 0.5-1.5x of 1000 Pa, MOTOR (k3) the
    motor's stiffness 0.25-4x. The cap at 24 rings.
- **Not done yet for IL6:** the user's first play; a SPEED glide in the demo (the demo script
  plays no knob changes; the sketch's `speed_glide_reed` is the reference); per-ring variation.

**Next:** IL7, the Arc Organ (a new device kind).

### Session 3, continued: IL7 step 1, the arc as a device kind

- **Built (ae49b3e):** a device kind **`arc`** (pins (a, s, w, b)): Mayr's arc whose steady
  state is Ayrton's law (`varimu/devices/arc.py`, the reference: d ln g / dt = (v i / P(i) - 1)
  / tau, P(i) = (a + b l) |i| + (c + d l), the sketch's strike, cap and floor), its ln g a state
  node on a 1 F capacitor (the lamp's pattern), its power out of pin w (1 A = 1 W). SPICE
  (`subckt`, `test_spice_agreement.py::test_arc_agrees` at two gaps), circuitsim
  (`devices/arc.rs`; `tests/devices.rs` on the fixtures' currents and Jacobians), both builders
  bit for bit (a per-instance `gap_mm`, as a photocell's `lux`; `agreement.rs`), the component
  `CARBON_ARC@1` (`library.build_carbon_arc`, `varimu fit-devices --only CARBON_ARC`), and
  `config/circuits/arc_test.yaml`: Duddell's arc on one condenser (110 V, a ballast for 5 A,
  0.1 H choke, 0.5 uF mica, the 4 mH tank with A4's 30.5 uF), `tests/test_arc.py`.
- **Found:** it starts on Ayrton's curve (49.576 V at 5 A) and sings at 423 Hz (the LC's 456,
  pulled ~7 % flat; draft and production agree, 423.3 Hz both, rms within 0.5 dB), 0.27 Pa rms
  at 1 m, peaks ~3-5 Pa (spiky: the strike); a tank of 2 ohm (past the arc's -1.31) never
  starts. 0.34x real time at draft, 0.68x at production (the whole circuit, no keys).
- **Decided (IL7 so far):**
  - **The sound is the arc's own** (a thermophone): its power on 1 ohm, differentiated by a
    C-R with RC = (gamma - 1) / (4 pi r c^2) (`arc.thermophone_rc_s`), so `out` is pascals at
    1 m. The readout is a third port of the device (nothing depends on its voltage).
  - **A 1 GOhm leak on the state node** (numerical; documented in arc.py): at 0 V the growth
    doesn't depend on the state, so Newton's first DC iterate from rest was singular.
  - Numerics in the model: |i| smoothed at 1 mA, the strike ramped over 5 V, the floor and the
    cap restored at 1e7 per neper; Newton limited to 1 neper and 10 V a step.
- **Next for IL7 (open, for the next session to decide and record):**
  1. **How the keys switch the condensers live.** The app reaches a circuit through control
     inputs (`panel::Feed`: gate, pitch, a key string, pressure); a value (a knob) changes in
     place only after a background build, at a block (the tube synth's RANGE AUTO: a key waits
     until the switch has moved). Options:
     - (a) a `contact` per key on its own gate input: exact, but ~49 more DK ports and 49 new
       feeds (per-key gates don't exist);
     - (b) a binary-coded bank (~12-14 contacts on bit feeds, a new `Feed`): fewer ports, a
       keyboard encoder's glitches between codes;
     - (c) a new engine element, a condenser bank whose value follows a control input (the DK
       responses rebuilt at a key's sample): exact, engine work;
     - (d) **recommended to try first:** the gate (sample-exact, `Feed::Gate`) works one
       `contact` device that closes the tank at SPEAK and opens it onto the quench resistance
       (the sketch's 200 ohm; the contact's own transition and an RC on the gate line as the
       sketch's 30 ms release), and the key's condenser is a value updated in place, asked by
       the Performer when the sounding key changes, the key waiting with its gate up until it
       has landed (RangeSwitch's pattern: `performance.rs`, `panel::RangeSwitch`; event takes
       replay it bit for bit). Measure the latency first (a small circuit builds in ~ms; the
       update lands at the next block).
  2. **The circuit** `config/circuits/arc_organ.yaml`: CURRENT (the ballast as a rheostat,
     3-9 A), SPEAK (the tank's resistance), ARC GAP (the instance's `gap_mm`: check whether a
     device parameter updates in place or restarts the stream), the hiss (the sketch's flutter:
     a `noise_source` into the state node, or the carbons' feed wandering the gap ~0.3 Hz),
     a condenser per key (C2-C6 or a smaller compass: Duddell's was about two octaves) trimmed on
     this circuit (`scripts/arc_organ_trim.py`: the sketch's trim was against its own
     numerics; the arc pulls ~7 % flat).
  3. The app device, its load and level, a demo (the recipe's steps 6-7), the done-when.

### Session 4 (2026-11-21): IL7, the Arc Organ, built

- **Built:**
  - `config/circuits/arc_organ.yaml`: the arc on 110 V through the CURRENT rheostat and the
    choke, the mica shunt, the tank (TUNE's variometer, SPEAK's rheostat, the key contact
    `ARC_KEY@1` across the 200 ohm quench resistance, the key's condenser `key_f`), the key's
    one-way dashpot on the gate, the hiss, the thermophone readout.
  - `ARC_KEY@1` (`library.build_arc_key`): a contact of 2 mOhm closed (the tank's whole
    resistance must stay under the arc's -1.3 ohm), closed above 8 V, open below 1 V.
  - The factory trim `scripts/arc_organ_trim.py [--survey | --write | --check]` ->
    `config/arc_organ_trims.yaml` (the record) and `crates/varimu-app/src/arc_organ_trims.rs`
    (the app's table): each key within 1.5 cents at the panel's defaults; `--check` hashes the
    circuit file without `key_f`, the full scale and comments.
  - The app: `panel::KeyedValue` (a value per key riding on the gate: `with_note`, `note_in`),
    `panel::KEYED_VALUES` (by device id, like `WHEEL_REVERSED`: no new `Device` field),
    `Feed::KeyedGate`; the Performer's `block_keyed`, `applied`, `positioned`,
    `with_asked_key_in` and `Block::key`; `Live::land` (the builds ready now applied before
    the block is made); the player's keys worker and `take_render` use them. The device
    `arc_organ` (draft-2x, mod wheel SPEAK).
  - Tests: `tests/test_arc_organ.py` (the trim current and in the app; E2 / A4 / C6 in tune;
    the contact gates the tank; TUNE both ways), `crates/varimu-app/tests/live.rs`'s
    `the_arc_organ_switches_its_condensers_in_place` (the player's loop: a key from silence
    waits for its condenser, then sings within 3 cents; legato keeps the gate down; a key off
    the compass is silent; nothing restarts).
  - Demos: `scripts/invented_live_render.py`'s `GATED` renders through varimu-app's
    `midi_render` example (the take renderer: the Performer and the keyed condensers as Play):
    melody, melody legato, the phrase at 3 / 5 / 9 A and at a low SPEAK, the compass ->
    `reports/invented/arc_organ/live_*.wav`.
- **Decided (IL7):**
  - **(d), measured first:** the key's condenser is a value updated in place. A key's build
    takes 0.34 ms, so it lands at the next block: from silence a key waits at most one block
    (10 ms at 48 kHz; 7.9 ms for a key 100 samples into its block). Only a device with a keyed
    value lands its ready builds before the Performer looks (`Live::land`); the range switch
    keeps its old timing, so the tube synth's recorded AUTO takes replay as heard.
  - **Legato switches the condenser on the singing arc** (Duddell's way): the gate stays down
    and the new condenser takes over when it lands (the sketch quenched every change).
    Multi-trigger's 1 ms lift can't open the contact through the dashpot.
  - **The compass E2-C6** (MIDI 40-84, 45 keys; keys outside it are silent): `--survey` finds
    the pitch following the condenser from 600 uF (73.5 Hz) to 2.5 uF (1521 Hz); at 1.8 uF and
    less the arc no longer sings (its rms 27 dB down).
  - **The contact and the release:** the open tank lies on the quench resistance (its condenser
    resting at the arc's voltage, so a key closes without a kick); the gate charges the key's
    dashpot through a diode (an electrical analog of a one-way mechanism) and it falls over 20 ms
    as the key rises: the note is gone into the hiss within 60 ms.
  - **The hiss:** a white `noise_source` across the HISS rheostat (an audio taper) drives the
    arc's state node through a `G` part: noise on the growth of ln g. Its gain calibrated to the
    sketch's idle hiss at 5 A, 22 dB under an A4 note (the white equivalent of the sketch's
    flutter came out 9 dB louder). The hiss also seeds the attack: a note builds in 50-70 ms
    (to -6 dB; ~110 ms from numerical noise alone). The carbons' feed wander (the sketch's gap
    +-0.25 mm at 0.3 Hz) is not modelled: the gap is a device parameter.
  - **TUNE, a variometer** (two 1.6 mH coils in series, their coupling 0.02-0.5, 0.25 at rest:
    the tank 3.26-4.8 mH; at A4 +158 / -136 cents). CURRENT and ARC GAP pull the keyboard
    (the arc's physics; at A4 3 A -41 cents, 9 A +85, gaps 1.2-3 mm +-10; an A3 phrase at 3 A
    and 9 A sits ~1.3 semitones flat / ~1.2 sharp), so the player retunes as with any
    instrument; the keys stay trimmed at TUNE's rest. A negative coupling isn't an IR value,
    hence the centred rotor: turned up the tank grows and the pitch falls.
  - **Velocity and aftertouch do nothing** (an organ's key is a switch). The mod wheel is SPEAK.
  - **Draft-2x** (the trim was measured at the draft's 96 kHz; the thermophone's d/dt makes the
    strikes bright). Full scale 4 Pa.
- **Found:**
  - The arc's pull grows toward the bass: 4.5 % at the top, 15 % at G3, 28 % at E2.
  - The level rises ~16 dB from E2 (0.08 Pa rms) to C6 (0.5 Pa): the thermophone's pressure
    goes as dP/dt. Not voiced (option for the user: a resonator per register, or leave it as
    the arc's own).
  - At 9 A, and at SPEAK 0, the arc barely sustains the tank (rms 18-21 dB down, a quiet
    near-sine): Ayrton's negative resistance (c + d l) / I^2 shrinks with the current. The
    "9 A hissing" demo is mostly hiss.
  - The bass's pitch wanders +-10 cents under the hiss (the halves of a 1.2 s hold).
- **Live:** a key held 18 % load (worst block 31 %); the sounding key changing 8 times a
  second (each change a build and an in-place update) worst block 52 %; 0 dropouts at 30 ms;
  0 restarts. Offline the circuit runs 0.2-0.25x real time.
- **Done-when:** plays from a MIDI keyboard path (Performer, gate, keyed value) without
  dropouts; its tests; the demos through the app's take renderer. (The -120 dB medium
  agreement doesn't apply: the arc is a device kind, checked against SPICE and the fixtures in
  step 1.)
- **Not done yet for IL7:** the user's first play; a duet (two arcs, the sketch's
  `two_arcs`); the level's evenness; the carbons' feed wander.

**IL1-IL7 are all built.** Next: the user plays them.

### After the user's first play (2026-11-21): the Rosin Wheel's LIMIT

The user: "on certain settings, holding a note can result in out of control feedback." Measured
(one bar held 12 s at velocity 127 over WHEEL / RESONATOR / TOUCH / aftertouch, five bars): no
instability and no unbounded growth; the stick-slip's limit cycle follows the wheel's speed, and
at a fast WHEEL the friction curve's slope is shallow, so a held bar swells exponentially for
5-10 s and settles at 3.1 V (RESONATOR 0.5) to 5.2 V (RESONATOR 1): one bar past the 4 V full
scale, a chord far past it.

- **Built:** LIMIT (k3, the panel's fourth knob), a check felt at each bar's free end: past its
  gap the bar rubs it (a drag of 10 N s/m on the end's velocity, engaging over a smoothstep across
  half the gap), which caps the held swing without touching the swell below it. Each bar's gap is
  v_lim / (2 pi f1) (every bar meets its felt at the same end velocity); LIMIT sets v_lim
  0.6-0.08 m/s evenly in log; 0 = no felt. In `rosin.py` and `invented.rs` (bit-exact, the felt
  engaged), `ROSIN_WHEEL@2` (its data adds the felt; `@1` reads without it and ignores k3), the
  circuit pinned to `@2`, the app's panel. Tests: `tests/test_invented_keys.py`'s agreement at
  LIMIT 0 and 1, `test_the_rosin_wheel_without_its_felt_is_version_1`, `test_limit_holds_a_held_bar`.
- **Decided:** LIMIT defaults to 0.75: the default panel's held bar 1.6 -> 1.5 V (-0.4 dB);
  at WHEEL 1 / RESONATOR 1 one held bar ~1.7 V (default touch) to ~2.1 V (pressed hard with
  aftertouch), was 5.2-5.4 V. At LIMIT 1 every held bar sits ~1 V.
- **Not done:** a chord at the fastest WHEEL can still pass the full scale (bars add); the felt's
  rub has no sound of its own.
- **Corrected the same day (`ROSIN_WHEEL@3`), after the user: "limit doesn't seem to do
  anything... a loud note still swells a lot".** `@2`'s felt engaged just under a bar's own level
  at the default panel (0.6-0.08 m/s; 1.57 V uncapped, 1.51 at 0.75), so most of the knob did
  nothing there; tuned against the fastest WHEEL alone. And at 10 N s/m hard-pressed bars that
  break into their second mode (G#3, A#3, C4, C5, ...) went past it: the same loudness swings the
  end less in mode 2. Now 30 N s/m and 0.3-0.03 m/s: a ceiling that is the same on every key and
  panel (held, one bar at 127: 1.50 V at 0.25, 0.78 at 0.5, 0.42 at 0.75, 0.22 at 1; the default
  panel 1.57 V at 0, a fast WHEEL 2.6), reached sooner the lower it is (C4 at the default panel
  1.6 s -> 1.1 s). LIMIT defaults to 0.25 (the default panel -0.4 dB; a fast WHEEL's runaway
  halved). `test_limit_sets_a_ceiling_at_the_default_panel` checks it at the default panel.
  LIMIT can't shorten the swell below its ceiling: the bar's growth time is its physics (~0.7 s,
  Session 1's "Found"; lighter bars, a new component, would speak ~5x faster).
- **Even notes, a fast attack (`ROSIN_WHEEL@4`, the user the same day: "an option for just even
  volume throughout and faster attack ... keep the variation of the sound as it plays").** The
  swell is the stick-slip growing from a bar at rest (25-35 dB at ~0.5-0.7 s a time constant), so
  a ceiling can't shorten it. With LIMIT on, the key's felt mallet now throws the bar to the felt's
  level as it goes down: a raised-cosine push at the free end lasting one period of the
  fundamental (half its impulse into the fundamental, mode 2 ~30 dB less: no click), sized so the
  fundamental starts at the lower of the wheel's speed and 1.2x LIMIT's engaging velocity; the
  stick-slip carries on from there (the rosin's texture unchanged) and the felt holds it. Measured
  (velocities 50 and 127, C2-C6, three panels): within ~1 dB of the held level by 0.2 s (the
  treble by 0.05-0.1 s; the bass -3 dB at 0.1 s: the press's 80 ms attack and its long period),
  then within +-0.3 dB; was 1.5-3.4 s to arrive. Started this way a bar settles lower than when it
  swells up (~1.0 V at LIMIT 0.25, 0.5 V at 0.5, 0.15 V at 1). **Decided:** the mallet comes with
  the felt (one mechanism: the stop sets the level, the key throws the bar to it), so LIMIT 0 is
  the free swelling bar and LIMIT's default is 0 again (the instrument as first played).
  `test_limit_makes_held_notes_even_and_early`; demos `reports/invented/rosin_wheel/
  live_melody_and_chord_limit_*.wav` through the app's take renderer.
  **Open:** at LIMIT 0.25 a held four-note chord peaks +2.2 dBFS (each bar ~1 V from the start, all
  at once; LIMIT 0.5 -3.1 dBFS): the full scale (4 V) or the even mode's levels may want a change,
  the user's call after playing it.

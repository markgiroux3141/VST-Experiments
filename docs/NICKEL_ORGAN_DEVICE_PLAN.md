# The Nickel Organ as a device

Backlogged 2026-11-06 at the user's call; **built 2026-11-10** (the user's ask: "make sure
it works just like the others"; "Status" below). It picks up from the Rust voice in
docs/NICKEL_ORGAN_PLAN.md ("The Rust voice").

## Status (2026-11-10): built

The organ is the device `nickel_organ` (Play view, Instruments), a circuit with its keys as
circuitsim's keyed medium, so it has every row the Rhodes and the Clavinet have: the SOURCE
row and touch, the monitor, Render, CHAIN END, and MIDI event takes in the Session view
(nothing in the app names it: those paths serve any circuit with a medium played by keys).

- **The medium** (`crates/circuitsim/src/nickel.rs`): a key (`Keyed`) is the voice plus the
  reference's keyboard logic (a strike's POLARIZE catch-up, running until released and
  quiet), on `keyed.rs`'s workers and summing order. `nickel::Organ` and its `Pool` are gone.
  `Voice::at_rate` steps a key at any rate (`Voice::new`: the reference's 96 / 192 kHz).
  The rates are the element's: line outs at the least multiple of the step rate at or above
  `rate_hz` (96 kHz), physics at the least multiple of that at or above `step_hz` (192 kHz).
  - **The filter question** (step 1): at 96 kHz, the device's draft-2x, k = 1 and the line
    out is the reference's own sample, every second physics step, as `voice.py` takes it: the
    medium is the reference voice bit for bit (`tests/nickel.rs`), and the whole circuit is
    within -100 dB of the Python voice (`tests/test_nickel_organ_device.py`). At 48 kHz
    (draft-1x) `keyed.rs` decimates from 96 kHz with its filter; production steps at 192 kHz,
    one physics step a sample.
  - **Power-on at load** (step 6): every key powered on when the medium is made, in parallel
    (~110 ms for 61 keys), and the powered keyboard kept per (data, rates, POLARIZE, noise
    seed), so a restarted stream costs nothing. The catch-up ramp of a frozen key struck after
    POLARIZE moved (~7 ms) still runs at its strike, on a worker thread when other keys sound.
  - **The cap** (step 6): the element's `max_keys`, 12 in the circuit (the same in renders):
    `keyed::Medium::set_max_awake` silences a released key first, else the one struck longest
    ago, decided on the calling thread (the same on any number of threads). 12 keys cost what
    8 do (two rounds over six threads: `nickel::workers` is five beside the caller; the other
    keyed media's three were too few). `keyed::Medium::set_inline_voices(1)`: the default 4
    rendered four organ keys on one thread (1.5x real time).
  - Knobs: SUSTAIN and POLARIZE reach the keys through `Medium::update` (a shared `Knobs`), from
    the first step not yet rendered (a stream renders the keys at most a few steps past the
    run, so within a few samples).
- **The IR and the part** (step 2): `NickelKeys` (name, `out`, `data`, `sha256`, `rate_hz`,
  `step_hz`, `sustain`, `polarize`, `max_keys`) and the part `nickel_keys: [out]` in both
  builders, SPICE holding `out` at 0 V, both pre-flights, a symbol (`NK`) in both tables; the
  fixtures regenerated (only `nickel_organ.json` new: no other circuit's IR moved).
- **The component** (step 2): `NICKEL_ORGAN@1` (kind `nickel_keys`, `varimu/nickel/compile.py`),
  `config/nickel/organ.live.json`'s bytes; `scripts/compile_nickel_organ.py` saves versions,
  `--check` against the latest (up to date).
- **The circuit** (step 4): `config/circuits/nickel_organ.yaml`: the keys on `out`, a 470k
  line load, the unused input loaded, SUSTAIN and POLARIZE as controls, full scale 20 V, and a
  `noise` block (each key's hiss follows the circuit's noise, the Play view's Noise switch).
- **The app** (step 5): `panel::DEVICES`' `nickel_organ` at draft-2x (`own_oscillator`); its
  touch spans the hammer's law, 21.9 dB (`live::key_velocity_span_db`); the bare instrument
  removed (`varimu-app/src/nickel.rs`, `Source::Nickel`, `work_nickel`, the Play view's
  branches); `examples/nickel.rs` plays the device (`--mute`, `--wav F` the medium offline).
- **Measured live** (`examples/nickel.rs --chord-keys 8 --mute`, a 50 ms buffer, the chord
  and a run over it up to 12 keys): 0 dropouts, worst blocks 86-94%. The bench
  (`nickel_bench`): 1-6 keys ~0.4x real time, 8-12 keys ~0.8x. Step 7 (a cheaper voice) was
  not needed.
- **Tests:** `crates/circuitsim/tests/nickel.rs` (the reference, the medium bit for bit, any
  number of threads, quiet after release, the cap, the panel), `tests/test_nickel_organ_
  device.py`, `crates/varimu-app/tests/live.rs` (`the_nickel_organ_plays_from_note_events`).

Open: the user plays it.

## Why

The Rust voice plays in the app, but as a bare instrument beside the Sampler (Play view,
device menu, Instruments, **Nickel Organ**). That path skips everything a device gets in the
Play view. The user noticed this by comparing it with the Rhodes:

- the SOURCE row (file, live input, MIDI keyboard) and the touch settings that belong to a
  device;
- the monitor: DEVICE IN, gain compensation, Output;
- Render (production);
- CHAIN END (a device after it, e.g. the plate);
- recording in the Session view as an **event take** (MIDI plus panel, re-rendered later).
  The bare instrument records audio only, as the Sampler does.

The Rhodes and the Clavinet get all of these by being circuits with a **keyed medium** inside
(`crates/circuitsim/src/keyed.rs`: the harp, the Clavinet's strings). The organ should take the
same route.

## The plan

1. **A keyed medium.** The organ's key, `circuitsim::nickel::Voice`, becomes a `KeyVoice`
   (`keyed.rs`), the way `clavinet.rs` wraps the Clavinet's strings. The voice's physics stays
   as it is; `tests/nickel.rs`'s -250 dB agreement with Python must keep passing.
   - Events are placed at their sample (`NoteEvent::On` / `Off`); a key wakes on its strike
     and sleeps once it is released and quiet (`QUIET_V` over `QUIET_S`). Frozen between
     notes, as in Python.
   - Use keyed.rs's workers and its bit-for-bit summing order. Retire `nickel::Organ`'s own
     `Pool`, or keep it only for `examples/nickel_bench.rs`.
   - The medium runs its voices at 192 kHz internally (k = 2 per 96 kHz step); keyed.rs's
     decimator takes the line out down to the step rate. Python takes every second sample,
     so decide whether the live tier filters. It should, but then the Python renders differ
     by that filter.
2. **The IR and the part, in both builders.** Add an element `NickelKeys` (name, `out` node,
   the compiled model's path pinned by sha256, `sustain`, `polarize`) and a part
   `nickel_keys: [out]`. The files to change are the same set the Clavinet's `clav_strings`
   touches:
   - Python: `varimu/circuit/{ir,builder,parts,spice}.py` (SPICE holds `out` at 0 V, as for
     the harp), `varimu/preflight.py`, `varimu/kicad/symbols.py`;
   - Rust: `crates/circuitsim/src/{ir,media,mna,stream,python}.rs`,
     `crates/varimu-circuit/src/{builder,devices,preflight,symbols}.rs`,
     `crates/varimu-app/src/live.rs`.

   Rerun `scripts/export_app_fixtures.py` and `export_circuit_fixtures.py`.
   - Consider making the compiled model a component version (`config/components/
     nickel_organ/1.yaml` pinning `organ.live.json`), like `MK1_HARP@1` and
     `D6_STRINGS@N`. `scripts/compile_nickel_organ.py` would then save versions.
3. **The panel as circuit controls.** SUSTAIN and POLARIZE become the circuit file's
   `controls`, read by the medium through `Medium::update(el)`, the way the Clavinet's wear
   sliders reach it. Per the Python reference:
   - SUSTAIN applies at once (the loop's wiper);
   - POLARIZE ramps over 20 ms, in a sounding key now and in a frozen key at its next strike.
4. **The circuit.** Add `config/circuits/nickel_organ.yaml`: the medium onto the line-out
   node, with a load (the console input's 470k is already inside the voice) and an `out`
   probe. Add its `full_scale` (the bare instrument uses 20 V at 0 dBFS; one key peaks at
   5-12 V).
5. **The app.**
   - Add a `nickel_organ` entry in `panel::DEVICES`, keyed (like `clavinet_d6`), with its
     velocity law. The Python maps velocity to hammer speed on a log scale; the touch
     curve's range should reflect that.
   - Remove the bare instrument: `varimu-app/src/nickel.rs`, `player::Source::Nickel` /
     `work_nickel`, and `play_view`'s `nickel_on`, `start_nickel`, `nickel_panel_ui` and
     `nickel_main`. Keep `examples/nickel.rs` working on the device instead.
6. **Real time, fixed on the way:**
   - **Power-on happens at load, not on the audio thread.** A key's first strike now runs its
     50 ms power-on (~18 ms of compute) inside the player's block: a likely dropout at a
     30 ms buffer. Power every key on when the device loads, in parallel (61 keys x ~18 ms).
     Or power on at load once and cache that state: it is the same for every key at a given
     POLARIZE.
   - **The same for POLARIZE's catch-up ramp** on a frozen key (~7 ms of compute at its
     strike).
   - **The voice cap.** `MAX_RUNNING` is 12, but 8 keys already take ~0.8x real time on 4
     threads (worst blocks ~100%: `cargo run --release -p circuitsim --example nickel_bench
     -- 8 3 0.75 4`). Measure the device under `examples/play.rs` and set the cap from that
     (likely 8 on this desktop). Also fix the UI text that says 12.
7. **A cheaper voice, if needed.** The cost per step is spread evenly: the tube Newton loops
   (secant pairs, 2-3 iterations each, ~30 transcendentals), JA's Langevin functions and
   about 100 divisions. Swapping in `fastmath` changed nothing. Options, each to be measured
   against the reference:
   - analytic derivatives instead of secant pairs (halves the tube work);
   - one Newton iteration warm-started from the last step;
   - tabulating the Koren shape `Phi` (as `triode_table.rs` does);
   - a 96 kHz step (oversample 1: half the cost, but a longer loop delay, so judge it by
     ear).

## Done when

- The Nickel Organ is a Play-view device with the same rows as the Rhodes: source, monitor,
  output, Render, chain end.
- It records MIDI event takes in the Session view.
- The Python and Rust builders agree on its IR (fixtures).
- The voice still agrees with Python at -250 dB.
- 8 keys play live without dropouts.

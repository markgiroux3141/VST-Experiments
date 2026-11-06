# The Nickel Organ as a device (backlog)

Backlogged 2026-11-06 at the user's call. Nothing in this doc is built yet. It picks up from
the Rust voice in docs/NICKEL_ORGAN_PLAN.md ("The Rust voice").

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

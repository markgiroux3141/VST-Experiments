# Native app: the editor, playback and render as one Rust program

Drafted 2026-10-27 from the handoff that followed circuit-sim M8's real-time
playback (`docs/CIRCUIT_SIM_PLAN.md`, M8: "Draft quality", "Draft-1x", "Real-time
playback"); decisions taken with the user the same day. It replaces the main plan's
Phase 10 lean (nih-plug with a webview editor) for the user-facing product. Work
milestones in order, each ending with its "done when" met and covered by tests, like
the main plan, [CIRCUIT_SIM_PLAN.md](CIRCUIT_SIM_PLAN.md) and
[DEVICE_BUILDER_PLAN.md](DEVICE_BUILDER_PLAN.md).

## Goal

What a user sees becomes one self-contained native Rust app with a clean GUI: no
Python and no browser at runtime.

1. **Circuit editor:** the schematic editor that is now the web page `/editor`.
2. **Playback and render as one thing:** the app plays in real time by default at
   draft-1x quality, as `/play` does. A Render action renders the same audio at
   production settings, offline with progress, and saves a WAV.

Out of scope: the research tools (blind A/B, ABX, reports, studies). They stay in the
Python / web lab. The web app keeps working.

## Decisions (2026-10-27, the user's)

1. **Standalone only.** No VST3 / CLAP plugin is planned, so nothing is shaped for a
   host (no nih-plug, no plugin threading or state constraints). The circuit builder
   is still a library crate, because R1's agreement tests need one; the engine is
   `circuitsim` as it is.
2. **GUI: egui / eframe.** The schematic canvas is painted directly (pan, zoom, wires,
   symbols). The look is the editor's dark "studio" direction
   (`docs/editor_mockups/direction_studio.png`, `drawn_*.png`) and the hardware art
   for the device panels (`ui-mockup/`: filmstrip knobs, VU needles, lit tubes;
   `assets/`), loaded as textures.
3. **Inputs: audio files and live input, both in R2.** Files play as a loop region.
   Live input runs the audio interface's input through the device at draft-1x.
   Render works on recorded audio, so for live input the app records the take while
   it monitors and renders that recording.

## What exists

- **Engine** (`crates/circuitsim`, DK solver, IR read as JSON in `src/ir.rs`):
  - `stream.rs` (`Stream`): block-by-block runs equal to a whole run bit for bit, and
    `Stream::update` for knob changes (~2.4 ms, DK rebuild);
  - the supply partition on a second thread (`partition.rs`);
  - tube tables (`devices/triode_table.rs`), cached per process;
  - `Transient::update` takes unknowns renumbered by a rewiring (a tapped pot's wiper
    crossing its tap). It refuses changes of structure (the pad's 0 dB end, Time
    Constant 5-6, Pultec selectors that rewire); the player restarts the stream with
    a crossfade instead (`varimu/sim/live.py`).
- **Qualities** (`config/sim_settings.yaml`): production is the `circuitsim` block;
  draft adds `circuitsim_draft`; draft-1x adds `circuitsim_draft_1x` (a 48 kHz host at
  1x, the supplies on a second thread: the user's choice for playing). Measured: the
  670 at 0.69-0.86x real time on two cores, ~-45 dB from production; the EQP-1A at
  ~0.16x.
- **The web player to port:** `varimu/sim/live.py` (`Live`: a loop with a 10 ms seam
  crossfade, background IR builds, update or restart via `structure()`, meters) and
  `varimu/listen/play.py`, `play.html`, `play_worklet.js` (the device list
  `play.DEVICES`; the 670's four knobs; for other circuits, the circuit file's
  controls with selectors as dropdowns, mains settings left off).

**Still Python, needed in Rust:**

1. Circuit building, YAML -> IR, about 2,000 lines: `varimu/circuit/spec.py` (format,
   `resolve`), `builder.py` (macros, tolerance), `parts.py` (resistor, pot,
   tapped_pot, t_pad, transformer, bridge, vr_tube, mains_sine, tube / pentode /
   device instances), `netlist.py` and `fairchild_670.py` (the 670's derived values:
   channel 2 lumped); the load path of `varimu/devices/library.py` (device files in
   `config/devices/*.yaml`, the 6386's pitch distribution -> 32 sections; fitting
   stays Python); core materials in `config/magnetics.yaml`. Factory setup
   (`varimu/sim/setup.py`) isn't needed: a circuit file's defaults are the factory
   adjustment.
2. The editor: `varimu/editor/drawing.py` (the `.drawing.json` format), `connect.py`
   (drawing -> netlist), `compile.py` (the KiCad importer's core,
   `varimu/kicad/importer.py`, then `varimu/preflight.py`; problems mapped back onto
   symbols), `symbols.py` and `varimu/kicad/symbols.py` (the symbol table),
   `layout.py` (generated drawings); the UI logic in `varimu/listen/editor/*.js`
   (geom.js: place, move with rubber-banding, rotate, delete, copy / paste; tools.js;
   inspector.js; the Ctrl+K palette; E12 stepping).

## Ground rules

- CLAUDE.md's hard rules hold: values carry sources, the genome is physical only,
  results reproduce from (genome, signal, settings, code), listening comparisons are
  loudness-matched.
- **Python stays the reference** for circuit building and compiling. Two
  implementations with an agreement test, as for the device models.
- **circuitsim's production behaviour doesn't change.** An engine change keeps
  production bit-identical, or it gets the user's agreement and
  `slice_report.py --verify`.
- **Tolerance draws:** numpy's `default_rng([seed, crc32(name)])` (PCG64 with
  SeedSequence, then numpy's samplers). The Rust builder supports spread 0 (nominal
  units) first and refuses a nonzero spread with a clear error. Matching numpy's
  sampling bit for bit is a separate decision, taken when a non-nominal unit is
  needed in the app.
- Checks: `cargo test`, `cargo clippy --all-targets --all-features -- -D warnings`,
  `cargo fmt --check`, `uv run --extra listen --extra fast pytest`, ruff.

## Milestones

### R0. Scaffold

Two workspace crates next to `circuitsim`:

- `crates/varimu-circuit` (lib): later the circuit format, builder, parts, device
  loading, drawing, connect, compile and preflight. It depends on `circuitsim` for
  the IR types (`circuitsim::ir`), so the builder emits the engine's IR directly.
- `crates/varimu-app` (bin, eframe): the window, with the editor and player as
  panels.

**Done when:** the workspace builds; `cargo run -p varimu-app` opens a window in the
studio palette; every check passes; circuitsim's Python build (`uv sync --extra fast`)
is unaffected.

**Done (2026-10-27).** eframe 0.35 (its `App::ui` API; `egui::Panel` for side and
top panels). The window has an Editor view (the canvas's dot grid) and a Play view,
both empty; `theme.rs` holds the studio tokens. Adding eframe left every package
circuitsim locks at its version (Cargo.lock compared), `clippy --all-features` builds
the PyO3 bindings, and `tests/test_fast.py` passes. Note: `[profile.test]` is
opt-level 3 for the whole workspace, so the first `cargo test` compiles eframe
optimized too (a few minutes, once).

### R1. Circuit library in Rust

YAML -> IR for every circuit file in `config/circuits/` (the 670, the EQP-1A, the
triode stage and the drawn and compiled circuits), with device files and core
materials. Fixtures are exported from Python: the IR JSON at each circuit's defaults
and over a sweep of control values (every selector position, pots at
0 / 0.3 / 0.5 / 0.7 / 1).

**Done when:** the Rust-built IR equals the Python-built IR for every fixture,
compared value by value to 1e-15 (relative), in `cargo test`; a nonzero spread is
refused with a clear error; pytest fails when the fixtures are stale (as for
`export_circuit_fixtures.py`).

**Done (2026-10-27).** `crates/varimu-circuit`: `yaml` (yaml-rust2, plain scalars
resolved with PyYAML's YAML 1.1 rules: a float needs a dot and a signed exponent),
`spec` (load with Python's checks, `resolve`), `builder` (the macro parts, devices,
tolerance, `build_ir`), `parts`, `devices` (device files, the 6386's pitch
distribution in numpy's order of operations with its pairwise sum, materials; the
linear-limit core from circuitsim's own core port), `derived` (the 670's four
values; Python's module lookup is a table here). Python's order of floating-point
operations is kept throughout (`**` as `powf`, `max` as Python's).

- Fixtures: `scripts/export_app_fixtures.py` -> `crates/varimu-circuit/tests/fixtures/`
  (one file per circuit, the default IR in full and per case only the sections and
  models that differ: 198 cases + 6 defaults, ~520 kB). Per circuit: the defaults with
  linear cores, every control one at a time (selectors at every position, the rest at
  0 / 0.3 / 0.5 / 0.7 / 1 of their range), and for the 670 the tubes and T101's core
  away from nominal. `tests/test_app_fixtures.py` fails when they're stale.
- Result: **bit for bit**, 118,078 numbers in 204 builds, so `tests/agreement.rs`
  requires that (stricter than 1e-15: R2's bit-for-bit renders need the same IR). A
  deliberate one-ulp reordering in the T-pad and leakage formulas showed up as 294
  differences (worst 1.4e-16), so the comparison is sensitive to it.
- `tests/errors.rs`: a nonzero `passive_spread` is refused ("nominal units only"),
  as are unknown or out-of-range parameters, an unknown material (naming the part) and
  a bad circuit file (Python's load messages).
- A 670 build takes ~1.7 ms (the 204 builds in 0.34 s), negligible against R2's
  0.3 s from knob to ear.
- Not ported (not needed by the app): the SPICE emission and table grids, the
  genome-link checks, `register()` for circuit-specific macros (no circuit has one).

### R2. Player and render

- **Files:** load (symphonia), resample to the device's rate (rubato), loop a region,
  play via cpal at draft-1x through `Stream`.
- **Live input:** pick an input device and channel and monitor through the device at
  draft-1x. The input-to-output latency is shown. A record button keeps the take,
  which is then an input like a file (loop it, render it).
- **Front panel live:** a knob change rebuilds the IR on a background thread, then
  `Stream::update`, or a restart with a crossfade on a change of structure (as
  `live.py`). Meters.
- **Render:** the same input and panel at production settings, on a background
  thread with progress and cancel, saved as a WAV and played back.

**Done when:**

- both devices play files without dropouts at a default buffer;
- live input through both devices runs 5 minutes without dropouts on an idle desktop,
  with its latency measured and reported (the 670 has little headroom at draft-1x,
  0.69-0.86x real time: if it can't keep up live, report it and bring options);
- a knob change reaches the ear within ~0.3 s;
- a Rust production render equals a Python production render of the same input and
  values bit for bit (same engine, same IR).

### R3. Editor

Open, edit and save `.drawing.json`; place, move, rotate, delete, wire and label; an
inspector for values; compile with preflight markers; save as a circuit; edits heard
live in the player.

**Done when:**

- the three drawn circuits open, round-trip byte-identically, and compile to the same
  IR as Python's compile;
- drawing the triode stage from scratch works (`scripts/editor_draw_triode.py` does
  it for the web page).

### R4. Look and polish, with the user

The studio editor look and hardware-art device panels.

## Open

- Matching numpy's tolerance draws in Rust (see Ground rules).
- Live input on the 670 if draft-1x can't keep up live (R2 measures it).

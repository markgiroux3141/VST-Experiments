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

Recording (a click, takes, layered tracks) is its own plan,
[RECORDING_PLAN.md](RECORDING_PLAN.md) (2026-10-30, not started).

Out of scope: the research tools (blind A/B, ABX, reports, studies). They stay in the
Python / web lab. The web app keeps working.
**Update 2026-10-29 (the user's):** the user intends to retire the web app. Nothing new
goes into it (the component editor, [COMPONENT_EDITOR_PLAN.md](COMPONENT_EDITOR_PLAN.md),
is native only). Retiring it isn't planned yet: the blind A/B, ABX and difference
listening have no native counterpart, and `layout.py` (hand-written circuits opened as
generated drawings) isn't ported.

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

**Done (2026-10-28), except two points** (below: selectors that rewire take
0.3-0.55 s to be heard; the 670 on live input is measured on a silent input only).
`crates/varimu-app` is now a library (`src/lib.rs`, tested
on its own) plus the window (`main.rs`, `play_view.rs`):

- `resample`: scipy's `resample_poly` (Kaiser 5 window, Cephes `i0`, numpy's `sinc` and
  pairwise sum, `upfirdn`'s loop) ported operation for operation, **bit for bit** with
  scipy on every ratio and padding the project uses (`tests/resample.rs` on
  `scripts/export_audio_fixtures.py`'s fixture; `tests/test_audio_fixtures.py` says when
  it's stale). It replaces rubato from the plan: the render has to resample exactly as
  Python does, and one resampler serves both.
- `audio`: symphonia 0.6 decoding (power-of-two integer scaling, channels averaged as
  numpy's `mean`, then `resample_poly`): the six clips in data/clips (16-bit and float,
  mono and stereo, 44.1 kHz) load bit for bit equal to `load_audio`. Float32 WAV out.
- `settings`: the qualities of `sim_settings.yaml` stacked as `TransientSettings` does.
- `live`: `varimu/sim/live.py` ported (loop seam, background builds, update or restart
  with a crossfade, meters). On the EQP-1A its output equals Python's `Live` bit for bit
  (60 blocks of a tone; numpy's `linspace` matters at the seam).
- `player`: the session on a worker thread feeding a lock-free ring (rtrb) that a cpal
  output stream at the host rate copies out of (WASAPI converts rates for outputs);
  callbacks it can't fill are counted as dropouts. A file's loop is kept 150 ms ahead.
  Live input: a cpal input stream (the device's default format; one channel) into a
  second ring, `StreamResampler` (the same filter, streaming) to 48 kHz, blocks through
  the circuit as they arrive, the output starting at a 30 ms queue; a block of input is
  skipped when the queue passes the buffer plus two blocks (clock drift). Input to
  output is reported from cpal's timestamps (input device + half a block + compute +
  queue + output device), knob to ear from `set` to the first block built with it
  playing. Record keeps the input as a take (`cache/app_takes/`, float32 WAV at the
  device's rate), which then opens as the file. The process runs at high priority
  (`raise_priority`). `Playback` loops a finished render.
- `render`: `fast.run_transient` and the runner's float32 output ported, with progress
  and cancel. **Bit for bit with Python** at production and at draft-1x, both devices
  (0.25 s of the arpeggio with knobs away from their defaults, every probe:
  `scripts/app_render_agreement.py`, which runs the `render` example).
- The Play view: device, file (data/clips or Open…), the loop region dragged on a
  waveform, Play / Stop, the front panel (sliders and selectors), meters (gain, output,
  CV, load, queued audio, dropouts, restarts), Render (production) with progress,
  cancel, Play render and Save as (renders also go to `cache/app_renders/`).
  `varimu-app [FILE] [--play] [--device ID] [--input NAME --channel N]` opens and plays
  from the command line.
- Sources (2026-10-28): data/clips and folders the user adds (Add folder…, scanned with
  their subfolders, grouped per folder), kept per user outside the repo
  (`prefs`: `%APPDATA%\varimu\app.json`; multitracks for educational use must never be
  committed). A file's loop starts on its loudest 8 s.
- Input level: each file's loudest 8 s normalized to -18 dBFS (sine-equivalent rms; the
  studio alignment the 670's factory adjustment assumes, +4 dBu), changeable or off,
  plus a trim; a console fader's job, ahead of the device (`Live::with_gain`: the circuit
  settles at the gained first sample). Renders take the same gain.
- `monitor`: Device in / Bypass (B; the input, delayed by the engine's lag, crossfaded
  over 10 ms, the circuit running on) and gain compensation (K-weighted as BS.1770,
  ~3 s, applied to the device's output, smoothed over ~1 s, held below -70 LUFS), so the
  device is compared with itself off at the same loudness. Monitoring only.

The live-input UI: File / Live input, the input device (↻ lists them again), channel,
buffer (10-150 ms), Monitor, Record; `varimu-app --input NAME --channel N --play`.

**Measurements (2026-10-27,** `examples/play.rs`: a line per second and a summary; the
desktop ~30% busy with the user's other work, so not the idle desktop the done-when
asks for; UA Twin USB in and out, WASAPI shared mode, 48 kHz, 10 ms device buffers):

| Run | Load (mean / worst block) | Dropouts | Notes |
|---|---|---|---|
| EQP-1A, file loop, 20 s, High boost flipped every 2 s | ~30% / 361% (first second) | 0 | knob to ear 182 ms mean, 186 max |
| 670, file loop, 30 s, threshold 0.709 / 0.9, normal priority | ~100% / 402% | 152 | knob to ear 127 ms mean, 194 max |
| 670, file loop, 25 s, defaults, high priority | ~95% / 199% | 12 | |
| 670, file loop, 60 s, threshold flipped, high priority | ~103% / 247% | 116 | knob to ear 139 ms mean, 195 max |
| 670, file loop, 30 s, defaults, high priority | ~90% / 215% | 8 | |
| EQP-1A, live input, 5 min, 30 ms buffer, normal priority | ~26% / 417% | 2 | input to output 60-80 ms (80 mean); each dropout added 10 ms of queue |
| 670, live input, 60 s, 50 ms buffer, high priority | ~45% / 84% | 0 | 86 ms; the input was silent |

Of the input-to-output latency, 32 ms is the output device (WASAPI shared mode) and
the starting queue is the buffer; the rest is the input device, half a block and the
compute. Silence is cheap for the 670 (45% load against ~90% on program material), so
its live-input run doesn't show what an instrument would cost. The dropouts come from
isolated stalls (single blocks taking 2-4x their time; the supplies' partition steps in
lockstep with the main thread, so a stall on either costs a block), and on the 670 from
its mean load near 100%: draft-1x runs the 670 at about real time here (the M8 study:
0.69-0.86x on an idle desktop), harder compression costing more.

Found: cpal 0.18 overflows (debug builds panic) listing the formats of inputs with many
channels (the UA Twin's 22, `supported_input_configs`), so inputs use
`default_input_config`.

**On an idle desktop (2026-10-28,** CPU 5-12% before each run, high priority, UA Twin USB):

| Run | Mean load (worst second) | Dropouts | Latency |
|---|---|---|---|
| 670, arpeggio loop, defaults, 60 s | 84% | 0 | |
| 670, arpeggio, threshold 0.709 / 0.9 every 2 s, 60 s | 86% (98%) | 0 | knob to ear 186 ms mean, 202 max (150 ms lead) |
| 670, dense mix, pad 6 dB (-5 dB mean gain), 2 min | 74% (95%) | 0 | |
| EQP-1A, dense mix, HF frequency selector flipped, 60 s | 25% | 0 | selector to ear 365 ms (150 ms lead), 325 ms (100 ms lead) |
| EQP-1A, live input, 5 min, 30 ms buffer | 23% | 0 | input to output 64 ms mean, 71 max |
| 670, live input, 5 min, 30 ms buffer | 43% | 0 | 75 ms mean, 82 max (silent input) |
| 670, dense mix, Time Constant 2 / 5 every 2 s, 60 s, 100 ms lead | 79% (96%) | 0 | selector to ear 538 ms mean, 579 max |
| 670, dense mix, threshold flipped, 30 s, 100 ms lead | | 0 | knob to ear 135 ms mean, 143 max |

The busy-desktop dropouts were contention: idle, every run is clean, the 670 at 74-86%
of real time (heavier compression costs more). A loop's output now starts once its lead
is queued (the one remaining dropout was the first blocks warming up), and the lead is
100 ms (knobs heard in ~135 ms). Open:

- **Selectors that rewire** (the EQP-1A's frequency selectors, the 670's Time Constant
  5-6, the pad's 0 dB end) restart the stream, which first runs `settle_s` (1 s) of its
  supply: 0.3 s (EQP-1A) to 0.55 s (670) to the ear. The lead isn't the lever; a shorter
  settle for restarts (a supply not quite settled when it fades in) or streams kept
  warm for neighbouring positions would be.
- **The 670 on live input** was measured on a silent input (43% load against ~80% on
  program): a run with an instrument into the interface is still to do.

**HF-rich input (2026-10-28).** A drum stem (normalized to -11.5 dBFS) dropped out at
every hi-hat on the 670. `examples/load_profile.rs` (a file through a device at draft-1x
without an audio device: each block's load next to the solver's counters, per device and
per refactorization cause; `--add-c NODE=F` tries a capacitor to ground) found:

- the load is the sidechain's bridge (DCR101-104), not level: at the same level, HF-rich
  blocks ran at 3-4x real time, dull ones at 0.6x; with no signal into the sidechain the
  stem ran at 0.45x with no block over 1.0;
- the bridge sits on T104's floating secondary, whose common mode only the diodes'
  leakage (~1e-7 S) held. Each time HF peaks switched the bridge, Newton moved that
  common mode by tens to hundreds of volts and walked it back one nVt (47 mV) per
  iteration, refactoring nearly every time (28 iterations and 22 factorizations per
  sample in the hits; whole stem 0.97x, every 8 s loop 0.92-1.02x, backlogs to 570 ms
  against the 100 ms lead). Junction limiting doesn't cover a walk down; inverting the
  diode's curve on downward steps saved 13% and nothing once the island was held, and
  caching factorizations wouldn't cut iterations;
- the fix (the user's choice): the secondary's capacitance to its grounded core,
  `CT104A/B` (`t104_c_sec_gnd_f`, 100 pF each, provisional, genome-bounded 30-300 pF; the
  value barely matters from 100 pF to 1 nF). The stem then runs at 0.68x, the worst 8 s
  loop at 0.71x, 0.49 factorizations per sample, the worst backlog 115 ms; what remains
  is the 6973s seeing the bridge switch through T104. The 670 keeps a 250 ms lead
  (`panel::Device::ahead_s`; other devices 100 ms).
- checked: in real time (`examples/play.rs --gain-db 5.9`, the stem's first 8 s, 15 s,
  idle desktop) 0 dropouts at 62-68% load, single blocks up to 485% absorbed by the lead;
  `slice_report.py --verify` passes (behaviour within 0.01 dB of ngspice, every waveform
  row within its regression bound, the largest move 1.3 dB).

The Play view also has a manual Output gain (+-24 dB, on top of the compensation,
monitoring only): the compensation can sit low for seconds after quiet stretches (a
likely cause, not yet measured: quiet input above its -70 LUFS gate while the device's
own floor reads louder).

Fixed on the way: a knob change after a restart, both ready before the next block, was
applied to the playing stream rather than the one fading in, which stopped playback
("update: the circuit's nodes, sources or inductors changed"; the pad across 0 dB). The
port's builder compares with the last structure built, `live.py` with the one playing,
which is why only the port had it (`tests/live.rs`, `tests/test_live.py` guard both).

### R3. Editor

Open, edit and save `.drawing.json`; place, move, rotate, delete, wire and label; an
inspector for values; compile with preflight markers; save as a circuit; edits heard
live in the player.

**Done when:**

- the three drawn circuits open, round-trip byte-identically, and compile to the same
  IR as Python's compile;
- drawing the triode stage from scratch works (`scripts/editor_draw_triode.py` does
  it for the web page).

In three steps, as B4a went (2026-10-28):

- **R3a, formats and compile** (`varimu-circuit`): the drawing document, the symbol
  table and placement transform, the connectivity, the importer's core, the circuit
  file's YAML as PyYAML writes it, the pre-flight checks and markers on the drawing.
- **R3b, the canvas**: the drawing painted (frames, symbols, wires, labels, grounds,
  junctions), pan and zoom, selection, an inspector for values and fields, compile
  with markers on symbols and nets, edits heard live in the player (a compiled drawing
  is a circuit like the others).
- **R3c, topology**: place, move with rubber-banding wires, rotate, mirror, delete,
  copy / paste, the wire tool, labels and grounds, E12 stepping, Save as.

**R3a done (2026-10-28).** New modules in `crates/varimu-circuit`, each a port of its
Python counterpart with Python's orders and messages: `json` (JSON with keys in file
order, written as `json.dumps(indent=1, ensure_ascii=False)`), `drawing`
(`varimu/editor/drawing.py`), `symbols` (`varimu/kicad/symbols.py`'s table, graphics
as shapes, and `varimu/editor/symbols.py`'s transform), `values` (`parse_eng`, natural
order), `connect`, `importer` (`varimu/kicad/importer.py` without the KiCad XML),
`yaml_out` (PyYAML's `safe_dump` for the subset circuit files use: YAML 1.1 implicit
types quoted, non-ASCII double-quoted, `.0` before an exponent; and `to_yaml`),
`preflight`, `compile` (compile, the file's text, markers, `save_circuit`).
`spec::circuit_from_value` builds a spec from content in memory.

- The three drawn circuits round-trip byte for byte (`tests/drawings.rs`), and compiling
  each writes exactly the circuit file the Python editor wrote (`<name>_drawn.yaml`).
- `tests/editor.rs` against `scripts/export_editor_fixtures.py`'s fixtures (the three
  drawings and four broken copies of the triode stage: a wire removed, a Source removed,
  two labels on one net, a stray resistor): the connectivity, compile errors and
  problems, the compiled content, the file's text, the IR (bit for bit) and the markers
  all equal Python's; the symbol table too. `tests/test_editor_fixtures.py` says when
  the fixtures are stale (`uv run python scripts/export_editor_fixtures.py`).
- Known difference: Python iterates a wire's two ends as a set (order from float
  hashing), which only orders error messages when a drawing has several; Rust takes
  them in order. A build error's message names Python's exception type as
  `ConfigError`.

**R3b and R3c done (2026-10-28); R3's done-when is met.** The web editor's page logic
(`varimu/listen/editor/*.js`) is ported to `varimu-app`'s library, `src/editor/`, so it is
driven and tested without a window; `src/editor_view.rs` paints it:

- `eng` (eng.js and `engText`: numbers as JavaScript writes them, E12 / E24 stepping),
  `geom` (geom.js: place, move with rubber-banding wires, rotate, mirror, delete, copy /
  paste, wires, segment dragging, with `Math.round`'s rounding), `edits` (edits.js:
  parameter homes, edit sources, unlink, undo history), `analysis` (editor_api.py's
  `analyze`: nets, parameters with their genome bounds, tolerance bands), `scene`
  (view.js: the symbol table with y down, every pin's net, unit boxes, the parts' upright
  texts, cores drawn the length of their windings, open pins, hit testing), `camera`
  (camera.js), `session` (main.js, tools.js and inspector.js's behaviour: the editor's
  state, every tool, the inspector's edits, the checks on a thread of their own 600 ms
  after an edit, open, Save as). The JS tests (`tests/editor_js/*.test.mjs`) are ported
  as unit tests.
- **The done-when, headless** (`tests/editor_draw.rs`): the triode stage drawn from a
  blank drawing through the editor's API, step for step as
  `scripts/editor_draw_triode.py` drives the page (palette and clicks on the canvas
  through the camera, R to turn, the reference and value fields, the wire tool, the
  label prompt, grounds, the circuit's title and probes): the drawing comes out
  `triode_stage_drawn.drawing.json` **byte for byte** (which the web editor drew), the
  checks find nothing, Save as writes the committed `.drawing.json` and `.yaml`, and it
  builds `triode_stage_drawn.yaml`'s IR bit for bit (linear and Jiles-Atherton cores).
  Also: undo and redo through the whole drawing; on the drawn stage, E12 stepping keeps
  the value's first provenance, a drag rubber-bands its wire, duplicate and delete.
- **Edits heard live:** `live::Circuit::from_spec` (the compiled drawing, its device
  files from the editor's library), `Live::set_circuit` / `Player::set_circuit` (built on
  the background thread like a knob: the same structure updates the stream in place, a
  new one restarts it with the crossfade). The drawing is a device of the Play view
  ("Drawing: <title>", its controls as the panel), handed over at every edit that
  compiles and has an `out` node; Space (or the listen bar) plays it through the Play
  view's file and loop region. `tests/editor_live.rs`: a load edit (RL 470k -> 4.7k) is
  heard in place (-10 dB or more, no restart), deleting the cathode bypass restarts the
  stream once and lowers the gain. In the window: the drawn stage at 5% load, no
  dropouts.
- The window (checked by screenshots, driving it with synthetic mouse and keys): the bar
  (circuit, tools, undo / redo with their labels, Save as, the checks pill, zoom, Fit),
  the left column (find, problems with open pins per part, the parts palette drawn from
  the symbol table, the drawing's front panel, sections), the canvas (dot grid, dashed
  frames with their titles, symbols, wires, labels, grounds, junctions, open pins, net
  highlight on hover, problem rings, selection, the hover chip, the tools' ghosts), the
  inspector (a part's value with its source and E12 stepping, shared parameter and
  "only this part", device and material swaps, its other parameters, pins and their
  nets, every raw field; several items; a net; the circuit's title, input, probes and
  controls), the listen bar, the label / section prompt, the Ctrl+K palette, the ? sheet.
  Text uses Segoe UI, Cascadia Mono (or Consolas) and Segoe UI Symbol where Windows has
  them (egui's fonts lack the arrows and dots the labels use). `varimu-app --edit NAME`
  opens the editor on a drawn circuit.
- Found on the way: a prompt opened by a click lost its focus to that click's release (the
  page waits for it too); front-panel sliders wrote their snapped values back when shown
  (opening the 670 marked it edited). Both fixed.
- Not ported: hand-written circuits opened as generated drawings (`varimu/editor/layout.py`
  and the KiCad exporter under it; the drawn copies cover the three circuits); the camera
  remembered per circuit. A `.drawing.json` dropped on the window opens, as on the page.

### R4. Look and polish, with the user

The studio editor look and hardware-art device panels.

**Paused 2026-10-28 (the user's call: the artwork isn't a priority now).** Where it
stands, to pick up from:

- **The art.** `assets/Compressor/` is a 670-style rack panel (`UI Lit.png`,
  `UI Unlit.png`, 2244 x 701) plus parts (large and small knob, three toggle states, a VU
  needle); its controls match the circuit's: Input Gain 0-30, Threshold, Time Constant
  1-6, and the Balance and Zero screwdriver trims (`balance`, `zero` in
  `fairchild_670.yaml`). `assets/Test/` and `ui-mockup/` are the older "Valvechild"
  concept (its controls aren't a 670's). There is no EQP-1A art.
- **Prepared:** `scripts/build_panel_art.py` writes the 670's textures to
  `crates/varimu-app/assets/fairchild_670/`: channel 1 and the centre section with the
  left rack ear mirrored on the right (one channel is simulated; it reads like the mono
  660), the knobs centred on their pivots, the needle turned upright, the two screw
  heads cut out to turn, and `layout.json` (holes, sweeps, VU face and pivot, tick
  angles, all measured on the art). Not yet used by the app.
- **Art flaws found:** the Time Constant scale reads 2, 2, 3, 4, 5, 6 (the leftmost should
  be 1); the lit and unlit images are different pictures (scales, text, escutcheons), so
  they can't be crossfaded as `docs/UI_PIPELINE.md` does (use the lit one, dim the meter
  face and lamp when stopped); the VU scale's arc centres ~100 px below the face (the
  needle pivots there, clipped to the face); DC THRESHOLD has no place on the panel.
  `ui-mockup/relight_knob.py` is fitted to the Valvechild knob only: the 670 knobs would
  turn with their highlights unless it is refitted.
- **Three directions to prototype and show** (screenshots, then the user picks):
  *Faceplate* (the 670 art as is, knobs and trims turning over it, needle on the VU;
  other circuits fall back to Built), *Built* (a plate painted by egui with the same knob,
  screw and needle textures, scales from the circuit's ranges: works for the EQP-1A and
  drawings), *Studio* (flat vector dials in the editor's tokens, no textures). Planned as
  `src/panel_view.rs` with a look switch (and `--look`) in the Play view, the panel at the
  top of its main area.
- **Questions for the user:** the input knob's direction (printed "Input Gain" 0-30 vs
  the circuit's attenuation: clockwise louder = 30 - `input_atten_db`?); what the VU
  reads (`Meter::gain_db` is output over input, not GR: output level as VU, or GR
  calibrated from the control voltage); Balance and Zero on the panel (they'd join the
  670's `panel` list); where DC threshold goes (a trim strip under the panel?).

## Open

- Matching numpy's tolerance draws in Rust (see Ground rules).
- Live input on the 670 if draft-1x can't keep up live (R2 measures it).
- The editor opening hand-written circuits as generated drawings (`layout.py`'s port,
  R3's optional part).

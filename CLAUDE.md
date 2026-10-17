# CLAUDE.md

The project plan is [VARIMU_PROJECT_PLAN.md](VARIMU_PROJECT_PLAN.md) (the plan's
layout calls it `PLAN.md`). Read it before starting work.

**Phases 0 and 1 are done; next per the plan is Phase 2 (Transformer Models).**
Work one phase at a time. Don't start the next phase until the current phase's
"done when" criterion is met and covered by tests.

A crude end-to-end slice exists ahead of plan order ("end-to-end early,
fidelity later"): one 670 channel as one coupled netlist
(`config/circuits/fairchild_670.yaml` -> `varimu/circuit/netlist.py`), audio
I/O and a cached parallel runner (`varimu/sim/io.py`, `runner.py`), and a
tweak-and-listen page (`varimu/listen/`). Its transformers are linear
placeholders with provisional parasitics; Phase 2 replaces them. Results are in
`reports/slice/` (compression curve, Time Constant bursts, tolerance study).

A fast Rust circuit simulator (`crates/circuitsim`, ngspice stays the
reference) is planned in [docs/CIRCUIT_SIM_PLAN.md](docs/CIRCUIT_SIM_PLAN.md).
Work its milestones in order, with the same "done when" discipline.
**M0 (scaffolding), M1 (circuit IR), M2 (linear engine), M3 (devices and
Newton), M4 (the 670 slice on the fast engine) and M5 (nodal DK) are done,
except M5's speed target (10x faster than ngspice; 5-6x so far), deferred
until the main milestone work is done (decided 2026-10-17; the plan's M5
status lists where to start). Next is M6 (default engine).**
`netlist.build()` builds a typed circuit IR (`varimu/circuit/ir.py`) and emits
SPICE from it (`varimu/circuit/spice.py`); the Rust side reads the same IR as
JSON (`crates/circuitsim/src/ir.rs`) and simulates it at a fixed step
(`mna.rs`, `transient.rs`), with compiled ports of the Python device models
(`devices/`). The default solver is nodal DK (`dk.rs`): the linear part
folded into responses of the step matrix once per step size, Newton on the
22 device ports with the factored Jacobian reused and unmoved devices not
re-evaluated; `solver: mna` is M3-M4's Newton on the device-node block of the
full MNA system (`newton.rs`), the reference DK is tested against.
`Transient::update(ir)` changes component values mid-run. `varimu.sim.fast.run_transient(ir, x)` is the Rust counterpart
of `varimu.sim.io.run_transient` (same oversampling and decimation).
Production settings are the `circuitsim` block of `config/sim_settings.yaml`:
esdirk4 at 2x, 5th-order input interpolation, local error control (chosen by
M4's method study; the plan has the numbers), DK with Newton tolerances
1e-4 / 1e-3 V (M5). `simulator.engine` picks the
engine for renders (ngspice until M6).

## Commands

```sh
uv sync                          # install (add --extra listen|fast|ml|optimize when a phase needs it)
uv run pytest                    # tests
uv run ruff check . && uv run ruff format --check .
uv run varimu signals [--seed N] [--only NAME ...] [--list]
uv run varimu genome-status
uv run varimu fit-devices [--only 6386 ...]   # refit device models -> config/devices/*.yaml
uv run python scripts/digitize_ge6386.py --overlays DIR   # re-digitize the 6386 sheet
uv run varimu render --clip data/clips/x.wav --set ac_threshold=0.7 time_constant=3 --out r.wav
uv run varimu render --signal steps_1000hz --vary time_constant=1,2,3   # parallel, cached
uv run --extra fast varimu render --signal burst_1000hz_0dbfs --engine circuitsim
uv run varimu listen             # http://127.0.0.1:8765 (needs: uv sync --extra listen)
uv run python scripts/slice_report.py [--engine circuitsim]   # compression curve + TC attack/release -> reports/slice/
uv run python scripts/tolerance_study.py    # solver settings vs accuracy -> reports/slice/
uv run python scripts/export_circuit_fixtures.py [--golden]   # IR + device fixtures for Rust tests (+ SPICE goldens)
```

Rust (`crates/circuitsim`; workspace `Cargo.toml` at the repo root, output in `target/`):

```sh
cargo test                                            # Rust tests (IR round trip, ...)
cargo run --release --example profile -- circuit.json [method] [oversample] [dk|mna] [reltol] [vntol]   # speed of a step
cargo run --release --features timing --example profile -- ...   # plus where the DK step's time goes (cycle counts)
cargo clippy --all-targets -- -D warnings
cargo clippy --all-targets --all-features -- -D warnings   # also the PyO3 bindings
cargo fmt --check
uv sync --extra fast             # build circuitsim (maturin, abi3) into .venv: `import circuitsim`
```

- **Rebuilds:** `uv sync --extra fast` and `uv run --extra fast ...` rebuild
  circuitsim whenever a crate source changes (`cache-keys` in
  `crates/circuitsim/pyproject.toml`: its `pyproject.toml`, `Cargo.toml`,
  `build.rs`, the workspace `Cargo.toml`, `src/**/*.rs`) and are no-ops
  otherwise. **Plain `uv run` does not rebuild:** it keeps the installed
  circuitsim, stale after a Rust edit. So after editing Rust, use
  `uv run --extra fast pytest` (or sync first). Add a cache key if the build
  starts depending on another file. (All verified 2026-10-14.) A stale build
  can't slip through: `build.rs` embeds a hash of the crate sources
  (`circuitsim.SOURCE_HASH`) and `varimu.sim.fast` raises `StaleBuild` when it
  doesn't match the working tree (`tests/test_fast.py` too).
- **`uv sync` is exact:** it uninstalls every extra you don't name (plain
  `uv run` leaves them installed). Name all of them each time, e.g.
  `uv sync --extra listen --extra fast`.
- **Windows file locks:** stop `varimu listen` (and any Python that imported
  circuitsim) before syncing. A sync that hits a locked `.pyd`/`.exe` aborts
  halfway and can leave a package half-removed; rerun the sync once the
  process is gone.
- The circuitsim tests in `tests/test_circuit_ir.py` skip when the extra isn't
  installed. Cargo builds use every core; `CARGO_BUILD_JOBS=6` keeps the
  desktop responsive.
- `tests/fixtures/netlist_golden/` holds byte-exact SPICE netlists,
  `crates/circuitsim/tests/fixtures/` the IR JSON, and its `devices/` the
  Python device models evaluated on grids (`varimu.devices.fixtures`). All
  are regenerated by `export_circuit_fixtures.py` (pytest fails when the IR
  or device fixtures are stale, e.g. after a device refit); re-capture the
  goldens only when the circuit is meant to change, and review the diff.
  `.gitattributes` keeps them LF.

Renders are cached in `cache/renders/<hash>/` (key: netlist, tables, input,
settings, and the source of `varimu/{sim,circuit,devices}` + `config.py`).
`cache/renders/timing.csv` logs wall-clock per second of audio for every render.
`--set` keys are the names in `config/circuits/fairchild_670.yaml` plus
`v6386_{a,b}.{emission_scale,mu_spread,grid_contact_v}`.

The dev machine runs Windows. Use `pathlib` for paths and never hardcode separators.

**Simulator:** ngspice 47 is installed portably under `tools/ngspice-47/` (git-ignored).
`varimu.sim.ngspice.find_ngspice()` looks at `$VARIMU_NGSPICE`, then `tools/`,
then `PATH`. To reinstall, download `ngspice-47_64.7z` from SourceForge
(ng-spice-rework/47) and extract it into `tools/ngspice-47/`. SPICE agreement
tests skip when ngspice is missing.

## Hard rules

- **Never present invented values as data.** Prefer a schematic, datasheet or
  cited paper. The user has OK'd using web sources and model knowledge to keep
  moving, but every value carries a `source`: a datasheet reference,
  `web: <url>`, or `provisional: model knowledge (...)`. Provisional values
  should become bounded genome parameters or be replaced later. `varimu.config`
  enforces that every genome parameter has a `source`, and device files carry
  one per block.
- **The genome is physical only.** No EQ curves, saturation knobs or anything
  a real unit couldn't have.
- **One coupled simulation.** The audio path, sidechain and PSU go in one
  netlist, never in separately chained DSP blocks.
- **Every device model has two implementations**, SPICE and a Python
  reference, with a test that they agree.
- **Reproducibility.** Every result must be reproducible from (genome, signal,
  settings, code version). All randomness goes through a seeded
  `np.random.Generator`. Derive per-item seeds, e.g.
  `default_rng([seed, crc32(name)])`, so adding an item doesn't perturb the others.
- **Loudness lies.** Every listening comparison is matched for both gain
  reduction and LUFS.

## Conventions

- Units are SI in code. Put the unit in the name whenever it isn't obvious:
  `_s`, `_hz`, `_ohm`, `_dbfs`, `_v`.
- Audio levels are **peak dBFS**: 0 dBFS is a sine of amplitude 1.0. Convert to
  circuit volts with `audio.full_scale_volts_peak` from `sim_settings.yaml`,
  in the sim layer only.
- Read the sample rate from `sim_settings.yaml` (96 kHz). Don't hardcode it
  outside tests.
- Audio files are mono float32 WAV. Generated audio is not committed, because
  it can be regenerated from the seed, and `manifest.json` records hashes.
- `data/clips/` holds only recordings the user owns or has rights to.
  Never commit it.
- Digitized datasheet CSVs need a provenance sidecar (see `data/datasheets/README.md`).
- Prefer small, inspectable steps. Save measurement plots for candidates so
  changes in character can be reviewed visually.
- `assets/` and `ui-mockup/` hold plugin UI art for Phase 10. They are not part
  of the Python package.

## Known issues / gotchas

- **ngspice behavioral sources in sweeps.** In a `.dc` sweep, ngspice reports a
  B-source's value linearized from the previous point and accepts it after
  one iteration, even with tight RELTOL. The error scales with step^2 and was
  about 0.1% at 2 V steps. A fresh `.op` is exact, so the agreement tests use
  one `.op` with many instances. The same effect may hurt transient accuracy
  at default tolerances: measure it in Phase 4 before trusting renders.
- The SPICE `D` model uses a cubic approximation in deep reverse bias, so it
  differs from pure Shockley by about 1e-11 A.
- **Full-slice render speed (measured 2026-10-13).** About **25-40x slower than
  real time** per render (one core each): 25.5 s staircase 28x, 7 s bursts
  28x, 1 s program clip 25-31x, plus ~2-5 s fixed start-up. Parallel renders
  scale with cores. What made it feasible:
  - triode plate currents are XSPICE `table2D` tables of the Python models
    (`varimu/devices/table.py`), ~20x cheaper than the 32-section B-source,
    whose symbolic derivatives blow up (1.3 ms per timepoint). Bilinear error
    is <=1e-4 of max current; `devices.triode_formulation: exact` restores
    the B-sources for verification;
  - the circuit had a parasitic ~30 kHz oscillation (tuned-plate tuned-grid
    through lossless transformer leakage) that forced 80 ns steps. Winding
    self-capacitance and lumped core loss (provisional values) fixed it, and
    `tests/test_slice.py` guards idle stability.
- **Transient accuracy (measured 2026-10-13).** The DC-sweep under-convergence
  above does not show up in transient: at reltol 1e-3 renders are within
  -59 to -67 dB (re signal) of a tight reference. Chosen: trap, reltol 1e-3,
  2x oversampling (`config/sim_settings.yaml` has the numbers). reltol 1e-5
  fails to start at the bridge diodes. KLU (`.options klu`) also fails there.
- **ngspice 47 I/O gotchas** (details in `varimu/sim/io.py`):
  - XSPICE `filesource` load time is quadratic in file length (4.9 M lines:
    140 s), so inputs are split into series-connected chunks;
  - `.options interp` freezes output values when the solver steps below TSTEP;
    interpolate in Python instead;
  - batch mode ignores `.options filetype`; a `.spiceinit` in the job dir sets
    binary output (and `num_threads`);
  - an inline PWL source breakpoints every sample (5x the timepoints);
  - a filesource reads 0 past its last entry (it doesn't hold), and the
    final timepoint can land a rounding error past it, so the last chunk ends
    with an extra hold point (fixed 2026-10-14; before that, the last
    oversampled sample of every render saw input 0);
  - for agreement tests, `run_transient(..., max_step_div=8,
    grid_breakpoints=True)` makes ngspice a reference: plain runs straddle
    the input's sample kinks and interpolate, about -55 to -75 dB re signal.
- **Fixed-step engine accuracy (decided 2026-10-15, plan M4).** Trapezoidal
  frequency-warps the transformers' resonances (the slice peaks +10 dB near
  17 kHz from provisional winding capacitances): 0.8 dB / 8 deg off at 20 kHz
  at 2x. Production uses esdirk4 at 2x instead, with 5th-order input
  interpolation (linear input between samples, ngspice's PWL, droops 20 kHz
  by 0.3 dB at 2x and caps any higher-order method) and local error control
  for the non-smooth events (bridge diodes switching on HF, the TC1 attack),
  where only smaller steps help. Measure against the engine's converged
  solution (e.g. radau5 at 8x, input_order 5), not ngspice: ngspice with
  tabulated triodes is ~-62 dB rms from it; with the exact formulation it
  agrees to -92 dB but runs ~7000x slower than real time. The M2/M3
  agreement tests (`tests/engine_compare.py`) still run trapezoidal, the
  engine's 2nd-order baseline.
- **circuitsim speed (measured 2026-10-17, M5).** Production (DK) runs
  3.3x slower than real time on the 7 s TC1 burst and 4.2x on the arpeggio
  clip, against ngspice's 20.6x / 21.2x and M4's full MNA 15.8x / 18.5x in
  the same session (one job at a time). HF test tones are slower (CCIF
  -10 dBFS 77x) where error control subdivides steps. Per sample: ~9 Newton
  iterations over 5 stages, ~1.4 factorizations of the 22 x 22 port matrix.
- **Benchmarking on this desktop.** Timings drift +-35% between runs:
  VS Code's rust-analyzer recompiles the crate on all cores for ~2 minutes
  after each Rust edit, and explorer.exe often holds a core. Wait until no
  `rustc` runs, report the best of several runs, and compare engines back to
  back rather than against old numbers.
- **Floating nodes and Newton tolerance (measured 2026-10-14).** At DC the 670's
  T104 secondary is a 1 mOhm winding held only by bridge-diode leakage and a
  1 GOhm leak; double precision resolves it to ~1e-6..1e-5 V in any engine.
  So circuitsim's vntol is 1e-6 V (SPICE's), and ngspice can't find the
  670's `.op` at reltol 1e-9. Compare such nodes against the engine's own
  roundoff spread (reorder the unknowns), as `test_circuitsim_nonlinear.py` does.
  In transient the floor is ~1e-4 V with the bridge off and ~1e-2 V with it
  reversed for good, in either solver, and reordering doesn't reveal it (both
  orders share it): compare that island relative to its common mode
  (`crates/circuitsim/tests/dk.rs`). DK also needs a 10 uS shunt per diode
  port moved into the step matrix (`Device::shunt`), or its precomputed
  responses lose 4 digits there.
- **`ngspice.run(options=...)` was silently ignored until 2026-10-14** (fixed):
  `.op` agreement tests written before then ran at ngspice's default
  tolerances. Pass `digits=16` for full-precision output (the default prints
  ~10 significant digits, ~5e-7 V at B+).
- **Renders and the desktop.** ngspice runs at below-normal priority with one
  thread, and parallel renders default to cpu_count - 2 (`runner:` in
  `sim_settings.yaml`). Don't kill ngspice by walking up process trees: two
  renders launched from one shell share ancestors.
- **Patching files from Bash heredocs:** this shell collapses a doubled
  backslash to a single one inside heredocs, so an escaped `\n` meant for a
  Python string arrives as a real newline. Write patch scripts with the Write
  tool, not heredocs.

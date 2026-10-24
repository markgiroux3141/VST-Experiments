# CLAUDE.md

The project plan is [VARIMU_PROJECT_PLAN.md](VARIMU_PROJECT_PLAN.md) (the plan's
layout calls it `PLAN.md`). Read it before starting work.

**Phases 0-4 are done (Phase 4, measurement suite: 2026-10-23; noise waits
for noise sources). Phase 5 (Listening App and Preference Data) is in
progress: blind A/B at `/ab` of `varimu listen`, stimuli matched by
`varimu ab-prepare` (varimu/listen/: candidates, stimuli, prepare, session,
store; the plan's Phase 5 status), with its first listening aids (2026-10-24:
difference listening and an ABX exaggeration staircase on the same page;
`difference`, `abx`). Mumetall's Rayleigh refit (the plan's Phase 2, "Low-level
core physics", Option 1) is applied (2026-10-24). Next: Phase 5's planned
items 3 (condition search) and 4 (physical caricatures), and a first real
ABX session by the listener.** Plausibility (`varimu.measure.plausibility`) rejects only what no
working unit could do; comparisons with the 670's published figures are the
report's `vs_670` and never reject (the plan's Vision: "Aim, restated").
Since 2026-10-23 the default front panel is the
factory adjustment (the manual's threshold procedure to its curve 3,
`varimu.sim.setup.threshold`), T103 is 8.5 and the AC THRESHOLD pots are
tapped (Phase 3's sourced leftovers). Phase 2's decision (the user's): the hysteretic
core has a Python reference and a circuitsim device, no SPICE
implementation; ngspice cross-checks the rest with the cores in their linear
limit (Hard rules). Work one phase at a time. Don't start the next phase until
the current phase's "done when" criterion is met and covered by tests.

A crude end-to-end slice exists ahead of plan order ("end-to-end early,
fidelity later"): one 670 channel as one coupled netlist
(`config/circuits/fairchild_670.yaml` -> `varimu/circuit/netlist.py`), audio
I/O and a cached parallel runner (`varimu/sim/io.py`, `runner.py`), and a
tweak-and-listen page (`varimu/listen/`). Results are in `reports/slice/`
(compression curve, Time Constant bursts, program clip, `--verify`) and
`reports/transformers/` (each transformer standalone). Its transformers
(Phase 2) are windings on Jiles-Atherton cores (`varimu/devices/core.py`;
materials in `config/magnetics.yaml`, mumetall fitted to its datasheet by
`scripts/fit_core_material.py`) with leakage, winding R, self-capacitance,
the cores' joint gap and classical eddy loss; geometry, turns, leakage and
capacitances are provisional genome parameters (`genome_bounds.yaml`
`transformers`). Since Phase 3 the circuit has the 670's power supply, traced
on the drawing (`data/schematics/fairchild_670/README.md`, "Supply rails"):
the mains (an IR `SineSource`) into T302 / GZ34 / L301, the EL34 / 6084 / 5651
regulator (240 V, B+ ADJ), the selenium bias supply (the 6386 cathode return
at C303, ZERO, the 6973 grid-leak return), and idle channel 2 lumped onto the
same rails. Unprinted supply values are genome parameters, three nominals
calibrated by `scripts/calibrate_psu.py`. Every part and tube instance
deviates by its own seeded draw (`passive_seed`, `passive_spread`; the
nominal genome has spread 0), each 6386 bank is its four triodes, and
`varimu.sim.setup.adjust` sets B+ ADJ / BALANCE / ZERO per the manual.

A fast Rust circuit simulator (`crates/circuitsim`, ngspice stays the
reference) is planned in [docs/CIRCUIT_SIM_PLAN.md](docs/CIRCUIT_SIM_PLAN.md).
Work its milestones in order, with the same "done when" discipline.
**M0 (scaffolding), M1 (circuit IR), M2 (linear engine), M3 (devices and
Newton), M4 (the 670 slice on the fast engine), M5 (nodal DK) and M6
(default engine) are done, except M5's speed target (10x faster than
ngspice; 5-7x so far), deferred (decided 2026-10-17; the plan's M5 status
lists where to start). M7 and M8 stay deferred after Phase 2 too (decided
2026-10-21, the user delegating: nothing in main-plan Phases 3-5 needs a
second circuit or real time, and renders at 6-7x real time are workable);
next is main-plan Phase 3. Phase 2's core is in circuitsim (the circuit-sim
plan's "Phase 2 in circuitsim").** The periodic
agreement test against ngspice is
`slice_report.py --verify` (Commands); run it after changes to the engine,
the circuit or the device models. It checks behaviour (GR, attack/release)
vs production ngspice, waveforms vs exact-formulation ngspice on six short
excerpts (TC1-4 bursts, the clip's loudest and HF-richest 0.25 s), both of
those with both engines on linear cores, and the clip vs circuitsim's
converged solution with the Jiles-Atherton cores, with regression bounds a
few dB outside the measured values (re-measure them when the circuit
changes); numbers in the circuit-sim plan's M6 follow-up and "Phase 2 in
circuitsim".
**What the references are for (decided 2026-10-21):** accuracy is judged
against circuitsim's converged solution and analog behaviour; ngspice is the
independent cross-check that catches bugs, best with the exact triode
formulation on short excerpts (its tabulated triodes are only good to about
-55 dB on hot material); behaviour metrics (GR, attack/release) are compared
with production ngspice. Details: the circuit-sim plan's Verification section.
`netlist.build()` builds a typed circuit IR (`varimu/circuit/ir.py`) and emits
SPICE from it (`varimu/circuit/spice.py`); the Rust side reads the same IR as
JSON (`crates/circuitsim/src/ir.rs`) and simulates it at a fixed step
(`mna.rs`, `transient.rs`), with compiled ports of the Python device models
(`devices/`). The default solver is nodal DK (`dk.rs`): the linear part
folded into responses of the step matrix once per step size, Newton on the
22 device ports with the factored Jacobian reused and unmoved devices not
re-evaluated; `solver: mna` is M3-M4's Newton on the device-node block of the
full MNA system (`newton.rs`), the reference DK is tested against.
`Transient::update(ir)` changes component values mid-run (device state, a
core's magnetization, carries over). Transformers in the IR (v2): `Winding`s
on a core node whose voltage is B (1 V = 1 mT) and a `MagneticCore` device
on it; `netlist.build(cores="ja" | "linear")` (default `devices.cores: ja`);
a "ja" build has no SPICE text (`Circuit.text` is None), and ngspice renders
always build "linear" (`TransientSettings.cores`). `varimu.sim.fast.run_transient(ir, x)` is the Rust counterpart
of `varimu.sim.io.run_transient` (same oversampling and decimation).
Production settings are the `circuitsim` block of `config/sim_settings.yaml`:
esdirk4 at 2x, 5th-order input interpolation, local error control (chosen by
M4's method study; the plan has the numbers), DK with Newton tolerances
1e-4 / 1e-3 V (M5). `simulator.engine` picks the engine for renders,
the CLI, the listen app and `slice_report.py`: **circuitsim by default
(M6)**, ngspice by name (`--engine ngspice`). Without the `fast` extra,
renders stop with instructions (`fast.EngineUnavailable`); nothing falls back
to ngspice silently. circuitsim renders run in-process on the runner's
threads (GIL released), at the `runner:` priority (Windows thread priority),
with progress and Ctrl-C through `circuitsim.simulate(progress=...)`.

## Commands

```sh
uv sync --extra fast             # install; renders need fast (add listen|ml|optimize when a phase needs it)
uv run pytest                    # tests
uv run ruff check . && uv run ruff format --check .
uv run varimu signals [--seed N] [--only NAME ...] [--list]
uv run varimu genome-status
uv run varimu fit-devices [--only 6386 ...]   # refit device models -> config/devices/*.yaml
uv run python scripts/digitize_ge6386.py --overlays DIR   # re-digitize the 6386 sheet
uv run --extra fast varimu render --clip data/clips/x.wav --set ac_threshold=0.7 time_constant=3 --out r.wav
uv run --extra fast varimu render --signal steps_1000hz --vary time_constant=1,2,3   # parallel, cached
uv run varimu render --signal burst_1000hz_0dbfs --engine ngspice   # the reference engine
uv run --extra listen --extra fast varimu listen   # http://127.0.0.1:8765
uv run --extra fast python scripts/slice_report.py [--engine ngspice] [--clip NAME]   # curve, TC bursts, program clip -> reports/slice/
uv run --extra listen --extra fast python scripts/slice_report.py --verify   # periodic agreement test (both engines; ~70 min cold since Phase 3, ~1 min warm)
uv run --extra fast python scripts/transformer_report.py [--only t101 ...]   # each transformer standalone -> reports/transformers/
uv run python scripts/fit_core_material.py mumetall   # refit a core material's JA parameters to its datasheet figures
uv run --extra fast python scripts/calibrate_psu.py    # re-derive T302's voltage, L302's resistance, B+ ADJ from the printed/measured rails
uv run --extra fast python scripts/corner_sweep.py [--quick]   # genome corners: simulates? GR rises? quiet at idle? -> reports/corners/
uv run --extra fast varimu unit --name NAME [--genome FILE] [--set k=v ...] [--no-clips]   # Phase 4: genome -> setup -> renders -> reports/units/NAME/ (exit 2: rejected)
uv run --extra fast python scripts/plausibility_check.py [--only NAME ...]   # the checks on nominal, Phase 3's flagged and deliberately broken genomes -> reports/plausibility/
uv run --extra listen --extra fast varimu ab-prepare [--candidates NAME ...] [--swap KEY=VALUE ...] [--targets 3 6]   # Phase 5: match the pool (config/listening.yaml) on data/clips -> SQLite + reports/listening/matching.json
uv run --extra listen --extra fast varimu listen   # then http://127.0.0.1:8765/ab: blind A/B session (keys: Space, 1/2, A/B/N), ABX staircase, difference listening
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
  reference, with a test that they agree. **Exception (decided by the user
  2026-10-21): the hysteretic transformer core** has the Python reference
  and circuitsim only, with tests that they agree; ngspice cross-checks the
  rest of the circuit with the core in its linear limit in both engines
  (measurements behind it: the circuit-sim plan's Open decisions).
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
- **ngspice render speed (measured 2026-10-13; circuitsim is the default
  since M6, see below).** About **25-40x slower than
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
    the input's sample kinks and interpolate, about -55 to -75 dB re signal;
  - ngspice can stop at its first step (t = h / 100, at a bridge diode on
    T104's floating secondary) depending only on how the input is split into
    filesources (found 2026-10-23: 4 and 4.5 s renders at the default panel;
    no method, rshunt, gmin or capacitance helped). Again 2026-10-24 after
    mumetall's refit (stiffer T101 / T103 couplings): two compression-curve
    chunks stopped 9 and 59 ms into the settling in four filesources and ran in
    three or five. `run_transient` retries any stopped run once with one
    filesource more (a second stop raises).
- **Fixed-step engine accuracy (decided 2026-10-15, plan M4).** Trapezoidal
  frequency-warps the transformers' resonances (the slice peaks +10 dB near
  17 kHz from the pre-Phase 2 provisional winding capacitances; Phase 2's
  transformers moved it to 35.5 kHz, +1.4 dB, and the rerun method comparison
  kept the choice): 0.8 dB / 8 deg off at 20 kHz
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
  M6 (2026-10-21): 3.7x / 4.5x vs ngspice's 26x on the TC1 burst and the
  arpeggio clip at the report's hot front panel. Parallel circuitsim renders
  scale to ~8.5x one job's throughput at 14 jobs (the default) on this
  8-core desktop.
- **Tabulated-triode ngspice can't referee hot program material much below
  -55 dB (measured 2026-10-21, M6).** Its tables are -53 dB from the exact
  formulation where the CV swings to -84 V (the arpeggio clip at pad 0 dB,
  threshold 0.8). So waveform references use the exact formulation
  (`TransientSettings.triode_formulation="exact"`, ~800x slower than real
  time) on short excerpts; even then, on the HF-rich clip excerpt ngspice's
  own error (-61 dB, gear 4x) sets the margin, and the converged-solution
  row is the sensitive one for circuitsim regressions.
- **The compression curve renders in chunks** (`slice_report.py`: 6 steps
  plus 1 warm-up step each, in parallel), equal to the continuous staircase
  to 3e-6 dB on the current circuit. `--verify` checks that; if a circuit
  change (e.g. slow PSU or core dynamics) breaks it, lengthen the warm-up.
- **Transformer cores and ngspice (2026-10-21).** ngspice has no
  Jiles-Atherton core: it runs the cores' linear limit, emitted as coupled
  inductors with the leakage folded into the inductance matrix, eddy loss as
  a shorted turn, and `.options rshunt=1e12` (without it ngspice at reltol
  <= 1e-4 stopped within ~60 ns at the bridge on T104's floating secondary).
  Three other emissions stopped ngspice on the 670 (`varimu/circuit/spice.py`
  docstring). The SPICE text has no core nodes and no inner nodes of
  windings (`spice.spice_nodes`); `.op` comparisons pass `rshunt_ohm=None`.
  The device-stripped 670 no longer runs in ngspice's transient (its T104
  secondary floats), so "the transformers alone" are tested standalone
  (`varimu/measure/transformers.py` fixtures).
- **Core quirks (2026-10-21).** A run starts at the DC operating point with
  its first input sample: DC on T101's primary saturates its mumetall core,
  and a DC point past saturation can fail; fade excerpts in. The linear limit
  is the susceptibility at the demagnetized origin (mumetall since its
  refit: 29,300, within ~20% of its permeability at program levels, so JA and
  linear builds compress the slice's clip within 0.022 dB per 50 ms; the old
  fit's 246 made that ~2 dB).
  The core's map is piecewise smooth (substep and direction changes), so
  Jacobian tests compare it only within 10 uT of its state.
- **Mumetall at low fields (refit 2026-10-24).** The fit now has a Rayleigh
  region (`rayleigh_r_per_a_m`, `h_rayleigh_a_per_m` in its datasheet block;
  c 0.289): origin permeability 29,300, hysteresis distortion that falls with
  level (nominal unit, 1 kHz, -10 dBm: 0.012% THD, was 0.16%). The previous
  fit (c 0.00077, origin 246, H ~ sqrt(B) at program levels) caused Phase 4's
  low-level THD and a level-dependent bass response. T101's and T103's turns
  stay as derived (for 10 H / 5 H at an origin of 5,850); their linear limits
  are 17.7 H / 7.9 H, mostly the joint gap. Keep the Rayleigh targets when
  refitting: the four datasheet scalars alone gave the old fit.
- **Attack is current-limited (2026-10-23).** The 6973 pair (its zero-bias
  current at the ~150 V screen tap) sets the CV's slope into C109; the
  bridge diodes and T104's leakage don't matter. A long burst's CV keeps
  creeping at constant gain (it tracks the supply's sag), so measure attack
  against the CV a few tens of ms in (`metrics.cv_attack`), not the burst's
  end.
- **Listening renders are excerpts (Phase 5).** A GR-matched stimulus takes
  ~8-12 renders of its excerpt (the pool's `excerpt_s`, 8 s: the clip's
  loudest window); `ab-prepare` on 3 candidates x 2 clips x 2 targets is
  ~100 renders. Judgments go to data/judgments/judgments.sqlite (never
  committed); stimuli are stored per code and config version
  (`prepare.code_version`: a material refit counts), so a circuit change
  means preparing again. The listening aids (difference listening, ABX:
  `varimu.listen.difference`, `abx`) render nothing: they work on the
  matched renders in the cache. ABX judgments live in their own tables
  (`abx_*`, every trial at k != 1 flagged `exaggerated`) and are never
  preference data.
- **One render job twice at once (fixed 2026-10-24).** Two threads rendering
  the identical job (same cache key) used to share `cache/renders/<key>.tmp`
  and `cache/jobs/<key>` (WinError 32). Each render now has its own (key, pid,
  thread) names, and the second to finish keeps the first's cache entry
  (`tests/test_fast.py`). `listen.prepare` still runs a candidate's targets in
  turn: that shares the grid's renders through the cache instead of rendering
  them twice.
- **The power supply and the start of a run (Phase 3, 2026-10-21).** A run
  starts at the DC operating point with the mains sine sources at their t = 0
  value (phase 90: the peak), so the reservoirs start charged to the peak;
  renders first run `start.settle_s` = 1 s with the input held at its first
  sample (both engines, trimmed from the outputs). `--verify`'s exact-ngspice
  excerpts skip it in both engines (`EXCERPT_SETTLE_S`), and the standalone
  transformer measurements have no supply to settle. ngspice stopped ~1 ms in,
  where the GZ34 first cuts off and its leakage inductance kicks into a node
  with nothing on it, until T302's winding capacitance and the selenium cells'
  capacitance went in: keep a capacitance on every rectifier node.
- **Speed since Phase 3 (measured 2026-10-21).** circuitsim 14x slower than
  real time on the 7 s TC1 burst and 36x on the 4 s clip (Phase 2: 5.8x /
  7.3x), plus 1 s of settling per render: 45 device ports instead of 22, and
  error-control substeps at every 6973 grid clamp (pentodes have grid current
  since Phase 3; without it the 6973 grids ran to +251 V). Cold `--verify`:
  see the circuit-sim plan's "Phase 3 in circuitsim". 2026-10-23 (the
  circuit-sim plan's "Speed after Phase 3"): step selection, probe-only steps
  with the ports-and-states error norm, and AVX2 linear algebra, 1.16-1.26x
  faster at the same accuracy; the substeps are needed by accuracy (the 6973
  feedback nodes nfa / nfb), not wasted by halving. 2026-10-24, mumetall's
  refit: no change (11.8x / 24.0x against the old fit's 11.9x / 24.3x, back to
  back, one job, the 1 s of settling counted in).
- **Genomes that oscillate** (`reports/corners/summary.json`, flagged): some
  random corners oscillate at 19-30 kHz or wander at LF (weak-supply corners:
  the regulator in dropout). `varimu.measure.plausibility` rejects every one
  (`scripts/plausibility_check.py`). Its oscillation check looks for spurs away
  from the tone's harmonics: at the hottest panel the CV is still settling
  within a short step, and that modulation isn't an oscillation.
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

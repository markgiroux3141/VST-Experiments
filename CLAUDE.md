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

## Commands

```sh
uv sync                          # install (add --extra listen|ml|optimize when a phase needs it)
uv run pytest                    # tests
uv run ruff check . && uv run ruff format --check .
uv run varimu signals [--seed N] [--only NAME ...] [--list]
uv run varimu genome-status
uv run varimu fit-devices [--only 6386 ...]   # refit device models -> config/devices/*.yaml
uv run python scripts/digitize_ge6386.py --overlays DIR   # re-digitize the 6386 sheet
uv run varimu render --clip data/clips/x.wav --set ac_threshold=0.7 time_constant=3 --out r.wav
uv run varimu render --signal steps_1000hz --vary time_constant=1,2,3   # parallel, cached
uv run varimu listen             # http://127.0.0.1:8765 (needs: uv sync --extra listen)
uv run python scripts/slice_report.py       # compression curve + TC attack/release -> reports/slice/
uv run python scripts/tolerance_study.py    # solver settings vs accuracy -> reports/slice/
```

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
  - an inline PWL source breakpoints every sample (5x the timepoints).
- **Renders and the desktop.** ngspice runs at below-normal priority with one
  thread, and parallel renders default to cpu_count - 2 (`runner:` in
  `sim_settings.yaml`). Don't kill ngspice by walking up process trees: two
  renders launched from one shell share ancestors.
- **Patching files from Bash heredocs:** this shell collapses a doubled
  backslash to a single one inside heredocs, so an escaped `\n` meant for a
  Python string arrives as a real newline. Write patch scripts with the Write
  tool, not heredocs.

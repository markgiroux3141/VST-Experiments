# CLAUDE.md

The project plan is [VARIMU_PROJECT_PLAN.md](VARIMU_PROJECT_PLAN.md) (the plan's
layout calls it `PLAN.md`). Read it before starting work.

**Current phase: 1 (Device Models).** Phase 0 is done. Work one phase at a time.
Don't start the next phase until the current phase's "done when" criterion is
met and covered by tests.

## Commands

```sh
uv sync                          # install (add --extra listen|ml|optimize when a phase needs it)
uv run pytest                    # tests
uv run ruff check . && uv run ruff format --check .
uv run varimu signals [--seed N] [--only NAME ...] [--list]
uv run varimu genome-status
uv run varimu fit-devices [--only 6386 ...]   # refit device models -> config/devices/*.yaml
uv run python scripts/digitize_ge6386.py --overlays DIR   # re-digitize the 6386 sheet
```

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
- **Simulation speed (measured 2026-10-13).** One 6386 section with a 10k load,
  in a 96 kHz transient on ngspice 47, ran about 60-110x slower than real time.
  The 32-section behavioral expression is the likely cost. Options for Phase 4:
  tabulate the plate current (XSPICE 2-D table), try Xyce, cut the section
  count, or rely on the Phase 7 surrogate sooner.

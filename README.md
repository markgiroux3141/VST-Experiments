# Vari-Mu

A physically modeled Fairchild-style variable-mu tube compressor, whose
character comes from coupled circuit physics, plus a human-in-the-loop search
over physically realizable units. The full plan is in
[VARIMU_PROJECT_PLAN.md](VARIMU_PROJECT_PLAN.md).

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                      # create .venv and install varimu + dev tools
uv run pytest                # run the tests
uv run varimu signals        # generate the test signal library into data/test_signals/
uv run varimu genome-status  # list genome parameters still awaiting a sourced value
```

## Layout

| Path | Contents |
|---|---|
| `varimu/` | Python package (devices, circuit, sim, measure, listen, prefs, surrogate, optimize) |
| `config/` | `genome_bounds.yaml` (sourced physical ranges), `sim_settings.yaml` |
| `data/` | datasheets (committed), plus test signals, clips and judgments (not committed) |
| `tests/` | pytest suite |
| `assets/`, `ui-mockup/` | plugin UI art and an HTML mockup (Phase 10) |

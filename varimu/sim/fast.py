"""Audio through the Rust engine (crates/circuitsim), with varimu.sim.io's contract.

Same input and output handling as `io.run_transient`: the input is upsampled
by `settings.oversample`, simulated, and every probe is decimated back to the
input's length, with the same filters. The difference is the solver: a fixed
step of exactly 1 / sim_rate, so outputs land on the grid without
interpolation. The solver tolerances in TransientSettings are ngspice's and
don't apply; `method`, `input_order` and the error tolerances do (see
`circuitsim.simulate`).
`TransientSettings.from_sim_settings(engine="circuitsim")` gives the production
settings (sim_settings.yaml, `circuitsim` block).

Needs the `fast` extra (`uv sync --extra fast`). Tubes and diodes are solved
by Newton on the full MNA system (circuit-sim plan, M3); a step that won't
converge even after halving raises SimulationFailed naming the time and node.

A build of circuitsim older than the crate's sources (plain `uv run` after a
Rust edit doesn't rebuild) is refused: `check_build` compares the hash the
build embedded with `source_hash()` of the working tree.
"""

from __future__ import annotations

import time
from functools import cache

import numpy as np

from varimu.circuit.ir import CircuitIR
from varimu.config import REPO_ROOT
from varimu.sim.io import TransientResult, TransientSettings, decimate, upsample
from varimu.sim.ngspice import SimulationFailed

CRATE_DIR = REPO_ROOT / "crates" / "circuitsim"


class StaleBuild(RuntimeError):
    """The installed circuitsim was built from other sources than the working tree's."""


def available() -> bool:
    try:
        import circuitsim  # noqa: F401
    except ImportError:
        return False
    return True


def source_hash() -> str:
    """The crate sources' hash, computed like crates/circuitsim/build.rs: FNV-1a 64 over
    each file (Cargo.toml and src/**/*.rs, sorted by relative path) as path, 0, bytes, 0."""
    files = [CRATE_DIR / "Cargo.toml", *(CRATE_DIR / "src").rglob("*.rs")]
    named = sorted((p.relative_to(CRATE_DIR).as_posix(), p) for p in files)
    h = 0xCBF29CE484222325
    for name, path in named:
        for b in name.encode() + b"\0" + path.read_bytes() + b"\0":
            h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


@cache
def check_build() -> str:
    """The installed build's source hash; raises StaleBuild if the sources changed since."""
    import circuitsim

    built = circuitsim.SOURCE_HASH
    if CRATE_DIR.exists() and built != (now := source_hash()):
        raise StaleBuild(
            f"circuitsim was built from sources {built}, the working tree has {now}: "
            "rebuild with `uv sync --extra fast` (name every extra you use) or run "
            "through `uv run --extra fast ...`"
        )
    return built


def run_transient(
    ir: CircuitIR,
    input_v: np.ndarray,
    *,
    settings: TransientSettings | None = None,
    method: str | None = None,
) -> TransientResult:
    """Drive `ir.input_node` (to ground) with `input_v` volts; every IR probe comes back
    on the input's sample grid, keyed like ngspice vectors ("v(out)"). `method`
    overrides `settings.method`."""
    import circuitsim

    check_build()
    s = settings or TransientSettings.from_sim_settings(engine="circuitsim")
    x = np.asarray(input_v, float)
    n, k = len(x), s.oversample
    x_up = upsample(x, k)
    t0 = time.perf_counter()
    try:
        raw = circuitsim.simulate(
            ir.to_json(),
            np.ascontiguousarray(x_up),
            1.0 / s.sim_rate,
            method or s.method,
            input_order=s.input_order,
            error_abstol=s.error_abstol,
            error_reltol=s.error_reltol,
        )
    except circuitsim.SimulationError as e:
        raise SimulationFailed(str(e)) from e
    wall = time.perf_counter() - t0
    out = {p.spice: decimate(raw[p.spice], k, n) for p in ir.probes}
    return TransientResult(out, s.sample_rate, wall, len(x_up))

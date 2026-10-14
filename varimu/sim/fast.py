"""Audio through the Rust engine (crates/circuitsim), with varimu.sim.io's contract.

Same input and output handling as `io.run_transient`: the input is upsampled
by `transient.oversample`, simulated, and every probe is decimated back to the
input's length, with the same filters. The difference is the solver: a fixed
step of exactly 1 / sim_rate, so outputs land on the grid without
interpolation. The solver tolerances in TransientSettings are ngspice's and
don't apply.

Needs the `fast` extra (`uv sync --extra fast`). So far the engine is linear
only (milestone M2): circuits with tubes or diodes raise SimulationFailed.
"""

from __future__ import annotations

import time

import numpy as np

from varimu.circuit.ir import CircuitIR
from varimu.sim.io import TransientResult, TransientSettings, decimate, upsample
from varimu.sim.ngspice import SimulationFailed


def available() -> bool:
    try:
        import circuitsim  # noqa: F401
    except ImportError:
        return False
    return True


def run_transient(
    ir: CircuitIR,
    input_v: np.ndarray,
    *,
    settings: TransientSettings | None = None,
    method: str = "trap",
) -> TransientResult:
    """Drive `ir.input_node` (to ground) with `input_v` volts; every IR probe comes back
    on the input's sample grid, keyed like ngspice vectors ("v(out)")."""
    import circuitsim

    s = settings or TransientSettings.from_sim_settings()
    x = np.asarray(input_v, float)
    n, k = len(x), s.oversample
    x_up = upsample(x, k)
    t0 = time.perf_counter()
    try:
        raw = circuitsim.simulate(
            ir.to_json(), np.ascontiguousarray(x_up), 1.0 / s.sim_rate, method
        )
    except circuitsim.SimulationError as e:
        raise SimulationFailed(str(e)) from e
    wall = time.perf_counter() - t0
    out = {p.spice: decimate(raw[p.spice], k, n) for p in ir.probes}
    return TransientResult(out, s.sample_rate, wall, len(x_up))

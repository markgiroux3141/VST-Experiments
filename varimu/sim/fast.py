"""Audio through the Rust engine (crates/circuitsim), with varimu.sim.io's contract.

Same input and output handling as `io.run_transient`: the input is upsampled
by `settings.oversample`, simulated, and every probe is decimated back to the
input's length, with the same filters. The difference is the solver: a fixed
step of exactly 1 / sim_rate, so outputs land on the grid without
interpolation. TransientSettings' reltol, abstol and vntol are ngspice's and
don't apply; `method`, `solver`, `input_order`, the error tolerances and the
`newton_*` settings do (see `circuitsim.simulate`).
`TransientSettings.from_sim_settings(engine="circuitsim")` gives the production
settings (sim_settings.yaml, `circuitsim` block).

Needs the `fast` extra (`uv sync --extra fast`). Tubes and diodes are solved
by Newton on the device ports of a nodal DK system (`solver="dk"`, circuit-sim
plan M5) or on the full MNA system (`"mna"`, M3); a step that won't converge
even after halving raises SimulationFailed naming the time and the device.

circuitsim is the default engine (circuit-sim plan M6). Without the extra,
`check_build` raises EngineUnavailable, which says how to install it or to
render with ngspice instead; nothing falls back to ngspice silently. A build
of circuitsim older than the crate's sources (plain `uv run` after a Rust
edit doesn't rebuild) is refused: `check_build` compares the hash the build
embedded with `source_hash()` of the working tree.

The engine simulates on the calling thread with the GIL released, so
parallel renders are threads of one process (varimu.sim.runner);
`thread_priority` gives those threads the priority ngspice's processes get.
"""

from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cache

import numpy as np

from varimu.circuit.ir import CircuitIR
from varimu.config import REPO_ROOT
from varimu.sim.io import TransientResult, TransientSettings, decimate, upsample
from varimu.sim.ngspice import SimulationFailed

CRATE_DIR = REPO_ROOT / "crates" / "circuitsim"

MISSING = (
    "the circuitsim engine (simulator.engine's default) isn't installed: run "
    "`uv sync --extra fast` (name every extra you use, e.g. `--extra listen --extra fast`), "
    "or render with ngspice (`--engine ngspice`, or simulator.engine: ngspice in "
    "config/sim_settings.yaml)"
)


class EngineUnavailable(RuntimeError):
    """circuitsim isn't installed (the `fast` extra)."""


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
    """The installed build's source hash; raises EngineUnavailable without the extra and
    StaleBuild if the sources changed since the build."""
    try:
        import circuitsim
    except ImportError as e:
        raise EngineUnavailable(MISSING) from e

    built = circuitsim.SOURCE_HASH
    if CRATE_DIR.exists() and built != (now := source_hash()):
        raise StaleBuild(
            f"circuitsim was built from sources {built}, the working tree has {now}: "
            "rebuild with `uv sync --extra fast` (name every extra you use) or run "
            "through `uv run --extra fast ...`"
        )
    return built


# Windows thread priorities (SetThreadPriority). In a normal-class process,
# LOWEST runs at base priority 6, as a normal thread of ngspice's
# BELOW_NORMAL_PRIORITY_CLASS process does.
_THREAD_PRIORITY = {"below_normal": -2, "idle": -15}  # LOWEST, IDLE


@contextmanager
def thread_priority(priority: str) -> Iterator[None]:
    """Run the calling thread at `priority` (sim_settings runner.priority: normal |
    below_normal | idle) inside the block, then restore it. circuitsim simulates on
    the calling thread, so this is its counterpart of ngspice's process priority.
    Windows only; elsewhere a no-op (lowering a Linux thread's nice value can't be
    undone without privileges)."""
    if priority not in ("normal", *_THREAD_PRIORITY):
        raise ValueError(f"unknown priority {priority!r}")
    if priority == "normal" or sys.platform != "win32":
        yield
        return
    k32 = _kernel32()
    handle = k32.GetCurrentThread()
    old = k32.GetThreadPriority(handle)
    k32.SetThreadPriority(handle, _THREAD_PRIORITY[priority])
    try:
        yield
    finally:
        k32.SetThreadPriority(handle, old)


@cache
def _kernel32():
    """kernel32 with the thread-priority functions typed (a private instance, so the
    shared ctypes.windll function objects keep their defaults)."""
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentThread.restype = wintypes.HANDLE
    k32.GetThreadPriority.argtypes = (wintypes.HANDLE,)
    k32.GetThreadPriority.restype = ctypes.c_int
    k32.SetThreadPriority.argtypes = (wintypes.HANDLE, ctypes.c_int)
    k32.SetThreadPriority.restype = wintypes.BOOL
    return k32


def run_transient(
    ir: CircuitIR,
    input_v: np.ndarray,
    *,
    settings: TransientSettings | None = None,
    method: str | None = None,
    progress: Callable[[float], None] | None = None,
) -> TransientResult:
    """Drive `ir.input_node` (to ground) with `input_v` volts; every IR probe comes back
    on the input's sample grid, keyed like ngspice vectors ("v(out)"). `method`
    overrides `settings.method`. `progress(fraction)` is called ~200 times during
    the run; Ctrl-C stops it (KeyboardInterrupt)."""
    check_build()
    import circuitsim

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
            solver=s.solver,
            reltol=s.newton_reltol,
            vntol=s.newton_vntol,
            newton_reuse=s.newton_reuse,
            input_order=s.input_order,
            error_abstol=s.error_abstol,
            error_reltol=s.error_reltol,
            progress=progress,
        )
    except circuitsim.SimulationError as e:
        raise SimulationFailed(str(e)) from e
    wall = time.perf_counter() - t0
    out = {p.spice: decimate(raw[p.spice], k, n) for p in ir.probes}
    return TransientResult(out, s.sample_rate, wall, len(x_up))

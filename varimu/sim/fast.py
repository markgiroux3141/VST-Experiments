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
import dataclasses
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import cache

import numpy as np

from varimu.circuit.ir import CircuitIR
from varimu.config import REPO_ROOT
from varimu.sim.io import (
    GROUP_BREAK,
    TransientResult,
    TransientSettings,
    decimate,
    resample,
    upsample,
    with_settle,
)
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
    each file (Cargo.toml and src/**/*.rs, then the GPU kernel's crate crates/tapegpu's
    Cargo.toml and src/**/*.{rs,wgsl} named "tapegpu/<path>"; sorted by name) as name, 0,
    bytes, 0."""
    files = [CRATE_DIR / "Cargo.toml", *(CRATE_DIR / "src").rglob("*.rs")]
    named = [(p.relative_to(CRATE_DIR).as_posix(), p) for p in files]
    gpu = CRATE_DIR.parent / "tapegpu"
    gfiles = [gpu / "Cargo.toml", *(gpu / "src").rglob("*.rs"), *(gpu / "src").rglob("*.wgsl")]
    named = sorted(named + [("tapegpu/" + p.relative_to(gpu).as_posix(), p) for p in gfiles])
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


def partition_sections(ir: CircuitIR, s: TransientSettings) -> list[str]:
    """The sections of `ir` that `s.partition` puts on other threads (the titles the
    circuit has with elements in them, groups separated by GROUP_BREAK, empty groups
    dropped; none if that would leave nothing besides them). A section a switch has
    emptied (the tube synth's LFO turned off) gets no thread."""
    titles = [sec.title for sec in ir.sections if sec.elements]
    groups: list[list[str]] = [[]]
    for t in s.partition:
        if t == GROUP_BREAK:
            groups.append([])
        elif t in titles:
            groups[-1].append(t)
    groups = [g for g in groups if g]
    if sum(len(g) for g in groups) >= len(titles):
        return []
    out: list[str] = []
    for g in groups:
        if out:
            out.append(GROUP_BREAK)
        out.extend(g)
    return out


def control_streams(
    ir: CircuitIR,
    controls: Mapping[str, np.ndarray] | None,
    n: int,
    n0: int,
    rate: int,
    sim_rate: int,
    n_sim: int,
) -> list[np.ndarray]:
    """The IR's control inputs (IR order) on the simulation's grid: each of `controls`
    ({name: volts at `rate`}, `n` samples) behind `n0` samples of its first value,
    interpolated linearly onto `n_sim` samples at `sim_rate` (held past its end)."""
    controls = dict(controls or {})
    names = [c.name for c in ir.controls]
    if set(controls) != set(names):
        raise ValueError(f"control inputs {sorted(controls)} for the circuit's {names}")
    t_in = np.arange(n0 + n) / rate
    t_sim = np.arange(n_sim) / sim_rate
    out = []
    for name in names:
        c = np.asarray(controls[name], float)
        if len(c) != n:
            raise ValueError(f"control {name}: {len(c)} samples for {n} of input")
        c = np.concatenate([np.full(n0, c[0] if n else 0.0), c])
        out.append(np.ascontiguousarray(np.interp(t_sim, t_in, c)))
    return out


def note_steps(
    notes: Sequence[tuple[float, str, int, int]] | None, n0: int, s: TransientSettings
) -> list[tuple[int, str, int, int]]:
    """Note events (seconds from the input's start) as circuitsim takes them: sample
    indices on the simulation's grid, behind `n0` samples of settle at the sample rate."""
    out = []
    for t_s, kind, note, value in notes or ():
        at = round((n0 / s.sample_rate + t_s) * s.sim_rate)
        out.append((int(at), str(kind), int(note), int(value)))
    if any(b[0] < a[0] for a, b in zip(out, out[1:], strict=False)):
        raise ValueError("note events must come in order of their times")
    return out


def run_transient(
    ir: CircuitIR,
    input_v: np.ndarray,
    *,
    settings: TransientSettings | None = None,
    method: str | None = None,
    progress: Callable[[float], None] | None = None,
    controls: Mapping[str, np.ndarray] | None = None,
    stats: dict | None = None,
    notes: Sequence[tuple[float, str, int, int]] | None = None,
    origin_s: float = 0.0,
) -> TransientResult:
    """Drive `ir.input_node` (to ground) with `input_v` volts; every IR probe comes back
    on the input's sample grid, keyed like ngspice vectors ("v(out)"). `method`
    overrides `settings.method`. `progress(fraction)` is called ~200 times during
    the run; Ctrl-C stops it (KeyboardInterrupt). `controls` drives the IR's control
    inputs ({name: volts}, each as long as `input_v`): held at their first sample while
    the circuit settles, and linear between samples at every rate (a gate's step stays a
    step, where band-limited resampling would ring). `stats`: a dict to fill with the
    engine's statistics of the run (circuitsim.simulate's). `notes` play the IR's media
    played by keys (a harp, docs/RHODES_PLAN.md RH3; a Clavinet's strings, CL3): (seconds
    from the input's start, "on" | "off" | "pedal" | "pressure", MIDI note, velocity, pedal
    0 / 1 or pressure 0-127), in order; each lands on
    the simulation's grid behind the settle (silent while the circuit settles).
    `origin_s`: the input starts that many seconds into a longer input (circuitsim's
    `origin_samples`: the mains' phase, the noise streams, a tape's transport and grain
    continue that run; the settle in front is that run's too), for `run_transient_chunked`."""
    check_build()
    import circuitsim

    s = settings or TransientSettings.from_sim_settings(engine="circuitsim")
    if ir.heaters is not None and ir.heaters.start == "cold":
        # A cold start is the power-on: its warm-up from the first sample, no settle.
        s = dataclasses.replace(s, settle_s=0.0)
    x, n0 = with_settle(np.asarray(input_v, float), s)
    n, k = len(x), s.oversample
    # At a host rate of its own (s.host_rate) the input goes there and the outputs
    # come back to sample_rate.
    xh = resample(x, s.sample_rate, s.host)
    x_up = upsample(xh, k)
    ctl = control_streams(ir, controls, len(input_v), n0, s.sample_rate, s.sim_rate, len(x_up))
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
            step_selection=s.step_selection,
            error_norm=s.error_norm,
            tube_tables=s.tube_tables,
            partition=partition_sections(ir, s) or None,
            partition_coupling=s.partition_coupling,
            progress=progress,
            controls=ctl or None,
            stats=stats is not None,
            notes=note_steps(notes, n0, s) or None,
            **({"origin_samples": round(origin_s * s.sim_rate)} if origin_s else {}),
            **({"tape_gpu": True} if s.tape_gpu else {}),
            **({"hard_step_iterations": s.hard_step_iterations} if s.hard_step_iterations else {}),
        )
    except circuitsim.SimulationError as e:
        raise SimulationFailed(str(e)) from e
    wall = time.perf_counter() - t0
    if stats is not None:
        raw, st = raw
        stats.update(st)

    def back(v: np.ndarray) -> np.ndarray:
        return resample(decimate(v, k, len(xh)), s.host, s.sample_rate)[:n][n0:]

    out = {p.spice: back(raw[p.spice]) for p in ir.probes}
    return TransientResult(out, s.sample_rate, wall, len(x_up))


def run_transient_chunked(
    ir: CircuitIR,
    input_v: np.ndarray,
    *,
    settings: TransientSettings | None = None,
    chunk_s: float = 20.0,
    warmup_s: float = 2.0,
    fade_s: float = 0.01,
    workers: int = 4,
    progress: Callable[[float], None] | None = None,
) -> TransientResult:
    """`run_transient` in pieces of `chunk_s` seconds run at once on `workers` threads
    (TAPE_SPEED_PLAN.md P3: a long offline print in a fraction of the wall time).

    Each piece starts `warmup_s` early (the input faded in over its first 50 ms or half, after the
    usual settle) at its place in the whole run (`origin_s`: the mains, the noise, a tape's
    transport and grain continue the whole run's), and runs `fade_s` past its end, where
    the next piece takes over through a raised-cosine crossfade. The warm-up must cover
    the circuit's memory of its input: its supply's and coupling capacitors' settling, a
    tape's head distance and its playback EQ's bass. What a piece can't continue is the
    state the warm-up doesn't bring back: a free oscillator's phase (the Ampex 351's bias:
    compare pieces with the whole in band levels, not waveforms), a tape's grain cells
    (the same coating, cells a flutter's integral apart). No control inputs or notes."""
    s = settings or TransientSettings.from_sim_settings(engine="circuitsim")
    x = np.asarray(input_v, float)
    fs, n = s.sample_rate, len(x)
    c, w, f = round(chunk_s * fs), round(warmup_s * fs), max(1, round(fade_s * fs))
    ramp = min(w // 2, round(0.05 * fs))
    # Past what a piece keeps, so the resampling filters' edges fall outside it.
    tail = round(0.02 * fs)
    if c <= f:
        raise ValueError("run_transient_chunked: chunk_s must exceed fade_s")
    starts = list(range(0, n, c))
    done = np.zeros(len(starts))
    lock = threading.Lock()

    def piece(j: int) -> tuple[int, int, dict[str, np.ndarray], float]:
        s0 = starts[j]
        a, b = max(0, s0 - w), min(n, s0 + c + f + tail)
        keep = min(n, s0 + c + f) - a
        u = x[a:b].copy()
        if a > 0 and ramp:
            u[:ramp] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp) / ramp)

        def prog(frac: float) -> None:
            if progress is not None:
                with lock:
                    done[j] = frac * (b - a)
                    progress(float(done.sum()) / sum(min(n, q + c + f + tail) - max(0, q - w)
                                                     for q in starts))  # fmt: skip

        r = run_transient(ir, u, settings=s, progress=prog, origin_s=a / fs)
        return a, s0, {k: v[s0 - a : keep] for k, v in r.vectors.items()}, r.wall_s

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max(1, workers)) as ex:
        pieces = list(ex.map(piece, range(len(starts))))
    names = pieces[0][2].keys()
    out = {k: np.zeros(n) for k in names}
    up = 0.5 - 0.5 * np.cos(np.pi * (np.arange(f) + 0.5) / f)
    for j, (_, s0, vec, _) in enumerate(pieces):
        for k in names:
            v = vec[k]
            if j == 0:
                out[k][s0 : s0 + len(v)] = v
                continue
            m = min(f, len(v))
            out[k][s0 : s0 + m] = out[k][s0 : s0 + m] * (1.0 - up[:m]) + v[:m] * up[:m]
            out[k][s0 + m : s0 + len(v)] = v[m:]
    wall = time.perf_counter() - t0
    return TransientResult(out, fs, wall, 0)

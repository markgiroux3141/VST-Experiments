"""Audio through an ngspice transient: samples -> file source -> transient -> samples.

How audio gets in and out (measured on ngspice 47, see CLAUDE.md):

- Input is an XSPICE `filesource`: an ASCII (time, value) table that ngspice
  interpolates linearly. The newer `file(...) snd(...)` WAV source also works,
  but its interpolation isn't documented. An inline PWL source puts a
  breakpoint on every sample, which costs about 5x the timepoints.
- Loading a filesource is quadratic in its length (1 M lines 6 s, 4.9 M lines
  140 s), so the input is split into chunks of CHUNK_LINES, one filesource
  each, in series. Each chunk ramps to zero one sample outside its window, so
  the sum is exactly the piecewise-linear signal through every sample.
- No breakpoints means the solver's timepoints don't land on the sample grid.
  Linear interpolation on both sides then loses some high end, so the input is
  band-limited upsampled by `transient.oversample` first. The output is
  interpolated onto the oversampled grid here and decimated with an anti-alias
  filter. That also keeps harmonics the circuit makes above Nyquist from
  aliasing.
- Don't use `.options interp`. In ngspice 47 it freezes the output values once
  the solver takes steps shorter than TSTEP (seen with a filesource into an RC).
- Output is a binary rawfile written incrementally in batch mode (`-r`), so a
  caller can follow its last timestamp for progress. Batch mode ignores
  `.options filetype`, so a `.spiceinit` in the job directory sets it.
- The simulator runs at reduced OS priority with one OpenMP thread (runner
  section of sim_settings.yaml), so renders don't take over the desktop.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from math import gcd
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from varimu.config import SimSettings, load_sim_settings
from varimu.sim.ngspice import SimulationFailed, find_ngspice

INPUT_FILE = "in{}.txt"  # one per chunk
CHUNK_LINES = 250_000
RAW_FILE = "out.raw"
NETLIST_FILE = "in.cir"
LOG_FILE = "ngspice.log"


# --- Settings ---------------------------------------------------------------------


ENGINES = ("ngspice", "circuitsim")


def configured_engine(s: SimSettings | None = None) -> str:
    """sim_settings.yaml simulator.engine (circuitsim when absent)."""
    s = s or load_sim_settings()
    engine = str(s.data.get("simulator", {}).get("engine", "circuitsim"))
    if engine not in ENGINES:
        raise ValueError(f"simulator.engine must be one of {ENGINES}, got {engine!r}")
    return engine


@dataclass(frozen=True)
class TransientSettings:
    sample_rate: int
    oversample: int
    full_scale_volts_peak: float
    reltol: float
    abstol: float
    vntol: float
    method: str  # ngspice: trap | gear; circuitsim: see circuitsim.simulate
    threads: int = 1  # ngspice OpenMP threads per job
    priority: str = "below_normal"  # normal | below_normal | idle
    engine: str = "ngspice"  # ngspice | circuitsim
    # How triode plate currents reach SPICE (devices.triode_formulation): table | exact.
    # ngspice only; circuitsim always evaluates the analytic models.
    triode_formulation: str = "table"
    # Transformer cores the circuit is built with (devices.cores): ja | linear. ngspice
    # always runs "linear" (no SPICE core); circuitsim takes the configured model.
    cores: str = "linear"
    input_order: int = 1  # circuitsim only: input interpolation at stage times
    error_abstol: float = 0.0  # circuitsim only: local error control (0 = off), V
    error_reltol: float = 0.0  # circuitsim only: ... plus this times |v|
    solver: str = "dk"  # circuitsim only: dk | mna
    newton_reltol: float = 1e-6  # circuitsim only: Newton's update tolerance, relative
    newton_vntol: float = 1e-6  # circuitsim only: ... plus this, V
    newton_reuse: bool = True  # circuitsim only: lagged Jacobian and device bypass (dk)
    # Seconds run before the input starts, with the input held at its first sample
    # (start.settle_s): the power supply settles from its DC operating point (mains
    # at its peak) into its ripple. Both engines; the outputs leave it out.
    settle_s: float = 0.0

    @classmethod
    def from_sim_settings(
        cls, s: SimSettings | None = None, engine: str = "ngspice"
    ) -> TransientSettings:
        """The settings for `engine` ("configured" = simulator.engine, which renders
        use). The default is ngspice's, for the ngspice-specific callers
        (`run_transient` here, agreement tests). circuitsim takes its oversampling
        and method from the `circuitsim` block; reltol, abstol and vntol stay
        ngspice's and don't apply to it."""
        s = s or load_sim_settings()
        if engine == "configured":
            engine = configured_engine(s)
        if engine not in ENGINES:
            raise ValueError(f"unknown engine {engine!r} ({' | '.join(ENGINES)})")
        tr, audio = s.data["transient"], s.data["audio"]
        runner = s.data.get("runner", {})
        st = cls(
            sample_rate=s.sample_rate,
            oversample=int(tr["oversample"]),
            full_scale_volts_peak=float(audio["full_scale_volts_peak"]),
            reltol=float(tr["reltol"]),
            abstol=float(tr["abstol"]),
            vntol=float(tr["vntol"]),
            method=str(tr["method"]),
            threads=int(runner.get("threads_per_job", 1)),
            priority=str(runner.get("priority", "below_normal")),
            triode_formulation=str(s.data["devices"]["triode_formulation"]),
            settle_s=float(s.data.get("start", {}).get("settle_s", 0.0)),
        )
        if engine == "circuitsim":
            cs = s.data["circuitsim"]
            st = replace(
                st,
                engine=engine,
                oversample=int(cs["oversample"]),
                method=str(cs["method"]),
                input_order=int(cs.get("input_order", 1)),
                error_abstol=float(cs.get("error_abstol", 0.0)),
                error_reltol=float(cs.get("error_reltol", 0.0)),
                solver=str(cs.get("solver", "dk")),
                newton_reltol=float(cs.get("newton_reltol", 1e-6)),
                newton_vntol=float(cs.get("newton_vntol", 1e-6)),
                newton_reuse=bool(cs.get("newton_reuse", True)),
                cores=str(s.data["devices"].get("cores", "ja")),
            )
        return st

    @property
    def sim_rate(self) -> int:
        return self.sample_rate * self.oversample

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Oversampling and settling (shared by both engines) ---------------------------


def with_settle(x: np.ndarray, s: TransientSettings) -> tuple[np.ndarray, int]:
    """`x` with `s.settle_s` of its first sample in front, and how many samples that is
    (the outputs drop them)."""
    n0 = round(s.settle_s * s.sample_rate)
    if n0 <= 0 or len(x) == 0:
        return x, 0
    return np.concatenate([np.full(n0, x[0]), x]), n0


def upsample(x: np.ndarray, k: int) -> np.ndarray:
    """Band-limited upsampling of the input to the simulation rate."""
    return resample_poly(x, k, 1) if k > 1 else x


def decimate(v: np.ndarray, k: int, n: int) -> np.ndarray:
    """Anti-aliased decimation of a simulated vector back to n output samples."""
    if k > 1:
        v = resample_poly(v, 1, k, padtype="edge")
    return v[:n]


# --- Audio files ------------------------------------------------------------------


def load_audio(path: Path, sample_rate: int) -> np.ndarray:
    """Read any soundfile-readable file as mono float64 at `sample_rate`.

    Channels are averaged. Resampling is polyphase (band-limited).
    """
    x, rate = sf.read(path, dtype="float64", always_2d=True)
    x = x.mean(axis=1)
    if rate != sample_rate:
        g = gcd(rate, sample_rate)
        x = resample_poly(x, sample_rate // g, rate // g)
    return x


def write_audio(path: Path, x: np.ndarray, sample_rate: int) -> None:
    """Mono float32 WAV (CLAUDE.md conventions)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.asarray(x, dtype="<f4"), sample_rate, subtype="FLOAT")


# --- ngspice files ----------------------------------------------------------------


def write_filesource(path: Path, t: np.ndarray, values: np.ndarray) -> None:
    """(time, value) table for an XSPICE filesource. CRLF line endings, as Windows expects."""
    np.savetxt(path, np.column_stack([t, values]), fmt=("%.15g", "%.12g"), newline="\r\n")


def input_chunks(x: np.ndarray, rate: float, chunk: int | None = None):
    """(times, values) per filesource chunk; the chunks sum to x's linear interpolation.

    Chunk k holds samples [a, b). Outside them it is zero, reached by a ramp
    to the neighbouring sample time, so adjacent chunks' ramps add up to the
    straight segment between x[b-1] and x[b]. A filesource holds its first
    value before its first point, so later chunks also start with (0, 0).
    It does not hold its last value: past the last entry it reads 0 (ngspice 47),
    and the final timepoint can land a rounding error past it. So the last
    chunk ends with an extra point one sample after the end, holding x[-1].
    """
    n, chunk = len(x), chunk or CHUNK_LINES
    out = []
    for a in range(0, n, chunk):
        b = min(a + chunk, n)
        idx, vals = np.arange(a, b), x[a:b]
        if a > 0:
            idx, vals = np.concatenate([[a - 1], idx]), np.concatenate([[0.0], vals])
        if b < n:
            idx, vals = np.concatenate([idx, [b]]), np.concatenate([vals, [0.0]])
        else:
            idx, vals = np.concatenate([idx, [n]]), np.concatenate([vals, [x[-1]]])
        t = idx / rate
        if a > 1:
            t, vals = np.concatenate([[0.0], t]), np.concatenate([[0.0], vals])
        out.append((t, vals))
    return out


def write_input_chunks(directory: Path, x: np.ndarray, rate: float) -> list[str]:
    names = []
    for k, (t, v) in enumerate(input_chunks(x, rate)):
        name = INPUT_FILE.format(k)
        write_filesource(directory / name, t, v)
        names.append(name)
    return names


def read_raw(path: Path) -> dict[str, np.ndarray]:
    """Read a real-valued binary ngspice rawfile. Keys are the lower-cased vector names."""
    data = path.read_bytes()
    marker = b"Binary:\n"
    idx = data.find(marker)
    if idx < 0:
        raise SimulationFailed(f"{path}: not a binary rawfile")
    header = data[:idx].decode("latin-1").splitlines()
    nvars = npts = None
    names: list[str] = []
    for i, line in enumerate(header):
        key, _, val = line.partition(":")
        if key == "Flags" and "complex" in val:
            raise SimulationFailed(f"{path}: complex rawfiles are not supported")
        if key == "No. Variables":
            nvars = int(val)
        elif key == "No. Points":
            npts = int(val)
        elif key == "Variables":
            names = [header[i + 1 + j].split()[1].lower() for j in range(nvars or 0)]
    if not nvars or npts is None or len(names) != nvars:
        raise SimulationFailed(f"{path}: malformed rawfile header")
    body = data[idx + len(marker) :]
    npts = min(npts, len(body) // (8 * nvars))  # tolerate a run that stopped early
    arr = np.frombuffer(body, dtype="<f8", count=npts * nvars).reshape(npts, nvars)
    return {n: arr[:, k].copy() for k, n in enumerate(names)}


# --- Transient run ----------------------------------------------------------------


@dataclass
class TransientResult:
    vectors: dict[str, np.ndarray]  # each on the output sample grid, same length as the input
    sample_rate: int
    wall_s: float
    sim_points: int  # timepoints the solver accepted

    @property
    def duration_s(self) -> float:
        return len(next(iter(self.vectors.values()))) / self.sample_rate

    @property
    def realtime_factor(self) -> float:
        """Wall-clock seconds per second of audio."""
        return self.wall_s / self.duration_s


def _place(dst: Path, src: Path | str) -> None:
    dst.unlink(missing_ok=True)
    if isinstance(src, str):
        dst.write_text(src, encoding="utf-8")
        return
    try:
        os.link(src, dst)  # no copy: tables are megabytes and are reused by every job
    except OSError:
        shutil.copyfile(src, dst)


def _priority_kwargs(priority: str) -> dict[str, Any]:
    """Popen arguments that lower the simulator's CPU priority, so the desktop stays usable."""
    if priority == "normal":
        return {}
    if priority not in ("below_normal", "idle"):
        raise ValueError(f"unknown priority {priority!r}")
    if sys.platform == "win32":
        flag = (
            subprocess.IDLE_PRIORITY_CLASS
            if priority == "idle"
            else subprocess.BELOW_NORMAL_PRIORITY_CLASS
        )
        return {"creationflags": flag}
    nice = 19 if priority == "idle" else 10
    return {"preexec_fn": lambda: os.nice(nice)}


def _input_sources(input_node: str, chunks: Sequence[str]) -> str:
    """Filesources in series from input_node to ground, one per chunk file."""
    nodes = [input_node] + [f"audio_in_{k}" for k in range(1, len(chunks))] + ["0"]
    lines = []
    for k, name in enumerate(chunks):
        lines.append(f"a_audio_in{k} %vd([{nodes[k]} {nodes[k + 1]}]) audio_fsrc{k}")
        lines.append(f'.model audio_fsrc{k} filesource(file="{name}" amploffset=[0] amplscale=[1])')
    return "\n".join(lines) + "\n"


def _deck(
    netlist: str,
    input_node: str,
    save: Sequence[str],
    s: TransientSettings,
    t_end: float,
    chunks: Sequence[str],
    max_step_div: int = 1,
    grid_breakpoints: bool = False,
) -> str:
    dt = 1.0 / s.sim_rate
    # A pulse with corners every dt / 2 on an isolated node: its breakpoints put
    # a timepoint on every sample, so the output needs no interpolation.
    brk = (
        f"Vgrid_brk grid_brk 0 PULSE(0 1 0 {dt / 2:.17g} {dt / 2:.17g} 0 {dt:.17g})\n"
        f"Rgrid_brk grid_brk 0 1k\n"
        if grid_breakpoints
        else ""
    )
    return (
        f"{netlist.rstrip()}\n"
        f"* --- audio input (varimu.sim.io) ---\n"
        f"{_input_sources(input_node, chunks)}"
        f"{brk}"
        f".options reltol={s.reltol:g} abstol={s.abstol:g} vntol={s.vntol:g} method={s.method}\n"
        f".save {' '.join(save)}\n"
        f".tran {dt:.17g} {t_end:.17g} 0 {dt / max_step_div:.17g}\n"
        f".end\n"
    )


def _last_time(raw: Path, ncols: int) -> float | None:
    """Timestamp of the last complete row of a rawfile that ngspice is still writing."""
    try:
        with open(raw, "rb") as f:
            head = f.read(8192)
            i = head.find(b"Binary:\n")
            if i < 0:
                return None
            start = i + 8
            rows = (f.seek(0, 2) - start) // (8 * ncols)
            if rows < 1:
                return None
            f.seek(start + (rows - 1) * 8 * ncols)
            return float(np.frombuffer(f.read(8), "<f8")[0])
    except OSError:
        return None


def run_transient(
    netlist: str,
    input_v: np.ndarray,
    *,
    input_node: str,
    save: Sequence[str],
    settings: TransientSettings | None = None,
    workdir: Path | None = None,
    progress: Callable[[float], None] | None = None,
    timeout_s: float | None = None,
    files: Mapping[str, Path | str] | None = None,
    max_step_div: int = 1,
    grid_breakpoints: bool = False,
) -> TransientResult:
    """Drive `input_node` (to ground) with `input_v` volts and run a transient.

    `netlist` is the circuit body without analysis or `.end` lines.
    `input_v` is sampled at settings.sample_rate. Every vector in `save` comes
    back on the same grid with the same length. `progress` is called with a
    fraction in [0, 1] while the simulator runs. `workdir` keeps the job files
    for inspection; by default a temporary directory is used and removed.
    `files` are placed next to the netlist under the given names, e.g. device
    tables: a Path is hard-linked (copied if linking fails), a str is written.

    Reference runs (agreement tests): `max_step_div` caps ngspice's step at
    1 / (sim_rate * max_step_div), and `grid_breakpoints` forces a timepoint
    on every sample. Without them ngspice's timepoints straddle the sample
    grid, where the piecewise-linear input has its kinks, and the output is
    interpolated: about -55 to -75 dB re signal on small linear circuits at
    tight reltol (measured 2026-10-14, see tests/test_circuitsim_linear.py).
    """
    s = settings or TransientSettings.from_sim_settings()
    x, n0 = with_settle(np.asarray(input_v, float), s)
    n, k = len(x), s.oversample
    x_up = upsample(x, k)
    n_up = len(x_up)
    t_end = (n_up - 1) / s.sim_rate

    with tempfile.TemporaryDirectory() as td:
        wd = Path(workdir) if workdir else Path(td)
        wd.mkdir(parents=True, exist_ok=True)
        chunks = write_input_chunks(wd, x_up, s.sim_rate)
        for name, src in (files or {}).items():
            _place(wd / name, src)
        # spinit sets num_threads=8 (OpenMP); one per job is enough for these circuits.
        (wd / ".spiceinit").write_text(
            f"set filetype=binary\nset num_threads={s.threads}\n", encoding="utf-8"
        )
        deck = _deck(netlist, input_node, save, s, t_end, chunks, max_step_div, grid_breakpoints)
        (wd / NETLIST_FILE).write_text("* varimu transient\n" + deck, encoding="utf-8")
        raw = wd / RAW_FILE
        raw.unlink(missing_ok=True)

        t0 = time.perf_counter()
        with open(wd / LOG_FILE, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [str(find_ngspice()), "-b", "-r", RAW_FILE, NETLIST_FILE],
                cwd=wd,
                stdout=log,
                stderr=subprocess.STDOUT,
                **_priority_kwargs(s.priority),
            )
            try:
                while proc.poll() is None:
                    if timeout_s is not None and time.perf_counter() - t0 > timeout_s:
                        raise SimulationFailed(f"ngspice timed out after {timeout_s:.0f} s")
                    if progress:
                        t_now = _last_time(raw, len(save) + 1)
                        if t_now is not None:
                            progress(min(max(t_now / t_end, 0.0), 1.0))
                    time.sleep(0.25)
            finally:
                # Never leave a simulator running behind an exception (timeout, Ctrl-C, ...).
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        wall = time.perf_counter() - t0

        log_text = (wd / LOG_FILE).read_text(encoding="utf-8", errors="replace")
        if not raw.exists():
            raise SimulationFailed(f"ngspice wrote no output:\n{log_text[-3000:]}")
        vec = read_raw(raw)

    t = vec.pop("time")
    if len(t) == 0 or t[-1] < t_end * (1 - 1e-9):
        raise SimulationFailed(
            f"transient stopped at t={t[-1] if len(t) else 0:.6g} s of {t_end:.6g} s:\n"
            f"{log_text[-3000:]}"
        )
    grid = np.arange(n_up) / s.sim_rate
    out: dict[str, np.ndarray] = {}
    for name in save:
        out[name] = decimate(np.interp(grid, t, vec[name.lower()]), k, n)[n0:]
    if progress:
        progress(1.0)
    return TransientResult(out, s.sample_rate, wall, len(t))

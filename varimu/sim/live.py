"""Real-time playback: a clip looped through the circuit while its knobs turn
(CIRCUIT_SIM_PLAN.md M8; the listen app's Play page drives it).

A `Live` session runs a `circuitsim.Stream` at a quality fast enough for real time
(draft-1x by default: a 48 kHz host at 1x, the supplies on a second thread; the
user's choice for playing, the final render being production) and hands out its
output in blocks at the host rate. The clip is resampled to the host rate once,
and looped with a short crossfade over the seam.

Knob changes (`set`) are built into a circuit IR on a thread of their own (a build
takes tens of ms) and the newest is handed to the stream at the next block: the
same circuit with other values updates it in place (`Stream.update`); a change of
structure (the input pad's 0 dB end, Time Constant 5-6: other nodes or elements)
starts a new stream in the background, settled like a render's start, and the
output crossfades to it over one block.

`next_block(n)` must keep up with real time on average (the caller's buffer
absorbs the rest): the draft-1x 670 runs at ~0.85x real time on two cores.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from varimu.circuit import spec
from varimu.circuit.ir import CircuitIR
from varimu.sim import fast, runner
from varimu.sim.io import TransientSettings, full_scale, resample

LOOP_FADE_S = 0.01  # the loop's seam: the end crossfades into the start


@dataclass
class Meter:
    """One block's levels: output vs input (dB, rms) and the control voltage."""

    gain_db: float
    out_dbfs: float
    cv_v: float | None
    load: float  # compute time / audio time of the block


def structure(ir: CircuitIR) -> tuple:
    """What a stream can't change in place: its elements (kind, name) and nodes."""
    els = [e for s in ir.sections for e in s.elements]
    names = frozenset((type(e).__name__, e.name) for e in els)
    nodes = frozenset(n for e in els for n in _nodes(e))
    return names, nodes


def _nodes(e: Any) -> list[str]:
    for attrs in (("nodes",), ("a", "b"), ("pos", "neg")):
        if all(hasattr(e, a) for a in attrs):
            vals = [getattr(e, a) for a in attrs]
            return list(vals[0]) if attrs == ("nodes",) else vals
    return []


def make_loop(x: np.ndarray, rate: int) -> np.ndarray:
    """`x` as a loop: its last LOOP_FADE_S crossfaded into its start."""
    n = min(int(LOOP_FADE_S * rate), len(x) // 4)
    if n < 2:
        return x.copy()
    y = x[: len(x) - n].copy()
    w = np.linspace(0.0, 1.0, n)
    y[:n] = x[:n] * w + x[len(x) - n :] * (1 - w)
    return y


class Live:
    """A clip looped through the circuit in real time, its values changeable."""

    def __init__(
        self,
        clip: np.ndarray,
        overrides: dict[str, Any],
        *,
        circuit: str | Path | None = None,
        quality: str = "draft-1x",
        settings: TransientSettings | None = None,
    ):
        s = settings or TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
        if s.engine != "circuitsim" or s.oversample != 1:
            raise ValueError("live playback runs circuitsim at 1x (a quality with oversample 1)")
        fast.check_build()
        self.s, self.circuit = s, circuit
        # The circuit's volts at full scale in and out (its file's, or sim_settings').
        file_spec = None if circuit is None else spec.load_circuit(runner.circuit_file(circuit))
        self.v_in, self.v_out = full_scale(s, file_spec)
        self.rate = s.host
        x = resample(np.asarray(clip, float), s.sample_rate, self.rate)
        if len(x) < self.rate // 10:
            raise ValueError("the loop is shorter than 0.1 s")
        self.loop = make_loop(x, self.rate)
        self.pos = 0
        self.overrides = dict(overrides)
        ir = self._build(self.overrides)
        self._structure = structure(ir)
        self.stream = self._new_stream(ir, self.loop[0])
        self._fade: Any = None  # a new stream to crossfade to
        self._wanted: dict[str, Any] | None = None
        self._ready: queue.Queue = queue.Queue()
        self._wake = threading.Event()
        self._closed = False
        self.error: str | None = None
        self.restarts = 0
        self._builder = threading.Thread(target=self._build_loop, name="live builds", daemon=True)
        self._builder.start()

    # --- Circuit and stream ------------------------------------------------------------

    def _build(self, overrides: dict[str, Any]) -> CircuitIR:
        job = runner.RenderJob(np.zeros(1), overrides, circuit=self.circuit)
        return runner.build_circuit(job, self.s).ir

    def _new_stream(self, ir: CircuitIR, u0: float):
        """A stream at the DC point with input `u0`, settled for the run's settle_s
        with the input held (as a render starts)."""
        import circuitsim

        s, v = self.s, self.v_in
        st = circuitsim.Stream(
            ir.to_json(),
            1.0 / s.sim_rate,
            u0 * v,
            s.method,
            solver=s.solver,
            reltol=s.newton_reltol,
            vntol=s.newton_vntol,
            input_order=s.input_order,
            newton_reuse=s.newton_reuse,
            tube_tables=s.tube_tables,
            partition=fast.partition_sections(ir, s) or None,
            partition_coupling=s.partition_coupling,
        )
        n0 = int(s.settle_s * self.rate)
        if n0:
            st.process(np.full(n0, u0 * v))
        return st

    def _build_loop(self) -> None:
        """Build the newest wanted values into an update or a settled new stream."""
        while not self._closed:
            self._wake.wait(0.2)
            self._wake.clear()
            wanted, self._wanted = self._wanted, None
            if wanted is None or self._closed:
                continue
            try:
                ir = self._build(wanted)
                if structure(ir) == self._structure:
                    self._ready.put(("update", ir, wanted))
                else:
                    stream = self._new_stream(ir, self.loop[self.pos % len(self.loop)])
                    self._ready.put(("restart", (stream, structure(ir)), wanted))
            except Exception as e:  # shown to the player; the stream plays on unchanged
                self.error = f"{type(e).__name__}: {e}"[-500:]

    def set(self, overrides: dict[str, Any]) -> None:
        """New values (all of them, as for a render): built in the background, the
        newest applied at a coming block."""
        self._wanted = dict(overrides)
        self._wake.set()

    # --- Audio -------------------------------------------------------------------------

    def _input(self, n: int) -> np.ndarray:
        idx = (self.pos + np.arange(n)) % len(self.loop)
        self.pos = (self.pos + n) % len(self.loop)
        return self.loop[idx]

    def next_block(self, n: int) -> tuple[np.ndarray, Meter]:
        """The next `n` output samples (float32, full scale 1.0, at `self.rate`)."""
        t0 = time.perf_counter()
        while True:
            try:
                kind, what, values = self._ready.get_nowait()
            except queue.Empty:
                break
            if kind == "update":
                self.stream.update(what.to_json())
            else:
                self._fade = what
            self.overrides = values
        x = self._input(n)
        v, vo = self.v_in, self.v_out
        out = self.stream.process(x * v)
        y = out["v(out)"] / vo
        cv = out.get("v(cv)")
        if self._fade is not None:
            new, struct = self._fade
            self._fade = None
            o2 = new.process(x * v)
            y2 = o2["v(out)"] / vo
            m = min(len(y), len(y2))
            w = np.linspace(0.0, 1.0, m)
            y = y[-m:] * (1 - w) + y2[-m:] * w
            self.stream, self._structure = new, struct
            cv = o2.get("v(cv)")
            self.restarts += 1
        # A stream's output lags its input by a few samples (the input's
        # interpolation); pad its first block to keep the block size.
        if len(y) < n:
            y = np.concatenate([np.zeros(n - len(y)), y])
        rms_in = float(np.sqrt(np.mean(x**2))) + 1e-12
        rms_out = float(np.sqrt(np.mean(y**2))) + 1e-12
        meter = Meter(
            # The circuit's gain, V/V (0 dB more when the scales in and out differ).
            gain_db=20 * np.log10(rms_out * vo / (rms_in * v)),
            out_dbfs=20 * np.log10(rms_out * np.sqrt(2)),
            cv_v=float(np.mean(cv)) if cv is not None and len(cv) else None,
            load=(time.perf_counter() - t0) / (n / self.rate),
        )
        return y.astype(np.float32), meter

    def close(self) -> None:
        self._closed = True
        self._wake.set()
        self._builder.join(timeout=5)

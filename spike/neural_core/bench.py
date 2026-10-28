"""The test bench: T101 (the 670's input transformer) in a 600 ohm line, at one fixed rate.

A source of EMF v and impedance R_s drives T101's primary (winding resistance R_p) on
its core; the secondary is unloaded (in the 670 it feeds the 6386 grids) and its
self-capacitance, above the audio band, is left out, as is the leakage inductance. The
bench's output is the primary's EMF e = N A dB/dt (the secondary's voltage over the
turns ratio). Values come from config/circuits/fairchild_670.yaml (`t101_*`,
`source_impedance_ohm`) and mumetall's block in config/magnetics.yaml, so the core sees
what it sees in the slice, minus the rest of the circuit.

Per sample n, trapezoidal at the project's rate fs (one step per sample, no
oversampling: the spike's decision):

    e_n = 2 fs N A (B_n - B_{n-1}) - e_{n-1}                 (the winding)
    i_n = (v_n - e_n) / (R_s + R_p)                           (the loop)
    N i_n = l H(B_n) + (g / mu0) B_n + K_e e_n / (N A)        (Ampere: core, gap, eddy)

with K_e = l d^2 / (12 rho) (classical eddy loss, as `varimu.circuit.parts.transformer`).
One unknown, B_n, solved by Newton; the core is asked for H and dH/dB at its frozen
state as often as Newton needs, then told to accept. The bench runs a batch of
independent sequences at once (one core state each), which is what makes a numpy net
fast enough here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from varimu.circuit import netlist as nl
from varimu.config import load_sim_settings
from varimu.devices.core import MU0, CoreState, MagneticCore, core_model, materials

DBU_V_RMS = math.sqrt(0.6)  # 0 dBu: 1 mW into 600 ohm, 0.7746 V rms


class Core(Protocol):
    """A core in the bench: one state per sequence of the batch."""

    def eval(self, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """H (A/m) and dH/dB (A/m per T) at flux densities b (T), state frozen."""
        ...

    def accept(self, b: np.ndarray) -> None:
        """Move the state on to b (the last `eval` was at b)."""
        ...


@dataclass(frozen=True)
class Bench:
    fs_hz: int
    r_ohm: float  # source impedance + primary winding resistance
    turns: float
    area_m2: float
    path_m: float
    material: str
    gap_mmf_per_t: float  # g / mu0: the joint gap's magnetomotive force per tesla (A/T)
    eddy_mmf_s_per_t: float  # K_e: eddy-loss magnetomotive force per T/s (A s/T)

    def core_model(self) -> MagneticCore:
        return core_model("CORE_T101", self.material, self.path_m)


def t101_bench() -> Bench:
    p = nl.resolve()
    mat = materials()[p["t101_core_material"]]
    path = p["t101_core_path_m"]
    return Bench(
        fs_hz=load_sim_settings().sample_rate,
        r_ohm=p["source_impedance_ohm"] + p["t101_r_pri_ohm"],
        turns=p["t101_turns"],
        area_m2=p["t101_core_area_m2"],
        path_m=path,
        material=p["t101_core_material"],
        gap_mmf_per_t=p["t101_gap_m"] / MU0,
        eddy_mmf_s_per_t=path * mat["lamination_m"] ** 2 / (12 * mat["resistivity_ohm_m"]),
    )


# --- Cores ------------------------------------------------------------------------------


class JACore:
    """The Jiles-Atherton reference (varimu.devices.core), one state per sequence."""

    def __init__(self, model: MagneticCore, n: int = 1):
        self.model = model
        self.states = [CoreState()] * n
        self._last: tuple[np.ndarray, np.ndarray] | None = None

    def eval(self, b):
        h = np.empty_like(b)
        dh = np.empty_like(b)
        for k, (bk, s) in enumerate(zip(b, self.states, strict=True)):
            h[k], dh[k] = self.model.h_of_b(float(bk), s)
        self._last = (b.copy(), h)
        return h, dh

    def accept(self, b):
        last_b, h = self._last
        assert np.array_equal(last_b, b), "accept follows an eval at the same b"
        new = []
        for bk, hk, s in zip(b, h, self.states, strict=True):
            delta = s.delta if bk == s.b else (1.0 if bk > s.b else -1.0)
            new.append(CoreState(float(bk), float(hk), delta))
        self.states = new


class LinearCore:
    """The core's linear limit (its susceptibility at the demagnetized origin): the
    baseline any net must beat by a wide margin."""

    def __init__(self, model: MagneticCore, n: int = 1):
        self.slope = 1 / (MU0 * (1 + model.initial_susceptibility()))
        self.n = n

    def eval(self, b):
        return self.slope * b, np.full_like(b, self.slope)

    def accept(self, b):
        pass


# --- Running ----------------------------------------------------------------------------

ATOL_T = 1e-16
RTOL = 1e-12
MAX_NEWTON = 30
# Newton may cycle across a jump in the core's H(B) (JA deep in saturation: its RK4
# substep bounds make H(B) jump ~0.15 A/m within 0.13 uT at 0.8 T, measured 2026-10-28);
# then the iterate with the smallest residual is taken, if the cycle is within this.
STALL_T = 1e-6


def run(bench: Bench, v: np.ndarray, core: Core) -> dict[str, np.ndarray]:
    """Run sequences v (volts, shape (n_seq, n_samples) or (n_samples,)) through the bench.
    Returns b (T), h (A/m), e (V, the output), i (A), each shaped like v, and per sample
    newton (iterations, the batch's max) and stalls (1 where Newton cycled, STALL_T)."""
    squeeze = v.ndim == 1
    v = np.atleast_2d(np.asarray(v, dtype=float))
    n_seq, n = v.shape
    c = 2 * bench.fs_hz * bench.turns * bench.area_m2  # de/dB
    na = bench.turns * bench.area_m2
    n_over_r = bench.turns / bench.r_ohm
    path = bench.path_m
    out = {k: np.zeros((n_seq, n)) for k in ("b", "h", "e", "i")}
    newton = np.zeros(n, dtype=np.int32)
    stalls = np.zeros(n, dtype=np.int8)
    b1 = np.zeros(n_seq)  # B_{n-1}
    b2 = np.zeros(n_seq)  # B_{n-2}
    e1 = np.zeros(n_seq)
    for t in range(n):
        vt = v[:, t]
        b = 2 * b1 - b2 if t > 1 else b1.copy()
        best_b, best_f = b.copy(), np.full(n_seq, np.inf)
        for it in range(1, MAX_NEWTON + 1):  # noqa: B007
            newton[t] = it
            h, dh = core.eval(b)
            e = c * (b - b1) - e1
            f = n_over_r * (vt - e) - path * h - bench.gap_mmf_per_t * b
            f -= bench.eddy_mmf_s_per_t * e / na
            df = -(n_over_r + bench.eddy_mmf_s_per_t / na) * c - path * dh - bench.gap_mmf_per_t
            better = np.abs(f) < best_f
            best_b = np.where(better, b, best_b)
            best_f = np.where(better, np.abs(f), best_f)
            step = -f / df
            b = b + step
            done = np.abs(step) <= ATOL_T + RTOL * np.abs(b)
            if np.all(done):
                break
        else:
            if np.any(np.abs(step) > STALL_T):
                raise RuntimeError(f"Newton didn't converge at sample {t}")
            b = np.where(done, b, best_b)
            stalls[t] = 1
        h, _ = core.eval(b)
        core.accept(b)
        e = c * (b - b1) - e1
        out["b"][:, t], out["h"][:, t], out["e"][:, t] = b, h, e
        out["i"][:, t] = (vt - e) / bench.r_ohm
        b2, b1, e1 = b1, b, e
    if squeeze:
        out = {k: x[0] for k, x in out.items()}
    out["newton"] = newton
    out["stalls"] = stalls
    return out

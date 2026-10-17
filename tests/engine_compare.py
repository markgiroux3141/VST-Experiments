"""Rust engine (varimu.sim.fast) vs ngspice (varimu.sim.io) on the same IR and input.

Shared by the circuitsim agreement tests. Both engines get the same upsampled
input and the same decimation, so the remaining difference is the solvers'.
ngspice runs as a reference: tight reltol, a timepoint on every sample and 8
steps per sample (io.run_transient's reference options). Without those,
ngspice's own error (timepoints straddling the input's sample kinks, then
interpolation) is -55 to -75 dB re signal and hides the comparison.
"""

import dataclasses

import numpy as np

from varimu.circuit import spice
from varimu.circuit.ir import CircuitIR, Section, VoltageProbe
from varimu.sim import fast, io

FS = 96000
REFERENCE = {"max_step_div": 8, "grid_breakpoints": True}


def settings(k: int, reltol: float = 1e-6) -> io.TransientSettings:
    return io.TransientSettings(
        sample_rate=FS,
        oversample=k,
        full_scale_volts_peak=1.0,
        reltol=reltol,
        abstol=1e-15,
        vntol=1e-9,
        method="trap",
    )


def signal(dur_s: float = 0.03, amp: float = 1.0) -> np.ndarray:
    """Three tones across the band, faded in so the start is smooth."""
    t = np.arange(int(dur_s * FS)) / FS
    fade = np.clip(t / 0.003, 0, 1) ** 2
    return amp * fade * sum(np.sin(2 * np.pi * f * t) / 3 for f in (100.0, 1000.0, 10000.0))


def circuit(elements, probes, models=()) -> CircuitIR:
    """A one-section test circuit driven at node "in"."""
    return CircuitIR(
        "test",
        "in",
        tuple(VoltageProbe(p) for p in probes),
        tuple(models),
        (Section("t", tuple(elements)),),
    )


def compare(
    ir: CircuitIR, x: np.ndarray, k: int, reltol: float = 1e-6, method: str = "trap"
) -> tuple[float, float]:
    """(worst AC difference in dB re the probe's swing, worst DC difference re the
    largest DC voltage in the circuit).

    Probes that barely move are skipped for AC: a swing within ~100x of
    ngspice's tolerance there (reltol x |V|, e.g. uV on a node at B+), or
    below 1e-4 of the largest swing in the run. Probes that also sit near 0 V
    (below 1e-3 of the largest DC voltage) are skipped for DC too. Both
    engines put roundoff noise on nodes held only by high resistances: the
    device-stripped 670's T104 secondary floats on a 1 GOhm leak and should
    sit at exactly 0 V, and shows ~1e-5..1e-4 V in both. Errors on such a
    node measure roundoff, not agreement.
    """
    s = dataclasses.replace(settings(k, reltol), method=method)
    text, _ = spice.emit(ir, triode_formulation="exact")
    save = [p.spice for p in ir.probes]
    ng = io.run_transient(
        text, x, input_node=ir.input_node, save=save, settings=s, timeout_s=300, **REFERENCE
    )
    rs = fast.run_transient(ir, x, settings=s, method="trap")  # the engine's 2nd-order baseline
    worst_db, worst_dc = -np.inf, 0.0
    swings = {n: np.max(np.abs(v - v[0])) for n, v in ng.vectors.items()}
    floor = 1e-4 * max(swings.values())
    dc_scale = max(1.0, max(abs(v[0]) for v in ng.vectors.values()))
    for name in save:
        a, b = rs.vectors[name], ng.vectors[name]
        swing = swings[name]
        carries_signal = swing > max(floor, 100 * (reltol * np.max(np.abs(b)) + s.vntol))
        if carries_signal or abs(b[0]) > 1e-3 * dc_scale:
            worst_dc = max(worst_dc, abs(a[0] - b[0]) / dc_scale)
        if carries_signal:
            d = np.max(np.abs((a - a[0]) - (b - b[0]))) / swing
            worst_db = max(worst_db, 20 * np.log10(d + 1e-300))
    return worst_db, worst_dc


def compare_solvers(ir: CircuitIR, x: np.ndarray, k: int, method: str, skip=()) -> float:
    """Worst difference between the DK and full-MNA solvers (circuit-sim plan, M5) over
    every probe and output sample, in units of the Newton tolerance on that value
    (reltol |v| + vntol). Exact Newton (no Jacobian reuse), so the iterates are the
    same up to roundoff. `skip`: probes on nodes whose roundoff exceeds the tolerance
    (a winding floating on a 1 GOhm leak)."""
    base = dataclasses.replace(settings(k), method=method, newton_reuse=False)
    runs = {
        solver: fast.run_transient(ir, x, settings=dataclasses.replace(base, solver=solver))
        for solver in ("mna", "dk")
    }
    worst = 0.0
    for p in ir.probes:
        if p.spice in skip:
            continue
        a, b = runs["mna"].vectors[p.spice], runs["dk"].vectors[p.spice]
        tol = base.newton_reltol * np.maximum(np.abs(a), np.abs(b)) + base.newton_vntol
        worst = max(worst, float(np.max(np.abs(a - b) / tol)))
    return worst

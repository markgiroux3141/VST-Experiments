"""The ensemble's static measurements, as 3M's 60 cycle B-H meter made them, and the fit
of the particles' free parameters to them (Sound Talk No. 20 and Eilers' Hc; No. 22's
loops as a check).

**The meter** (Sound Talk Nos. 20 and 22): a 60 Hz sinusoidal field along the tape on a
sample in a solenoid (a long strip: no demagnetization along it), the flux contributed by
the material read. Bulletin 20's point for a peak field Hp is the remanence on the
descending branch of the symmetric loop to +-Hp, read at H = 0 (`remanence_curve`: from the
erased state, `cycles` loops, then the descending branch to 0); the major loop's coercivity
(`coercivity`) is where M crosses 0 on the descending branch of a 1000 Oe loop (Bulletin
22's major loop; intrinsic: the material's flux, as the meter read it).

The thermal activation runs at 60 Hz here: the ensemble's switching fields at the meter's
rate are what the static data fix; recording at 70 kHz bias then switches the same
particles harder (Sharrock), from the same barriers, without a separate mapping.
"""

from __future__ import annotations

import math

import numpy as np

from varimu.tape_particles import ensemble as ens

OE = ens.OE
METER_HZ = 60.0


def loop_history(h_peak: np.ndarray, steps_per_cycle: int, cycles: float, end: str) -> np.ndarray:
    """H(t) of the meter (steps x len(h_peak)): sin from 0 for `cycles` whole cycles, then
    (end = "remanence") up to +Hp and down to 0, or (end = "descending") up to +Hp and down
    to -Hp."""
    m = steps_per_cycle
    total = int(round(cycles * m)) + (m // 2 if end == "remanence" else 3 * m // 4)
    ph = 2.0 * math.pi * (np.arange(1, total + 1) / m)
    return np.sin(ph)[:, None] * np.asarray(h_peak, float)[None, :]


def remanence_curve(backend, h_peak_a_m, steps_per_cycle=96, cycles=1.0) -> np.ndarray:
    """M_x / Ms at H = 0 on the descending branch after symmetric loops to each Hp."""
    h = loop_history(np.asarray(h_peak_a_m, float), steps_per_cycle, cycles, "remanence")
    return backend.uniform(h, 1.0 / (METER_HZ * steps_per_cycle))


def saturation_remanence(backend, steps_per_cycle=96) -> float:
    """After a 2000 Oe loop (past every switching field)."""
    return float(remanence_curve(backend, [2000.0 * OE], steps_per_cycle)[0])


def descending_branch(backend, h_peak_a_m=1000.0 * OE, steps_per_cycle=400, cycles=1.0):
    """(H, M_x / Ms) on the descending branch of the h_peak loop, from +Hp to -Hp."""
    m = steps_per_cycle
    h = loop_history(np.array([h_peak_a_m]), m, cycles, "descending")
    tr = backend.uniform(h, 1.0 / (METER_HZ * m), record=True)
    i0 = int(round(cycles * m)) + m // 4  # the +peak
    return h[i0 - 1 :, 0], tr[i0 - 1 :, 0]


def coercivity(backend, h_peak_a_m=1000.0 * OE, steps_per_cycle=400) -> float:
    """Where M_x crosses 0 on the descending branch (A/m, positive)."""
    h, m = descending_branch(backend, h_peak_a_m, steps_per_cycle)
    j = int(np.argmax(m <= 0.0))
    if j == 0:
        return float("nan")
    f = m[j - 1] / (m[j - 1] - m[j])
    return float(-(h[j - 1] + f * (h[j] - h[j - 1])))


class NumpyBackend:
    """The Python reference for uniform fields (small ensembles)."""

    def __init__(self, parts: ens.Particles, spec: ens.ParticleSpec, grid: int = 32):
        self.parts, self.spec, self.grid = parts, spec, grid

    def uniform(self, h_x: np.ndarray, dt_s: float, record: bool = False):
        _, final, trace = ens.run_uniform(
            self.parts, self.spec, h_x, dt_s, grid=self.grid, record=record
        )
        return trace if record else final

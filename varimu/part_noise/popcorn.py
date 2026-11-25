"""Popcorn (burst) noise: a trap at the base-emitter junction captures and releases a carrier,
switching the base current between two levels; dwell times are exponential (a two-state Markov
process, a random telegraph signal). Several traps add.

Each sample is the exact average of the trap's state over the sample's interval (the integral
of a piecewise-constant signal), so the steps are band-limited by the sample's box and nothing
aliases beyond that.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRAP_SOURCE = (
    "provisional: model knowledge (popcorn noise in small-signal BJTs: base-current steps of "
    "tens to hundreds of pA, dwell times from ~0.1 ms to seconds, exponential; amplitude rising "
    "with Vbe. Mechanism and statistics: web: https://en.wikipedia.org/wiki/Burst_noise, "
    "web: https://www.electronicdesign.com/technologies/power/power-supply/"
    "power-electronics-systems/article/21195658/burstpopcorn-noise-in-linear-bicmos-and-bcd-"
    "technologies (two levels, Poisson switching, high / low times); measured base currents to "
    "find: J. N. Puckett, Caltech thesis 1971, web: https://thesis.library.caltech.edu/10787/; "
    "F. Sischka, AK Bipo 2014 (2N2222))"
)


@dataclass(frozen=True)
class Trap:
    amplitude_a: float  # the step in base current
    tau_high_s: float  # mean dwell in the high state
    tau_low_s: float  # mean dwell in the low state


def telegraph(trap: Trap, n: int, rate_hz: float, rng: np.random.Generator) -> np.ndarray:
    """One trap's state (0 or 1, times its amplitude) averaged over each of n samples."""
    duration = n / rate_hz
    p_high = trap.tau_high_s / (trap.tau_high_s + trap.tau_low_s)
    high = bool(rng.random() < p_high)
    # Switching times: alternate exponential dwells until past the end (stationary start: the
    # first dwell is exponential too, by memorylessness).
    times = [0.0]
    states = [high]
    t = 0.0
    while t < duration:
        t += rng.exponential(trap.tau_high_s if high else trap.tau_low_s)
        high = not high
        times.append(min(t, duration))
        states.append(high)
    times = np.array(times)
    states = np.array(states[:-1], dtype=float)  # the state on [times[i], times[i + 1])
    # F(t) = integral of the state: piecewise linear with nodes at the switching times.
    f_nodes = np.concatenate([[0.0], np.cumsum(states * np.diff(times))])
    edges = np.arange(n + 1) / rate_hz
    f_edges = np.interp(edges, times, f_nodes)
    return trap.amplitude_a * np.diff(f_edges) * rate_hz


def burst_current(traps, n: int, rate_hz: float, rng: np.random.Generator) -> np.ndarray:
    """The traps' base-current steps added (mean removed: the bias absorbs it)."""
    i = np.zeros(n)
    for trap in traps:
        i += telegraph(trap, n, rate_hz, rng)
    return i - i.mean()

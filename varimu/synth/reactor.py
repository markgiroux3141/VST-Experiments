"""Saturable reactors (tube synth S1): a core's incremental permeability under DC bias.

A saturable reactor's inductance follows its core's incremental permeability at the DC
operating point the control winding sets. `incremental_permeability` measures it on the
Jiles-Atherton reference (varimu.devices.core) alone: from the demagnetized state, B is
ramped up the initial curve to where H reaches the bias, then cycled by +-dB/2, and the
settled minor loop's dB / (mu0 dH) is read off. A circuit's DC operating point puts its
cores on that same initial curve (tests/test_reactor.py). In a circuit the signal drives
the cores by current, and there the JA core's minor loops ratchet toward the anhysteretic
curve before they settle, at a lower permeability under strong bias than this B-centered
measurement (`current_driven_permeability`; the settled values are in the tests).

The reference it is compared with is Gans' law of reversible permeability (provisional:
model knowledge; R. Gans 1910, shown against measured materials in Bozorth,
Ferromagnetism, 1951): chi_rev / chi_rev(0) = 3 L'(x) with M / Ms = L(x), L the Langevin
function. No published curve of incremental permeability against DC bias was found for
mumetall (searched 2026-10-29; docs/TUBE_SYNTH_PLAN.md, S1's status), so the law stands
in until a measured curve does.
"""

from __future__ import annotations

import numpy as np

from varimu.devices.core import DEMAGNETIZED, MU0, CoreState, MagneticCore


def initial_curve_state(
    core: MagneticCore, h_dc_a_per_m: float, *, b_max_t: float = 1.5, steps: int = 6000
) -> CoreState:
    """The core's state where its initial curve (from demagnetized) reaches H = h_dc (>= 0),
    to the step b_max_t / steps."""
    state = DEMAGNETIZED
    if h_dc_a_per_m <= 0.0:
        return state
    for b in np.linspace(0.0, b_max_t, steps)[1:]:
        h, _ = core.h_of_b(b, state)
        if h >= h_dc_a_per_m:
            return state
        state = core.advance(b, state)
    raise ValueError(f"H = {h_dc_a_per_m} A/m not reached below {b_max_t} T")


def incremental_permeability(
    core: MagneticCore,
    h_dc_a_per_m: float,
    ripple_pp_t: float,
    *,
    cycles: int = 4,
    points_per_cycle: int = 200,
) -> tuple[float, float]:
    """(B_dc in T, relative incremental permeability) at bias h_dc on the initial curve,
    on the minor loop of `ripple_pp_t` peak to peak after `cycles` cycles."""
    state = initial_curve_state(core, h_dc_a_per_m)
    b_dc = state.b
    hs = []
    n = points_per_cycle
    for t in np.linspace(0.0, 2 * np.pi * cycles, cycles * n + 1)[1:]:
        b = b_dc + 0.5 * ripple_pp_t * np.sin(t)
        h, _ = core.h_of_b(b, state)
        state = core.advance(b, state)
        hs.append(h)
    last = np.asarray(hs[-n:])
    return b_dc, ripple_pp_t / (MU0 * (last.max() - last.min()))


def b_for_h(core: MagneticCore, h_a_per_m: float, state: CoreState = DEMAGNETIZED) -> float:
    """The B at which the path from `state` reaches H = h (Newton on the core's own map,
    kept on the side of state.b that h lies on)."""
    if h_a_per_m == state.h:
        return state.b
    up = h_a_per_m > state.h
    lo, hi = (state.b, state.b + 2.0) if up else (state.b - 2.0, state.b)
    b = state.b + (h_a_per_m - state.h) * MU0  # a vacuum-permeability first step
    for _ in range(100):
        h, dh = core.h_of_b(b, state)
        if abs(h - h_a_per_m) <= 1e-12 * (abs(h_a_per_m) + core.a_a_per_m):
            return b
        if h < h_a_per_m:
            lo = b
        else:
            hi = b
        nxt = b - (h - h_a_per_m) / dh
        b = nxt if lo < nxt < hi else 0.5 * (lo + hi)
    raise RuntimeError(f"no B for H = {h_a_per_m} A/m from {state}")


def current_driven_permeability(
    core: MagneticCore,
    h_dc_a_per_m: float,
    h_pp_a_per_m: float,
    *,
    cycles: int = 12,
    points_per_cycle: int = 200,
) -> tuple[float, float]:
    """(B at the last cycle's center in T, relative permeability) of a current-driven
    reactor: from the initial curve at h_dc, H swung by h_pp sinusoidally (rising first),
    the last cycle's B component in phase with H over the H amplitude (what an inductance
    measurement reads). Below the anhysteretic curve (the initial curve is), a JA minor loop
    ratchets: rising is irreversible, falling reversible, so B climbs toward the anhysteretic
    for tens to hundreds of cycles before the loop settles, and a cycle read during the
    climb includes its drift. Biased, use this only after enough cycles (tests/test_reactor.py
    has the numbers); unbiased, the loop is closed from the start."""
    state = DEMAGNETIZED
    if h_dc_a_per_m != 0.0:
        state = core.advance(b_for_h(core, h_dc_a_per_m), DEMAGNETIZED)
    n = points_per_cycle
    theta = np.linspace(0.0, 2 * np.pi * cycles, cycles * n + 1)[1:]
    bs = np.empty(len(theta))
    for k, th in enumerate(theta):
        b = b_for_h(core, h_dc_a_per_m + 0.5 * h_pp_a_per_m * np.sin(th), state)
        state = core.advance(b, state)
        bs[k] = b
    last, th = bs[-n:], theta[-n:]
    in_phase = 2.0 * np.mean((last - last.mean()) * np.sin(th))
    return float(0.5 * (last.max() + last.min())), in_phase / (MU0 * 0.5 * h_pp_a_per_m)


def inverse_langevin(y: float) -> float:
    """x with coth(x) - 1/x = y, for 0 <= y < 1 (bisection)."""
    if y <= 0.0:
        return 0.0
    lo, hi = 1e-9, 1e6
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if 1.0 / np.tanh(mid) - 1.0 / mid < y:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def gans_ratio(m_over_ms: float) -> float:
    """Gans' law: reversible susceptibility relative to its value at M = 0, 3 L'(x) with
    M / Ms = L(x)."""
    x = inverse_langevin(abs(m_over_ms))
    if x < 1e-4:
        return 1.0
    return 3.0 * (1.0 / x**2 - 1.0 / np.sinh(x) ** 2)

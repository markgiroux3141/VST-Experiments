"""A unit's setup: the manual's adjustment procedures, applied per genome.

A real 670 is adjusted after it is built and when its tubes age ([MAN] p.7):
B+ ADJ (R313) until pin 8 of the EL34 reads 240 V; BALANCE (R105) until the meter
reads the same in both BALANCE positions; ZERO (R142) for a meter zero in the ZERO
position. A genome with part tolerances (passive_spread > 0) or tube spreads is a
unit before that setup; `adjust` does it, on the DC operating point (circuitsim, a
few ms each), against what the nominal unit reads at its nominal trims:

- B+ ADJ: the regulated rail's DC value (the nominal's settled 240 V, calibrated by
  scripts/calibrate_psu.py, sits a little below its DC value: the DC point holds the
  mains at its peak);
- BALANCE: the meter in its BALANCE positions reads the drop across R107 (30 ohm,
  1%) or R108 from the centre tap: equal readings are V(t3) = V(t2);
- ZERO: the meter in its ZERO position reads 15 ohm x the stage's total plate
  current; zero is the nominal unit's total current.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from functools import cache
from typing import Any

import numpy as np
from scipy.optimize import brentq

from varimu.circuit import netlist as nl
from varimu.circuit.ir import VoltageProbe

TRIMS = ("b_plus_adj", "balance", "zero")
_NODES = ("bp", "ctr", "t2", "t3")


def dc(overrides: Mapping[str, Any]) -> dict[str, float]:
    """The DC operating point's bp, ctr, t2, t3 (V)."""
    import circuitsim

    from varimu.sim.fast import check_build

    check_build()
    ir = nl.build(overrides).ir
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(n) for n in _NODES))
    raw = circuitsim.simulate(ir.to_json(), np.zeros(2), 1 / 192000, "esdirk4")
    return {n: float(raw[f"v({n})"][0]) for n in _NODES}


def _readings(v: dict[str, float]) -> dict[str, float]:
    """What the procedures read: B+, the BALANCE difference, the ZERO total (V)."""
    return {
        "bp": v["bp"],
        "balance": v["t3"] - v["t2"],
        "total": (v["ctr"] - v["t3"]) + (v["ctr"] - v["t2"]),
    }


@cache
def _nominal_targets() -> tuple[float, float]:
    r = _readings(dc({}))
    return r["bp"], r["total"]


def adjust(overrides: Mapping[str, Any], *, rounds: int = 3) -> dict[str, Any]:
    """`overrides` with B+ ADJ, BALANCE and ZERO set by the procedures (those the
    overrides already give are left alone)."""
    bp_target, total_target = _nominal_targets()
    out = dict(overrides)
    free = [t for t in TRIMS if t not in overrides]
    p0 = nl.resolve(out)
    for t in free:
        out[t] = p0[t]

    def reading(t, x):
        r = _readings(dc({**out, t: x}))
        return {
            "b_plus_adj": r["bp"] - bp_target,
            "balance": r["balance"],
            "zero": r["total"] - total_target,
        }[t]

    for _ in range(rounds):
        for t in free:
            lo, hi = 0.0, 1.0
            f_lo, f_hi = reading(t, lo), reading(t, hi)
            if f_lo * f_hi > 0:  # out of the trim's range: leave it at the nearer end
                out[t] = lo if abs(f_lo) < abs(f_hi) else hi
                continue
            out[t] = round(brentq(lambda x, t=t: reading(t, x), lo, hi, xtol=1e-5), 5)
    return out

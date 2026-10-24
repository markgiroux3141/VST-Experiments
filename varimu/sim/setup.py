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
from dataclasses import dataclass
from functools import cache
from typing import Any

import numpy as np
from scipy.optimize import brentq

from varimu.circuit import netlist as nl
from varimu.circuit.ir import VoltageProbe
from varimu.config import DATA_DIR

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


# --- Threshold adjustments ([MAN] p.8) ------------------------------------------------------

CURVE3_CSV = DATA_DIR / "datasheets" / "fairchild_670_io_curve3.csv"
THRESHOLD_CONTROLS = ("input_atten_db", "dc_threshold", "ac_threshold")
UNITY_PROBE_DBM = -10.0  # the unity-gain step's tone, well below any threshold
NUDGE = 0.02  # rotation: the largest finite-difference step of the joint adjustment
MAX_NEWTON_STEP = 0.25  # rotation: the most a joint step moves either control


@dataclass(frozen=True)
class ThresholdTarget:
    """The output levels the procedure sets at 3 dB and 10 dB of limiting (dBm)."""

    out_3db_dbm: float
    out_10db_dbm: float


def curve3() -> tuple[np.ndarray, np.ndarray]:
    """The manual's curve 3, factory-adjusted (in dBm, out dBm; digitized, see
    data/datasheets/fairchild_670.provenance.yaml)."""
    d = np.loadtxt(CURVE3_CSV, delimiter=",", skiprows=1)
    return d[:, 0], d[:, 1]


def factory_target() -> ThresholdTarget:
    """Curve 3's output where it has limited 3 dB and 10 dB (unity gain below)."""
    x, y = curve3()
    gr = x - y
    return ThresholdTarget(float(np.interp(3.0, gr, y)), float(np.interp(10.0, gr, y)))


@dataclass
class ThresholdSetup:
    overrides: dict[str, Any]  # with input_atten_db, dc_threshold, ac_threshold set
    k_db: float  # input terminals re the EMF (dBm - dBFS) at the chosen pad
    unity_gain_db: float  # gain at UNITY_PROBE_DBM with AC THRESHOLD at 0
    log: list[str]


def _bracket_solve(f, lo: float, hi: float, n: int, batches: int) -> tuple[float, bool]:
    """Root of the monotonic f on [lo, hi] by `batches` rounds of n parallel
    evaluations (f takes an array of trims); linear interpolation in the last
    bracket. (root, in range); out of range, the end where |f| is smaller."""
    xs = np.linspace(lo, hi, n)
    ys = np.asarray(f(xs))
    for b in range(batches):
        s = np.flatnonzero(np.sign(ys[:-1]) != np.sign(ys[1:]))
        if not len(s):
            i = int(np.argmin(np.abs(ys)))
            return float(xs[i]), False
        i = int(s[0])
        a, c, fa, fc = xs[i], xs[i + 1], ys[i], ys[i + 1]
        if b == batches - 1:
            return float(a - fa * (c - a) / (fc - fa)), True
        inner = np.linspace(a, c, n + 2)[1:-1]
        xs = np.concatenate([[a], inner, [c]])
        ys = np.concatenate([[fa], np.asarray(f(inner)), [fc]])
    raise AssertionError("unreachable")


def threshold(
    overrides: Mapping[str, Any],
    target: ThresholdTarget | None = None,
    *,
    tol_db: float = 0.05,
    max_newton: int = 8,
    n: int = 7,
    batches: int = 2,
    settings=None,
    log=print,
) -> ThresholdSetup:
    """The manual's threshold adjustment (p.8) with steady 1 kHz tones
    (varimu.measure.levels), the factory curve (curve 3) by default:

    1. AC THRESHOLD to zero, INPUT GAIN (1 dB steps) for unity gain;
    2. AC and DC THRESHOLD to the lowest threshold ("full clockwise": AC 1, DC 0);
    3. input 3 dB above the desired output at 3 dB of limiting: DC THRESHOLD for
       that output;
    4. input 10 dB above the desired output at 10 dB of limiting: AC THRESHOLD
       for that output;
    5. repeat 3 and 4 until both points are right.

    Steps 3 and 4 run once as written (each searches its control's whole range,
    `batches` rounds of `n` renders in parallel). Repeating them converges slowly,
    as each control moves the other's point (measured 2026-10-23 on the nominal
    unit: each round moved both controls by ~0.84 of the round before), so step 5
    goes to the same end point by Newton on both controls together: both points'
    outputs at the controls and at each control nudged, 6 renders in parallel per
    iteration, until both are within `tol_db`. Controls the overrides already
    give are left alone (with one free, 3 or 4 alone)."""
    from varimu.measure import levels

    target = target or factory_target()
    out = dict(overrides)
    msgs: list[str] = []

    def note(m: str) -> None:
        msgs.append(m)
        log(m)

    def measure(points):
        return levels.tone_levels(points, settings=settings, label="threshold")

    # 1. Unity gain with no sidechain signal. k_db's first guess: a matched 600 ohm
    # input takes half the EMF (0 dBFS = 13.8 V peak EMF = +16 dBm on the terminals).
    pad = float(nl.resolve(out)["input_atten_db"])
    lo_db, hi_db = (nl.load_spec().controls["input_atten_db"][k] for k in ("min", "max"))
    k_db, gain = 16.0, float("nan")
    for _ in range(4):
        emf = UNITY_PROBE_DBM - k_db
        r = measure([({**out, "ac_threshold": 0.0, "input_atten_db": pad}, emf)])[0]
        k_db, gain = r.in_dbm - emf, r.gain_db
        step = float(np.clip(pad + round(gain), lo_db, hi_db))
        if "input_atten_db" in overrides or step == pad:
            break
        pad = step
    out["input_atten_db"] = pad
    note(f"input gain: pad {pad:g} dB, gain {gain:+.2f} dB at {UNITY_PROBE_DBM:g} dBm")

    # 2.-4.
    free = [t for t in ("dc_threshold", "ac_threshold") if t not in overrides]
    if "ac_threshold" in free:
        out["ac_threshold"] = 1.0
    if "dc_threshold" in free:
        out["dc_threshold"] = 0.0
    points = {
        "dc_threshold": (target.out_3db_dbm, levels.emf_dbfs_for(target.out_3db_dbm + 3, k_db)),
        "ac_threshold": (
            target.out_10db_dbm,
            levels.emf_dbfs_for(target.out_10db_dbm + 10, k_db),
        ),
    }
    for t in free:
        want, emf = points[t]

        def f(xs, t=t, want=want, emf=emf):
            rs = measure([({**out, t: float(x)}, emf) for x in xs])
            return [r.out_dbm - want for r in rs]

        x, ok = _bracket_solve(f, 0.0, 1.0, n, batches)
        out[t] = round(x, 4)
        note(f"{t} {out[t]:.4f}" + ("" if ok else " (out of range: at the end)"))
    if len(free) < 2:
        return ThresholdSetup(out, float(k_db), float(gain), msgs)

    # 5. Both points at once.
    keys = ("dc_threshold", "ac_threshold")

    def errors(xs):
        jobs = []
        for d, a in xs:
            ov = {**out, "dc_threshold": float(d), "ac_threshold": float(a)}
            jobs += [(ov, points[k][1]) for k in keys]
        rs = measure(jobs)
        return [
            np.array([rs[2 * i + j].out_dbm - points[k][0] for j, k in enumerate(keys)])
            for i in range(len(xs))
        ]

    x = np.array([out[k] for k in keys])
    h = NUDGE
    for it in range(max_newton):
        nudged = [x.copy() for _ in keys]
        for j in range(2):
            nudged[j][j] += h if x[j] + h <= 1.0 else -h
        e0, *e = errors([x, *nudged])
        note(
            f"newton {it + 1}: dc {x[0]:.4f} ac {x[1]:.4f}: "
            f"{e0[0]:+.3f} / {e0[1]:+.3f} dB at the 3 / 10 dB points"
        )
        if np.max(np.abs(e0)) <= tol_db:
            break
        jac = np.column_stack(
            [(ej - e0) / (nj[j] - x[j]) for j, (ej, nj) in enumerate(zip(e, nudged, strict=True))]
        )
        step = np.linalg.solve(jac, -e0)
        step *= min(1.0, MAX_NEWTON_STEP / np.max(np.abs(step)))
        x = np.clip(x + step, 0.0, 1.0)
        h = float(np.clip(0.5 * np.max(np.abs(step)), 0.002, NUDGE))
    else:
        note(f"not within {tol_db} dB after {max_newton} iterations")
    out.update({k: round(float(v), 4) for k, v in zip(keys, x, strict=True)})
    return ThresholdSetup(out, float(k_db), float(gain), msgs)

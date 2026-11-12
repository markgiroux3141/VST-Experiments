"""Sound Talk No. 21's protocol (scripts/tape_switching_study.py's `no21`, the same fit):
each model's bias curves at 1 and 15 kHz against the bulletin's, after one bias scale (A/m
of deep-gap field per mA, the Ampex 300's unprinted head efficiency) and an offset per
curve. Nothing else is fitted to No. 21."""

from __future__ import annotations

import math

import numpy as np

# No. 21, Type B, dB re each curve's peak at 2..8 mA (TAPE_PLAN.md TM2 step 7).
NO21_MA = np.arange(2.0, 9.0)
NO21_1K = np.array([-20.4, -11.0, -4.0, -0.6, 0.0, -0.8, -3.3])
NO21_15K = np.array([-13.8, -6.6, -2.0, 0.0, -1.7, -4.1, -7.1])


def fit(biases_a_m, curve_1k_db, curve_15k_db=None) -> dict:
    """One scale (A/m per mA) for both curves (or the 1 kHz alone), the switching study's
    grid search. Returns its residuals, peaks and the 15k - 1k differential."""
    biases_a_m = np.asarray(biases_a_m, float)
    lb = np.log(biases_a_m)
    curves = [(np.asarray(curve_1k_db, float), NO21_1K)]
    if curve_15k_db is not None:
        curves.append((np.asarray(curve_15k_db, float), NO21_15K))
    best = None
    lo = biases_a_m[0] / NO21_MA[0]
    hi = biases_a_m[-1] / NO21_MA[-1]
    for s in np.geomspace(lo, hi, 2000):
        x = np.log(s * NO21_MA)
        r = []
        for c, data in curves:
            m = np.interp(x, lb, c)
            r.append(m - data - np.mean(m - data))
        cost = float(np.mean(np.concatenate(r) ** 2))
        if best is None or cost < best[0]:
            best = (cost, s, r)
    _, s, r = best
    x = np.log(s * NO21_MA)
    fine = np.linspace(lb[0], lb[-1], 4000)
    out = {"scale_a_m_per_ma": float(s), "rms_db_1k": float(np.sqrt(np.mean(r[0] ** 2)))}
    m1 = np.interp(x, lb, curves[0][0])
    out["model_1k_db"] = (m1 - m1.max()).tolist()
    out["peak_ma_1k"] = float(math.exp(fine[np.argmax(np.interp(fine, lb, curves[0][0]))]) / s)
    if curve_15k_db is not None:
        m15 = np.interp(x, lb, curves[1][0])
        out["rms_db_15k"] = float(np.sqrt(np.mean(r[1] ** 2)))
        out["model_15k_db"] = (m15 - m15.max()).tolist()
        d = (m15 - m15.max()) - (m1 - m1.max())
        out["diff_15k_1k_db"] = (d - d[0]).tolist()
        out["peak_ma_15k"] = float(math.exp(fine[np.argmax(np.interp(fine, lb, curves[1][0]))]) / s)
    return out

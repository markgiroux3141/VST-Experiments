"""Plausibility checks any circuit gets (device builder B2): reject what no working unit
could do, before a circuit's own checks (its profile's).

Each check is {"passes", "value", "limit"}, as varimu.measure.plausibility's:

- quiet: the output at idle (no input) below IDLE_OUT_DBFS: an oscillation or a
  low-frequency wander (a supply in dropout) shows here (the 670's Phase 3 corner
  sweep: oscillating units sat at -76 .. -14 dBFS);
- rails: each documented supply rail within RAIL_PCT of its printed value, as built
  (a broken bias network, a rectifier that doesn't conduct, a short);
- no oscillation riding on a tone: nothing far from the tone's harmonics above
  SPUR_DB re the tone (metrics.harmonics: a spur more than 300 Hz from every
  harmonic);
- gain: a circuit that should pass signal does, within GAIN_DB of its nominal.

A render that fails to simulate is a rejection too (the caller's).
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from varimu.measure import metrics

IDLE_OUT_DBFS = -80.0
RAIL_PCT = 10.0
SPUR_DB = -50.0
GAIN_DB = 6.0


def check(passes: bool, value, limit) -> dict:
    return {"passes": bool(passes), "value": value, "limit": limit}


def quiet(out_dbfs: np.ndarray) -> dict:
    """The idle output (dBFS-scaled samples, after the decimation filter's ring-in)."""
    level = float(metrics.rms_dbfs_peak(out_dbfs))
    return check(level < IDLE_OUT_DBFS, round(level, 1), IDLE_OUT_DBFS)


def rails(vectors: Mapping[str, np.ndarray], printed: Mapping[str, float], n_avg: int) -> dict:
    """{rail: check}: each node's mean over the last n_avg samples against its printed volts."""
    out = {}
    for node, v_printed in printed.items():
        v = float(np.mean(vectors[f"v({node})"][-n_avg:]))
        dev = 100 * (v / v_printed - 1)
        out[node] = check(abs(dev) <= RAIL_PCT, {"v": round(v, 2), "pct": round(dev, 1)}, RAIL_PCT)
    return out


def no_spurs(h: metrics.Harmonics) -> dict:
    return check(h.spur_db < SPUR_DB, {"db": round(h.spur_db, 1), "hz": h.spur_hz}, SPUR_DB)


def gain(gain_db: float, nominal_db: float) -> dict:
    dev = gain_db - nominal_db
    return check(
        abs(dev) <= GAIN_DB, round(gain_db, 2), [nominal_db - GAIN_DB, nominal_db + GAIN_DB]
    )

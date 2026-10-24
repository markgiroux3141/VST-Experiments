"""Difference listening and exaggeration of a matched pair (Phase 5's listening aids).

Two matched units often differ by little once gain reduction and loudness are
matched (the plan's Phase 5, the first session). These aids show what to listen
for, from the matched renders alone (no new renders):

- **the residual** A - g B, g the least-squares gain that aligns B to A
  (`align_gain`): what the part changes, played turned up to the listening
  loudness, with its level re A reported;
- **exaggeration** A + k (g B - A) (`extrapolate`): the difference scaled by k
  (k = 1 is B itself, aligned; k = 0 is A), the colour-saturation analogy. It is
  a waveform extrapolation, not a unit: never preference data, never a genome.

Every stream is loudness matched again (varimu.listen.matching) and its gain
reduction re-measured (`gain_reduction`). The extrapolation is applied to the
outputs and, with the same g, to the two units' no-limiting references, so the
"unit" at k has a reference too: its GR is exactly A's at k = 0 and B's at k = 1,
and at large k it shows how far the extrapolation drifts. Where the two units'
gain envelopes differ, extrapolating scales that difference too, and the
envelope can fold (a window where A + k (B - A) cancels): those are reported as
artifacts (`ARTIFACT_*`), not hidden.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from varimu.listen import matching, stimuli

EXAGGERATION_K = (2.0, 4.0, 8.0)
ARTIFACT_GR_DB = 0.5  # the extrapolated unit's GR off the pair's by more than this
ARTIFACT_ENVELOPE_DB = 3.0  # a 50 ms window's level off A's (loudness matched) by more


def align_gain(a: np.ndarray, b: np.ndarray) -> float:
    """The least-squares gain g minimizing |a - g b|^2."""
    bb = float(np.dot(b, b))
    return float(np.dot(a, b) / bb) if bb > 0 else 1.0


def _trim(*xs: np.ndarray) -> list[np.ndarray]:
    n = min(len(x) for x in xs)
    return [np.asarray(x[:n], float) for x in xs]


def extrapolate(a: np.ndarray, b: np.ndarray, k: float, g: float) -> np.ndarray:
    """A + k (g B - A)."""
    return a + k * (g * b - a)


def _rms_db(x: np.ndarray, re: np.ndarray) -> float:
    num, den = float(np.sqrt(np.mean(x * x))), float(np.sqrt(np.mean(re * re)))
    return 20 * np.log10(num / den) if num > 0 and den > 0 else float("-inf")


def envelope_db(x: np.ndarray, a: np.ndarray, sample_rate: int) -> dict[str, float]:
    """Per GR window, the level of x minus A's, both at one loudness, over A's windows
    within the GR gate of its loudest: worst and rms (dB)."""
    w = int(stimuli.GR_WINDOW_S * sample_rate)
    n = min(len(x), len(a)) // w * w
    lx = np.sqrt(np.mean(np.square(x[:n]).reshape(-1, w), axis=1))
    la = np.sqrt(np.mean(np.square(a[:n]).reshape(-1, w), axis=1))
    keep = la >= la.max() * 10 ** (-stimuli.GATE_DB / 20)
    with np.errstate(divide="ignore"):
        d = 20 * np.log10(np.maximum(lx[keep], 1e-30) / la[keep])
    d -= np.mean(d)  # loudness matching removes the static part
    return {"worst_db": round(float(np.max(np.abs(d))), 3),
            "rms_db": round(float(np.sqrt(np.mean(d * d))), 3)}  # fmt: skip


def gain_reduction(
    a: np.ndarray, b: np.ndarray, ref_a: np.ndarray, ref_b: np.ndarray, k: float, g: float,
    sample_rate: int,
) -> float:  # fmt: skip
    """Average GR (varimu.listen.stimuli.average_gr_db) of the extrapolated unit:
    A + k (g B - A) re its reference ref_A + k (g ref_B - ref_A)."""
    return stimuli.average_gr_db(
        extrapolate(ref_a, ref_b, k, g), extrapolate(a, b, k, g), sample_rate
    )


def streams(
    a: np.ndarray, b: np.ndarray, ref_a: np.ndarray, ref_b: np.ndarray, sample_rate: int,
    ks: Sequence[float] = EXAGGERATION_K,
) -> dict[str, Any]:  # fmt: skip
    """A, B, the residual and A + k (B - A) for each k, all at one loudness (the
    residual on its own: it is turned up), with what each is: its k, its GR, its
    envelope against A's, the gain the loudness match applied, and the artifacts."""
    a, b, ref_a, ref_b = _trim(a, b, ref_a, ref_b)
    g = align_gain(a, b)
    gr_a = stimuli.average_gr_db(ref_a, a, sample_rate)
    gr_b = stimuli.average_gr_db(ref_b, b, sample_rate)
    named = [("A", 0.0), ("B", 1.0)] + [(f"A+{k:g}(B-A)", float(k)) for k in ks]
    sig = [extrapolate(a, b, k, g) for _, k in named]
    matched, info = matching.match_loudness(sig, sample_rate)
    am = matched[0]
    out = []
    for (name, k), y, gain_db in zip(named, matched, info.gains_db, strict=True):
        gr = gain_reduction(a, b, ref_a, ref_b, k, g, sample_rate)
        env = envelope_db(y, am, sample_rate)
        warn = []
        if k not in (0.0, 1.0):
            if abs(gr - 0.5 * (gr_a + gr_b)) > ARTIFACT_GR_DB:
                warn.append(f"GR {gr:.2f} dB, the pair's {0.5 * (gr_a + gr_b):.2f}")
            if env["worst_db"] > ARTIFACT_ENVELOPE_DB:
                warn.append(f"envelope off A's by up to {env['worst_db']:.1f} dB")
        out.append({
            "name": name, "k": k, "exaggerated": k not in (0.0, 1.0), "audio": y,
            "gr_db": round(gr, 3), "envelope": env, "gain_db": round(gain_db, 3),
            "artifacts": warn,
        })  # fmt: skip
    r = a - g * b
    (rm,), rinfo = matching.match_loudness([r], sample_rate)
    peak_limited = bool(info.target_lufs < matching.TARGET_LUFS - 1e-9)
    return {
        "align_gain_db": round(float(20 * np.log10(abs(g))), 4) if g else None,
        "gr_db": {"A": round(gr_a, 3), "B": round(gr_b, 3)},
        "target_lufs": round(float(info.target_lufs), 2),
        "peak_limited": peak_limited,  # the shared loudness lowered so nothing clips
        "streams": out,
        "residual": {
            "name": "A-B",
            "audio": rm,
            "level_db": round(_rms_db(r, a), 2),
            "gain_db": round(rinfo.gains_db[0], 2),
            "target_lufs": round(rinfo.target_lufs, 2),
        },
    }


def residual_db(a: np.ndarray, b: np.ndarray) -> float:
    """Level (dB re A, rms) of the residual A - g B: how different the pair is."""
    a, b = _trim(a, b)
    return _rms_db(a - align_gain(a, b) * b, a)


def exaggerated_pair(
    a: np.ndarray, b: np.ndarray, ref_a: np.ndarray, ref_b: np.ndarray, k: float,
    sample_rate: int,
) -> dict[str, Any]:  # fmt: skip
    """(A, A + k (B - A)) at one loudness, for discrimination (varimu.listen.abx), with
    what was played: the gains, the LUFS after them, the GRs, the envelope, artifacts."""
    a, b, ref_a, ref_b = _trim(a, b, ref_a, ref_b)
    g = align_gain(a, b)
    x = extrapolate(a, b, k, g)
    (ma, mx), info = matching.match_loudness([a, x], sample_rate)
    gr_a = stimuli.average_gr_db(ref_a, a, sample_rate)
    gr_x = gain_reduction(a, b, ref_a, ref_b, k, g, sample_rate)
    env = envelope_db(mx, ma, sample_rate)
    warn = []
    if k != 1.0 and abs(gr_x - gr_a) > ARTIFACT_GR_DB:
        warn.append(f"GR {gr_x:.2f} dB against A's {gr_a:.2f}")
    if k != 1.0 and env["worst_db"] > ARTIFACT_ENVELOPE_DB:
        warn.append(f"envelope off A's by up to {env['worst_db']:.1f} dB")
    return {
        "audio": (ma, mx),
        "gains_db": [round(v, 3) for v in info.gains_db],
        "lufs_after": [round(matching.integrated_lufs(y, sample_rate), 3) for y in (ma, mx)],
        "gr_db": [round(gr_a, 3), round(gr_x, 3)],
        "envelope": env,
        "artifacts": warn,
    }

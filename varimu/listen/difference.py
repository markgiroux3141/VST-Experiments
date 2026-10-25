"""Difference listening and exaggeration of a matched pair (Phase 5's listening aids).

Two matched units often differ by little once gain reduction and loudness are
matched (the plan's Phase 5, the first session). These aids show what to listen
for, from the matched renders alone (no new renders).

**The difference, in two parts** (`decompose`). B is first aligned to A by the
least-squares gain g (B' = g B). Then the linear time-invariant filter H that best
maps B' onto A (`linear_fit`: Welch cross-spectra, H = S_B'A / S_B'B', as an FIR
of LINEAR_FIT_N taps) splits B' - A into

- **tone** T = B' - H B': what a fixed filter does (an EQ tilt, a phase shift,
  a delay): heard as colour, not as dynamics;
- **character** C = H B' - A: what no fixed filter can explain (distortion,
  gain modulation that differs, thump, timing): what a compressor's physics
  adds beyond EQ.

B' - A = T + C exactly. A gain-only residual (A - g B) mixes both, and a small
phase difference, nearly inaudible, can dominate it: the first ABX session missed
at k = 8 on a pair whose gain-aligned residual was -21 dB.

**Streams** (`streams`), per part ("all": T + C, "character", "tone"): A, B, the
part itself turned up to the listening loudness (with its level re A), and the
part exaggerated, A + k d for k = 2, 4, 8 (k = 1 of "all" is B' itself; of
"character", H B', B's character in A's tone; of "tone", A + T, A's character in
B's tone). An exaggeration is a waveform, not a unit: never preference data,
never a genome.

Every stream is loudness matched again (varimu.listen.matching) and its gain
reduction measured: the same operations (g, H, k) are applied to the two units'
no-limiting references, so a stream has a reference too; its average GR is A's
at k = 0 and B's for "all" at k = 1. Where the gain envelopes differ,
exaggerating scales that difference, and the envelope can fold: reported as
artifacts (`ARTIFACT_*`), not hidden.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.signal import csd, fftconvolve, welch
from scipy.signal.windows import tukey

from varimu.listen import matching, stimuli

EXAGGERATION_K = (2.0, 4.0, 8.0)
PARTS = ("all", "character", "tone")
LINEAR_FIT_N = 32768  # taps of H: 0.34 s, 2.9 Hz resolution at 96 kHz
SMOOTH_OCT = 1 / 12  # H averaged over this fraction of an octave (difference.smooth_octave)
ARTIFACT_GR_DB = 0.5  # a stream's GR off the pair's by more than this
ARTIFACT_ENVELOPE_DB = 3.0  # a 50 ms window's level off A's (loudness matched) by more


def align_gain(a: np.ndarray, b: np.ndarray) -> float:
    """The least-squares gain g minimizing |a - g b|^2."""
    bb = float(np.dot(b, b))
    return float(np.dot(a, b) / bb) if bb > 0 else 1.0


def _trim(*xs: np.ndarray) -> list[np.ndarray]:
    n = min(len(x) for x in xs)
    return [np.asarray(x[:n], float) for x in xs]


def _rms_db(x: np.ndarray, re: np.ndarray) -> float:
    num, den = float(np.sqrt(np.mean(x * x))), float(np.sqrt(np.mean(re * re)))
    return 20 * np.log10(num / den) if num > 0 and den > 0 else float("-inf")


def linear_fit(x: np.ndarray, y: np.ndarray, n: int | None = None) -> np.ndarray:
    """The FIR h (n taps, centred: delay n // 2) of the LTI filter that best maps x onto
    y, from Welch cross-spectra (H1 = S_xy / S_xx, Hann segments of n, half overlap),
    smoothed over SMOOTH_OCT of an octave around its bulk delay, windowed (Tukey 0.25)
    against the circular wrap. Measured (2026-10-24, 3 and 8 s of noise program,
    `tests/test_abx.py`): a filter's character leakage -53 / -62 dB re A; distortion's
    and pumping's tone leakage 26-33 dB below their character (unsmoothed: 9-15 dB);
    a 20 Hz high-pass, the hardest case, leaks 12 dB below its tone."""
    n = min(n or LINEAR_FIT_N, 1 << int(np.floor(np.log2(len(x) // 2))))  # >= 2 segments
    _, sxy = csd(x, y, nperseg=n, window="hann", noverlap=n // 2, detrend=False)
    _, sxx = welch(x, nperseg=n, window="hann", noverlap=n // 2, detrend=False)
    hf = sxy / (sxx + 1e-12 * sxx.max())
    # A bulk delay is a phase ramp that averaging would smear: out before, back after.
    delay = int(np.argmax(np.abs(np.fft.irfft(hf, n=n))))
    delay = delay - n if delay > n // 2 else delay
    ramp = np.exp(-2j * np.pi * np.arange(len(hf)) * delay / n)
    hf = smooth_octave(hf / ramp, SMOOTH_OCT) * ramp
    h = np.fft.irfft(hf, n=n)
    return np.roll(h, n // 2) * tukey(n, 0.25)


def smooth_octave(hf: np.ndarray, frac: float | None) -> np.ndarray:
    """A complex response on an rfft grid averaged over `frac` of an octave around each
    bin (a running mean whose width grows with frequency; None: unsmoothed): the low
    end keeps the fit's resolution, the many bins up high average out its variance."""
    if not frac:
        return hf
    k = np.arange(len(hf))
    half = np.maximum(0, np.floor(k * (2 ** (frac / 2) - 1))).astype(int)
    lo, hi = np.maximum(k - half, 0), np.minimum(k + half, len(hf) - 1)
    c = np.concatenate([[0], np.cumsum(hf)])
    return (c[hi + 1] - c[lo]) / (hi - lo + 1)


def apply_linear(h: np.ndarray, x: np.ndarray) -> np.ndarray:
    """x through the centred FIR h, same length as x."""
    d = len(h) // 2
    return fftconvolve(x, h)[d : d + len(x)]


@dataclass(frozen=True)
class Decomposition:
    g: float  # the gain aligning B to A
    h: np.ndarray  # the filter mapping B' = g B onto A
    tone: np.ndarray  # T = B' - H B'
    character: np.ndarray  # C = H B' - A

    def part(self, name: str) -> np.ndarray:
        """The part's difference d (B' - A = T + C for "all")."""
        if name == "all":
            return self.tone + self.character
        if name in ("character", "tone"):
            return getattr(self, name)
        raise ValueError(f"part must be one of {PARTS}, not {name!r}")


def decompose(a: np.ndarray, b: np.ndarray) -> Decomposition:
    a, b = _trim(a, b)
    g = align_gain(a, b)
    bp = g * b
    h = linear_fit(bp, a)
    hb = apply_linear(h, bp)
    return Decomposition(g, h, bp - hb, hb - a)


def _part_of(dec: Decomposition, part: str, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The same part, with the pair's g and H, of another pair of signals (the references)."""
    bp = dec.g * b
    if part == "all":
        return bp - a
    hb = apply_linear(dec.h, bp)
    return hb - a if part == "character" else bp - hb


def levels(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """How different the pair is, dB re A (rms): all (B' - A), character, tone."""
    a, b = _trim(a, b)
    dec = decompose(a, b)
    return {p: round(_rms_db(dec.part(p), a), 2) for p in PARTS}


def residual_db(a: np.ndarray, b: np.ndarray, part: str = "all") -> float:
    """Level of the pair's `part` difference, dB re A."""
    a, b = _trim(a, b)
    return _rms_db(decompose(a, b).part(part), a)


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


def _warnings(gr: float, gr_pair: float, env: dict) -> list[str]:
    out = []
    if abs(gr - gr_pair) > ARTIFACT_GR_DB:
        out.append(f"GR {gr:.2f} dB, the pair's {gr_pair:.2f}")
    if env["worst_db"] > ARTIFACT_ENVELOPE_DB:
        out.append(f"envelope off A's by up to {env['worst_db']:.1f} dB")
    return out


def streams(
    a: np.ndarray, b: np.ndarray, ref_a: np.ndarray, ref_b: np.ndarray, sample_rate: int,
    part: str = "all", ks: Sequence[float] = EXAGGERATION_K,
) -> dict[str, Any]:  # fmt: skip
    """A, B and A + k d (d the pair's `part`) for each k, at one loudness, and d itself
    turned up on its own; with each stream's k, GR, envelope against A's, the gain the
    loudness match applied, and its artifacts; and the pair's levels."""
    a, b, ref_a, ref_b = _trim(a, b, ref_a, ref_b)
    dec = decompose(a, b)
    d, d_ref = dec.part(part), _part_of(dec, part, ref_a, ref_b)
    gr_a = stimuli.average_gr_db(ref_a, a, sample_rate)
    gr_b = stimuli.average_gr_db(ref_b, b, sample_rate)
    gr_pair = 0.5 * (gr_a + gr_b)
    label = {"all": "B-A", "character": "C", "tone": "T"}[part]
    named = [("A", 0.0, a, ref_a), ("B", None, b, ref_b)]
    term = f"({label})" if part == "all" else label
    named += [(f"A+{k:g}{term}", float(k), a + k * d, ref_a + k * d_ref) for k in ks]
    matched, info = matching.match_loudness([y for *_, y, _ in named], sample_rate)
    out = []
    for (name, k, y, ref), ym, gain_db in zip(named, matched, info.gains_db, strict=True):
        gr = stimuli.average_gr_db(ref, y, sample_rate)
        env = envelope_db(ym, matched[0], sample_rate)
        exaggerated = k not in (None, 0.0)
        out.append({
            "name": name, "k": k if k is not None else 1.0, "exaggerated": exaggerated,
            "audio": ym, "gr_db": round(gr, 3), "envelope": env, "gain_db": round(gain_db, 3),
            "artifacts": _warnings(gr, gr_pair, env) if exaggerated else [],
        })  # fmt: skip
    (dm,), dinfo = matching.match_loudness([d], sample_rate)
    lv = {p: round(_rms_db(dec.part(p), a), 2) for p in PARTS}
    return {
        "part": part,
        "align_gain_db": round(float(20 * np.log10(abs(dec.g))), 4) if dec.g else None,
        "gr_db": {"A": round(gr_a, 3), "B": round(gr_b, 3)},
        "levels_db": lv,  # every part's level re A
        "target_lufs": round(float(info.target_lufs), 2),
        "peak_limited": bool(info.target_lufs < matching.TARGET_LUFS - 1e-9),
        "streams": out,
        "residual": {
            "name": label,
            "audio": dm,
            "level_db": lv[part],
            "gain_db": round(dinfo.gains_db[0], 2),
            "target_lufs": round(dinfo.target_lufs, 2),
        },  # fmt: skip
    }


def exaggerated_pair(
    a: np.ndarray, b: np.ndarray, ref_a: np.ndarray, ref_b: np.ndarray, k: float,
    sample_rate: int, part: str = "all",
) -> dict[str, Any]:  # fmt: skip
    """(A, A + k d) at one loudness, d the pair's `part`, for discrimination
    (varimu.listen.abx), with what was played: the gains, the LUFS after them, the
    GRs, the envelope, artifacts."""
    a, b, ref_a, ref_b = _trim(a, b, ref_a, ref_b)
    dec = decompose(a, b)
    x = a + k * dec.part(part)
    ref_x = ref_a + k * _part_of(dec, part, ref_a, ref_b)
    (ma, mx), info = matching.match_loudness([a, x], sample_rate)
    gr_a = stimuli.average_gr_db(ref_a, a, sample_rate)
    gr_x = stimuli.average_gr_db(ref_x, x, sample_rate)
    env = envelope_db(mx, ma, sample_rate)
    real = part == "all" and k == 1.0
    return {
        "audio": (ma, mx),
        "gains_db": [round(v, 3) for v in info.gains_db],
        "lufs_after": [round(matching.integrated_lufs(y, sample_rate), 3) for y in (ma, mx)],
        "gr_db": [round(gr_a, 3), round(gr_x, 3)],
        "envelope": env,
        "artifacts": [] if real else _warnings(gr_x, gr_a, env),
    }

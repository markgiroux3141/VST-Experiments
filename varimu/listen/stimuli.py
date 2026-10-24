"""Matched stimuli for blind A/B (Phase 5): a candidate on a clip at a target gain reduction.

"Loudness lies" (the plan's guiding principles): two renders compared by ear must
compress the same amount and play at the same loudness, or the louder and the
more compressed one wins. So every stimulus is

- **gain-reduction matched** (`match`): the candidate is set up as the factory
  would (varimu.sim.setup.adjust: B+ ADJ, BALANCE, ZERO; the front panel at the
  factory adjustment: pad and DC THRESHOLD), and its AC THRESHOLD is solved so
  that its average gain reduction on the excerpt equals the target (e.g. 3 or 6 dB).
  Gain reduction is measured against the same unit at AC THRESHOLD 0 (no
  limiting), so its own transformers and tubes are in both sides: per 50 ms
  window, 20 log10 of the reference's rms over the render's, averaged over the
  windows within GATE_DB of the reference's loudest (`average_gr_db`). The solve is
  monotone interpolation on a parallel grid, then refinements (the estimate and a
  neighbour either side, rendered together) to GR_TOL_DB;
- **loudness matched** at playback (varimu.listen.matching.match_loudness: one
  integrated LUFS for the pair, lowered together if a peak would clip).

Both are verified by measurement: the solved render's GR is re-measured (it is
the measurement that stops the solve), and the pair's LUFS after the gains
(`verify_pair`).

Excerpts: renders run ~17x slower than real time, so a clip longer than the
pool's excerpt length is played from its loudest window of that length
(`default_excerpt`), faded in and out over FADE_S (DC into T101 at the start of
a run saturates its core: CLAUDE.md, core quirks).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from varimu.config import DATA_DIR, load_sim_settings
from varimu.listen import matching
from varimu.listen.candidates import Candidate

CLIP_DIR = DATA_DIR / "clips"
CLIP_SUFFIXES = (".wav", ".flac", ".aiff", ".aif")
GR_WINDOW_S = 0.05
GATE_DB = 30.0
GR_TOL_DB = 0.1
GRID = (0.25, 0.4, 0.55, 0.7, 0.85, 1.0)  # AC THRESHOLD, first batch
LOW_GRID = (0.05, 0.1, 0.15, 0.2)  # when the target is below the first batch's GR
MAX_SECANT = 4
REFINE_STEP = 0.01  # AC THRESHOLD: each refinement also renders this either side
FADE_S = 0.05


@dataclass(frozen=True)
class Excerpt:
    clip: str  # file name in data/clips
    start_s: float
    seconds: float

    @property
    def label(self) -> str:
        return f"{self.clip}@{self.start_s:g}+{self.seconds:g}s"


def clip_names() -> list[str]:
    if not CLIP_DIR.is_dir():
        return []
    return sorted(p.name for p in CLIP_DIR.iterdir() if p.suffix.lower() in CLIP_SUFFIXES)


def _clip(name: str) -> np.ndarray:
    from varimu.sim.io import load_audio

    return load_audio(CLIP_DIR / name, load_sim_settings().sample_rate)


def default_excerpt(name: str, seconds: float, x: np.ndarray | None = None) -> Excerpt:
    """The whole clip if it is no longer than `seconds`, else its loudest window of
    that length (rms, on a 0.1 s grid)."""
    fs = load_sim_settings().sample_rate
    x = _clip(name) if x is None else x
    dur = len(x) / fs
    if dur <= seconds:
        return Excerpt(name, 0.0, round(dur, 3))
    hop = int(0.1 * fs)
    e = np.square(x[: len(x) // hop * hop]).reshape(-1, hop).sum(1)
    w = int(round(seconds / 0.1))
    best = int(np.argmax(np.convolve(e, np.ones(w), "valid")))
    return Excerpt(name, round(best * 0.1, 3), seconds)


def excerpt_audio(ex: Excerpt, x: np.ndarray | None = None) -> np.ndarray:
    fs = load_sim_settings().sample_rate
    x = _clip(ex.clip) if x is None else x
    a = int(ex.start_s * fs)
    y = x[a : a + int(ex.seconds * fs)].copy()
    n = min(int(FADE_S * fs), len(y) // 2)
    ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(n) + 0.5) / n)
    y[:n] *= ramp
    y[len(y) - n :] *= ramp[::-1]
    return y


def average_gr_db(reference: np.ndarray, out: np.ndarray, sample_rate: int) -> float:
    """Mean gain reduction (dB) of `out` re `reference` (the same unit, no limiting)
    over GR_WINDOW_S windows within GATE_DB of the reference's loudest window."""
    w = int(GR_WINDOW_S * sample_rate)
    n = min(len(reference), len(out)) // w * w
    r = np.sqrt(np.mean(np.square(reference[:n]).reshape(-1, w), axis=1))
    y = np.sqrt(np.mean(np.square(out[:n]).reshape(-1, w), axis=1))
    keep = r >= r.max() * 10 ** (-GATE_DB / 20)
    keep &= y > 0
    return float(np.mean(20 * np.log10(r[keep] / y[keep])))


@dataclass(frozen=True)
class Stimulus:
    """A matched render: what was solved, measured and rendered."""

    candidate_id: str
    candidate: str
    clip: str
    start_s: float
    seconds: float
    time_constant: int
    gr_target_db: float
    solved: bool  # False: the target is out of the threshold's reach
    ac_threshold: float
    gr_db: float  # measured on the final render
    render_key: str
    reference_key: str  # the no-limiting render
    overrides: dict[str, Any]
    renders: int  # renders the solve took (cached ones included)

    def public(self) -> dict[str, Any]:
        return asdict(self)


# A render function: (input samples, overrides) -> (output samples, render key).
RenderFn = Callable[[Sequence[tuple[np.ndarray, Mapping[str, Any]]]], list[tuple[np.ndarray, str]]]


def circuit_renders(jobs):
    """The production renderer (varimu.sim.runner: cached, parallel)."""
    from varimu.sim import runner

    rs = runner.render_many(runner.RenderJob(x, dict(ov), "listen") for x, ov in jobs)
    return [(r.output, r.key) for r in rs]


def unit_overrides(c: Candidate) -> dict[str, Any]:
    """The candidate set up as the factory would: the DC trims (setup.adjust); the
    front panel stays at its factory adjustment (the circuit's defaults)."""
    from varimu.sim import setup

    return setup.adjust(dict(c.genome))


def match(
    c: Candidate,
    ex: Excerpt,
    target_db: float,
    time_constant: int,
    *,
    render: RenderFn | None = None,
    base: Mapping[str, Any] | None = None,
    x: np.ndarray | None = None,
    log: Callable[[str], Any] = lambda m: None,
) -> Stimulus:
    """Solve AC THRESHOLD for `target_db` of average gain reduction on the excerpt."""
    render = render or circuit_renders
    fs = load_sim_settings().sample_rate
    x = excerpt_audio(ex) if x is None else x
    ov = dict(unit_overrides(c) if base is None else base)
    ov["time_constant"] = int(time_constant)
    count = 0

    def run(acs):
        nonlocal count
        count += len(acs)
        return render([(x, {**ov, "ac_threshold": round(float(a), 4)}) for a in acs])

    (ref, ref_key), *grid = run([0.0, *GRID])
    pts = {
        round(a, 4): (average_gr_db(ref, y, fs), k) for a, (y, k) in zip(GRID, grid, strict=True)
    }
    if target_db < min(g for g, _ in pts.values()):
        pts |= {
            round(a, 4): (average_gr_db(ref, y, fs), k)
            for a, (y, k) in zip(LOW_GRID, run(LOW_GRID), strict=True)
        }

    def result(a, solved):
        g, k = pts[a]
        log(f"{c.name} {ex.label} {target_db:g} dB: AC {a:.4f} -> {g:.3f} dB ({count} renders)")
        return Stimulus(
            c.id, c.name, ex.clip, ex.start_s, ex.seconds, int(time_constant), float(target_db),
            solved, a, round(g, 4), k, ref_key, {**ov, "ac_threshold": a}, count,
        )  # fmt: skip

    for _ in range(MAX_SECANT + 1):
        acs = sorted(pts)
        grs = np.array([pts[a][0] for a in acs])
        best = min(acs, key=lambda a: abs(pts[a][0] - target_db))
        if abs(pts[best][0] - target_db) <= GR_TOL_DB:
            return result(best, True)
        if target_db > grs.max():
            return result(acs[int(np.argmax(grs))], False)
        # The bracketing pair (GR rises with AC THRESHOLD; take the first crossing).
        i = int(np.argmax(grs >= target_db))
        a0, a1, g0, g1 = acs[max(i - 1, 0)], acs[i], grs[max(i - 1, 0)], grs[i]
        a = a1 if g1 == g0 else a0 + (target_db - g0) * (a1 - a0) / (g1 - g0)
        a = round(float(np.clip(a, 0.0, 1.0)), 4)
        if a in pts:
            return result(best, abs(pts[best][0] - target_db) <= 2 * GR_TOL_DB)
        # The estimate and its close neighbours at once: the next bracket is then tight.
        near = (a, a - REFINE_STEP, a + REFINE_STEP)
        new = [v for v in dict.fromkeys(round(float(np.clip(v, 0, 1)), 4) for v in near)
               if v not in pts]  # fmt: skip
        for ac, (y, k) in zip(new, run(new), strict=True):
            pts[ac] = (average_gr_db(ref, y, fs), k)
    best = min(pts, key=lambda a: abs(pts[a][0] - target_db))
    return result(best, abs(pts[best][0] - target_db) <= GR_TOL_DB)


def verify_pair(a: np.ndarray, b: np.ndarray, sample_rate: int) -> dict[str, Any]:
    """Loudness-match a pair for playback, and measure the result."""
    (ma, mb), info = matching.match_loudness([a, b], sample_rate)
    after = [matching.integrated_lufs(y, sample_rate) for y in (ma, mb)]
    return {
        "audio": (ma, mb),
        "gains_db": [round(g, 3) for g in info.gains_db],
        "lufs_before": [round(v, 3) for v in info.measured_lufs],
        "lufs_after": [round(v, 3) for v in after],
        "lufs_diff": round(abs(after[0] - after[1]), 4),
    }

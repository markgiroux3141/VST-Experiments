"""Steady-tone levels in the manual's units: dBm at the unit's 600 ohm terminals.

The 670 manual specifies levels in dBm (power into 600 ohm: 0 dBm = 0.775 V rms).
The input is measured at the unit's input terminals (node `in_s`, behind the
source impedance), the output across the 600 ohm load (`out`), so neither depends
on how the input impedance terminates the source. Input EMFs are chosen from
dBm through `k_db`, the terminals' level re the EMF (dBm - dBFS), which the
input pad sets (varimu.sim.setup.threshold measures it).

Two ways to hold a tone:

- `tone_levels`: one render per level, the tone rising over RISE_S (a raised
  cosine: the control voltage follows the level up instead of overshooting it at
  an abrupt onset and then relaxing at the release time), held, measured over its
  last MEASURE_S. For a few points (the threshold procedure).
- `Staircase`: rising levels held HOLD_S each, rendered in parallel chunks of
  CHUNK steps with WARMUP steps in front whose results are dropped (as
  scripts/slice_report.py's compression curve: levels only rise and every step
  settles, so the chunks give the continuous staircase's values). Each step is
  measured over its last TAIL fraction: levels, the control voltage, and the
  output's harmonics (metrics.harmonics).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from varimu.config import load_sim_settings
from varimu.measure import metrics, signals
from varimu.sim import runner

DBM_V_RMS = float(np.sqrt(1e-3 * 600.0))  # 0 dBm into 600 ohm
TONE_HZ = 1000.0
RISE_S = 0.3
HOLD_S = 0.5
MEASURE_S = 0.2
CHUNK = 6
WARMUP = 1
TAIL = 0.3


def dbm(v_rms: float) -> float:
    return float(20 * np.log10(v_rms / DBM_V_RMS + 1e-30))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def emf_dbfs_for(in_dbm: float, k_db: float) -> float:
    """The input EMF (dBFS peak) that puts `in_dbm` on the terminals, given the
    terminals' level re the EMF, `k_db` = in_dbm - EMF in dBFS (measured; it depends
    on the input pad, through the input impedance)."""
    return in_dbm - k_db


def tone(amp: float, *, freq_hz: float = TONE_HZ, sample_rate: int | None = None) -> np.ndarray:
    """A sine of peak `amp` (dBFS-scaled) rising over RISE_S and held for HOLD_S. Whole
    carrier cycles in the measured tail when sample_rate / freq_hz is an integer."""
    fs = sample_rate or load_sim_settings().sample_rate
    n_rise, n = int(RISE_S * fs), int((RISE_S + HOLD_S) * fs)
    t = np.arange(n) / fs
    env = np.ones(n)
    env[:n_rise] = 0.5 - 0.5 * np.cos(np.pi * (np.arange(n_rise) + 0.5) / n_rise)
    return amp * env * np.sin(2 * np.pi * freq_hz * t)


@dataclass(frozen=True)
class ToneLevel:
    in_dbm: float  # at the input terminals
    out_dbm: float  # across the load
    cv_v: float  # the control voltage (6386 grid centre tap), median over the tail
    key: str  # the render

    @property
    def gain_db(self) -> float:
        return self.out_dbm - self.in_dbm


def tone_levels(
    jobs: Sequence[tuple[Mapping[str, Any], float]],
    *,
    freq_hz: float = TONE_HZ,
    settings=None,
    label: str = "tone",
) -> list[ToneLevel]:
    """(overrides, input EMF in dBFS peak) -> the settled levels, rendered in parallel."""
    fs = load_sim_settings().sample_rate
    rjobs = [
        runner.RenderJob(
            tone(10 ** (lv / 20), freq_hz=freq_hz, sample_rate=fs),
            dict(ov),
            f"{label}:{freq_hz:g}Hz@{lv:+.2f}dBFS",
        )
        for ov, lv in jobs
    ]
    out = []
    for r in runner.render_many(rjobs, settings=settings):
        tail = slice(-int(MEASURE_S * fs), None)
        v = r.vectors
        out.append(
            ToneLevel(
                dbm(rms(v["v(in_s)"][tail])),
                dbm(rms(v["v(out)"][tail])),
                float(np.median(v["v(cv)"][tail])),
                r.key[:12],
            )
        )
    return out


@dataclass(frozen=True)
class StepLevel:
    """One staircase step, settled."""

    emf_dbfs: float
    in_dbm: float
    out_dbm: float
    cv_v: float
    harmonics: metrics.Harmonics  # of the output, in volts

    @property
    def gain_db(self) -> float:
        return self.out_dbm - self.in_dbm


def _whole_periods(n: int, freq_hz: float, fs: int) -> int:
    """The largest length <= n holding a whole number of periods (exactly, when fs /
    freq_hz is rational with a small denominator, as for the frequencies used here)."""
    per = fs / freq_hz
    k = int(n // per)
    while k > 1 and abs(k * per - round(k * per)) > 1e-9:
        k -= 1
    return round(k * per)


@dataclass
class Staircase:
    """A rising 1-tone staircase on one front panel (EMF levels in dBFS peak)."""

    overrides: dict[str, Any]
    emf_dbfs: Sequence[float]
    freq_hz: float = TONE_HZ
    hold_s: float = HOLD_S
    label: str = "steps"
    _parts: list = field(default_factory=list, repr=False)

    def __post_init__(self):
        if np.any(np.diff(self.emf_dbfs) <= 0):
            raise ValueError("a staircase's levels must rise")
        fs = load_sim_settings().sample_rate
        sig = signals.stepped_levels(
            freq_hz=self.freq_hz,
            levels_dbfs=list(self.emf_dbfs),
            hold_s=self.hold_s,
            sample_rate=fs,
        )
        segs = sig.meta["segments"]
        for i0 in range(0, len(segs), CHUNK):
            i1 = min(i0 + CHUNK, len(segs))
            a, b = segs[max(0, i0 - WARMUP)]["start"], segs[i1 - 1]["stop"]
            local = [dict(s, start=s["start"] - a, stop=s["stop"] - a) for s in segs[i0:i1]]
            job = runner.RenderJob(
                sig.samples[a:b],
                dict(self.overrides),
                f"{self.label}:{self.freq_hz:g}Hz[{i0}:{i1}]",
            )
            self._parts.append((job, local))

    def jobs(self) -> list[runner.RenderJob]:
        return [j for j, _ in self._parts]

    def measure(self, settings=None) -> list[StepLevel]:
        """Every step's settled levels (renders from the cache when prefetched)."""
        fs = load_sim_settings().sample_rate
        renders = runner.render_many(self.jobs(), settings=settings)
        out = []
        for (_, segs), r in zip(self._parts, renders, strict=True):
            v = r.vectors
            for s in segs:
                n = _whole_periods(int((s["stop"] - s["start"]) * TAIL), self.freq_hz, fs)
                sl = slice(s["stop"] - n, s["stop"])
                y = v["v(out)"][sl]
                out.append(
                    StepLevel(
                        float(s["level_dbfs"]),
                        dbm(rms(v["v(in_s)"][sl])),
                        dbm(rms(y - np.mean(y))),
                        float(np.median(v["v(cv)"][sl])),
                        metrics.harmonics(y, self.freq_hz, fs),
                    )
                )
        return out

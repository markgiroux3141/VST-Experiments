"""Listening samples for HYBRID_PHYSICS_PLAN.md H2's options: four scales on RCA's 884 sweep
oscillator through each way of simulating it -> reports/hybrid/audio/h2_scales/

    uv run --extra fast --extra listen python scripts/thyratron_scale_demo.py [--workers N]

Each scale is a major scale up an octave on one S1 range, its notes tuned with R6 (the fine
rheostat; the period against R6 from production runs with the slow capacitors preset,
interpolated): A1-A2 on C2 (the circuit's lowest: R6 at its top is ~52 Hz), D3-D4 on C3,
G5-G6 on C5, B7-B8 on C7. Each note is a run of its own (0.5 s, the slow capacitors preset
as in scripts/thyratron_event_study.py, whose runs and cache it shares), its 0.08-0.43
s joined to the next with a 10 ms crossfade. The output is the 6J7's grid (n8: the sweep
through C9), every version matched to -16 LUFS (BS.1770; lower if a peak would pass
0.98).

Versions (the event study's modes):
- `1_reference`: the reference (3.072 MHz, production's method) band-limited to 20 kHz:
  the physics without the grid's errors, what K and M1 both aim at;
- `2_production_8x`: production's method at 8x through renders' decimator (what M1 would
  give: the oscillator at 8x behind an anti-alias filter);
- `3_production`: today's production render (2x, error control);
- `4_island_8x_esdirk4`: M as built (M0), point-sampled at 96 kHz;
- `5_draft_2x`: the native app's Play quality today (96 kHz behind a 48 kHz host).
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import thyratron_event_study as st  # noqa: E402

from varimu.config import REPO_ROOT  # noqa: E402

OUT = REPO_ROOT / "reports" / "hybrid" / "audio" / "h2_scales"
MAJOR = (0, 2, 4, 5, 7, 9, 11, 12)
SCALES = ((2, "A1", 55.0), (3, "D3", 146.832), (5, "G5", 783.991), (7, "B7", 3951.07))
VERSIONS = (
    ("1_reference", "reference"),
    ("2_production_8x", "production-8x"),
    ("3_production", "production"),
    ("4_island_8x_esdirk4", "island-8x-esdirk4"),
    ("5_draft_2x", "draft-2x"),
)
CAL_FINES = (0.0, 0.25, 0.5, 0.75, 1.0)
NOTE_S = (0.08, 0.43)
FADE_S = 0.01
GAP_S = 0.5
TARGET_LUFS = -16.0


def pitch(r: dict) -> float:
    y = (r["v"]["out"] - r["v"]["k"])[int(0.2 * r["rate"]) :]
    ev = st.events(y, r["rate"])
    return float(r["rate"] / np.mean(np.diff([top for top, _ in ev])))


def spectral_pitch(r: dict, hint_hz: float) -> float:
    """A run's pitch from its spectrum at 96 kHz (the event study's harmonic estimate: the
    draft's ringing crosses the midpoint more than once a period)."""
    y = r["v"]["out"] - r["v"]["k"]
    y = st.band_limit_ref(y) if r["mode"] == "reference" else y
    return st.spectrum_metrics(y[int(0.15 * st.FS) :], st.FS, hint_hz)["f0_hz"]


def job(rng, fine, mode, preset=None, seconds=0.5):
    return dict(range=rng, fine=round(float(fine), 6), cond="", over={}, mode=mode,
                seconds=seconds, preset=preset, fresh=False)  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workers", type=int, default=7)
    args = ap.parse_args()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        # tuning: the period against R6, per range
        # (with the slow capacitors preset, as the notes: C9's load moves the pitch ~3%)
        cal_at = [(r, f) for r, _, _ in SCALES for f in CAL_FINES]
        cal_pre = list(ex.map(st.run_cached, [job(r, f, "preset", seconds=4.0) for r, f in cal_at]))
        cal_jobs = [
            job(r, f, "production", st.preset_of(p))
            for (r, f), p in zip(cal_at, cal_pre, strict=True)
        ]
        cal = list(ex.map(st.run_cached, cal_jobs))
        notes = []
        for rng, name, f_root in SCALES:
            fs_, ts = zip(
                *[(c["fine"], 1 / pitch(c)) for c in cal if c["range"] == rng], strict=True
            )
            for k in MAJOR:
                t = 1 / (f_root * 2 ** (k / 12))
                if not min(ts) <= t <= max(ts):
                    raise SystemExit(f"{name}+{k}: {1 / t:.1f} Hz is outside C{rng}'s range")
                notes.append((rng, float(np.interp(t, ts, fs_)), f"{name}+{k}"))
        print(f"notes: {len(notes)}; presets")
        pre = list(ex.map(st.run_cached, [job(r, f, "preset", seconds=4.0) for r, f, _ in notes]))
        presets = [st.preset_of(p) for p in pre]
        jobs = [
            job(r, f, m, p)
            for (r, f, _), p in zip(notes, presets, strict=True)
            for _, m in VERSIONS
        ]
        print(f"renders: {len(jobs)}")
        runs = list(ex.map(st.run_cached, jobs))
    by = {(r["range"], r["fine"], r["mode"]): r for r in runs}
    fs = st.FS
    fade = int(FADE_S * fs)
    ramp = np.linspace(0.0, 1.0, fade)
    tracks = {}
    for label, mode in VERSIONS:
        parts = []
        for i, (rng, fine, _) in enumerate(notes):
            r = by[rng, round(fine, 6), mode]
            y = st.band_limit_ref(r["v"]["n8"]) if mode == "reference" else r["v"]["n8"]
            y = y[int(NOTE_S[0] * fs) : int(NOTE_S[1] * fs)].copy()
            y -= y.mean()
            first = i % len(MAJOR) == 0
            last = i % len(MAJOR) == len(MAJOR) - 1
            if first:
                y[:fade] *= ramp
            if last:
                y[-fade:] *= ramp[::-1]
            if parts and not first:  # crossfade into the previous note
                prev = parts[-1]
                prev[-fade:] = prev[-fade:] * ramp[::-1] + y[:fade] * ramp
                y = y[fade:]
            elif parts:
                parts.append(np.zeros(int(GAP_S * fs)))
            parts.append(y)
        tracks[label] = np.concatenate(parts)
    # every version at one integrated loudness (BS.1770), the target lowered if a peak
    # would pass the ceiling (varimu.listen.matching's rule)
    from varimu.listen.matching import PEAK_CEILING, integrated_lufs

    lufs = {k: integrated_lufs(t, fs) for k, t in tracks.items()}
    target = min(
        TARGET_LUFS,
        *(lufs[k] + 20 * np.log10(PEAK_CEILING / np.max(np.abs(t))) for k, t in tracks.items()),
    )
    import soundfile as sf

    OUT.mkdir(parents=True, exist_ok=True)
    for label, t in tracks.items():
        gain = 10 ** ((target - lufs[label]) / 20)
        db = 20 * np.log10(gain)
        print(f"{label:22s} {lufs[label]:6.1f} LUFS as rendered -> {target:.1f} ({db:+.1f} dB)")
        sf.write(OUT / f"{label}.wav", (t * gain).astype(np.float32), fs, subtype="FLOAT")
    for rng, fine, name in notes:
        runs_ = {m: by[rng, round(fine, 6), m] for _, m in VERSIONS}
        f_ref = spectral_pitch(runs_["reference"], pitch(runs_["reference"]))
        cents = {
            m: 1200 * np.log2(spectral_pitch(r, f_ref) / f_ref)
            for m, r in runs_.items()
            if m != "reference"
        }
        others = "  ".join(f"{m} {c:+5.1f}c" for m, c in cents.items())
        print(f"{name:6s} C{rng} R6 {fine:.3f} ref {f_ref:8.1f} Hz  {others}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()

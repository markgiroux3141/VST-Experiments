"""How uneven a real Mk I is from key to key: the spreads behind the Rhodes imperfection knobs
(docs/RHODES_IMPERFECTION_PLAN.md; varimu/rhodes/imperfection.py cites this script).

    uv run --extra listen python scripts/rhodes_unit_spread.py [--samples DIR]

On jRhodes3d (a 1977 Mk I Stage 73 recorded from the harp connector; see
scripts/rhodes_vs_jrhodes.py for where to put it), 15 notes x up to 5 layers:

- **tuning**: each note's fundamental, from 0.3 s after the onset over 2 s (a zero-padded
  spectrum's peak, refined by a parabola), in cents against equal temperament at A440, the
  median over its softer layers (L3-L5: the loud bass reads sharp from the magnet's pull,
  RHODES_PLAN.md); the spread is the rms about the notes' mean (the piano's own A doesn't
  matter);
- **decay**: config/rhodes/mk1.yaml's measured `q_jrhodes` (the fundamental's Q per note)
  about the cubic in log f the tine's loss is fitted to (spec.py's fit): the rms of ln Q's
  residual (it includes the measurement's own scatter; the layers agree within ~20%).

Writes reports/rhodes/imperfection/unit_spread.json. 15 notes give a standard deviation with
a wide error bar (a chi-square 90% interval is printed with it).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import stats

ROOT = Path(__file__).parents[1]
SAMPLES = (
    ROOT
    / "real instrument samples"
    / "jrhodes3d_download"
    / "jlearman.jRhodes3d-master"
    / "jRhodes3d-mono"
)
OUT = ROOT / "reports" / "rhodes" / "imperfection"


def note_hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12)


def fundamental_hz(y: np.ndarray, fs: float, f0: float) -> float:
    i0 = int(np.argmax(np.abs(y) > 0.05 * np.max(np.abs(y))))
    s = y[i0 + int(0.3 * fs) : i0 + int(2.3 * fs)]
    n = 1 << 22
    mag = np.abs(np.fft.rfft(s * np.hanning(s.size), n))
    fr = np.fft.rfftfreq(n, 1 / fs)
    band = np.flatnonzero((fr > f0 * 0.97) & (fr < f0 * 1.03))
    j = band[np.argmax(mag[band])]
    a, b, c = np.log(mag[j - 1 : j + 2] + 1e-300)
    p = 0.5 * (a - c) / (a - 2 * b + c)
    return float(fr[j] + p * (fr[1] - fr[0]))


def interval(sd: float, n: int, conf: float = 0.9) -> tuple[float, float]:
    """A chi-square interval for a standard deviation from n samples (n - 1 dof)."""
    dof = n - 1
    lo = sd * np.sqrt(dof / stats.chi2.ppf(0.5 + conf / 2, dof))
    hi = sd * np.sqrt(dof / stats.chi2.ppf(0.5 - conf / 2, dof))
    return float(lo), float(hi)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=Path, default=SAMPLES)
    args = ap.parse_args()
    notes: dict[int, dict[int, Path]] = {}
    for p in sorted(args.samples.glob("A_*__*_*.flac")):
        m = re.match(r"A_(\d+)__\w+?_(\d)\.flac", p.name)
        if m:
            notes.setdefault(int(m.group(1)), {})[int(m.group(2))] = p
    cents = {}
    for midi, layers in sorted(notes.items()):
        f0 = note_hz(midi)
        per = []
        for layer in (3, 4, 5):
            if layer in layers:
                y, fs = sf.read(layers[layer], always_2d=True)
                per.append(1200 * np.log2(fundamental_hz(y[:, 0], fs, f0) / f0))
        cents[midi] = float(np.median(per))
        print(f"MIDI {midi}: {cents[midi]:+.2f} cents ({len(per)} layers)")
    c = np.array(list(cents.values()))
    above_e2 = np.array([v for m, v in cents.items() if m >= 40])
    tuning = {
        "per_note_cents": cents,
        "mean_cents": float(c.mean()),
        "rms_about_mean_cents": float(np.std(c, ddof=1)),
        "rms_about_mean_cents_from_e2": float(np.std(above_e2, ddof=1)),
        "n": int(c.size),
    }
    tuning["interval_90"] = interval(tuning["rms_about_mean_cents_from_e2"], above_e2.size)
    import yaml

    cfg = yaml.safe_load((ROOT / "config" / "rhodes" / "mk1.yaml").read_text(encoding="utf-8"))
    fq = np.array(cfg["anchors"]["q_jrhodes"]["value"], float)
    x, lq = np.log(fq[:, 0]), np.log(fq[:, 1])
    resid = lq - np.polyval(np.polyfit(x, lq, 3), x)
    sd = float(np.sqrt(np.sum(resid**2) / (resid.size - 4)))
    decay = {
        "ln_q_residual_rms": sd,
        "n": int(resid.size),
        "residuals": resid.round(3).tolist(),
        "interval_90": interval(sd, resid.size - 3),
    }
    lo, hi = tuning["interval_90"]
    print(
        f"tuning: rms {tuning['rms_about_mean_cents']:.2f} c"
        f" (E2 up {tuning['rms_about_mean_cents_from_e2']:.2f}, 90% {lo:.2f}-{hi:.2f})"
    )
    lo, hi = decay["interval_90"]
    print(f"decay: ln Q residual rms {sd:.3f} (90% {lo:.3f}-{hi:.3f})")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "unit_spread.json").write_text(
        json.dumps({"tuning": tuning, "decay": decay}, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

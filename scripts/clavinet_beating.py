"""CL1: the beating hypothesis (docs/CLAVINET_PLAN.md, "The string"): does the pinch's
anisotropy (the anvil's push against the rubber's sideways grip, their axes tilted) split
the partials into two polarizations that beat at the pickups the way [G13] Fig. 7 shows
(0.5-2 Hz, up to 15 dB peak to peak, only up to E4)? -> reports/clavinet/beating/summary.json

Per key: a long held note, each partial's amplitude envelope at the pickups (a narrow
band around it, Hilbert), the envelope's detrended log ripple (peak to peak in dB) and its
dominant rate; and the held system's mode pairs near each partial (split, shares).

    uv run python scripts/clavinet_beating.py [--keys 17 24 36 43 50] [--hold 6]
"""

from __future__ import annotations

import argparse
import json

import numpy as np
from scipy import signal

from varimu.clavinet import fit, note, strings
from varimu.config import REPO_ROOT

OUT = REPO_ROOT / "reports" / "clavinet" / "beating"
FS = 96000


def envelope_ripple(x: np.ndarray, f_hz: float, t0_s: float = 0.3) -> tuple[float, float]:
    """(peak-to-peak dB of the detrended log envelope, its dominant rate Hz) of x's
    partial at f_hz, from t0_s on."""
    bw = max(0.04 * f_hz, 6.0)
    sos = signal.butter(4, [f_hz - bw, f_hz + bw], btype="band", fs=FS, output="sos")
    y = signal.sosfiltfilt(sos, x)
    env = np.abs(signal.hilbert(y))
    dec = 480  # 200 Hz envelope rate
    e = env[int(t0_s * FS) :: dec]
    e = e[: int(len(e) * 0.9)]
    db = 20 * np.log10(e + 1e-12)
    t = np.arange(db.size) / (FS / dec)
    db = db - np.polyval(np.polyfit(t, db, 2), t)  # the decay and its curvature out
    spec = np.abs(np.fft.rfft(db * np.hanning(db.size)))
    f = np.fft.rfftfreq(db.size, dec / FS)
    band = (f > 0.1) & (f < 10)
    rate = float(f[band][np.argmax(spec[band])]) if band.any() else float("nan")
    return float(np.ptp(db)), rate


def mode_pairs(n: int, count: int) -> list[dict]:
    p = fit.params(n)
    held = strings.system(p, True)
    f, sig, amp = strings.mode_table(held, fit.pickup_row(p, held.lay, 0))
    out = []
    for k in range(1, count + 1):
        near = np.flatnonzero(np.abs(f - k * p.geom.f_hz) < 0.2 * p.geom.f_hz)
        top = near[np.argsort(amp[near])[::-1][:2]]
        if top.size < 2:
            continue
        out.append(
            {
                "partial": k,
                "split_hz": float(abs(f[top[0]] - f[top[1]])),
                "weaker_share_db": float(20 * np.log10(amp[top[1]] / amp[top[0]])),
                "t60_s": [float(np.log(1000) / sig[i]) for i in top],
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", type=int, nargs="+", default=[17, 24, 36, 43, 50])
    ap.add_argument("--hold", type=float, default=6.0)
    ap.add_argument("--velocity", type=float, default=2.5)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in args.keys:
        pl = note.play(n, args.velocity, args.hold, tail_s=0.05)
        f0 = fit.params(n).geom.f_hz
        parts = []
        for k in range(1, 6):
            fk = k * f0
            ripple, rate = envelope_ripple(pl.emf_v["centre"], fk)
            parts.append({"partial": k, "ripple_db": ripple, "rate_hz": rate})
        row = {"key": n, "f0_hz": f0, "partials": parts, "modes": mode_pairs(n, 5)}
        rows.append(row)
        print(n, [(round(q["ripple_db"], 1), round(q["rate_hz"], 2)) for q in parts], flush=True)
    (OUT / "summary.json").write_text(
        json.dumps({"velocity_m_s": args.velocity, "hold_s": args.hold, "keys": rows}, indent=1)
    )


if __name__ == "__main__":
    main()

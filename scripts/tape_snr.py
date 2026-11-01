"""The tape's signal-to-noise against the Ampex 351's spec (docs/TAPE_PLAN.md, TM3): peak
record level (3% THD at 400 Hz) to unweighted noise, 50-15,000 Hz, on tape recorded silent
with the bias on (351 manual p10: 60 dB full track at 7.5 and 15 ips, bias, erase and
amplifier noise included; this is the tape's share, the electronics come with TM5).

    uv run --extra fast python scripts/tape_snr.py [--tape SCOTCH111@3] [--speed 15]
"""

from __future__ import annotations

import argparse
import math
import sys

import numpy as np
from scipy import signal as sps

from varimu.config import REPO_ROOT
from varimu.devices import library
from varimu.devices.tape_machine import MINUS_18_DBFS_PEAK, TapeMachineSpec, aligned, print_audio

FS = 96_000.0


def thd(spec, tape, al, drive_db: float) -> tuple[float, float]:
    n = int(0.4 * FS)
    x = MINUS_18_DBFS_PEAK * np.sin(2 * math.pi * 400.0 * np.arange(n) / FS)
    y = print_audio(x, FS, spec, tape, al, drive_db=drive_db)
    seg = y[n // 3 :]
    k = np.arange(len(seg))
    a = [
        abs(2 * np.mean(seg * np.exp(-2j * math.pi * h * 400.0 * k / FS))) for h in (1, 2, 3, 4, 5)
    ]
    return math.sqrt(sum(v * v for v in a[1:])) / a[0], a[0] / math.sqrt(2.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tape", default="SCOTCH111@3")
    ap.add_argument("--speed", type=float, default=15.0, help="ips")
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    tape = library.load_tape(a.tape)
    spec = TapeMachineSpec().at_speed(a.speed * 0.0254)
    al = aligned(spec, tape, REPO_ROOT / "cache" / "tape")
    lo, hi = 0.0, 18.0
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if thd(spec, tape, al, mid)[0] < 0.03 else (lo, mid)
    drive = 0.5 * (lo + hi)
    _, ref_rms = thd(spec, tape, al, drive)
    y = print_audio(np.zeros(int(a.seconds * FS)), FS, spec, tape, al, noise_seed=1)
    f, p = sps.welch(y[int(0.5 * FS) :], FS, nperseg=1 << 15)
    band = (f >= 50) & (f <= 15000)
    noise_rms = math.sqrt(p[band].sum() * (f[1] - f[0]))
    snr = 20 * math.log10(ref_rms / noise_rms)
    print(
        f"{a.tape} at {a.speed:g} ips: 3% THD at {drive:+.2f} dB over 0 VU; "
        f"S/N {snr:.1f} dB (50-15,000 Hz, unweighted; the 351's spec: 60 dB with its "
        "electronics)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

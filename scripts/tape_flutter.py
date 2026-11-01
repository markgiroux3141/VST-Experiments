"""The transport's wow and flutter (docs/TAPE_PLAN.md, TM3), measured as a flutter meter
does: a 3150 Hz tone printed (recorded and played back on the moving tape), its
instantaneous frequency demodulated, the deviation's rms over 0.5-250 Hz (the 351's spec:
0.11% rms at 15 ips, ASA Z57.1-1954, unweighted) and above. Plots the speed's spectrum and
the deviation's.

    uv run --extra fast python scripts/tape_flutter.py [--seconds 8] [--speed 15]
"""

from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np
from scipy import signal as sps

from varimu.config import REPO_ROOT
from varimu.devices import library
from varimu.devices.tape_machine import (
    MINUS_18_DBFS_PEAK,
    TapeMachineSpec,
    TapeStream,
    aligned,
    print_audio,
)

FS = 96_000.0
OUT = REPO_ROOT / "reports" / "tape"


def band_rms(x: np.ndarray, fs: float, lo: float, hi: float) -> float:
    k = np.fft.rfft(x - x.mean())
    f = np.fft.rfftfreq(len(x), 1.0 / fs)
    m = (f >= lo) & (f <= hi)
    return math.sqrt(2.0 * float(np.sum(np.abs(k[m]) ** 2))) / len(x)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--speed", type=float, default=15.0, help="ips")
    ap.add_argument("--tape", default="SCOTCH111@3")
    a = ap.parse_args()
    tape = library.load_tape(a.tape)
    spec = TapeMachineSpec().at_speed(a.speed * 0.0254)
    al = aligned(spec, tape, REPO_ROOT / "cache" / "tape")

    # The speed itself.
    st = TapeStream(spec, tape, al.hg_bias, FS)
    eps = st._speeds(1, int(a.seconds * FS)) / spec.speed_m_s - 1.0
    speed = {
        "0.5-250 Hz": band_rms(eps, FS, 0.5, 250.0),
        "250 Hz-10 kHz": band_rms(eps, FS, 250.0, 1e4),
    }

    # A 3150 Hz tone through the tape, its frequency demodulated.
    n = int(a.seconds * FS)
    x = MINUS_18_DBFS_PEAK * np.sin(2 * math.pi * 3150.0 * np.arange(n) / FS)
    y = print_audio(x, FS, spec, tape, al)
    sos = sps.butter(4, [2000.0, 4500.0], btype="bandpass", fs=FS, output="sos")
    z = sps.hilbert(sps.sosfiltfilt(sos, y))
    inst = np.diff(np.unwrap(np.angle(z))) * FS / (2 * math.pi)
    dev = inst[int(0.3 * FS) : -int(0.1 * FS)] / 3150.0 - 1.0
    measured = {
        "0.5-250 Hz": band_rms(dev, FS, 0.5, 250.0),
        "250 Hz-2 kHz": band_rms(dev, FS, 250.0, 2000.0),
    }
    print(
        f"{a.speed:g} ips: speed eps {100 * speed['0.5-250 Hz']:.3f}% rms 0.5-250 Hz "
        f"({100 * speed['250 Hz-10 kHz']:.3f}% above); measured on a 3150 Hz tone "
        f"{100 * measured['0.5-250 Hz']:.3f}% rms 0.5-250 Hz (the 351: 0.11% at 15 ips)"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"flutter_{a.speed:g}ips.json").write_text(
        json.dumps(
            {"speed_rms": speed, "measured_rms": measured, "components": spec.transport()}, indent=1
        )
    )

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for sig, label in ((eps, "tape speed (1 + eps)"), (dev, "3150 Hz tone, demodulated")):
        f, p = sps.welch(sig - sig.mean(), FS, nperseg=1 << 18)
        ax.loglog(f[1:], np.sqrt(p[1:]) * 100, label=label)
    ax.axvspan(0.5, 250, color="0.9", zorder=0, label="the spec's band")
    ax.set_xlim(0.2, 1e4)
    ax.set_xlabel("Hz")
    ax.set_ylabel("% / sqrt(Hz)")
    ax.set_title(
        f"Wow and flutter at {a.speed:g} ips: {100 * measured['0.5-250 Hz']:.3f}% rms (0.5-250 Hz)",
        fontsize=10,
    )
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(OUT / f"flutter_{a.speed:g}ips.png", dpi=120)
    return 0


if __name__ == "__main__":
    sys.exit(main())

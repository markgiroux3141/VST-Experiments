"""Where a stereo plate's second pickup goes (docs/REVERB_PLAN.md, "Stereo"): the two
pickups' impulse responses (varimu.devices.plate's reference) per octave band, the second's
level against the first's and their correlation. The EMT 140 TS's brochure (p.6) has its
two pickups "mounted at unequal distances from the driving coil" so that their outputs are
"entirely uncorrelated"; the positions aren't published, so a component's `pickup2_xy` is
placed where it matches the first pickup's level per band and doesn't correlate with it.

    uv run python scripts/plate_pickups.py EMT140@2 [x,y ...]

Without positions it reports the component's own `pickup2_xy`. The responses are the full
model's (the direct wave from the exciter included: near it the two pickups see the same
coherent wave, which a modal energy sum misses), at 8 kHz with the modes below 3.2 kHz and
a 40 dB tail, the damper at 2 s: the low bands are the question, above ~1 kHz any two
places decorrelate.
"""

from __future__ import annotations

import argparse
import dataclasses
import math

import numpy as np
from scipy.signal import butter, sosfiltfilt

from varimu.devices import plate as plt
from varimu.devices.library import load_plate

FS = 8000.0
BANDS_HZ = (125, 250, 500, 1000, 2000)


def bands(h: np.ndarray) -> list[np.ndarray]:
    """h above 40 Hz, in octave bands."""
    h = sosfiltfilt(butter(4, 40.0, "highpass", fs=FS, output="sos"), h)
    out = []
    for f in BANDS_HZ:
        edges = [f / math.sqrt(2), min(f * math.sqrt(2), 0.45 * FS)]
        out.append(sosfiltfilt(butter(4, edges, "bandpass", fs=FS, output="sos"), h))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("component", help="a plate component version, e.g. EMT140@2")
    ap.add_argument("positions", nargs="*", help="x,y as fractions of the sides")
    args = ap.parse_args()
    c = load_plate(args.component)
    spec = plt.PlateSpec(
        c.lx_m, c.ly_m, c.thickness_m, c.density_kg_m3, c.youngs_pa, c.poisson,
        c.tension_n_m, c.drive_xy, c.pickup_xy, 0.4 * FS, plt.decay_table(c, 2.0), 40.0,
    )  # fmt: skip
    if args.positions:
        cands = [tuple(float(v) for v in p.split(",")) for p in args.positions]
    elif c.pickup2_xy is not None:
        cands = [c.pickup2_xy]
    else:
        raise SystemExit(f"{args.component} has no pickup2_xy: give positions")
    first = bands(plt.impulse_response(spec, FS))

    def dist(xy: tuple[float, float]) -> float:
        return math.hypot((xy[0] - c.drive_xy[0]) * c.lx_m, (xy[1] - c.drive_xy[1]) * c.ly_m)

    print(
        f"{args.component}: drive {c.drive_xy}, pickup 1 {c.pickup_xy} ({dist(c.pickup_xy):.3f} m)"
    )
    print("bands (Hz):", " ".join(f"{f:>5d}" for f in BANDS_HZ))
    for xy in cands:
        second = bands(plt.impulse_response(dataclasses.replace(spec, pickup_xy=xy), FS))
        n = min(len(first[0]), len(second[0]))
        level, corr = [], []
        for u, v in zip(first, second, strict=True):
            u, v = u[:n], v[:n]
            level.append(10 * math.log10(float(np.dot(v, v) / np.dot(u, u))))
            corr.append(float(np.dot(u, v) / math.sqrt(float(np.dot(u, u) * np.dot(v, v)))))
        print(
            f"({xy[0]:.2f}, {xy[1]:.2f}) {dist(xy):.3f} m from the drive\n"
            f"   level re pickup 1 (dB) " + " ".join(f"{x:+5.1f}" for x in level) + "\n"
            "   correlation            " + " ".join(f"{r:+5.2f}" for r in corr)
        )


if __name__ == "__main__":
    main()

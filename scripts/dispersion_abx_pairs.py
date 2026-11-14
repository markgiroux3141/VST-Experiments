"""AM5 step 4's realistic pairs: y1 = S(AP(x)) against y2 = AP(S(x)), LUFS-matched, for the
cases a 1960s record would have had (the tape at its aligned level, the 670 at about 6 dB of
gain reduction), beside the largest case dispersion_study.py writes. From the render cache.

  uv run --extra fast --extra listen python scripts/dispersion_abx_pairs.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import dispersion_study as ds  # noqa: E402

from varimu.listen.matching import match_loudness  # noqa: E402
from varimu.magic import dispersion as dp  # noqa: E402
from varimu.magic import render  # noqa: E402
from varimu.sim.io import write_audio  # noqa: E402

CASES = (("tape_0dB", "voice"), ("tape_0dB", "drums"), ("670_in+6dB", "voice"))


def main() -> int:
    fs = render.sample_rate()
    fir = np.load(ds.OUT / "chain_allpass_fir.npy")
    for s, p in CASES:
        x = ds.program(p, 10.0, fs)
        f = ds.sat_fn(s)
        y1 = f(dp.apply_fir(fir, x))[: len(x)]
        y2 = dp.apply_fir(fir, f(x))[: len(x)]
        (m1, m2), _ = match_loudness([y1, y2], fs)
        write_audio(ds.OUT / "abx" / f"{s}_{p}_historical_S_of_AP.wav", m1, fs)
        write_audio(ds.OUT / "abx" / f"{s}_{p}_AP_of_S.wav", m2, fs)
        print(f"{s} {p}: written", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

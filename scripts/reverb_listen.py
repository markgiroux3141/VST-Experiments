"""One clip through every reverb, for listening (docs/REVERB_PLAN.md) ->
reports/reverb/listen/.

    uv run --extra fast --extra listen python scripts/reverb_listen.py [--clip "Dry Guitar.wav"]
        [--start 0 --seconds 12] [--quality production] [--wet-lu -12]

The reverbs: the EMT 140 plate (plate_reverb), the EMT 240 gold foil (foil_reverb), the
Fender 6G15 spring (fender_6g15, MIXER fully wet: its wet path only) at their default
panels. The clip goes in at -18 dBFS rms, followed by 4 s of silence for the tails. Per
reverb: `<clip>_<reverb>_wet.wav` (the return alone) and `<clip>_<reverb>_mix.wav` (the dry
plus the return at `--wet-lu` LU under the dry's loudness, the same share for each), and
every file matched to -23 LUFS integrated (CLAUDE.md: loudness lies), so the reverbs differ
only in character. Plus the dry clip at the same loudness.
"""

from __future__ import annotations

import argparse
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.listen.matching import integrated_lufs
from varimu.sim import fast
from varimu.sim.io import TransientSettings, full_scale, load_audio, write_audio

OUT = REPO_ROOT / "reports" / "reverb" / "listen"
REVERBS = {
    "plate140": ("plate_reverb", {}),
    "foil240": ("foil_reverb", {}),
    "spring6g15": ("fender_6g15", {"mixer": 1.0}),
}
TARGET_LUFS = -23.0


def to_lufs(x: np.ndarray, fs: int, lufs: float) -> np.ndarray:
    return x * 10 ** ((lufs - integrated_lufs(x, fs)) / 20)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clip", default="Dry Guitar.wav")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--quality", default="production")
    ap.add_argument("--wet-lu", type=float, default=-12.0)
    a = ap.parse_args()
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=a.quality)
    fs = st.sample_rate
    x = load_audio(REPO_ROOT / "data" / "clips" / a.clip, fs)
    x = x[int(a.start * fs) : int((a.start + a.seconds) * fs)]
    x = x * 10 ** (-18 / 20) / (np.std(x) + 1e-30)
    xp = np.concatenate([x, np.zeros(int(4.0 * fs))])
    stem = Path(a.clip).stem.replace(" ", "_")

    def one(item: tuple[str, tuple[str, dict]]) -> tuple[str, np.ndarray]:
        name, (circuit, vals) = item
        c = spec.load_circuit(spec.circuit_path(circuit))
        v_in, v_out = full_scale(st, c)
        r = fast.run_transient(builder.build(c, vals).ir, xp * v_in, settings=st)
        return name, np.asarray(r.vectors["v(out)"]) / v_out

    t0 = time.time()
    with ThreadPoolExecutor(len(REVERBS)) as ex:
        wets = dict(ex.map(one, REVERBS.items()))
    dry_lufs = integrated_lufs(xp, fs)
    write_audio(OUT / f"{stem}_dry.wav", to_lufs(xp, fs, TARGET_LUFS), fs)
    for name, wet in wets.items():
        wet = wet - np.mean(wet[-int(0.5 * fs) :])  # the output's settled DC, if any
        write_audio(OUT / f"{stem}_{name}_wet.wav", to_lufs(wet, fs, TARGET_LUFS), fs)
        mix = xp + to_lufs(wet, fs, dry_lufs + a.wet_lu)
        write_audio(OUT / f"{stem}_{name}_mix.wav", to_lufs(mix, fs, TARGET_LUFS), fs)
        print(f"  {name}: wet {20 * math.log10(np.std(wet) + 1e-30):.1f} dBFS rms raw")
    print(f"{len(wets)} reverbs, {len(xp) / fs:.0f} s each, in {time.time() - t0:.0f} s -> {OUT}")


if __name__ == "__main__":
    main()

"""Print audio through the aligned Ampex 351 (docs/TAPE_PLAN.md, TM5): the whole machine,
config/circuits/ampex_351.yaml at production (its literal bias, Scotch 111, the record and
reproduce electronics, 6T3 into 600 ohm), aligned by varimu.measure.tape_align
(scripts/align_351.py; cached).

    uv run --extra fast --extra listen python scripts/print_351.py \
        --clip drums_setmefree.wav --seconds 10 --drive-db 0 6 12

Levels as the first prints' (scripts/tape_print.py): -18 dBFS rms is 0 VU in (-10 dBm
bridging) and out (+8 dBm); `--drive-db` feeds the machine that much hotter at the aligned
RECORD LEVEL. The head distance's delay (133 ms at 15 ips) is taken out. Writes
reports/tape/audio/<clip>_351_15ips_drive<+N>dB.wav and the dry excerpt matched to each
print's loudness (<clip>_dry_for_351_drive<+N>dB.wav: loudness lies); `--tag` is appended
to both names. The drives run at
once (each keeps two threads busy). With the circuit's noise (its tubes' and resistors'
hiss, the mains wander, the tape's grain; `--no-noise`: none).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta
from varimu.sim import fast
from varimu.sim.io import TransientSettings, load_audio

OUT = REPO_ROOT / "reports" / "tape"
TAIL_S = 0.3


def _write(path: Path, x: np.ndarray, fs: int) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, x.astype(np.float32), fs, subtype="FLOAT")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clip", default="drums_setmefree.wav")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--drive-db", type=float, nargs="+", default=[0.0])
    ap.add_argument("--no-noise", action="store_true", help="no hiss, hum or grain")
    ap.add_argument("--tag", default="", help="appended to the file names (e.g. _nonoise)")
    a = ap.parse_args()

    al = ta.aligned()
    print(f"aligned: {json.dumps(al.overrides)}", flush=True)
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st.sample_rate
    c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
    v_in, v_out = c.full_scale
    p = spec.resolve(c, al.overrides)
    delay = int(round(p["head_distance_m"] / p["speed_m_s"] * fs))
    ir = builder.build(c, al.overrides, cores="ja", noise=False if a.no_noise else None).ir

    x = load_audio(REPO_ROOT / "data" / "clips" / a.clip, fs)
    x = x[int(a.start * fs) : int((a.start + a.seconds) * fs)]
    xp = np.concatenate([x, np.zeros(delay + int(TAIL_S * fs))])
    stem = Path(a.clip).stem
    done = dict.fromkeys(a.drive_db, 0.0)
    lock = threading.Lock()
    t0 = time.time()

    def show() -> None:
        with lock:
            s = "  ".join(f"{d:+.0f} dB {100 * f:5.1f}%" for d, f in done.items())
            print(f"\r  {s}  ({time.time() - t0:.0f} s)", end="", flush=True)

    def one(drive: float) -> np.ndarray:
        def progress(f: float, d=drive) -> None:
            done[d] = f
            show()

        u = xp * v_in * 10 ** (drive / 20)
        r = fast.run_transient(ir, u, settings=st, progress=progress)
        return r.vectors["v(out)"][delay : delay + len(x) + int(TAIL_S * fs)] / v_out

    with ThreadPoolExecutor(len(a.drive_db)) as ex:
        ys = list(ex.map(one, a.drive_db))
    el = time.time() - t0
    print()
    import pyloudnorm

    meter = pyloudnorm.Meter(fs)
    for drive, y in zip(a.drive_db, ys, strict=True):
        name = f"{stem}_351_15ips_drive{drive:+.0f}dB{a.tag}"
        _write(OUT / "audio" / f"{name}.wav", y, fs)
        dry = x * 10 ** ((meter.integrated_loudness(y) - meter.integrated_loudness(x)) / 20)
        _write(OUT / "audio" / f"{stem}_dry_for_351_drive{drive:+.0f}dB{a.tag}.wav", dry, fs)
        print(
            f"  {name}: peak {20 * math.log10(np.abs(y).max() + 1e-30):.1f} dBFS, "
            f"{meter.integrated_loudness(y):.1f} LUFS"
        )
    print(
        f"{len(a.drive_db)} prints of {len(x) / fs:.1f} s in {el:.0f} s "
        f"({el / (len(x) / fs + st.settle_s):.1f}x real time each, the 1 s settle counted)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Print the Ampex 351 slap echo (docs/DELAY_PLAN.md, "The 351 echo"): the literal machine
at production (config/circuits/ampex_351_echo.yaml: its oscillator, Scotch 111, the factory
alignment, the console's SEND and REPEAT), and optionally its live tier for comparison.

    uv run --extra fast --extra listen python scripts/print_351_echo.py \
        --clip drums_setmefree.wav --seconds 4 --repeat 0 0.35 0.6 [--live]

-18 dBFS rms in is the console's 0 VU (-10 dBm). Each REPEAT setting renders at once (two
threads each), the input followed by `--tail` seconds of silence so the repeats ring out.
Writes reports/delay/audio/<clip>_351echo_rep<R>[_live].wav: the slap (wet only, the line
output at -18 dBFS rms = +8 dBm) and <clip>_351echo_rep<R>_mix.wav, the dry plus the slap at
the app's default share (a chain end's 30% wet). `--live` renders the events build (the
reduced tape, the oscillator out, the record side at the audio rate) at the draft quality,
the way the app plays it. With the circuit's noise unless `--no-noise`. `--ips 7.5` runs the
tape at 7-1/2 ips (the speed switch with EQUAL SWITCH at LOW: a 267 ms slap; files tagged
`_7.5ips`). `--bias-pf C` sets BIAS ADJUST (5C13, 15-130 pF; aligned ~31): under-biased gritty
and compressed, over-biased dark (files tagged `_biasC`).
"""

from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.sim import fast
from varimu.sim.io import TransientSettings, load_audio

OUT = REPO_ROOT / "reports" / "delay" / "audio"
CIRCUIT = "ampex_351_echo"
PINGPONG = "ampex_351_2_echo"
WET = 0.3


def _write(path: Path, x: np.ndarray, fs: int) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, x.astype(np.float32), fs, subtype="FLOAT")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clip", default="drums_setmefree.wav")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--tail", type=float, default=2.0)
    ap.add_argument("--repeat", type=float, nargs="+", default=[0.35])
    ap.add_argument("--send", type=float, default=1.0)
    ap.add_argument("--drive", type=float, help="DRIVE (the line amp; default the file's)")
    ap.add_argument("--live", action="store_true", help="the live tier at the draft quality")
    ap.add_argument("--no-noise", action="store_true")
    ap.add_argument("--pingpong", action="store_true", help="the 351-2, in stereo")
    ap.add_argument("--ips", type=float, choices=[7.5, 15.0], default=15.0)
    ap.add_argument("--bias-pf", type=float, help="BIAS ADJUST in pF (default the alignment's)")
    a = ap.parse_args()
    speed = {} if a.ips == 15.0 else {"speed": 0, "equalization": 0}

    quality = "draft" if a.live else "production"
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    fs = st.sample_rate
    c = spec.load_circuit(spec.circuit_path(PINGPONG if a.pingpong else CIRCUIT))
    v_in, v_out = c.full_scale
    x = load_audio(REPO_ROOT / "data" / "clips" / a.clip, fs)
    x = x[int(a.start * fs) : int((a.start + a.seconds) * fs)]
    xp = np.concatenate([x, np.zeros(int(a.tail * fs))])
    stem = Path(a.clip).stem
    tag = ("" if a.drive is None else f"_drive{a.drive:g}") + ("_live" if a.live else "")
    tag = ("" if a.bias_pf is None else f"_bias{a.bias_pf:g}") + tag
    tag = ("" if a.ips == 15.0 else f"_{a.ips:g}ips") + tag
    if a.bias_pf is not None:
        speed = {**speed, "bias_adjust_f": a.bias_pf * 1e-12}
    done = dict.fromkeys(a.repeat, 0.0)
    lock = threading.Lock()
    t0 = time.time()

    def show() -> None:
        with lock:
            s = "  ".join(f"rep {r:g} {100 * f:5.1f}%" for r, f in done.items())
            print(f"\r  {s}  ({time.time() - t0:.0f} s)", end="", flush=True)

    def one(rep: float) -> np.ndarray:
        def progress(f: float, r=rep) -> None:
            done[r] = f
            show()

        ir = builder.build(
            c,
            {
                "repeat": rep,
                "send": a.send,
                **speed,
                **({} if a.drive is None else {"drive": a.drive}),
            },
            cores="linear" if a.live else "ja",
            noise=False if a.no_noise else None,
            events=a.live,
        ).ir
        r = fast.run_transient(ir, xp * v_in, settings=st, progress=progress)
        if a.pingpong:
            return np.stack([r.vectors["v(out)"], r.vectors["v(out_r)"]], axis=1) / v_out
        return r.vectors["v(out)"] / v_out

    with ThreadPoolExecutor(len(a.repeat)) as ex:
        ys = list(ex.map(one, a.repeat))
    el = time.time() - t0
    print()
    for rep, y in zip(a.repeat, ys, strict=True):
        name = f"{stem}_{'351pingpong' if a.pingpong else '351echo'}_rep{rep:g}{tag}"
        _write(OUT / f"{name}.wav", y, fs)
        dry = xp[:, None] if y.ndim == 2 else xp
        _write(OUT / f"{name}_mix.wav", (1 - WET) * dry + WET * y, fs)
        print(f"  {name}: peak {20 * math.log10(np.abs(y).max() + 1e-30):.1f} dBFS")
    print(
        f"{len(a.repeat)} prints of {len(xp) / fs:.1f} s in {el:.0f} s "
        f"({el / (len(xp) / fs + st.settle_s):.1f}x real time each, the 1 s settle counted)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

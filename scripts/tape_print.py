"""Print audio to the simulated tape (docs/TAPE_PLAN.md, "The first print"): Scotch 111 on
an Ampex 351's tape path with idealized NAB electronics (varimu.devices.tape_machine).

    uv run --extra fast --extra listen python scripts/tape_print.py --clip drums_setmefree.wav \
        --seconds 10 --drive-db 0 6 12 [--speed 15] [--tape SCOTCH111@3] [--no-noise]

Writes reports/tape/audio/<clip>_<speed>ips_drive<+N>dB.wav and the dry excerpt matched
to each print's loudness (<clip>_dry_for_drive<+N>dB.wav: loudness lies), plus the
alignment's report (reports/tape/alignment_<speed>ips.json). `--tone` prints test tones
instead (levels and THD to the console).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT
from varimu.devices import library
from varimu.devices.tape_machine import TapeMachineSpec, aligned, print_audio

FS = 96_000
OUT = REPO_ROOT / "reports" / "tape"


def _write(path: Path, x: np.ndarray) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, x.astype(np.float32), FS, subtype="FLOAT")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clip", default="drums_setmefree.wav")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--drive-db", type=float, nargs="+", default=[0.0])
    ap.add_argument("--speed", type=float, default=15.0, help="ips: 15 or 7.5")
    ap.add_argument("--tape", default="SCOTCH111@3")
    ap.add_argument(
        "--noise-seed", type=int, default=1, help="the coating's grain (if the tape has one)"
    )
    ap.add_argument("--no-noise", action="store_true", help="no grain")
    ap.add_argument("--tone", action="store_true")
    ap.add_argument(
        "--demag-iterations",
        type=int,
        default=8,
        help="8: within -58 dB of converged (12); 4: -42 dB, ~1.5x faster",
    )
    a = ap.parse_args()

    tape = library.load_tape(a.tape)
    seed = None if a.no_noise or tape.noise is None else a.noise_seed
    spec = TapeMachineSpec().at_speed(a.speed * 0.0254)
    import dataclasses

    print_spec = dataclasses.replace(spec, demag_iterations=a.demag_iterations)
    t = time.time()
    al = aligned(spec, tape, REPO_ROOT / "cache" / "tape")
    print(f"aligned in {time.time() - t:.0f} s: {json.dumps(al.report, default=float)[:400]}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"alignment_{a.speed:g}ips.json").write_text(
        json.dumps(
            {"tape": a.tape, "spec": spec.__dict__, "alignment": al.__dict__},
            indent=1,
            default=float,
        )
    )
    if a.tone:
        for f_hz in (100.0, 1000.0, 10000.0):
            for drive in a.drive_db:
                n = int(0.3 * FS)
                x = MINUS_18 * np.sin(2 * math.pi * f_hz * np.arange(n) / FS)
                y = print_audio(x, FS, spec, tape, al, drive_db=drive)
                seg = y[n // 3 :]
                k = np.arange(len(seg))
                amps = [
                    abs(2 * np.mean(seg * np.exp(-2j * math.pi * h * f_hz * k / FS)))
                    for h in (1, 2, 3)
                ]
                rms_db = 20 * math.log10(amps[0] / math.sqrt(2) + 1e-30)
                thd = math.hypot(amps[1], amps[2]) / amps[0] * 100
                print(
                    f"{f_hz:7.0f} Hz drive {drive:+5.1f} dB: out {rms_db:6.2f} dBFS rms "
                    f"(in {-18 + drive:+.1f}), THD {thd:.3f} %"
                )
        return 0

    from varimu.sim.io import load_audio

    x = load_audio(REPO_ROOT / "data" / "clips" / a.clip, FS)
    x = x[int(a.start * FS) : int((a.start + a.seconds) * FS)]
    stem = Path(a.clip).stem
    import pyloudnorm

    meter = pyloudnorm.Meter(FS)
    for drive in a.drive_db:
        t = time.time()
        y = print_audio(
            x,
            FS,
            print_spec,
            tape,
            al,
            drive_db=drive,
            noise_seed=seed,
            progress=lambda f, d=drive: print(
                f"\r  drive {d:+.0f} dB: {100 * f:5.1f} %", end="", flush=True
            ),
        )
        el = time.time() - t
        name = f"{stem}_{a.speed:g}ips_drive{drive:+.0f}dB"
        _write(OUT / "audio" / f"{name}.wav", y)
        # The dry excerpt for A/B, as loud as the print (loudness lies). Not shifted: the
        # print's impulse response peaks within 3 samples (cross-correlating music instead
        # finds the NAB networks' few-ms bass delay, or a beat period).
        dry = x * 10 ** ((meter.integrated_loudness(y) - meter.integrated_loudness(x)) / 20)
        _write(OUT / "audio" / f"{stem}_dry_for_drive{drive:+.0f}dB.wav", dry)
        print(
            f"\r  {name}: {el:.0f} s for {len(x) / FS:.1f} s "
            f"({el * FS / len(x):.1f}x real time), "
            f"peak {20 * math.log10(np.abs(y).max() + 1e-30):.1f} dBFS"
        )
    return 0


MINUS_18 = 10 ** (-18 / 20) * math.sqrt(2.0)

if __name__ == "__main__":
    sys.exit(main())

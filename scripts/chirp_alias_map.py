"""The literal bias's cell alias over the oscillator's frequency (docs/PERIOD_GEAR_BACKLOG.md
PG1, the 300-4's 5.4 kHz chirp; docs/TAPE_PLAN.md "Gaps"): the tape medium alone
(circuitsim's TapeStream, the deck's Scotch 202 medium, literal bias at 10 substeps: the
alias doesn't depend on them), fed an ideal head field (a sine bias at f_b plus a 55.3 Hz
tone at 0.6 mA rms on 8.0e6 A/m per A, the bias at the 351's aligned 2.94 mA rms; the
transport off, so its flutter's sidebands don't mask the alias), for each
f_b and three cell lengths:

- `now`: the circuits' cells, 7.62 per wavelength of the NOMINAL 100 kHz (0.5 um at 15 ips);
- `matched`: 7.62 per wavelength of the actual f_b (the cell beat at 0.38 f_b);
- `fine`: 0.25 um.

The recorded bias pattern (two field peaks per bias cycle, ~2 um apart on tape) point-sampled
by the cells aliases to |8 f_b - v / ds| (and weaker higher orders). Per run: the strongest
line 200 Hz - 20 kHz that isn't a harmonic of the tone, dB re the tone, and the predicted
first-order beat. -> reports/tape/chirp/alias_map.{json,png}.

    uv run --extra fast --extra listen python scripts/chirp_alias_map.py [--fb-khz 88 104 2]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from varimu.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import chirp_medium  # noqa: E402

FS = 192_000.0
OUT = REPO_ROOT / "reports" / "tape" / "chirp"
TONE_HZ = 55.3
SECONDS = 0.5
BIAS_MA, AUDIO_MA, HEAD_A_M_PER_A = 2.94, 0.6, 8.0e6
M = 10


def worst_line(y: np.ndarray) -> tuple[float, float]:
    w = np.blackman(len(y))
    sp = np.abs(np.fft.rfft(y * w)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / FS)
    ref = sp[np.abs(f - TONE_HZ) < 4].sum()
    harm = np.abs(f / TONE_HZ - np.round(f / TONE_HZ)) * TONE_HZ < 15
    m = (f > 200) & (f < 20_000) & ~harm
    # a line's power: the 7 bins around the strongest bin
    i = np.where(m)[0][np.argmax(sp[m])]
    return float(f[i]), float(10 * math.log10(sp[i - 3 : i + 4].sum() / ref))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fb-khz", type=float, nargs=3, default=[88.0, 104.0, 2.0])
    a = ap.parse_args()
    import circuitsim

    med = chirp_medium.medium("deck")
    lo, hi, st = a.fb_khz
    fbs = [1e3 * x for x in np.arange(lo, hi + st / 2, st)]
    jobs = []
    for fb in fbs:
        for kind in ("now", "matched", "fine"):
            ds = {"now": med.speed_m_s / (100e3 * 7.62), "matched": med.speed_m_s / (fb * 7.62), "fine": 0.25e-6}[kind]
            jobs.append((fb, kind, dataclasses.replace(
                med, bias_substeps=M, ds_m=ds, f_bias_hz=fb, flutter=(), flutter_noise=())))

    def run(job):
        fb, kind, md = job
        params = json.dumps(dataclasses.asdict(md))
        n = int((SECONDS + md.head_distance_m / md.speed_m_s + 0.05) * FS)
        t = (np.arange(n * M) + 1 - 2 * M) / (M * FS)
        env = np.clip(t / 0.02, 0.0, 1.0)
        hb = BIAS_MA * 1e-3 * math.sqrt(2) * HEAD_A_M_PER_A
        ha = AUDIO_MA * 1e-3 * math.sqrt(2) * HEAD_A_M_PER_A
        h = env * (ha * np.sin(2 * math.pi * TONE_HZ * t) + hb * np.sin(2 * math.pi * fb * t + 0.3))
        y = np.asarray(circuitsim.tape_stream_run(params, FS, h, chunk=20 * M * 48))
        y = y[int(md.head_distance_m / md.speed_m_s * FS) + int(0.05 * FS) :]
        f, db = worst_line(y)
        cell = md.speed_m_s / md.ds_m
        beat = abs(8 * fb - cell)
        print(f"  f_b {fb / 1e3:6.1f} kHz {kind:8s} ds {md.ds_m * 1e6:.3f} um: worst {f:7.0f} Hz "
              f"{db:6.1f} dB (first-order beat {beat / 1e3:.1f} kHz)", flush=True)
        return {"f_bias_hz": fb, "kind": kind, "ds_m": md.ds_m, "worst_hz": f, "worst_db": db,
                "beat_hz": beat}

    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(run, jobs))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "alias_map.json").write_text(json.dumps({"rows": rows}, indent=1))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    for kind in ("now", "matched", "fine"):
        r = [x for x in rows if x["kind"] == kind]
        ax[0].plot([x["f_bias_hz"] / 1e3 for x in r], [x["worst_db"] for x in r], "o-", label=kind)
        ax[1].plot([x["f_bias_hz"] / 1e3 for x in r], [x["worst_hz"] / 1e3 for x in r], "o", label=kind)
    ax[0].axvline(92.99, color="k", lw=0.5)
    ax[0].axvline(95.86, color="r", lw=0.5)
    ax[0].set_xlabel("oscillator (kHz); black the 351, red the 300-4")
    ax[0].set_ylabel("worst non-harmonic line < 20 kHz (dB re tone)")
    ax[1].set_xlabel("oscillator (kHz)")
    ax[1].set_ylabel("its frequency (kHz)")
    for x in ax:
        x.legend()
        x.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "alias_map.png", dpi=110)
    return 0


if __name__ == "__main__":
    sys.exit(main())

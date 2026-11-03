"""Listen to the prototype 2D21 sawtooth: notes rendered from the scipy Radau solution.

The capacitor's voltage is read from the solver's dense output at 16 x 96 kHz and
decimated to 96 kHz with scipy's resample_poly (its anti-alias filter), so the files carry
the tube's reset as the physics shapes it, band-limited, without the audio grid's aliasing
(the point of HYBRID_PHYSICS_PLAN.md H2). Each note: B+ 300 V, the charging resistor sets
the pitch, the grid bias the strike (amplitude); AC-coupled (10 Hz), one common gain for all
files (their levels compare), 10 ms fades.

    uv run python scripts/prototypes/thyratron/thy_listen.py   # -> reports/hybrid/audio/
"""

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.integrate import solve_ivp
from scipy.signal import butter, resample_poly, sosfilt

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
from thy_proto import P0, ie, ig, rate  # noqa: E402

FS = 96000
OS = 16
SECONDS = 2.0
SKIP_S = 0.05
B, C, RA, RG = 300.0, 10e-9, 270.0, 47e3
CAK, CGK = 1.6e-12, 2.4e-12
# (file, charging resistor, grid bias)
NOTES = [
    ("saw_r1m0_bias-2.0", 1.0e6, -2.0),
    ("saw_r470k_bias-2.0", 470e3, -2.0),
    ("saw_r220k_bias-2.0", 220e3, -2.0),
    ("saw_r100k_bias-2.0", 100e3, -2.0),
    ("saw_r47k_bias-2.0", 47e3, -2.0),
    ("saw_r470k_bias-1.5", 470e3, -1.5),
    ("saw_r470k_bias-2.5", 470e3, -2.5),
]


def params():
    import json

    p = dict(P0)
    p.update(json.loads((HERE / "fit_2026-11-02.json").read_text()))
    return p


def render(note):
    name, r, vbias = note
    p = params()

    def f(t, s):
        vc, va, vg, w = s
        x = np.exp(min(w, 40.0))
        i_a = ie(p, va, vg, 0.0, x)
        i_g = ig(p, va, vg, x)
        return [
            ((B - vc) / r - (vc - va) / RA) / C,
            ((vc - va) / RA - i_a) / CAK,
            ((vbias - vg) / RG - i_g) / CGK,
            rate(p, va, vg, 0.0, x) / x,
        ]

    t_end = SECONDS + SKIP_S
    sol = solve_ivp(
        f,
        (0, t_end),
        [10.0, 10.0, vbias, np.log(1e-10)],
        method="Radau",
        rtol=1e-7,
        atol=1e-6,
        max_step=2e-5,
        dense_output=True,
    )
    t = np.arange(int(t_end * FS * OS)) / (FS * OS)
    vc = sol.sol(t)[0]
    y = resample_poly(vc, 1, OS)[int(SKIP_S * FS) :]
    # periods from the resets (falls of more than 20 V in a sample)
    k = np.where(np.diff(y) < -20.0)[0]
    f0 = FS / np.mean(np.diff(k)) if len(k) > 2 else float("nan")
    return name, y, f0, float(vc.max()), float(vc[int(SKIP_S * FS * OS) :].min()), len(sol.t)


def main():
    out = REPO / "reports/hybrid/audio"
    out.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=len(NOTES)) as ex:
        res = list(ex.map(render, NOTES))
    sos = butter(1, 10.0, "highpass", fs=FS, output="sos")
    ys = [sosfilt(sos, y - y[0]) for _, y, *_ in res]
    gain = 0.5 / max(np.max(np.abs(y)) for y in ys)
    fade = np.linspace(0.0, 1.0, int(0.01 * FS))
    for (name, _, f0, hi, lo, steps), y in zip(res, ys, strict=True):
        y = y * gain
        y[: len(fade)] *= fade
        y[-len(fade) :] *= fade[::-1]
        sf.write(out / f"{name}.wav", y.astype(np.float32), FS, subtype="FLOAT")
        print(f"{name}: {f0:.1f} Hz, swing {lo:.1f} -> {hi:.1f} V, {steps} solver steps")


if __name__ == "__main__":
    main()

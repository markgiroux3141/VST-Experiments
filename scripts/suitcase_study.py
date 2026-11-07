"""The Rhodes Suitcase's preamp and vibrato against the reference recording (docs/RHODES_PLAN.md,
"The Suitcase"): config/circuits/rhodes_suitcase.yaml driven through ACCESSORY IN by a test
tone, its two outputs' balance (L over R in dB, short-time rms) measured the same way as the
reference recording's ("real instrument samples/Rhodes Mk I 1978 - with Suitcase preamp by
Tines and reeds.mp3", untracked).

    uv run --extra fast python scripts/suitcase_study.py [--quality draft] [--seconds 4]
        [--set KEY=VALUE ...] [--calibrate] [--candidate KEY=VALUE ... [--candidate ...]]

The balance b(t) is fitted with a Fourier series at its own fundamental (found by a fine
search around the spectrum's peak): the rate, the peak to peak, the harmonics re the
fundamental; and folded over one period (the median per phase bin), compared with the
reference's folded balance as an rms difference at the best phase and either sign (the
shape error). `--calibrate` searches SPEED for the reference's rate, then INTENSITY for the
least shape error. Each `--candidate` (settings over `--set`, e.g. opto_model=VTL5C2@1) is
calibrated and compared. Writes reports/rhodes/suitcase/vibrato.json and vibrato.png.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import optimize, signal

from varimu.circuit import builder, spec
from varimu.sim import fast
from varimu.sim.io import TransientSettings

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "rhodes" / "suitcase"
REFERENCE = (
    ROOT
    / "real instrument samples"
    / "Rhodes Mk I 1978 - with Suitcase preamp by Tines and reeds.mp3"
)
CIRCUIT = "rhodes_suitcase"
WINDOW_S = 0.02  # the envelope's rms window
HOP_S = 0.005
FOLD_BINS = 40


def envelope_db(y: np.ndarray, fs: float) -> np.ndarray:
    """Short-time rms in dB (WINDOW_S windows every HOP_S) of y high-passed at 80 Hz."""
    sos = signal.butter(4, 80.0, "highpass", fs=fs, output="sos")
    y = signal.sosfiltfilt(sos, y)
    w, h = int(WINDOW_S * fs), int(HOP_S * fs)
    n = (len(y) - w) // h
    idx = np.arange(w)[None, :] + h * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(y[idx] ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-12))


def fit_balance(b: np.ndarray, harmonics: int = 5) -> dict:
    """b sampled every HOP_S: its fundamental (the spectrum's peak over 1-10 Hz, refined by
    least squares), and the Fourier series' amplitudes (dB of balance) at it."""
    fs = 1.0 / HOP_S
    t = np.arange(len(b)) / fs
    bb = b - b.mean()
    n = 1 << 18
    spec_ = np.abs(np.fft.rfft(bb * np.hanning(len(bb)), n))
    f = np.fft.rfftfreq(n, 1 / fs)
    band = (f > 1.0) & (f < 10.0)
    f0 = f[band][np.argmax(spec_[band])]

    def design(f1):
        cols = [np.ones_like(t), t]  # a mean and a drift (the program's own L / R balance)
        for k in range(1, harmonics + 1):
            cols += [np.cos(2 * np.pi * k * f1 * t), np.sin(2 * np.pi * k * f1 * t)]
        return np.stack(cols, axis=1)

    def resid(f1):
        a = design(f1)
        c, *_ = np.linalg.lstsq(a, b, rcond=None)
        return np.sum((b - a @ c) ** 2)

    f0 = optimize.minimize_scalar(resid, bounds=(f0 * 0.98, f0 * 1.02), method="bounded").x
    a = design(f0)
    c, *_ = np.linalg.lstsq(a, b, rcond=None)
    amps = [float(np.hypot(c[2 + 2 * k], c[3 + 2 * k])) for k in range(harmonics)]
    # each harmonic's phase against k times the fundamental's (cosine form): for the 3rd,
    # 180 deg is a flattened (square-like) wave, 0 a peaked (triangle-like) one
    ph = [np.arctan2(-c[3 + 2 * k], c[2 + 2 * k]) for k in range(harmonics)]
    rel = [float(np.degrees((ph[k] - (k + 1) * ph[0] + np.pi) % (2 * np.pi) - np.pi))
           for k in range(1, harmonics)]  # fmt: skip
    fitted = a[:, 2:] @ c[2:]
    resid_rms = float(np.sqrt(np.mean((b - a @ c) ** 2)))
    return {
        "rate_hz": float(f0),
        "fundamental_db": amps[0],  # the balance's swing: +-amps[0] dB
        "peak_to_peak_db": float(fitted.max() - fitted.min()),
        "harmonics_re_fundamental": [h / amps[0] for h in amps[1:]],
        "harmonics_phase_deg": rel,
        "residual_rms_db": resid_rms,
    }


def fold(b: np.ndarray, rate_hz: float) -> np.ndarray:
    """b (every HOP_S, its linear drift removed: the program's own balance) folded over one
    period of rate_hz: the median per phase bin, its mean removed."""
    n = np.arange(len(b))
    b = b - np.polyval(np.polyfit(n, b, 1), n)
    idx = ((n * HOP_S * rate_hz) % 1.0 * FOLD_BINS).astype(int)
    m = np.array([np.median(b[idx == i]) for i in range(FOLD_BINS)])
    return m - m.mean()


def shape_error(model: np.ndarray, ref: np.ndarray) -> tuple[float, np.ndarray]:
    """The rms difference (dB) of two folded balances at the best circular shift, either sign
    (which output is the reference's left isn't known); and the model aligned so."""
    best = None
    for sign in (1.0, -1.0):
        for s in range(len(model)):
            m = sign * np.roll(model, s)
            e = float(np.sqrt(np.mean((m - ref) ** 2)))
            if best is None or e < best[0]:
                best = (e, m)
    return best


def analyse(left: np.ndarray, right: np.ndarray, fs: float) -> dict:
    el, er = envelope_db(left, fs), envelope_db(right, fs)
    b = el - er
    out = fit_balance(b)
    out["folded_db"] = [round(float(x), 3) for x in fold(b, out["rate_hz"])]
    mid = 0.5 * (el + er)
    out["correlation_lr"] = float(np.corrcoef(left, right)[0, 1])
    # each channel against the two's mean (in dB): +-half the balance when in antiphase
    for name, e in (("left", el), ("right", er)):
        out[f"{name}_vs_mean_fundamental_db"] = fit_balance(e - mid)["fundamental_db"]
    return out


def reference() -> dict:
    y, fs = sf.read(REFERENCE)
    return analyse(y[:, 0], y[:, 1], float(fs))


def render(overrides: dict, quality: str, seconds: float, tone_hz: float = 1000.0):
    c = spec.load_circuit(spec.circuit_path(CIRCUIT))
    s = TransientSettings.from_sim_settings(
        engine="circuitsim", quality=None if quality == "production" else quality
    )
    ir = builder.build(c, {"accessory_in": 1, **overrides}).ir
    fs = float(s.sample_rate)
    t = np.arange(int(seconds * fs)) / fs
    x = 0.05 * np.sin(2 * np.pi * tone_hz * t)
    v = fast.run_transient(ir, x, settings=s).vectors
    return v, fs


def measure(overrides: dict, quality: str, seconds: float, ref: dict | None = None) -> dict:
    v, fs = render(overrides, quality, seconds)
    skip = int(0.5 * fs)  # the oscillator's first half second
    out = analyse(v["v(out)"][skip:], v["v(out_r)"][skip:], fs)
    if ref is not None:
        e, m = shape_error(np.array(out["folded_db"]), np.array(ref["folded_db"]))
        out["shape_error_db"] = e
        out["folded_db"] = [round(float(x), 3) for x in m]  # aligned to the reference
    return out


def calibrate(ref: dict, quality: str, seconds: float, base: dict) -> dict:
    """SPEED for the reference's rate, then INTENSITY for the least shape error (the folded
    balance's rms difference: the depth and the shape together)."""
    over = dict(base)

    def rate_err(sp):
        r = measure({**over, "speed": sp}, quality, seconds)
        print(f"  speed {sp:.4f}: {r['rate_hz']:.3f} Hz", flush=True)
        return np.log(r["rate_hz"] / ref["rate_hz"])

    over["speed"] = optimize.brentq(rate_err, 0.4, 0.75, xtol=1e-3)

    def shape_err(it):
        r = measure({**over, "intensity": it}, quality, seconds, ref)
        print(
            f"  intensity {it:.4f}: shape error {r['shape_error_db']:.2f} dB, "
            f"+-{r['fundamental_db']:.2f} dB",
            flush=True,
        )
        return r["shape_error_db"]

    over["intensity"] = optimize.minimize_scalar(
        shape_err, bounds=(0.3, 1.0), method="bounded", options={"xatol": 3e-3}
    ).x
    return over


def plot(result: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    ph = np.arange(FOLD_BINS) / FOLD_BINS
    ax.plot(ph, result["reference"]["folded_db"], "k", lw=2, label="reference recording")
    for name, r in result["candidates"].items():
        ax.plot(ph, r["folded_db"], label=f"{name} ({r['shape_error_db']:.2f} dB rms)")
    ax.set_xlabel("phase (periods)")
    ax.set_ylabel("L / R balance (dB)")
    ax.set_title("The Suitcase vibrato, one period (folded, median per bin)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.savefig(path, dpi=110, bbox_inches="tight")


def number_or_text(v: str):
    try:
        return float(v)
    except ValueError:
        return v  # a component, e.g. opto_model=VTL5C2@1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--quality", default="draft", choices=["production", "draft", "draft-1x"])
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    ap.add_argument(
        "--candidate",
        nargs="*",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="a candidate's settings over --set (repeatable): each calibrated and compared",
    )
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    def parse(kvs):
        return {k: number_or_text(v) for k, v in (kv.split("=", 1) for kv in kvs)}

    base = parse(args.set)
    result: dict = {"reference": reference(), "quality": args.quality, "candidates": {}}
    ref = result["reference"]
    print(
        f"reference: {ref['rate_hz']:.3f} Hz, +-{ref['fundamental_db']:.2f} dB, harmonics "
        f"{np.round(ref['harmonics_re_fundamental'], 3)}",
        flush=True,
    )
    for cand in args.candidate or [[]]:
        over = {**base, **parse(cand)}
        name = " ".join(f"{k}={v}" for k, v in parse(cand).items()) or "as set"
        if args.calibrate:
            over = calibrate(ref, args.quality, args.seconds, over)
        r = {"settings": over, **measure(over, args.quality, args.seconds, ref)}
        result["candidates"][name] = r
        print(
            f"{name}: {r['rate_hz']:.3f} Hz, +-{r['fundamental_db']:.2f} dB, shape error "
            f"{r['shape_error_db']:.2f} dB, settings {over}",
            flush=True,
        )
    (OUT / "vibrato.json").write_text(json.dumps(result, indent=1))
    plot(result, OUT / "vibrato.png")
    print(f"-> {OUT / 'vibrato.json'}, vibrato.png")


if __name__ == "__main__":
    main()

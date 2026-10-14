"""Measure the vertical slice: static compression curve and Time Constant attack/release.

    uv run python scripts/slice_report.py [--tc 1 2 3 4] [--set key=value ...]

Renders come from the cache when `varimu render` already produced them with
the same settings, otherwise they run here. Plots and a JSON summary go to
reports/slice/.
"""

from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from varimu.config import REPO_ROOT, load_sim_settings  # noqa: E402
from varimu.measure import metrics, signals  # noqa: E402
from varimu.sim import runner  # noqa: E402

OUT = REPO_ROOT / "reports" / "slice"

# [MAN] p.4 (Fairchild 670 manual, 1959): attack, and release from 10 dB of limiting.
PUBLISHED = {
    1: (0.2e-3, 0.3),
    2: (0.2e-3, 0.8),
    3: (0.4e-3, 2.0),
    4: (0.4e-3, 5.0),
    5: (0.4e-3, 2.0),
    6: (0.2e-3, 0.3),
}


def _signal(name: str):
    st = load_sim_settings()
    spec = next(s for s in signals.default_library() if s.name == name)
    return signals.render(spec, sample_rate=st.sample_rate, seed=st.seed)


def compression_curve(overrides: dict) -> dict:
    sig = _signal("steps_1000hz")
    r = runner.render(runner.RenderJob(sig.samples, dict(overrides), "steps_1000hz"))
    pts = metrics.segment_gains(sig.samples, r.output, sig.meta["segments"])
    lin, gain = np.array(pts).T
    gr = gain[0] - gain
    cv = [
        float(np.median(r.vectors["v(cv)"][s["stop"] - (s["stop"] - s["start"]) // 4 : s["stop"]]))
        for s in sig.meta["segments"]
    ]

    fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
    ax[0].plot(lin, lin + gain, "o-", ms=3, label="670 slice")
    ax[0].plot(lin, lin + gain[0], "--", c="gray", label="no compression")
    ax[0].set(xlabel="input (dBFS peak)", ylabel="output (dBFS peak)", title="Static curve, 1 kHz")
    ax[0].legend()
    ax[1].plot(lin, gr, "o-", ms=3)
    ax[1].set(xlabel="input (dBFS peak)", ylabel="gain reduction (dB)", title="Gain reduction")
    ax[2].plot(lin, cv, "o-", ms=3)
    ax[2].set(xlabel="input (dBFS peak)", ylabel="V", title="Control voltage (6386 grid CT)")
    for a in ax:
        a.grid(alpha=0.3)
    fig.suptitle(f"steps_1000hz  overrides={overrides or 'defaults'}  render {r.key[:12]}")
    fig.tight_layout()
    path = OUT / "compression_curve.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return {
        "render": r.key[:12],
        "input_dbfs": lin.round(2).tolist(),
        "gain_db": gain.round(3).tolist(),
        "gain_reduction_db": gr.round(3).tolist(),
        "cv_v": np.round(cv, 3).tolist(),
        "gr_monotonic": bool(np.all(np.diff(gr) >= -0.05)),
        "plot": str(path.relative_to(REPO_ROOT)),
    }


def bursts(tcs, overrides: dict) -> dict:
    sig = _signal("burst_1000hz_0dbfs")
    jobs = [
        runner.RenderJob(sig.samples, {**overrides, "time_constant": tc}, f"burst_tc{tc}")
        for tc in tcs
    ]
    renders = runner.render_many(jobs)
    fs = renders[0].sample_rate
    a, b = sig.meta["burst_start"], sig.meta["burst_stop"]
    t = (np.arange(len(sig.samples)) - a) / fs
    fig, ax = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    gin = metrics.envelope_db(sig.samples, fs)
    rows = {}
    for tc, r in zip(tcs, renders, strict=True):
        cvt = metrics.cv_timing(r.vectors["v(cv)"], fs, a, b)
        gt = metrics.burst_timing(sig.samples, r.output, fs, a, b)
        pub_a, pub_r = PUBLISHED[tc]
        rows[tc] = {
            "render": r.key[:12],
            "cv_before_v": round(cvt.cv_before_v, 2),
            "cv_burst_v": round(cvt.cv_burst_v, 2),
            "gain_reduction_db": round(gt.gain_before_db - gt.gain_burst_db, 2),
            "attack_cv_63_ms": round(cvt.attack_s * 1e3, 3),
            "release_cv_63_s": round(cvt.release_63_s, 3),
            "release_cv_90_s": round(cvt.release_90_s, 3),
            "published_attack_ms": pub_a * 1e3,
            "published_release_s": pub_r,
        }
        ax[0].plot(t, metrics.envelope_db(r.output, fs) - gin, lw=1, label=f"TC{tc}")
        ax[1].plot(t, r.vectors["v(cv)"], lw=1, label=f"TC{tc}")
    ax[0].set(ylabel="gain (dB)", title="1 kHz burst, -40 -> 0 -> -40 dBFS", ylim=(-40, 15))
    ax[1].set(xlabel="time from burst start (s)", ylabel="control voltage (V)")
    for x in ax:
        x.axvline(0, c="gray", lw=0.5)
        x.axvline((b - a) / fs, c="gray", lw=0.5)
        x.grid(alpha=0.3)
        x.legend()
    fig.tight_layout()
    path = OUT / "bursts.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return {"plot": str(path.relative_to(REPO_ROOT)), "by_time_constant": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tc", nargs="+", type=int, default=[1, 2, 3, 4])
    ap.add_argument("--set", nargs="+", default=[], metavar="KEY=VALUE")
    ap.add_argument("--skip-curve", action="store_true")
    args = ap.parse_args()
    ov = runner.parse_overrides(args.set)
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"overrides": ov}
    if not args.skip_curve:
        summary["compression_curve"] = compression_curve(ov)
    summary["bursts"] = bursts(args.tc, ov)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1)[:4000])


if __name__ == "__main__":
    main()

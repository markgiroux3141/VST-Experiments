"""Plots of a unit report (varimu.measure.suite): one figure per section, so changes in
character can be reviewed visually (plan: "save measurement plots for candidates")."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from varimu.config import REPO_ROOT, load_sim_settings  # noqa: E402
from varimu.measure import metrics  # noqa: E402
from varimu.sim import setup  # noqa: E402


def _save(fig, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return str(path.relative_to(REPO_ROOT))


def plot_curves(report: dict, out_dir: Path) -> str:
    c = report["curves"]
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.8))
    for name, v in c.items():
        if not isinstance(v, dict) or "steps" not in v:
            continue
        x = [r["in_dbm"] for r in v["steps"]]
        ls = "-" if name.startswith("1000hz") else "--"
        ax[0].plot(x, [r["out_dbm"] for r in v["steps"]], ls, marker="o", ms=3, label=name)
        ax[1].plot(x, [r["gr_db"] for r in v["steps"]], ls, marker="o", ms=3, label=name)
        ax[2].plot(x, [r["cv_v"] for r in v["steps"]], ls, marker="o", ms=3, label=name)
    x3, y3 = setup.curve3()
    g = c["vs_curve3"]["gain_below_threshold_db"]
    ax[0].plot(x3, y3 + g, "k+", ms=8, label="manual curve 3 (+ unit gain)")
    ax[0].set(xlabel="in (dBm)", ylabel="out (dBm)", title="Static curves")
    ax[1].set(xlabel="in (dBm)", ylabel="gain reduction (dB)", title="Gain reduction")
    ax[2].set(xlabel="in (dBm)", ylabel="V", title="Control voltage")
    for a in ax:
        a.grid(alpha=0.3)
    ax[0].legend(fontsize=7)
    fig.suptitle(f"{report['name']}: static curves (factory panel unless named)")
    return _save(fig, out_dir / "curves.png")


def plot_distortion(report: dict, out_dir: Path) -> str:
    c = report["curves"]
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.8))
    for name, v in c.items():
        if not isinstance(v, dict) or "steps" not in v:
            continue
        out = [r["out_dbm"] for r in v["steps"]]
        ax[0].semilogy(
            out, [max(r["thd_pct"], 1e-4) for r in v["steps"]], marker="o", ms=3, label=name
        )
    fac = c["1000hz_factory"]["steps"]
    for k in (2, 3, 4, 5):
        ax[1].plot(
            [r["gr_db"] for r in fac], [r[f"h{k}_db"] for r in fac], marker="o", ms=3, label=f"H{k}"
        )
    for name in ("100hz_factory", "1000hz_factory", "6000hz_factory"):
        st = c[name]["steps"]
        ax[2].semilogy(
            [r["gr_db"] for r in st],
            [max(r["thd_pct"], 1e-4) for r in st],
            marker="o",
            ms=3,
            label=name,
        )
    ax[0].axhline(1.0, c="gray", lw=0.8)
    ax[0].axvline(18.0, c="gray", lw=0.8)
    ax[0].set(xlabel="out (dBm)", ylabel="THD (%)", title="THD vs output (spec: <1% to +18 dBm)")
    ax[1].set(
        xlabel="gain reduction (dB)", ylabel="dB re fundamental", title="Harmonics, 1 kHz, factory"
    )
    ax[2].set(
        xlabel="gain reduction (dB)", ylabel="THD (%)", title="THD vs gain reduction and frequency"
    )
    for a in ax:
        a.grid(alpha=0.3)
        a.legend(fontsize=7)
    return _save(fig, out_dir / "distortion.png")


def plot_timing(report: dict, renders: dict, unit: Any, out_dir: Path) -> str:
    from varimu.measure import suite

    fs = load_sim_settings().sample_rate
    fig, ax = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for key in report["timing"]:
        r = renders[key]
        tc = int(key[len("timing_tc")])
        x, meta = suite.burst_signal(unit, tc, key.endswith("_train"), fs)
        a = meta["burst_start"]
        t = (np.arange(len(x)) - a) / fs
        g = metrics.envelope_db(r.output, fs, 0.005) - metrics.envelope_db(x, fs, 0.005)
        ax[0].plot(t, g, lw=0.8, label=key)
        ax[1].plot(t, r.vectors["v(cv)"], lw=0.8, label=key)
    ax[0].set(ylabel="gain (dB)", title="Burst to 10 dB of limiting and release", ylim=(-25, 5))
    ax[1].set(xlabel="time from burst start (s)", ylabel="control voltage (V)")
    for a in ax:
        a.set_xscale("symlog", linthresh=0.01)
        a.grid(alpha=0.3)
        a.legend(fontsize=7, ncol=2)
    return _save(fig, out_dir / "timing.png")


def plot_response(report: dict, out_dir: Path) -> str:
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for gr, v in report["response"].items():
        ax.semilogx(v["freqs_hz"], v["re_1khz_db"], marker="o", ms=3, label=f"{gr} dB of limiting")
    ax.axhspan(-1, 1, color="gray", alpha=0.15, label="published +-1 dB, 40 Hz-15 kHz")
    ax.set(xlabel="Hz", ylabel="dB re 0.5-2 kHz", title="Frequency response under gain reduction")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    return _save(fig, out_dir / "response.png")


def plot_all(report: dict, renders: dict, unit: Any, out_dir: Path) -> list[str]:
    return [
        plot_curves(report, out_dir),
        plot_distortion(report, out_dir),
        plot_timing(report, renders, unit, out_dir),
        plot_response(report, out_dir),
    ]

"""The 670's transformers on their own (main plan Phase 2, "done when").

    uv run --extra fast python scripts/transformer_report.py [--only t101 ...]

For each of T101-T104 (varimu.measure.transformers: the slice's transformer
between the slice's own source and load impedances, Jiles-Atherton core,
circuitsim): frequency response re 1 kHz, THD at 30 Hz and 1 kHz against the
peak flux density, and the 30 Hz B-H loop near saturation with minor loops.
Plots and reports/transformers/summary.json; tests/test_transformers.py checks
the same figures.
"""

from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from varimu.config import REPO_ROOT  # noqa: E402
from varimu.measure import transformers as tx  # noqa: E402

OUT = REPO_ROOT / "reports" / "transformers"


def plot(key: str, s: dict) -> str:
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))
    ax[0].semilogx(s["freqs_hz"], s["gain_db"], "o-", ms=3)
    ax[0].axhspan(-1, 1, color="C2", alpha=0.08, label="+-1 dB")
    ax[0].axvspan(40, 15000, color="gray", alpha=0.06, label="670 spec band")
    ax[0].set(xlabel="frequency (Hz)", ylabel="gain re 1 kHz (dB)", title="Frequency response",
              ylim=(-12, 10))  # fmt: skip
    ax[0].legend(fontsize=8)
    for rows, label in ((s["thd_30hz"], "30 Hz"), (s["thd_1khz"], "1 kHz")):
        b = [r["b_peak_t"] for r in rows]
        ax[1].semilogy(b, [max(r["thd_pct"], 1e-4) for r in rows], "o-", ms=3, label=label)
    ax[1].axvline(s["bsat_t"], c="gray", lw=0.7, ls="--", label="mu0 Ms")
    ax[1].set(xlabel="peak flux density (T)", ylabel="THD (%)", title="Distortion vs flux")
    ax[1].legend(fontsize=8)
    lp = s["loop"]
    ax[2].plot(lp["h"], lp["b"], lw=1, label="30 Hz near saturation")
    ax[2].plot(lp["h_minor"], lp["b_minor"], lw=0.8, label="half level + 600 Hz (minor loops)")
    ax[2].set(xlabel="H (A/m)", ylabel="B (T)", title="B-H loop")
    hmax = np.percentile(np.abs(lp["h"]), 98)
    ax[2].set_xlim(-1.3 * hmax, 1.3 * hmax)
    ax[2].legend(fontsize=8)
    for a in ax:
        a.grid(alpha=0.3, which="both")
    fig.suptitle(f"{s['name']} ({s['material']}), standalone, circuitsim")
    fig.tight_layout()
    path = OUT / f"{key}.png"
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return str(path.relative_to(REPO_ROOT))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", default=list(tx.KEYS))
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    out = {}
    for key in args.only:
        s = tx.summary(key)
        s["plot"] = plot(key, s)
        g = dict(zip(s["freqs_hz"], s["gain_db"], strict=True))
        thd = " ".join(f"{r['b_peak_t']:.2f} T {r['thd_pct']:.2f}%" for r in s["thd_30hz"])
        fr = f"{g[40]:+.2f} dB at 40 Hz, {g[15000]:+.2f} dB at 15 kHz"
        print(f"{s['name']}: {fr}; 30 Hz THD {thd}")
        s["loop"] = {k: v for k, v in s["loop"].items() if k == "bsat_t"}  # plots keep the loops
        out[key] = s
    (OUT / "summary.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

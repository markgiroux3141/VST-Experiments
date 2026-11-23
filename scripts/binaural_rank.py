"""Rank the simulated HUTUBS heads by their front / back cues (docs/BINAURAL_PLAN.md B5).

For every simulated subject: `variants.front_back_contrast` on our HRTFs and on the same
person's measured ones, and our spectral distance to the measurement (from
reports/binaural/validate/summary_all.json). Does the simulation rank heads as reality does?
-> reports/binaural/validate/ranking.json (+ a scatter plot).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from varimu.binaural.hrtf import cached_head
from varimu.binaural.render import SofaHead
from varimu.binaural.variants import front_back_contrast

ROOT = Path(__file__).resolve().parents[1]
HUTUBS = ROOT / "data" / "hrtf" / "hutubs"
OUT = ROOT / "reports" / "binaural" / "validate"


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = json.loads((OUT / "summary_all.json").read_text())["subjects"]
    rows = []
    for subj in sorted(summary, key=lambda s: int(s[2:])):
        h = cached_head(f"hutubs_{subj}")
        m = SofaHead(HUTUBS / "HRIRs" / f"{subj}_HRIRs_measured.sofa", subj)
        rows.append(
            {
                "subject": subj,
                "contrast_sim_db": round(front_back_contrast(h), 2),
                "contrast_measured_db": round(front_back_contrast(m), 2),
                "lsd_vs_measured_db": round(summary[subj]["measured"]["lsd_db"], 2),
                "lsd_vs_bem_db": round(summary[subj]["hutubs_bem"]["lsd_db"], 2),
            }
        )
        print(rows[-1])
    a = np.array([r["contrast_sim_db"] for r in rows])
    b = np.array([r["contrast_measured_db"] for r in rows])
    r = float(np.corrcoef(a, b)[0, 1])
    rank = sorted(rows, key=lambda x: -x["contrast_sim_db"])
    out = {
        "corr_sim_vs_measured_contrast": round(r, 3),
        "median_contrast_sim_db": round(float(np.median(a)), 2),
        "median_contrast_measured_db": round(float(np.median(b)), 2),
        "by_sim_contrast": rank,
    }
    (OUT / "ranking.json").write_text(json.dumps(out, indent=1))
    print(f"corr {r:.3f}; median sim {np.median(a):.2f} dB, measured {np.median(b):.2f} dB")
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(b, a)
    for row in rows:
        ax.annotate(
            row["subject"], (row["contrast_measured_db"], row["contrast_sim_db"]), fontsize=7
        )
    lim = [0, max(a.max(), b.max()) * 1.05]
    ax.plot(lim, lim, "k:", lw=0.8)
    ax.set_xlabel("measured front / back contrast (dB, 4-16 kHz)")
    ax.set_ylabel("simulated (dB)")
    ax.set_title(f"HUTUBS heads, r = {r:.2f}")
    fig.tight_layout()
    fig.savefig(OUT / "ranking.png", dpi=120)


if __name__ == "__main__":
    main()

"""The Ampex 351 aligned as its manual aligns it (docs/TAPE_PLAN.md, TM5;
varimu.measure.tape_align): the settings and each step's measurements ->
reports/tape/ampex_351_alignment.{json,png}. Cached (cache/tape/align_351_<key>.json):
reruns only when the circuit, the code or the settings change (--refresh: always).

    uv run --extra fast python scripts/align_351.py [--refresh]
    uv run --extra fast python scripts/align_351.py --low   # step 3b only (1C46, 7-1/2 ips)

`--low` runs the 7-1/2 ips record EQ (step 3b) on the report's settings and merges it into
the report (its key unchanged): ~5 min instead of the whole alignment's hour.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time

import numpy as np

from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta

OUT = REPO_ROOT / "reports" / "tape"


def note(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def plot(al: ta.Alignment, path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = al.steps
    fig, ax = plt.subplots(2, 2, figsize=(11, 8))
    b = s["bias"]
    a = ax[0, 0]
    a.semilogx(b["sweep_bias_ma_rms"], b["sweep_out_db"], "o-")
    a.axvline(b["bias_ma_rms"], color="k", ls="--", label=f"set {b['bias_ma_rms']:.2f} mA")
    for i in b["half_db_ma_rms"]:
        a.axvline(i, color="gray", ls=":")
    a.set(xlabel="bias, mA rms (BIAS meter)", ylabel="1 kHz out, dB re peak",
          title="Bias: 1 kHz at 15 ips, -10 dB")  # fmt: skip
    a.legend()
    a = ax[0, 1]
    p, r = s["playback_eq"], s["record_eq"]
    a.semilogx(p["freqs_hz"], p["flatness_db"], "o-", label="test tape (2R31)")
    a.semilogx(r["freqs_hz"], r["before_db"], "x:", label="record, 1C7 as drawn")
    a.semilogx(r["freqs_hz"], r["flatness_db"], "o-", label="record, 1C7 set")
    if "record_eq_lo" in s:
        lo = s["record_eq_lo"]
        a.semilogx(lo["freqs_hz"], lo["flatness_db"], "s-", label="record 7-1/2 ips, 1C46 set")
    a.axhline(0, color="k", lw=0.5)
    a.set(xlabel="Hz", ylabel="dB re 700 / 500 Hz", title="EQ trims")
    a.legend()
    a = ax[1, 0]
    lv = s["record_level"]
    a.semilogy(lv["sweep_levels"], lv["sweep_thd_pct"], "o-")
    a.axhline(1.0, color="gray", ls=":")
    a.axvline(lv["record_level"], color="k", ls="--")
    a.set(xlabel="RECORD LEVEL rotation", ylabel="THD at 400 Hz, %",
          title="Operating level: 1% THD, 0 VU in")  # fmt: skip
    a = ax[1, 1]
    a.axis("off")
    c = s["check"]
    lines = [f"{k}: {v:.4g}" for k, v in al.overrides.items()]
    lines += [""] + [f"{k}: {np.round(v, 3)}" for k, v in c.items()]
    a.text(0, 1, "\n".join(lines), va="top", family="monospace", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=110)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--low", action="store_true", help="step 3b only, merged into the report")
    a = ap.parse_args()
    if a.low:
        al = ta.Alignment(**json.loads((OUT / "ampex_351_alignment.json").read_text()))
        o = {k: v for k, v in al.overrides.items() if k != "rec_eq_lo_f"}
        al.steps["record_eq_lo"] = ta.record_eq_lo(ta.Bench.load(), o, note)
        al.overrides["rec_eq_lo_f"] = al.steps["record_eq_lo"]["rec_eq_lo_f"]
    else:
        al = ta.aligned(note=note, refresh=a.refresh)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ampex_351_alignment.json").write_text(
        json.dumps(dataclasses.asdict(al), indent=1, default=float)
    )
    plot(al, OUT / "ampex_351_alignment.png")
    note(f"settings: {json.dumps(al.overrides)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

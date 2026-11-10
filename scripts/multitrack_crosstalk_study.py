"""Crosstalk between neighbouring tracks (docs/PERIOD_GEAR_BACKLOG.md, PG1, MT3): the model
(`varimu.multitrack.crosstalk`) fitted to Ampex's measured curve for a three-track Model 300
(`data/datasheets/ampex_300_crosstalk.csv`) on its octave envelope, with our 351's repro head
(its pole_m / relax_m), then predicted for the four-track 1/2 in stack (couplings +5 dB,
Ampex AI-14) at 15 and 7.5 ips; and the alternative where the head's contour is fitted to the
curve's lobes too, checked against the head's own response (2026-11-10: pole 6.3 mm, relax
12 mm at the search's bound, its own response within ~+-2.2 dB 20 Hz-1 kHz: a candidate head
for the deck, the user's call; PERIOD_GEAR_BACKLOG.md, MT3).

    uv run python scripts/multitrack_crosstalk_study.py [--no-contour-fit]
-> reports/multitrack/crosstalk/{fit.json,crosstalk.png} (~1 min; the contour fit ~10 min)
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np
from scipy import optimize

from varimu.config import REPO_ROOT
from varimu.devices.tape import HeadGeometry
from varimu.multitrack import crosstalk as x

OUT = REPO_ROOT / "reports" / "multitrack" / "crosstalk"
#: The 351's repro head (config/circuits/ampex_351.yaml: rep_gap_m, pole_m, relax_m).
HEAD_351 = HeadGeometry(6.35e-6, 1.5e-3, 5.5e-3)
SPEED = 0.381


def params(c: x.Crosstalk) -> dict:
    return {
        "head": {"gap_m": c.head.gap_m, "pole_m": c.head.pole_m, "relax_m": c.head.relax_m},
        "unshielded": float(c.unshielded),
        "contour_width_ratio": float(c.contour_width_ratio),
        "core": float(c.core),
        "core_db": float(20 * math.log10(abs(c.core))),
        "mutual_at_10k": float(c.mutual),
        "mutual_at_10k_db": float(20 * math.log10(c.mutual)),
        "capacitive_at_10k": float(c.capacitive),
        "capacitive_at_10k_db": float(20 * math.log10(c.capacitive)),
    }


def contour_fit(dense, fc, want) -> tuple[x.Crosstalk, float, float]:
    """The head's contour free too, on third octaves; returns it, its misfit and the head's
    own response's deepest dip 30 Hz-1 kHz at 15 ips (dB re 1 kHz)."""
    fmt = x.THREE_TRACK_HALF_INCH

    def make(p, sign):
        h = HeadGeometry(6.35e-6, p[5] * 1e-3, p[6] * 1e-3)
        g = [10 ** (v / 20) for v in p[:5]]
        return x.Crosstalk(h, g[0], p[1], sign * g[2], g[3], g[4])

    def cost(p, sign):
        _, got = x.bands(dense, make(p, sign).curve_db(dense, SPEED, fmt), fc, 3)
        return float(np.sqrt(np.mean((got - want) ** 2)))

    bounds = [(-40, 20), (0.5, 1.84), (-70, -50), (-90, -40), (-90, -40), (0.3, 8), (0.3, 12)]
    rng = np.random.default_rng(2)
    best = None
    for sign in (1.0, -1.0):
        for _ in range(25):
            p0 = [
                rng.uniform(-20, 5),
                rng.uniform(0.8, 1.8),
                -59,
                -65,
                -52,
                rng.uniform(0.5, 7),
                rng.uniform(0.5, 10),
            ]
            r = optimize.minimize(cost, p0, args=(sign,), method="Powell", bounds=bounds)
            if best is None or r.fun < best[0]:
                best = (float(r.fun), make(r.x, sign))
    rms, c = best
    ff = np.geomspace(30, 1000, 200)
    k = 2 * math.pi * ff / SPEED
    own = np.abs(x.gap_term(c.head, k) + x.contour_term(c.head, k))
    return c, rms, float(20 * np.log10(own.min() / own[-1]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-contour-fit", action="store_true", help="skip the slow alternative")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    f, db = x.measured()
    dense = np.geomspace(f.min(), f.max(), 2000)
    three, four = x.THREE_TRACK_HALF_INCH, x.FOUR_TRACK_HALF_INCH

    fitted, rms_oct = x.fit(HEAD_351)
    fc3, want3 = x.bands(f, db, per_octave=3)
    _, got3 = x.bands(dense, fitted.curve_db(dense, SPEED, three), fc3, 3)
    miss3 = got3 - want3
    four_c = fitted.scaled()
    report = {
        "fit": params(fitted),
        "rms_octaves_db": rms_oct,
        "rms_third_octaves_db": float(np.sqrt(np.mean(miss3**2))),
        "worst_third_octave": {
            "f_hz": float(fc3[np.argmax(np.abs(miss3))]),
            "miss_db": float(miss3[np.argmax(np.abs(miss3))]),
        },
        "third_octaves": [
            {"f_hz": float(c), "measured_db": float(m), "model_db": float(g)}
            for c, m, g in zip(fc3, want3, got3, strict=True)
        ],
        "four_track": {"scaled_db": x.FOUR_VS_THREE_DB, "params": params(four_c), "curves": {}},
    }
    for speed in (0.381, 0.1905):
        fo = np.array([31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000])
        report["four_track"]["curves"][f"{speed / 0.0254:g} ips"] = {
            f"{v:g}": float(c) for v, c in zip(fo, four_c.curve_db(fo, speed, four), strict=True)
        }
    if not a.no_contour_fit:
        alt, rms_alt, dip = contour_fit(dense, fc3, want3)
        report["contour_fit_alternative"] = {
            "params": params(alt),
            "rms_third_octaves_db": rms_alt,
            "own_response_deepest_30hz_1khz_db": dip,
            "relax_at_bound": bool(alt.head.relax_m >= 0.0119),
            "verdict": (
                "a candidate head for the deck: its own response within Ampex's +-2 dB-ish"
                if dip > -2.5
                else "rejected: the head's own response would dip that far (Ampex's +-2 dB)"
            ),
        }
    (OUT / "fit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.semilogx(f, db, color="0.55", lw=1.2, label="Ampex 3-track Model 300 (354 manual p 12)")
    ax.semilogx(
        dense,
        fitted.curve_db(dense, SPEED, three),
        color="C0",
        lw=1.4,
        label=f"model, 3 tracks, 15 ips (octave fit, {rms_oct:.1f} dB rms)",
    )
    ax.semilogx(
        dense,
        four_c.curve_db(dense, SPEED, four),
        color="C3",
        lw=1.4,
        label="model, 4 tracks on 1/2 in, 15 ips (+5 dB couplings)",
    )
    ax.semilogx(
        dense,
        four_c.curve_db(dense, 0.1905, four),
        color="C3",
        lw=1.0,
        ls="--",
        label="model, 4 tracks, 7.5 ips",
    )
    ax.set(
        xlim=(20, 20e3),
        ylim=(-80, -20),
        xlabel="Hz",
        ylabel="dB re the neighbour's level",
        title="Adjacent-track crosstalk",
    )
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "crosstalk.png", dpi=130)
    print(json.dumps({k: v for k, v in report.items() if k != "third_octaves"}, indent=1))


if __name__ == "__main__":
    main()

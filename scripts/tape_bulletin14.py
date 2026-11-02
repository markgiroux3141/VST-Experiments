"""A check, not a fit (docs/TAPE_PLAN.md, "Gaps" 2): Sound Talk Bulletin No. 14 on the
medium as it stands. 3M measured, by third-order cross-modulation (2F1 - F2 of two nearly
equal tones), the recording current that gives equal distortion against frequency: for
Scotch 111 at 7.5 ips "the permissable recording current is constant up to about 1200 cps.,
and above that rises gradually until at 7000 cycles, 4 db. greater recording current may be
used"; "the effect is a wavelength rather than a frequency effect". The bulletin prints no
figure and no distortion criterion, so two criteria are run.

Here: the first print's machine (varimu.devices.tape_machine, its heads provisional) at
7.5 ips with its aligned bias (500 Hz at 7.5 ips, the median of the 1/2 dB points), F2 =
1.1 F1, equal deep-gap fields per tone; the pattern read by the repro head over one common
period (F1 and 2F1 - F2 both whole cycles), two periods' worth recorded either side; per
F1 a sweep of levels, each criterion's crossing interpolated. 15 ips at twice the
frequencies checks the wavelength claim. -> reports/tape/bulletin14.{json,png}

    uv run --extra fast python scripts/tape_bulletin14.py [--tape SCOTCH111@3]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time

import numpy as np

from varimu.config import REPO_ROOT
from varimu.devices import library
from varimu.devices.tape import head_hx_spectrum, head_hy_spectrum
from varimu.devices.tape_machine import TapeMachineSpec, _record, _slab, aligned

OUT = REPO_ROOT / "reports" / "tape"
F1_HZ = (400.0, 800.0, 1200.0, 2000.0, 3000.0, 5000.0, 7000.0)
CRITERIA_DB = (-40.0, -30.0)  # 2F1 - F2 re F1
PUBLISHED = {"f_hz": [1200.0, 7000.0], "db": [0.0, 4.0]}  # re the low frequencies


def cross_mod_db(spec, tape, f1: float, hg: float, hg_bias: float) -> float:
    """2F1 - F2 re F1 (dB) as the repro head reads a two-tone recording, F2 = 1.1 F1, each
    at peak deep-gap field hg."""
    d = 0.1 * f1
    f2, v = f1 + d, spec.speed_m_s
    slab = _slab(spec, tape)
    period_m = v / d
    pad = 2.0 * period_m
    lead = 600e-6
    every = lead + np.arange(int(round((period_m + 2 * pad) / slab.ds_m))) * slab.ds_m
    mx, my = _record(
        spec,
        tape,
        lambda t: hg * (np.sin(2 * math.pi * f1 * t) + np.sin(2 * math.pi * f2 * t)),
        hg_bias,
        0.0,
        (every[-1] + lead) / v,
        every,
        2.0 * hg,
    )
    s0 = every[0] + pad
    mid = (every >= s0) & (every < s0 + period_m)
    s, mx, my = every[mid], mx[:, mid], my[:, mid]
    head = spec.rep_head()

    def read(f: float) -> complex:
        k = 2 * math.pi * f / v
        ph = np.exp(-1j * k * s)
        ax, ay = (mx * ph).mean(axis=1) * 2, (my * ph).mean(axis=1) * 2
        ks = np.array([k])
        wx = np.array([head_hx_spectrum(head, ks, slab.spacing_m + y)[0] for y in slab.depths_m])
        wy = np.array([head_hy_spectrum(head, ks, slab.spacing_m + y)[0] for y in slab.depths_m])
        return 1j * k * v * ((ax * wx).sum() - (ay * wy).sum())

    return 20 * math.log10(abs(read(2 * f1 - f2)) / abs(read(f1)))


LEVELS_OVER_HC = tuple(float(x) for x in np.geomspace(0.05, 1.6, 8))


def sweep(spec, tape, f1, hg_bias, hc) -> np.ndarray:
    """Cross-modulation (dB) at LEVELS_OVER_HC times hc per tone."""
    return np.array([cross_mod_db(spec, tape, f1, x * hc, hg_bias) for x in LEVELS_OVER_HC])


def permissible(levels: np.ndarray, imd_db: np.ndarray, target_db: float) -> float:
    """The level where the cross-modulation first rises through target_db (linear in
    log level between the sweep's points)."""
    lv = np.log(levels)
    for i in range(1, len(lv)):
        if imd_db[i - 1] < target_db <= imd_db[i]:
            w = (target_db - imd_db[i - 1]) / (imd_db[i] - imd_db[i - 1])
            return float(np.exp(lv[i - 1] + w * (lv[i] - lv[i - 1])))
    raise RuntimeError(f"{target_db} dB not crossed: {np.round(imd_db, 1)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tape", default="SCOTCH111@3")
    a = ap.parse_args()
    tape = library.load_tape(a.tape)
    t0 = time.time()
    al = aligned(TapeMachineSpec(), tape, REPO_ROOT / "cache" / "tape")
    hc = tape.preisach.hc_median_a_m
    print(f"bias {al.hg_bias / hc:.2f} Hc (aligned in {time.time() - t0:.0f} s)", flush=True)
    res = {
        "tape": a.tape,
        "hg_bias_over_hc": al.hg_bias / hc,
        "published": PUBLISHED,
        "levels_over_hc": LEVELS_OVER_HC,
    }
    for ips, scale in ((7.5, 1.0), (15.0, 2.0)):
        spec = TapeMachineSpec(flutter=False).at_speed(ips * 0.0254)
        sweeps = []
        for f in F1_HZ:
            sweeps.append(sweep(spec, tape, f * scale, al.hg_bias, hc))
            print(f"  {ips} ips, {f * scale:.0f} Hz: {np.round(sweeps[-1], 1)}", flush=True)
        res[f"{ips:g}ips_sweeps_db"] = [x.tolist() for x in sweeps]
        for target in CRITERIA_DB:
            rows = [permissible(np.array(LEVELS_OVER_HC), sw, target) for sw in sweeps]
            db = 20 * np.log10(np.array(rows) / rows[0])
            res[f"{ips:g}ips_{target:g}db"] = {
                "f1_hz": [f * scale for f in F1_HZ],
                "hg_over_hc": rows,
                "re_lowest_db": db.tolist(),
            }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bulletin14.json").write_text(json.dumps(res, indent=1))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for k, r in res.items():
        if isinstance(r, dict) and "f1_hz" in r:
            ax.semilogx(F1_HZ, r["re_lowest_db"], "o-", label=k.replace("_", ", "))
    ax.plot(PUBLISHED["f_hz"], PUBLISHED["db"], "ks", ms=8, label="No. 14 (7.5 ips)")
    ax.plot([400, 1200], [0, 0], "k-", lw=3, alpha=0.4)
    ax.set(xlabel="F1 at 7.5 ips (15 ips: at the same wavelength)",
           ylabel="permissible field, dB re 400 Hz",
           title=f"Bulletin 14: equal cross-modulation against frequency ({a.tape})")  # fmt: skip
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "bulletin14.png", dpi=110)
    print(f"done in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

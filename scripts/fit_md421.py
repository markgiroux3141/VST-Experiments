"""Fit the R_MD421 cartridge's provisional geometry to Sennheiser's MD 421-II figures (CHAINS_PLAN.md WP14 step 3).

    uv run python scripts/fit_md421.py [--write] [--band LO HI]

No dimension of the MD 421 is published (data/schematics/sennheiser_md421/README.md). Its
sensitivity (2 mV/Pa, open circuit: a transformerless coil), its response (the sheet's M
position, data/datasheets/sennheiser_md421_response.csv) and its polars at 90 degrees (180 at 8 and
16 kHz: sennheiser_md421_polar.csv) are the figures; the unknowns are fitted one to a figure the way
scripts/fit_sm57.py does it (this reuses its machinery on the MD 421's geometry and no
transformer):

    bl_tm, b_gap_t           the sensitivity
    resonance_hz             the low end's corner
    ps.r1_pa_s_m3            the low end's damping (the bass bump)
    ps.q, ps.d_m             the network's delay: the side / rear ratio at 2-4 kHz and the presence rise
    washer.r_pa_s_m3,        the pattern at 125 Hz: the bass chamber's air behind the washer
    handle.volume_m3

The body (`bor.dynamic_mesh`, a 70 mm head) gives the entries. `--write` puts the fitted values
into data/datasheets/published_points.yaml's "R_MD421" block; `varimu fit-devices --only R_MD421`
makes the component version. Plot -> reports/mics/r_md421_fit.png, numbers ->
reports/mics/r_md421_fit.json.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).parent))
import fit_sm57 as fs  # noqa: E402

from varimu.config import DATA_DIR, REPO_ROOT  # noqa: E402
from varimu.devices.library import _plain  # noqa: E402
from varimu.mics.networks import moving_coil_response  # noqa: E402

KEY = "R_MD421"
BAND_HZ = (40.0, 8000.0)
FREE = [
    (("coil", "bl_tm"), 0.5, 20.0, True),
    (("coil", "b_gap_t"), 0.6, 1.4, False),
    (("diaphragm", "resonance_hz"), 35.0, 110.0, False),
    (("diaphragm", "thickness_m"), 8e-6, 60e-6, True),
    (("network", "ps", "r1_pa_s_m3"), 1e4, 1e8, True),
    (("network", "ps", "q"), 0.55, 80.0, True),
    (("network", "ps", "d_m"), 0.015, 0.060, False),
    (("network", "washer", "r_pa_s_m3"), 1e5, 1e10, True),
    (("network", "handle", "volume_m3"), 5e-6, 400e-6, True),
]
MODE = [  # the dome's presence-region mode
    (("diaphragm", "modes", 0, "f_hz"), 1800.0, 9000.0, True),
    (("diaphragm", "modes", 0, "q"), 0.7, 10.0, True),
    (("diaphragm", "modes", 0, "mass_fraction"), 0.02, 0.5, True),
    (("diaphragm", "modes", 0, "area_fraction"), 0.05, 0.6, True),
]
FREE += MODE
LEVELS_HZ = {"125": 125.0, "250": 250.0, "500": 500.0, "1000": 1000.0, "2000": 2000.0,
             "4000": 4000.0, "8000": 8000.0, "16000": 16000.0}  # fmt: skip


def load_targets():
    """The M position's response re 1 kHz, and the polars (90 deg; 180 where the sheet's curve
    is above its 25 dB floor: 8 and 16 kHz)."""
    with open(DATA_DIR / "datasheets" / "sennheiser_md421_response.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["trace"] == "M"]
    fr = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["dbv_per_pa"]) for r in rows])
    db = db - float(np.interp(1000.0, fr, db))
    polar = {}
    with open(DATA_DIR / "datasheets" / "sennheiser_md421_polar.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ang, hz, d = float(r["angle_deg"]), float(r["freq_hz"]), float(r["db_re_axis"])
            if (ang == 90.0 or (ang == 180.0 and d > -24.0)) and hz <= BAND_HZ[1]:
                polar[(hz, int(ang))] = d
    return (fr, db), polar


def response(g, f, theta_deg):
    """Volts at the coil, open circuit, per pascal of a plane wave from theta (no transformer)."""
    c = fs.cartridge(g)
    ent = fs.body_entries(g["body"], g["diaphragm"]["radius_m"], f, theta_deg)
    return moving_coil_response(c, f, ent)


fs.response = response  # fs.residuals / fs.summary / fs.plot call the module's `response`


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--band", type=float, nargs=2, default=BAND_HZ)
    args = ap.parse_args()
    fs.MIC = {"key": KEY, "response": ("sennheiser_md421_response.csv", "sennheiser"), "polar": None}
    fs.CAP_ON = False
    entry = yaml.safe_load(fs.PUBLISHED.read_text(encoding="utf-8"))[KEY]
    g0 = _plain(entry["geometry"])
    sens = entry["published"]["sensitivity_v_per_pa"]
    all_resp, polar = load_targets()
    band = tuple(args.band)
    f, db = all_resp
    keep = (f >= band[0]) & (f <= band[1])
    fit_resp = (f[keep], db[keep])
    free = FREE
    res = least_squares(fs.residuals, fs._x0(g0, free), bounds=fs._bounds(free), x_scale="jac",
                        args=(g0, free, band, fit_resp, polar, sens, None), diff_step=1e-4)  # fmt: skip
    g = fs._with(g0, res.x, free)
    # summary() reads band_of(g) and free_of(g): the MD 421's are these
    fs.band_of = lambda _g: band
    fs.free_of = lambda _g: free
    out = fs.summary(g, all_resp, polar, sens)
    out["cost"] = float(res.cost)
    out["at_bounds"] = [
        fs._label(p) for (p, lo, hi, log), v in zip(free, res.x, strict=True)
        if min(abs(v - (math.log(lo) if log else lo)), abs(v - (math.log(hi) if log else hi)))
        < 1e-3 * abs(v or 1)
    ]  # fmt: skip
    out.pop("seeler", None)
    print(json.dumps(out, indent=1))
    rep = REPO_ROOT / "reports" / "mics"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "r_md421_fit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    fs.MIC["response"] = ("sennheiser_md421_response.csv", "sennheiser")
    plot(g, all_resp, polar, band, rep / "r_md421_fit.png")
    if args.write:
        write(g, free)
        print("written; run: uv run varimu fit-devices --only R_MD421")


def plot(g, all_resp, polar, band, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f, db = all_resp
    ff = np.geomspace(30, 16000, 120)
    ref = abs(response(g, np.array([1000.0]), 0.0)[0])
    fig, ax = plt.subplots(figsize=(8, 5))
    for th, style in ((0, "-"), (90, "--"), (180, ":")):
        ax.semilogx(ff, 20 * np.log10(abs(response(g, ff, th)) / ref), "k" + style, lw=1.2,
                    label=f"model {th} deg")  # fmt: skip
    ax.semilogx(f, db, "o", ms=3, color="tab:red", label="sennheiser M on axis")
    for (fr, side), want in polar.items():
        ax.plot(fr, want, "s" if side == 90 else "^", color="tab:blue", ms=5)
    ax.axvspan(*band, color="0.93", zorder=0)
    ax.set(xlabel="Hz", ylabel="dB re 1 kHz on axis", ylim=(-30, 10), title="R_MD421 on its body")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def write(g, free) -> None:
    """The fitted values into published_points.yaml's R_MD421 block, in place."""
    p = fs.PUBLISHED
    text = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    lines = text.replace("\r\n", "\n").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f'"{KEY}":'))
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()
                and not lines[i].startswith("#")), len(lines))  # fmt: skip
    for path, *_ in free:
        key, v = path[-1], fs._get(g, path)
        if path[0] == "network":
            hits = [i for i in range(start, end) if f"name: {path[1]}," in lines[i]]
        elif "modes" in path:
            hits = [i for i in range(start, end) if "name: dome," in lines[i]]
        else:
            hits = [i for i in range(start, end) if re.match(rf"\s+{key}: \{{value:", lines[i])]
        if len(hits) != 1:
            raise SystemExit(f"published_points.yaml: {len(hits)} lines for {path}")
        i = hits[0]
        pat = rf"({key}: \{{value: )([^}}]+)\}}"
        lines[i], n = re.subn(pat, rf"\g<1>{fs._num(v, 5)}}}", lines[i])
        if n != 1:
            raise SystemExit(f"published_points.yaml: {key} not on line {i + 1}")
    out = "\n".join(lines)
    p.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))


if __name__ == "__main__":
    main()

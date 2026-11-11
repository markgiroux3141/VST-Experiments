"""Fit the R_520 cartridge's provisional geometry to Shure's 520D figures (CHAINS_PLAN.md WP30).

    uv run python scripts/fit_520d.py [--write] [--band LO HI]

scripts/fit_sm7.py's method (fit_sm57's machinery) on the 520D "Green Bullet" (Shure's 1980 data
sheet): Figure 1's response re 1 kHz (data/datasheets/shure_520d_response.csv, from the scan by
scripts/digitize_shure_520d.py); 15.85 mV/Pa at the high-impedance lead with the case's 39k across
the cartridge and the attached 20 ft cord's capacitance (the mic as shipped); the winding's
impedance at 1 kHz derived from the low tap's 160 ohm (published_points.yaml "R_520").
Omnidirectional: no polar targets (the back is sealed: a pressure element on its case, the body
form `cylinder`). Every unknown bounded (FREE). Writes reports/mics/r_520_fit.{json,png};
--write puts the values into published_points.yaml.
"""

from __future__ import annotations

import argparse
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
from varimu.devices.moving_coil import compile_network  # noqa: E402
from varimu.mics.networks import moving_coil_response  # noqa: E402

KEY = "R_520"
BAND_HZ = (85.0, 6500.0)
FREE = [
    (("coil", "bl_tm"), 1.0, 1000.0, True),
    (("coil", "le_h"), 0.2, 5.0, True),
    (("diaphragm", "moving_mass_kg"), 30e-6, 2e-3, True),
    (("diaphragm", "resonance_hz"), 150.0, 1800.0, True),
    (("diaphragm", "q"), 0.3, 10.0, True),
    (("diaphragm", "modes", 0, "f_hz"), 1500.0, 7000.0, True),
    (("diaphragm", "modes", 0, "q"), 0.7, 20.0, True),
    (("diaphragm", "modes", 0, "mass_fraction"), 0.005, 0.5, True),
    (("diaphragm", "modes", 0, "area_fraction"), 0.05, 0.6, True),
    (("network", "grille", "r_pa_s_m3"), 1e3, 1e8, True),
    (("network", "grille", "m_kg_m4"), 10.0, 1e4, True),
    (("network", "chamber", "volume_m3"), 0.1e-6, 40e-6, True),
    (("network", "back", "volume_m3"), 1e-6, 100e-6, True),
]
SENS_WEIGHT = 3.0  # dB residuals: the sensitivity and the impedance count as three response points
Z_WEIGHT = 3.0


def load_targets():
    with open(DATA_DIR / "datasheets" / "shure_520d_response.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fr = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    return fr, db - float(np.interp(math.log(1000.0), np.log(fr), db))


def response(g, f, theta_deg, pub):
    """Volts at the end of the attached cord per pascal of a plane wave from theta: the
    cartridge's Thevenin source (open circuit and short circuit solved) into the case's 39k in
    parallel with the cord's capacitance (the response of the mic as shipped)."""
    c = fs.cartridge(g)
    f = np.asarray(f, float)
    ent = fs.body_entries(g["body"], g["diaphragm"]["radius_m"], f, theta_deg)
    v_oc = moving_coil_response(c, f, ent, r_load_ohm=1e9)
    r_short = 1e-2
    z_th = v_oc / (moving_coil_response(c, f, ent, r_load_ohm=r_short) / r_short)
    y_load = 1.0 / pub["load_ohm"] + 2j * np.pi * f * pub["cable_c_f"]
    return v_oc / (1.0 + z_th * y_load)


def impedance(g, f_hz=1000.0):
    """The winding's Thevenin impedance at f_hz (|V open| / |I short|), motional part included."""
    c = fs.cartridge(g)
    f = np.array([f_hz])
    ent = fs.body_entries(g["body"], g["diaphragm"]["radius_m"], f, 0.0)
    v_oc = moving_coil_response(c, f, ent, r_load_ohm=1e9)[0]
    r_short = 1e-2
    return abs(v_oc / (moving_coil_response(c, f, ent, r_load_ohm=r_short)[0] / r_short))


def residuals(x, g0, free, band, target, pub):
    g = fs._with(g0, x, free)
    f, db = target
    sel = (f >= band[0]) & (f <= band[1])
    f, db = f[sel], db[sel]
    grid = np.unique(np.concatenate([f, [1000.0]]))
    h = response(g, grid, 0.0, pub)
    ref = abs(h[grid == 1000.0][0])
    r = list(np.interp(f, grid, 20 * np.log10(abs(h) / ref)) - db)
    r.append(SENS_WEIGHT * 20 * math.log10(ref / pub["sensitivity_v_per_pa"]))
    r.append(Z_WEIGHT * 20 * math.log10(impedance(g) / pub["impedance_ohm"]))
    return np.array(r)


def summary(g, target, pub, band):
    f, db = target
    grid = np.unique(np.concatenate([f, [1000.0]]))
    h = response(g, grid, 0.0, pub)
    ref = abs(h[grid == 1000.0][0])
    model = np.interp(f, grid, 20 * np.log10(abs(h) / ref))
    err = model - db
    sel = (f >= band[0]) & (f <= band[1])
    worst = int(np.argmax(np.abs(np.where(sel, err, 0.0))))
    side = {}
    for th in (90, 180):
        hh = response(g, np.array([1000.0, 4000.0]), float(th), pub)
        h0 = response(g, np.array([1000.0, 4000.0]), 0.0, pub)
        side[str(th)] = [round(float(x), 2) for x in 20 * np.log10(abs(hh) / abs(h0))]
    return {
        "values": {fs._label(p): fs._get(g, p) for p, *_ in FREE},
        "sensitivity_v_per_pa": float(ref),
        "impedance_1k_ohm": float(impedance(g)),
        "response_rms_db": float(np.sqrt(np.mean(err[sel] ** 2))),
        "response_worst_db": [float(f[worst]), float(err[worst])],
        "off_axis_db_at_1k_4k": side,
        "resonance_hz": compile_network(g)["resonance_hz"],
    }


def plot(g, target, pub, band, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f, db = target
    ff = np.geomspace(40, 16000, 140)
    ref = abs(response(g, np.array([1000.0]), 0.0, pub)[0])
    fig, ax = plt.subplots(figsize=(8, 5))
    for th, style in ((0, "-"), (90, "--"), (180, ":")):
        h = response(g, ff, float(th), pub)
        ax.semilogx(ff, 20 * np.log10(abs(h) / ref), "k" + style, lw=1.2, label=f"model {th} deg")
    ax.semilogx(f, db, "o", ms=3, color="tab:red", label="shure 520D Figure 1")
    ax.axvspan(*band, color="0.93", zorder=0)
    ax.set(xlabel="Hz", ylabel="dB re 1 kHz on axis", ylim=(-30, 10),
           title="R_520 on its case, into the case's 39k and its cord")  # fmt: skip
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def write(g) -> None:
    """The fitted values into published_points.yaml's R_520 block, in place."""
    p = fs.PUBLISHED
    text = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    lines = text.replace("\r\n", "\n").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f'"{KEY}":'))
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()
                and not lines[i].startswith("#")), len(lines))  # fmt: skip
    for path, *_ in FREE:
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
        lines[i], n = re.subn(rf"({key}: \{{value: )([^}}]+)\}}", rf"\g<1>{fs._num(v, 5)}}}",
                              lines[i])  # fmt: skip
        if n != 1:
            raise SystemExit(f"published_points.yaml: {key} not on line {i + 1}")
    out = "\n".join(lines)
    p.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--band", type=float, nargs=2, default=BAND_HZ)
    args = ap.parse_args()
    fs.MIC = {"key": KEY, "response": None, "polar": None}
    entry = yaml.safe_load(fs.PUBLISHED.read_text(encoding="utf-8"))[KEY]
    g0 = _plain(entry["geometry"])
    pub = entry["published"]
    target = load_targets()
    band = tuple(args.band)
    res = least_squares(
        residuals, fs._x0(g0, FREE), bounds=fs._bounds(FREE), x_scale="jac",
        args=(g0, FREE, band, target, pub), diff_step=1e-4,
    )  # fmt: skip
    g = fs._with(g0, res.x, FREE)
    out = summary(g, target, pub, band)
    out["cost"] = float(res.cost)
    out["at_bounds"] = [
        fs._label(p) for (p, lo, hi, log), v in zip(FREE, res.x, strict=True)
        if min(abs(v - (math.log(lo) if log else lo)), abs(v - (math.log(hi) if log else hi)))
        < 1e-3 * abs(v or 1)
    ]  # fmt: skip
    print(json.dumps(out, indent=1, default=float))
    rep = REPO_ROOT / "reports" / "mics"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "r_520_fit.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    plot(g, target, pub, band, rep / "r_520_fit.png")
    if args.write:
        write(g)
        print("written; run: uv run varimu fit-devices --only R_520")


if __name__ == "__main__":
    main()

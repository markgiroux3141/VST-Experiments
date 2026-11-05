"""Fit the CK12 capsule's provisional geometry to AKG's published curves (CHAINS_PLAN.md WP3).

    uv run python scripts/fit_ck12.py [--spacing-mm 3.5 4.1 5] [--proud-mm 0 0.5] [--write]

The CK12's geometry has no primary source (data/schematics/akg_c12/README.md, "The capsule
CK12"): what is published bounds it (Austrian Audio: the gap 30-50 um, the slit between
the resistance disks the gradient resistance, the membrane resonance 800-1500 Hz; the
first film 10 um Styroflex), the rest is fitted here, as scripts/fit_k47.py does the K47:
the capsule-only network wired as the C12's (varimu.mics.networks.backplate_response: the
backplate the output, the front diaphragm at ground, the pattern the rear's polarization:
+60 V omni, 0 cardioid, -60 V figure-8), into the C12's grid (LOAD), on the capsule's body
(varimu.mics.bor) against AKG's curves (data/datasheets/akg_c12_response.csv: omni and
cardioid / 8 on axis, cardioid at 180 deg, figure-8 at 90 deg, re each pattern's on-axis
1 kHz) and its sensitivity (br: 1.0 mV/ubar at the output, over the C12's amplifier:
SENSITIVITY_V_PA). Points below 60 Hz are left to the electronics (T14/1 and C12 set the
curves' last octave: the omni capsule is flat there).

`--write` puts the best body's fitted values into data/datasheets/published_points.yaml's
"CK12" geometry (by each fitted line's bounds comment); `varimu fit-devices --only CK12`
then makes the component version. Plots -> reports/mics/ck12_fit.png, the grid's table ->
reports/mics/ck12_fit.json.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json

import numpy as np
import yaml
from fit_k47 import BODY_GRID, Entries, _get, _set, _with
from scipy.optimize import least_squares

from varimu.config import DATA_DIR, REPO_ROOT
from varimu.devices.capsule import DUAL_FIELDS, DualCapsule, dual_lumped
from varimu.devices.library import _plain
from varimu.mics.networks import backplate_response

PUBLISHED = DATA_DIR / "datasheets" / "published_points.yaml"
# The backplate's load in the C12 (config/circuits/akg_c12.yaml): R14 || R15 (each 250
# MOhm, R15 through C13), and C13 (1000 pF) in series with the 6072's input, Cgk + Cgp (1 +
# A), A the grid-to-anode gain measured in the circuit (32.3; 12AY7@1's 1.3 / 1.3 pF:
# 44.6 pF), 42.7 pF.
LOAD = {"r_load_ohm": 125e6, "c_load_f": 42.7e-12}
# The sensitivity at the backplate (V/Pa at 1 kHz): br's 1.0 mV/ubar at no load over the
# amplifier's backplate-to-output gain there, 0.957 (C13 against the grid's input) x 2.803
# (grid to the 200 ohm output, measured in the circuit 2026-11-05). AKG: 'equally high
# sensitivity at all directional patterns'.
AMP_GAIN = 0.957 * 2.803
SENSITIVITY_V_PA = 10e-3 / AMP_GAIN
REAR_V = {"omni": 60.0, "cardioid": 0.0, "figure8": -60.0}

# (path into the geometry, low, high, its line's comment in published_points.yaml).
NETWORK = [
    # Austrian Audio's membrane resonance 800-1500 Hz, read as the membrane's own
    # (sqrt(6 T / (rho_s a^2)) / 2 pi: dual_lumped's membrane_resonance_hz) on the 10 um film
    (("diaphragm", "tension_n_m"), 7.47, 26.3, "bounds 7.47-26.3 N/m"),
    (("gap_m",), 30e-6, 50e-6, "bounds 30-50 um"),
    (("through_resistance_pa_s_m3",), 1e6, 3e9, "bounds 1e6-3e9"),
    (("film_resistance_pa_s_m3",), 1e4, 3e7, "bounds 1e4-3e7"),
    (("backplate", "blind", "depth_m"), 0.3e-3, 1.9e-3, "bounds 0.3-1.9 mm"),
    (("backplate", "blind", "holes"), 10.0, 250.0, "bounds 10-250 per side"),
    (("stray_capacitance_f",), 2e-12, 40e-12, "bounds 2-40 pF"),
]
F_MIN_HZ = 60.0
# The curves fitted. The figure-8's 90 deg curve (-17 to -23 dB) is reported, not fitted:
# the model's halves are equal, so its side null is exact; the real one is set by the
# halves' differences (Austrian Audio: the two resistance disks differ), not modelled.
FITTED = (("omni", 0), ("cardioid", 0), ("cardioid", 180))
REAR_CLIP_DB = -30.0
TEXT = {"pattern", "document", "reference", "quality"}


def _rows():
    with open(DATA_DIR / "datasheets" / "akg_c12_response.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [{k: (v if k in TEXT else float(v)) for k, v in r.items()} for r in rows]


def load_curves():
    return [r for r in _rows() if r["freq_hz"] >= F_MIN_HZ]


def capsule_of(geom) -> DualCapsule:
    lp = dual_lumped(geom)
    return DualCapsule("CK12", *(lp[k] for k in DUAL_FIELDS))


def _h(c, ent, e0):
    def h(f, th, pat):
        return backplate_response(c, f, ent(f, th), e0, REAR_V[pat] * e0 / 60.0, **LOAD)

    return h


def _curve_db(h, pat, ang, f):
    """dB at angle `ang` re the pattern's on-axis 1 kHz (AKG's charts' reference)."""
    on = abs(h([1000.0], 0.0, pat)[0])
    return 20 * np.log10(np.abs(h(f, np.radians(ang), pat)) / on)


def residuals(x, geom0, free, ent, e0, rows):
    g = _with(geom0, free, x)
    c = capsule_of(g)
    if c.c_diaphragm_at(e0) <= 0:  # collapsed onto the backplate
        n = sum(1 for r in rows if (r["pattern"], r["angle_deg"]) in FITTED)
        return np.full(n + 3, 50.0)
    h = _h(c, ent, e0)
    out = []
    for pat, ang in FITTED:
        pts = [r for r in rows if r["pattern"] == pat and r["angle_deg"] == ang]
        f = np.array([r["freq_hz"] for r in pts])
        db = _curve_db(h, pat, ang, f)
        w = np.array([0.5 if r["quality"] == "coarse" else 1.0 for r in pts])
        if ang != 0:
            w = 0.5 * w
            db = np.maximum(db, REAR_CLIP_DB)
        out.append(w * (db - np.maximum([r["db"] for r in pts], REAR_CLIP_DB)))
    for pat in ("cardioid", "omni", "figure8"):
        s = abs(h([1000.0], 0.0, pat)[0])
        # br: +-1.5 dB; weighted so that a dB off costs about what a curve's dB does
        out.append(np.array([1.5 * 20 * np.log10(s / SENSITIVITY_V_PA)]))
    return np.concatenate(out)


def summary(g, free, ent, e0, rows) -> dict:
    c = capsule_of(g)
    h = _h(c, ent, e0)
    out = {"/".join(p): float(_get(g, p)) for p, *_ in free}
    out |= {f"body/{k}": v for k, v in g["body"].items()}
    for pat in ("cardioid", "omni", "figure8"):
        out[f"{pat}_mv_pa_at_backplate"] = round(1e3 * abs(h([1000.0], 0.0, pat)[0]), 3)
    out["target_mv_pa"] = round(1e3 * SENSITIVITY_V_PA, 3)
    for pat, ang in (("omni", 0), ("cardioid", 0), ("cardioid", 180), ("figure8", 90)):
        pts = [r for r in rows if r["pattern"] == pat and r["angle_deg"] == ang]
        f = np.array([r["freq_hz"] for r in pts])
        d = _curve_db(h, pat, ang, f) - [r["db"] for r in pts]
        out[f"{pat}_{ang}_rms_db"] = round(float(np.sqrt(np.mean(d**2))), 2)
        out[f"{pat}_{ang}_max_db"] = round(float(np.max(np.abs(d))), 2)
        out[f"{pat}_{ang}_max_db_at_hz"] = float(f[np.argmax(np.abs(d))])
    out["c0_pf"] = round(1e12 * c.c0_f, 1)
    out["electrostatic_softening"] = round(c.neg_stiffness_per_v2 * e0**2 * c.c_diaphragm, 3)
    lp = dual_lumped(g)
    out["membrane_resonance_in_vacuo_hz"] = round(lp["membrane_resonance_hz"], 1)
    return out


def fit(geom0, e0, rows) -> tuple[dict, dict, Entries]:
    free = NETWORK
    freqs = [r["freq_hz"] for r in rows] + [1000.0]
    angles = [0.0, np.pi / 2, np.pi]
    ent = Entries(geom0, freqs, angles)
    lo = np.log([f[1] for f in free])
    hi = np.log([f[2] for f in free])
    best = None
    for t in (12.0, 40.0):
        for rt in (1e7, 2e8):
            x0 = np.log([_get(geom0, f[0]) for f in free])
            x0[0], x0[2] = np.log(t), np.log(rt)
            sol = least_squares(
                residuals, np.clip(x0, lo + 1e-9, hi - 1e-9), bounds=(lo, hi),
                args=(geom0, free, ent, e0, rows), x_scale="jac", max_nfev=200,
            )  # fmt: skip
            if best is None or sol.cost < best.cost:
                best = sol
    g = _with(geom0, free, best.x)
    result = summary(g, free, ent, e0, rows)
    result["rms_weighted_db"] = round(float(np.sqrt(np.mean(best.fun**2))), 2)
    return g, result, ent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spacing-mm", type=float, nargs="+", help="the body's diaphragm spacing grid")
    ap.add_argument("--proud-mm", type=float, nargs="+", help="the membrane rings' height grid")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    entry = yaml.safe_load(PUBLISHED.read_text(encoding="utf-8"))["CK12"]
    geom0 = _plain(entry["geometry"])
    e0 = entry["polarization_v"]
    rows = load_curves()
    spacings = args.spacing_mm or [1e3 * _get(geom0, BODY_GRID[0])]
    prouds = args.proud_mm or [1e3 * _get(geom0, BODY_GRID[1])]
    table, best = [], None
    for s in spacings:
        for pr in prouds:
            g0 = copy.deepcopy(geom0)
            _set(g0, BODY_GRID[0], 1e-3 * s)
            _set(g0, BODY_GRID[1], 1e-3 * pr)
            g, result, ent = fit(g0, e0, rows)
            print(json.dumps(result, indent=1), flush=True)
            table.append(result)
            if best is None or result["rms_weighted_db"] < best[1]["rms_weighted_db"]:
                best = (g, result, ent)
    g, result, ent = best
    (REPO_ROOT / "reports" / "mics").mkdir(parents=True, exist_ok=True)
    out = {"best": result, "grid": table}
    (REPO_ROOT / "reports" / "mics" / "ck12_fit.json").write_text(json.dumps(out, indent=1))
    _plot(g, e0)
    if args.write:
        lines = PUBLISHED.read_text(encoding="utf-8").split("\n")
        start = lines.index('"CK12":')
        for path in [p for p, *_ in NETWORK] + list(BODY_GRID):
            key = f"{path[-1]}: {{value:"
            tag = next((f[3] for f in NETWORK if f[0] == path), "grid:")
            hits = [i for i, ln in enumerate(lines) if i > start and tag in ln and key in ln]
            if not hits:
                raise SystemExit(f"published_points.yaml: no line for {path} ({tag})")
            i = hits[0]
            head, rest = lines[i].split("{value:", 1)
            lines[i] = f"{head}{{value: {_yaml_float(_get(g, path))}}}" + rest.split("}", 1)[1]
        PUBLISHED.write_text("\n".join(lines), encoding="utf-8")
        print("written; run: uv run varimu fit-devices --only CK12")


def _yaml_float(v: float) -> str:
    """4 significant digits as a YAML 1.1 float (PyYAML reads '5e-05' as a string)."""
    s = f"{float(v):.4g}"
    mant, _, exp = s.partition("e")
    if "." not in mant:
        mant += ".0"
    return mant + ("e" + exp if exp else "")


def _plot(g, e0) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = _rows()
    c = capsule_of(g)
    f = np.geomspace(20, 20000, 120)
    ang = np.radians(np.arange(0, 361, 5))
    pf = [100.0, 1000.0, 5000.0, 10000.0]
    ent = Entries(g, [*f, 1000.0, *pf], [*np.radians([0, 90, 180]), *ang])
    h = _h(c, ent, e0)
    fig = plt.figure(figsize=(14, 9))
    for i, pat in enumerate(("omni", "cardioid", "figure8")):
        ax = fig.add_subplot(2, 3, 1 + i)
        ref = abs(h([1000.0], 0.0, pat)[0])
        for a in (0, 90, 180):
            (ln,) = ax.semilogx(f, 20 * np.log10(np.abs(h(f, np.radians(a), pat)) / ref),
                                label=f"{a} deg")  # fmt: skip
            pts = [r for r in data if r["pattern"] == pat and r["angle_deg"] == a]
            if pts:
                ax.plot([r["freq_hz"] for r in pts], [r["db"] for r in pts], "o", ms=3,
                        color=ln.get_color())  # fmt: skip
        ax.set_title(f"{pat}: capsule model (lines) vs AKG (dots), re 1 kHz on axis", fontsize=9)
        ax.set_ylim(-35, 10)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=7)
        ax = fig.add_subplot(2, 3, 4 + i, projection="polar")
        ax.set_theta_zero_location("S")
        for f0 in pf:
            on = abs(h([f0], 0.0, pat)[0])
            sim = [abs(h([f0], a, pat)[0]) for a in ang]
            db = np.maximum(20 * np.log10(np.array(sim) / on), -25)
            ax.plot(ang, db + 25, label=f"{f0:g} Hz")
        ax.set_title(f"{pat} polars (radius: dB + 25)", fontsize=9)
        ax.legend(fontsize=6, loc="lower left")
    fig.tight_layout()
    fig.savefig(REPO_ROOT / "reports" / "mics" / "ck12_fit.png", dpi=100)
    plt.close(fig)


if __name__ == "__main__":
    main()

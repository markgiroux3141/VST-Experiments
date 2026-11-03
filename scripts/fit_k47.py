"""Fit the K47 capsule's provisional geometry to Neumann's published curves (A3).

    uv run python scripts/fit_k47.py [--write]

The K47's geometry has no primary source (data/schematics/neumann_u47/README.md, "The
capsule"): what is known is sourced (2 x 78-83 pF, 63 V, the diaphragm's material and
size), the rest is bounded and fitted here, the capsule-only network
(varimu.mics.networks.dual_response, into the drawing's 60 MOhm grid leak and the
VF14's input capacitance) against Neumann's curves (data/datasheets/
neumann_u47_response.csv, neumann_u47_polar.csv; ds58): the cardioid's on-axis response
re 1 kHz, its polar diagrams (dB re 0 degrees per frequency), the omni's on-axis response.
The absolute level too: Neumann's sensitivities at the output over the U47 amplifier's
measured gain (SENSITIVITY_V_PA). The fitted values go into data/datasheets/
published_points.yaml's "K47" geometry with `--write` (sourced "provisional: fitted by
scripts/fit_k47.py"); `varimu fit-devices --only K47` then makes the component version.
Plots -> reports/mics/k47_fit.png.

Status (2026-11-03): not usable yet. This network can't reach Neumann's curves (no
low-frequency cardioid; without the body's diffraction the omni notches near 15 kHz), so
K47@1 holds the starting values as a placeholder (MIC_ROOM_PLAN.md A3's status).
"""

from __future__ import annotations

import argparse
import copy
import csv
import json

import numpy as np
import yaml
from scipy.optimize import least_squares

from varimu.config import DATA_DIR, REPO_ROOT
from varimu.devices.capsule import DUAL_FIELDS, DualCapsule, dual_lumped
from varimu.devices.library import _plain
from varimu.mics.networks import dual_response

PUBLISHED = DATA_DIR / "datasheets" / "published_points.yaml"
LOAD = {"r_load_ohm": 60e6, "c_load_f": 8e-12}  # R2; the VF14's grid (provisional ~8 pF)

# (path into the geometry, low, high, its line's comment in published_points.yaml): the
# fitted values, bounded.
FREE = [
    (("diaphragm", "tension_n_m"), 300.0, 5000.0, "fitted (bounds 300-5000)"),
    (("backplate", "through", "radius_m"), 0.15e-3, 1.2e-3, "fitted (bounds 0.15-1.2 mm)"),
    (("backplate", "blind", "depth_m"), 0.2e-3, 4.0e-3, "fitted (bounds 0.2-4 mm)"),
    (("backplate", "blind", "radius_m"), 0.2e-3, 1.0e-3, "fitted (bounds 0.2-1.0 mm)"),
    (("path_m",), 4e-3, 30e-3, "path, bounds 4-30 mm"),
    (("film_resistance_pa_s_m3",), 1e6, 3e9, "film resistance, bounds 1e6-3e9"),
]
# The polars' weight. 0 in version 1: the lumped dual network can't hold a cardioid at low
# frequencies (its internal air's compliance against the diaphragm's adds an omni term that
# fills the null: 0 dB front to back at 100 Hz where Neumann's has 11.7; MIC_ROOM_PLAN.md A3's
# status), so K47@1 fits the on-axis responses and sensitivities only (a source on axis in
# free field: the first listen) and its directivity is not Neumann's.
POLAR_WEIGHT = 0.0


TEXT = {"pattern", "document", "reference", "quality"}
RESPONSE_DOC, POLAR_DOC = "tf52", "ds58"  # Telefunken's measured-looking 1952 curves re 1 kHz
# The sensitivity at the grid (V/Pa at 1 kHz): Neumann's at the output into 1 kOhm (ds58:
# cardioid 2.5-2.8, omni 1.4-1.7 mV/ubar, the middles) over the amplifier's +9.7 dB from
# grid to output there (the circuit's, measured 2026-11-03).
AMP_GAIN = 10 ** (9.7 / 20)
SENSITIVITY_V_PA = {"cardioid": 26.5e-3 / AMP_GAIN, "omni": 15.5e-3 / AMP_GAIN}


def load_curves():
    def rows(name, doc):
        with open(DATA_DIR / "datasheets" / name, encoding="utf-8") as f:
            out = [
                {k: (v if k in TEXT else float(v)) for k, v in r.items()} for r in csv.DictReader(f)
            ]
        return [r for r in out if r["document"] == doc]

    return (
        rows("neumann_u47_response.csv", RESPONSE_DOC),
        rows("neumann_u47_polar.csv", POLAR_DOC),
    )


def _get(g, path):
    for k in path:
        g = g[k]
    return g


def _set(g, path, v):
    for k in path[:-1]:
        g = g[k]
    g[path[-1]] = v


def capsule_of(geom) -> DualCapsule:
    lp = dual_lumped(geom)
    return DualCapsule("K47", *(lp[k] for k in DUAL_FIELDS))


def residuals(x, geom0, e0, response, polar):
    g = copy.deepcopy(geom0)
    for (path, *_), v in zip(FREE, np.exp(x), strict=True):
        _set(g, path, v)
    c = capsule_of(g)
    path_m = g["path_m"]
    out = []
    for pat, weight in (("cardioid", 1.0), ("omni", 0.7)):
        pts = [r for r in response if r["pattern"] == pat and r["angle_deg"] == 0]
        if not pts:
            continue
        f = np.array([r["freq_hz"] for r in pts])
        h = dual_response(c, np.r_[f, 1000.0], 0.0, path_m, e0, pat, **LOAD)
        db = 20 * np.log10(np.abs(h[:-1]) / np.abs(h[-1]))
        out.append(weight * (db - np.array([r["db"] for r in pts])))
    for pat in ("cardioid", "omni"):
        for f0 in sorted({r["freq_hz"] for r in polar if r["pattern"] == pat}):
            pts = [r for r in polar if r["pattern"] == pat and r["freq_hz"] == f0]
            ang = np.array([r["angle_deg"] for r in pts])
            on = dual_response(c, [f0], 0.0, path_m, e0, pat, **LOAD)[0]
            sim = np.array(
                [
                    abs(dual_response(c, [f0], np.radians(a), path_m, e0, pat, **LOAD)[0])
                    for a in ang
                ]
            )
            db = 20 * np.log10(np.maximum(sim, 1e-12) / abs(on))
            # Nulls are poorly defined: clip both at -25 dB; coarse readings count half.
            w = POLAR_WEIGHT * np.array([0.5 if r["quality"] == "coarse" else 1.0 for r in pts])
            out.append(w * (np.maximum(db, -25) - np.maximum([r["db"] for r in pts], -25)))
    for pat, target in SENSITIVITY_V_PA.items():
        h = dual_response(c, [1000.0], 0.0, path_m, e0, pat, **LOAD)[0]
        out.append(np.array([3.0 * 20 * np.log10(abs(h) / target)]))
    return np.concatenate(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    pub = yaml.safe_load(PUBLISHED.read_text(encoding="utf-8"))
    entry = pub["K47"]
    geom0 = _plain(entry["geometry"])
    e0 = entry["polarization_v"]
    response, polar = load_curves()
    x0 = np.log([_get(geom0, f[0]) for f in FREE])
    lo = np.log([f[1] for f in FREE])
    hi = np.log([f[2] for f in FREE])
    sol = least_squares(
        residuals, np.clip(x0, lo + 1e-9, hi - 1e-9), bounds=(lo, hi),
        args=(geom0, e0, response, polar), x_scale="jac", max_nfev=400,
    )  # fmt: skip
    g = copy.deepcopy(geom0)
    for (path, *_), v in zip(FREE, np.exp(sol.x), strict=True):
        _set(g, path, float(v))
    rms = float(np.sqrt(np.mean(sol.fun**2)))
    result = {"/".join(f[0]): float(_get(g, f[0])) for f in FREE}
    result["rms_weighted_db"] = rms
    c = capsule_of(g)
    for pat, target in SENSITIVITY_V_PA.items():
        h = abs(dual_response(c, [1000.0], 0.0, g["path_m"], e0, pat, **LOAD)[0])
        result[f"{pat}_mv_pa_at_grid"] = round(1e3 * h, 2)
        result[f"{pat}_target_mv_pa"] = round(1e3 * target, 2)
    back = dual_response(c, [1000.0], np.pi, g["path_m"], e0, "cardioid", **LOAD)[0]
    front = dual_response(c, [1000.0], 0.0, g["path_m"], e0, "cardioid", **LOAD)[0]
    result["cardioid_front_back_1k_db"] = round(float(20 * np.log10(abs(front / back))), 1)
    on = [r for r in response if r["angle_deg"] == 0]
    for pat in ("cardioid", "omni"):
        pts = [r for r in on if r["pattern"] == pat]
        f = np.array([r["freq_hz"] for r in pts])
        h = dual_response(c, np.r_[f, 1000.0], 0.0, g["path_m"], e0, pat, **LOAD)
        d = 20 * np.log10(np.abs(h[:-1]) / np.abs(h[-1])) - np.array([r["db"] for r in pts])
        result[f"{pat}_on_axis_rms_db"] = round(float(np.sqrt(np.mean(d**2))), 2)
        result[f"{pat}_on_axis_max_db"] = round(float(np.max(np.abs(d))), 2)
    print(json.dumps(result, indent=1))
    _plot(g, e0, response, polar)
    if args.write:
        lines = PUBLISHED.read_text(encoding="utf-8").split("\n")
        for path, _, _, tag in FREE:
            hits = [i for i, ln in enumerate(lines) if tag in ln and f"{path[-1]}: {{value:" in ln]
            if len(hits) != 1:
                raise SystemExit(f"published_points.yaml: {len(hits)} lines for {path} ({tag})")
            i = hits[0]
            head, rest = lines[i].split("{value:", 1)
            lines[i] = f"{head}{{value: {float(_get(g, path)):.4g}}}" + rest.split("}", 1)[1]
        PUBLISHED.write_text("\n".join(lines), encoding="utf-8")
        print("written; run: uv run varimu fit-devices --only K47")


def _plot(g, e0, response, polar) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    c = capsule_of(g)
    f = np.geomspace(20, 20000, 120)
    fig = plt.figure(figsize=(13, 9))
    for i, pat in enumerate(("cardioid", "omni")):
        ax = fig.add_subplot(2, 2, 1 + i)
        for ang in (0, 90, 180):
            h = dual_response(c, np.r_[f, 1000.0], np.radians(ang), g["path_m"], e0, pat, **LOAD)
            ref = abs(dual_response(c, [1000.0], 0.0, g["path_m"], e0, pat, **LOAD)[0])
            (ln,) = ax.semilogx(f, 20 * np.log10(np.abs(h[:-1]) / ref), label=f"{ang} deg")
            pts = [r for r in response if r["pattern"] == pat and r["angle_deg"] == ang]
            if pts:
                ax.plot(
                    [r["freq_hz"] for r in pts],
                    [r["db"] for r in pts],
                    "o",
                    ms=3,
                    color=ln.get_color(),
                )
        ax.set_title(f"{pat}: model (lines) vs Neumann (dots), re 1 kHz on axis")
        ax.set_ylim(-35, 10)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=7)
        ax = fig.add_subplot(2, 2, 3 + i, projection="polar")
        for f0 in sorted({r["freq_hz"] for r in polar if r["pattern"] == pat}):
            ang = np.radians(np.arange(0, 361, 5))
            on = abs(dual_response(c, [f0], 0.0, g["path_m"], e0, pat, **LOAD)[0])
            sim = [abs(dual_response(c, [f0], a, g["path_m"], e0, pat, **LOAD)[0]) for a in ang]
            (ln,) = ax.plot(
                ang, np.maximum(20 * np.log10(np.array(sim) / on), -30) + 30, label=f"{f0:g} Hz"
            )
            pts = [r for r in polar if r["pattern"] == pat and r["freq_hz"] == f0]
            ax.plot(
                np.radians([r["angle_deg"] for r in pts]),
                [max(r["db"], -30) + 30 for r in pts],
                "o",
                ms=3,
                color=ln.get_color(),
            )
        ax.set_title(f"{pat} polars (radius: dB + 30)")
        ax.legend(fontsize=6, loc="lower left")
    fig.tight_layout()
    out = REPO_ROOT / "reports" / "mics"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "k47_fit.png", dpi=100)
    plt.close(fig)


if __name__ == "__main__":
    main()

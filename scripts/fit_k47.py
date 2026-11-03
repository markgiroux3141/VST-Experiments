"""Fit the K47 capsule's provisional geometry to Neumann's published curves (A3).

    uv run python scripts/fit_k47.py [--write]

The K47's geometry has no primary source (data/schematics/neumann_u47/README.md, "The
capsule"; K47_THEORY.md): what is known is sourced (2 x 78-83 pF, 63 V, the diaphragm's
material and size, the backplate's measured thickness and hole diameters), the rest is
bounded and fitted here: the capsule-only network (varimu.mics.networks.dual_response,
into the drawing's 60 MOhm grid leak and the VF14's input capacitance) on a rigid sphere
(the entries' diffraction: varimu.mics.free_field.sphere_entry_factors) against Neumann's
curves (data/datasheets/neumann_u47_response.csv: Telefunken 1952's on-axis responses re
1 kHz; neumann_u47_polar.csv: the 1958 sheet's polars) and sensitivities (ds58 at the
output over the U47 amplifier's measured gain: SENSITIVITY_V_PA).

The regime (K47_THEORY.md, Torio & Segota, AES 2000; von Braunmuhl & Weber, US
2,179,361): a nearly slack diaphragm (tens of N/m: the gradient mode friction-controlled),
the gradient resistance in the path between the two sides (the film's flow to the
through holes and the holes: `through_resistance_pa_s_m3`, fitted), a small film
resistance into the blind holes, the blind holes' adiabatic air the cavity. A first fit
bounded the tension like a measurement capsule's (300-5000 N/m) and found no cardioid.

`--write` puts the fitted values into data/datasheets/published_points.yaml's "K47"
geometry (by each fitted line's bounds comment); `varimu fit-devices --only K47` then
makes the component version. Plots -> reports/mics/k47_fit.png.
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
# The grid as the capsule sees it in the U47: R2, and the VF14's input with its Miller
# capacitance, Cgk + Cgp (1 + A), A the stage's gain grid to anode measured in the circuit
# (20.5; VF14T@1's 6.5 / 3.0 pF: 71 pF, 2026-11-03). An 8 pF guess left the circuit's
# sensitivity 4.4 dB under the fit's.
LOAD = {"r_load_ohm": 60e6, "c_load_f": 71e-12}

# (path into the geometry, low, high, its line's comment in published_points.yaml).
FREE = [
    (("diaphragm", "tension_n_m"), 12.0, 200.0, "bounds 12-200 N/m"),
    (("through_resistance_pa_s_m3",), 1e6, 3e9, "bounds 1e6-3e9"),
    (("film_resistance_pa_s_m3",), 1e4, 3e7, "bounds 1e4-3e7"),
    (("backplate", "blind", "depth_m"), 0.5e-3, 4.5e-3, "bounds 0.5-4.5 mm"),
    (("backplate", "blind", "holes"), 15.0, 140.0, "bounds 15-140 per side"),
    (("sphere_radius_m",), 9.5e-3, 25e-3, "bounds 9.5-25 mm"),
]
POLAR_WEIGHT = 0.5
TEXT = {"pattern", "document", "reference", "quality"}
RESPONSE_DOC, POLAR_DOC = "tf52", "ds58"
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


def capsule_of(geom) -> tuple[DualCapsule, tuple[float, float]]:
    lp = dual_lumped(geom)
    sphere = (geom["sphere_radius_m"], geom["diaphragm"]["radius_m"])
    return DualCapsule("K47", *(lp[k] for k in DUAL_FIELDS)), sphere


def _with(geom0, x):
    g = copy.deepcopy(geom0)
    for (path, *_), v in zip(FREE, np.exp(x), strict=True):
        _set(g, path, float(v))
    return g


def residuals(x, geom0, e0, response, polar):
    c, sph = capsule_of(_with(geom0, x))
    if c.c_diaphragm_at(e0) <= 0:  # collapsed onto the backplate
        return np.full(len(response) + len(polar) + 2, 50.0)

    def h(f, th, pat):
        return dual_response(c, f, th, 0.0, e0, pat, sphere=sph, **LOAD)

    out = []
    for pat in ("cardioid", "omni"):
        pts = [r for r in response if r["pattern"] == pat and r["angle_deg"] == 0]
        f = np.array([r["freq_hz"] for r in pts])
        hh = h(np.r_[f, 1000.0], 0.0, pat)
        out.append(20 * np.log10(np.abs(hh[:-1]) / np.abs(hh[-1])) - [r["db"] for r in pts])
    for pat in ("cardioid", "omni"):
        for f0 in sorted({r["freq_hz"] for r in polar if r["pattern"] == pat}):
            pts = [r for r in polar if r["pattern"] == pat and r["freq_hz"] == f0]
            on = abs(h([f0], 0.0, pat)[0])
            sim = np.array([abs(h([f0], np.radians(r["angle_deg"]), pat)[0]) for r in pts])
            db = 20 * np.log10(np.maximum(sim, 1e-12) / on)
            w = POLAR_WEIGHT * np.array([0.5 if r["quality"] == "coarse" else 1.0 for r in pts])
            # Nulls are poorly defined: both clipped at -25 dB.
            out.append(w * (np.maximum(db, -25) - np.maximum([r["db"] for r in pts], -25)))
    for pat, target in SENSITIVITY_V_PA.items():
        out.append(np.array([3.0 * 20 * np.log10(abs(h([1000.0], 0.0, pat)[0]) / target)]))
    return np.concatenate(out)


def summary(g, e0, response) -> dict:
    c, sph = capsule_of(g)

    def h(f, th, pat):
        return dual_response(c, f, th, 0.0, e0, pat, sphere=sph, **LOAD)

    out = {"/".join(p): float(_get(g, p)) for p, *_ in FREE}
    for pat, target in SENSITIVITY_V_PA.items():
        out[f"{pat}_mv_pa_at_grid"] = round(1e3 * abs(h([1000.0], 0.0, pat)[0]), 2)
        out[f"{pat}_target_mv_pa"] = round(1e3 * target, 2)
    for f0 in (100.0, 1000.0, 5000.0):
        fb = abs(h([f0], 0.0, "cardioid")[0] / h([f0], np.pi, "cardioid")[0])
        out[f"cardioid_front_back_{f0:g}_db"] = round(float(20 * np.log10(fb)), 1)
    for pat in ("cardioid", "omni"):
        pts = [r for r in response if r["pattern"] == pat and r["angle_deg"] == 0]
        f = np.array([r["freq_hz"] for r in pts])
        hh = h(np.r_[f, 1000.0], 0.0, pat)
        d = 20 * np.log10(np.abs(hh[:-1]) / np.abs(hh[-1])) - [r["db"] for r in pts]
        out[f"{pat}_on_axis_rms_db"] = round(float(np.sqrt(np.mean(d**2))), 2)
        out[f"{pat}_on_axis_max_db"] = round(float(np.max(np.abs(d))), 2)
    out["electrostatic_softening"] = round(c.neg_stiffness_per_v2 * e0**2 * c.c_diaphragm, 2)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    entry = yaml.safe_load(PUBLISHED.read_text(encoding="utf-8"))["K47"]
    geom0 = _plain(entry["geometry"])
    e0 = entry["polarization_v"]
    response, polar = load_curves()
    lo = np.log([f[1] for f in FREE])
    hi = np.log([f[2] for f in FREE])
    best = None
    for t in (15.0, 40.0):  # the solution doesn't depend on the start (2026-11-03)
        for rt in (1e7, 2e8):
            x0 = np.log([_get(geom0, f[0]) for f in FREE])
            x0[0], x0[1] = np.log(t), np.log(rt)
            sol = least_squares(
                residuals, np.clip(x0, lo + 1e-9, hi - 1e-9), bounds=(lo, hi),
                args=(geom0, e0, response, polar), x_scale="jac", max_nfev=150,
            )  # fmt: skip
            if best is None or sol.cost < best.cost:
                best = sol
    g = _with(geom0, best.x)
    result = summary(g, e0, response)
    result["rms_weighted_db"] = round(float(np.sqrt(np.mean(best.fun**2))), 2)
    print(json.dumps(result, indent=1))
    (REPO_ROOT / "reports" / "mics").mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "reports" / "mics" / "k47_fit.json").write_text(json.dumps(result, indent=1))
    _plot(g, e0, response, polar)
    if args.write:
        lines = PUBLISHED.read_text(encoding="utf-8").split("\n")
        for path, _, _, tag in FREE:
            key = f"{path[-1]}: {{value:"
            hits = [i for i, ln in enumerate(lines) if tag in ln and key in ln]
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

    c, sph = capsule_of(g)

    def h(f, th, pat):
        return dual_response(c, f, th, 0.0, e0, pat, sphere=sph, **LOAD)

    f = np.geomspace(20, 20000, 120)
    fig = plt.figure(figsize=(13, 9))
    for i, pat in enumerate(("cardioid", "omni")):
        ax = fig.add_subplot(2, 2, 1 + i)
        ref = abs(h([1000.0], 0.0, pat)[0])
        for ang in (0, 90, 180):
            (ln,) = ax.semilogx(f, 20 * np.log10(np.abs(h(f, np.radians(ang), pat)) / ref),
                                label=f"{ang} deg")  # fmt: skip
            pts = [r for r in response if r["pattern"] == pat and r["angle_deg"] == ang]
            if pts:
                ax.plot([r["freq_hz"] for r in pts], [r["db"] for r in pts], "o", ms=3,
                        color=ln.get_color())  # fmt: skip
        ax.set_title(f"{pat}: model (lines) vs Telefunken 1952 (dots), re 1 kHz on axis")
        ax.set_ylim(-35, 10)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=7)
        ax = fig.add_subplot(2, 2, 3 + i, projection="polar")
        for f0 in sorted({r["freq_hz"] for r in polar if r["pattern"] == pat}):
            ang = np.radians(np.arange(0, 361, 5))
            on = abs(h([f0], 0.0, pat)[0])
            sim = [abs(h([f0], a, pat)[0]) for a in ang]
            (ln,) = ax.plot(ang, np.maximum(20 * np.log10(np.array(sim) / on), -30) + 30,
                            label=f"{f0:g} Hz")  # fmt: skip
            pts = [r for r in polar if r["pattern"] == pat and r["freq_hz"] == f0]
            ang_p = np.radians([r["angle_deg"] for r in pts])
            ax.plot(ang_p, [max(r["db"], -30) + 30 for r in pts], "o", ms=3, color=ln.get_color())
        ax.set_title(f"{pat} polars vs Neumann 1958 (radius: dB + 30)")
        ax.legend(fontsize=6, loc="lower left")
    fig.tight_layout()
    fig.savefig(REPO_ROOT / "reports" / "mics" / "k47_fit.png", dpi=100)
    plt.close(fig)


if __name__ == "__main__":
    main()

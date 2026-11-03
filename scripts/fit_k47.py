"""Fit the K47 capsule's provisional geometry to Neumann's published curves (A3).

    uv run python scripts/fit_k47.py [--spacing-mm 5.75 7] [--proud-mm 0 0.5] [--write]

The K47's geometry has no primary source (data/schematics/neumann_u47/README.md, "The
capsule"; K47_THEORY.md): what is known is sourced (2 x 78-83 pF, 63 V, the diaphragm's
material and size, the backplate's measured thickness and hole diameters), the rest is
bounded and fitted here: the capsule-only network (varimu.mics.networks.dual_response,
into the drawing's 60 MOhm grid leak and the VF14's input capacitance) on the capsule's
body against Neumann's curves (data/datasheets/neumann_u47_response.csv: Telefunken 1952's
on-axis responses re 1 kHz; neumann_u47_polar.csv: the 1958 sheet's polars) and
sensitivities (ds58 at the output over the U47 amplifier's measured gain:
SENSITIVITY_V_PA).

The entries' diffraction: the geometry's `body` (the capsule as a rigid body of
revolution, varimu.mics.bor: its order-0 BEM, the diaphragms' blocked pressures), solved
once per body on the data's frequencies and angles; the body's unknown dimensions (the
diaphragms' spacing, the clamping rings' height) are a grid (`--spacing-mm`,
`--proud-mm`), the network fitted on each. A geometry with `sphere_radius_m` instead (K47@2)
fits the sphere's radius with the network (free_field.sphere_entry_factors).

The regime (K47_THEORY.md, Torio & Segota, AES 2000; von Braunmuhl & Weber, US
2,179,361): a nearly slack diaphragm (tens of N/m: the gradient mode friction-controlled),
the gradient resistance in the path between the two sides (the film's flow to the
through holes and the holes: `through_resistance_pa_s_m3`, fitted), a small film
resistance into the blind holes, the blind holes' adiabatic air the cavity. A first fit
bounded the tension like a measurement capsule's (300-5000 N/m) and found no cardioid.

`--write` puts the best body's fitted values into data/datasheets/published_points.yaml's
"K47" geometry (by each fitted line's bounds comment); `varimu fit-devices --only K47` then
makes the component version. Plots -> reports/mics/k47_fit.png, the grid's table ->
reports/mics/k47_fit.json.
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
from varimu.mics import bor
from varimu.mics.free_field import sphere_entry_factors
from varimu.mics.networks import dual_response

PUBLISHED = DATA_DIR / "datasheets" / "published_points.yaml"
# The grid as the capsule sees it in the U47: R2, and the VF14's input with its Miller
# capacitance, Cgk + Cgp (1 + A), A the stage's gain grid to anode measured in the circuit
# (20.5; VF14T@1's 6.5 / 3.0 pF: 71 pF, 2026-11-03). An 8 pF guess left the circuit's
# sensitivity 4.4 dB under the fit's.
LOAD = {"r_load_ohm": 60e6, "c_load_f": 71e-12}

# (path into the geometry, low, high, its line's comment in published_points.yaml).
NETWORK = [
    (("diaphragm", "tension_n_m"), 12.0, 200.0, "bounds 12-200 N/m"),
    (("through_resistance_pa_s_m3",), 1e6, 3e9, "bounds 1e6-3e9"),
    (("film_resistance_pa_s_m3",), 1e4, 3e7, "bounds 1e4-3e7"),
    (("backplate", "blind", "depth_m"), 0.5e-3, 4.5e-3, "bounds 0.5-4.5 mm"),
    (("backplate", "blind", "holes"), 15.0, 140.0, "bounds 15-140 per side"),
]
SPHERE = (("sphere_radius_m",), 9.5e-3, 25e-3, "bounds 9.5-25 mm")
BODY_GRID = (("body", "spacing_m"), ("body", "ring_proud_m"))
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


def capsule_of(geom) -> DualCapsule:
    lp = dual_lumped(geom)
    return DualCapsule("K47", *(lp[k] for k in DUAL_FIELDS))


class Entries:
    """The entries' pressures at (f, theta) for a geometry: on its body (a BEM table on
    the frequencies and angles asked for at construction, ~0.2 s per frequency) or on
    its sphere (the series, live)."""

    def __init__(self, geom, freqs, angles_rad):
        self.geom = geom
        self.table = None
        if "body" in geom:
            self.f = np.unique(np.asarray(freqs, float))
            self.th = np.unique(np.round(np.asarray(angles_rad, float), 12))
            op = bor.operator(bor.capsule_mesh(geom["body"], geom["diaphragm"]["radius_m"]))
            self.table = bor.entry_factors(op, self.f, self.th)
            k = 2 * np.pi * 20.0 / 343.2
            lf = bor.entry_factors(op, [20.0], [0.0])
            self.path_m = float(np.imag(lf[0][0, 0] - lf[1][0, 0]) / k)
        else:
            self.path_m = 3 * geom["sphere_radius_m"]

    def __call__(self, f, th):
        f = np.atleast_1d(np.asarray(f, float))
        if self.table is None:
            g = self.geom
            return sphere_entry_factors(f, th, g["sphere_radius_m"], g["diaphragm"]["radius_m"])
        j = np.searchsorted(self.th, round(float(th), 12))
        i = np.searchsorted(self.f, f)
        if j >= len(self.th) or self.th[j] != round(float(th), 12) or np.any(self.f[i] != f):
            raise KeyError(f"entries not tabulated at {f} Hz, {np.degrees(th)} deg")
        return self.table[0][i, j], self.table[1][i, j]


def _with(geom0, free, x):
    g = copy.deepcopy(geom0)
    for (path, *_), v in zip(free, np.exp(x), strict=True):
        _set(g, path, float(v))
    return g


def _h(c, ent, e0):
    def h(f, th, pat):
        return dual_response(c, f, th, 0.0, e0, pat, entries=ent(f, th), **LOAD)

    return h


def residuals(x, geom0, free, ent, e0, response, polar):
    g = _with(geom0, free, x)
    c = capsule_of(g)
    if c.c_diaphragm_at(e0) <= 0:  # collapsed onto the backplate
        return np.full(len(response) + len(polar) + 2, 50.0)
    h = _h(c, ent if ent.table is not None else Entries(g, (), ()), e0)
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


def summary(g, free, ent, e0, response) -> dict:
    c = capsule_of(g)
    h = _h(c, ent, e0)
    out = {"/".join(p): float(_get(g, p)) for p, *_ in free}
    if "body" in g:
        out |= {f"body/{k}": v for k, v in g["body"].items()}
    out["low_frequency_path_mm"] = round(1e3 * ent.path_m, 2)
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
        out[f"{pat}_on_axis_max_db_at_hz"] = float(f[np.argmax(np.abs(d))])
    out["electrostatic_softening"] = round(c.neg_stiffness_per_v2 * e0**2 * c.c_diaphragm, 2)
    return out


def fit(geom0, e0, response, polar) -> tuple[dict, dict, Entries]:
    """The network fitted on one geometry (its body fixed, or its sphere free)."""
    free = NETWORK if "body" in geom0 else [*NETWORK, SPHERE]
    freqs = (
        [r["freq_hz"] for r in response] + [r["freq_hz"] for r in polar] + [100.0, 1000.0, 5000.0]
    )
    angles = [0.0, np.pi] + [np.radians(r["angle_deg"]) for r in polar]
    ent = Entries(geom0, freqs, angles)
    lo = np.log([f[1] for f in free])
    hi = np.log([f[2] for f in free])
    best = None
    for t in (15.0, 40.0):  # the solution doesn't depend on the start (2026-11-03)
        for rt in (1e7, 2e8):
            x0 = np.log([_get(geom0, f[0]) for f in free])
            x0[0], x0[1] = np.log(t), np.log(rt)
            sol = least_squares(
                residuals, np.clip(x0, lo + 1e-9, hi - 1e-9), bounds=(lo, hi),
                args=(geom0, free, ent, e0, response, polar), x_scale="jac", max_nfev=150,
            )  # fmt: skip
            if best is None or sol.cost < best.cost:
                best = sol
    g = _with(geom0, free, best.x)
    if ent.table is None:
        ent = Entries(g, (), ())
    result = summary(g, free, ent, e0, response)
    result["rms_weighted_db"] = round(float(np.sqrt(np.mean(best.fun**2))), 2)
    return g, result, ent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spacing-mm", type=float, nargs="+", help="the body's diaphragm spacing grid")
    ap.add_argument("--proud-mm", type=float, nargs="+", help="the clamping rings' height grid")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    entry = yaml.safe_load(PUBLISHED.read_text(encoding="utf-8"))["K47"]
    geom0 = _plain(entry["geometry"])
    e0 = entry["polarization_v"]
    response, polar = load_curves()
    grids = [[None]]
    if "body" in geom0:
        grids = [
            args.spacing_mm or [1e3 * _get(geom0, BODY_GRID[0])],
            args.proud_mm or [1e3 * _get(geom0, BODY_GRID[1])],
        ]
    rows, best = [], None
    for s in grids[0]:
        for pr in grids[1] if len(grids) > 1 else [None]:
            g0 = copy.deepcopy(geom0)
            if s is not None:
                _set(g0, BODY_GRID[0], 1e-3 * s)
                _set(g0, BODY_GRID[1], 1e-3 * pr)
            g, result, ent = fit(g0, e0, response, polar)
            print(json.dumps(result, indent=1), flush=True)
            rows.append(result)
            if best is None or result["rms_weighted_db"] < best[1]["rms_weighted_db"]:
                best = (g, result, ent)
    g, result, ent = best
    (REPO_ROOT / "reports" / "mics").mkdir(parents=True, exist_ok=True)
    out = {"best": result, "grid": rows}
    (REPO_ROOT / "reports" / "mics" / "k47_fit.json").write_text(json.dumps(out, indent=1))
    _plot(g, e0, response, polar)
    if args.write:
        free = NETWORK if "body" in g else [*NETWORK, SPHERE]
        lines = PUBLISHED.read_text(encoding="utf-8").split("\n")
        for path in [p for p, *_ in free] + (list(BODY_GRID) if "body" in g else []):
            key = f"{path[-1]}: {{value:"
            tag = next((f[3] for f in free if f[0] == path), "grid:")
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

    c = capsule_of(g)
    f = np.geomspace(20, 20000, 120)
    pf = sorted({r["freq_hz"] for r in polar})
    ang = np.radians(np.arange(0, 361, 5))
    ent = Entries(g, [*f, 1000.0, *pf], [*np.radians([0, 90, 180]), *ang])
    h = _h(c, ent, e0)
    fig = plt.figure(figsize=(13, 9))
    for i, pat in enumerate(("cardioid", "omni")):
        ax = fig.add_subplot(2, 2, 1 + i)
        ref = abs(h([1000.0], 0.0, pat)[0])
        for a in (0, 90, 180):
            (ln,) = ax.semilogx(f, 20 * np.log10(np.abs(h(f, np.radians(a), pat)) / ref),
                                label=f"{a} deg")  # fmt: skip
            pts = [r for r in response if r["pattern"] == pat and r["angle_deg"] == a]
            if pts:
                ax.plot([r["freq_hz"] for r in pts], [r["db"] for r in pts], "o", ms=3,
                        color=ln.get_color())  # fmt: skip
        ax.set_title(f"{pat}: model (lines) vs Telefunken 1952 (dots), re 1 kHz on axis")
        ax.set_ylim(-35, 10)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=7)
        ax = fig.add_subplot(2, 2, 3 + i, projection="polar")
        for f0 in sorted({r["freq_hz"] for r in polar if r["pattern"] == pat}):
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

"""Fit the KK 49 capsule's provisional network to Neumann's M 49 c curves (CHAINS_PLAN.md WP29).

    uv run --extra fast python scripts/fit_kk49.py [--correction] [--write]

scripts/fit_k67.py's method (fit_ck12.py's machinery: the capsule-only network into a grid load,
on the capsule's body, patterns by the rear's polarization) with the M 49 c's data: the on-axis
responses per pattern and the cardioid's 180 deg from its polars
(data/datasheets/neumann_m49_response.csv, digitized from the product description's p. 7-8) and
the sensitivities into 1000 ohm (pd p. 5: 0.45 / 0.6 / 0.8 mV/ub omni / cardioid / figure-8). The
circuit's part (the R3 feedback onto the backplate, the grid's loading, BV 11) is measured as a
correction per pattern: the whole microphone (config/circuits/neumann_m49.yaml, the capsule it
pins) over the capsule-only model (same geometry) into LOAD, on axis, by a multitone; its 1 kHz
ratio is the pattern's amplifier gain (`--correction` re-measures it:
reports/mics/kk49_correction.json). The KK 49 is taken to be the K 47's twin (RecordingHacks): its
geometry starts from published_points.yaml's "KK49" (K47@3's), the gap and the backplate (2 x
78...83 pF) and the body not fitted.

`--write` puts the fitted values into published_points.yaml's "KK49" geometry; `varimu
fit-devices --only KK49` then makes the component version. Plots -> reports/mics/kk49_fit.png,
the table -> reports/mics/kk49_fit.json.
"""

from __future__ import annotations

import argparse
import csv
import json

import fit_ck12 as base
import fit_k67
import numpy as np
import yaml
from scipy.optimize import least_squares

from varimu.config import DATA_DIR, REPO_ROOT
from varimu.devices.library import _plain

CIRCUIT = "neumann_m49"
# The grid's load: R5 150M (to the ground line) and the AC 701's input with C4 (the loop's
# measured correction carries the rest).
LOAD = {"r_load_ohm": 150e6, "c_load_f": 100e-12}
# fit_ck12 scales these by e0 / 60: the rear's polarization against the front's 58 V
REAR_V = {"omni": 60.0, "cardioid": 0.0, "figure8": -60.0}
# K47's bounds (published_points.yaml's comments, the K 47's regime: Torio & Segota)
NETWORK = [
    (("diaphragm", "tension_n_m"), 12.0, 200.0, "bounds 12-200 N/m"),
    (("through_resistance_pa_s_m3",), 1e6, 3e9, "bounds 1e6-3e9"),
    (("film_resistance_pa_s_m3",), 1e4, 3e7, "bounds 1e4-3e7"),
    (("backplate", "blind", "depth_m"), 0.5e-3, 4.5e-3, "bounds 0.5-4.5 mm"),
    (("backplate", "blind", "holes"), 15.0, 140.0, "bounds 15-140 per side"),
    (("stray_capacitance_f",), 2e-12, 40e-12, "bounds 2-40 pF"),
]
# pd (p. 5): mV/ub into 1000 ohm = 10 x mV/Pa
SPEC_MV_PA = {"omni": 4.5, "cardioid": 6.0, "figure8": 8.0}
CORRECTION = REPO_ROOT / "reports" / "mics" / "kk49_correction.json"
PATTERNS = {"omni": 0, "cardioid": 4, "figure8": 8}


def _rows():
    with open(DATA_DIR / "datasheets" / "neumann_m49_response.csv", encoding="utf-8") as f:
        return [
            {
                "pattern": r["pattern"],
                "angle_deg": float(r["angle_deg"]),
                "freq_hz": float(r["freq_hz"]),
                "db": float(r["db_re_1k"]),
                "quality": "read",
            }
            for r in csv.DictReader(f)
        ]


def fit(geom0, e0, rows):
    """fit_ck12.fit with the K 47's starts (its NETWORK has no gap: the through resistance is
    index 1)."""
    free = NETWORK
    freqs = [r["freq_hz"] for r in rows] + [1000.0]
    ent = base.Entries(geom0, freqs, [0.0, np.pi / 2, np.pi])
    lo = np.log([f[1] for f in free])
    hi = np.log([f[2] for f in free])
    best = None
    for t in (20.0, 45.0):
        for rt in (1e7, 1e8):
            x0 = np.log([base._get(geom0, f[0]) for f in free])
            x0[0], x0[1] = np.log(t), np.log(rt)
            sol = least_squares(
                base.residuals, np.clip(x0, lo + 1e-9, hi - 1e-9), bounds=(lo, hi),
                args=(geom0, free, ent, e0, rows), x_scale="jac", max_nfev=200,
            )  # fmt: skip
            if best is None or sol.cost < best.cost:
                best = sol
    g = base._with(geom0, free, best.x)
    result = base.summary(g, free, ent, e0, rows)
    result["rms_weighted_db"] = round(float(np.sqrt(np.mean(best.fun**2))), 2)
    return g, result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--correction", action="store_true", help="re-measure the circuit's part")
    args = ap.parse_args()
    # fit_k67's correction and residual wrappers, pointed at the M 49 c
    fit_k67.CORRECTION = CORRECTION
    fit_k67.PATTERNS = PATTERNS
    fit_k67.LOAD = LOAD
    fit_k67.REAR_V = REAR_V
    fit_k67._rows = _rows
    if args.correction or not CORRECTION.exists():
        cr = _measure_correction()
    else:
        cr = json.loads(CORRECTION.read_text())
    fit_k67._with_correction(cr)
    target = {p: SPEC_MV_PA[p] * 1e-3 / cr["gain"][p] for p in SPEC_MV_PA}
    base.LOAD = LOAD
    base.REAR_V = REAR_V
    base.NETWORK = NETWORK
    base.SENSITIVITY_V_PA = target["cardioid"]
    fit_k67._residuals_per_pattern(target)
    fit_k67._summary_skipping_empty()
    base.FITTED = (("omni", 0), ("cardioid", 0), ("figure8", 0), ("cardioid", 180))
    base._rows = _rows
    base.load_curves = lambda: [r for r in _rows() if r["freq_hz"] >= base.F_MIN_HZ]
    entry = yaml.safe_load(base.PUBLISHED.read_text(encoding="utf-8"))["KK49"]
    geom0 = _plain(entry["geometry"])
    e0 = entry["polarization_v"]
    rows = base.load_curves()
    g, result = fit(geom0, e0, rows)
    result["target_mv_pa_at_electrode"] = {p: round(1e3 * v, 3) for p, v in target.items()}
    print(json.dumps(result, indent=1))
    out_dir = REPO_ROOT / "reports" / "mics"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "kk49_fit.json").write_text(json.dumps({"best": result}, indent=1))
    ck12_png = out_dir / "ck12_fit.png"  # fit_ck12's _plot writes there: keep the C12's
    kept = ck12_png.read_bytes() if ck12_png.exists() else None
    base._plot(g, e0)
    ck12_png.replace(out_dir / "kk49_fit.png")
    if kept is not None:
        ck12_png.write_bytes(kept)
    if args.write:
        lines = base.PUBLISHED.read_text(encoding="utf-8").split("\n")
        start = lines.index('"KK49":')
        for path, *_rest, tag in NETWORK:
            key = f"{path[-1]}: {{value:"
            hits = [i for i, ln in enumerate(lines) if i > start and tag in ln and key in ln]
            if not hits:
                raise SystemExit(f"published_points.yaml: no line for {path} ({tag})")
            i = hits[0]
            head, rest = lines[i].split("{value:", 1)
            val = base._yaml_float(base._get(g, path))
            lines[i] = f"{head}{{value: {val}}}" + rest.split("}", 1)[1]
        base.PUBLISHED.write_text("\n".join(lines), encoding="utf-8")
        print("written; run: uv run varimu fit-devices --only KK49")


def _measure_correction() -> dict:
    """fit_k67.measure_correction on the M 49 c (its circuit file and pattern positions)."""
    from varimu.circuit import builder, spec
    from varimu.config import CONFIG_DIR
    from varimu.devices.library import component_data
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    u = spec.load_circuit(CONFIG_DIR / "circuits" / f"{CIRCUIT}.yaml")
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st.sample_rate
    n = int(fs)  # 1 s: tones on whole cycles of 1 Hz
    t = np.arange(2 * n) / fs
    freqs = np.unique(np.round(np.geomspace(30.0, 20000.0, 48)))
    freqs = np.unique(np.r_[freqs, 1000.0])
    rng = np.random.default_rng(49)
    amp = 0.01
    phases = rng.uniform(0, 2 * np.pi, len(freqs))
    p = sum(amp * np.sin(2 * np.pi * f * t + ph) for f, ph in zip(freqs, phases, strict=True))
    res = spec.resolve(u)
    g = component_data(res["capsule_model"])["geometry"]
    e0 = res["pol_front_v"]
    front, rear, _ = capsule_entry_pressures(g, p, 0.0, fs)
    ent = base.Entries(g, list(freqs), [0.0])
    c = base.capsule_of(g)
    out = {"freq_hz": freqs.tolist(), "capsule": res["capsule_model"], "gain": {}}
    for key, pat in PATTERNS.items():
        ir = builder.build(u, {"pattern": pat}).ir
        v = fast.run_transient(ir, front, settings=st, controls={"p_rear": rear}).vectors
        y = np.asarray(v["v(out)"])[-n:]
        sp = np.fft.rfft(y) * 2 / n
        mic = np.array([abs(sp[int(f)]) for f in freqs]) / amp
        cap = np.abs(
            base.backplate_response(c, freqs, ent(freqs, 0.0), e0, REAR_V[key] * e0 / 60.0, **LOAD)
        )
        i1k = int(np.argmin(abs(freqs - 1000.0)))
        corr = 20 * np.log10(mic / cap)
        out[key] = (corr - corr[i1k]).tolist()
        out["gain"][key] = float(mic[i1k] / cap[i1k])
        print(
            key, "mV/Pa", round(1e3 * mic[i1k], 2), "gain", round(out["gain"][key], 3), flush=True
        )
    CORRECTION.parent.mkdir(parents=True, exist_ok=True)
    CORRECTION.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()

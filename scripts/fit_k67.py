"""Fit the K 67 capsule's provisional network to Neumann's U 67 curves (CHAINS_PLAN.md WP28).

    uv run --extra fast python scripts/fit_k67.py [--correction] [--write]

scripts/fit_ck12.py's machinery (the capsule-only network into a grid load, on the capsule's
body, patterns by the rear's polarization) with the K 67's data: the on-axis responses and the
cardioid's 180 deg (data/datasheets/neumann_u67_response.csv, digitized from the 1966 sheets'
p. 7) and the sheets' sensitivities at the output into 1000 ohm (1.1 / 2.0 / 1.4 mV/ub omni /
cardioid / figure-8). The U 67's amplifier is in the capsule's loop (the feedback winding drives
the backplate), so the circuit's part is measured as a correction per pattern: the whole
microphone (config/circuits/neumann_u67.yaml, the capsule it pins) over the capsule-only model
(same geometry) into LOAD, on axis, by a multitone; its 1 kHz ratio is the pattern's amplifier
gain (the sensitivity at the electrode = the sheet's over it). `--correction` re-measures it
(reports/mics/k67_correction.json). The K 67 is the K 87's form (the same 34 mm dual-diaphragm
capsule): its geometry starts from published_points.yaml's "K67" (K87@2's), the gap and the
backplate (50 pF a side: spec) not fitted.

`--write` puts the fitted values into published_points.yaml's "K67" geometry; `varimu
fit-devices --only K67` then makes the component version. Plots -> reports/mics/k67_fit.png,
the table -> reports/mics/k67_fit.json.
"""

from __future__ import annotations

import argparse
import csv
import json

import fit_ck12 as base
import numpy as np
import yaml

from varimu.config import DATA_DIR, REPO_ROOT
from varimu.devices.library import _plain

# The grid's load: R8 500M (to C7, AC ground) and the EF 86's input as a triode (the loop's
# measured correction carries the rest).
LOAD = {"r_load_ohm": 500e6, "c_load_f": 100e-12}
# fit_ck12 scales these by e0 / 60: the circuit's rear polarizations over the front's 60.7 V
REAR_V = {"omni": 60.0, "cardioid": 0.0, "figure8": -60.0 * 61.0 / 60.7}
NETWORK = [
    (("diaphragm", "tension_n_m"), 5.0, 150.0, "bounds 5-150 N/m"),
    (("through_resistance_pa_s_m3",), 1e6, 3e9, "bounds 1e6-3e9"),
    (("film_resistance_pa_s_m3",), 1e4, 3e7, "bounds 1e4-3e7"),
    (("backplate", "blind", "depth_m"), 0.3e-3, 1.9e-3, "bounds 0.3-1.9 mm"),
    (("backplate", "blind", "holes"), 10.0, 250.0, "bounds 10-250 per side"),
    (("stray_capacitance_f",), 2e-12, 40e-12, "bounds 2-40 pF"),
]
# spec (1966, p. 5): mV/ub across 1000 ohm = 10 x mV/Pa
SPEC_MV_PA = {"omni": 11.0, "cardioid": 20.0, "figure8": 14.0}
CORRECTION = REPO_ROOT / "reports" / "mics" / "k67_correction.json"
PATTERNS = {"omni": 0, "cardioid": 1, "figure8": 2}


def _rows():
    with open(DATA_DIR / "datasheets" / "neumann_u67_response.csv", encoding="utf-8") as f:
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


def measure_correction() -> dict:
    """The whole microphone over the capsule-only model, per pattern, on axis (dB re 1 kHz),
    and each pattern's 1 kHz gain (output V over the model's electrode V)."""
    from varimu.circuit import builder, spec
    from varimu.config import CONFIG_DIR
    from varimu.devices.library import component_data
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    u = spec.load_circuit(CONFIG_DIR / "circuits" / "neumann_u67.yaml")
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st.sample_rate
    n = int(fs)  # 1 s: tones on whole cycles of 1 Hz
    t = np.arange(2 * n) / fs
    freqs = np.unique(np.round(np.geomspace(40.0, 20000.0, 48)))
    freqs = np.unique(np.r_[freqs, 1000.0])
    rng = np.random.default_rng(67)
    amp = 0.01
    phases = rng.uniform(0, 2 * np.pi, len(freqs))
    p = sum(amp * np.sin(2 * np.pi * f * t + ph) for f, ph in zip(freqs, phases, strict=True))
    ref = component_data(spec.resolve(u)["capsule_model"])
    g = ref["geometry"]
    e0 = spec.resolve(u)["pol_front_v"]
    front, rear, _ = capsule_entry_pressures(g, p, 0.0, fs)
    ent = base.Entries(g, list(freqs), [0.0])
    c = base.capsule_of(g)
    out = {"freq_hz": freqs.tolist(), "capsule": spec.resolve(u)["capsule_model"], "gain": {}}
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


def _with_correction(cr: dict):
    f0 = np.log10(cr["freq_hz"])
    orig = base._curve_db

    def curve_db(h, pat, ang, f):
        return orig(h, pat, ang, f) + np.interp(np.log10(np.atleast_1d(f)), f0, cr[pat])

    base._curve_db = curve_db


def _residuals_per_pattern(target_v_pa: dict):
    orig = base.residuals

    def residuals(x, geom0, free, ent, e0, rows):
        r = orig(x, geom0, free, ent, e0, rows)
        g = base._with(geom0, free, x)
        c = base.capsule_of(g)
        if c.c_diaphragm_at(e0) <= 0:
            return r
        h = base._h(c, ent, e0)
        sens = [
            1.5 * 20 * np.log10(abs(h([1000.0], 0.0, p)[0]) / target_v_pa[p])
            for p in ("cardioid", "omni", "figure8")
        ]
        return np.r_[r[:-3], sens]

    base.residuals = residuals


def _summary_skipping_empty():
    """fit_ck12's summary over the curves this sheet has (no figure-8 at 90 deg)."""
    orig = base.summary

    def summary(g, free, ent, e0, rows):
        have = {(r["pattern"], r["angle_deg"]) for r in rows}
        if ("figure8", 90.0) in have:
            return orig(g, free, ent, e0, rows)
        stub = [
            {**r, "pattern": "figure8", "angle_deg": 90.0}
            for r in rows
            if r["pattern"] == "figure8" and r["angle_deg"] == 0.0
        ]
        out = orig(g, free, ent, e0, rows + stub)
        return {k: v for k, v in out.items() if not k.startswith("figure8_90")}

    base.summary = summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--correction", action="store_true", help="re-measure the circuit's part")
    args = ap.parse_args()
    cr = (
        measure_correction()
        if args.correction or not CORRECTION.exists()
        else json.loads(CORRECTION.read_text())
    )
    _with_correction(cr)
    target = {p: SPEC_MV_PA[p] * 1e-3 / cr["gain"][p] for p in SPEC_MV_PA}
    base.LOAD = LOAD
    base.REAR_V = REAR_V
    base.NETWORK = NETWORK
    base.SENSITIVITY_V_PA = target["cardioid"]
    _residuals_per_pattern(target)
    _summary_skipping_empty()
    base.FITTED = (("omni", 0), ("cardioid", 0), ("figure8", 0), ("cardioid", 180))
    base._rows = _rows
    base.load_curves = lambda: [r for r in _rows() if r["freq_hz"] >= base.F_MIN_HZ]
    entry = yaml.safe_load(base.PUBLISHED.read_text(encoding="utf-8"))["K67"]
    geom0 = _plain(entry["geometry"])
    e0 = entry["polarization_v"]
    rows = base.load_curves()
    g, result, _ = base.fit(geom0, e0, rows)
    result["target_mv_pa_at_electrode"] = {p: round(1e3 * v, 3) for p, v in target.items()}
    print(json.dumps(result, indent=1))
    out_dir = REPO_ROOT / "reports" / "mics"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "k67_fit.json").write_text(json.dumps({"best": result}, indent=1))
    ck12_png = out_dir / "ck12_fit.png"  # fit_ck12's _plot writes there: keep the C12's
    kept = ck12_png.read_bytes() if ck12_png.exists() else None
    base._plot(g, e0)
    ck12_png.replace(out_dir / "k67_fit.png")
    if kept is not None:
        ck12_png.write_bytes(kept)
    if args.write:
        lines = base.PUBLISHED.read_text(encoding="utf-8").split("\n")
        start = lines.index('"K67":')
        for path, *_rest in NETWORK:
            tag = next(f[3] for f in NETWORK if f[0] == path)
            key = f"{path[-1]}: {{value:"
            hits = [i for i, ln in enumerate(lines) if i > start and tag in ln and key in ln]
            if not hits:
                raise SystemExit(f"published_points.yaml: no line for {path} ({tag})")
            i = hits[0]
            head, rest = lines[i].split("{value:", 1)
            val = base._yaml_float(base._get(g, path))
            lines[i] = f"{head}{{value: {val}}}" + rest.split("}", 1)[1]
        base.PUBLISHED.write_text("\n".join(lines), encoding="utf-8")
        print("written; run: uv run varimu fit-devices --only K67")


if __name__ == "__main__":
    main()

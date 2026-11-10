"""Fit the K87 capsule's provisional network to Neumann's U 87 i curves (CHAINS_PLAN.md WP22).

    uv run python scripts/fit_k87.py [--write] [--target-mv-pa X]

scripts/fit_ck12.py's machinery (the capsule-only network into its backplate load, on the
capsule's body, patterns by the rear's polarization) with the K87's data: the on-axis responses
(data/datasheets/neumann_u87_response.csv, digitized from copi0042 p. 10), the cardioid's polar
points read from p. 11 (below, quality coarse) and the sensitivity at the backplate that gives
the catalog's 8 mV/Pa at the output (the U 87's backplate-to-output gain measured in
config/circuits/neumann_u87.yaml: AMP_GAIN). The gap is the published 40 um spacer, not fitted.

`--write` puts the fitted values into data/datasheets/published_points.yaml's "K87" geometry;
`varimu fit-devices --only K87` then makes the component version. Plots ->
reports/mics/k87_fit.png, the table -> reports/mics/k87_fit.json.
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

# The backplate's load in the U 87 (config/circuits/neumann_u87.yaml): R6 || R7 (1 GOhm each, R7
# through C4) and C4 470p in series with the gate's input (the FET's Cgs and Miller Cgd: the
# gate 0.722 of the backplate in the circuit at 1 kHz, so ~181 pF): ~131 pF.
LOAD = {"r_load_ohm": 0.5e9, "c_load_f": 131e-12}
# The backplate-to-output gain into 1000 ohm, measured in the circuit (2026-11-10, Ue1 at
# 0.214, K87 at 50 pF a side): 3.503 at 1 kHz (cardioid, a plane wave on axis; 3.469 with the
# feedback on: it acts at the backplate, not in this gain).
AMP_GAIN = 3.503
# fit_ck12 scales these by e0 / 60: the rear at +e0 (omni), 0, -e0 (figure-8)
REAR_V = {"omni": 60.0, "cardioid": 0.0, "figure8": -60.0}
NETWORK = [
    (("diaphragm", "tension_n_m"), 5.0, 150.0, "bounds 5-150 N/m"),
    (("through_resistance_pa_s_m3",), 1e6, 3e9, "bounds 1e6-3e9"),
    (("film_resistance_pa_s_m3",), 1e4, 3e7, "bounds 1e4-3e7"),
    (("backplate", "blind", "depth_m"), 0.3e-3, 1.9e-3, "bounds 0.3-1.9 mm"),
    (("backplate", "blind", "holes"), 10.0, 250.0, "bounds 10-250 per side"),
    (("stray_capacitance_f",), 2e-12, 40e-12, "bounds 2-40 pF"),
]
# copi0042 p. 11, the cardioid's polar, read on a 300 dpi render (0 dB at r 228 px, 9.1 px/dB):
# 90 deg at 125 Hz / 1 / 4 / 12.5 kHz, 180 deg at 1 kHz (the rear lobe's floor).
POLAR = [
    ("cardioid", 90.0, 125.0, -3.5),
    ("cardioid", 90.0, 1000.0, -3.1),
    ("cardioid", 90.0, 4000.0, -4.5),
    ("cardioid", 90.0, 12500.0, -15.7),
    ("cardioid", 180.0, 1000.0, -20.0),
    ("figure8", 90.0, 1000.0, -25.0),  # the side null (reported, not fitted)
]


def _rows():
    with open(DATA_DIR / "datasheets" / "neumann_u87_response.csv", encoding="utf-8") as f:
        rows = [
            {
                "pattern": r["pattern"],
                "angle_deg": 0.0,
                "freq_hz": float(r["freq_hz"]),
                "db": float(r["db_re_1k"]),
                "quality": "read",
            }
            for r in csv.DictReader(f)
        ]
    rows += [
        {"pattern": p, "angle_deg": a, "freq_hz": f, "db": d, "quality": "coarse"}
        for p, a, f, d in POLAR
    ]
    return rows


FEEDBACK = REPO_ROOT / "reports" / "mics" / "k87_feedback.json"
FB_OFF = {"r8_ohm": 1e15, "c6_f": 1e-18, "c3_f": 1e-18}


def measure_feedback() -> dict:
    """The U 87's feedback (C3 into the backplates, R8 || C6 onto the diaphragms) as a correction
    per pattern: the output with it over the output without it, on axis, by a multitone through
    the whole circuit (the capsule as config/circuits/neumann_u87.yaml pins it)."""
    from varimu.circuit import builder, spec
    from varimu.config import CONFIG_DIR
    from varimu.devices.library import component_data
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    u = spec.load_circuit(CONFIG_DIR / "circuits" / "neumann_u87.yaml")
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st.sample_rate
    n = int(fs)  # 1 s: tones on whole cycles of 1 Hz
    t = np.arange(2 * n) / fs
    freqs = np.unique(np.round(np.geomspace(40.0, 20000.0, 48)))
    rng = np.random.default_rng(87)
    p = sum(0.02 * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) for f in freqs)
    g = component_data(spec.resolve(u)["capsule_model"])["geometry"]
    front, rear, _ = capsule_entry_pressures(g, p, 0.0, fs)
    out = {"freq_hz": freqs.tolist()}
    for pat, key in ((0, "omni"), (1, "cardioid"), (2, "figure8")):
        amps = []
        for over in ({}, FB_OFF):
            ir = builder.build(u, {"pattern": pat, **over}).ir
            v = fast.run_transient(ir, front, settings=st, controls={"p_rear": rear}).vectors
            y = np.asarray(v["v(out)"])[-n:]
            sp = np.fft.rfft(y)
            amps.append(np.array([sp[int(f)] for f in freqs]))
        out[key] = (20 * np.log10(np.abs(amps[0] / amps[1]))).tolist()
        print(key, "feedback at 1 kHz", round(float(np.interp(1000, freqs, out[key])), 2), "dB")
    FEEDBACK.write_text(json.dumps(out, indent=1))
    return out


def _with_feedback(fb: dict):
    """fit_ck12's _curve_db with the circuit's feedback correction added (re its 1 kHz)."""
    f0 = np.log10(fb["freq_hz"])

    def corr(pat, f):
        c = np.interp(np.log10(np.atleast_1d(f)), f0, fb[pat])
        return c - np.interp(3.0, f0, fb[pat])

    orig = base._curve_db

    def curve_db(h, pat, ang, f):
        return orig(h, pat, ang, f) + corr(pat, f)

    base._curve_db = curve_db


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--target-mv-pa", type=float, default=8.0, help="at the output")
    ap.add_argument("--feedback", action="store_true", help="re-measure the circuit's feedback")
    args = ap.parse_args()
    fb = (
        measure_feedback()
        if args.feedback or not FEEDBACK.exists()
        else json.loads(FEEDBACK.read_text())
    )
    _with_feedback(fb)
    # The sensitivity at the backplate with the feedback's 1 kHz loss made up (the cardioid's).
    fb_1k_db = float(np.interp(3.0, np.log10(fb["freq_hz"]), fb["cardioid"]))
    base.LOAD = LOAD
    base.REAR_V = REAR_V
    base.NETWORK = NETWORK
    base.SENSITIVITY_V_PA = args.target_mv_pa * 1e-3 / AMP_GAIN / 10 ** (fb_1k_db / 20)
    base.FITTED = (
        ("omni", 0),
        ("cardioid", 0),
        ("figure8", 0),
        ("cardioid", 90),
        ("cardioid", 180),
    )
    base._rows = _rows
    base.load_curves = lambda: [r for r in _rows() if r["freq_hz"] >= base.F_MIN_HZ]
    entry = yaml.safe_load(base.PUBLISHED.read_text(encoding="utf-8"))["K87"]
    geom0 = _plain(entry["geometry"])
    e0 = entry["polarization_v"]
    rows = base.load_curves()
    g, result, _ = base.fit(geom0, e0, rows)
    print(json.dumps(result, indent=1))
    out_dir = REPO_ROOT / "reports" / "mics"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "k87_fit.json").write_text(json.dumps({"best": result}, indent=1))
    ck12_png = out_dir / "ck12_fit.png"  # fit_ck12's _plot writes there: keep the C12's
    kept = ck12_png.read_bytes() if ck12_png.exists() else None
    base._plot(g, e0)
    ck12_png.replace(out_dir / "k87_fit.png")
    if kept is not None:
        ck12_png.write_bytes(kept)
    if args.write:
        lines = base.PUBLISHED.read_text(encoding="utf-8").split("\n")
        start = lines.index('"K87":')
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
        print("written; run: uv run varimu fit-devices --only K87")


if __name__ == "__main__":
    main()

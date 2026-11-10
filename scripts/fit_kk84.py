"""Fit the KK 84 capsule's provisional network to Neumann's KM 84 i figures (CHAINS_PLAN.md WP24).

    uv run --extra fast python scripts/fit_kk84.py [--write] [--feedback]

scripts/fit_ck12.py's machinery (the dual-diaphragm form at the cardioid setting, into the
capsule node's load, on the capsule's body) with the KM 84 i's data: the on-axis response read
from the operating instructions' chart (KM84-manual.pdf p. 16, by eye on a 300 dpi render, the
scan's 1.3% tilt taken out: below), the text's 135 deg figure (~14 dB down from 100 Hz to 18
kHz, "almost parallel": RecordingHacks quoting Neumann) and the catalog's 5 mV/Pa at the output, the
circuit's C2 3p3 feedback (config/circuits/neumann_km84.yaml) measured as a correction, as
scripts/fit_k87.py does the U 87's.

`--write` puts the fitted values into published_points.yaml's "KK84"; `varimu fit-devices --only
KK84` then makes the component version. Plots -> reports/mics/kk84_fit.png, the table ->
reports/mics/kk84_fit.json, the feedback -> reports/mics/kk84_feedback.json.
"""

from __future__ import annotations

import argparse
import json

import fit_ck12 as base
import numpy as np
import yaml

from varimu.config import REPO_ROOT
from varimu.devices.library import _plain

# The capsule node's load in the KM 84: R1 || R2 (1 GOhm each) and C1 470p in series with the
# gate's input (the gate 0.710 of the node in the circuit at 1 kHz: ~192 pF): ~136 pF.
LOAD = {"r_load_ohm": 0.5e9, "c_load_f": 136e-12}
# The node-to-output gain into 1000 ohm, measured in the circuit (2026-11-10, Bv. 107 at 0.171,
# C2 removed): 3.004 at 1 kHz.
AMP_GAIN = 3.004
REAR_V = {"cardioid": 0.0}
# cat (cata0120, the 1970s, the drawing's era): the KM 84 ~0.5 mV/ubar at the output (the KM 84 i
# of the later manual: 10 mV/Pa).
SENSITIVITY_V_PA = 5e-3
NETWORK = [
    (("diaphragm", "tension_n_m"), 5.0, 200.0, "bounds 5-200 N/m"),
    (("through_resistance_pa_s_m3",), 1e6, 1e10, "bounds 1e6-1e10"),
    (("film_resistance_pa_s_m3",), 1e5, 1e9, "bounds 1e5-1e9"),
    (("backplate", "blind", "depth_m"), 0.2e-3, 1.5e-3, "bounds 0.2-1.5 mm"),
    (("backplate", "blind", "holes"), 5.0, 150.0, "bounds 5-150 per side"),
    (("stray_capacitance_f",), 1e-12, 20e-12, "bounds 1-20 pF"),
]
# man p. 16 (KM 84 i), re 1 kHz, read by eye: (Hz, dB).
ON_AXIS = [
    (40.0, -1.8), (50.0, -1.4), (100.0, -0.25), (200.0, 0.33), (500.0, 0.26), (1000.0, 0.0),
    (2000.0, -0.14), (5000.0, -0.33), (10000.0, -0.36), (15000.0, -0.5), (20000.0, -1.0),
]  # fmt: skip
REAR_135 = [(100.0, -14.0), (1000.0, -14.0), (10000.0, -14.0)]
FEEDBACK = REPO_ROOT / "reports" / "mics" / "kk84_feedback.json"


def _rows():
    rows = [
        {"pattern": "cardioid", "angle_deg": 0.0, "freq_hz": f, "db": d, "quality": "read"}
        for f, d in ON_AXIS
    ]
    rows += [
        {"pattern": "cardioid", "angle_deg": 135.0, "freq_hz": f, "db": d, "quality": "coarse"}
        for f, d in REAR_135
    ]
    return rows


def measure_feedback() -> dict:
    """C2's feedback as a correction: the output with it over the output without it, on axis."""
    from varimu.circuit import builder, spec
    from varimu.config import CONFIG_DIR
    from varimu.devices.library import component_data
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    u = spec.load_circuit(CONFIG_DIR / "circuits" / "neumann_km84.yaml")
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st.sample_rate
    n = int(fs)
    t = np.arange(2 * n) / fs
    freqs = np.unique(np.round(np.geomspace(40.0, 20000.0, 48)))
    rng = np.random.default_rng(84)
    p = sum(0.02 * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) for f in freqs)
    g = component_data(spec.resolve(u)["capsule_model"])["geometry"]
    front, rear, _ = capsule_entry_pressures(g, p, 0.0, fs)
    amps = []
    for over in ({}, {"c2_f": 1e-18}):
        v = fast.run_transient(
            builder.build(u, over).ir, front, settings=st, controls={"p_rear": rear}
        ).vectors
        sp = np.fft.rfft(np.asarray(v["v(out)"])[-n:])
        amps.append(np.array([sp[int(f)] for f in freqs]))
    out = {
        "freq_hz": freqs.tolist(),
        "cardioid": (20 * np.log10(np.abs(amps[0] / amps[1]))).tolist(),
    }
    FEEDBACK.write_text(json.dumps(out, indent=1))
    print(
        "feedback at 1 kHz", round(float(np.interp(3.0, np.log10(freqs), out["cardioid"])), 2), "dB"
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--feedback", action="store_true", help="re-measure the circuit's feedback")
    args = ap.parse_args()
    fb = (
        measure_feedback()
        if args.feedback or not FEEDBACK.exists()
        else json.loads(FEEDBACK.read_text())
    )
    f0 = np.log10(fb["freq_hz"])
    fb_1k = float(np.interp(3.0, f0, fb["cardioid"]))
    orig = base._curve_db

    def curve_db(h, pat, ang, f):
        c = np.interp(np.log10(np.atleast_1d(f)), f0, fb[pat]) - fb_1k
        return orig(h, pat, ang, f) + c

    base._curve_db = curve_db
    base.LOAD, base.REAR_V, base.NETWORK = LOAD, REAR_V, NETWORK
    base.SENSITIVITY_V_PA = SENSITIVITY_V_PA / AMP_GAIN / 10 ** (fb_1k / 20)
    base.FITTED = (("cardioid", 0), ("cardioid", 135))
    base._rows = _rows
    base.load_curves = _rows

    def residuals(x, geom0, free, ent, e0, rows):
        g = base._with(geom0, free, x)
        c = base.capsule_of(g)
        if c.c_diaphragm_at(e0) <= 0:
            return np.full(len(rows) + 1, 50.0)
        h = base._h(c, ent, e0)
        out = []
        for pat, ang in base.FITTED:
            pts = [r for r in rows if r["pattern"] == pat and r["angle_deg"] == ang]
            f = np.array([r["freq_hz"] for r in pts])
            w = 1.0 if ang == 0 else 0.5
            out.append(w * (base._curve_db(h, pat, ang, f) - [r["db"] for r in pts]))
        s = abs(h([1000.0], 0.0, "cardioid")[0])
        out.append(np.array([1.5 * 20 * np.log10(s / base.SENSITIVITY_V_PA)]))
        return np.concatenate(out)

    def summary(g, free, ent, e0, rows):
        c = base.capsule_of(g)
        h = base._h(c, ent, e0)
        res = {"/".join(p): float(base._get(g, p)) for p, *_ in free}
        res["mv_pa_at_node"] = round(1e3 * abs(h([1000.0], 0.0, "cardioid")[0]), 3)
        res["target_mv_pa"] = round(1e3 * base.SENSITIVITY_V_PA, 3)
        for pat, ang in base.FITTED:
            pts = [r for r in rows if r["pattern"] == pat and r["angle_deg"] == ang]
            f = np.array([r["freq_hz"] for r in pts])
            d = base._curve_db(h, pat, ang, f) - [r["db"] for r in pts]
            res[f"{pat}_{ang:g}_rms_db"] = round(float(np.sqrt(np.mean(d**2))), 2)
            res[f"{pat}_{ang:g}_max_db"] = round(float(np.max(np.abs(d))), 2)
        res["c0_pf"] = round(1e12 * c.c0_f, 1)
        return res

    base.residuals, base.summary = residuals, summary
    entries = base.Entries
    base.Entries = lambda g, f, a: entries(g, f, [*a, np.radians(135.0)])  # the 135 deg figure
    entry = yaml.safe_load(base.PUBLISHED.read_text(encoding="utf-8"))["KK84"]
    geom0 = _plain(entry["geometry"])
    e0 = entry["polarization_v"]
    g, result, _ = base.fit(geom0, e0, _rows())
    print(json.dumps(result, indent=1))
    out_dir = REPO_ROOT / "reports" / "mics"
    (out_dir / "kk84_fit.json").write_text(json.dumps({"best": result}, indent=1))
    _plot(g, e0, f0, fb, fb_1k)
    if args.write:
        lines = base.PUBLISHED.read_text(encoding="utf-8").split("\n")
        start = lines.index('"KK84":')
        for path, _lo, _hi, tag in NETWORK:
            key = f"{path[-1]}: {{value:"
            i = next(i for i, ln in enumerate(lines) if i > start and tag in ln and key in ln)
            head, rest = lines[i].split("{value:", 1)
            val = base._yaml_float(base._get(g, path))
            lines[i] = f"{head}{{value: {val}}}" + rest.split("}", 1)[1]
        base.PUBLISHED.write_text("\n".join(lines), encoding="utf-8")
        print("written; run: uv run varimu fit-devices --only KK84")


def _plot(g, e0, f0, fb, fb_1k) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from fit_k47 import Entries

    c = base.capsule_of(g)
    f = np.geomspace(20, 20000, 100)
    ent = Entries(g, [*f, 1000.0], np.radians([0, 90, 135, 180]))
    h = base._h(c, ent, e0)
    fig, ax = plt.subplots(figsize=(8, 5))
    for a in (0, 90, 135, 180):
        ax.semilogx(f, base._curve_db(h, "cardioid", a, f), label=f"{a} deg (model, feedback in)")
    ax.plot(*zip(*ON_AXIS, strict=True), "o", label="KM 84 i on axis (Neumann)")
    ax.plot(*zip(*REAR_135, strict=True), "s", label="135 deg (Neumann's text)")
    ax.set_ylim(-35, 10)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7)
    ax.set_title("KK 84 fit, re 1 kHz on axis")
    fig.savefig(REPO_ROOT / "reports" / "mics" / "kk84_fit.png", dpi=100)
    plt.close(fig)


if __name__ == "__main__":
    main()

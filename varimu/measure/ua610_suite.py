"""The UA 610's profile (the chains build-out's WP2).

    report = run(name, genome)     # varimu unit --circuit ua_610 --name NAME

A unit is the circuit file with the genome's overrides. Nothing is published for the
original 610-A module (data/schematics/ua_610/README.md): the only specifications are the
2-610 reissue's (UA's manual, `ua_2610_manual_p6.png`), a different circuit (500 / 2 k
input transformer, its own output stage and supply). They are reported as `vs_2610`, a
reference, never a pass or a rejection. Conditions: a 200 ohm generator, the 600 ohm load,
levels in dB re 0.775 V (dBu); gain is the output re the generator's EMF. The tones,
spectra and level readings are the V76's (varimu.measure.preamp_suite). Sections:

- screen: an idle render (the output quiet, the module's B+ terminal within 10% of the
  console's 275 V: Hinson) and 1 kHz at +4 dB out at the nominal setting (no oscillation
  riding on it, the gain within 6 dB of NOMINAL_GAIN_DB);
- gain: 1 kHz at full LEVEL, the Hi and Lo links (the 2-610: 61 dB maximum); the LEVEL
  law at Hi (the gain at each rotation against the full gain plus the pot's taper);
- response: the multitone at +4 dB out at the nominal setting, re 1 kHz, flat and at every
  HF (-6, +3, +6) and LF (-6, +6) position (the 2-610: 20 Hz-20 kHz +-1 dB flat);
- input impedance at the terminals (the 2-610's are 500 / 2 k; the original runs the mic
  into the O-1's 50 ohm tap);
- output impedance: the multitone into 600 ohm and into 1 MOhm (the 2-610: 60 ohm);
- distortion: THD of 1 kHz against level to past clipping at the nominal setting (the
  2-610's maximum output +20 dBm, read here at 1%); 40 Hz at +4 and +12 dB out (the O-1
  and the PA-5946 at the bottom).

Not modelled: noise (the circuit has no noise block), hum, the line input.

Results: reports/units/<name>/report.json, response.png.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from varimu.circuit import parts, spec
from varimu.measure import generic
from varimu.measure import preamp_suite as pre
from varimu.sim import runner
from varimu.sim.io import TransientSettings, full_scale

CIRCUIT = "ua_610"
REPORT_DIR = pre.REPORT_DIR
MAX_JOBS: int | None = None
NOMINAL = {"level": 0.3, "gain_link": 1, "hf_eq": 0, "lf_eq": 0}  # ~40 dB at Hi
NOMINAL_GAIN_DB = 40.0
RAILS_V = {"bp": 275.0}  # the console's B+ at the module (Hinson; the drawing prints none)
LEVELS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
EQ = {
    "hf-6": {"hf_eq": -6},
    "hf+3": {"hf_eq": 3},
    "hf+6": {"hf_eq": 6},
    "lf-6": {"lf_eq": -6},
    "lf+6": {"lf_eq": 6},
}
SPEC_2610 = {
    "max_gain_db": 61.0,
    "flat_tol_db": 1.0,  # 20 Hz-20 kHz
    "z_out_ohm": 60.0,  # "internal output impedance"
    "max_out_db": 20.0,  # "+20 dBm" (read at 1% THD here)
}
RESPONSE_OUT_DB = 4.0
SWEEP_OUT_DB = (-10, 0, 4, 8, 12, 14, 16, 18, 20, 22, 24, 26, 28)
LOW_OUT_DB = (4.0, 12.0)


def _job(emf_v: np.ndarray, genome: Mapping[str, Any], ov: Mapping, label: str, s) -> Any:
    fs_v = full_scale(s, spec.load_circuit(spec.circuit_path(CIRCUIT)))[0]
    return runner.RenderJob(emf_v / fs_v, {**genome, **NOMINAL, **ov}, label, circuit=CIRCUIT)


def multitone(out_db: float, gain_db: float, fs: int) -> np.ndarray:
    """The V76's multitone (TONES at equal EMF), about out_db out in total at gain_db."""
    return pre.multitone(gain_db + pre.RESPONSE_OUT_DB - out_db, fs)


def screen(genome: Mapping[str, Any], s: TransientSettings) -> tuple[dict, dict]:
    fs = s.sample_rate
    x = pre.tone(RESPONSE_OUT_DB, NOMINAL_GAIN_DB, 1000.0, fs)
    idle, nominal = runner.render_many(
        [
            _job(np.zeros(int(1.0 * fs)), genome, {}, "idle", s),
            _job(x, genome, {}, "1k +4 dB", s),
        ],
        settings=s,
        max_jobs=MAX_JOBS,
    )
    a = int(0.05 * fs)
    lv = pre.tone_levels(nominal, x, 1000.0)
    checks = {
        "idle_quiet": generic.quiet(idle.output[a:]),
        **{f"rail_{k}": v for k, v in generic.rails(idle.vectors, RAILS_V, int(0.2 * fs)).items()},
        "nominal_no_spurs": generic.no_spurs(lv["harmonics"]),
        "nominal_gain": generic.gain(lv["gain_db"], NOMINAL_GAIN_DB),
    }
    info = {"idle_out_dbfs": checks["idle_quiet"]["value"], "nominal": pre._clean(lv)}
    return checks, info


def response_section(spectra: Mapping[str, np.ndarray]) -> dict[str, Any]:
    tones, at, lim = pre.TONES, pre.at, pre._limits
    db = {k: 20 * np.log10(np.abs(h)) for k, h in spectra.items()}
    rel = {k: d - at(d, 1000.0) for k, d in db.items()}
    band = (tones >= 20) & (tones <= 20000)
    points = (20, 50, 100, 1000, 5000, 10000, 15000, 20000)
    return {
        "tones_hz": tones.tolist(),
        "rel_db": {k: np.round(r, 3).tolist() for k, r in rel.items()},
        "at_db": {k: {f"{f:g}": round(at(r, f), 2) for f in points} for k, r in rel.items()},
        "eq_re_flat_db": {
            k: {f"{f:g}": round(at(db[k], f) - at(db["flat"], f), 2) for f in points} for k in EQ
        },
        "vs_2610": {
            "flat_20_20k": lim(
                float(np.max(np.abs(rel["flat"][band]))), None, SPEC_2610["flat_tol_db"]
            )
        },
    }


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """Screen the genome; if it passes, measure everything, write the report."""
    del clips  # no program clips yet
    t0 = time.perf_counter()
    genome = dict(genome or {})
    out_dir = REPORT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    s = settings or TransientSettings.from_sim_settings(engine="configured")
    circuit = spec.load_circuit(spec.circuit_path(CIRCUIT))
    report: dict[str, Any] = {
        "name": name,
        "circuit": CIRCUIT,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "genome": genome,
        "nominal_setting": NOMINAL,
    }
    log(f"{name}: screen")
    checks, screen_info = screen(genome, s)
    report["screen"] = screen_info
    report["checks"] = checks
    report["plausible"] = all(c["passes"] for c in checks.values())
    if not report["plausible"]:
        log(f"{name}: rejected: {[k for k, c in checks.items() if not c['passes']]}")
        _write(out_dir, report)
        return report

    fs = s.sample_rate
    g_nom = screen_info["nominal"]["gain_db"]
    jobs, inputs, keys = [], [], []

    def add(key, x, ov, label):
        keys.append(key)
        inputs.append(x)
        jobs.append(_job(x, genome, ov, label, s))

    for link in (1, 0):
        add(("max", link), pre.tone(4.0, 69.0 - 8.0 * (1 - link), 1000.0, fs),
            {"level": 1.0, "gain_link": link}, f"max gain link {link}")  # fmt: skip
    for lv in LEVELS:  # -80 dBu EMF: below clipping at every rotation
        add(("level", lv), pre.tone(-10.0, 70.0, 1000.0, fs), {"level": lv}, f"level {lv}")
    add(("resp", "flat"), multitone(RESPONSE_OUT_DB, g_nom, fs), {}, "response flat")
    for k, ov in EQ.items():
        add(("resp", k), multitone(RESPONSE_OUT_DB, g_nom, fs), ov, f"response {k}")
    add(("zout", "open"), multitone(RESPONSE_OUT_DB, g_nom, fs), {"load_ohm": 1.0e6}, "z_out open")
    for out_db in SWEEP_OUT_DB:
        add(("sweep", out_db), pre.tone(out_db, g_nom, 1000.0, fs), {}, f"sweep {out_db} dB")
    for out_db in LOW_OUT_DB:
        add(("low", out_db), pre.tone(out_db, g_nom, 40.0, fs), {}, f"40 Hz {out_db} dB")
    log(f"{name}: {len(jobs)} renders")
    renders = runner.render_many(jobs, settings=s, max_jobs=MAX_JOBS)
    got = dict(zip(keys, zip(renders, inputs, strict=True), strict=True))
    lim = pre._limits

    gmax = {link: pre._clean(pre.tone_levels(*got[("max", link)], 1000.0)) for link in (1, 0)}
    q = spec.resolve(circuit, genome)
    full = gmax[1]["gain_db"]
    law = []
    for lv in LEVELS:
        g = pre._clean(pre.tone_levels(*got[("level", lv)], 1000.0))["gain_db"]
        expect = full + 20 * np.log10(parts.taper(lv, q["r13_taper_mid"]))
        law.append({"level": lv, "gain_db": g, "full_plus_taper_db": round(float(expect), 2)})
    report["gain"] = {
        "hi_full": gmax[1],
        "lo_full": gmax[0],
        "link_step_db": round(gmax[1]["gain_db"] - gmax[0]["gain_db"], 2),
        "level_law_hi": law,
        "vs_2610": {"max_gain": lim(full, None, SPEC_2610["max_gain_db"])},
    }
    spectra = {k[1]: pre.spectrum(r, x) for k, (r, x) in got.items() if k[0] == "resp"}
    report["response"] = response_section(spectra)
    r_src = q["source_impedance_ohm"]
    h_term = pre.spectrum(*got[("resp", "flat")], node="ia")
    z_in = r_src * np.abs(h_term / (1.0 - h_term))
    tones, at = pre.TONES, pre.at
    report["input_impedance"] = {
        "z_ohm": np.round(z_in, 1).tolist(),
        "at_ohm": {f"{f:g}": round(float(np.interp(f, tones, z_in)), 1) for f in (40, 1000, 10000)},
    }
    z = pre.z_out(pre.spectrum(*got[("zout", "open")]), spectra["flat"], q["load_ohm"])
    report["output_impedance"] = {
        "z_ohm": np.round(z, 2).tolist(),
        "at_1k_ohm": round(at(z, 1000.0), 2),
        "vs_2610": {"at_1k": lim(at(z, 1000.0), None, SPEC_2610["z_out_ohm"])},
    }
    rows = [pre._clean(pre.tone_levels(*got[("sweep", lv)], 1000.0)) for lv in SWEEP_OUT_DB]
    outs, thd = np.array([r["out_db"] for r in rows]), np.array([r["thd_pct"] for r in rows])

    def level_at(pct: float) -> float | None:
        i = np.nonzero(thd >= pct)[0]
        if len(i) == 0 or i[0] == 0:
            return None
        j = i[0]
        return round(
            float(np.interp(np.log(pct), np.log(thd[j - 1 : j + 1]), outs[j - 1 : j + 1])), 2
        )

    at_1 = level_at(1.0)
    low = {f"{o:+g} dB": pre._clean(pre.tone_levels(*got[("low", o)], 40.0)) for o in LOW_OUT_DB}
    report["distortion"] = {
        "sweep_1k": {"rows": rows, "out_db_at_0p3pct": level_at(0.3), "out_db_at_1pct": at_1,
                     "out_db_at_3pct": level_at(3.0)},
        "at_40hz": low,
        "vs_2610": {"max_output_at_1pct": lim(at_1 if at_1 is not None else float(outs[-1]),
                                              SPEC_2610["max_out_db"], None)},
    }  # fmt: skip
    every = [
        *report["gain"]["vs_2610"].values(),
        *report["response"]["vs_2610"].values(),
        *report["output_impedance"]["vs_2610"].values(),
        *report["distortion"]["vs_2610"].values(),
    ]
    report["meets_2610"] = f"{sum(c['meets'] for c in every)}/{len(every)}"
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plots(out_dir, report)
    log(f"{name}: within {report['meets_2610']} of the 2-610 reissue's figures (a reference)")
    return report


def _write(out_dir: Path, report: Mapping[str, Any]) -> None:
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8"
    )


def _plots(out_dir: Path, report: Mapping[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f = np.array(report["response"]["tones_hz"])
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
    ax = axes[0, 0]
    for k, r in report["response"]["rel_db"].items():
        ax.semilogx(f, r, label=k, lw=2.0 if k == "flat" else 1.0)
    ax.axhspan(-1.0, 1.0, color="g", alpha=0.1, label="+-1 dB, 20 Hz-20 kHz (2-610)")
    ax.set_ylim(-15, 10)
    ax.set_title("Response at the nominal setting, HF / LF positions (re 1 kHz)")
    ax = axes[0, 1]
    ax.semilogx(f, report["input_impedance"]["z_ohm"], label="|Z in| at the terminals")
    ax.set_title("Input impedance")
    ax.set_ylabel("ohm")
    ax = axes[1, 0]
    ax.semilogx(f, report["output_impedance"]["z_ohm"], label="|Z out|")
    ax.axhline(SPEC_2610["z_out_ohm"], ls="--", c="gray", label="60 ohm (2-610)")
    ax.set_title("Output impedance")
    ax.set_ylabel("ohm")
    for a in axes.flat[:3]:
        a.set_xlim(10, 45000)
    ax = axes[1, 1]
    rows = report["distortion"]["sweep_1k"]["rows"]
    o = [r["out_db"] for r in rows]
    ax.semilogy(o, [r["thd_pct"] for r in rows], "o-", label="THD")
    ax.semilogy(o, [r["k2_pct"] for r in rows], ".--", label="k2")
    ax.semilogy(o, [r["k3_pct"] for r in rows], ".--", label="k3")
    ax.plot([SPEC_2610["max_out_db"]], [1.0], "k^", ms=9, label="+20 dBm (2-610)")
    ax.set_xlabel("output (dBu, 600 ohm)")
    ax.set_ylabel("%")
    ax.set_title("1 kHz at the nominal setting")
    for a in axes.flat:
        a.grid(True, which="both", alpha=0.3)
        a.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

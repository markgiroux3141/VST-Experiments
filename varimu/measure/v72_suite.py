"""The Telefunken V72's profile (the chains build-out's WP1).

    report = run(name, genome)     # varimu unit --circuit telefunken_v72 --name NAME

A unit is the circuit file with the genome's overrides (R20 is the factory's gain trim,
set by scripts/v72_trim.py). The Braunbuch V 72's acceptance specs ("Elektrische Daten",
sheets 3-5) and the Siemens datasheet (data/schematics/telefunken_v72/README.md) set the
conditions: a 200 ohm generator, a 300 ohm load, levels in dB re 0.775 V. The tones,
spectra and level readings are the V76's (varimu.measure.preamp_suite). Sections:

- screen: an idle render (the output quiet, the choke's rail within 10% of B+ 245 V) and
  1 kHz at +6 dB out (no oscillation riding on it, the gain within 6 dB of 34);
- gain (sheet 3, point 4): 1 kHz, +6 dB out, re the generator's EMF: 34 +-0.2 dB;
- response (sheet 4, point 5): the multitone at the specs' two input levels, -28 dB (+6 dB
  out) and -68 dB, re 1 kHz: flat +-0.3 dB 60 Hz-10 kHz, 40 Hz down 0.3-1 dB, 15 kHz down
  0-0.6 dB (the 15 Hz and 40 kHz points are dropped in the specs: reported, not checked);
- input impedance (sheet 3, point 3): >= 2 kOhm 40 Hz-15 kHz, from the terminals' voltage
  against the generator's EMF behind 200 ohm;
- distortion (sheet 4, point 6): THD at +12 dB out at 40 Hz, 1 kHz, 5 kHz (<= 0.4 / 0.1 /
  0.1 %) and at +17 dB, 1 kHz (<= 0.3%); THD of 1 kHz against level to past clipping, the
  datasheet's maximum (5.5 V into 300 ohm at 0.3%: >= +17.0 dB);
- output impedance (sheet 5, point 7): the multitone into 300 ohm and into 1 MOhm:
  <= 35 ohm, 40 Hz-15 kHz.

Checks against the specs are reported (`vs_published`), never rejecting. Not modelled:
noise (point 8: the circuit has no noise block), hum fields (9-10), insulation (11).

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

from varimu.circuit import spec
from varimu.measure import generic
from varimu.measure import preamp_suite as pre
from varimu.sim import runner
from varimu.sim.io import TransientSettings, full_scale

CIRCUIT = "telefunken_v72"
REPORT_DIR = pre.REPORT_DIR
MAX_JOBS: int | None = None
GAIN_DB = 34.0
RAILS_V = {"bp": 245.0}  # B+ on the choke's rail (CJ, GroupDIY; the drawing prints none)

SPECS = {
    "gain_tol_db": 0.2,  # point 4
    "flat_tol_db": 0.3,  # point 5: 60 Hz-10 kHz
    "at_40hz_db": (-1.0, -0.3),
    "at_15khz_db": (-0.6, 0.0),
    "z_in_min_ohm": 2000.0,  # point 3: 40 Hz-15 kHz
    "distortion": {(12, 40): 0.4, (12, 1000): 0.1, (12, 5000): 0.1, (17, 1000): 0.3},  # point 6
    "z_out_max_ohm": 35.0,  # point 7: 40 Hz-15 kHz
    "max_out_db_at_0p3pct": 17.0,  # ds: 5.5 V into 300 ohm (+17.0 dB) at 0.3%, 1 kHz
}
RESPONSE_OUT_DB = (6.0, -34.0)  # the specs' input levels -28 / -68 dB at 34 dB gain
SWEEP_OUT_DB = (-10, 0, 6, 12, 14, 16, 17, 18, 19, 20, 22, 24, 26)


def _job(emf_v: np.ndarray, genome: Mapping[str, Any], ov: Mapping, label: str, s) -> Any:
    fs_v = full_scale(s, spec.load_circuit(spec.circuit_path(CIRCUIT)))[0]
    return runner.RenderJob(emf_v / fs_v, {**genome, **ov}, label, circuit=CIRCUIT)


def multitone(out_db: float, fs: int) -> np.ndarray:
    """The V76's multitone (TONES at equal EMF), out_db out in total at 34 dB gain."""
    return pre.multitone(GAIN_DB + pre.RESPONSE_OUT_DB - out_db, fs)


def screen(genome: Mapping[str, Any], s: TransientSettings) -> tuple[dict, dict]:
    fs = s.sample_rate
    x = pre.tone(6.0, GAIN_DB, 1000.0, fs)
    idle, nominal = runner.render_many(
        [
            _job(np.zeros(int(1.0 * fs)), genome, {}, "idle", s),
            _job(x, genome, {}, "1k +6 dB", s),
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
        "nominal_gain": generic.gain(lv["gain_db"], GAIN_DB),
    }
    info = {"idle_out_dbfs": checks["idle_quiet"]["value"], "nominal": pre._clean(lv)}
    return checks, info


def response_section(spectra: Mapping[float, np.ndarray]) -> dict[str, Any]:
    tones, at, lim = pre.TONES, pre.at, pre._limits
    rel = {}
    for out_db, h in spectra.items():
        d = 20 * np.log10(np.abs(h))
        rel[out_db] = d - at(d, 1000.0)
    band = (tones >= 60) & (tones <= 10000)
    checks = {}
    for out_db, r in rel.items():
        tag = f"{out_db:+g}dB"
        checks[f"flat_60_10k_{tag}"] = lim(
            float(np.max(np.abs(r[band]))), None, SPECS["flat_tol_db"]
        )
        checks[f"at_40hz_{tag}"] = lim(at(r, 40.0), *SPECS["at_40hz_db"])
        checks[f"at_15khz_{tag}"] = lim(at(r, 15000.0), *SPECS["at_15khz_db"])
    return {
        "tones_hz": tones.tolist(),
        "rel_db": {f"{k:+g}": np.round(r, 3).tolist() for k, r in rel.items()},
        "dropped_points": {
            f"{k:+g}": {"at_15hz": round(at(r, 15.0), 2), "at_40khz": round(at(r, 40000.0), 2)}
            for k, r in rel.items()
        },  # fmt: skip
        "vs_published": checks,
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
    report: dict[str, Any] = {
        "name": name,
        "circuit": CIRCUIT,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "genome": genome,
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
    jobs, inputs, keys = [], [], []

    def add(key, x, ov, label):
        keys.append(key)
        inputs.append(x)
        jobs.append(_job(x, genome, ov, label, s))

    add(("gain",), pre.tone(6.0, GAIN_DB, 1000.0, fs), {}, "gain")
    for out_db in RESPONSE_OUT_DB:
        add(("resp", out_db), multitone(out_db, fs), {}, f"response {out_db:+g} dB")
    load = spec.resolve(spec.load_circuit(spec.circuit_path(CIRCUIT)))["load_ohm"]
    add(("zout", "open"), multitone(6.0, fs), {"load_ohm": 1.0e6}, "z_out open")
    for out_db, f in SPECS["distortion"]:
        add(
            ("dist", out_db, f),
            pre.tone(out_db, GAIN_DB, float(f), fs),
            {},
            f"k {f} Hz {out_db} dB",
        )
    for lv in SWEEP_OUT_DB:
        add(("sweep", lv), pre.tone(lv, GAIN_DB, 1000.0, fs), {}, f"sweep {lv} dB")
    log(f"{name}: {len(jobs)} renders")
    renders = runner.render_many(jobs, settings=s, max_jobs=MAX_JOBS)
    got = dict(zip(keys, zip(renders, inputs, strict=True), strict=True))
    lim = pre._limits

    g = pre._clean(pre.tone_levels(*got[("gain",)], 1000.0))
    report["gain"] = {**g, "vs_published": lim(g["gain_db"] - GAIN_DB, -SPECS["gain_tol_db"],
                                               SPECS["gain_tol_db"])}  # fmt: skip
    spectra = {k[1]: pre.spectrum(r, x) for k, (r, x) in got.items() if k[0] == "resp"}
    report["response"] = response_section(spectra)
    tones = pre.TONES
    band = (tones >= 40) & (tones <= 15000)
    r_src = spec.resolve(spec.load_circuit(spec.circuit_path(CIRCUIT)))["source_impedance_ohm"]
    h_term = pre.spectrum(*got[("resp", 6.0)], node="ia")
    z_in = r_src * np.abs(h_term / (1.0 - h_term))
    report["input_impedance"] = {
        "z_ohm": np.round(z_in, 1).tolist(),
        "vs_published": {"min_40_15k": lim(float(np.min(z_in[band])), SPECS["z_in_min_ohm"], None)},
    }
    z = pre.z_out(pre.spectrum(*got[("zout", "open")]), spectra[6.0], load)
    report["output_impedance"] = {
        "z_ohm": np.round(z, 2).tolist(),
        "vs_published": {"max_40_15k": lim(float(np.max(z[band])), None, SPECS["z_out_max_ohm"])},
    }
    dist = {}
    for (out_db, f), thd_max in SPECS["distortion"].items():
        lv = pre._clean(pre.tone_levels(*got[("dist", out_db, f)], float(f)))
        dist[f"{out_db:+d} dB, {f} Hz"] = {**lv, "thd": lim(lv["thd_pct"], None, thd_max)}
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

    at_0p3 = level_at(0.3)
    report["distortion"] = {
        "spec_points": dist,
        "sweep_1k": {"rows": rows, "out_db_at_0p3pct": at_0p3, "out_db_at_1pct": level_at(1.0),
                     "out_db_at_3pct": level_at(3.0)},
        "max_output": lim(at_0p3 if at_0p3 is not None else float(outs[-1]),
                          SPECS["max_out_db_at_0p3pct"], None),
    }  # fmt: skip
    every = [
        report["gain"]["vs_published"],
        *report["response"]["vs_published"].values(),
        *report["input_impedance"]["vs_published"].values(),
        *report["output_impedance"]["vs_published"].values(),
        *(d["thd"] for d in dist.values()),
        report["distortion"]["max_output"],
    ]
    report["meets_specs"] = f"{sum(c['meets'] for c in every)}/{len(every)}"
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plots(out_dir, report)
    log(f"{name}: meets {report['meets_specs']} of the Braunbuch's specs")
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
        ax.semilogx(f, r, label=f"{k} dB out")
    ax.axhspan(-0.3, 0.3, color="g", alpha=0.1, label="+-0.3 dB, 60 Hz-10 kHz (spec)")
    ax.plot([40, 40], [-1.0, -0.3], "k-", lw=3, label="40 Hz, 15 kHz (spec)")
    ax.plot([15000, 15000], [-0.6, 0.0], "k-", lw=3)
    ax.set_ylim(-12, 3)
    ax.set_title("Response (re 1 kHz)")
    ax = axes[0, 1]
    ax.semilogx(f, report["input_impedance"]["z_ohm"], label="|Z in|")
    ax.axhline(SPECS["z_in_min_ohm"], ls="--", c="gray", label="2 kOhm (spec, 40 Hz-15 kHz)")
    ax.set_title("Input impedance")
    ax.set_ylabel("ohm")
    ax = axes[1, 0]
    ax.semilogx(f, report["output_impedance"]["z_ohm"], label="|Z out|")
    ax.axhline(SPECS["z_out_max_ohm"], ls="--", c="gray", label="35 ohm (spec, 40 Hz-15 kHz)")
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
    ax.plot([SPECS["max_out_db_at_0p3pct"]], [0.3], "k^", ms=9, label="5.5 V at 0.3% (ds)")
    ax.set_xlabel("output (dB re 0.775 V, 300 ohm)")
    ax.set_ylabel("%")
    ax.set_title("1 kHz at 34 dB")
    for a in axes.flat:
        a.grid(True, which="both", alpha=0.3)
        a.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

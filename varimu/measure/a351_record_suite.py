"""The Ampex 351 direct monitor's profile (the chains build-out's WP7).

    report = run(name, genome)     # varimu unit --circuit ampex_351_record --name NAME

A unit is config/circuits/ampex_351_record.yaml (scripts/make_351_record.py: the machine's
microphone input and the METER AND OUTPUT switch at RECORD LEVEL, the tape stopped) with the
genome's overrides. The manual publishes three figures for this path
(data/schematics/ampex_351/README.md): the microphone input's sensitivity, "200 uV for
operating level" (man p 11; operating level read as 0 VU, +8 dBm, at full RECORD LEVEL with
RECORD CALIBRATE set), the line output's "+14 VU into 600 ohm" (man p 11: +22 dBm, read here
at 3% THD, the manual's peak record level's distortion), and the drawing's signal voltages
at the record amplifier's first two stages (sch p 95: -80, -57, -35, -12 dB re 0.78 V at 5J1,
1V1b's grid, 1V1a's grid, 1V1a's plate; at full RECORD LEVEL, 500 Hz, 4S1 at MICROPHONE).
They are `vs_published`; the response, the impedances and the distortion are reported.
Conditions: a 200 ohm generator, the 600 ohm load, dB re 0.775 V (dBu); gain is the output
re the generator's EMF. The tones, spectra and level readings are the V76's
(varimu.measure.preamp_suite). Sections:

- screen: an idle render (quiet, the rails within 10% of the drawing's 330 / 300 / 250 V:
  printed in record mode, which the manual says 3K1b keeps "nearly constant") and 1 kHz at
  +8 dB out at the nominal setting (no spurs, the gain within 6 dB of NOMINAL_GAIN_DB);
- gain: RECORD LEVEL's law (the chain list's rotations), the sensitivity at full RECORD
  LEVEL, the drawing's stage levels;
- response: the multitone at +8 dB out at the nominal setting, re 1 kHz;
- input and output impedance;
- distortion: THD of 1 kHz against output level at the nominal setting (the 1% and 3%
  levels); 40 Hz at +8 and +16 dB out (6T1 and 6T3 at the bottom); the input stage's
  overload (the EMF at which 1V1b, ahead of RECORD LEVEL, takes the chain to 1% at a
  low gain, the output stage well below its own).

Not modelled: noise, hum (the heaters), the BALANCED BRIDGE input, the 30-50 ohm strap.

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

CIRCUIT = "ampex_351_record"
REPORT_DIR = pre.REPORT_DIR
MAX_JOBS: int | None = None
NOMINAL = {"record_level": 0.1, "input_transfer": 0}  # ~58 dB: the ribbons' setting
NOMINAL_GAIN_DB = 58.4
RAILS_V = {"b330": 330.0, "b300": 300.0, "b250": 250.0}  # sch p 95
LEVELS = (0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.7, 1.0)
PUBLISHED = {
    "sensitivity_uv": 200.0,  # man p 11: microphone, 200 uV for operating level
    "sensitivity_tol_db": 2.0,
    "max_out_db": 22.0,  # man p 11: +14 VU into 600 ohm over 0 VU = +8 dBm
    # sch p 95: dB re 0.78 V at 500 Hz, full RECORD LEVEL, -80 dB at 5J1
    "stages_db": {"g1b": -57.0, "g1a": -35.0, "p1a": -12.0},
    "stage_tol_db": 2.0,
}
OPERATING_OUT_DB = float(20 * np.log10(1.9494 / 0.775))  # +8 dBm into 600 ohm, in dBu
RESPONSE_OUT_DB = 8.0
SWEEP_OUT_DB = (-10, 0, 8, 12, 16, 18, 20, 22, 24, 26, 28, 30, 32)
LOW_OUT_DB = (8.0, 16.0)
#: The input stage's overload: EMFs (dBu) at RECORD LEVEL OVERLOAD_LEVEL (~32 dB of gain:
#: the output stays near +8 dB, its own THD ~0.2%), 1V1b clipping first.
OVERLOAD_LEVEL = 0.005
OVERLOAD_EMF_DB = (-40, -34, -30, -27, -24, -21, -18, -15, -12)


def _job(emf_v: np.ndarray, genome: Mapping[str, Any], ov: Mapping, label: str, s) -> Any:
    fs_v = full_scale(s, spec.load_circuit(spec.circuit_path(CIRCUIT)))[0]
    return runner.RenderJob(emf_v / fs_v, {**genome, **NOMINAL, **ov}, label, circuit=CIRCUIT)


def multitone(out_db: float, gain_db: float, fs: int) -> np.ndarray:
    return pre.multitone(gain_db + pre.RESPONSE_OUT_DB - out_db, fs)


def _node_db(render: runner.Render, node: str, f_hz: float) -> float:
    from varimu.measure import metrics

    n = int(pre.DIST_MEASURE_S * render.sample_rate)
    h = metrics.harmonics(render.vectors[f"v({node})"][-n:], f_hz, render.sample_rate)
    return float(20 * np.log10(h.amps[0] / np.sqrt(2) / 0.775))


def screen(genome: Mapping[str, Any], s: TransientSettings) -> tuple[dict, dict]:
    fs = s.sample_rate
    x = pre.tone(RESPONSE_OUT_DB, NOMINAL_GAIN_DB, 1000.0, fs)
    idle, nominal = runner.render_many(
        [_job(np.zeros(int(1.0 * fs)), genome, {}, "idle", s), _job(x, genome, {}, "1k +8", s)],
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


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """Screen the genome; if it passes, measure everything, write the report."""
    del clips
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

    for lv in LEVELS:  # -90 dBu EMF: below clipping at every rotation
        add(("level", lv), pre.tone(-10.0, 80.0, 1000.0, fs), {"record_level": lv}, f"level {lv}")
    # The drawing's conditions: -80 dB at 5J1, 500 Hz, full RECORD LEVEL.
    add(("stages",), pre.tone(-80.0, 0.0, 500.0, fs), {"record_level": 1.0}, "stages")
    add(("resp",), multitone(RESPONSE_OUT_DB, g_nom, fs), {}, "response")
    add(("zout",), multitone(RESPONSE_OUT_DB, g_nom, fs), {"r_load_ohm": 1.0e6}, "z_out open")
    for out_db in SWEEP_OUT_DB:
        add(("sweep", out_db), pre.tone(out_db, g_nom, 1000.0, fs), {}, f"sweep {out_db} dB")
    for out_db in LOW_OUT_DB:
        add(("low", out_db), pre.tone(out_db, g_nom, 40.0, fs), {}, f"40 Hz {out_db} dB")
    for e in OVERLOAD_EMF_DB:
        add(
            ("over", e),
            pre.tone(e, 0.0, 1000.0, fs),
            {"record_level": OVERLOAD_LEVEL},
            f"overload {e}",
        )
    log(f"{name}: {len(jobs)} renders")
    renders = runner.render_many(jobs, settings=s, max_jobs=MAX_JOBS)
    got = dict(zip(keys, zip(renders, inputs, strict=True), strict=True))
    lim = pre._limits
    q = spec.resolve(circuit, genome)

    law = [{"record_level": lv, "gain_db": pre._clean(pre.tone_levels(*got[("level", lv)],
            1000.0))["gain_db"]} for lv in LEVELS]  # fmt: skip
    full = law[-1]["gain_db"]
    sens_uv = 1e6 * 0.775 * 10 ** ((OPERATING_OUT_DB - full) / 20)
    r_st = got[("stages",)][0]
    stages = {n: round(_node_db(r_st, n, 500.0), 2) for n in PUBLISHED["stages_db"]}
    st_tol = PUBLISHED["stage_tol_db"]
    sens_tol = PUBLISHED["sensitivity_tol_db"]
    sens_lo = PUBLISHED["sensitivity_uv"] * 10 ** (-sens_tol / 20)
    sens_hi = PUBLISHED["sensitivity_uv"] * 10 ** (sens_tol / 20)
    report["gain"] = {
        "record_level_law": law,
        "full_db": full,
        "sensitivity_uv_for_operating_level": round(sens_uv, 1),
        "stages_db_re_078v": stages,
        "vs_published": {
            "sensitivity": lim(sens_uv, sens_lo, sens_hi),
            **{f"stage_{n}": lim(v, PUBLISHED["stages_db"][n] - st_tol,
                                 PUBLISHED["stages_db"][n] + st_tol)
               for n, v in stages.items()},
        },
    }  # fmt: skip

    tones, at = pre.TONES, pre.at
    flat = pre.spectrum(*got[("resp",)])
    db = 20 * np.log10(np.abs(flat))
    rel = db - at(db, 1000.0)
    points = (20, 30, 50, 100, 1000, 5000, 10000, 15000, 20000)
    band = rel >= -1.0
    report["response"] = {
        "tones_hz": tones.tolist(),
        "rel_db": np.round(rel, 3).tolist(),
        "at_db": {f"{f:g}": round(at(rel, f), 2) for f in points},
        "minus_1db_hz": [float(tones[band][0]), float(tones[band][-1])],
    }
    r_src = q["source_impedance_ohm"]
    h_term = pre.spectrum(*got[("resp",)], node="ia")
    z_in = r_src * np.abs(h_term / (1.0 - h_term))
    report["input_impedance"] = {
        "z_ohm": np.round(z_in, 1).tolist(),
        "at_ohm": {f"{f:g}": round(float(np.interp(f, tones, z_in)), 1) for f in (40, 1000, 10000)},
    }
    z = pre.z_out(pre.spectrum(*got[("zout",)]), flat, q["r_load_ohm"])
    report["output_impedance"] = {
        "z_ohm": np.round(z, 2).tolist(),
        "at_1k_ohm": round(at(z, 1000.0), 2),
    }

    def level_at(xs: np.ndarray, thd: np.ndarray, pct: float) -> float | None:
        i = np.nonzero(thd >= pct)[0]
        if len(i) == 0 or i[0] == 0:
            return None
        j = i[0]
        return round(
            float(np.interp(np.log(pct), np.log(thd[j - 1 : j + 1]), xs[j - 1 : j + 1])), 2
        )

    rows = [pre._clean(pre.tone_levels(*got[("sweep", lv)], 1000.0)) for lv in SWEEP_OUT_DB]
    outs, thd = np.array([r["out_db"] for r in rows]), np.array([r["thd_pct"] for r in rows])
    at_3 = level_at(outs, thd, 3.0)
    over = [pre._clean(pre.tone_levels(*got[("over", e)], 1000.0)) for e in OVERLOAD_EMF_DB]
    over_thd = np.array([r["thd_pct"] for r in over])
    low = {f"{o:+g} dB": pre._clean(pre.tone_levels(*got[("low", o)], 40.0)) for o in LOW_OUT_DB}
    report["distortion"] = {
        "sweep_1k": {"rows": rows, "out_db_at_1pct": level_at(outs, thd, 1.0),
                     "out_db_at_3pct": at_3},
        "at_40hz": low,
        "input_overload": {"rows": over, "emf_db_at_1pct": level_at(
            np.array(OVERLOAD_EMF_DB, float), over_thd, 1.0)},
        "vs_published": {"max_output_at_3pct": lim(at_3 if at_3 is not None else float(outs[-1]),
                                                   PUBLISHED["max_out_db"] - 2.0, None)},
    }  # fmt: skip
    every = [
        *report["gain"]["vs_published"].values(),
        *report["distortion"]["vs_published"].values(),
    ]
    report["meets_published"] = f"{sum(c['meets'] for c in every)}/{len(every)}"
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plots(out_dir, report)
    log(f"{name}: meets {report['meets_published']} of the published figures")
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
    ax.semilogx(f, report["response"]["rel_db"], lw=2.0, label="direct monitor")
    ax.set_ylim(-15, 5)
    ax.set_title("Response at RECORD LEVEL 0.1 (re 1 kHz)")
    ax = axes[0, 1]
    ax.semilogx(f, report["input_impedance"]["z_ohm"], label="|Z in| at the terminals")
    ax.set_title("Input impedance (6T1, 150-250 ohm strap)")
    ax.set_ylabel("ohm")
    ax = axes[1, 0]
    ax.semilogx(f, report["output_impedance"]["z_ohm"], label="|Z out|")
    ax.set_title("Output impedance (6T3)")
    ax.set_ylabel("ohm")
    for a in axes.flat[:3]:
        a.set_xlim(10, 45000)
    ax = axes[1, 1]
    rows = report["distortion"]["sweep_1k"]["rows"]
    o = [r["out_db"] for r in rows]
    ax.semilogy(o, [r["thd_pct"] for r in rows], "o-", label="THD")
    ax.semilogy(o, [r["k2_pct"] for r in rows], ".--", label="k2")
    ax.semilogy(o, [r["k3_pct"] for r in rows], ".--", label="k3")
    ax.plot([PUBLISHED["max_out_db"]], [3.0], "k^", ms=9, label="+14 VU = +22 dBm (man p 11)")
    ax.set_xlabel("output (dBu, 600 ohm)")
    ax.set_ylabel("%")
    ax.set_title("1 kHz at RECORD LEVEL 0.1")
    for a in axes.flat:
        a.grid(True, which="both", alpha=0.3)
        a.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

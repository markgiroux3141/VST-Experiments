"""The equalizer profile's measurements (device builder B2): the Pultec EQP-1A.

    report = run(name, genome)     # varimu unit --circuit pultec_eqp1a --name NAME

A unit is the circuit file with the genome's overrides (no setup procedure: the
EQP-1A has no trims). Sections:

- screen (varimu.measure.generic, then the profile's own): an idle render (the
  output quiet, the supply's rails within 10% of DWG E-72,658-2's printed
  voltages) and 1 kHz at the nominal +4 dBm out at flat settings (no oscillation
  riding on it, the overall gain within 6 dB of the drawing's 0 dB);
- response: the small-signal response (a multitone, TONES, 0.01 V per tone at the
  source) at flat settings and at the extreme of every published family: LF boost
  and attenuate at 20 / 30 / 60 / 100 cps, HF boost sharp and broad at every
  frequency, HF attenuate at 5 / 10 / 20 kc; each relative to the flat response;
- vs_published: the published curves' extremes (data/datasheets/pultec_eqp1a_curves.csv,
  read off the manual's page 3, +-1.5 dB) against the response at the same
  frequencies; informative, never rejecting (the plan's "Aim, restated");
- distortion: THD of 1 kHz at flat settings from -10 to +22 dBm out, against the
  brochure's 0.15% at +10 dBm into 600 ohm and its +21 dBm maximum peak output.

Results: reports/units/<name>/report.json, response.png, distortion.png. Levels
are dBm at the unit's 600 ohm terminals (in_s, out). Not modelled: noise (the
brochure's 92 dB below +10 dBm waits for noise sources, B5).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from varimu.circuit import spec
from varimu.config import DATA_DIR, REPO_ROOT
from varimu.measure import generic, metrics
from varimu.measure.levels import DBM_V_RMS, dbm
from varimu.sim import runner
from varimu.sim.io import TransientSettings, full_scale

CIRCUIT = "pultec_eqp1a"
REPORT_DIR = REPO_ROOT / "reports" / "units"
CURVES_CSV = DATA_DIR / "datasheets" / "pultec_eqp1a_curves.csv"

# Supply rails printed on DWG E-72,658-2 (typical, no signal): rejecting outside
# generic.RAIL_PCT. The heaters' tap (+60 V) is only reported: a divider of two 10%
# resistors (270K / 62K) is +-18% in a working unit (a corner rejected at +12.9%,
# 2026-10-26).
RAILS_V = {"b0": 355.0, "b1": 345.0, "b2": 325.0, "b3": 290.0, "b4": 250.0}
REPORTED_V = {"htr": 60.0}
NOMINAL_GAIN_DB = 0.0  # "overall gain with input & output transformers ... is 0 db" (dwg)
NOMINAL_OUT_DBM = 4.0
PUBLISHED = {
    "thd_pct_at_10dbm": 0.15,  # brochure ([MAN] p.1): 0.15% at +10 dbm into 600 ohm
    "max_peak_out_dbm": 21.0,  # [MAN] p.4
    "ranges_db": {"lf_boost": 13.5, "lf_atten": 17.5, "hf_boost": 18.0, "hf_atten": 16.0},
}
AGREES_DB = 2.0  # the curves' reading (+-1.5 dB) and a little slack

TONES = np.unique(np.round(np.geomspace(20.0, 20000.0, 31) / 2.0) * 2.0)  # 2 Hz bins
TONE_V = 0.01
PRE_S, WIN_S = 0.5, 0.5
# Idle: long enough for the supply to settle from its start (the +250 V node's 47K / 40 uF
# is 1.9 s; the rails are averaged over the last RAIL_AVG_S).
IDLE_S, IDLE_WINDOW_S, RAIL_AVG_S = 6.0, (0.05, 5.95), 0.5
DIST_DBM = (-10.0, -5.0, 0.0, 4.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 21.0, 22.0)
DIST_RISE_S, DIST_HOLD_S, DIST_MEASURE_S = 0.05, 0.3, 0.2
EMF_RE_TERMINALS_DB = 6.0  # a 600 ohm source into the unit's ~600 ohm input


def panels() -> dict[str, dict[str, Any]]:
    """Every published family's extreme, by the curves file's panel names, and flat."""
    out: dict[str, dict[str, Any]] = {"flat": {}}
    for f in (20, 30, 60, 100):
        out[f"lf_boost_{f}"] = {"lf_freq_hz": f, "lf_boost": 1.0}
        out[f"lf_atten_{f}"] = {"lf_freq_hz": f, "lf_atten": 1.0}
    for k in (3, 4, 5, 8, 10, 12, 16):
        out[f"hf_boost_sharp_{k}k"] = {"hf_boost_freq_khz": k, "hf_boost": 1.0, "bandwidth": 0.0}
        out[f"hf_boost_broad_{k}k"] = {"hf_boost_freq_khz": k, "hf_boost": 1.0, "bandwidth": 1.0}
    for k in (5, 10, 20):
        out[f"hf_atten_{k}k"] = {"hf_atten_freq_khz": k, "hf_atten": 1.0}
    return out


def published_curves() -> list[dict[str, Any]]:
    with open(CURVES_CSV, encoding="utf-8") as f:
        return [
            {"panel": r["panel"], "freq_hz": float(r["freq_hz"]), "db": float(r["db"])}
            for r in csv.DictReader(f)
        ]


def _job(samples_v: np.ndarray, genome: Mapping[str, Any], ov: Mapping, label: str, s) -> Any:
    return runner.RenderJob(
        samples_v / full_scale(s, spec.load_circuit(spec.circuit_path(CIRCUIT)))[0],
        {**genome, **ov},
        label,
        circuit=CIRCUIT,
    )


def multitone(fs: int) -> np.ndarray:
    t = np.arange(int((PRE_S + WIN_S) * fs)) / fs
    rng = np.random.default_rng(1)
    x = sum(TONE_V * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) for f in TONES)
    return x * np.minimum(1.0, t / 0.02)


def tone(out_dbm: float, fs: int) -> np.ndarray:
    """1 kHz rising over DIST_RISE_S (a raised cosine), held; volts at the source."""
    n = int((DIST_RISE_S + DIST_HOLD_S) * fs)
    t = np.arange(n) / fs
    amp = DBM_V_RMS * np.sqrt(2) * 10 ** ((out_dbm + EMF_RE_TERMINALS_DB) / 20)
    rise = 0.5 - 0.5 * np.cos(np.pi * np.minimum(1.0, t / DIST_RISE_S))
    return amp * rise * np.sin(2 * np.pi * 1000.0 * t)


def response_db(render: runner.Render) -> np.ndarray:
    fs = render.sample_rate
    k, n = int(PRE_S * fs), int(WIN_S * fs)
    bins = np.round(TONES * WIN_S).astype(int)

    def at(w):
        return np.fft.rfft(w[k : k + n])[bins]

    v = render.vectors
    return 20 * np.log10(np.abs(at(v["v(out)"]) / at(v["v(in_s)"])))


def tone_levels(render: runner.Render) -> dict[str, Any]:
    fs = render.sample_rate
    n = int(DIST_MEASURE_S * fs)
    out, inp = render.vectors["v(out)"][-n:], render.vectors["v(in_s)"][-n:]
    h = metrics.harmonics(out, 1000.0, fs)
    return {
        "out_dbm": round(dbm(float(np.sqrt(np.mean(out**2)))), 2),
        "in_dbm": round(dbm(float(np.sqrt(np.mean(inp**2)))), 2),
        "thd_pct": round(100 * h.thd, 4),
        "h2_db": round(h.db(2), 1),
        "h3_db": round(h.db(3), 1),
        "spur": {"db": round(h.spur_db, 1), "hz": h.spur_hz},
        "harmonics": h,
    }


def screen(genome: Mapping[str, Any], s: TransientSettings) -> tuple[dict, dict]:
    fs = s.sample_rate
    idle, nominal = runner.render_many(
        [
            _job(np.zeros(int(IDLE_S * fs)), genome, {}, "idle", s),
            _job(tone(NOMINAL_OUT_DBM, fs), genome, {}, f"1k {NOMINAL_OUT_DBM} dBm", s),
        ],
        settings=s,
    )
    a, b = (int(x * fs) for x in IDLE_WINDOW_S)
    lv = tone_levels(nominal)
    checks = {
        "idle_quiet": generic.quiet(idle.output[a:b]),
        **{
            f"rail_{k}": v
            for k, v in generic.rails(idle.vectors, RAILS_V, int(RAIL_AVG_S * fs)).items()
        },
        "nominal_no_spurs": generic.no_spurs(lv["harmonics"]),
        "nominal_gain": generic.gain(lv["out_dbm"] - lv["in_dbm"], NOMINAL_GAIN_DB),
    }
    n = int(RAIL_AVG_S * fs)
    reported = {
        k: {"v": round(float(np.mean(idle.vectors[f"v({k})"][-n:])), 2), "printed": v}
        for k, v in REPORTED_V.items()
    }
    info = {"idle_out_dbfs": checks["idle_quiet"]["value"], "nominal": _clean(lv), **reported}
    return checks, info


def _clean(lv: Mapping[str, Any]) -> dict:
    return {k: v for k, v in lv.items() if k != "harmonics"}


def compare(rel: Mapping[str, np.ndarray]) -> dict[str, Any]:
    rows = []
    for c in published_curves():
        sim = float(np.interp(np.log(c["freq_hz"]), np.log(TONES), rel[c["panel"]]))
        rows.append({**c, "sim_db": round(sim, 2), "diff_db": round(sim - c["db"], 2)})
    by_panel: dict[str, float] = {}
    for r in rows:
        by_panel[r["panel"]] = max(by_panel.get(r["panel"], 0.0), abs(r["diff_db"]))
    agree = sum(abs(r["diff_db"]) <= AGREES_DB for r in rows)
    return {
        "points": rows,
        "worst_by_panel_db": {k: round(v, 2) for k, v in by_panel.items()},
        "agrees_db": AGREES_DB,
        "agree": f"{agree}/{len(rows)}",
    }


def ranges(rel: Mapping[str, np.ndarray]) -> dict[str, Any]:
    """Each control's extreme at its selected frequency, the most over its positions,
    against the brochure's range ("20, 30, 60, 100 cps shelf boost, 0 to 13.5 db", ...)."""

    def at(panel: str, f_hz: float) -> float:
        return float(np.interp(np.log(f_hz), np.log(TONES), rel[panel]))

    def freq(panel: str) -> float:
        tail = panel.rsplit("_", 1)[1]
        return 1e3 * float(tail[:-1]) if tail.endswith("k") else float(tail)

    out = {}
    for ctl in ("lf_boost", "lf_atten", "hf_boost_sharp", "hf_atten"):
        vals = {p: at(p, freq(p)) for p in rel if p.startswith(ctl + "_")}
        key = "hf_boost" if ctl == "hf_boost_sharp" else ctl
        out[key] = {
            "sim_db": round(max(abs(v) for v in vals.values()), 2),
            "by_position_db": {p: round(v, 2) for p, v in vals.items()},
            "published_db": PUBLISHED["ranges_db"][key],
        }
    return out


def distortion(rows: list[dict]) -> dict[str, Any]:
    outs = np.array([r["out_dbm"] for r in rows])
    thd = np.array([r["thd_pct"] for r in rows])
    at10 = float(np.interp(10.0, outs, thd))
    at21 = float(np.interp(PUBLISHED["max_peak_out_dbm"], outs, thd))
    return {
        "rows": rows,
        "thd_pct_at_10dbm": round(at10, 4),
        "published_thd_pct_at_10dbm": PUBLISHED["thd_pct_at_10dbm"],
        "thd_pct_at_21dbm": round(at21, 4),
        "published_max_peak_out_dbm": PUBLISHED["max_peak_out_dbm"],
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
    del clips  # the EQ's report has no program clips yet
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
    ps = panels()
    jobs = [_job(multitone(fs), genome, ov, p, s) for p, ov in ps.items()]
    jobs += [_job(tone(lv, fs), genome, {}, f"1k {lv} dBm", s) for lv in DIST_DBM]
    log(f"{name}: {len(jobs)} renders")
    renders = runner.render_many(jobs, settings=s)
    resp = {p: response_db(r) for p, r in zip(ps, renders, strict=False)}
    rel = {p: r - resp["flat"] for p, r in resp.items() if p != "flat"}
    report["response"] = {
        "tones_hz": TONES.tolist(),
        "flat_db": np.round(resp["flat"], 3).tolist(),
        "panels": {
            p: {"overrides": ps[p], "rel_db": np.round(r, 3).tolist()} for p, r in rel.items()
        },
    }
    report["vs_published"] = {"curves": compare(rel), "ranges": ranges(rel)}
    rows = [_clean(tone_levels(r)) for r in renders[len(ps) :]]
    report["distortion"] = distortion(rows)
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plots(out_dir, report)
    log(f"{name}: {report['vs_published']['curves']['agree']} curve points within {AGREES_DB} dB")
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
    families = {
        "LF boost": "lf_boost_",
        "LF attenuate": "lf_atten_",
        "HF boost, sharp": "hf_boost_sharp_",
        "HF boost, broad": "hf_boost_broad_",
        "HF attenuate": "hf_atten_",
    }
    pts = report["vs_published"]["curves"]["points"]
    fig, axes = plt.subplots(3, 2, figsize=(12, 11))
    for ax, (title, prefix) in zip(axes.flat, families.items(), strict=False):
        for p, d in report["response"]["panels"].items():
            if p.startswith(prefix):
                (line,) = ax.semilogx(f, d["rel_db"], label=p.removeprefix(prefix))
                pub = [x for x in pts if x["panel"] == p]
                ax.plot(
                    [x["freq_hz"] for x in pub], [x["db"] for x in pub], "o", color=line.get_color()
                )
        ax.set_title(f"{title} (lines: simulated extreme; dots: published, +-1.5 dB)")
        ax.set_xlim(10, 20000)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=7)
        ax.set_ylabel("dB re flat")
    ax = axes.flat[5]
    ax.semilogx(f, report["response"]["flat_db"])
    ax.set_title("Flat response (out / input terminals)")
    ax.set_xlim(10, 20000)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

    rows = report["distortion"]["rows"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.semilogy(
        [r["out_dbm"] for r in rows], [r["thd_pct"] for r in rows], "o-", label="THD, 1 kHz"
    )
    ax.plot([10.0], [PUBLISHED["thd_pct_at_10dbm"]], "s", label="brochure: 0.15% at +10 dBm")
    ax.axvline(PUBLISHED["max_peak_out_dbm"], ls="--", c="gray", label="max peak output +21 dBm")
    ax.set_xlabel("output (dBm, 600 ohm)")
    ax.set_ylabel("THD (%)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "distortion.png", dpi=110)
    plt.close(fig)

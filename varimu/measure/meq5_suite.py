"""The Pultec MEQ-5's profile (docs/EQ_PLAN.md EQ2): `varimu unit --circuit pultec_meq5`.

The EQP-1A's measurements (varimu.measure.eq_suite: the multitone, the 1 kHz tone, its
levels at the 600 ohm terminals, the supply's rails, which the MEQ-5 shares) on the MEQ-5's
panels:
- screen: an idle render (quiet, the rails within 10% of the EQP-1A drawing's) and 1 kHz at
  +4 dBm out at flat settings (no spurs; the overall gain within generic.gain's window of 0
  dB);
- response: every LOW BOOST, MID CUT and HIGH BOOST position at its full knob, relative to
  flat: its extreme (dB, frequency) against the knob and the published 0-10 dB range (web:
  https://www.kmraudio.com/pulse-techniques-meq-5.php: "200, 300, 500, 700, 1000 CPS, 0 - 10
  dB"; the network is Gyraf's reconstruction, so the frequencies are reported, never fitted);
- distortion: THD of 1 kHz at flat from -10 to +22 dBm out.
No published curves of the MEQ-5 were found.
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
from varimu.measure import eq_suite as eq
from varimu.measure import generic
from varimu.sim import runner
from varimu.sim.io import TransientSettings, full_scale

CIRCUIT = "pultec_meq5"
REPORT_DIR = eq.REPORT_DIR
PUBLISHED_RANGE_DB = 10.0
BANDS = {  # band: (frequency control, knob, positions, sign of the extreme)
    "low": ("low_peak_hz", "low_boost", (200, 300, 500, 700, 1000), 1),
    "dip": ("dip_hz", "dip", (200, 300, 500, 700, 1000, 1500, 2000, 3000, 4000, 5000, 7000), -1),
    "high": ("high_peak_hz", "high_boost", (1500, 2000, 3000, 4000, 5000), 1),
}


def _job(x: np.ndarray, genome: Mapping[str, Any], ov: Mapping, label: str, s) -> Any:
    circuit = spec.load_circuit(spec.circuit_path(CIRCUIT))
    return runner.RenderJob(x / full_scale(s, circuit)[0], {**genome, **ov}, label, circuit=CIRCUIT)


def panels() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {"flat": {}}
    for band, (ctl, knob, positions, _) in BANDS.items():
        for f in positions:
            out[f"{band}_{f}"] = {ctl: f, knob: 1.0}
    return out


def extremes(rel: Mapping[str, np.ndarray]) -> dict[str, Any]:
    """Each position's extreme and where it falls, against its knob (log-interpolated)."""
    out: dict[str, Any] = {}
    for band, (_, _, positions, sign) in BANDS.items():
        rows = []
        for f in positions:
            r = rel[f"{band}_{f}"]
            i = int(np.argmax(sign * r))
            rows.append(
                {
                    "knob_hz": f,
                    "extreme_db": round(float(r[i]), 2),
                    "at_hz": float(eq.TONES[i]),
                    "at_ratio": round(float(eq.TONES[i] / f), 3),
                }
            )
        out[band] = {
            "positions": rows,
            "range_db": round(max(abs(r["extreme_db"]) for r in rows), 2),
            "published_range_db": PUBLISHED_RANGE_DB,
        }
    return out


def screen(genome: Mapping[str, Any], s: TransientSettings) -> tuple[dict, dict]:
    fs = s.sample_rate
    idle, nominal = runner.render_many(
        [
            _job(np.zeros(int(eq.IDLE_S * fs)), genome, {}, "idle", s),
            _job(eq.tone(eq.NOMINAL_OUT_DBM, fs), genome, {}, f"1k {eq.NOMINAL_OUT_DBM} dBm", s),
        ],
        settings=s,
    )
    a, b = (int(x * fs) for x in eq.IDLE_WINDOW_S)
    lv = eq.tone_levels(nominal)
    checks = {
        "idle_quiet": generic.quiet(idle.output[a:b]),
        **{
            f"rail_{k}": v
            for k, v in generic.rails(idle.vectors, eq.RAILS_V, int(eq.RAIL_AVG_S * fs)).items()
        },
        "nominal_no_spurs": generic.no_spurs(lv["harmonics"]),
        "nominal_gain": generic.gain(lv["out_dbm"] - lv["in_dbm"], eq.NOMINAL_GAIN_DB),
    }
    return checks, {"idle_out_dbfs": checks["idle_quiet"]["value"], "nominal": eq._clean(lv)}


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    del clips
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
    checks, info = screen(genome, s)
    report.update(screen=info, checks=checks, plausible=all(c["passes"] for c in checks.values()))
    if not report["plausible"]:
        log(f"{name}: rejected: {[k for k, c in checks.items() if not c['passes']]}")
        _write(out_dir, report)
        return report
    fs = s.sample_rate
    ps = panels()
    jobs = [_job(eq.multitone(fs), genome, ov, p, s) for p, ov in ps.items()]
    jobs += [_job(eq.tone(lv, fs), genome, {}, f"1k {lv} dBm", s) for lv in eq.DIST_DBM]
    log(f"{name}: {len(jobs)} renders")
    renders = runner.render_many(jobs, settings=s)
    resp = {p: eq.response_db(r) for p, r in zip(ps, renders, strict=False)}
    rel = {p: r - resp["flat"] for p, r in resp.items() if p != "flat"}
    report["response"] = {
        "tones_hz": eq.TONES.tolist(),
        "flat_db": np.round(resp["flat"], 3).tolist(),
        "panels": {
            p: {"overrides": ps[p], "rel_db": np.round(r, 3).tolist()} for p, r in rel.items()
        },
    }
    report["extremes"] = extremes(rel)
    rows = [eq._clean(eq.tone_levels(r)) for r in renders[len(ps) :]]
    outs = np.array([r["out_dbm"] for r in rows])
    thd = np.array([r["thd_pct"] for r in rows])
    report["distortion"] = {
        "rows": rows,
        "thd_pct_at_10dbm": round(float(np.interp(10.0, outs, thd)), 4),
        "thd_pct_at_21dbm": round(float(np.interp(21.0, outs, thd)), 4),
    }
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plot(out_dir, report)
    log(f"{name}: written to {out_dir}")
    return report


def _write(out_dir: Path, report: Mapping[str, Any]) -> None:
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8"
    )


def _plot(out_dir: Path, report: Mapping[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f = np.array(report["response"]["tones_hz"])
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for ax, (band, title) in zip(
        axes.flat, (("low", "LOW BOOST"), ("dip", "MID CUT"), ("high", "HIGH BOOST")), strict=False
    ):
        for p, d in report["response"]["panels"].items():
            if p.startswith(band + "_"):
                ax.semilogx(f, d["rel_db"], label=p.split("_", 1)[1])
        ax.set_title(f"{title}, full knob (dB re flat)")
        ax.set_xlim(20, 20000)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=7, ncol=2)
    ax = axes.flat[3]
    ax.semilogx(f, report["response"]["flat_db"])
    ax.set_title("Flat response (out / input terminals)")
    ax.set_xlim(20, 20000)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

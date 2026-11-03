"""The microphone preamp profile's measurements (device builder B10): the Telefunken V76.

    report = run(name, genome)     # varimu unit --circuit telefunken_v76 --name NAME

A unit is the circuit file with the genome's overrides (R54 and R75 are trimmed at the
factory; the drawing's values are used: the gains below meet the specs without a trim).
The Braunbuch V 76's acceptance specs ("Abnahmebedingungen", sheets 5-8;
data/schematics/telefunken_v76/README.md) set the conditions: a 200 ohm generator, a
300 ohm load, levels in dB re 0.775 V. Sections:

- screen (varimu.measure.generic, then the profile's own): an idle render (the output
  quiet, the rails within 10% of S 1176's printed 300 / 279 / 242 V) and 1 kHz at
  +6 dB out at 34 dB gain (no oscillation riding on it, the gain within 6 dB of 34);
- gain (sheet 5, point 4a): 1 kHz at +6 dB out at all twelve positions, against the
  scale +-0.5 dB. Gain is the output level re the generator's EMF: the period's
  broadcast practice of voltage matching (the V76's input is >= 600 ohm on a 200 ohm
  generator; provisional: model knowledge). Re the input terminals the pad positions
  read 0.5-1.5 dB higher (reported as `re_terminals_db`);
- response (sheet 6, point 5): a multitone (TONES) at +12 dB out in total, re 1 kHz
  (re 500 Hz for the 3 kHz filter): flat at 76 and 58 dB gain; each bass cut of both
  versions (80 / 120 Hz) and the 3 kHz cut at 76 dB, each against its limits; the gain
  at 1 kHz at every filter setting re flat (point 4b: drops at most 1.5 dB);
- distortion (sheet 7, point 6a): k2 and k3 at 40 Hz, 1 kHz and 5 kHz at +12 dB out /
  76 dB, +22 dB / 76 dB and +22 dB / 34 dB; THD of 1 kHz against level at 34 dB to past
  clipping (the 1% and 3% output levels);
- output impedance (sheet 8, point 7): the multitone at 34 dB into 300 ohm and into
  1 MOhm; Z = 300 (V_open / V_300 - 1), against <= 40 ohm (40 Hz-15 kHz), <= 30 at 1 kHz.

Checks against the specs are reported (`vs_published`), never rejecting (the plan's
"Aim, restated"). The 40-200 kHz stop band (>= 20 dB down) is read at 40 kHz only (the
project's 96 kHz). Not modelled: noise (sheet 8's -120 / -121 dB re the input waits for
the circuit's noise sources, B5), hum fields, power consumption.

Results: reports/units/<name>/report.json, response.png, distortion.png.
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
from varimu.config import REPO_ROOT
from varimu.measure import generic, metrics
from varimu.sim import runner
from varimu.sim.io import TransientSettings, full_scale

CIRCUIT = "telefunken_v76"
REPORT_DIR = REPO_ROOT / "reports" / "units"
MAX_JOBS: int | None = None  # renders at once (None: the runner's default)
V_REF = 0.775  # 0 dB (bb sheet 5)

RAILS_V = {"b300": 300.0, "ba": 279.0, "bb": 242.4}  # S 1176 (the derived two: its currents)
GAINS_DB = (3, 9, 18, 24, 34, 40, 46, 52, 58, 64, 70, 76)
NOMINAL_GAIN_DB = 34

SPECS = {
    "gain_step_tol_db": 0.5,  # point 4a
    "gain_drop_filters_db": 1.5,  # point 4b
    # point 5a: re 1 kHz
    "flat_tol_db": 0.5,  # 60 Hz-15 kHz
    "drop_15hz_min_db": 12.0,
    "at_40hz_db": (-1.5, 0.5),
    "stop_40khz_min_db": 20.0,
    # point 5b: (position, version) -> [(freq, drop at most), (freq, drop at least)]
    "bass_cut": {
        "80": [(80.0, None, 3.0), (40.0, 12.0, None)],
        "120": [(120.0, None, 3.0), (60.0, 12.0, None)],
        "300": [(300.0, None, 4.0), (40.0, 14.0, None)],
        "80+300": [(300.0, None, 4.0), (40.0, 28.0, None)],
        "120+300": [(300.0, None, 4.0), (60.0, 26.0, None)],
    },
    # point 5c: re 500 Hz
    "treble_cut": [(1000.0, None, 0.6), (10000.0, 5.0, 7.0), (15000.0, 6.0, 8.0)],
    # point 6a: (out dB, gain dB) -> {freq: (k2 max %, k3 max %)}
    "distortion": {
        (12, 76): {40: (0.2, 0.2), 1000: (0.1, 0.1), 5000: (0.1, 0.1)},
        (22, 76): {40: (0.3, 0.2), 1000: (0.2, 0.2), 5000: (0.2, 0.2)},
        (22, 34): {40: (1.0, 1.5), 1000: (0.2, 0.2), 5000: (0.2, 0.2)},
    },
    "z_out_max_ohm": 40.0,  # point 7, 40 Hz-15 kHz
    "z_out_1khz_max_ohm": 30.0,
}

# The filter panels (switch settings) the response measures, at 76 dB.
FILTERS = {
    "80": {"bass_cut": 1, "version_hz": 80},
    "300": {"bass_cut": 2, "version_hz": 80},
    "80+300": {"bass_cut": 3, "version_hz": 80},
    "120": {"bass_cut": 1, "version_hz": 120},
    "120+300": {"bass_cut": 3, "version_hz": 120},
    "3k": {"treble_cut": 1},
}
FIXED_TONES = (15, 40, 60, 80, 120, 300, 500, 1000, 5000, 10000, 15000, 40000)
TONES = np.unique(
    np.r_[np.round(np.geomspace(15.0, 40000.0, 40)), np.array(FIXED_TONES, float)]
)  # 1 Hz bins
PRE_S, WIN_S = 0.5, 1.0
RESPONSE_OUT_DB = 12.0  # the multitone's total output level (point 5a: +12 dB)

DIST_RISE_S, DIST_HOLD_S = 0.1, 0.5
DIST_MEASURE_S = 0.25  # 10 periods of 40 Hz
SWEEP_OUT_DB = (-10, 0, 6, 12, 16, 20, 22, 24, 26, 28, 30, 32)


def _emf_v_peak(level_db: float) -> float:
    return V_REF * np.sqrt(2) * 10 ** (level_db / 20)


def _db(v_rms: float) -> float:
    return float(20 * np.log10(v_rms / V_REF))


def _job(emf_v: np.ndarray, genome: Mapping[str, Any], ov: Mapping, label: str, s) -> Any:
    fs_v = full_scale(s, spec.load_circuit(spec.circuit_path(CIRCUIT)))[0]
    return runner.RenderJob(emf_v / fs_v, {**genome, **ov}, label, circuit=CIRCUIT)


def tone(out_db: float, gain_db: float, freq_hz: float, fs: int) -> np.ndarray:
    """A tone (EMF volts) whose output is about out_db at gain_db, rising over DIST_RISE_S
    (a raised cosine), held."""
    t = np.arange(int((DIST_RISE_S + DIST_HOLD_S) * fs)) / fs
    rise = 0.5 - 0.5 * np.cos(np.pi * np.minimum(1.0, t / DIST_RISE_S))
    return _emf_v_peak(out_db - gain_db) * rise * np.sin(2 * np.pi * freq_hz * t)


def multitone(gain_db: float, fs: int) -> np.ndarray:
    """TONES at equal EMF, +RESPONSE_OUT_DB out in total at gain_db (EMF volts)."""
    t = np.arange(int((PRE_S + WIN_S) * fs)) / fs
    rng = np.random.default_rng(1)
    per_tone = _emf_v_peak(RESPONSE_OUT_DB - gain_db - 10 * np.log10(len(TONES)))
    x = sum(per_tone * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) for f in TONES)
    return x * np.minimum(1.0, t / 0.02)


def spectrum(render: runner.Render, emf_v: np.ndarray, node: str = "out") -> np.ndarray:
    """Complex out / EMF at TONES."""
    fs = render.sample_rate
    k, n = int(PRE_S * fs), int(WIN_S * fs)
    bins = np.round(TONES * WIN_S).astype(int)
    return (
        (np.fft.rfft(render.vectors[f"v({node})"][k : k + n])[bins])
        / (np.fft.rfft(emf_v[k : k + n])[bins])
    )


def at(curve_db: np.ndarray, f_hz: float) -> float:
    return float(np.interp(np.log(f_hz), np.log(TONES), curve_db))


def tone_levels(render: runner.Render, emf_v: np.ndarray, freq_hz: float) -> dict[str, Any]:
    fs = render.sample_rate
    n = int(DIST_MEASURE_S * fs)
    out = render.vectors["v(out)"][-n:]
    term = render.vectors["v(ia)"][-n:]
    h = metrics.harmonics(out, freq_hz, fs)
    out_rms = float(h.amps[0] / np.sqrt(2))
    emf_rms = float(np.sqrt(np.mean(emf_v[-n:] ** 2)))
    term_rms = float(metrics.harmonics(term, freq_hz, fs).amps[0] / np.sqrt(2))
    return {
        "out_db": round(_db(out_rms), 2),
        "gain_db": round(_db(out_rms) - _db(emf_rms), 2),
        "re_terminals_db": round(_db(out_rms) - _db(term_rms), 2),
        "thd_pct": round(100 * h.thd, 4),
        "k2_pct": round(100 * 10 ** (h.db(2) / 20), 4),
        "k3_pct": round(100 * 10 ** (h.db(3) / 20), 4),
        "spur": {"db": round(h.spur_db, 1), "hz": h.spur_hz},
        "harmonics": h,
    }


def _clean(lv: Mapping[str, Any]) -> dict:
    return {k: v for k, v in lv.items() if k != "harmonics"}


def screen(genome: Mapping[str, Any], s: TransientSettings) -> tuple[dict, dict]:
    fs = s.sample_rate
    x = tone(6.0, NOMINAL_GAIN_DB, 1000.0, fs)
    idle, nominal = runner.render_many(
        [
            _job(np.zeros(int(1.0 * fs)), genome, {}, "idle", s),
            _job(x, genome, {"gain_db": NOMINAL_GAIN_DB}, "1k +6 dB at 34 dB", s),
        ],
        settings=s,
        max_jobs=MAX_JOBS,
    )
    a = int(0.05 * fs)
    lv = tone_levels(nominal, x, 1000.0)
    checks = {
        "idle_quiet": generic.quiet(idle.output[a:]),
        **{f"rail_{k}": v for k, v in generic.rails(idle.vectors, RAILS_V, int(0.2 * fs)).items()},
        "nominal_no_spurs": generic.no_spurs(lv["harmonics"]),
        "nominal_gain": generic.gain(lv["gain_db"], NOMINAL_GAIN_DB),
    }
    info = {"idle_out_dbfs": checks["idle_quiet"]["value"], "nominal": _clean(lv)}
    return checks, info


def _limits(value: float, lo: float | None, hi: float | None) -> dict[str, Any]:
    ok = (lo is None or value >= lo) and (hi is None or value <= hi)
    return {"value": round(value, 2), "limit": [lo, hi], "meets": bool(ok)}


def response_section(spectra: Mapping[str, np.ndarray]) -> dict[str, Any]:
    db = {p: 20 * np.log10(np.abs(h)) for p, h in spectra.items()}
    rel = {p: d - at(d, 1000.0) for p, d in db.items()}
    flat = rel["flat_76"]
    band = (TONES >= 60) & (TONES <= 15000)
    checks = {
        "flat_60_15k": _limits(float(np.max(np.abs(flat[band]))), None, SPECS["flat_tol_db"]),
        "drop_15hz": _limits(-at(flat, 15.0), SPECS["drop_15hz_min_db"], None),
        "at_40hz": _limits(at(flat, 40.0), *SPECS["at_40hz_db"]),
        "drop_40khz": _limits(-at(flat, 40000.0), SPECS["stop_40khz_min_db"], None),
    }
    for panel, rows in SPECS["bass_cut"].items():
        for f, lo, hi in rows:
            checks[f"bass_{panel}_at_{f:g}"] = _limits(-at(rel[panel], f), lo, hi)
    treble = db["3k"] - at(db["3k"], 500.0)
    for f, lo, hi in SPECS["treble_cut"]:
        checks[f"treble_3k_at_{f:g}"] = _limits(-at(treble, f), lo, hi)
    drops = {p: at(db[p], 1000.0) - at(db["flat_76"], 1000.0) for p in FILTERS}
    checks["gain_drop_filters"] = _limits(-min(drops.values()), None, SPECS["gain_drop_filters_db"])
    return {
        "tones_hz": TONES.tolist(),
        "rel_db": {p: np.round(r, 3).tolist() for p, r in rel.items()},
        "treble_re_500_db": np.round(treble, 3).tolist(),
        "gain_at_1k_re_flat_db": {p: round(v, 2) for p, v in drops.items()},
        "vs_published": checks,
    }


def z_out(open_h: np.ndarray, loaded_h: np.ndarray, r_load: float) -> np.ndarray:
    return r_load * np.abs(open_h / loaded_h - 1.0)


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

    for g in GAINS_DB:
        add(("gain", g), tone(6.0, g, 1000.0, fs), {"gain_db": g}, f"gain {g}")
    for g in (76, 58):
        add(("resp", f"flat_{g}"), multitone(g, fs), {"gain_db": g}, f"flat {g}")
    for p, ov in FILTERS.items():
        add(("resp", p), multitone(76, fs), {"gain_db": 76, **ov}, f"filter {p}")
    load = spec.resolve(spec.load_circuit(spec.circuit_path(CIRCUIT)))["load_ohm"]
    add(("zout", "loaded"), multitone(34, fs), {"gain_db": 34}, "z_out loaded")
    add(("zout", "open"), multitone(34, fs), {"gain_db": 34, "load_ohm": 1.0e6}, "z_out open")
    for (out_db, g), freqs in SPECS["distortion"].items():
        for f in freqs:
            x = tone(out_db, g, float(f), fs)
            add(("dist", (out_db, g, f)), x, {"gain_db": g}, f"k {f} Hz {out_db} dB at {g}")
    for lv in SWEEP_OUT_DB:
        add(("sweep", lv), tone(lv, 34, 1000.0, fs), {"gain_db": 34}, f"sweep {lv} dB")
    log(f"{name}: {len(jobs)} renders")
    renders = runner.render_many(jobs, settings=s, max_jobs=MAX_JOBS)
    got = dict(zip(keys, zip(renders, inputs, strict=True), strict=True))

    gains = {g: _clean(tone_levels(*got[("gain", g)], 1000.0)) for g in GAINS_DB}
    report["gain"] = {
        "positions": gains,
        "vs_published": {
            str(g): _limits(
                gains[g]["gain_db"] - g, -SPECS["gain_step_tol_db"], SPECS["gain_step_tol_db"]
            )
            for g in GAINS_DB
        },  # fmt: skip
    }
    spectra = {k[1]: spectrum(r, x) for k, (r, x) in got.items() if k[0] == "resp"}
    report["response"] = response_section(spectra)
    zl = spectrum(*got[("zout", "loaded")])
    zo = spectrum(*got[("zout", "open")])
    z = z_out(zo, zl, load)
    band = (TONES >= 40) & (TONES <= 15000)
    report["output_impedance"] = {
        "tones_hz": TONES.tolist(),
        "z_ohm": np.round(z, 2).tolist(),
        "vs_published": {
            "max_40_15k": _limits(float(np.max(z[band])), None, SPECS["z_out_max_ohm"]),
            "at_1k": _limits(float(np.interp(1000.0, TONES, z)), None, SPECS["z_out_1khz_max_ohm"]),
        },  # fmt: skip
    }
    dist = {}
    for (out_db, g), freqs in SPECS["distortion"].items():
        for f, (k2_max, k3_max) in freqs.items():
            lv = _clean(tone_levels(*got[("dist", (out_db, g, f))], float(f)))
            dist[f"{out_db:+d} dB at {g} dB, {f} Hz"] = {
                **lv,
                "k2": _limits(lv["k2_pct"], None, k2_max),
                "k3": _limits(lv["k3_pct"], None, k3_max),
            }
    rows = [_clean(tone_levels(*got[("sweep", lv)], 1000.0)) for lv in SWEEP_OUT_DB]
    outs, thd = np.array([r["out_db"] for r in rows]), np.array([r["thd_pct"] for r in rows])

    def level_at(pct: float) -> float | None:
        i = np.nonzero(thd >= pct)[0]
        if len(i) == 0 or i[0] == 0:
            return None
        j = i[0]
        return round(
            float(np.interp(np.log(pct), np.log(thd[j - 1 : j + 1]), outs[j - 1 : j + 1])), 2
        )

    report["distortion"] = {
        "spec_points": dist,
        "sweep_1k_34db": {"rows": rows, "out_db_at_1pct": level_at(1.0),
                          "out_db_at_3pct": level_at(3.0)},
    }  # fmt: skip
    every = [
        *report["gain"]["vs_published"].values(),
        *report["response"]["vs_published"].values(),
        *report["output_impedance"]["vs_published"].values(),
        *(d[k] for d in dist.values() for k in ("k2", "k3")),
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
    rel = report["response"]["rel_db"]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
    ax = axes[0, 0]
    for p in ("flat_76", "flat_58"):
        ax.semilogx(f, rel[p], label=p.replace("_", " at ") + " dB")
    ax.axhspan(-0.5, 0.5, color="g", alpha=0.1, label="+-0.5 dB, 60 Hz-15 kHz (spec)")
    ax.set_ylim(-30, 3)
    ax.set_title("Flat (re 1 kHz)")
    ax = axes[0, 1]
    for p in ("80", "300", "80+300", "120", "120+300"):
        ax.semilogx(f, rel[p], label=p + " Hz")
    for rows in SPECS["bass_cut"].values():
        for fr, lo, hi in rows:
            ax.plot([fr], [-(hi if hi is not None else lo)], "k_" if hi else "k^", ms=8)
    ax.set_ylim(-45, 3)
    ax.set_title("Bass cut at 76 dB (re 1 kHz; marks: the specs' limits)")
    ax = axes[1, 0]
    ax.semilogx(f, report["response"]["treble_re_500_db"], label="3 kHz")
    for fr, lo, hi in SPECS["treble_cut"]:
        ax.plot([fr, fr], [-(hi), -(lo if lo is not None else 0)], "k-", lw=3)
    ax.set_ylim(-15, 3)
    ax.set_title("3 kHz cut (re 500 Hz; bars: the specs' ranges)")
    ax = axes[1, 1]
    ax.semilogx(f, report["output_impedance"]["z_ohm"], label="|Z out| at 34 dB")
    ax.axhline(SPECS["z_out_max_ohm"], ls="--", c="gray", label="40 ohm (spec, 40 Hz-15 kHz)")
    ax.set_title("Output impedance")
    ax.set_ylabel("ohm")
    for a in axes.flat:
        a.set_xlim(10, 45000)
        a.grid(True, which="both", alpha=0.3)
        a.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

    rows = report["distortion"]["sweep_1k_34db"]["rows"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.semilogy([r["out_db"] for r in rows], [r["thd_pct"] for r in rows], "o-", label="THD")
    ax.semilogy([r["out_db"] for r in rows], [r["k2_pct"] for r in rows], ".--", label="k2")
    ax.semilogy([r["out_db"] for r in rows], [r["k3_pct"] for r in rows], ".--", label="k3")
    ax.axvline(22.0, ls="--", c="gray", label="+22 dB (the specs' maximum)")
    ax.set_xlabel("output (dB re 0.775 V, 300 ohm)")
    ax.set_ylabel("%")
    ax.set_title("1 kHz at 34 dB gain")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "distortion.png", dpi=110)
    plt.close(fig)

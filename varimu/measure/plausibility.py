"""Plausibility checks that reject broken units (main plan Phase 4).

Two stages, so a broken genome costs little:

- `screen(genome)`: after the DC trims (varimu.sim.setup.adjust), three renders:
  - idle (no input) at the unit's default front panel: the output must be quiet
    (an oscillation, or low-frequency wander when the regulator is in dropout),
    the rails and the 6386 bias where a working unit has them;
  - the hottest front panel's staircase (pad 0 dB, AC THRESHOLD 1, DC THRESHOLD
    0, TC1; 1 kHz from -30 to 0 dBFS in 10 dB steps after silence, as Phase 3's
    corner sweep): gain reduction present and rising at every step, no
    oscillation riding on the signal (output that isn't the tone's harmonics),
    the control voltage within reach of a real sidechain;
  - 1 kHz at the nominal level (+4 dBm out) with no limiting (AC THRESHOLD 0):
    distortion far beyond the manual's < 1% is absurd.
- `full_checks(report)`: on the full report (varimu.measure.suite): the factory
  curve reachable, gain reduction rising on every curve, attack and release
  within reach of the published Time Constants, the control voltage coming back
  after a burst, the response and intermodulation at no limiting, and no
  oscillation under any curve's tone.

Each check is {"passes", "value", "limit"}; limits are deliberately loose, a
factor of several around the manual's specifications (what is "far outside the
vari-mu range"), so a plausible unit with character passes and a broken one
doesn't. Found by Phase 3's corner sweep (reports/corners/summary.json): HF
oscillators (19-30 kHz), low-frequency wander in weak-supply corners, gain
reduction folding back with T101's leakage at its 20 mH bound.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from varimu.circuit import netlist as nl
from varimu.config import REPO_ROOT, load_sim_settings
from varimu.measure import levels, metrics, signals
from varimu.sim import runner, setup
from varimu.sim.io import TransientSettings
from varimu.sim.ngspice import SimulationFailed

HOT = {"input_atten_db": 0.0, "ac_threshold": 1.0, "dc_threshold": 0.0, "time_constant": 1}
HOT_SILENCE_S, HOT_STEP_S = 0.1, 0.1
HOT_LEVELS_DBFS = (-30.0, -20.0, -10.0, 0.0)
IDLE_S = 0.5
IDLE_WINDOW_S = (0.05, 0.45)  # the decimation filter rings ahead of a signal: no signal here
NOMINAL_OUT_DBM = 4.0  # the 670's nominal output level, [MAN] p.4 ("+4 or +8 VU")
NOMINAL_K_DB = 15.81  # terminals re the EMF at the default pad (setup.threshold, nominal unit)
BANK_R_OHM = 680 + 50  # a bank's cathode resistor plus half the BALANCE pot (for its current)

LIMITS = {
    "idle_out_dbfs": -80.0,  # Phase 3: oscillating / wandering units sat at -76 .. -14 dBFS
    "b_plus_v": (232.0, 248.0),  # [MAN]: adjusted to 240 V (+-3%: as built, too)
    "unregulated_v": (380.0, 480.0),  # printed 420-450 V
    "bank_ma": (10.0, 50.0),  # measured ~26 mA
    "cv_idle_v": -1.5,  # grids biased negative (the 6386's grid current starts near -0.7 V)
    "cv_vs_zero_v": 0.5,  # the idle CV is ZERO's divider
    "hot_gr_db": 6.0,  # gain reduction at 0 dBFS at the hottest panel
    "gr_step_db": 0.5,  # ... rising by more than this per 10 dB step
    "spur_db": -50.0,  # output far from the tone's harmonics re the tone: an oscillation
    "cv_min_v": -150.0,  # Phase 3's oscillator pinned its CV at -212 V; units reach ~-90 V
    "nominal_thd_pct": 5.0,  # [MAN] p.4: < 1% up to +18 dBm out, no limiting
    "curve3_db": 3.0,  # the factory curve within this of curve 3
    "factory_gr_db": 10.0,  # the factory curve limits at least this by +25 dBm in
    "attack_ms": 20.0,  # published 0.2-0.4 ms
    "release_ratio": (0.25, 4.0),  # 90% CV release re the published release
    "cv_return_v": 1.0,  # the CV back within this of its idle value after the release window
    "response_db": 3.0,  # 40 Hz - 15 kHz at no limiting; published +-1 dB
    "smpte_pct": 10.0,  # at no limiting; [MAN] p.10 shows 0.3-4% at 0 dB limiting
}


def _check(passes: bool, value: Any, limit: Any) -> dict:
    return {"passes": bool(passes), "value": value, "limit": limit}


def _hot_signal(fs: int) -> tuple[np.ndarray, list[dict]]:
    sig = signals.stepped_levels(
        freq_hz=1000, levels_dbfs=list(HOT_LEVELS_DBFS), hold_s=HOT_STEP_S, sample_rate=fs
    )
    n0 = int(HOT_SILENCE_S * fs)
    segs = [dict(s, start=s["start"] + n0, stop=s["stop"] + n0) for s in sig.meta["segments"]]
    return np.concatenate([np.zeros(n0), sig.samples]), segs


def screen(
    genome: Mapping[str, Any],
    *,
    adjust: bool = True,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """The cheap stage (see the module docstring): {"passes", "checks", ...}. With
    `adjust` False the unit runs as built (its trims as given), for Phase 3's runs
    flagged that way."""
    fs = load_sim_settings().sample_rate
    s = settings or TransientSettings.from_sim_settings(engine="configured")
    out: dict[str, Any] = {}
    checks: dict[str, dict] = {}
    try:
        ov = setup.adjust(dict(genome)) if adjust else dict(genome)
        out["trims"] = {k: nl.resolve(ov)[k] for k in setup.TRIMS}
        x_hot, segs = _hot_signal(fs)
        nominal_emf = NOMINAL_OUT_DBM - NOMINAL_K_DB
        jobs = [
            runner.RenderJob(np.zeros(int(IDLE_S * fs)), ov, "screen:idle"),
            runner.RenderJob(x_hot, {**ov, **HOT}, "screen:hot"),
            runner.RenderJob(
                levels.tone(10 ** (nominal_emf / 20), sample_rate=fs),
                {**ov, "ac_threshold": 0.0},
                "screen:nominal",
            ),
        ]
        idle, hot, nominal = runner.render_many(jobs, settings=s)
    except (SimulationFailed, RuntimeError, ValueError) as e:
        checks["simulates"] = _check(False, str(e)[:300], "simulates")
        return {"passes": False, "checks": checks, **out}
    checks["simulates"] = _check(True, True, "simulates")

    # Idle.
    v = idle.vectors
    a, b = (int(t * fs) for t in IDLE_WINDOW_S)
    y = idle.output[a:b]
    peak = float(20 * np.log10(np.max(np.abs(y)) + 1e-30))
    spec = np.abs(np.fft.rfft((y - y.mean()) * np.hanning(len(y))))
    peak_hz = float(np.fft.rfftfreq(len(y), 1 / fs)[np.argmax(spec)])
    m = {k: float(np.mean(v[f"v({k})"][a:b])) for k in ("bp", "ur", "cv", "nb2", "nb3", "ka", "kb")}
    p = nl.resolve(ov)
    banks = [(m[k] - m["nb2"]) / BANK_R_OHM * 1e3 for k in ("ka", "kb")]
    out["idle"] = {
        "out_peak_dbfs": round(peak, 1),
        "out_peak_hz": round(peak_hz),
        "rails_v": {k: round(m[k], 2) for k in ("ur", "bp", "nb2", "nb3")},
        "cv_v": round(m["cv"], 3),
        "bank_ma": [round(x, 2) for x in banks],
    }
    lo, hi = LIMITS["b_plus_v"]
    checks["idle_quiet"] = _check(peak < LIMITS["idle_out_dbfs"], peak, LIMITS["idle_out_dbfs"])
    checks["b_plus"] = _check(lo <= m["bp"] <= hi, round(m["bp"], 2), LIMITS["b_plus_v"])
    lo, hi = LIMITS["unregulated_v"]
    checks["unregulated_rail"] = _check(lo <= m["ur"] <= hi, round(m["ur"], 1), (lo, hi))
    lo, hi = LIMITS["bank_ma"]
    checks["bank_current"] = _check(
        all(lo <= x <= hi for x in banks), out["idle"]["bank_ma"], (lo, hi)
    )
    cv_zero = p["zero"] * m["nb3"]
    checks["grid_bias"] = _check(
        m["cv"] < LIMITS["cv_idle_v"] and abs(m["cv"] - cv_zero) < LIMITS["cv_vs_zero_v"],
        {"cv_v": round(m["cv"], 3), "zero_divider_v": round(cv_zero, 3)},
        {"below_v": LIMITS["cv_idle_v"], "within_v": LIMITS["cv_vs_zero_v"]},
    )

    # The hottest front panel.
    gains, spurs, spur_hz, cvs = [], [], [], []
    for sg in segs:
        n = int((sg["stop"] - sg["start"]) * 0.5) // 96 * 96
        sl = slice(sg["stop"] - n, sg["stop"])
        h = metrics.harmonics(hot.output[sl], 1000.0, fs)
        gains.append(20 * np.log10(h.amps[0] / 10 ** (sg["level_dbfs"] / 20)))
        spurs.append(h.spur_db)
        spur_hz.append(h.spur_hz)
        cvs.append(float(np.median(hot.vectors["v(cv)"][sl])))
    gr = [gains[0] - g for g in gains]
    out["hot"] = {
        "levels_dbfs": list(HOT_LEVELS_DBFS),
        "gr_db": [round(x, 2) for x in gr],
        "spur_db": [round(x, 1) for x in spurs],
        "spur_hz": [round(x) for x in spur_hz],
        "cv_v": [round(x, 2) for x in cvs],
        "cv_min_v": round(float(np.min(hot.vectors["v(cv)"])), 2),
    }
    checks["gain_reduction"] = _check(
        gr[-1] > LIMITS["hot_gr_db"], round(gr[-1], 2), LIMITS["hot_gr_db"]
    )
    steps = np.diff(gr)
    checks["gr_rises"] = _check(
        bool(np.all(steps > LIMITS["gr_step_db"])),
        [round(float(x), 2) for x in steps],
        LIMITS["gr_step_db"],
    )
    checks["no_oscillation_under_signal"] = _check(
        max(spurs) < LIMITS["spur_db"],
        {"spur_db": round(max(spurs), 1), "at_hz": round(spur_hz[int(np.argmax(spurs))])},
        LIMITS["spur_db"],
    )
    cv_min = float(np.min(hot.vectors["v(cv)"]))
    checks["cv_in_range"] = _check(
        cv_min > LIMITS["cv_min_v"], round(cv_min, 2), LIMITS["cv_min_v"]
    )

    # Distortion at the nominal level, no limiting.
    tail = slice(-int(levels.MEASURE_S * fs) // 96 * 96, None)
    h = metrics.harmonics(nominal.vectors["v(out)"][tail], 1000.0, fs)
    out_dbm = levels.dbm(h.amps[0] / np.sqrt(2))
    out["nominal"] = {"out_dbm": round(out_dbm, 2), "thd_pct": round(100 * h.thd, 4)}
    checks["nominal_distortion"] = _check(
        100 * h.thd < LIMITS["nominal_thd_pct"], round(100 * h.thd, 4), LIMITS["nominal_thd_pct"]
    )
    passes = all(c["passes"] for c in checks.values())
    failed = [k for k, c in checks.items() if not c["passes"]]
    log(f"screen: {'passes' if passes else f'fails {failed}'}")
    return {"passes": passes, "checks": checks, **out}


def full_checks(report: Mapping[str, Any]) -> dict[str, dict]:
    """Checks on a full report (varimu.measure.suite.run)."""
    c: dict[str, dict] = {}
    curves = report["curves"]
    d = curves["vs_curve3"]["max_abs_diff_db"]
    c["factory_curve"] = _check(d is not None and d < LIMITS["curve3_db"], d, LIMITS["curve3_db"])
    fac = curves["1000hz_factory"]["gr_max_db"]
    c["factory_gain_reduction"] = _check(
        fac > LIMITS["factory_gr_db"], fac, LIMITS["factory_gr_db"]
    )
    bad = [k for k, v in curves.items() if isinstance(v, dict) and v.get("gr_monotonic") is False]
    c["gr_rises_on_every_curve"] = _check(not bad, bad, "no curve folds back")
    res = {
        k: max(r["spur_db"] for r in v["steps"])
        for k, v in curves.items()
        if isinstance(v, dict) and "steps" in v
    }
    worst = max(res.values())
    c["no_oscillation_under_tone"] = _check(
        worst < LIMITS["spur_db"], round(worst, 1), LIMITS["spur_db"]
    )
    thd = report["distortion"]["no_limiting_thd_pct_at_4dbm_out"]
    c["nominal_distortion"] = _check(
        thd is not None and thd < LIMITS["nominal_thd_pct"], thd, LIMITS["nominal_thd_pct"]
    )
    c.update(timing_checks(report["timing"]))
    band = report["response"]["0"]["band_40hz_15khz_db"]
    c["response"] = _check(
        max(abs(band[0]), abs(band[1])) < LIMITS["response_db"], band, LIMITS["response_db"]
    )
    smpte = report["imd"]["0"]["smpte_pct"]
    c["intermodulation"] = _check(smpte < LIMITS["smpte_pct"], smpte, LIMITS["smpte_pct"])
    return c


def timing_checks(timing: Mapping[str, Any]) -> dict[str, dict]:
    """Attack, release (re the published, single bursts) and the CV's return, on the
    timing rows of a report (suite.measure_timing; any subset of the positions)."""
    c: dict[str, dict] = {}
    attacks, releases, returns = {}, {}, {}
    lo, hi = LIMITS["release_ratio"]
    for key, t in timing.items():
        if key.endswith("_train"):
            continue
        attacks[key] = t["attack_cv_63_ms"]
        returns[key] = round(abs(t["cv_end_v"] - t["cv_before_v"]), 3)
        # Re the published range (a single value for positions 1-4; 5 and 6 are
        # program dependent: 2-10 s and 0.3-25 s): 1 inside it, else the factor by
        # which the release is outside it (> 1 slower, < 1 faster); None when it
        # didn't release within the window.
        r_lo, r_hi = t.get("published_release_range_s", [t["published_release_s"]] * 2)
        rel = t["release_cv_90_s"]
        if not np.isfinite(rel):
            releases[key] = None
            continue
        ratio = rel / r_hi if rel > r_hi else (rel / r_lo if rel < r_lo else 1.0)
        releases[key] = round(ratio, 3)
    c["attack"] = _check(
        all(np.isfinite(a) and a < LIMITS["attack_ms"] for a in attacks.values()),
        attacks,
        LIMITS["attack_ms"],
    )
    c["release"] = _check(
        all(r is not None and lo <= r <= hi for r in releases.values()),
        releases,
        {"ratio_to_published_range": (lo, hi)},
    )
    fixed = {
        k: v
        for k, v in returns.items()
        if k in ("timing_tc1", "timing_tc2", "timing_tc3", "timing_tc4")
    }
    c["cv_returns"] = _check(
        all(v < LIMITS["cv_return_v"] for v in fixed.values()), fixed, LIMITS["cv_return_v"]
    )
    return c


# --- Genomes the checks must reject (Phase 4's "done when") ---------------------------------

CORNERS = REPO_ROOT / "reports" / "corners" / "summary.json"

# Deliberately broken: values outside the genome bounds on purpose, one per kind of
# failure the plan names. name -> (overrides, the checks expected to reject it,
# the stage that does: "screen" or "timing" (the full suite's TC2 burst)).
BROKEN = {
    # No gain reduction: T103 steps the output down 20x instead of up 8.5x.
    "no_sidechain_drive": ({"t103_turns_half": 0.05}, {"gain_reduction"}, "screen"),
    # (Oscillation: Phase 3's flagged corners. Phase 2's unscreened transformers, 20 pF
    # on T101 plus 50 pF on T102, oscillated at ~31 kHz in the slice of then; in the
    # current circuit that unit idles at -164 dBFS (checked 2026-10-23).)
    # Runaway DC: the regulator's reference above the regulated rail: no B+ ADJ
    # setting gets 240 V. (At 150 V B+ ADJ still trimmed the rail to 240.9 V.)
    "regulator_reference_off": ({"v5651_operating_v": 300.0}, {"b_plus"}, "screen"),
    # Runaway DC: the 6386s at a tenth of their emission; ZERO can't restore the current.
    "dead_6386s": (
        {"v6386_a.emission_scale": 0.1, "v6386_b.emission_scale": 0.1},
        {"bank_current", "grid_bias"},
        "screen",
    ),
    # Absurd distortion: T101 with 1e-8 of its core area and 1e4 x its turns (the same
    # inductance, 1e4 x the flux per volt) saturates at the nominal level, where the
    # nominal T101 peaks at 0.45 mT. (A small output transformer core alone loses
    # level, not linearity: its inductance shunts the signal.)
    "saturated_input_transformer": (
        {"t101_core_area_m2": 1e-12, "t101_turns": 13_200_000},
        {"nominal_distortion"},
        "screen",
    ),
    # Release far outside the vari-mu range: C109 100x (2 uF -> 200 uF).
    "slow_release": ({"c109_f": 200e-6}, {"release", "cv_returns"}, "timing"),
}


def phase3_flagged() -> dict[str, tuple[dict, bool]]:
    """Phase 3's flagged corner runs as recorded (reports/corners/summary.json):
    name -> (genome, set up?). A run flagged as built is screened as built."""
    data = json.loads(CORNERS.read_text(encoding="utf-8"))
    rows = {(r["label"], r["trimmed"]): r for r in data["results"]}
    return {
        f"phase3:{f['label']}" + ("" if f["trimmed"] else ":as-built"): (
            dict(rows[(f["label"], f["trimmed"])]["genome"]),
            bool(f["trimmed"]),
        )
        for f in data["flagged"]
    }

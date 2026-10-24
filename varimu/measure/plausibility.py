"""Plausibility checks (main plan Phase 4): reject what is broken, report what isn't a 670.

The 670's published curves and specs are calibration anchors, not targets (the
plan's "Aim, restated"): a unit is rejected only for what no working unit could
do, and its distance from the 670 is reported beside, never rejecting.

Rejecting checks, each {"passes", "value", "limit"}, in two stages so a broken
genome costs little:

- `screen(genome)`: after the DC trims (varimu.sim.setup.adjust), three renders:
  - idle (no input) at the unit's default front panel: the output quiet (no
    oscillation, no low-frequency wander from a regulator in dropout), the
    regulator regulating, the 6386 banks conducting with their grids biased
    negative on ZERO's divider (no runaway DC, no collapsed bias);
  - the hottest front panel's staircase (pad 0 dB, AC THRESHOLD 1, DC THRESHOLD
    0, TC1; 1 kHz from -30 to 0 dBFS in 10 dB steps after silence, as Phase 3's
    corner sweep): gain reduction present and rising at every step (none, or
    folding back, is broken), no oscillation riding on the signal (output that
    isn't the tone's harmonics);
  - 1 kHz at the nominal level (+4 dBm out) with no limiting (AC THRESHOLD 0):
    absurd distortion.
- `full_checks(report)`: on the full report (varimu.measure.suite): gain
  reduction rising on every curve, no oscillation under any curve's tone, absurd
  distortion or intermodulation at no limiting, and a control voltage that never
  returns after a burst.

Informative comparisons with the 670 (`vs_670(report)`, and the screen's own
`vs_670`), each {"value", "published", ...}: the factory curve against curve 3,
attack and release against the manual's Time Constants (each burst against the
matching figure: positions 5 and 6 are program dependent), the frequency
response against +-1 dB, the unregulated rail against its printed range, the
control voltage's reach.

Found by Phase 3's corner sweep (reports/corners/summary.json): HF oscillators
(19-30 kHz), low-frequency wander in weak-supply corners, gain reduction folding
back with T101's leakage at its 20 mH bound; all are rejected.
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

# What rejects a unit: what no working unit could do. Deliberately loose.
LIMITS = {
    "idle_out_dbfs": -80.0,  # Phase 3: oscillating / wandering units sat at -76 .. -14 dBFS
    # The regulator regulates: after B+ ADJ, the rail within 3% of the procedure's 240 V
    # ([MAN] p.7). As built (trims as given) within 10%: the 5651's spread (82-92 V,
    # +-6%) and the divider's 10% resistors move an unadjusted rail that far, not more.
    "b_plus_adjusted_pct": 3.0,
    "b_plus_as_built_pct": 10.0,
    "bank_ma": (10.0, 50.0),  # a bank conducting, not running away (measured ~26 mA)
    "cv_idle_v": -1.5,  # grids biased negative (the 6386's grid current starts near -0.7 V)
    "cv_vs_zero_v": 0.5,  # the idle CV is ZERO's divider
    "hot_gr_db": 6.0,  # gain reduction at 0 dBFS at the hottest panel
    "gr_step_db": 0.5,  # ... rising by more than this per 10 dB step
    "spur_db": -50.0,  # output far from the tone's harmonics re the tone: an oscillation
    "nominal_thd_pct": 5.0,  # 5x the manual's < 1% (p.4, no limiting): absurd
    "smpte_pct": 10.0,  # at no limiting; [MAN] p.10 shows 0.3-4% at 0 dB limiting
    # The CV never returns: its 90% release (extrapolated past the window when it
    # isn't there yet) beyond a minute, longer than any program phrase and over twice
    # the slowest vari-mu release published (the 670's 25 s, consistently high level).
    "cv_return_s": 60.0,
}

# The 670's published values the informative comparisons (vs_670) are made against.
B_PLUS_V = 240.0  # [MAN] p.7
PUBLISHED = {
    "unregulated_v": (420.0, 450.0),  # printed on A-96039
    "response_db": 1.0,  # 40 Hz - 15 kHz, +-1 dB (reissue/dealer specs; config/circuits)
}
# Times by position: suite.PUBLISHED_ATTACK_S, suite.PUBLISHED_RELEASE.
# Informative tolerances: "agrees" within these (the measurement's own slack, the
# pad's 1 dB step for the curve; a factor for times quoted to one figure).
AGREES = {"curve3_db": 1.0, "time_ratio": (0.67, 1.5)}


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
    checks["idle_quiet"] = _check(peak < LIMITS["idle_out_dbfs"], peak, LIMITS["idle_out_dbfs"])
    pct = LIMITS["b_plus_adjusted_pct" if adjust else "b_plus_as_built_pct"]
    lim = (round(B_PLUS_V * (1 - pct / 100), 1), round(B_PLUS_V * (1 + pct / 100), 1))
    checks["b_plus"] = _check(lim[0] <= m["bp"] <= lim[1], round(m["bp"], 2), lim)
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
    lo, hi = PUBLISHED["unregulated_v"]
    out["vs_670"] = {
        "unregulated_rail_v": {
            "value": round(m["ur"], 1),
            "published": [lo, hi],
            "agrees": lo <= m["ur"] <= hi,
        },
    }

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
    """The rejecting checks on a full report (varimu.measure.suite.run)."""
    c: dict[str, dict] = {}
    curves = report["curves"]
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
    smpte = report["imd"]["0"]["smpte_pct"]
    c["intermodulation"] = _check(smpte < LIMITS["smpte_pct"], smpte, LIMITS["smpte_pct"])
    return c


def timing_checks(timing: Mapping[str, Any]) -> dict[str, dict]:
    """The CV comes back after every burst (suite.measure_timing's rows; any subset):
    its 90% release, extrapolated past the window when needed, within a minute."""
    est = {k: t["release_cv_90_estimate_s"] for k, t in timing.items()}
    return {
        "cv_returns": _check(
            all(np.isfinite(v) and v < LIMITS["cv_return_s"] for v in est.values()),
            est,
            LIMITS["cv_return_s"],
        )
    }


def _ratio_entry(value: float, published: float) -> dict:
    lo, hi = AGREES["time_ratio"]
    ratio = value / published if np.isfinite(value) else None
    return {
        "value": value,
        "published": published,
        "ratio": None if ratio is None else round(ratio, 3),
        "agrees": ratio is not None and lo <= ratio <= hi,
    }


def vs_670(report: Mapping[str, Any]) -> dict[str, Any]:
    """The unit against the 670's published figures: informative, rejects nothing.
    Each entry {"value", "published", "agrees", ...}; "agrees" within the
    measurement's slack (AGREES: the pad's 1 dB step on the curve, a factor of 1.5
    on times the manual quotes to one figure)."""
    out: dict[str, Any] = {}
    curves = report["curves"]
    d = curves["vs_curve3"]["max_abs_diff_db"]
    out["factory_curve_vs_curve3_db"] = {
        "value": d,
        "published": "curve 3 ([MAN] p.13), the factory adjustment",
        "agrees": d is not None and d <= AGREES["curve3_db"],
    }
    fac = curves["1000hz_factory"]["gr_max_db"]
    x3, y3 = setup.curve3()
    pub = round(float(x3[-1] - y3[-1]), 2)  # curve 3's limiting at its top, +25 dBm in
    out["factory_limiting_at_25dbm_db"] = {
        "value": fac,
        "published": pub,
        "agrees": abs(fac - pub) <= AGREES["curve3_db"],
    }
    # Attack: the manual doesn't say how it was measured. Its 0.2 / 0.4 ms by position
    # compare with the CV's onset (its first 10%; measured 2026-10-23: the 63% point
    # is current-limited by the 6973 pair, ~0.9-2.7 ms; the plan's Phase 4 status).
    attack = {
        k: _ratio_entry(t["attack_cv_10_ms"], t["published_attack_ms"])
        | {"cv_63_ms": t["attack_cv_63_ms"], "gain_3db_ms": t["attack_gain_3db_ms"]}
        for k, t in report["timing"].items()
        if t["burst"] == "burst"
    }
    out["attack_onset_ms"] = attack
    # Release: each burst against the figure published for it (positions 5 and 6:
    # an individual peak, multiple peaks, a consistently high level).
    out["release_cv_90_s"] = {
        k: _ratio_entry(t["release_cv_90_estimate_s"], t["published_release_s"])
        | {"for": t["published_release_for"], "extrapolated": t["release_cv_90_extrapolated"]}
        for k, t in report["timing"].items()
        if t["published_release_s"] is not None
    }
    band = report["response"]["0"]["band_40hz_15khz_db"]
    out["response_40hz_15khz_db"] = {
        "value": band,
        "published": [-PUBLISHED["response_db"], PUBLISHED["response_db"]],
        "agrees": max(abs(band[0]), abs(band[1])) <= PUBLISHED["response_db"],
    }
    if "screen" in report:
        out.update(report["screen"].get("vs_670", {}))
    return out


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
    # A CV that never returns: C109 300x (2 uF -> 600 uF). TC2's release scales with
    # it (100x: 69 s, measured 2026-10-23, too close to the minute to be a clear case).
    "slow_release": ({"c109_f": 600e-6}, {"cv_returns"}, "timing"),
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

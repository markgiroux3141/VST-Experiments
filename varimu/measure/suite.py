"""The measurement suite (main plan Phase 4): genome -> set-up unit -> renders -> report.

    report = run(genome, name)           # varimu unit --name NAME [--genome FILE] [--set k=v ...]

A unit is built from a genome (any circuit value or tube parameter overrides, see
varimu.circuit.netlist) and set up as the factory would: the manual's B+ ADJ,
BALANCE and ZERO procedures (varimu.sim.setup.adjust, on the DC point), then its
threshold procedure to curve 3, the factory-adjusted condition
(setup.threshold: the input pad for unity gain, DC and AC THRESHOLD for 3 dB of
limiting at +3.66 dBm out and 10 dB at +5.41 dBm out). Every measurement runs on
that unit's front panel unless it says otherwise. Levels are dBm at the unit's
600 ohm terminals (varimu.measure.levels), as the manual gives them; the
"gain-reduction points" are the inputs curve 3 limits 0, 3 and 10 dB at (-10,
+6.66 and +15.41 dBm), which the threshold procedure sets the unit to.

Sections (all their renders go out as one parallel batch, then each is measured
from the cache):

- screen: the plausibility screen (varimu.measure.plausibility): idle, the
  hottest front panel's staircase, distortion at the nominal level;
- curves: the static curve at 1 kHz at AC THRESHOLD 0 (no limiting), 0.4, the
  factory setting and 1, -10 .. +25 dBm (no limiting to +28), and at the factory
  setting at 100 Hz and 6 kHz; the factory 1 kHz curve against curve 3;
- distortion: THD and harmonics 2-5 from every step of those staircases (vs level,
  frequency and gain reduction); the manual's specs (p.4: < 1% to +18 dBm out with
  no limiting, < 1% at 10 dB of limiting and +12 dBm out);
- timing: a 1 kHz burst from -10 dBm to the 10 dB point and back, for each Time
  Constant position: attack, and release from 10 dB of limiting as the manual
  specifies it (p.4), from the control voltage and from the gain; for the
  program-dependent positions 5 and 6 also an individual peak and a train of
  short bursts ("multiple peaks"), each compared with its own published figure;
- response: the frequency response at 0, 3 and 10 dB of gain reduction: a 1 kHz
  pilot at the gain-reduction point holds the reduction, a multitone probe 40 dB
  below it (per tone) reads the response;
- imd: SMPTE (60 Hz + 7 kHz, 4:1, as the manual's p.10) and CCIF (19 + 20 kHz)
  twin tones at the three gain-reduction points;
- thump: 6 kHz bursts out of silence at the 0 and 10 dB points: the output
  low-passed at 1 kHz;
- clips: every program clip in data/clips (the user's material; none committed,
  skipped where missing), rendered through the unit: audio to the report's
  audio/ folder (not committed) and the gain over 50 ms windows.

Results: reports/units/<name>/report.json and a plot per section. The report's
`checks` reject a broken unit (varimu.measure.plausibility); its `vs_670` compares
it with the 670's published figures and rejects nothing. Not modelled yet: noise
(the plan's noise floor waits for noise sources).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from varimu.config import DATA_DIR, REPO_ROOT, load_sim_settings
from varimu.measure import levels, metrics, plausibility, signals
from varimu.sim import runner, setup
from varimu.sim.io import TransientSettings, load_audio, write_audio

REPORT_DIR = REPO_ROOT / "reports" / "units"
CLIP_DIR = DATA_DIR / "clips"
CLIP_SUFFIXES = (".wav", ".flac", ".aiff", ".aif")

CURVE_DBM = tuple(float(x) for x in np.arange(-10.0, 25.01, 2.5))
NO_LIMIT_DBM = tuple(float(x) for x in np.arange(-10.0, 28.01, 2.0))
CURVE_AC = (0.0, 0.4, "factory", 1.0)
CURVE_FREQS_HZ = (100.0, 1000.0, 6000.0)  # 6 kHz: whole periods at 96 kHz
HARMONICS_REPORTED = (2, 3, 4, 5)
# [MAN] p.4 attack per Time Constant position (the manual doesn't say how it was
# measured: the 660's brochure says "full limiting in the first 5,000th of a second").
PUBLISHED_ATTACK_S = {1: 0.2e-3, 2: 0.2e-3, 3: 0.4e-3, 4: 0.4e-3, 5: 0.4e-3, 6: 0.2e-3}
# The bursts each position gets: "burst" (BURST_S at one level: for 5 and 6 a
# consistently high level), "peak" (an individual peak, PEAK_S) and "train" (multiple
# peaks, TRAIN) for the program-dependent positions.
TIMING_KINDS = {1: ("burst",), 2: ("burst",), 3: ("burst",), 4: ("burst",),
                5: ("burst", "peak", "train"), 6: ("burst", "peak", "train")}  # fmt: skip
# [MAN] p.4 release (from 10 dB of limiting) per position and burst: 5 and 6 are
# "automatic: a function of the program material". None: no figure for that burst.
PUBLISHED_RELEASE = {
    (1, "burst"): (0.3, "fixed"),
    (2, "burst"): (0.8, "fixed"),
    (3, "burst"): (2.0, "fixed"),
    (4, "burst"): (5.0, "fixed"),
    (5, "peak"): (2.0, "individual peaks"),
    (5, "train"): (10.0, "multiple peaks"),
    # No figure for 5 at a consistent level (the 660's brochure gives its position 5
    # 25 s there, as the 670's manual gives position 6).
    (5, "burst"): (None, "consistently high program level"),
    (6, "peak"): (0.3, "individual peaks"),
    (6, "train"): (10.0, "multiple peaks"),
    (6, "burst"): (25.0, "consistently high program level"),
}
BURST_BASE_DBM = -10.0
BURST_PRE_S, BURST_S = 0.5, 1.0
# An individual peak: long enough for the CV to reach its fast swing (63% at
# ~0.9-1.8 ms, the reduction in place within ~5 ms) and still a short transient
# (a drum hit) against positions 5 and 6's slow capacitors (R139 C110 0.8 s,
# R140 C112 2 s). The release from a peak depends on its length; see the plan.
PEAK_S = 0.02
ATTACK_REF_S = 0.02  # the attack's reference: the CV this far into the burst
RELEASE_WINDOW_S = {1: 2.0, 2: 3.0, 3: 6.0, 4: 15.0, 5: 15.0, 6: 15.0}
TRAIN = (6, 0.15, 0.35)  # multiple peaks: bursts, on s, off s


def timing_keys() -> list[tuple[int, str, str]]:
    """(position, burst kind, report key) of every timing render."""
    return [
        (tc, kind, f"timing_tc{tc}" + ("" if kind == "burst" else f"_{kind}"))
        for tc, kinds in TIMING_KINDS.items()
        for kind in kinds
    ]


PROBE_PERIOD_S = 0.25
PROBE_TONES = 31
PROBE_DB = -40.0  # each probe tone re the pilot's amplitude
PILOT_HZ = 1000.0
RISE_S, SETTLE_S, MEASURE_PERIODS = 0.3, 0.7, 2
IMD_MEASURE_S = 0.5
THUMP_HZ, THUMP_LP_HZ = 6000.0, 1000.0
THUMP_LEAD_S, THUMP_BURST_S, THUMP_GAP_S = 0.5, 0.5, 1.5
THUMP_EDGE_S, THUMP_GUARD_S = 0.005, 0.1
IDLE_S = 0.5
GAIN_WINDOW_S = 0.05


# --- The unit ------------------------------------------------------------------------------


@dataclass
class Unit:
    """A genome, set up: `overrides` is what every render of it builds the circuit from."""

    name: str
    genome: dict[str, Any]
    overrides: dict[str, Any]
    k_db: float  # input terminals re the EMF (dBm - dBFS) at the unit's pad
    gr_points_dbm: dict[str, float]  # "0", "3", "10" dB of limiting -> input dBm
    setup_log: list[str]

    def emf(self, in_dbm: float) -> float:
        return levels.emf_dbfs_for(in_dbm, self.k_db)

    def panel(self, **controls) -> dict[str, Any]:
        return {**self.overrides, **controls}


def gr_points() -> dict[str, float]:
    """Input dBm of 0, 3 and 10 dB of limiting on curve 3 (which setup.threshold sets)."""
    target = setup.factory_target()
    return {"0": BURST_BASE_DBM, "3": target.out_3db_dbm + 3.0, "10": target.out_10db_dbm + 10.0}


def as_built(name: str, genome: Mapping[str, Any]) -> Unit:
    """The genome at its default front panel with no setup at all (the nominal unit's
    factory adjustment and input calibration): for quick partial measurements."""
    return Unit(name, dict(genome), dict(genome), plausibility.NOMINAL_K_DB, gr_points(), [])


def set_up(name: str, genome: Mapping[str, Any], *, log: Callable[[str], Any] = print) -> Unit:
    """The genome with the manual's trims (setup.adjust) and threshold adjustment
    (setup.threshold, to curve 3)."""
    ov = setup.adjust(dict(genome))
    trims = {k: ov[k] for k in setup.TRIMS if k not in genome}
    log(f"{name}: trims {trims}")
    th = setup.threshold(ov, log=lambda m: log(f"{name}: {m}"))
    return Unit(name, dict(genome), th.overrides, th.k_db, gr_points(), th.log)


# --- Signals ---------------------------------------------------------------------------------


def _fs() -> int:
    return load_sim_settings().sample_rate


def _rise(n: int) -> np.ndarray:
    return 0.5 - 0.5 * np.cos(np.pi * (np.arange(n) + 0.5) / n)


def _held(x: np.ndarray, fs: int) -> np.ndarray:
    """x faded in over RISE_S."""
    x = x.copy()
    n = int(RISE_S * fs)
    x[:n] *= _rise(n)
    return x


def probe_freqs(fs: int) -> np.ndarray:
    """PROBE_TONES log-spaced 20 Hz - 20 kHz on the probe period's bins, clear of the
    pilot's harmonics and of their sums and differences with another probe tone."""
    bin_hz = 1 / PROBE_PERIOD_S
    fs_ = []
    for f in np.geomspace(20, 20000, PROBE_TONES):
        b = max(1, round(f / bin_hz))
        while True:
            fb = b * bin_hz
            bad = abs(fb - PILOT_HZ * round(fb / PILOT_HZ)) < 3 * bin_hz
            for g in fs_:
                for k in range(1, 4):
                    bad |= abs(abs(fb - g) - k * PILOT_HZ) < 0.5 * bin_hz
                    bad |= abs(fb + g - k * PILOT_HZ) < 0.5 * bin_hz
            bad |= any(abs(fb - g) < 0.5 * bin_hz for g in fs_)
            if not bad:
                break
            b += 1
        fs_.append(b * bin_hz)
    return np.array(fs_)


def response_signal(pilot_dbfs: float, fs: int, seed: int) -> tuple[np.ndarray, dict]:
    """Pilot + probe multitone, faded in, held SETTLE_S, then MEASURE_PERIODS periods."""
    freqs = probe_freqs(fs)
    rng = np.random.default_rng([seed, 4141])  # phases: fixed per seed
    ph = rng.uniform(0, 2 * np.pi, len(freqs))
    n_per = round(PROBE_PERIOD_S * fs)
    n = int((RISE_S + SETTLE_S) * fs) // n_per * n_per + MEASURE_PERIODS * n_per
    t = np.arange(n) / fs
    a = 10 ** (pilot_dbfs / 20)
    probe = (
        a
        * 10 ** (PROBE_DB / 20)
        * np.sum(np.sin(2 * np.pi * np.outer(freqs, t) + ph[:, None]), axis=0)
    )
    x = _held(a * np.sin(2 * np.pi * PILOT_HZ * t) + probe, fs)
    return x, {"freqs_hz": freqs.tolist(), "measure_from": n - MEASURE_PERIODS * n_per}


def twin_signal(f1: float, f2: float, ratio: float, peak_dbfs: float, fs: int) -> np.ndarray:
    """Two tones whose amplitudes sum to the peak (f1 `ratio` times f2), faded in,
    held SETTLE_S + IMD_MEASURE_S."""
    n = int((RISE_S + SETTLE_S + IMD_MEASURE_S) * fs)
    t = np.arange(n) / fs
    a2 = 10 ** (peak_dbfs / 20) / (1 + ratio)
    return _held(ratio * a2 * np.sin(2 * np.pi * f1 * t) + a2 * np.sin(2 * np.pi * f2 * t), fs)


def burst_signal(unit: Unit, tc: int, kind: str, fs: int) -> tuple[np.ndarray, dict]:
    """-10 dBm, the 10 dB point (one BURST_S burst, an individual PEAK_S peak, or
    TRAIN's short bursts), back to -10 dBm."""
    base, hot = unit.emf(BURST_BASE_DBM), unit.emf(unit.gr_points_dbm["10"])
    segs = [(BURST_PRE_S, base)]
    if kind == "train":
        k, on, off = TRAIN
        for i in range(k):
            segs += [(on, hot), (off if i < k - 1 else 0.0, base)]
        segs = [s for s in segs if s[0] > 0]
    else:
        segs.append((PEAK_S if kind == "peak" else BURST_S, hot))
    segs.append((RELEASE_WINDOW_S[tc], base))
    x, meta = signals._stepped_sine(1000.0, segs, fs)
    hot_segs = [s for s in meta if s["level_dbfs"] == hot]
    return x, {
        "burst_start": hot_segs[0]["start"],
        "first_stop": hot_segs[0]["stop"],
        "burst_stop": hot_segs[-1]["stop"],
    }


# --- Jobs -----------------------------------------------------------------------------------


def curve_staircases(unit: Unit) -> dict[str, levels.Staircase]:
    out = {}
    for ac in CURVE_AC:
        panel = unit.panel() if ac == "factory" else unit.panel(ac_threshold=float(ac))
        dbms = NO_LIMIT_DBM if ac == 0.0 else CURVE_DBM
        tag = "factory" if ac == "factory" else f"ac{ac:g}"
        out[f"1000hz_{tag}"] = levels.Staircase(
            panel, [unit.emf(x) for x in dbms], 1000.0, label=f"{unit.name}:curve_{tag}"
        )
    for f in CURVE_FREQS_HZ:
        if f != 1000.0:
            out[f"{f:g}hz_factory"] = levels.Staircase(
                unit.panel(), [unit.emf(x) for x in CURVE_DBM], f, label=f"{unit.name}:curve"
            )
    return out


def jobs(unit: Unit, *, clips: bool = True) -> dict[str, runner.RenderJob]:
    """Every render the report needs (staircases separately: curve_staircases)."""
    fs, seed = _fs(), load_sim_settings().seed
    j: dict[str, runner.RenderJob] = {}
    for tc, kind, key in timing_keys():
        x, _ = burst_signal(unit, tc, kind, fs)
        j[key] = runner.RenderJob(x, unit.panel(time_constant=tc), f"{unit.name}:{key}")
    for gr, dbm in unit.gr_points_dbm.items():
        x, _ = response_signal(unit.emf(dbm), fs, seed)
        j[f"response_{gr}db"] = runner.RenderJob(x, unit.panel(), f"{unit.name}:response_{gr}db")
        for kind, (f1, f2, ratio) in {
            "smpte": (60, 7000, 4.0),
            "ccif": (19000, 20000, 1.0),
        }.items():
            # The twin tone's peak-equivalent level: its peak = that of a sine at dbm.
            x = twin_signal(f1, f2, ratio, unit.emf(dbm), fs)
            j[f"{kind}_{gr}db"] = runner.RenderJob(x, unit.panel(), f"{unit.name}:{kind}_{gr}db")
    j["thump"] = runner.RenderJob(thump_signal(unit, fs), unit.panel(), f"{unit.name}:thump")
    if clips:
        for path in clip_paths():
            x = load_audio(path, fs)
            j[f"clip:{path.name}"] = runner.RenderJob(x, unit.panel(), f"{unit.name}:{path.name}")
    return j


def clip_paths() -> list[Path]:
    if not CLIP_DIR.is_dir():
        return []
    return sorted(p for p in CLIP_DIR.iterdir() if p.suffix.lower() in CLIP_SUFFIXES)


# --- Measurements ------------------------------------------------------------------------------


def _step_row(s: levels.StepLevel, ref_gain_db: float) -> dict:
    h = s.harmonics
    return {
        "in_dbm": round(s.in_dbm, 2),
        "out_dbm": round(s.out_dbm, 2),
        "gr_db": round(ref_gain_db - s.gain_db, 2),
        "cv_v": round(s.cv_v, 2),
        "thd_pct": round(100 * h.thd, 4),
        **{f"h{k}_db": round(h.db(k), 1) for k in HARMONICS_REPORTED},
        "residual_db": round(h.residual_db, 1),
        "spur_db": round(h.spur_db, 1),
        "spur_hz": round(h.spur_hz),
    }


def measure_curves(unit: Unit, s: TransientSettings | None) -> dict:
    out: dict[str, Any] = {}
    stairs = curve_staircases(unit)
    no_limit = stairs["1000hz_ac0"].measure(s)
    ref = no_limit[0].gain_db  # the unit's gain below any threshold
    for name, st in stairs.items():
        steps = no_limit if name == "1000hz_ac0" else st.measure(s)
        rows = [_step_row(x, ref) for x in steps]
        gr = np.array([r["gr_db"] for r in rows])
        out[name] = {
            "panel": {
                k: st.overrides[k] for k in ("input_atten_db", "ac_threshold", "dc_threshold")
            },
            "freq_hz": st.freq_hz,
            "steps": rows,
            "gr_max_db": round(float(gr.max()), 2),
            # With AC THRESHOLD at 0 there is no limiting: its "reduction" is the
            # amplifier's own compression toward clipping (+27 dBm), not checked.
            "gr_monotonic": None if name == "1000hz_ac0" else bool(np.all(np.diff(gr) >= -0.2)),
        }
    x3, y3 = setup.curve3()
    fac = out["1000hz_factory"]["steps"]
    d = [
        r["out_dbm"] - float(np.interp(r["in_dbm"], x3, y3)) - (ref + 0.0)
        for r in fac
        if r["in_dbm"] >= x3[0]
    ]
    out["vs_curve3"] = {
        "gain_below_threshold_db": round(ref, 2),
        "max_abs_diff_db": round(float(np.max(np.abs(d))), 2) if d else None,
        "note": "out - curve 3 - the unit's gain below threshold, from +2 dBm in",
    }
    return out


def measure_distortion(curves: dict) -> dict:
    """The manual's specs from the curves' steps (p.4)."""
    nl_steps = curves["1000hz_ac0"]["steps"]
    fac = curves["1000hz_factory"]["steps"]

    def at(steps, key, value, field):
        xs = np.array([r[key] for r in steps])
        ys = np.array([r[field] for r in steps])
        return float(np.interp(value, xs, ys)) if xs.min() <= value <= xs.max() else None

    thd_18 = max((r["thd_pct"] for r in nl_steps if r["out_dbm"] <= 18.0), default=None)
    out = {
        "no_limiting_thd_pct_at_4dbm_out": at(nl_steps, "out_dbm", 4.0, "thd_pct"),
        "no_limiting_max_thd_pct_to_18dbm_out": thd_18,
        "spec_no_limiting": "< 1% at any level up to +18 dBm output",
        "factory_thd_pct_at_10db_gr": at(fac, "gr_db", 10.0, "thd_pct"),
        "factory_out_dbm_at_10db_gr": at(fac, "gr_db", 10.0, "out_dbm"),
        "spec_limiting": "< 1% at 10 dB limiting and +12 dBm output",
    }
    # Where the no-limiting curve passes 1% (clipping is specified at +27 dBm).
    over = [r["out_dbm"] for r in nl_steps if r["thd_pct"] >= 1.0]
    out["no_limiting_1pct_out_dbm"] = over[0] if over else None
    return out


def measure_timing(unit: Unit, renders: dict, fs: int) -> dict:
    """Every timing render in `renders` (keys from timing_keys).

    Attack: the CV's first 10% and 63% of its fast swing (ATTACK_REF_S in; for a
    peak, its end), and the gain's 1 / 3 / 6 dB of reduction per half period of the
    tone. Release: from the end of the (last) burst to the CV's and the gain's 63%
    and 90% of the way back, against the burst's settled CV and gain (its last
    quarter), with the 90% CV release extrapolated when the window ends first."""
    rows = {}
    for tc, kind, key in timing_keys():
        if key not in renders:
            continue
        r = renders[key]
        cv = r.vectors["v(cv)"]
        x, meta = burst_signal(unit, tc, kind, fs)
        a, b = meta["burst_start"], meta["burst_stop"]
        ref = min(a + int(ATTACK_REF_S * fs), meta["first_stop"])
        cvt = metrics.cv_timing(cv, fs, a, b)
        gt = metrics.burst_timing(x, r.output, fs, a, b)
        a10, a63 = metrics.cv_attack(cv, fs, a, ref)
        g1, g3, g6 = metrics.gain_attack(x, r.output, fs, 1000.0, a, meta["first_stop"])
        rel90, extrapolated = metrics.cv_release_estimate(
            cv, fs, b, cvt.cv_before_v, cvt.cv_burst_v
        )
        pub_r, pub_as = PUBLISHED_RELEASE[(tc, kind)]
        ms = lambda s: round(s * 1e3, 3)  # noqa: E731
        rows[key] = {
            "position": tc,
            "burst": kind,
            "gr_db": round(gt.gain_before_db - gt.gain_burst_db, 2),
            "attack_cv_10_ms": ms(a10),
            "attack_cv_63_ms": ms(a63),
            "attack_gain_1db_ms": ms(g1),
            "attack_gain_3db_ms": ms(g3),
            "attack_gain_6db_ms": ms(g6),
            "release_cv_63_s": round(cvt.release_63_s, 3),
            "release_cv_90_s": round(cvt.release_90_s, 3),
            "release_cv_90_estimate_s": round(rel90, 3),
            "release_cv_90_extrapolated": extrapolated,
            "release_gain_63_s": round(gt.release_s, 3),
            "release_gain_90_s": round(gt.release_90_s, 3),
            "window_s": RELEASE_WINDOW_S[tc],
            "published_attack_ms": PUBLISHED_ATTACK_S[tc] * 1e3,
            "published_release_s": pub_r,
            "published_release_for": pub_as,
            "cv_end_v": round(float(np.median(cv[-fs // 10 :])), 2),
            "cv_before_v": round(cvt.cv_before_v, 2),
            "cv_burst_v": round(cvt.cv_burst_v, 2),
        }
    return rows


def measure_response(renders: dict, fs: int, seed: int) -> dict:
    out = {}
    for gr in ("0", "3", "10"):
        r = renders[f"response_{gr}db"]
        _, meta = response_signal(0.0, fs, seed)
        a = meta["measure_from"]
        f = np.array(meta["freqs_hz"])
        y = metrics.tone_amplitudes(r.vectors["v(out)"][a:], f, fs)
        x = metrics.tone_amplitudes(r.vectors["v(in_s)"][a:], f, fs)
        g = 20 * np.log10(np.abs(y / x))
        mid = (f > 500) & (f < 2000)
        rel = g - np.mean(g[mid])
        band = (f >= 40) & (f <= 15000)
        out[gr] = {
            "freqs_hz": f.round(1).tolist(),
            "gain_db": g.round(3).tolist(),
            "re_1khz_db": rel.round(3).tolist(),
            "band_40hz_15khz_db": [
                round(float(rel[band].min()), 2),
                round(float(rel[band].max()), 2),
            ],
            "cv_v": round(float(np.median(r.vectors["v(cv)"][a:])), 2),
        }
    return out


def measure_imd(renders: dict, fs: int) -> dict:
    out = {}
    a = int((RISE_S + SETTLE_S) * fs)
    for gr in ("0", "3", "10"):
        y = renders[f"smpte_{gr}db"].vectors["v(out)"][a:]
        n = int(IMD_MEASURE_S * fs)
        smpte = metrics.smpte_imd(y[:n], 60.0, 7000.0, fs)
        y = renders[f"ccif_{gr}db"].vectors["v(out)"][a:][:n]
        ccif = metrics.ccif_imd(y, 19000.0, 20000.0, fs)
        out[gr] = {
            "smpte_pct": round(100 * smpte, 4),
            "ccif_d2_pct": round(100 * ccif["d2"], 4),
            "ccif_d3_pct": round(100 * ccif["d3"], 4),
        }
    return out


def thump_signal(unit: Unit, fs: int) -> np.ndarray:
    """THUMP_HZ bursts out of silence at the 0 and 10 dB points, each rising and
    falling over THUMP_EDGE_S (a raised cosine: the carrier's own onset then puts
    next to nothing below THUMP_LP_HZ, while the sidechain still attacks within
    milliseconds)."""
    lead, burst, gap = (int(v * fs) for v in (THUMP_LEAD_S, THUMP_BURST_S, THUMP_GAP_S))
    e = int(THUMP_EDGE_S * fs)
    env1 = np.ones(burst)
    env1[:e] = _rise(e)
    env1[-e:] = _rise(e)[::-1]
    x = np.zeros(lead + 2 * (burst + gap))
    t = np.arange(burst) / fs
    for i, g in enumerate(("0", "10")):
        a = lead + i * (burst + gap)
        amp = 10 ** (unit.emf(unit.gr_points_dbm[g]) / 20)
        x[a : a + burst] = amp * env1 * np.sin(2 * np.pi * THUMP_HZ * t)
    return x


def measure_thump(unit: Unit, renders: dict, fs: int, full_scale_v: float) -> dict:
    """Per burst: the output low-passed at THUMP_LP_HZ (the thump: the control voltage
    moving on the push-pull grids, not cancelled where the halves differ), its peak
    in dBFS and re the burst's output, and the same low-pass of the input times the
    unit's gain (the measurement's floor: what the carrier leaves below the cutoff).
    Each window ends THUMP_GUARD_S before the next burst (the zero-phase filter
    spreads an onset backwards)."""
    r = renders["thump"]
    y = r.vectors["v(out)"] / full_scale_v
    x = thump_signal(unit, fs)
    lp, lpx = metrics.lowpass(y, THUMP_LP_HZ, fs), metrics.lowpass(x, THUMP_LP_HZ, fs)
    out = {}
    lead, burst, gap, guard = (
        int(v * fs) for v in (THUMP_LEAD_S, THUMP_BURST_S, THUMP_GAP_S, THUMP_GUARD_S)
    )
    for i, gr in enumerate(("0", "10")):
        a = lead + i * (burst + gap)
        seg = slice(a - guard, a + burst + gap - guard)
        steady = slice(a + burst // 2, a + burst - burst // 10)
        tone_pk = float(np.max(np.abs(y[steady])))
        gain = tone_pk / float(np.max(np.abs(x[steady])))
        thump_pk = float(np.max(np.abs(lp[seg])))
        floor = gain * float(np.max(np.abs(lpx[seg])))
        db = lambda v: round(float(20 * np.log10(v + 1e-30)), 1)  # noqa: E731
        out[gr] = {
            "thump_peak_dbfs": db(thump_pk),
            "re_tone_db": db(thump_pk / tone_pk),
            "floor_re_tone_db": db(floor / tone_pk),
        }
    return out


def measure_clips(unit: Unit, renders: dict, fs: int, out_dir: Path) -> dict:
    from varimu.listen.matching import gain_trace

    out = {}
    audio = out_dir / "audio"
    for key, r in renders.items():
        if not key.startswith("clip:"):
            continue
        name = key.split(":", 1)[1]
        x = load_audio(CLIP_DIR / name, fs)
        audio.mkdir(parents=True, exist_ok=True)
        write_audio(audio / f"{Path(name).stem}.wav", r.output, fs)
        _, g = gain_trace(x, r.output, fs, window_s=GAIN_WINDOW_S, points=len(x))
        finite = g[np.isfinite(g)]
        out[name] = {
            "audio": str((audio / f"{Path(name).stem}.wav").relative_to(REPO_ROOT)),
            "gain_db_range": [round(float(finite.max()), 2), round(float(finite.min()), 2)]
            if len(finite)
            else None,
            "cv_min_v": round(float(r.vectors["v(cv)"].min()), 2),
        }
    return out


# --- The report ------------------------------------------------------------------------------


def prefetch(todo: list[runner.RenderJob], settings, log) -> None:
    """Render everything in parallel (longest first); cached renders return at once."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    todo = sorted(todo, key=lambda j: -len(j.samples))
    n = min(runner.default_jobs(), len(todo))
    log(f"{len(todo)} renders, {n} at once")
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(runner.render, j, settings=settings): j for j in todo}
        for f in as_completed(futs):
            f.result()


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = True,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """Screen the genome; if it passes, set it up, measure everything, write the report."""
    t0 = time.perf_counter()
    genome = dict(genome or {})
    out_dir = REPORT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    s = settings or TransientSettings.from_sim_settings(engine="configured")
    report: dict[str, Any] = {
        "name": name,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "genome": genome,
    }
    screen = plausibility.screen(genome, settings=s, log=log)
    report["screen"] = screen
    if not screen["passes"]:
        report["plausible"] = False
        report["rejected_by"] = [c for c, v in screen["checks"].items() if not v["passes"]]
        _write(out_dir, report)
        log(f"{name}: rejected by the screen: {report['rejected_by']}")
        return report

    try:
        unit = set_up(name, genome, log=log)
    except RuntimeError as e:  # SimulationFailed, circuitsim.SimulationError
        report["plausible"] = False
        report["rejected_by"] = ["setup"]
        report["setup_error"] = str(e)[:500]
        _write(out_dir, report)
        log(f"{name}: setup failed: {e}")
        return report
    report["setup"] = {
        "overrides": unit.overrides,
        "k_db": round(unit.k_db, 3),
        "gr_points_dbm": {k: round(v, 2) for k, v in unit.gr_points_dbm.items()},
        "log": unit.setup_log,
    }
    fs, seed = _fs(), load_sim_settings().seed
    named = jobs(unit, clips=clips)
    stairs = curve_staircases(unit)
    prefetch([*named.values(), *(j for st in stairs.values() for j in st.jobs())], s, log)
    renders = {k: runner.render(j, settings=s) for k, j in named.items()}

    report["curves"] = measure_curves(unit, s)
    report["distortion"] = measure_distortion(report["curves"])
    report["timing"] = measure_timing(unit, renders, fs)
    report["response"] = measure_response(renders, fs, seed)
    report["imd"] = measure_imd(renders, fs)
    report["thump"] = measure_thump(unit, renders, fs, s.full_scale_volts_peak)
    report["clips"] = measure_clips(unit, renders, fs, out_dir)
    report["checks"] = plausibility.full_checks(report)
    report["vs_670"] = plausibility.vs_670(report)
    report["plausible"] = all(v["passes"] for v in report["checks"].values())
    report["rejected_by"] = [c for c, v in report["checks"].items() if not v["passes"]]
    report["wall_s"] = round(time.perf_counter() - t0, 1)
    from varimu.measure import report_plots

    report["plots"] = report_plots.plot_all(report, renders, unit, out_dir)
    _write(out_dir, report)
    verdict = "plausible" if report["plausible"] else f"rejected: {report['rejected_by']}"
    path = (out_dir / "report.json").relative_to(REPO_ROOT)
    log(f"{name}: {verdict} ({report['wall_s']:.0f} s) -> {path}")
    return report


def _write(out_dir: Path, report: dict) -> None:
    def default(o):
        if isinstance(o, np.generic):
            return o.item()
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return str(o)

    (out_dir / "report.json").write_text(json.dumps(report, indent=1, default=default), "utf-8")


def timing_stage(name: str, genome: Mapping[str, Any], tcs=(2,)) -> dict:
    """The suite's burst for each of `tcs` on the genome as built (no setup), and the
    timing checks: a cheap look at release without the whole report."""
    unit = as_built(name, genome)
    named = jobs(unit, clips=False)
    keys = [f"timing_tc{tc}" for tc in tcs]
    renders = dict(zip(keys, runner.render_many([named[k] for k in keys]), strict=True))
    rows = measure_timing(unit, renders, _fs())
    checks = plausibility.timing_checks(rows)
    return {"passes": all(c["passes"] for c in checks.values()), "checks": checks, "timing": rows}


def judge(
    name: str,
    genome: Mapping[str, Any],
    *,
    adjust: bool = True,
    stage: str = "screen",
    log: Callable[[str], Any] = print,
) -> dict:
    """One genome through `stage`: "screen" (plausibility.screen) or "timing"
    (timing_stage); the result with the names of the checks that failed."""
    if stage == "timing":
        res = timing_stage(name, genome)
    else:
        res = plausibility.screen(genome, adjust=adjust, log=lambda m: log(f"{name}: {m}"))
    res["failed"] = [k for k, c in res["checks"].items() if not c["passes"]]
    return res

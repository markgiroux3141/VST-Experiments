"""The UREI 1176LN's profile (DEVICE_BUILDER_PLAN.md B12): urei_1176, against the figures
UA's reissue manual gives for the D / E circuit (data/schematics/urei_1176/README.md, "The
manual's figures"; a reissue's figures: a reference, not acceptance data).

    report = run(name, genome)     # varimu unit --circuit urei_1176 --name NAME

Levels are dBu at the input terminals (an ideal source) and across the 600 ohm load (dBm
there). The panel is the circuit file's, with the factory trims (Q BIAS, R86, R83:
scripts/urei_1176_trim.py), and per section:

- screen: generic.quiet on silence, gain reduction disabled;
- gain: INPUT and OUTPUT fully CW, gain reduction disabled, 1 kHz at GAIN_DBU in: the
  manual's 45 dB +-1;
- response: the same, every RESPONSE_HZ re 1 kHz: the manual's +-1 dB, 20 Hz-20 kHz;
- max_output: gain reduction disabled, 1 kHz, the output level where THD (2nd-10th) passes
  0.5 %: the manual's "+22 dBm with no greater than 0.5 % THD";
- curves: the static curve per ratio and "all buttons in" (ratio 0), with THD against gain
  reduction (1 kHz, INPUT fully CW, OUTPUT at CURVE_OUTPUT so the
  line amp stays clean: the side chain listens ahead of the OUTPUT pot), ATTACK mid,
  RELEASE slowest. Per ratio the slope above threshold (the ratio: out vs in from GR 6 to
  GR 15 dB) and the threshold (the input where GR reaches 1 dB, and as the output's knee:
  the manual's "higher Ratio settings also set the threshold higher");
- timing: attack and release on the GR line, the control's own state (the manual doesn't
  define its figures: no level step, no percentage). A 1 kHz tone steps from TIMING_LO_DB
  to TIMING_HI_DB re the 4:1 threshold (attack) and back (release); the time constant is
  the time to 63 % of the GR line's swing, at ATTACK / RELEASE fully CW and CCW: the
  manual's 20-800 us and 50-1100 ms;
- thd_limiting: THD at THD_GR_DB of gain reduction (4:1, RELEASE slowest, as the manual's
  "at the 1.1 s release setting") at 50 Hz, 1 kHz, 15 kHz: the manual's < 0.5 %;
- noise: not measured (the circuit has no noise block yet; the manual's S/N > 81 dB).

Renders call varimu.sim.fast.run_transient uncached; a draft's Newton runs at 1e-5 (the
draft's 1e-3 reads ten times the THD here, as in the SSL bus compressor). Results:
reports/units/<name>/report.json, curves.png, response.png, timing.png.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.measure import generic
from varimu.sim import fast, runner
from varimu.sim.io import TransientSettings

CIRCUIT = "urei_1176"
REPORT_DIR = REPO_ROOT / "reports" / "units"
DBU_PEAK_V = 0.775 * np.sqrt(2)

OPEN = {"input_atten_db": 0.0, "output": 1.0, "attack_off": 1}
GAIN_DBU = -50.0
RESPONSE_HZ = (20.0, 30.0, 50.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0, 15000.0, 20000.0)
MAX_OUT_DBM = tuple(np.arange(16.0, 28.01, 1.0))
CURVE_OUTPUT = 0.45
CURVE_IN_DBU = tuple(np.arange(-56.0, 0.01, 4.0))
RATIOS = (4, 8, 12, 20, 0)  # 0: all buttons in
CURVE_PANEL = {"input_atten_db": 0.0, "attack": 0.5, "release": 0.0}
TIMING_LO_DB, TIMING_HI_DB = -10.0, 20.0
TIMING_STEP_S = 0.3
TIMING_REL_S = {1.0: 1.0, 0.0: 8.0}  # the recovery after the step down, per RELEASE (~7 tau)
THD_GR_DB = 10.0
THD_HZ = (50.0, 1000.0, 15000.0)
NEWTON_DRAFT = 1e-5


def tone(f_hz: float, dbu: float, seconds: float, fs: float, fade_s: float = 0.02):
    t = np.arange(int(round(seconds * fs))) / fs
    return (
        DBU_PEAK_V * 10 ** (dbu / 20) * np.sin(2 * np.pi * f_hz * t) * np.minimum(1.0, t / fade_s)
    )


def level_dbu(y: np.ndarray, f_hz: float, fs: float, frac: float = 0.5) -> float:
    """The f_hz component's level over the last (1 - frac) of y, in whole cycles."""
    a = int(frac * len(y))
    n = int((len(y) - a) * f_hz / fs) * fs / f_hz
    y = y[len(y) - int(n) :]
    t = np.arange(len(y)) / fs
    return float(20 * np.log10(2 * abs(np.mean(y * np.exp(-2j * np.pi * f_hz * t))) / DBU_PEAK_V))


def thd(y: np.ndarray, f_hz: float, fs: float, frac: float = 0.5, nh: int = 10) -> float:
    """2nd-10th harmonics re the fundamental (Hann window), harmonics below Nyquist."""
    y = y[int(frac * len(y)) :]
    t = np.arange(len(y)) / fs
    w = np.hanning(len(y))
    h = [
        abs(np.sum(w * y * np.exp(-2j * np.pi * k * f_hz * t)))
        for k in range(1, nh + 1)
        if k * f_hz < 0.45 * fs
    ]
    return float(np.sqrt(sum(x * x for x in h[1:])) / h[0])


class Bench:
    """Renders of the unit in parallel: {"out": volts, "gr": the GR line's volts}."""

    def __init__(self, genome: Mapping[str, Any], s: TransientSettings):
        self.genome, self.s, self.fs = dict(genome), s, s.sample_rate
        self.spec = spec.load_circuit(spec.circuit_path(CIRCUIT))

    def _one(self, job) -> dict[str, np.ndarray]:
        x, ov = job
        ir = builder.build(self.spec, {**self.genome, **ov}).ir
        with fast.thread_priority(self.s.priority):
            r = fast.run_transient(ir, x, settings=self.s)
        return {"out": np.asarray(r.vectors["v(out)"]), "gr": np.asarray(r.vectors["v(gr)"])}

    def run(self, jobs: list) -> list[dict[str, np.ndarray]]:
        order = sorted(range(len(jobs)), key=lambda i: -len(jobs[i][0]))
        out: list = [None] * len(jobs)
        with ThreadPoolExecutor(runner.default_jobs()) as ex:
            for i, r in zip(order, ex.map(self._one, [jobs[i] for i in order]), strict=True):
                out[i] = r
        return out


def crossing(xs, ys, y0: float) -> float | None:
    """The first x where ys passes y0 upward (linear between points), None if never."""
    for i in range(1, len(xs)):
        if ys[i - 1] < y0 <= ys[i]:
            return float(xs[i - 1] + (y0 - ys[i - 1]) * (xs[i] - xs[i - 1]) / (ys[i] - ys[i - 1]))
    return None


def tau_63(v: np.ndarray, i0: int, fs: float) -> float | None:
    """Seconds from sample i0 until v has covered 63 % of its swing to its end value."""
    v0, v1 = float(np.mean(v[max(0, i0 - 20) : i0])), float(np.mean(v[-int(0.005 * fs) :]))
    target = v0 + (1 - np.exp(-1)) * (v1 - v0)
    seg = (v[i0:] - target) * np.sign(v1 - v0)
    k = np.nonzero(seg >= 0)[0]
    return None if len(k) == 0 else float(k[0] / fs)


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """Screen the unit; if it passes, measure everything, write the report."""
    del clips  # no program clips
    t0 = time.perf_counter()
    genome = dict(genome or {})
    out_dir = REPORT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    s = settings or TransientSettings.from_sim_settings(engine="configured")
    if s.engine != "circuitsim":
        raise ValueError("the 1176's profile needs circuitsim (its cores and JFETs)")
    if s.quality and s.quality.startswith("draft"):
        s = dataclasses.replace(s, newton_reltol=NEWTON_DRAFT, newton_vntol=NEWTON_DRAFT)
    b = Bench(genome, s)
    fs = b.fs
    report: dict[str, Any] = {
        "name": name,
        "circuit": CIRCUIT,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "quality": s.quality,
        "genome": genome,
    }
    log(f"{name}: screen")
    (idle,) = b.run([(np.zeros(int(fs)), dict(OPEN))])
    a = int(0.05 * fs)
    checks = {"idle_quiet": generic.quiet(idle["out"][a:])}
    report["checks"] = checks
    report["plausible"] = all(c["passes"] for c in checks.values())
    if not report["plausible"]:
        log(f"{name}: rejected: {[k for k, c in checks.items() if not c['passes']]}")
        _write(out_dir, report)
        return report

    # --- the first batch: gain, response, max output, the curves --------------------------
    jobs, keys = [], []

    def add(k, x, ov):
        keys.append(k)
        jobs.append((x, dict(ov)))

    for f in RESPONSE_HZ:
        add(("resp", f), tone(f, GAIN_DBU, max(0.4, 12.0 / f), fs), OPEN)
    for o in MAX_OUT_DBM:
        add(("max", o), tone(1000.0, o - 45.0, 0.3, fs), OPEN)
    for r in RATIOS:
        add(("low", r), tone(1000.0, -70.0, 0.4, fs), {"output": CURVE_OUTPUT, "ratio": r,
                                                         **CURVE_PANEL})  # fmt: skip
        for lv in CURVE_IN_DBU:
            add(("curve", r, lv), tone(1000.0, lv, 0.8, fs),
                {"output": CURVE_OUTPUT, "ratio": r, **CURVE_PANEL})  # fmt: skip
    log(f"{name}: {len(jobs)} renders (gain, response, maximum output, curves)")
    got = dict(zip(keys, b.run(jobs), strict=True))

    resp = {f: level_dbu(got[("resp", f)]["out"], f, fs) - GAIN_DBU for f in RESPONSE_HZ}
    g1k = resp[1000.0]
    report["gain"] = {"db": round(g1k, 2), "manual": "45 dB +-1",
                      "passes": bool(abs(g1k - 45.0) <= 1.0)}  # fmt: skip
    rel = {f: round(resp[f] - g1k, 2) for f in RESPONSE_HZ}
    report["response"] = {"re_1khz_db": rel, "manual": "+-1 dB, 20 Hz-20 kHz",
                          "passes": bool(all(abs(v) <= 1.0 for v in rel.values()))}  # fmt: skip
    outs = [level_dbu(got[("max", o)]["out"], 1000.0, fs) for o in MAX_OUT_DBM]
    thds = [100 * thd(got[("max", o)]["out"], 1000.0, fs) for o in MAX_OUT_DBM]
    k = crossing(np.array(outs), np.array(thds), 0.5)
    report["max_output"] = {
        "rows": [
            {"out_dbm": round(o, 2), "thd_pct": round(t, 4)}
            for o, t in zip(outs, thds, strict=True)
        ],  # fmt: skip
        "out_dbm_at_0p5pct": None if k is None else round(k, 2),
        "manual": "+22 dBm, no more than 0.5 % THD",
        "passes": bool(k is not None and k >= 22.0),
    }
    curves, curve_rows = {}, []
    for r in RATIOS:
        g0 = level_dbu(got[("low", r)]["out"], 1000.0, fs) + 70.0
        ins = np.array(CURVE_IN_DBU)
        outs = np.array([level_dbu(got[("curve", r, lv)]["out"], 1000.0, fs, frac=0.7)
                         for lv in ins])  # fmt: skip
        gr = (ins + g0) - outs
        thr = crossing(ins, gr, 1.0)
        m = (gr >= 6.0) & (gr <= 15.0)
        slope = float(np.polyfit(ins[m], outs[m], 1)[0]) if m.sum() >= 2 else None
        thds = [100 * thd(got[("curve", r, lv)]["out"], 1000.0, fs, frac=0.7) for lv in ins]
        curves[r] = {"in": ins, "out": outs, "gr": gr, "g0": g0, "thd": thds}
        curve_rows.append({
            "ratio": r,
            "gain_below_db": round(g0, 2),
            "threshold_in_dbu": None if thr is None else round(thr, 2),
            "threshold_out_dbm": None if thr is None else round(thr + g0 - 1.0, 2),
            "slope_6_to_15_db": None if slope is None else round(slope, 4),
            "ratio_measured": None if not slope else round(1.0 / slope, 2),
            "gr_db": [round(float(x), 2) for x in gr],
            "thd_pct": [round(float(x), 4) for x in thds],
        })  # fmt: skip
    legend = [row for row in curve_rows if row["ratio"]]  # all buttons in: no legend
    thr = [row["threshold_in_dbu"] for row in legend]
    rat = [row["ratio_measured"] for row in legend]
    report["curves"] = {
        "in_dbu": list(CURVE_IN_DBU),
        "output_pot": CURVE_OUTPUT,
        "panel": CURVE_PANEL,
        "rows": curve_rows,
        "manual": "20:1, 12:1, 8:1, 4:1; higher ratios set the threshold higher",
        "ratios_in_order": bool(None not in rat and all(np.diff(rat) > 0)),
        "thresholds_rise": bool(None not in thr and all(np.diff(thr) > 0)),
    }

    # --- the second batch: timing and THD while limiting, from the 4:1 curve ---------------
    _write(out_dir, report)  # the first batch, before the second needs it
    c4 = curves[4]
    thr4 = curve_rows[0]["threshold_in_dbu"]
    lv10 = crossing(c4["in"], c4["gr"], THD_GR_DB)
    jobs, keys = [], []
    n_lo, n_hi = int(TIMING_STEP_S * fs), int(TIMING_STEP_S * fs)
    lo_db, hi_db = thr4 + TIMING_LO_DB, thr4 + TIMING_HI_DB
    for which, setting in (("attack", 1.0), ("attack", 0.0), ("release", 1.0),
                           ("release", 0.0)):  # fmt: skip
        # Phase-continuous steps: one sine, its amplitude stepped.
        tail = 0 if which == "attack" else int(TIMING_REL_S[setting] * fs)
        t = np.arange(n_lo + n_hi + tail) / fs
        amp = np.full(len(t), DBU_PEAK_V * 10 ** (lo_db / 20))
        amp[n_lo : n_lo + n_hi] = DBU_PEAK_V * 10 ** (hi_db / 20)
        x = amp * np.sin(2 * np.pi * 1000.0 * t) * np.minimum(1.0, t / 0.02)
        ov = {"input_atten_db": 0.0, "output": CURVE_OUTPUT, "ratio": 4, "attack": 0.5,
              "release": 0.5, which: setting}  # fmt: skip
        add(("timing", which, setting), x, ov)
    for f in THD_HZ:
        add(("thd", f), tone(f, lv10, max(1.5, 40.0 / f), fs),
            {"output": CURVE_OUTPUT, "ratio": 4, **CURVE_PANEL})  # fmt: skip
        add(("thd_ref", f), tone(f, lv10 - 40.0, max(0.5, 20.0 / f), fs),
            {"output": CURVE_OUTPUT, "ratio": 4, **CURVE_PANEL})  # fmt: skip
    log(f"{name}: {len(jobs)} renders (timing, THD while limiting)")
    got = dict(zip(keys, b.run(jobs), strict=True))
    timing = {}
    for which, setting in (("attack", 1.0), ("attack", 0.0), ("release", 1.0),
                           ("release", 0.0)):  # fmt: skip
        v = got[("timing", which, setting)]["gr"]
        i0 = n_lo if which == "attack" else n_lo + n_hi
        end = (n_lo + n_hi) if which == "attack" else len(v)
        tau = tau_63(v[:end], i0, fs)
        timing[(which, setting)] = (v, i0, tau)
    report["timing"] = {
        "step_dbu": [round(lo_db, 2), round(hi_db, 2)],
        "attack_cw_us": _us(timing[("attack", 1.0)][2]),
        "attack_ccw_us": _us(timing[("attack", 0.0)][2]),
        "release_cw_ms": _ms(timing[("release", 1.0)][2]),
        "release_ccw_ms": _ms(timing[("release", 0.0)][2]),
        "manual": "attack 20-800 us, release 50-1100 ms (fastest fully CW)",
        "definition": "63 % of the GR line's swing after a 30 dB step of a 1 kHz tone "
        "(10 dB under the 4:1 threshold to 20 dB over it, and back)",
    }
    rows = []
    for f in THD_HZ:
        y = got[("thd", f)]["out"]
        g_ref = level_dbu(got[("thd_ref", f)]["out"], f, fs) - (lv10 - 40.0)
        gr = g_ref - (level_dbu(y, f, fs, frac=0.6) - lv10)
        rows.append({"hz": f, "gr_db": round(gr, 2),
                     "thd_pct": round(100 * thd(y, f, fs, frac=0.6), 4)})  # fmt: skip
    report["thd_limiting"] = {
        "in_dbu": round(lv10, 2),
        "rows": rows,
        "manual": "< 0.5 % THD, 50 Hz-15 kHz, with limiting, at the 1.1 s release",
        "passes": bool(all(r["thd_pct"] < 0.5 for r in rows)),
    }
    report["noise"] = {"measured": False, "manual": "S/N > 81 dB at the threshold of limiting",
                       "why": "the circuit file has no noise block yet"}  # fmt: skip
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plots(out_dir, report, curves, timing, fs)
    log(f"{name}: done in {report['elapsed_s']} s -> {out_dir}")
    return report


def _us(x):
    return None if x is None else round(1e6 * x, 1)


def _ms(x):
    return None if x is None else round(1e3 * x, 1)


def _write(out_dir: Path, report: Mapping[str, Any]) -> None:
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8"
    )


def _plots(out_dir: Path, report: dict, curves: dict, timing: dict, fs: float) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12, 5))
    for r, c in curves.items():
        label = f"{r}:1" if r else "all buttons in"
        ax.plot(c["in"], c["out"], "o-", ms=3, label=label)
        bx.semilogy(c["gr"], c["thd"], "o-", ms=3, label=label)
    ax.set_xlabel("input (dBu)")
    ax.set_ylabel(f"output (dBm, OUTPUT at {CURVE_OUTPUT})")
    ax.set_title("Static curves, 1 kHz (ATTACK mid, RELEASE slowest)")
    bx.set_xlabel("gain reduction (dB)")
    bx.set_ylabel("THD (%)")
    bx.set_title("THD against gain reduction, 1 kHz")
    for axis in (ax, bx):
        axis.grid(True, which="both", alpha=0.3)
        axis.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "curves.png", dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    f = list(report["response"]["re_1khz_db"])
    ax.semilogx(f, [report["response"]["re_1khz_db"][k] for k in f], "o-")
    ax.axhspan(-1, 1, color="g", alpha=0.1, label="the manual's +-1 dB")
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB re 1 kHz")
    ax.set_title("Response, gain reduction off")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11, 4))
    for (which, setting), (v, i0, _tau) in timing.items():
        axis = ax if which == "attack" else bx
        span = int((0.004 if which == "attack" else 1.5) * fs)
        seg = v[max(0, i0 - span // 10) : i0 + span]
        t = (np.arange(len(seg)) - min(i0, span // 10)) / fs
        axis.plot(t * (1e3 if which == "attack" else 1.0), seg,
                  label=f"{which} {'CW' if setting else 'CCW'}")  # fmt: skip
    ax.set_xlabel("ms after the step up")
    bx.set_xlabel("s after the step down")
    for axis in (ax, bx):
        axis.set_ylabel("GR line (V)")
        axis.grid(True, alpha=0.3)
        axis.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "timing.png", dpi=110)
    plt.close(fig)

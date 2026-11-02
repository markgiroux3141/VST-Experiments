"""The tape machine profile's measurements (docs/TAPE_PLAN.md, TM5): the Ampex 351 against
its specs.

    report = run(name, genome)     # varimu unit --circuit ampex_351 --name NAME

A unit is the circuit file with the genome's values, aligned by its manual's procedure
(varimu.measure.tape_align, cached per genome), then measured at production (cached
renders; the circuit's noise on: the tubes', the resistors', the mains wander, the tape's
grain). Levels as the alignment's: 0 VU in is -10 dBm bridging, 0 VU out +8 dBm, each
-18 dBFS rms; operating level is 400 Hz at 1% THD. Measurements, as the manual specifies
them (p10-11, p84):

- idle: the drawing's DC voltages (20 kOhm/V, record mode, 117 V, oscillator tube removed:
  `oscillator` 0), each within IDLE_PCT, except AVERAGE_TUBE_NODES: the drawing's unit had
  those 12AX7s hotter than the average tube the model is (TAPE_PLAN.md, "Gaps" 1: reported,
  not held to the spec);
- response: tones RESPONSE_HZ at RESPONSE_DB under operating level ("at least 10 db
  below", p84), re 1 kHz: the spec is +-2 dB 30-15,000 Hz at 15 ips;
- distortion: 400 Hz THD against level (THD_LEVELS_DB re 0 VU in); the 3% level (the
  manual: ~6 dB over operating level) and the most output;
- noise: S/N, "a steady 400 cycle tone, recorded at a level at which distortion ... equals
  3% total rms, and that level of total rms noise, in the band from 30 [50] to 15,000
  cycles, which exists in reproduction under the same gain conditions" (p84): silence
  recorded (bias and erase on), the line out band-limited to NOISE_BAND_HZ (the spec's
  50-15,000, p10), unweighted. The spec: 60 dB at 15 ips full track.

Levels and THD are read from band powers (`tape_align.level`): the tape's wow and flutter
spread a tone a little. Results: reports/units/<name>/report.json, response.png,
distortion.png, noise.png.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal as sps

from varimu.config import REPO_ROOT
from varimu.measure import generic, tape_align
from varimu.sim import runner
from varimu.sim.io import TransientSettings

CIRCUIT = tape_align.CIRCUIT
REPORT_DIR = REPO_ROOT / "reports" / "units"
#: The 351's schematic's DC voltages (p95; data/schematics/ampex_351/README.md).
PRINTED_V = {
    "b330": 330, "b300": 300, "b275": 275, "b250": 250, "b220": 220, "b215": 215,
    "b190": 190, "n180": 180, "bosc": 300, "p1b": 170, "k1b": 1.4, "p1a": 170, "k1a": 1.6,
    "p2b": 75, "k2b": 26, "p2a": 150, "k3b": 1.0, "p4a": 110, "k4a": 1.0, "k4b": 0.6,
    "p5a": 295, "p5b": 295, "k5": 13, "p3b": 100, "p3a": 90, "p4b": 90,
}  # fmt: skip
#: The drawing's three hot 12AX7 plates: the nominal unit has average tubes (decided
#: 2026-11-02), so these are reported, not held to IDLE_PCT.
AVERAGE_TUBE_NODES = ("p3b", "p3a", "p4b")
#: The supply rails (the plausibility screen): a unit whose supply is off isn't working.
RAILS = ("b330", "b300", "b275", "b250")
IDLE_PCT = 20.0  # TM5's done-when
RESPONSE_HZ = (30, 40, 50, 70, 100, 200, 500, 1000, 2000, 5000, 7500, 10000, 12500, 15000)
RESPONSE_DB = -10.0
RESPONSE_SPEC_DB = 2.0
THD_LEVELS_DB = (-10.0, -5.0, 0.0, 3.0, 6.0, 9.0, 12.0)
NOISE_BAND_HZ = (50.0, 15000.0)
NOISE_S = 1.0
SN_SPEC_DB = 60.0
#: Renders at once: each keeps two threads spinning (TAPE_PLAN.md, "Speed").
MAX_JOBS = 6
FADE_S = 5e-3
#: Each tone runs this long after the settle; measured from MEASURE_FROM_S (the head
#: distance's 133 ms and the reproduce side's settling), longer for the lowest tones.
TONE_S, LOW_TONE_S, MEASURE_FROM_S = 0.4, 0.8, 0.2


def _tone(f_hz: float, level_db: float, fs: int) -> np.ndarray:
    """A sine at level_db re 0 VU in (dBFS-scaled samples: -18 dBFS rms is 0 VU)."""
    t = np.arange(int((LOW_TONE_S if f_hz < 100 else TONE_S) * fs)) / fs
    a = 10 ** ((tape_align.VU0_DBFS_RMS + level_db) / 20) * math.sqrt(2)
    return a * np.sin(2 * math.pi * f_hz * t) * np.minimum(1.0, t / FADE_S)


def _job(x: np.ndarray, ov: Mapping[str, Any], label: str) -> runner.RenderJob:
    return runner.RenderJob(x, dict(ov), label=label, circuit=CIRCUIT)


def _out(r: runner.Render) -> np.ndarray:
    """The line out, dBFS-scaled, from MEASURE_FROM_S on."""
    return r.output[int(MEASURE_FROM_S * r.sample_rate) :]


def _dbfs_rms(amp_peak: float) -> float:
    return 20 * math.log10(amp_peak / math.sqrt(2) + 1e-30)


def band_rms(y: np.ndarray, fs: int, band_hz: tuple[float, float]) -> float:
    """y's rms in band_hz (an 8th-order Butterworth band-pass, run both ways)."""
    sos = sps.butter(4, band_hz, "bandpass", fs=fs, output="sos")
    z = sps.sosfiltfilt(sos, y - np.mean(y))
    n = len(z) // 10  # the filter's ends left out
    return float(np.sqrt(np.mean(z[n:-n] ** 2)))


def _crossing(x: np.ndarray, y: np.ndarray, target: float) -> float | None:
    """x where y first rises through target (linear in between), None if it doesn't."""
    for i in range(1, len(y)):
        if y[i - 1] < target <= y[i]:
            return float(x[i - 1] + (target - y[i - 1]) * (x[i] - x[i - 1]) / (y[i] - y[i - 1]))
    return None


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """Align the unit, measure it, write the report."""
    del clips  # no program clips: scripts/print_351.py prints them
    t0 = time.perf_counter()
    genome = dict(genome or {})
    out_dir = REPORT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    s = settings or TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    report: dict[str, Any] = {
        "name": name,
        "circuit": CIRCUIT,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "quality": s.quality,
        "genome": genome,
    }
    log(f"{name}: aligning (cached per genome; ~32 min when not)")
    al = tape_align.aligned(genome, note=lambda m: log(f"  {m}"))
    ov = al.overrides
    report["alignment"] = {"settings": ov, "check": al.steps.get("check")}

    jobs = [_job(np.zeros(int(0.3 * fs)), {**ov, "oscillator": 0}, "idle")]
    jobs += [_job(_tone(f, RESPONSE_DB, fs), ov, f"response {f} Hz") for f in RESPONSE_HZ]
    jobs += [_job(_tone(400.0, lv, fs), ov, f"thd {lv:+g} dB") for lv in THD_LEVELS_DB]
    jobs += [_job(np.zeros(int((MEASURE_FROM_S + NOISE_S) * fs)), ov, "noise")]
    log(f"{name}: {len(jobs)} renders, {MAX_JOBS} at once")
    renders = iter(runner.render_many(jobs, settings=s, max_jobs=MAX_JOBS))

    # Idle.
    idle = next(renders)
    n_avg = int(0.1 * fs)
    idle_v = generic.rails(idle.vectors, PRINTED_V, n_avg)
    for c in idle_v.values():
        c["passes"] = abs(c["value"]["pct"]) <= IDLE_PCT
        c["limit"] = IDLE_PCT
    report["idle"] = idle_v

    # Response.
    lv = np.array([_dbfs_rms(tape_align.level(_out(next(renders)), fs, f)) for f in RESPONSE_HZ])
    rel = lv - lv[list(RESPONSE_HZ).index(1000)]
    report["response"] = {
        "level_db_re_0vu": RESPONSE_DB,
        "freqs_hz": list(RESPONSE_HZ),
        "out_dbfs_rms": np.round(lv, 3).tolist(),
        "re_1khz_db": np.round(rel, 3).tolist(),
        "spread_db": [float(rel.min()), float(rel.max())],
    }

    # Distortion.
    rows = []
    for level_db in THD_LEVELS_DB:
        y = _out(next(renders))
        thd, h = tape_align.thd(y, fs, 400.0)
        rows.append(
            {
                "in_db_re_0vu": level_db,
                "out_dbfs_rms": _dbfs_rms(tape_align.level(y, fs, 400.0)),
                "thd_pct": 100 * thd,
                "h2_pct": 100 * float(h[1]),
                "h3_pct": 100 * float(h[2]),
            }
        )
    ins = np.array(THD_LEVELS_DB)
    thd_db = 20 * np.log10([r["thd_pct"] for r in rows])
    outs = np.array([r["out_dbfs_rms"] for r in rows])
    at = {}
    for pct in (1.0, 3.0):
        x = _crossing(ins, thd_db, 20 * math.log10(pct))
        at[f"{pct:g}pct"] = None if x is None else {
            "in_db_re_0vu": x,
            "out_dbfs_rms": float(np.interp(x, ins, outs)),
        }  # fmt: skip
    report["distortion"] = {"f_hz": 400.0, "rows": rows, "at": at}

    # Noise.
    y = _out(next(renders))
    noise_dbfs = 20 * math.log10(band_rms(y, fs, NOISE_BAND_HZ) + 1e-30)
    f, p = sps.welch(y - np.mean(y), fs, nperseg=fs // 10)
    three = at["3pct"]
    sn = None if three is None else three["out_dbfs_rms"] - noise_dbfs
    report["noise"] = {
        "band_hz": list(NOISE_BAND_HZ),
        "noise_dbfs_rms": noise_dbfs,
        "sn_db": sn,
        "spectrum_hz": f[f <= 20000].tolist(),
        "spectrum_db": (10 * np.log10(p[f <= 20000] + 1e-40)).tolist(),
    }

    # Checks: the screen (a working unit) and the specs (TM5's done-when).
    checks = {
        f"rail_{k}": generic.check(
            abs(idle_v[k]["value"]["pct"]) <= generic.RAIL_PCT, idle_v[k]["value"], generic.RAIL_PCT
        )
        for k in RAILS
    }
    checks["records"] = generic.check(rows[2]["thd_pct"] < 10.0, rows[2]["thd_pct"], 10.0)
    report["checks"] = checks
    report["plausible"] = all(c["passes"] for c in checks.values())
    band = (rel >= -RESPONSE_SPEC_DB) & (rel <= RESPONSE_SPEC_DB)
    report["specs"] = {
        "response_30_15k_pm2db": generic.check(
            bool(band.all()), [round(float(rel.min()), 2), round(float(rel.max()), 2)], 2.0
        ),
        "sn_60db": generic.check(sn is not None and sn >= SN_SPEC_DB, sn, SN_SPEC_DB),
        "idle_pm20pct": generic.check(
            all(c["passes"] for k, c in idle_v.items() if k not in AVERAGE_TUBE_NODES),
            sorted(k for k, c in idle_v.items() if not c["passes"]),
            IDLE_PCT,
        ),
    }
    report["wall_s"] = time.perf_counter() - t0
    _write(out_dir, report)
    _plots(out_dir, report)
    log(f"{name}: specs {json.dumps({k: v['passes'] for k, v in report['specs'].items()})}")
    return report


def _write(out_dir: Path, report: dict) -> None:
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, default=float))


def _plots(out_dir: Path, report: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r = report["response"]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.semilogx(r["freqs_hz"], r["re_1khz_db"], "o-")
    ax.axhspan(-RESPONSE_SPEC_DB, RESPONSE_SPEC_DB, color="g", alpha=0.1, label="spec +-2 dB")
    title = f"Record / reproduce at 15 ips, {RESPONSE_DB:g} dB re operating level"
    ax.set(xlabel="Hz", ylabel="dB re 1 kHz", ylim=(-6, 6), title=title)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

    d = report["distortion"]["rows"]
    fig, ax = plt.subplots(figsize=(8, 4))
    x = [row["in_db_re_0vu"] for row in d]
    for k in ("thd_pct", "h2_pct", "h3_pct"):
        ax.semilogy(x, [row[k] for row in d], "o-", label=k[:-4].upper())
    for pct in (1, 3):
        ax.axhline(pct, color="gray", ls=":")
    ax.set(xlabel="400 Hz in, dB re 0 VU", ylabel="%", title="Distortion at 400 Hz")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "distortion.png", dpi=110)
    plt.close(fig)

    n = report["noise"]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.semilogx(n["spectrum_hz"][1:], n["spectrum_db"][1:])
    sn = n["sn_db"]
    ax.set(xlabel="Hz", ylabel="dB (dBFS^2 / Hz)",
           title=f"Noise at the line out: S/N {sn:.1f} dB" if sn else "Noise")  # fmt: skip
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "noise.png", dpi=110)
    plt.close(fig)

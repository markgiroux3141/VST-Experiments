"""The Ampex 300-4's profile (docs/PERIOD_GEAR_BACKLOG.md, PG1, MT5): each of its four
channels against the 351's specs and the format's figures, and the crosstalk between
neighbours against MT3's fitted curve.

    report = run(name, genome)     # varimu unit --circuit ampex_300_4 --name NAME

The unit is the generated circuit file as it stands: it carries a deck channel's alignment
(scripts/align_300_4.py, the 351's procedure on one channel) and the deck's trims (the record
heads' coupling, each BIAS ADJUST: scripts/ampex_300_4_trim.py), so nothing is aligned here;
a genome's `--set` values go on top. Measured at production (cached renders; the circuit's
noise on), levels as the 351's (tape_suite): 0 VU in -18 dBFS rms on every input (`in`,
`in2` .. `in4`), 0 VU out -18 dBFS rms on every line out (`out`, `out_2` ..).

- **response**: tones at tape_suite.RESPONSE_DB under 0 VU, every channel at once, each on a
  different frequency of the list (channel k three steps on from channel k - 1, so
  neighbours' tones sit bands apart and their crosstalk doesn't touch a channel's own
  reading); re 1 kHz; the 351's spec, +-2 dB 30-15,000 Hz at 15 ips;
- **distortion**: 400 Hz on every channel against level (tape_suite.THD_LEVELS_DB); the 1%
  and 3% levels per channel. (RECORD LEVEL runs out 0.54 dB short of operating level on
  SCOTCH202: the 1% level sits ~+0.5 dB re 0 VU.)
- **noise**: silence on every channel (bias and erase on), each line out's rms in
  NOISE_BAND_HZ, unweighted, against its 3% level: AI-14's definition (400 Hz at 3% against
  the rms noise of erased and biased tape, 30-15,000 Hz) and its figure for four tracks on
  1/2 in, "about 55 decibels" (data/schematics/ampex_300_4/README.md);
- **crosstalk**: an edge track driven at 0 VU, its neighbour's line out over the driven
  track's own at that frequency (dB re the driven track, as Ampex measured), at the fit's
  octave frequencies (reports/multitrack/crosstalk/fit.json, `four_track`), against that
  curve; both edges at once (track 1 at f, track 4 at the list's frequency half an octave
  list away), so each run measures 1 -> 2 and 4 -> 3. AI-14: "crosstalk rejection around 50
  decibels" (mid band, "at a frequency of greatest hearing sensitivity"). The fitted curve's
  63 Hz null (-81.6 dB) sits under the noise in a tone's band: reported, not compared.

Checks (a working unit): every channel's supply (b330..) within generic.RAIL_PCT, every
channel records (THD at 0 VU under 10%). Results: reports/units/<name>/report.json,
response.png, distortion.png, crosstalk.png.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal as sps

from varimu.circuit import spec
from varimu.config import REPO_ROOT
from varimu.measure import generic, tape_align, tape_suite
from varimu.sim import runner
from varimu.sim.io import TransientSettings

CIRCUIT = "ampex_300_4"
REPORT_DIR = tape_suite.REPORT_DIR
FIT = REPO_ROOT / "reports" / "multitrack" / "crosstalk" / "fit.json"
TRACKS = 4
TAGS = ("", "_2", "_3", "_4")
INPUTS = (None, "in2", "in3", "in4")  # channel 1 is the main input
RESPONSE_HZ = tape_suite.RESPONSE_HZ
RESPONSE_DB = tape_suite.RESPONSE_DB
RESPONSE_STEP = 3  # list steps between neighbouring channels' tones
THD_LEVELS_DB = tape_suite.THD_LEVELS_DB
NOISE_BAND_HZ = (30.0, 15000.0)  # AI-14's
NOISE_S = 1.0
SN_FIGURE_DB = 55.0  # AI-14 p 13: four tracks on 1/2 in
XT_LEVEL_DB = 0.0
XT_FIGURE_DB = -50.0  # AI-14 p 13: "crosstalk rejection around 50 decibels"
XT_MID_HZ = (250.0, 4000.0)  # where "around 50" is read
XT_NOISE_HZ = (63.0,)  # the fit's null: under the noise in a tone's band
#: Renders at once: each keeps the island's thread, the rest's and the tape threads busy.
MAX_JOBS = 5
TONE_S, LOW_TONE_S, MEASURE_FROM_S = tape_suite.TONE_S, tape_suite.LOW_TONE_S, 0.2


def _tone(f_hz: float, level_db: float, n: int, fs: int) -> np.ndarray:
    t = np.arange(n) / fs
    a = 10 ** ((tape_align.VU0_DBFS_RMS + level_db) / 20) * math.sqrt(2)
    return a * np.sin(2 * math.pi * f_hz * t) * np.minimum(1.0, t / tape_suite.FADE_S)


def _job(inputs: list[np.ndarray], ov: Mapping[str, Any], label: str) -> runner.RenderJob:
    ctl = {INPUTS[k]: inputs[k] for k in range(1, TRACKS)}
    return runner.RenderJob(inputs[0], dict(ov), label=label, circuit=CIRCUIT, controls=ctl)


def _tones_job(freqs: list[float | None], level_db: float, ov, label: str, fs: int):
    """One run: channel k a tone at freqs[k] (None: silence)."""
    low = any(f is not None and f < 100 for f in freqs)
    n = int((LOW_TONE_S if low else TONE_S) * fs)
    xs = [np.zeros(n) if f is None else _tone(f, level_db, n, fs) for f in freqs]
    return _job(xs, ov, label)


def _outs(r: runner.Render, v_out: float) -> list[np.ndarray]:
    """Each channel's line out, dBFS-scaled, from MEASURE_FROM_S on."""
    i0 = int(MEASURE_FROM_S * r.sample_rate)
    return [r.vectors[f"v(out{t})"][i0:] / v_out for t in TAGS]


def _db(a: float) -> float:
    return 20 * math.log10(a + 1e-30)


def response_freqs(i: int) -> list[float]:
    n = len(RESPONSE_HZ)
    return [float(RESPONSE_HZ[(i + RESPONSE_STEP * k) % n]) for k in range(TRACKS)]


def crosstalk_freqs(fit_hz: list[float]) -> list[tuple[float, float]]:
    """(track 1's, track 4's) per run: track 4 half the list away."""
    n = len(fit_hz)
    return [(fit_hz[i], fit_hz[(i + n // 2) % n]) for i in range(n)]


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """Measure the deck, write the report."""
    del clips  # program material: the session's tape print (MT6)
    t0 = time.perf_counter()
    ov = dict(genome or {})
    out_dir = REPORT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    # The tape's recording kernel on the GPU (TAPE_SPEED_PLAN.md P5: -117 dB from the f64
    # kernel, the floor unchanged): four tracks' kernels are most of a print's CPU.
    s = settings or dataclasses.replace(
        TransientSettings.from_sim_settings(engine="circuitsim"), tape_gpu=True
    )
    fs = s.sample_rate
    v_out = spec.load_circuit(spec.circuit_path(CIRCUIT)).full_scale[1]
    fit = json.loads(FIT.read_text(encoding="utf-8"))["four_track"]["curves"]["15 ips"]
    fit_hz = sorted(float(f) for f in fit)
    report: dict[str, Any] = {
        "name": name,
        "circuit": CIRCUIT,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "quality": s.quality,
        "tape_gpu": s.tape_gpu,
        "genome": ov,
    }

    jobs = [
        _tones_job(response_freqs(i), RESPONSE_DB, ov, f"response {i}", fs)
        for i in range(len(RESPONSE_HZ))
    ]
    jobs += [_tones_job([400.0] * TRACKS, lv, ov, f"thd {lv:+g} dB", fs) for lv in THD_LEVELS_DB]
    n_noise = int((MEASURE_FROM_S + NOISE_S) * fs)
    jobs += [_job([np.zeros(n_noise)] * TRACKS, ov, "noise")]
    xt_runs = crosstalk_freqs(fit_hz)
    jobs += [
        _tones_job([f1, None, None, f4], XT_LEVEL_DB, ov, f"crosstalk {f1:g} / {f4:g} Hz", fs)
        for f1, f4 in xt_runs
    ]
    log(f"{name}: {len(jobs)} renders of the four-track deck, {MAX_JOBS} at once")
    done = [0]

    def progress(i: int, frac: float) -> None:
        if frac >= 1.0:
            done[0] += 1
            log(f"  {done[0]}/{len(jobs)} done ({time.perf_counter() - t0:.0f} s)")

    renders = iter(runner.render_many(jobs, settings=s, max_jobs=MAX_JOBS, progress=progress))

    # Response: per channel, re its 1 kHz.
    lv = np.zeros((TRACKS, len(RESPONSE_HZ)))
    for i in range(len(RESPONSE_HZ)):
        ys = _outs(next(renders), v_out)
        for k, f in enumerate(response_freqs(i)):
            lv[k, RESPONSE_HZ.index(int(f))] = tape_suite._dbfs_rms(tape_align.level(ys[k], fs, f))
    rel = lv - lv[:, [RESPONSE_HZ.index(1000)]]
    report["response"] = {
        "level_db_re_0vu": RESPONSE_DB,
        "freqs_hz": list(RESPONSE_HZ),
        "out_dbfs_rms": np.round(lv, 3).tolist(),
        "re_1khz_db": np.round(rel, 3).tolist(),
        "spread_db": [[float(r.min()), float(r.max())] for r in rel],
    }

    # Distortion.
    rows: list[list[dict]] = [[] for _ in range(TRACKS)]
    for level_db in THD_LEVELS_DB:
        ys = _outs(next(renders), v_out)
        for k in range(TRACKS):
            thd, h = tape_align.thd(ys[k], fs, 400.0)
            rows[k].append(
                {
                    "in_db_re_0vu": level_db,
                    "out_dbfs_rms": tape_suite._dbfs_rms(tape_align.level(ys[k], fs, 400.0)),
                    "thd_pct": 100 * thd,
                    "h2_pct": 100 * float(h[1]),
                    "h3_pct": 100 * float(h[2]),
                }
            )
    ins = np.array(THD_LEVELS_DB)
    at: list[dict] = []
    for k in range(TRACKS):
        thd_db = 20 * np.log10([r["thd_pct"] for r in rows[k]])
        outs = np.array([r["out_dbfs_rms"] for r in rows[k]])
        a = {}
        for pct in (1.0, 3.0):
            x = tape_suite._crossing(ins, thd_db, 20 * math.log10(pct))
            a[f"{pct:g}pct"] = None if x is None else {
                "in_db_re_0vu": x,
                "out_dbfs_rms": float(np.interp(x, ins, outs)),
            }  # fmt: skip
        at.append(a)
    report["distortion"] = {"f_hz": 400.0, "rows": rows, "at": at}

    # Noise.
    r_noise = next(renders)
    ys = _outs(r_noise, v_out)
    noise = []
    for k in range(TRACKS):
        nd = _db(tape_suite.band_rms(ys[k], fs, NOISE_BAND_HZ))
        three = at[k]["3pct"]
        f, p = sps.welch(ys[k] - np.mean(ys[k]), fs, nperseg=fs // 10)
        noise.append(
            {
                "noise_dbfs_rms": nd,
                "sn_db": None if three is None else three["out_dbfs_rms"] - nd,
                "spectrum_db": (10 * np.log10(p[f <= 20000] + 1e-40)).tolist(),
            }
        )
    report["noise"] = {
        "band_hz": list(NOISE_BAND_HZ),
        "spectrum_hz": f[f <= 20000].tolist(),
        "channels": noise,
    }
    n_avg = int(0.1 * fs)
    rails = {}
    for t in TAGS:
        v = float(np.mean(r_noise.vectors[f"v(b330{t})"][-n_avg:]))
        rails[f"b330{t}"] = {"v": round(v, 2), "pct": round(100 * (v / 330 - 1), 1)}
    report["rails"] = rails

    # Crosstalk: 1 -> 2 at f1, 4 -> 3 at f4.
    pairs: dict[str, dict[str, float]] = {"1->2": {}, "4->3": {}}
    for f1, f4 in xt_runs:
        ys = _outs(next(renders), v_out)
        for key, drv, nbr, f in (("1->2", 0, 1, f1), ("4->3", 3, 2, f4)):
            own = tape_align.level(ys[drv], fs, f)
            pairs[key][f"{f:g}"] = _db(tape_align.level(ys[nbr], fs, f)) - _db(own)
    dev = {
        key: {
            f: v - fit[f] for f, v in d.items() if float(f) not in XT_NOISE_HZ and f in fit
        }  # fmt: skip
        for key, d in pairs.items()
    }
    devs = np.array([v for d in dev.values() for v in d.values()])
    mid = [
        v for d in pairs.values() for f, v in d.items() if XT_MID_HZ[0] <= float(f) <= XT_MID_HZ[1]
    ]
    report["crosstalk"] = {
        "level_db_re_0vu": XT_LEVEL_DB,
        "fit_db": fit,
        "measured_db": pairs,
        "minus_fit_db": dev,
        "rms_minus_fit_db": float(np.sqrt(np.mean(devs**2))),
        "worst_mid_band_db": float(max(mid)),
        "noise_limited_hz": list(XT_NOISE_HZ),
    }

    # Checks: the screen (a working unit) and the figures.
    checks = {
        f"rail_{k}": generic.check(abs(c["pct"]) <= generic.RAIL_PCT, c, generic.RAIL_PCT)
        for k, c in rails.items()
    }
    zero = THD_LEVELS_DB.index(0.0)
    for k in range(TRACKS):
        thd0 = rows[k][zero]["thd_pct"]
        checks[f"records_{k + 1}"] = generic.check(thd0 < 10.0, thd0, 10.0)
    report["checks"] = checks
    report["plausible"] = all(c["passes"] for c in checks.values())
    specs = {}
    for k in range(TRACKS):
        r = rel[k]
        ok = bool(((r >= -tape_suite.RESPONSE_SPEC_DB) & (r <= tape_suite.RESPONSE_SPEC_DB)).all())
        specs[f"response_{k + 1}_30_15k_pm2db"] = generic.check(
            ok, [round(float(r.min()), 2), round(float(r.max()), 2)], 2.0
        )
        sn = noise[k]["sn_db"]
        specs[f"sn_{k + 1}_55db"] = generic.check(sn is not None and sn >= SN_FIGURE_DB, sn, 55.0)
    specs["crosstalk_mid_band_50db"] = generic.check(
        max(mid) <= XT_FIGURE_DB, round(max(mid), 2), XT_FIGURE_DB
    )
    report["specs"] = specs
    report["wall_s"] = time.perf_counter() - t0
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, default=float))
    _plots(out_dir, report)
    log(f"{name}: specs {json.dumps({k: v['passes'] for k, v in specs.items()})}")
    return report


def _plots(out_dir: Path, report: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r = report["response"]
    fig, ax = plt.subplots(figsize=(8, 4))
    for k, row in enumerate(r["re_1khz_db"]):
        ax.semilogx(r["freqs_hz"], row, "o-", ms=3, label=f"track {k + 1}")
    ax.axhspan(-2, 2, color="g", alpha=0.1, label="351 spec +-2 dB")
    title = f"Ampex 300-4 record / reproduce, 15 ips, {RESPONSE_DB:g} dB re 0 VU"
    ax.set(xlabel="Hz", ylabel="dB re 1 kHz", ylim=(-6, 6), title=title)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

    d = report["distortion"]["rows"]
    fig, ax = plt.subplots(figsize=(8, 4))
    for k, rows in enumerate(d):
        x = [row["in_db_re_0vu"] for row in rows]
        ax.semilogy(x, [row["thd_pct"] for row in rows], "o-", ms=3, label=f"track {k + 1}")
    for pct in (1, 3):
        ax.axhline(pct, color="gray", ls=":")
    ax.set(xlabel="400 Hz in, dB re 0 VU", ylabel="THD %", title="Distortion at 400 Hz")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "distortion.png", dpi=110)
    plt.close(fig)

    x = report["crosstalk"]
    fig, ax = plt.subplots(figsize=(8, 4))
    fh = sorted(x["fit_db"], key=float)
    ax.semilogx([float(f) for f in fh], [x["fit_db"][f] for f in fh], "k--", label="MT3's fit")
    for key, dd in x["measured_db"].items():
        fk = sorted(dd, key=float)
        ax.semilogx([float(f) for f in fk], [dd[f] for f in fk], "o-", ms=4, label=key)
    ax.axhline(XT_FIGURE_DB, color="gray", ls=":", label="AI-14: ~50 dB")
    ax.set(xlabel="Hz", ylabel="dB re the driven track", title="Crosstalk on the deck, 15 ips")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "crosstalk.png", dpi=110)
    plt.close(fig)

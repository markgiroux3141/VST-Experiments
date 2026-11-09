"""The 351's live tier against its print (docs/TAPE_SPEED_PLAN.md, F1-F2): the same signals
through the literal machine (production, the print) and through the live tier (an events
build of config/circuits/ampex_351_insert.yaml: the reduced tape, the oscillator out, the
record side at the audio rate, at a draft quality), measured the same way.

    uv run --extra fast --extra listen python scripts/tape_tier_study.py [--live-quality draft-1x]
        [--clip drums_setmefree.wav --seconds 4] [--drive-db 0 6 12]
        [--only profile flutter program]

- profile: the 351 profile's measures (varimu.measure.tape_suite: response re 1 kHz at -10 dB,
  400 Hz THD over level and the 1% / 3% levels, S/N in 50 Hz-15 kHz); the print's renders are
  the profile's own (cached: the aligned ampex_351 at production);
- flutter: a 3150 Hz tone at -10 dB, its instantaneous frequency demodulated, the deviation's
  rms over 0.5-250 Hz (the 351's spec 0.11%) and 250 Hz-10 kHz (F1: the transport is the
  same model in both tiers, so this checks it survives the reduction);
- program: the clip at each drive, both tiers with the circuit's noise on and off (off: the
  deterministic core, F1); levels, third-octave bands 31.5 Hz-16 kHz and the waveform
  difference after aligning the delay (re the print's rms). Audio for an ABX in
  reports/tape/tiers/audio/: the print and the live tier, the live one matched to the print's
  loudness (loudness lies).

The print's renders use the GPU kernel for the flutter and program signals (TAPE_SPEED_PLAN.md
P5: -117 dB from the f64 print); the profile's are the CPU's (the profile's cache). Results:
reports/tape/tiers/summary_<live quality>.json, tiers_<live quality>.png.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy import signal as sps

from varimu.circuit import builder, spec
from varimu.circuit import ir as irm
from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta
from varimu.measure import tape_suite as ts
from varimu.sim import fast, runner
from varimu.sim.io import TransientSettings, load_audio

OUT = REPO_ROOT / "reports" / "tape" / "tiers"
INSERT = "ampex_351_insert"
FLUTTER_HZ, FLUTTER_S, FLUTTER_DB = 3150.0, 4.0, -10.0
TAIL_S = 0.3
BANDS_HZ = 1000.0 * 10 ** (np.arange(-15, 13) / 10)  # 31.6 Hz .. 15.8 kHz


def band_rms_fft(x: np.ndarray, fs: float, lo: float, hi: float) -> float:
    k = np.fft.rfft(x - x.mean())
    f = np.fft.rfftfreq(len(x), 1.0 / fs)
    m = (f >= lo) & (f <= hi)
    return math.sqrt(2.0 * float(np.sum(np.abs(k[m]) ** 2))) / len(x)


def without_flutter(ir: irm.CircuitIR) -> irm.CircuitIR:
    """`ir` with its tapes' transports steady (no flutter components)."""

    def el(e):
        if not isinstance(e, irm.Tape):
            return e
        m = dataclasses.replace(e.medium, flutter=(), flutter_noise=())
        return dataclasses.replace(e, medium=m)

    secs = tuple(
        dataclasses.replace(s, elements=tuple(el(e) for e in s.elements)) for s in ir.sections
    )
    return dataclasses.replace(ir, sections=secs)


def third_octaves(y: np.ndarray, fs: float) -> np.ndarray:
    """dB power per third-octave band (BANDS_HZ centres)."""
    k = np.abs(np.fft.rfft(y)) ** 2
    f = np.fft.rfftfreq(len(y), 1.0 / fs)
    edge = 10 ** (1 / 20)
    return np.array(
        [10 * math.log10(k[(f >= c / edge) & (f < c * edge)].sum() + 1e-30) for c in BANDS_HZ]
    )


def flutter(y: np.ndarray, fs: int) -> dict:
    """The tone's speed deviation (relative), as a flutter meter reads it."""
    y = y[int(0.5 * fs) :]
    sos = sps.butter(4, (0.7 * FLUTTER_HZ, 1.3 * FLUTTER_HZ), "bandpass", fs=fs, output="sos")
    z = sps.hilbert(sps.sosfiltfilt(sos, y))
    f = np.diff(np.unwrap(np.angle(z))) * fs / (2 * math.pi)
    n = int(0.1 * fs)
    eps = f[n:-n] / FLUTTER_HZ - 1.0
    return {
        "mean_pct": 100 * float(eps.mean()),
        "rms_0p5_250hz_pct": 100 * band_rms_fft(eps, fs, 0.5, 250.0),
        "rms_250hz_10khz_pct": 100 * band_rms_fft(eps, fs, 250.0, 1e4),
    }


def align(ref: np.ndarray, y: np.ndarray, max_lag: int) -> tuple[int, np.ndarray]:
    """y shifted (whole samples) to best match ref; the lag found."""
    c = sps.correlate(ref, y, mode="full", method="fft")
    mid = len(y) - 1
    w = c[mid - max_lag : mid + max_lag + 1]
    lag = int(np.argmax(w)) - max_lag
    return lag, np.roll(y, lag)


def profile_measures(outs: dict[str, np.ndarray], fs: int) -> dict:
    """tape_suite's measures from its renders (labels as its jobs')."""
    lv = np.array([ts._dbfs_rms(ta.level(outs[f"response {f} Hz"], fs, f)) for f in ts.RESPONSE_HZ])
    rel = lv - lv[list(ts.RESPONSE_HZ).index(1000)]
    rows = []
    for level_db in ts.THD_LEVELS_DB:
        y = outs[f"thd {level_db:+g} dB"]
        thd, h = ta.thd(y, fs, 400.0)
        rows.append(
            {
                "in_db_re_0vu": level_db,
                "out_dbfs_rms": ts._dbfs_rms(ta.level(y, fs, 400.0)),
                "thd_pct": 100 * thd,
                "h2_pct": 100 * float(h[1]),
                "h3_pct": 100 * float(h[2]),
            }
        )
    ins = np.array(ts.THD_LEVELS_DB)
    thd_db = 20 * np.log10([r["thd_pct"] for r in rows])
    out_db = np.array([r["out_dbfs_rms"] for r in rows])
    at = {}
    for pct in (1.0, 3.0):
        x = ts._crossing(ins, thd_db, 20 * math.log10(pct))
        at[f"{pct:g}pct"] = None if x is None else {
            "in_db_re_0vu": x, "out_dbfs_rms": float(np.interp(x, ins, out_db))
        }  # fmt: skip
    noise = 20 * math.log10(ts.band_rms(outs["noise"], fs, ts.NOISE_BAND_HZ) + 1e-30)
    three = at["3pct"]
    return {
        "response_re_1khz_db": dict(
            zip(map(str, ts.RESPONSE_HZ), np.round(rel, 3).tolist(), strict=False)
        ),
        "response_spread_db": [float(rel.min()), float(rel.max())],
        "thd": rows,
        "at": at,
        "noise_dbfs_rms": noise,
        "sn_db": None if three is None else three["out_dbfs_rms"] - noise,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--live-quality", default="draft-1x")
    ap.add_argument("--clip", default="drums_setmefree.wav")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--drive-db", type=float, nargs="+", default=[0.0, 6.0, 12.0])
    ap.add_argument("--only", nargs="+", default=["profile", "flutter", "program"])
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    al = ta.aligned()
    ov = al.overrides
    prod = TransientSettings.from_sim_settings(engine="circuitsim")
    prod_gpu = dataclasses.replace(prod, tape_gpu=True)
    live = TransientSettings.from_sim_settings(engine="circuitsim", quality=a.live_quality)
    fs = prod.sample_rate
    assert live.sample_rate == fs
    c_ins = spec.load_circuit(spec.circuit_path(INSERT))
    v_in, v_out = c_ins.full_scale
    res = spec.resolve(c_ins, {})
    for k, v in ov.items():  # the insert is the aligned machine
        if not math.isclose(float(res[k]), float(v), rel_tol=1e-12):
            raise SystemExit(f"{INSERT} is stale against the alignment ({k}): rerun make_351_echo")
    # The "core" (F1's deterministic core): the circuit's noise and the transport's flutter
    # off in both tiers. The flutter's random parts are drawn per sample of the tape stream's
    # own rate (the print's 192 kHz, the live tier's 96 kHz), so the two tiers flutter alike
    # in amount but not in realization, which decorrelates them above ~500 Hz.
    live_ir = {
        None: builder.build(c_ins, {}, cores=live.cores, events=True).ir,
        False: without_flutter(
            builder.build(c_ins, {}, cores=live.cores, noise=False, events=True).ir
        ),
    }
    prod_ir_quiet = without_flutter(builder.build(c_ins, {}, cores="ja", noise=False).ir)
    p = spec.resolve(c_ins, {})
    delay = int(round(p["head_distance_m"] / p["speed_m_s"] * fs))

    def run_live(x: np.ndarray, noise=None) -> np.ndarray:
        r = fast.run_transient(live_ir[noise], x * v_in, settings=live)
        return r.vectors["v(out)"] / v_out

    summary: dict = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "alignment_key": al.key,
        "live_quality": a.live_quality,
        "code": runner.code_version(),
    }

    # Signals: the profile's (labels as tape_suite's jobs), the flutter tone, the program.
    sigs: dict[str, np.ndarray] = {}
    if "profile" in a.only:
        for f in ts.RESPONSE_HZ:
            sigs[f"response {f} Hz"] = ts._tone(f, ts.RESPONSE_DB, fs)
        for lv in ts.THD_LEVELS_DB:
            sigs[f"thd {lv:+g} dB"] = ts._tone(400.0, lv, fs)
        sigs["noise"] = np.zeros(int((ts.MEASURE_FROM_S + ts.NOISE_S) * fs))
    if "flutter" in a.only:
        t = np.arange(int(FLUTTER_S * fs)) / fs
        amp = 10 ** ((ta.VU0_DBFS_RMS + FLUTTER_DB) / 20) * math.sqrt(2)
        sigs["flutter"] = amp * np.sin(2 * math.pi * FLUTTER_HZ * t) * np.minimum(1, t / 5e-3)
    clip = None
    if "program" in a.only:
        clip = load_audio(REPO_ROOT / "data" / "clips" / a.clip, fs)
        clip = clip[int(a.start * fs) : int((a.start + a.seconds) * fs)]
        xp = np.concatenate([clip, np.zeros(delay + int(TAIL_S * fs))])
        for d in a.drive_db:
            sigs[f"program {d:+g} dB"] = xp * 10 ** (d / 20)

    # The print: the profile's jobs through the runner's cache (CPU kernel, as the profile);
    # the flutter tone and the program on the GPU kernel; the noiseless program built here.
    prof = [k for k in sigs if k.startswith(("response", "thd", "noise"))]
    gpu = [k for k in sigs if k.startswith(("flutter", "program"))]
    print(f"print: {len(prof)} profile renders (cached?), {len(gpu)} on the GPU", flush=True)
    printed: dict[str, np.ndarray] = {}
    jobs = [runner.RenderJob(sigs[k], dict(ov), label=k, circuit=ta.CIRCUIT) for k in prof]
    for k, r in zip(prof, runner.render_many(jobs, settings=prod, max_jobs=a.jobs), strict=True):
        printed[k] = r.output
    jobs = [runner.RenderJob(sigs[k], dict(ov), label=k, circuit=ta.CIRCUIT) for k in gpu]
    for k, r in zip(gpu, runner.render_many(jobs, settings=prod_gpu, max_jobs=a.jobs), strict=True):
        printed[k] = r.output
    print(f"  print done ({time.time() - t0:.0f} s)", flush=True)

    quiet = [k for k in sigs if k.startswith("program")]

    def print_quiet(k: str) -> np.ndarray:
        r = fast.run_transient(prod_ir_quiet, sigs[k] * v_in, settings=prod_gpu)
        return r.vectors["v(out)"] / v_out

    with ThreadPoolExecutor(a.jobs) as ex:
        printed_quiet = dict(zip(quiet, ex.map(print_quiet, quiet), strict=True))
        t1 = time.time()
        lived = dict(zip(sigs, ex.map(lambda k: run_live(sigs[k]), sigs), strict=True))
        lived_quiet = dict(
            zip(quiet, ex.map(lambda k: run_live(sigs[k], False), quiet), strict=True)
        )
    live_wall = time.time() - t1
    n_live = sum(len(v) for v in sigs.values()) + sum(len(sigs[k]) for k in quiet)
    summary["live_x_real_time_parallel"] = live_wall / (n_live / fs)
    print(f"  live done ({time.time() - t0:.0f} s)", flush=True)

    m = int(ts.MEASURE_FROM_S * fs)
    if prof:
        summary["profile"] = {
            "print": profile_measures({k: printed[k][m:] for k in prof}, fs),
            "live": profile_measures({k: lived[k][m:] for k in prof}, fs),
        }
        pr, lv = summary["profile"]["print"], summary["profile"]["live"]
        d = [
            lv["response_re_1khz_db"][f] - pr["response_re_1khz_db"][f]
            for f in pr["response_re_1khz_db"]
        ]
        summary["profile"]["live_minus_print"] = {
            "response_worst_db": float(max(d, key=abs)),
            "sn_db": None if None in (lv["sn_db"], pr["sn_db"]) else lv["sn_db"] - pr["sn_db"],
            "noise_db": lv["noise_dbfs_rms"] - pr["noise_dbfs_rms"],
            "level_1pct_db": None
            if None in (lv["at"]["1pct"], pr["at"]["1pct"])
            else lv["at"]["1pct"]["in_db_re_0vu"] - pr["at"]["1pct"]["in_db_re_0vu"],
            "level_3pct_db": None
            if None in (lv["at"]["3pct"], pr["at"]["3pct"])
            else lv["at"]["3pct"]["in_db_re_0vu"] - pr["at"]["3pct"]["in_db_re_0vu"],
            "thd_db_per_level": [
                20 * math.log10(x["thd_pct"] / y["thd_pct"])
                for x, y in zip(lv["thd"], pr["thd"], strict=False)
            ],
        }
    if "flutter" in sigs:
        summary["flutter"] = {
            "print": flutter(printed["flutter"], fs),
            "live": flutter(lived["flutter"], fs),
        }

    import pyloudnorm
    import soundfile as sf

    meter = pyloudnorm.Meter(fs)
    prog = {}
    for k in quiet:
        d = float(k.split()[1])
        row = {}
        for tag, pv, lv_ in (
            ("noise", printed[k], lived[k]),
            ("core", printed_quiet[k], lived_quiet[k]),
        ):
            n = min(len(pv), len(lv_))
            pv, lv_ = pv[:n], lv_[:n]
            lag, la = align(pv, lv_, int(0.01 * fs))
            sl = slice(delay, n - int(0.05 * fs))
            pw, lw = pv[sl], la[sl]
            rms = math.sqrt(np.mean(pw**2))
            bands = third_octaves(lw, fs) - third_octaves(pw, fs)
            row[tag] = {
                "level_db": 20 * math.log10(math.sqrt(np.mean(lw**2)) / rms),
                "difference_db_re_rms": 20 * math.log10(math.sqrt(np.mean((lw - pw) ** 2)) / rms),
                "lag_samples": lag,
                "bands_db": dict(
                    zip((f"{b:.0f}" for b in BANDS_HZ), np.round(bands, 3).tolist(), strict=False)
                ),
                "worst_band_db": float(bands[np.argmax(np.abs(bands))]),
                "worst_band_hz": float(BANDS_HZ[np.argmax(np.abs(bands))]),
            }
            if tag == "noise":
                stem = Path(a.clip).stem
                y_p = pv[delay:]
                y_l = la[delay:]
                gain = meter.integrated_loudness(y_p) - meter.integrated_loudness(y_l)
                (OUT / "audio").mkdir(exist_ok=True)
                for name, y in (
                    (f"{stem}_print_{d:+.0f}dB", y_p),
                    (f"{stem}_live_{a.live_quality}_{d:+.0f}dB", y_l * 10 ** (gain / 20)),
                ):
                    sf.write(
                        OUT / "audio" / f"{name}.wav", y.astype(np.float32), fs, subtype="FLOAT"
                    )
                row[tag]["live_gain_to_match_lufs_db"] = gain
        prog[k] = row
    if prog:
        summary["program"] = prog
    summary["wall_s"] = time.time() - t0
    # Merged into the quality's summary: a run of some parts keeps the others'.
    path = OUT / f"summary_{a.live_quality}.json"
    summary = {**(json.loads(path.read_text()) if path.exists() else {}), **summary}
    path.write_text(json.dumps(summary, indent=1, default=float))
    _plot(summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("program",)}, indent=1, default=float
        )[:4000]
    )
    for k, row in prog.items():
        for tag, r in row.items():
            print(
                f"{k} [{tag}]: level {r['level_db']:+.2f} dB, "
                f"difference {r['difference_db_re_rms']:.1f} dB, "
                f"worst band {r['worst_band_db']:+.2f} dB at {r['worst_band_hz']:.0f} Hz, "
                f"lag {r['lag_samples']}"
            )
    return 0


def _plot(summary: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    if "profile" in summary:
        for tier, st in (("print", "-o"), ("live", "--s")):
            r = summary["profile"][tier]["response_re_1khz_db"]
            ax[0].semilogx([float(f) for f in r], list(r.values()), st, label=tier)
            rows = summary["profile"][tier]["thd"]
            ax[1].plot(
                [x["in_db_re_0vu"] for x in rows], [x["thd_pct"] for x in rows], st, label=tier
            )
        ax[0].axhspan(-2, 2, color="0.9")
        ax[0].set(title="Response re 1 kHz at -10 dB", xlabel="Hz", ylabel="dB")
        ax[1].set(title="400 Hz THD", xlabel="dB re 0 VU in", ylabel="%", yscale="log")
        ax[0].legend()
        ax[1].legend()
    for k, row in summary.get("program", {}).items():
        b = row["noise"]["bands_db"]
        ax[2].semilogx([float(f) for f in b], list(b.values()), label=f"{k.split()[1]} dB")
    ax[2].set(title="Program: live - print, third-octave bands", xlabel="Hz", ylabel="dB")
    ax[2].axhline(0, color="0.5", lw=0.5)
    ax[2].legend()
    fig.tight_layout()
    fig.savefig(OUT / f"tiers_{summary['live_quality']}.png", dpi=110)


if __name__ == "__main__":
    sys.exit(main())

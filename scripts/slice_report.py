"""Measure the vertical slice: compression curve, Time Constant attack/release, a program clip.

    uv run python scripts/slice_report.py [--tc 1 2 3 4] [--set key=value ...]
                                          [--engine ngspice|circuitsim] [--clip NAME]
    uv run --extra fast python scripts/slice_report.py --verify    # periodic agreement test

Renders come from the cache when `varimu render` already produced them with
the same settings, otherwise they run here. Plots and a JSON summary go to
reports/slice/ (summary.json for ngspice, summary_circuitsim.json for the fast
engine). A circuitsim run is also compared with the ngspice summary, when there
is one for the same overrides, against the circuit-sim plan's 670 behaviour
tolerances: gain reduction within 0.2 dB per step (and per 50 ms window of the
clip), CV times within 5%.

The program clip is data/clips/<--clip>, the user's own material: it is never
committed, and the clip is left out where it's missing. It runs at the
tolerance study's front panel (input pad 0 dB, threshold 0.8, TC2), where the
default clip compresses by up to ~6 dB.

--verify is the periodic check that the default engine (circuitsim) still
reproduces the reference engine (circuit-sim plan, M6). It renders the
report on both engines, plus the TC bursts and the clip on the ngspice
reference (gear, reltol 1e-4, 4x: the tolerance study's) and the clip on the
engine's converged solution (esdirk4 at 4x, error tolerance / 10), and checks
the plan's verification tolerances:

- behaviour, circuitsim vs production ngspice: the above;
- waveforms: output < -55 dB rms re signal and CV within 0.2 V, circuitsim vs
  the ngspice reference (bursts, clip) and vs the converged solution (clip).
  Production ngspice vs its reference is shown alongside, for scale.

Results go to reports/slice/agreement.json and agreement.png; the exit status
is 1 if a check fails. About 15 minutes from a cold cache (the ngspice
renders, in parallel); seconds when nothing changed since the last run.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import cache

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from varimu.config import DATA_DIR, REPO_ROOT, load_sim_settings  # noqa: E402
from varimu.listen.matching import gain_trace  # noqa: E402
from varimu.measure import metrics, signals  # noqa: E402
from varimu.sim import runner  # noqa: E402
from varimu.sim.io import TransientSettings, load_audio  # noqa: E402

OUT = REPO_ROOT / "reports" / "slice"
CLIP_DIR = DATA_DIR / "clips"
CLIP = "Arpeggio04b_120_m_D#_16b.WAV"
CLIP_FRONT_PANEL = {"input_atten_db": 0.0, "ac_threshold": 0.8, "time_constant": 2}
GAIN_WINDOW_S = 0.05

# The ngspice reference of the tolerance study and the circuit-sim plan's
# Verification table, as changes to production ngspice settings.
REFERENCE = {"method": "gear", "reltol": 1e-4, "oversample": 4}
# Circuit-sim plan, Verification: 670 slice and 670 behaviour rows.
TOLERANCE = {"gr_db": 0.2, "time_rel": 0.05, "out_rms_db": -55.0, "cv_v": 0.2}

# [MAN] p.4 (Fairchild 670 manual, 1959): attack, and release from 10 dB of limiting.
PUBLISHED = {
    1: (0.2e-3, 0.3),
    2: (0.2e-3, 0.8),
    3: (0.4e-3, 2.0),
    4: (0.4e-3, 5.0),
    5: (0.4e-3, 2.0),
    6: (0.2e-3, 0.3),
}


@cache
def _signal(name: str):
    st = load_sim_settings()
    spec = next(s for s in signals.default_library() if s.name == name)
    return signals.render(spec, sample_rate=st.sample_rate, seed=st.seed)


def _suffix(s: TransientSettings) -> str:
    return "" if s.engine == "ngspice" else f"_{s.engine}"


def converged(s: TransientSettings) -> TransientSettings:
    """circuitsim's converged solution (as tests/test_circuitsim_slice.py)."""
    return dataclasses.replace(
        s, oversample=4, error_abstol=s.error_abstol / 10, error_reltol=s.error_reltol / 10
    )


# --- Jobs ----------------------------------------------------------------------------------


def curve_job(overrides: dict) -> runner.RenderJob:
    return runner.RenderJob(_signal("steps_1000hz").samples, dict(overrides), "steps_1000hz")


def burst_jobs(tcs, overrides: dict) -> list[runner.RenderJob]:
    x = _signal("burst_1000hz_0dbfs").samples
    return [runner.RenderJob(x, {**overrides, "time_constant": tc}, f"burst_tc{tc}") for tc in tcs]


def clip_job(name: str, overrides: dict) -> runner.RenderJob | None:
    """The program clip at CLIP_FRONT_PANEL (overrides win), or None if it's missing."""
    path = CLIP_DIR / name
    if not name or not path.is_file():
        return None
    x = load_audio(path, load_sim_settings().sample_rate)
    return runner.RenderJob(x, {**CLIP_FRONT_PANEL, **overrides}, f"clip:{name}")


def prefetch(todo: list[tuple[TransientSettings, runner.RenderJob]]) -> None:
    """Run every (settings, job) render in parallel, filling the cache for the report."""
    n = min(runner.default_jobs(), len(todo))
    print(f"{len(todo)} renders, up to {n} in parallel (cached ones return at once)")
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(runner.render, j, settings=s): (s, j) for s, j in todo}
        for f in as_completed(futs):
            s, j = futs[f]
            r = f.result()
            how = "cached" if r.cached else f"{r.meta['wall_s']:.0f} s"
            print(f"  {j.label} [{s.engine} {s.method} {s.oversample}x]: {how}", flush=True)


# --- Report sections -------------------------------------------------------------------------


def compression_curve(overrides: dict, s: TransientSettings) -> dict:
    sig = _signal("steps_1000hz")
    r = runner.render(curve_job(overrides), settings=s)
    pts = metrics.segment_gains(sig.samples, r.output, sig.meta["segments"])
    lin, gain = np.array(pts).T
    gr = gain[0] - gain
    cv = [
        float(np.median(r.vectors["v(cv)"][s["stop"] - (s["stop"] - s["start"]) // 4 : s["stop"]]))
        for s in sig.meta["segments"]
    ]

    fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
    ax[0].plot(lin, lin + gain, "o-", ms=3, label="670 slice")
    ax[0].plot(lin, lin + gain[0], "--", c="gray", label="no compression")
    ax[0].set(xlabel="input (dBFS peak)", ylabel="output (dBFS peak)", title="Static curve, 1 kHz")
    ax[0].legend()
    ax[1].plot(lin, gr, "o-", ms=3)
    ax[1].set(xlabel="input (dBFS peak)", ylabel="gain reduction (dB)", title="Gain reduction")
    ax[2].plot(lin, cv, "o-", ms=3)
    ax[2].set(xlabel="input (dBFS peak)", ylabel="V", title="Control voltage (6386 grid CT)")
    for a in ax:
        a.grid(alpha=0.3)
    fig.suptitle(f"steps_1000hz  overrides={overrides or 'defaults'}  render {r.key[:12]}")
    fig.tight_layout()
    path = OUT / f"compression_curve{_suffix(s)}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return {
        "render": r.key[:12],
        "input_dbfs": lin.round(2).tolist(),
        "gain_db": gain.round(3).tolist(),
        "gain_reduction_db": gr.round(3).tolist(),
        "cv_v": np.round(cv, 3).tolist(),
        "gr_monotonic": bool(np.all(np.diff(gr) >= -0.05)),
        "plot": str(path.relative_to(REPO_ROOT)),
    }


def bursts(tcs, overrides: dict, s: TransientSettings) -> dict:
    sig = _signal("burst_1000hz_0dbfs")
    renders = runner.render_many(burst_jobs(tcs, overrides), settings=s)
    fs = renders[0].sample_rate
    a, b = sig.meta["burst_start"], sig.meta["burst_stop"]
    t = (np.arange(len(sig.samples)) - a) / fs
    fig, ax = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    gin = metrics.envelope_db(sig.samples, fs)
    rows = {}
    for tc, r in zip(tcs, renders, strict=True):
        cvt = metrics.cv_timing(r.vectors["v(cv)"], fs, a, b)
        gt = metrics.burst_timing(sig.samples, r.output, fs, a, b)
        pub_a, pub_r = PUBLISHED[tc]
        rows[tc] = {
            "render": r.key[:12],
            "cv_before_v": round(cvt.cv_before_v, 2),
            "cv_burst_v": round(cvt.cv_burst_v, 2),
            "gain_reduction_db": round(gt.gain_before_db - gt.gain_burst_db, 2),
            "attack_cv_63_ms": round(cvt.attack_s * 1e3, 3),
            "release_cv_63_s": round(cvt.release_63_s, 3),
            "release_cv_90_s": round(cvt.release_90_s, 3),
            "published_attack_ms": pub_a * 1e3,
            "published_release_s": pub_r,
        }
        ax[0].plot(t, metrics.envelope_db(r.output, fs) - gin, lw=1, label=f"TC{tc}")
        ax[1].plot(t, r.vectors["v(cv)"], lw=1, label=f"TC{tc}")
    ax[0].set(ylabel="gain (dB)", title="1 kHz burst, -40 -> 0 -> -40 dBFS", ylim=(-40, 15))
    ax[1].set(xlabel="time from burst start (s)", ylabel="control voltage (V)")
    for x in ax:
        x.axvline(0, c="gray", lw=0.5)
        x.axvline((b - a) / fs, c="gray", lw=0.5)
        x.grid(alpha=0.3)
        x.legend()
    fig.tight_layout()
    path = OUT / f"bursts{_suffix(s)}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return {"plot": str(path.relative_to(REPO_ROOT)), "by_time_constant": rows}


def program_clip(job: runner.RenderJob, s: TransientSettings) -> dict:
    """Gain over time (GAIN_WINDOW_S windows; NaN where the input is silent) and CV."""
    r = runner.render(job, settings=s)
    fs = r.sample_rate
    t, g = gain_trace(job.samples, r.output, fs, window_s=GAIN_WINDOW_S, points=len(job.samples))
    cv = r.vectors["v(cv)"]
    fig, ax = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    ax[0].plot(t, g, lw=1)
    ax[0].set(ylabel="gain (dB)", title=f"{job.label}  overrides={job.overrides}")
    ax[1].plot(np.arange(len(cv)) / fs, cv, lw=1)
    ax[1].set(xlabel="time (s)", ylabel="control voltage (V)")
    for a in ax:
        a.grid(alpha=0.3)
    fig.tight_layout()
    path = OUT / f"program_clip{_suffix(s)}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    finite = g[np.isfinite(g)]
    return {
        "render": r.key[:12],
        "clip": job.label,
        "overrides": job.overrides,
        "duration_s": round(len(job.samples) / fs, 3),
        "window_s": GAIN_WINDOW_S,
        "gain_db": [round(float(v), 3) if np.isfinite(v) else None for v in g],
        "gain_range_db": [round(float(finite.max()), 2), round(float(finite.min()), 2)],
        "cv_min_v": round(float(cv.min()), 2),
        "plot": str(path.relative_to(REPO_ROOT)),
    }


def compare(summary: dict, ref: dict) -> dict:
    """This summary against the ngspice one: worst gain-reduction difference per step
    (and per window of the clip), and each CV time's relative difference
    (circuit-sim plan: 0.2 dB, 5%)."""
    out: dict = {}
    gr = []
    if "compression_curve" in summary and "compression_curve" in ref:
        a = np.array(summary["compression_curve"]["gain_reduction_db"])
        b = np.array(ref["compression_curve"]["gain_reduction_db"])
        out["gr_max_diff_db"] = round(float(np.max(np.abs(a - b))), 3)
        gr.append(out["gr_max_diff_db"])
    pa, pb = summary.get("program_clip"), ref.get("program_clip")
    if pa and pb and (pa["clip"], pa["overrides"]) == (pb["clip"], pb["overrides"]):
        a = np.array(pa["gain_db"], float)  # None -> nan
        b = np.array(pb["gain_db"], float)
        ok = np.isfinite(a) & np.isfinite(b)
        out["clip_gain_max_diff_db"] = round(float(np.max(np.abs(a[ok] - b[ok]))), 3)
        gr.append(out["clip_gain_max_diff_db"])
    times = {}
    for tc, row in summary["bursts"]["by_time_constant"].items():
        r = ref["bursts"]["by_time_constant"].get(str(tc))
        if r is None:
            continue
        times[tc] = {
            k: round(row[k] / r[k] - 1, 4)
            for k in ("attack_cv_63_ms", "release_cv_63_s", "release_cv_90_s")
        }
        times[tc]["gain_reduction_db"] = round(row["gain_reduction_db"] - r["gain_reduction_db"], 3)
        gr.append(abs(times[tc]["gain_reduction_db"]))
    out["burst_relative_time_diff"] = times
    worst = max(
        (abs(v[k]) for v in times.values() for k in v if k != "gain_reduction_db"), default=0.0
    )
    out["passes"] = bool(max(gr, default=0.0) <= TOLERANCE["gr_db"])
    out["passes"] &= bool(worst <= TOLERANCE["time_rel"])
    return out


def report(overrides: dict, tcs, s: TransientSettings, clip, skip_curve=False) -> dict:
    """Every section on `s`'s engine; writes summary{_engine}.json and the plots."""
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict = {"overrides": overrides}
    if not skip_curve:
        summary["compression_curve"] = compression_curve(overrides, s)
    summary["bursts"] = bursts(tcs, overrides, s)
    if clip is not None:
        summary["program_clip"] = program_clip(clip, s)
    reference = OUT / "summary.json"
    if s.engine != "ngspice" and reference.exists():
        ref = json.loads(reference.read_text(encoding="utf-8"))
        if ref.get("overrides") == overrides:
            summary["vs_ngspice"] = compare(summary, ref)
    path = OUT / f"summary{_suffix(s)}.json"
    path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


# --- Verification ------------------------------------------------------------------------------


def waveform_diff(a: runner.Render, ref: runner.Render) -> dict:
    """Output rms error in dB re the reference's output, and the worst CV difference."""
    d = np.std(a.output - ref.output) / np.std(ref.output)
    cv = np.max(np.abs(a.vectors["v(cv)"] - ref.vectors["v(cv)"]))
    return {"out_rms_db": round(float(20 * np.log10(d)), 1), "cv_max_v": round(float(cv), 4)}


def verify(overrides: dict, tcs, clip_name: str) -> int:
    from varimu.sim import fast

    fast.check_build()  # fail before an hour of ngspice if the engine is missing or stale
    ng = TransientSettings.from_sim_settings(engine="ngspice")
    cs = TransientSettings.from_sim_settings(engine="circuitsim")
    ref, conv = dataclasses.replace(ng, **REFERENCE), converged(cs)
    curve, bjobs = curve_job(overrides), burst_jobs(tcs, overrides)
    clip = clip_job(clip_name, overrides)
    if clip is None:
        print(f"program clip {clip_name!r} not in {CLIP_DIR}: left out")
    clips = [clip] if clip else []
    # Longest first: the ngspice reference, then ngspice production, then circuitsim.
    todo = [(ref, j) for j in bjobs + clips]
    todo += [(s, j) for s in (ng, cs) for j in [curve, *bjobs, *clips]]
    todo += [(conv, j) for j in clips]
    prefetch(todo)

    ng_summary = report(overrides, tcs, ng, clip)
    cs_summary = report(overrides, tcs, cs, clip)
    behaviour = cs_summary.get("vs_ngspice") or compare(cs_summary, ng_summary)

    waveforms: dict = {}
    pairs = [(f"burst_tc{tc}", j) for tc, j in zip(tcs, bjobs, strict=True)]
    pairs += [("program_clip", j) for j in clips]
    traces = {}
    for name, j in pairs:
        r_cs, r_ng, r_ref = (runner.render(j, settings=s) for s in (cs, ng, ref))
        waveforms[name] = {
            "circuitsim_vs_reference": waveform_diff(r_cs, r_ref),
            "ngspice_vs_reference": waveform_diff(r_ng, r_ref),
        }
        traces[name] = [("vs ngspice reference", r_cs.vectors["v(cv)"] - r_ref.vectors["v(cv)"])]
        if name == "program_clip":
            r_conv = runner.render(j, settings=conv)
            waveforms[name]["circuitsim_vs_converged"] = waveform_diff(r_cs, r_conv)
            traces[name].append(("vs converged", r_cs.vectors["v(cv)"] - r_conv.vectors["v(cv)"]))

    def ok(d: dict) -> bool:
        return d["out_rms_db"] < TOLERANCE["out_rms_db"] and d["cv_max_v"] < TOLERANCE["cv_v"]

    wf_pass = all(ok(d) for w in waveforms.values() for k, d in w.items() if k.startswith("circ"))
    passes = bool(behaviour["passes"] and wf_pass)
    result = {
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine_build": fast.check_build(),
        "overrides": overrides,
        "program_clip": clip.label if clip else None,
        "tolerance": TOLERANCE,
        "reference": REFERENCE,
        "behaviour_vs_ngspice": behaviour,
        "waveforms": waveforms,
        "passes": passes,
    }
    (OUT / "agreement.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    _plot_agreement(traces)

    print("\nBehaviour, circuitsim vs ngspice (tolerance: 0.2 dB, 5%):")
    print(f"  compression curve GR: {behaviour.get('gr_max_diff_db')} dB max")
    if "clip_gain_max_diff_db" in behaviour:
        print(f"  clip gain per {GAIN_WINDOW_S * 1e3:.0f} ms: "
              f"{behaviour['clip_gain_max_diff_db']} dB max")  # fmt: skip
    for tc, v in behaviour["burst_relative_time_diff"].items():
        t = ", ".join(f"{k} {v[k]:+.2%}" for k in v if k != "gain_reduction_db")
        print(f"  TC{tc}: {t}; GR {v['gain_reduction_db']:+.3f} dB")
    print("Waveforms (tolerance: < -55 dB rms re signal, CV < 0.2 V):")
    for name, w in waveforms.items():
        for k, d in w.items():
            mark = "" if not k.startswith("circ") else ("  ok" if ok(d) else "  FAIL")
            print(f"  {name:13s} {k:24s} {d['out_rms_db']:6.1f} dB  CV {d['cv_max_v']:.4f} V{mark}")
    print(f"\n{'PASS' if passes else 'FAIL'} -> {(OUT / 'agreement.json').relative_to(REPO_ROOT)}")
    return 0 if passes else 1


def _plot_agreement(traces: dict) -> None:
    fs = load_sim_settings().sample_rate
    fig, ax = plt.subplots(len(traces), 1, figsize=(11, 2.2 * len(traces)), squeeze=False)
    for a, (name, rows) in zip(ax[:, 0], traces.items(), strict=True):
        for label, d in rows:
            a.plot(np.arange(len(d)) / fs, d, lw=0.8, label=label)
        a.set(ylabel="CV diff (V)", title=f"{name}: circuitsim's CV minus the other run's")
        a.grid(alpha=0.3)
        a.legend(loc="upper right")
    ax[-1, 0].set(xlabel="time (s)")
    fig.tight_layout()
    fig.savefig(OUT / "agreement.png", dpi=100)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tc", nargs="+", type=int, default=[1, 2, 3, 4])
    ap.add_argument("--set", nargs="+", default=[], metavar="KEY=VALUE")
    ap.add_argument("--skip-curve", action="store_true")
    ap.add_argument("--engine", choices=["ngspice", "circuitsim"], help="default: configured")
    ap.add_argument("--clip", default=CLIP, help="program clip in data/clips ('' skips it)")
    ap.add_argument(
        "--verify",
        action="store_true",
        help="both engines and the references, checked against the plan's tolerances",
    )
    args = ap.parse_args()
    ov = runner.parse_overrides(args.set)
    if args.verify:
        if args.engine or args.skip_curve:
            ap.error("--verify runs every section on both engines")
        sys.exit(verify(ov, args.tc, args.clip))
    s = TransientSettings.from_sim_settings(engine=args.engine or "configured")
    summary = report(ov, args.tc, s, clip_job(args.clip, ov), skip_curve=args.skip_curve)
    print(json.dumps(summary, indent=1)[:4000])


if __name__ == "__main__":
    main()

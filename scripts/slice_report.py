"""Measure the vertical slice: compression curve, Time Constant attack/release, a program clip.

    uv run python scripts/slice_report.py [--tc 1 2 3 4] [--set key=value ...]
                                          [--engine ngspice|circuitsim] [--clip NAME]
    uv run --extra fast python scripts/slice_report.py --verify    # periodic agreement test

Renders come from the cache when they already ran with the same settings,
otherwise they run here. Plots and a JSON summary go to reports/slice/
(summary.json for ngspice, summary_circuitsim.json for the fast engine with
its Jiles-Atherton cores, summary_circuitsim_linear.json with the cores in
their linear limit). A circuitsim run is also compared with the ngspice
summary, when there is one for the same overrides and core model (ngspice
always runs linear cores: there is no SPICE core, decided 2026-10-21),
against the circuit-sim plan's 670 behaviour tolerances: gain reduction
within 0.2 dB per step (and per 50 ms window of the clip), CV times within
5%.

The compression curve's staircase (51 steps of 0.5 s) runs as parallel chunks
of CURVE_CHUNK steps, each from the operating point with CURVE_WARMUP step(s)
before it, whose gains are dropped. Every step settles well within its 0.5 s
and levels only rise, so this is the continuous staircase's curve (measured
2026-10-21: within 3e-6 dB on circuitsim; --verify keeps checking it), and
ngspice's 13-minute staircase takes ~2.

The program clip is data/clips/<--clip>, the user's own material: it is never
committed, and the clip is left out where it's missing. It runs at the
tolerance study's front panel (input pad 0 dB, threshold 0.8, TC2), where the
default clip compresses by up to ~6 dB.

--verify is the periodic check that the default engine (circuitsim) still
agrees with the reference engine (circuit-sim plan, Verification and M6's
follow-up). It renders the report on both engines and checks:

- behaviour, circuitsim vs production ngspice, both with linear cores: the
  tolerances above;
- waveforms vs ngspice with the exact triode formulation (gear, reltol 1e-4,
  4x), the independent cross-check, on short excerpts, both with linear
  cores: a 0.1 s 0 dBFS burst at each Time Constant (onset and 0.15 s of
  release) and 0.25 s of the clip at its loudest window (the deepest CV) and
  its HF-richest one;
- the whole clip vs circuitsim's converged solution (esdirk4 at 4x, error
  tolerance / 10), with the Jiles-Atherton cores (production);
- the chunked staircase vs the continuous one, on circuitsim (Jiles-Atherton).

It also renders the report on circuitsim with the Jiles-Atherton cores, the
production circuit, for its plots and summary.

Waveform rows pass at the plan's tolerance (output < -55 dB rms re signal, CV
within 0.2 V) and, at the default front panel and clip, within regression
bounds a few dB outside the measured values. Results go to
reports/slice/agreement.json and agreement.png; the exit status is 1 if a
check fails. About 70 minutes from a cold cache since Phase 3's power
supply (all renders in parallel; it was ~6 minutes before), a minute when
nothing changed.
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
from scipy.signal import butter, sosfilt  # noqa: E402

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
CURVE_CHUNK = 6  # staircase steps per render
CURVE_WARMUP = 1  # steps rendered before each chunk and not measured

# Circuit-sim plan, Verification: 670 slice and 670 behaviour rows.
TOLERANCE = {"gr_db": 0.2, "time_rel": 0.05, "out_rms_db": -55.0, "cv_v": 0.2}
CHUNKING_TOLERANCE_DB = 0.01  # chunked vs continuous staircase, GR per step

# The excerpts' reference: ngspice with the exact triode formulation, at the
# tolerance study's reference settings, as changes to production ngspice.
# Production's trap 2x fails the HF clip excerpt on its own error (-50 dB).
EXACT = {"method": "gear", "reltol": 1e-4, "oversample": 4, "triode_formulation": "exact"}
EXCERPT_BURST = dict(
    freq_hz=1000, base_dbfs=-40, burst_dbfs=0, pre_s=0.02, burst_s=0.1, release_s=0.15
)
CLIP_EXCERPT_S = (0.15, 0.1)  # excerpt from this long before the chosen 0.1 s window to its end
CLIP_HF_HZ = 5000  # "HF-rich": the most energy above this
FADE_IN_S = 0.01  # raised cosine, so a clip excerpt starts from the operating point smoothly
# The excerpts compare two engines from the same DC operating point, so they skip the
# power supply's settling (start.settle_s, ~800 x 1 s of exact ngspice per excerpt): both
# run the supply's start from the mains peak, the same transient in both.
EXCERPT_SETTLE_S = 0.0

# Regression bounds (rms dB re signal, CV V) at the default front panel and
# clip, a few dB outside the values measured 2026-10-23: T103 at 8.5, the tapped
# AC THRESHOLD pots and the factory-adjusted default panel (VARIMU_PROJECT_PLAN.md,
# Phase 3), and circuitsim's step selection with the ports-and-states error norm
# (CIRCUIT_SIM_PLAN.md, "Speed after Phase 3"); circuitsim production vs exact
# ngspice, both on linear cores; the converged row on the Jiles-Atherton cores.
# Re-measure when the circuit changes.
#   burst_tc1 -81.9 / 0.0036    burst_tc2 -82.5 / 0.0029
#   burst_tc3 -84.4 / 0.0022    burst_tc4 -85.4 / 0.0019
#   clip_loudest -76.2 / 0.0049    clip_hf -71.3 / 0.0055
#   clip vs converged -77.2 / 0.070 (Phase 3: -56.8 / 0.19, at the plan's tolerance;
#   10x tighter error tolerances now give -78.5 / 0.040, 4x -83.9 / 0.007)
# (Phase 3, 2026-10-22: -80.9 / 0.0029, -81.9 / 0.0022, -84.9 / 0.0015,
# -85.2 / 0.0018; -76.2 / 0.0035, -70.8 / 0.0052; -56.8 / 0.1945.)
BOUNDS = {
    "burst_tc1": (-78.0, 0.01),
    "burst_tc2": (-79.0, 0.01),
    "burst_tc3": (-81.0, 0.01),
    "burst_tc4": (-82.0, 0.01),
    "clip_loudest": (-73.0, 0.01),
    "clip_hf": (-68.0, 0.015),
    "clip_vs_converged": (-73.0, 0.15),
}

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
    if s.engine == "ngspice":
        return ""
    return f"_{s.engine}" + ("_linear" if s.cores == "linear" else "")


def converged(s: TransientSettings) -> TransientSettings:
    """circuitsim's converged solution (as tests/test_circuitsim_slice.py)."""
    return dataclasses.replace(
        s, oversample=4, error_abstol=s.error_abstol / 10, error_reltol=s.error_reltol / 10
    )


# --- Jobs ----------------------------------------------------------------------------------


def curve_job(overrides: dict) -> runner.RenderJob:
    """The continuous staircase (--verify checks the chunks against it)."""
    return runner.RenderJob(_signal("steps_1000hz").samples, dict(overrides), "steps_1000hz")


def curve_chunks(overrides: dict) -> list[tuple[runner.RenderJob, list[dict]]]:
    """The staircase as (job, its measured segments in job samples), CURVE_CHUNK steps each."""
    sig = _signal("steps_1000hz")
    segs = sig.meta["segments"]
    out = []
    for i0 in range(0, len(segs), CURVE_CHUNK):
        i1 = min(i0 + CURVE_CHUNK, len(segs))
        a, b = segs[max(0, i0 - CURVE_WARMUP)]["start"], segs[i1 - 1]["stop"]
        local = [dict(s, start=s["start"] - a, stop=s["stop"] - a) for s in segs[i0:i1]]
        job = runner.RenderJob(sig.samples[a:b], dict(overrides), f"steps_1000hz[{i0}:{i1}]")
        out.append((job, local))
    return out


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


def excerpt_jobs(tcs, overrides: dict, clip: runner.RenderJob | None) -> dict:
    """--verify's short excerpts, name -> job: a burst per Time Constant (EXCERPT_BURST),
    and the clip's loudest and HF-richest 0.1 s windows with CLIP_EXCERPT_S around them."""
    fs = load_sim_settings().sample_rate
    burst = signals.tone_burst(**EXCERPT_BURST, sample_rate=fs).samples
    out = {
        f"burst_tc{tc}": runner.RenderJob(
            burst, {**overrides, "time_constant": tc}, f"excerpt:burst_tc{tc}"
        )
        for tc in tcs
    }
    if clip is None:
        return out
    x = clip.samples
    w, before, after = fs // 10, int(CLIP_EXCERPT_S[0] * fs), int(CLIP_EXCERPT_S[1] * fs)
    starts = np.arange(before, len(x) - after + 1, fs // 40)
    hp = sosfilt(butter(4, CLIP_HF_HZ, "hp", fs=fs, output="sos"), x)
    fade = 0.5 - 0.5 * np.cos(np.pi * np.arange(int(FADE_IN_S * fs)) / int(FADE_IN_S * fs))
    for name, v in (("clip_loudest", x), ("clip_hf", hp)):
        c = np.concatenate([[0.0], np.cumsum(v**2)])
        a = int(starts[np.argmax(c[starts + w] - c[starts])])
        y = x[a - before : a + after].copy()
        y[: len(fade)] *= fade
        label = f"excerpt:{name}:{clip.label}@{(a - before) / fs:.3f}-{(a + after) / fs:.3f}s"
        out[name] = runner.RenderJob(y, dict(clip.overrides), label)
    return out


def _cost(s: TransientSettings, j: runner.RenderJob) -> float:
    """Rough wall time (x slower than real time per oversampling), to start the longest first."""
    if s.engine == "ngspice":
        x = 200.0 if s.triode_formulation == "exact" else 15.0
    else:
        x = 3.0 * s.oversample / 2
    return len(j.samples) * s.oversample * x


def prefetch(todo: list[tuple[TransientSettings, runner.RenderJob]]) -> None:
    """Run every (settings, job) render in parallel, longest first, filling the cache."""
    todo = sorted(todo, key=lambda sj: -_cost(*sj))
    n = min(runner.default_jobs(), len(todo))
    print(f"{len(todo)} renders, up to {n} in parallel (cached ones return at once)")
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(runner.render, j, settings=s): (s, j) for s, j in todo}
        for f in as_completed(futs):
            s, j = futs[f]
            r = f.result()
            how = "cached" if r.cached else f"{r.meta['wall_s']:.0f} s"
            tag = f"{s.engine} {s.method} {s.oversample}x"
            tag += " exact" if s.engine == "ngspice" and s.triode_formulation == "exact" else ""
            print(f"  {j.label} [{tag}]: {how}", flush=True)


# --- Report sections -------------------------------------------------------------------------


def _curve_points(x: np.ndarray, r: runner.Render, segs: list[dict]):
    """(input dBFS, gain dB) per segment, and the CV's median over each segment's last quarter."""
    pts = metrics.segment_gains(x, r.output, segs)
    v = r.vectors["v(cv)"]
    cv = [float(np.median(v[s["stop"] - (s["stop"] - s["start"]) // 4 : s["stop"]])) for s in segs]
    return pts, cv


def curve_gains(overrides: dict, s: TransientSettings, chunked: bool = True):
    """The staircase's input levels, gains and CVs per step, and the render keys."""
    if chunked:
        parts = curve_chunks(overrides)
    else:
        parts = [(curve_job(overrides), _signal("steps_1000hz").meta["segments"])]
    renders = runner.render_many([j for j, _ in parts], settings=s)
    pts, cv = [], []
    for (j, segs), r in zip(parts, renders, strict=True):
        p, c = _curve_points(j.samples, r, segs)
        pts += p
        cv += c
    lin, gain = np.array(pts).T
    return lin, gain, np.array(cv), [r.key[:12] for r in renders]


def compression_curve(overrides: dict, s: TransientSettings) -> dict:
    lin, gain, cv, keys = curve_gains(overrides, s)
    gr = gain[0] - gain

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
    fig.suptitle(f"steps_1000hz  overrides={overrides or 'defaults'}  {s.engine}")
    fig.tight_layout()
    path = OUT / f"compression_curve{_suffix(s)}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return {
        "renders": keys,
        "chunk_steps": CURVE_CHUNK,
        "warmup_steps": CURVE_WARMUP,
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
    summary: dict = {"overrides": overrides, "cores": s.cores}
    if not skip_curve:
        summary["compression_curve"] = compression_curve(overrides, s)
    summary["bursts"] = bursts(tcs, overrides, s)
    if clip is not None:
        summary["program_clip"] = program_clip(clip, s)
    reference = OUT / "summary.json"
    if s.engine != "ngspice" and reference.exists():
        ref = json.loads(reference.read_text(encoding="utf-8"))
        if ref.get("overrides") == overrides and ref.get("cores", "linear") == s.cores:
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

    fast.check_build()  # fail before the ngspice renders if the engine is missing or stale
    ng = TransientSettings.from_sim_settings(engine="ngspice")
    cs = TransientSettings.from_sim_settings(engine="circuitsim")  # Jiles-Atherton cores
    # ngspice has no core model: circuitsim meets it on linear cores
    cs_lin = dataclasses.replace(cs, cores="linear")
    exact, conv = dataclasses.replace(ng, **EXACT), converged(cs)
    exact = dataclasses.replace(exact, settle_s=EXCERPT_SETTLE_S)
    cs_ex = dataclasses.replace(cs_lin, settle_s=EXCERPT_SETTLE_S)
    clip = clip_job(clip_name, overrides)
    if clip is None:
        print(f"program clip {clip_name!r} not in {CLIP_DIR}: left out")
    clips = [clip] if clip else []
    excerpts = excerpt_jobs(tcs, overrides, clip)
    # Regression bounds were measured at the default front panel and clip.
    bounded = not overrides and clip_name == CLIP
    report_jobs = [j for j, _ in curve_chunks(overrides)] + burst_jobs(tcs, overrides) + clips
    todo = [(exact, j) for j in excerpts.values()]
    todo += [(s, j) for s in (ng, cs_lin, cs) for j in report_jobs]
    todo += [(cs_ex, j) for j in excerpts.values()]
    todo += [(conv, j) for j in clips] + [(cs, curve_job(overrides))]
    prefetch(todo)

    ng_summary = report(overrides, tcs, ng, clip)
    lin_summary = report(overrides, tcs, cs_lin, clip)
    report(overrides, tcs, cs, clip)  # the production circuit's plots and summary
    behaviour = lin_summary.get("vs_ngspice") or compare(lin_summary, ng_summary)

    _, g_chunk, _, _ = curve_gains(overrides, cs)
    _, g_cont, _, _ = curve_gains(overrides, cs, chunked=False)
    chunking_db = float(np.max(np.abs((g_chunk[0] - g_chunk) - (g_cont[0] - g_cont))))
    chunking = {
        "gr_max_diff_db": float(f"{chunking_db:.2g}"),
        "tolerance_db": CHUNKING_TOLERANCE_DB,
        "passes": chunking_db <= CHUNKING_TOLERANCE_DB,
    }

    waveforms: dict = {}
    traces = {}
    for name, j in excerpts.items():
        r_cs, r_ex = runner.render(j, settings=cs_ex), runner.render(j, settings=exact)
        waveforms[name] = {
            "excerpt": j.label,
            "reference": "exact ngspice (linear)",
            **waveform_diff(r_cs, r_ex),
            "cv_min_v": round(float(r_cs.vectors["v(cv)"].min()), 2),
        }
        traces[name] = r_cs.vectors["v(cv)"] - r_ex.vectors["v(cv)"]
    if clip:
        r_cs, r_conv = runner.render(clip, settings=cs), runner.render(clip, settings=conv)
        waveforms["clip_vs_converged"] = {
            "excerpt": clip.label,
            "reference": "circuitsim converged",
            **waveform_diff(r_cs, r_conv),
            "cv_min_v": round(float(r_cs.vectors["v(cv)"].min()), 2),
        }
        traces["clip_vs_converged"] = r_cs.vectors["v(cv)"] - r_conv.vectors["v(cv)"]
    for name, d in waveforms.items():
        d["passes"] = (
            d["out_rms_db"] < TOLERANCE["out_rms_db"] and d["cv_max_v"] < TOLERANCE["cv_v"]
        )
        if bounded and name in BOUNDS:
            d["bound"] = BOUNDS[name]
            d["passes"] &= d["out_rms_db"] < BOUNDS[name][0] and d["cv_max_v"] < BOUNDS[name][1]

    passes = bool(behaviour["passes"] and chunking["passes"])
    passes &= all(d["passes"] for d in waveforms.values())
    result = {
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine_build": fast.check_build(),
        "overrides": overrides,
        "program_clip": clip.label if clip else None,
        "tolerance": TOLERANCE,
        "excerpt_reference": EXACT,
        "behaviour_vs_ngspice": behaviour,
        "curve_chunking": chunking,
        "waveforms": waveforms,
        "passes": passes,
    }
    (OUT / "agreement.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    _plot_agreement(traces)

    print("\nBehaviour, circuitsim vs ngspice, linear cores (tolerance: 0.2 dB, 5%):")
    print(f"  compression curve GR: {behaviour.get('gr_max_diff_db')} dB max")
    if "clip_gain_max_diff_db" in behaviour:
        print(f"  clip gain per {GAIN_WINDOW_S * 1e3:.0f} ms: "
              f"{behaviour['clip_gain_max_diff_db']} dB max")  # fmt: skip
    for tc, v in behaviour["burst_relative_time_diff"].items():
        t = ", ".join(f"{k} {v[k]:+.2%}" for k in v if k != "gain_reduction_db")
        print(f"  TC{tc}: {t}; GR {v['gain_reduction_db']:+.3f} dB")
    print(f"Chunked vs continuous staircase (circuitsim): {chunking['gr_max_diff_db']} dB max"
          f"{'' if chunking['passes'] else '  FAIL'}")  # fmt: skip
    print("Waveforms (tolerance: < -55 dB rms re signal, CV < 0.2 V; [regression bound]):")
    for name, d in waveforms.items():
        b = f"[{d['bound'][0]:.0f} dB, {d['bound'][1]} V]" if "bound" in d else ""
        print(f"  {name:17s} vs {d['reference']:20s} {d['out_rms_db']:6.1f} dB  "
              f"CV {d['cv_max_v']:.4f} V  {b:16s}{'ok' if d['passes'] else 'FAIL'}")  # fmt: skip
    if not bounded:
        print("  (regression bounds apply at the default front panel and clip only)")
    print(f"\n{'PASS' if passes else 'FAIL'} -> {(OUT / 'agreement.json').relative_to(REPO_ROOT)}")
    return 0 if passes else 1


def _plot_agreement(traces: dict) -> None:
    fs = load_sim_settings().sample_rate
    fig, ax = plt.subplots(len(traces), 1, figsize=(11, 1.9 * len(traces)), squeeze=False)
    for a, (name, d) in zip(ax[:, 0], traces.items(), strict=True):
        a.plot(np.arange(len(d)) / fs, d, lw=0.8)
        other = "converged solution" if name.endswith("converged") else "exact ngspice"
        a.set(ylabel="CV diff (V)", title=f"{name}: circuitsim's CV minus {other}'s")
        a.grid(alpha=0.3)
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

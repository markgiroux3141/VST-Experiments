"""The guitar amplifier profile's measurements (device builder B9 step 4): the Fender 5E3.

    report = run(name, genome)     # varimu unit --circuit fender_5e3 --name NAME

A unit is the circuit file with the genome's overrides (no setup procedure: the 5E3 has
no trims). Levels are volts at the input jack (the circuit's full scale: 0 dBFS is 1 V
peak, a hot pickup) and at the speaker's terminals (`out`); power is what the speaker's
electrical equivalent takes (`speaker_power_w`: from v(out) and the load's admittance,
the file's linear Re, Le and motional RLC), with the 8 ohm nominal figure V^2 / 8 beside
it. The
bright channel is input 1 of its pair (input_jack 1), the normal one input 3; the other
channel's volume is at 0. Sections:

- screen (varimu.measure.generic, then the profile's own): an idle render (the speaker
  quiet, B+1..3 within the drawing's +-20% of the kit's published voltages:
  data/schematics/fender_5e3/README.md) and a small 1 kHz tone at half volume (no
  oscillation riding on it);
- gain: 1 kHz at SMALL_V, each channel at each volume in VOLUMES (V/V, dB);
- response: the small-signal response (a multitone, MULTI_V per tone) at half volume,
  each channel at each tone setting in TONE_SETTINGS, out / in (dB);
- distortion: 1 kHz from DIST_DBV_PEAK in (dB re 1 V peak) on the bright channel at
  DIST_VOLUMES: THD, H2 / H3, the speaker's power; the clipping onset (the input and
  power where THD first reaches ONSET_THD_PCT) and the most power;
- sag: a burst (SAG_V peak, at 82.4 Hz and 1 kHz) at SAG_VOLUME: B+1..3 and the output
  tubes' cathode over time (each averaged over one mains period), the drop at the
  burst's end, recovery to 63% after it, and the output's fall over the burst
  (the sag's compression);
- aliasing: a hard-driven ALIAS_HZ tone at the run's quality and at circuitsim's
  draft and draft-1x: power in 300 Hz - 20 kHz away from the tone's harmonics and their
  mains sidebands (+-HARMONIC_GUARD_HZ), re the harmonics' power. Hum intermodulation
  further out counts as aliasing too: compare qualities, not the absolute figure.

Results: reports/units/<name>/report.json, gain.png, response.png, distortion.png,
sag.png, aliasing.png. Not modelled: noise (B5), the physical speaker (C3: until then
the speaker's terminal voltage serves for checks only, the user's decision).
"""

from __future__ import annotations

import datetime as dt
import functools
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

CIRCUIT = "fender_5e3"
REPORT_DIR = REPO_ROOT / "reports" / "units"

# Amplified Parts' kit with its reproduction transformers (README, "Published
# voltages"); the drawing's notice box: "values shown + or - 20 %".
KIT_V = {"b1": 370.0, "b2": 325.5, "b3": 240.8}
RAIL_PCT = 20.0
REPORTED_V = {"k6": 21.1, "p3": 195.1, "k3": 45.9, "p2": 157.7, "k2": 1.22}
CHANNELS = {
    "bright": {"input_jack": 1, "volume": "volume_bright", "other": "volume_normal"},
    "normal": {"input_jack": 3, "volume": "volume_normal", "other": "volume_bright"},
}
NOMINAL_VOLUME = 0.5
NOMINAL_V = 0.01  # V peak: clean at half volume (~1 V at the speaker)
IDLE_S, IDLE_WINDOW_S, RAIL_AVG_S = 0.5, (0.1, 0.5), 0.1

RISE_S, HOLD_S, MEASURE_S = 0.05, 0.25, 0.1  # tones: rise, hold, the window at the end
SMALL_V = 3e-3  # V peak: clean at full volume (~3 V at the speaker)
VOLUMES = tuple(round(0.1 * k, 1) for k in range(1, 11))

TONES = np.unique(np.round(np.geomspace(40.0, 16000.0, 31) / 2.0) * 2.0)  # 2 Hz bins
MULTI_V = 2e-4  # V peak per tone
TONE_SETTINGS = (0.0, 0.25, 0.5, 0.75, 1.0)
PRE_S, WIN_S = 0.3, 0.5

DIST_DBV_PEAK = tuple(float(x) for x in np.arange(-48.0, 1.0, 3.0))
DIST_VOLUMES = (0.25, 0.5, 1.0)
ONSET_THD_PCT = 1.0

SPEAKER = ("spk_re_ohm", "spk_le_h", "spk_res_ohm", "spk_lces_h", "spk_cmes_f")

SAG_V, SAG_VOLUME = 0.5, 0.75
SAG_HZ = (82.4, 1000.0)  # the guitar's low E, and a tone
SAG_PRE_S, SAG_BURST_S, SAG_POST_S = 0.3, 1.0, 1.5
SAG_NODES = ("b1", "b2", "b3", "k6")

ALIAS_HZ = 2902.0  # even: whole periods in WIN_S; off the mains' grid (module docstring)
ALIAS_V, ALIAS_VOLUME = 0.5, 1.0
ALIAS_QUALITIES = ("draft", "draft-1x")
HARMONIC_GUARD_HZ = 260.0  # four 60 Hz sidebands and a bin's leakage
ALIAS_BAND_HZ = (300.0, 20000.0)


@functools.cache
def _input_v_per_fs() -> float:
    """The circuit's volts at full scale in (its file's `full_scale`)."""
    s = TransientSettings.from_sim_settings()
    return full_scale(s, spec.load_circuit(spec.circuit_path(CIRCUIT)))[0]


def channel(name: str, volume: float, **ov) -> dict[str, Any]:
    c = CHANNELS[name]
    return {"input_jack": c["input_jack"], c["volume"]: volume, c["other"]: 0.0, **ov}


def _job(samples_v: np.ndarray, genome: Mapping[str, Any], ov: Mapping, label: str) -> Any:
    return runner.RenderJob(samples_v / _input_v_per_fs(), {**genome, **ov}, label, circuit=CIRCUIT)


def tone(f_hz: float, amp_v: float, fs: int, hold_s: float = HOLD_S) -> np.ndarray:
    """A sine rising over RISE_S (a raised cosine), held; volts at the jack."""
    t = np.arange(int((RISE_S + hold_s) * fs)) / fs
    rise = 0.5 - 0.5 * np.cos(np.pi * np.minimum(1.0, t / RISE_S))
    return amp_v * rise * np.sin(2 * np.pi * f_hz * t)


def multitone(fs: int) -> np.ndarray:
    t = np.arange(int((PRE_S + WIN_S) * fs)) / fs
    rng = np.random.default_rng(1)
    x = sum(MULTI_V * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) for f in TONES)
    return x * np.minimum(1.0, t / 0.02)


def burst(f_hz: float, fs: int) -> np.ndarray:
    n0, n1 = int(SAG_PRE_S * fs), int(SAG_BURST_S * fs)
    x = np.zeros(n0 + n1 + int(SAG_POST_S * fs))
    t = np.arange(n1) / fs
    edge = np.minimum(1.0, np.minimum(t, t[-1] - t) / 0.005)  # 5 ms ramps
    x[n0 : n0 + n1] = SAG_V * edge * np.sin(2 * np.pi * f_hz * t)
    return x


def speaker_admittance(p: Mapping[str, Any], f_hz: np.ndarray) -> np.ndarray:
    """The speaker's electrical equivalent (the circuit's `RSPK_E` .. `CSPK_M`) as an
    admittance: Re + jw Le in series with Res || Lces || Cmes."""
    jw = 2j * np.pi * np.asarray(f_hz, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        y_m = 1 / p["spk_res_ohm"] + np.where(jw == 0, np.inf, 1 / (jw * p["spk_lces_h"]))
    y_m = y_m + jw * p["spk_cmes_f"]
    z = p["spk_re_ohm"] + jw * p["spk_le_h"] + np.where(np.isinf(y_m), 0.0, 1 / y_m)
    return 1 / z


def speaker_power_w(r: runner.Render, n: int) -> float:
    """Mean power into the speaker over the last n samples (a whole number of the tone's
    periods): sum over bins of |V|^2 Re(Y), the load being linear."""
    v = r.vectors["v(out)"][-n:]
    spec = np.fft.rfft(v) / n
    f = np.fft.rfftfreq(n, 1 / r.sample_rate)
    w = np.full(len(f), 2.0)  # each bin's power counts twice (its negative frequency) ...
    w[0] = 1.0
    if n % 2 == 0:
        w[-1] = 1.0  # ... but DC's and Nyquist's
    y = speaker_admittance({k: float(r.meta["params"][k]) for k in SPEAKER}, f)
    return float(np.sum(w * np.abs(spec) ** 2 * y.real))


def input_v(job: runner.RenderJob) -> np.ndarray:
    """A job's input in volts at the jack (the circuit has no probe on `in`)."""
    return np.asarray(job.samples, float) * _input_v_per_fs()


def tone_row(r: runner.Render, job: runner.RenderJob, f_hz: float = 1000.0) -> dict[str, Any]:
    fs = r.sample_rate
    n = int(MEASURE_S * fs)
    out, inp = r.vectors["v(out)"][-n:], input_v(job)[-n:]
    h = metrics.harmonics(out, f_hz, fs)
    a1_in = metrics.harmonics(inp, f_hz, fs).amps[0]
    v_rms = float(np.sqrt(np.mean((out - np.mean(out)) ** 2)))
    return {
        "in_v_peak": round(float(a1_in), 6),
        "out_v_rms": round(v_rms, 4),
        "gain_db": round(float(20 * np.log10(h.amps[0] / a1_in)), 2),
        "thd_pct": round(100 * h.thd, 4),
        "h2_db": round(h.db(2), 1),
        "h3_db": round(h.db(3), 1),
        "power_w": round(speaker_power_w(r, n), 3),
        "power_8ohm_w": round(v_rms**2 / 8.0, 3),
        "spur": {"db": round(h.spur_db, 1), "hz": h.spur_hz},
        "harmonics": h,
    }


def _clean(row: Mapping[str, Any]) -> dict:
    return {k: v for k, v in row.items() if k != "harmonics"}


def screen(genome: Mapping[str, Any], s: TransientSettings) -> tuple[dict, dict]:
    fs = s.sample_rate
    nominal_ov = channel("bright", NOMINAL_VOLUME)
    jobs = [
        _job(np.zeros(int(IDLE_S * fs)), genome, nominal_ov, "idle"),
        _job(tone(1000.0, NOMINAL_V, fs), genome, nominal_ov, f"1k {NOMINAL_V} V"),
    ]
    idle, nominal = runner.render_many(jobs, settings=s)
    a, b = (int(x * fs) for x in IDLE_WINDOW_S)
    row = tone_row(nominal, jobs[1])
    n = int(RAIL_AVG_S * fs)
    rails = {}
    for node, v_kit in KIT_V.items():
        v = float(np.mean(idle.vectors[f"v({node})"][-n:]))
        dev = 100 * (v / v_kit - 1)
        rails[f"rail_{node}"] = generic.check(
            abs(dev) <= RAIL_PCT, {"v": round(v, 2), "pct": round(dev, 1)}, RAIL_PCT
        )
    checks = {
        "idle_quiet": generic.quiet(idle.output[a:b]),
        **rails,
        "nominal_no_spurs": generic.no_spurs(row["harmonics"]),
    }
    reported = {
        k: {"v": round(float(np.mean(idle.vectors[f"v({k})"][-n:])), 2), "kit": v}
        for k, v in REPORTED_V.items()
    }
    info = {
        "idle_out_dbfs": checks["idle_quiet"]["value"],
        "idle_out_mv_rms": round(1e3 * float(np.std(idle.vectors["v(out)"][a:b])), 3),
        "nominal": {"overrides": nominal_ov, **_clean(row)},
        "idle_v": reported,
    }
    return checks, info


def response_db(r: runner.Render, job: runner.RenderJob) -> np.ndarray:
    fs = r.sample_rate
    k, n = int(PRE_S * fs), int(WIN_S * fs)
    bins = np.round(TONES * WIN_S).astype(int)

    def at(w):
        return np.fft.rfft(w[k : k + n])[bins]

    return 20 * np.log10(np.abs(at(r.vectors["v(out)"]) / at(input_v(job))))


def onset(rows: list[dict]) -> dict[str, Any]:
    """Where THD first reaches ONSET_THD_PCT (interpolated in dB of input and of THD)."""
    for lo, hi in zip(rows, rows[1:], strict=False):
        if lo["thd_pct"] < ONSET_THD_PCT <= hi["thd_pct"]:
            w = np.log(ONSET_THD_PCT / lo["thd_pct"]) / np.log(hi["thd_pct"] / lo["thd_pct"])
            in_db = (1 - w) * 20 * np.log10(lo["in_v_peak"]) + w * 20 * np.log10(hi["in_v_peak"])
            p = (1 - w) * lo["power_w"] + w * hi["power_w"]
            return {"in_v_peak": round(float(10 ** (in_db / 20)), 5), "power_w": round(p, 3)}
    if rows and rows[0]["thd_pct"] >= ONSET_THD_PCT:
        return {"in_v_peak": f"< {rows[0]['in_v_peak']}", "power_w": None}
    return {"in_v_peak": None, "power_w": None}  # never within the levels


def smoothed(x: np.ndarray, n: int) -> np.ndarray:
    """Moving average over n samples (one mains period), centred."""
    c = np.cumsum(np.concatenate([[0.0], x]))
    y = (c[n:] - c[:-n]) / n
    return np.concatenate([np.full(n // 2, y[0]), y, np.full(len(x) - len(y) - n // 2, y[-1])])


def sag(r: runner.Render) -> dict[str, Any]:
    fs = r.sample_rate
    n_mains = round(fs / float(r.meta["params"]["mains_hz"]))
    n0, n1 = int(SAG_PRE_S * fs), int((SAG_PRE_S + SAG_BURST_S) * fs)
    out: dict[str, Any] = {}
    for node in SAG_NODES:
        v = smoothed(r.vectors[f"v({node})"], n_mains)
        idle = float(np.mean(v[n_mains : n0 - n_mains]))
        end = float(np.mean(v[n1 - 2 * n_mains : n1 - n_mains]))
        drop = end - idle
        after = v[n1:] - idle
        back = np.flatnonzero(np.abs(after) <= 0.37 * abs(drop))
        out[node] = {
            "idle_v": round(idle, 2),
            "burst_end_v": round(end, 2),
            "change_v": round(drop, 2),
            "change_pct": round(100 * drop / idle, 2),
            "recover_63_s": round(float(back[0] / fs), 3) if len(back) else None,
        }
    y = r.vectors["v(out)"]
    w = int(0.05 * fs)
    first = float(np.sqrt(np.mean(y[n0 + int(0.03 * fs) : n0 + int(0.03 * fs) + w] ** 2)))
    last = float(np.sqrt(np.mean(y[n1 - w - int(0.01 * fs) : n1 - int(0.01 * fs)] ** 2)))
    out["output_change_db"] = round(20 * np.log10(last / first), 2)
    return out


def alias_spectrum(r: runner.Render) -> tuple[np.ndarray, np.ndarray]:
    fs = r.sample_rate
    n = int(WIN_S * fs)
    y = r.vectors["v(out)"][-n:]
    y = y - np.mean(y)
    w = np.blackman(n)
    return np.fft.rfftfreq(n, 1 / fs), np.abs(np.fft.rfft(y * w)) ** 2


def aliasing(f: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    band = (f >= ALIAS_BAND_HZ[0]) & (f <= ALIAS_BAND_HZ[1])
    k = np.round(f / ALIAS_HZ)
    near = (k >= 1) & (np.abs(f - k * ALIAS_HZ) <= HARMONIC_GUARD_HZ)
    harmonic = float(np.sum(p[near & band]))
    alias = float(np.sum(p[band & ~near]))
    return {"alias_db": round(10 * np.log10(alias / harmonic), 1)}


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """Screen the genome; if it passes, measure everything, write the report."""
    del clips  # the amp's report has no program clips yet
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
        "quality": s.quality,
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
    gain_keys = [(c, v) for c in CHANNELS for v in VOLUMES]
    resp_keys = [(c, t) for c in CHANNELS for t in TONE_SETTINGS]
    dist_keys = [(v, lv) for v in DIST_VOLUMES for lv in DIST_DBV_PEAK]
    jobs = [
        _job(tone(1000.0, SMALL_V, fs), genome, channel(c, v), f"gain {c} {v}")
        for c, v in gain_keys
    ]
    jobs += [
        _job(multitone(fs), genome, channel(c, NOMINAL_VOLUME, tone=t), f"response {c} tone {t}")
        for c, t in resp_keys
    ]
    jobs += [
        _job(tone(1000.0, 10 ** (lv / 20), fs), genome, channel("bright", v), f"thd {v} {lv}")
        for v, lv in dist_keys
    ]
    jobs += [
        _job(burst(f, fs), genome, channel("bright", SAG_VOLUME), f"sag {f} Hz") for f in SAG_HZ
    ]
    alias_job = _job(
        tone(ALIAS_HZ, ALIAS_V, fs, hold_s=PRE_S + WIN_S),
        genome,
        channel("bright", ALIAS_VOLUME),
        f"alias {ALIAS_HZ} Hz",
    )
    jobs.append(alias_job)
    log(f"{name}: {len(jobs)} renders")
    renders = iter(zip(runner.render_many(jobs, settings=s), jobs, strict=True))

    gain: dict[str, Any] = {c: {"volume": list(VOLUMES), "gain_db": []} for c in CHANNELS}
    for c, _v in gain_keys:
        gain[c]["gain_db"].append(tone_row(*next(renders))["gain_db"])
    report["gain"] = {"in_v_peak": SMALL_V, "f_hz": 1000.0, **gain}

    resp: dict[str, Any] = {c: {} for c in CHANNELS}
    for c, t in resp_keys:
        resp[c][str(t)] = np.round(response_db(*next(renders)), 3).tolist()
    report["response"] = {
        "volume": NOMINAL_VOLUME,
        "tones_hz": TONES.tolist(),
        "in_v_peak_per_tone": MULTI_V,
        **resp,
    }

    dist: dict[str, Any] = {}
    for v in DIST_VOLUMES:
        rows = [_clean(tone_row(*next(renders))) for _ in DIST_DBV_PEAK]
        dist[str(v)] = {
            "rows": rows,
            "onset": onset(rows),
            "max_power_w": max(r["power_w"] for r in rows),
            "max_power_8ohm_w": max(r["power_8ohm_w"] for r in rows),
        }
    report["distortion"] = {"channel": "bright", "onset_thd_pct": ONSET_THD_PCT, **dist}

    sag_renders = [next(renders)[0] for _ in SAG_HZ]
    report["sag"] = {
        "in_v_peak": SAG_V,
        "volume": SAG_VOLUME,
        "burst_s": SAG_BURST_S,
        **{f"{f:g}_hz": sag(r) for f, r in zip(SAG_HZ, sag_renders, strict=True)},
    }
    traces = {f"{f:g}_hz": r for f, r in zip(SAG_HZ, sag_renders, strict=True)}

    spectra = {s.quality: alias_spectrum(next(renders)[0])}
    if s.engine == "circuitsim":
        for q in ALIAS_QUALITIES:
            if q != s.quality:
                sq = TransientSettings.from_sim_settings(engine="circuitsim", quality=q)
                spectra[q] = alias_spectrum(runner.render(alias_job, settings=sq))
    report["aliasing"] = {
        "f_hz": ALIAS_HZ,
        "in_v_peak": ALIAS_V,
        "volume": ALIAS_VOLUME,
        "band_hz": list(ALIAS_BAND_HZ),
        "guard_hz": HARMONIC_GUARD_HZ,
        **{q: aliasing(*sp) for q, sp in spectra.items()},
    }
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plots(out_dir, report, traces, spectra)
    b = report["distortion"][str(NOMINAL_VOLUME)]
    log(
        f"{name}: gain at half volume {gain['bright']['gain_db'][4]:.1f} dB; "
        f"{ONSET_THD_PCT}% THD at {b['onset']['in_v_peak']} V in; most power {b['max_power_w']} W"
    )
    return report


def _write(out_dir: Path, report: Mapping[str, Any]) -> None:
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8"
    )


def _plots(out_dir: Path, report: Mapping[str, Any], traces: dict, spectra: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = report["gain"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for c in CHANNELS:
        ax.plot(g[c]["volume"], g[c]["gain_db"], "o-", label=c)
    ax.set_xlabel("volume (rotation)")
    ax.set_ylabel("gain, speaker V / input V (dB)")
    ax.set_title(f"Gain per volume (1 kHz, {SMALL_V * 1e3:g} mV peak in)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "gain.png", dpi=110)
    plt.close(fig)

    rp = report["response"]
    f = np.array(rp["tones_hz"])
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, c in zip(axes, CHANNELS, strict=True):
        for t, db in rp[c].items():
            ax.semilogx(f, db, label=f"tone {t}")
        ax.set_title(f"{c} channel, volume {rp['volume']}")
        ax.set_xlim(30, 20000)
        ax.grid(True, which="both", alpha=0.3)
        ax.set_xlabel("Hz")
        ax.legend(fontsize=8)
    axes[0].set_ylabel("speaker V / input V (dB)")
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

    d = report["distortion"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.5))
    for v in DIST_VOLUMES:
        rows = d[str(v)]["rows"]
        x = [20 * np.log10(r["in_v_peak"]) for r in rows]
        a1.semilogy(x, [max(r["thd_pct"], 1e-4) for r in rows], "o-", label=f"volume {v}")
        a2.semilogy(x, [max(r["power_w"], 1e-6) for r in rows], "o-", label=f"volume {v}")
    a1.axhline(ONSET_THD_PCT, ls="--", c="gray")
    a1.set_ylabel("THD (%)")
    a2.set_ylabel("power into the speaker (W)")
    for ax in (a1, a2):
        ax.set_xlabel("input (dB re 1 V peak)")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend()
    a1.set_title("THD, 1 kHz, bright channel")
    a2.set_title("Output power")
    fig.tight_layout()
    fig.savefig(out_dir / "distortion.png", dpi=110)
    plt.close(fig)

    fig, axes = plt.subplots(len(SAG_NODES) + 1, len(traces), figsize=(12, 10), sharex=True)
    for j, (key, r) in enumerate(traces.items()):
        fs = r.sample_rate
        n = round(fs / float(r.meta["params"]["mains_hz"]))
        t = np.arange(len(r.vectors["v(out)"])) / fs
        for i, node in enumerate(SAG_NODES):
            axes[i, j].plot(t, smoothed(r.vectors[f"v({node})"], n))
            axes[i, j].set_ylabel(f"{node} (V)")
            axes[i, j].grid(True, alpha=0.3)
        axes[-1, j].plot(t, r.vectors["v(out)"], lw=0.3)
        axes[-1, j].set_ylabel("out (V)")
        axes[-1, j].set_xlabel("s")
        axes[0, j].set_title(f"Burst {key.replace('_', ' ')}, {SAG_V} V peak, volume {SAG_VOLUME}")
    fig.tight_layout()
    fig.savefig(out_dir / "sag.png", dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4.5))
    for q, (fr, p) in spectra.items():
        ax.semilogx(fr, 10 * np.log10(p / p.max() + 1e-30), lw=0.5, label=q)
    ax.set_xlim(20, report["aliasing"]["band_hz"][1] * 1.2)
    ax.set_ylim(-160, 5)
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB re the strongest bin")
    ax.set_title(f"{ALIAS_HZ:g} Hz at {ALIAS_V} V peak, volume {ALIAS_VOLUME}: output spectrum")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "aliasing.png", dpi=110)
    plt.close(fig)

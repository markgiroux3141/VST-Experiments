"""The API 550A's profile (docs/EQ_PLAN.md EQ3): `varimu unit --circuit api_550a`.

- network: the equalizer's linear network (config/circuits/api_550a_network.yaml: the 2520s and
  followers as linear `opamp` macros, varimu.measure.ac) at every band, position and step:
  where each peak falls, how far each step reaches against its panel marking (2, 4, 6, 9, 12
  dB), its width at +12 dB, the shelves, the band-pass, the flat response at both levels and
  the gain trim against the installation page's table. The 550A's frequencies come from its
  capacitors: they are measured here, never fitted; the curves to compare with are the Model
  550's (data/schematics/api_550a/sm550-2.png), the 550A's own weren't found.
- screen (renders of the real circuit): an idle render (quiet) and 1 kHz at +4 dBm out at the
  default panel (no spurs, the gain within generic.gain's window of the installation page's
  unity);
- agreement: a multitone through a few panels rendered, against the network;
- distortion: THD of 1 kHz from 0 to +28 dBm out, and at +28 dBm at 30 Hz and 20 kHz (the 550's
  sheet: < 0.35% 30 Hz-20 kHz at +28 dBm, its maximum output).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.measure import ac, generic, metrics
from varimu.measure.levels import DBM_V_RMS, dbm
from varimu.sim import runner
from varimu.sim.io import TransientSettings, full_scale

CIRCUIT = "api_550a"
NETWORK = "api_550a_network"
REPORT_DIR = REPO_ROOT / "reports" / "units"
GAINS = (-12, -9, -6, -4, -2, 2, 4, 6, 9, 12)
FREQS = (1, 2, 3, 4, 5)
BANDS = {"lf": True, "mf": False, "hf": True}  # band: has a shelf
TRIM_TABLE_DB = (0, 2, 4, 6, 8, 10, 11)  # the installation page's table
F_AC = np.geomspace(15.0, 40000.0, 240)
NOMINAL_OUT_DBM = 4.0
MAX_OUT_DBM = 28.0  # the 550's sheet: maximum output, and its THD figure's level
THD_SPEC_PCT = 0.35
DIST_DBM = (0.0, 10.0, 16.0, 20.0, 24.0, 26.0, 28.0)
DIST_EDGES_HZ = (30.0, 20000.0)
TONE_RISE_S, TONE_HOLD_S, TONE_MEASURE_S = 0.05, 0.3, 0.2
IDLE_S = 1.0
TONES = np.unique(np.round(np.geomspace(30.0, 20000.0, 31) / 2.0) * 2.0)  # 2 Hz bins
TONE_V = 0.01
PRE_S, WIN_S = 0.25, 0.5
RENDERED = {  # panels rendered for agreement
    "flat": {},
    "hf_+12_f3": {"hf_gain_db": 12, "hf_freq": 3},
    "mf_-12_f5": {"mf_gain_db": -12, "mf_freq": 5},
    "lf_+12_f4": {"lf_gain_db": 12, "lf_freq": 4},
    "lf_shelf_-12_f5": {"lf_gain_db": -12, "lf_freq": 5, "lf_shelf": 1},
    "bandpass": {"bandpass": 1},
}


def _one_blas_thread() -> None:
    """The network's small solves run ~1000x slower with BLAS on every core (CLAUDE.md:
    pin BLAS to one thread); threadpoolctl when present, else the environment."""
    try:
        from threadpoolctl import threadpool_limits

        threadpool_limits(1)
    except ImportError:
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")


def network_db(ov: Mapping[str, Any], f_hz: np.ndarray = F_AC) -> np.ndarray:
    s = spec.load_circuit(spec.circuit_path(NETWORK))
    ir = builder.build_ir(s, spec.resolve(s, ov), cores="linear").without_devices()
    return 20 * np.log10(np.abs(ac.transfer(ir, f_hz, "out")))


def _at(d: np.ndarray, f_hz: float) -> float:
    return float(np.interp(np.log(f_hz), np.log(F_AC), d))


def network(genome: Mapping[str, Any]) -> dict[str, Any]:
    _one_blas_thread()
    flat = network_db(genome)
    out: dict[str, Any] = {
        "flat": {
            f"level_{lv}": {
                "gain_1k_db": round(_at(d := network_db({**genome, "level": lv}), 1000), 2),
                "30hz_re_1k_db": round(_at(d, 30) - _at(d, 1000), 2),
                "20khz_re_1k_db": round(_at(d, 20000) - _at(d, 1000), 2),
            }
            for lv in (0, 1)
        },
        "gain_trim": [
            {
                "table_db": t,
                "measured_db": round(
                    _at(network_db({**genome, "gain_trim_db": t}), 1000) - _at(flat, 1000), 2
                ),
            }
            for t in TRIM_TABLE_DB
        ],  # fmt: skip
    }
    bp = network_db({**genome, "bandpass": 1}) - flat
    points = (30, 50, 100, 1000, 10000, 15000, 20000)
    out["bandpass_re_flat_db"] = {str(f): round(_at(bp, f), 2) for f in points}
    bands: dict[str, Any] = {}
    for band, shelf in BANDS.items():
        b: dict[str, Any] = {}
        for mode in (0, 1) if shelf else (0,):
            rows = []
            for fr in FREQS:
                steps = {}
                for g in GAINS:
                    ov = {**genome, f"{band}_gain_db": g, f"{band}_freq": fr}
                    if shelf:
                        ov[f"{band}_shelf"] = mode
                    d = network_db(ov) - flat
                    if mode:
                        end = _at(d, 20000) if band == "hf" else _at(d, 20)
                        j = int(np.argmin(np.abs(d - end / 2)))
                        steps[str(g)] = {"db": round(end, 2), "half_at_hz": round(float(F_AC[j]))}
                    else:
                        i = int(np.argmax(np.abs(d)))
                        row = {"db": round(float(d[i]), 2), "at_hz": round(float(F_AC[i]))}
                        if abs(g) == 12:
                            above = np.where(np.sign(g) * d >= abs(d[i]) / 2)[0]
                            row["half_db_width_oct"] = round(
                                float(np.log2(F_AC[above[-1]] / F_AC[above[0]])), 2)  # fmt: skip
                        steps[str(g)] = row
                rows.append({"position": fr, "steps": steps})
            b["shelf" if mode else "peak"] = rows
        bands[band] = b
    out["bands"] = bands
    return out


def _job(x_v: np.ndarray, genome: Mapping[str, Any], ov: Mapping, label: str, s) -> Any:
    circuit = spec.load_circuit(spec.circuit_path(CIRCUIT))
    return runner.RenderJob(
        x_v / full_scale(s, circuit)[0], {**genome, **ov}, label, circuit=CIRCUIT
    )


def multitone(fs: int) -> np.ndarray:
    t = np.arange(int((PRE_S + WIN_S) * fs)) / fs
    rng = np.random.default_rng(1)
    x = sum(TONE_V * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) for f in TONES)
    return x * np.minimum(1.0, t / 0.02)


def tone(out_dbm: float, f_hz: float, fs: int, gain_db: float = 0.0) -> np.ndarray:
    """A tone rising over TONE_RISE_S (a raised cosine), held; volts at the source, for
    `out_dbm` at the output with the unit's gain `gain_db`."""
    t = np.arange(int((TONE_RISE_S + TONE_HOLD_S) * fs)) / fs
    amp = DBM_V_RMS * np.sqrt(2) * 10 ** ((out_dbm - gain_db) / 20)
    rise = 0.5 - 0.5 * np.cos(np.pi * np.minimum(1.0, t / TONE_RISE_S))
    return amp * rise * np.sin(2 * np.pi * f_hz * t)


def tone_levels(render: runner.Render, x_v: np.ndarray, f_hz: float) -> dict[str, Any]:
    fs = render.sample_rate
    n = int(TONE_MEASURE_S * fs)
    out = render.vectors["v(out)"][-n:]
    h = metrics.harmonics(out, f_hz, fs)
    return {
        "f_hz": f_hz,
        "out_dbm": round(dbm(float(np.sqrt(np.mean(out**2)))), 2),
        "in_dbm": round(dbm(float(np.sqrt(np.mean(x_v[-n:] ** 2)))), 2),
        "thd_pct": round(100 * h.thd, 4),
        "h2_db": round(h.db(2), 1),
        "h3_db": round(h.db(3), 1),
        "spur": {"db": round(h.spur_db, 1), "hz": h.spur_hz},
        "harmonics": h,
    }


def _clean(lv: Mapping[str, Any]) -> dict:
    return {k: v for k, v in lv.items() if k != "harmonics"}


def response_db(render: runner.Render, x_v: np.ndarray) -> np.ndarray:
    fs = render.sample_rate
    k, n = int(PRE_S * fs), int(WIN_S * fs)
    bins = np.round(TONES * WIN_S).astype(int)
    y = np.fft.rfft(render.vectors["v(out)"][k : k + n])[bins]
    x = np.fft.rfft(x_v[k : k + n])[bins]
    return 20 * np.log10(np.abs(y / x))


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    del clips
    t0 = time.perf_counter()
    genome = dict(genome or {})
    out_dir = REPORT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    s = settings or TransientSettings.from_sim_settings(engine="configured")
    fs = s.sample_rate
    report: dict[str, Any] = {
        "name": name,
        "circuit": CIRCUIT,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "genome": genome,
    }
    log(f"{name}: network")
    report["network"] = network(genome)
    log(f"{name}: screen")
    x_nom = tone(NOMINAL_OUT_DBM, 1000.0, fs)
    idle, nominal = runner.render_many(
        [
            _job(np.zeros(int(IDLE_S * fs)), genome, {}, "idle", s),
            _job(x_nom, genome, {}, f"1k {NOMINAL_OUT_DBM} dBm", s),
        ],  # fmt: skip
        settings=s,
    )
    lv = tone_levels(nominal, x_nom, 1000.0)
    checks = {
        "idle_quiet": generic.quiet(idle.output[int(0.05 * fs) :]),
        "nominal_no_spurs": generic.no_spurs(lv["harmonics"]),
        "nominal_gain": generic.gain(lv["out_dbm"] - lv["in_dbm"], 0.0),
    }
    report.update(screen={"nominal": _clean(lv)}, checks=checks)
    report["plausible"] = all(c["passes"] for c in checks.values())
    if not report["plausible"]:
        log(f"{name}: rejected: {[k for k, c in checks.items() if not c['passes']]}")
        _write(out_dir, report)
        return report
    gain_db = lv["out_dbm"] - lv["in_dbm"]
    xm = multitone(fs)
    jobs = [_job(xm, genome, ov, p, s) for p, ov in RENDERED.items()]
    tones = [(lvl, 1000.0) for lvl in DIST_DBM] + [(MAX_OUT_DBM, f) for f in DIST_EDGES_HZ]
    xs = [tone(lvl, f, fs, gain_db) for lvl, f in tones]
    jobs += [
        _job(x, genome, {}, f"{f:g} Hz {lvl} dBm", s) for x, (lvl, f) in zip(xs, tones, strict=True)
    ]
    log(f"{name}: {len(jobs)} renders")
    renders = runner.render_many(jobs, settings=s)
    flat_net = network_db(genome, TONES)
    agree = {}
    for (p, ov), r in zip(RENDERED.items(), renders, strict=False):
        rendered = response_db(r, xm)
        net = network_db({**genome, **ov}, TONES)
        if p != "flat":
            rendered = rendered - response_db(renders[0], xm)
            net = net - flat_net
        dev = rendered - net
        agree[p] = {"max_abs_dev_db": round(float(np.max(np.abs(dev))), 3),
                    "mean_dev_db": round(float(np.mean(dev)), 3)}  # fmt: skip
    report["agreement"] = agree
    rows = [_clean(tone_levels(r, x, f)) for r, x, (_, f) in
            zip(renders[len(RENDERED) :], xs, tones, strict=True)]  # fmt: skip
    at_max = [r for r in rows if abs(r["out_dbm"] - MAX_OUT_DBM) < 1.5]
    report["distortion"] = {
        "rows": rows,
        "thd_pct_at_max": max((r["thd_pct"] for r in at_max), default=None),
        "spec_pct": THD_SPEC_PCT,
    }
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plot(out_dir, report)
    log(f"{name}: written to {out_dir}")
    return report


def _write(out_dir: Path, report: Mapping[str, Any]) -> None:
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8"
    )


def _plot(out_dir: Path, report: Mapping[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    genome = report["genome"]
    flat = network_db(genome)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for ax, mode in zip(axes[0], ("peak", "shelf"), strict=True):
        for band, shelf in BANDS.items():
            if mode == "shelf" and not shelf:
                continue
            for fr in FREQS:
                for g in (-12, 12):
                    ov = {**genome, f"{band}_gain_db": g, f"{band}_freq": fr}
                    if shelf:
                        ov[f"{band}_shelf"] = int(mode == "shelf")
                    ax.semilogx(F_AC, network_db(ov) - flat, lw=0.8)
        ax.set_title(f"{mode.upper()}ING family (+-12 dB, every position; network)")
        ax.set_xlim(20, 20000)
        ax.set_ylim(-16, 16)
        ax.grid(True, which="both", alpha=0.3)
    ax = axes[1][0]
    for fr in (3,):
        for g in GAINS:
            ax.semilogx(F_AC, network_db({**genome, "mf_gain_db": g, "mf_freq": fr}) - flat, lw=0.8)
    ax.set_title("MF position 3, every step (network)")
    ax.set_xlim(20, 20000)
    ax.grid(True, which="both", alpha=0.3)
    ax = axes[1][1]
    ax.semilogx(F_AC, flat, label="flat (HIGH LEVEL)")
    ax.semilogx(F_AC, network_db({**genome, "bandpass": 1}), label="band-pass IN")
    ax.set_title("Flat and band-pass (dB out / in)")
    ax.set_xlim(20, 20000)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

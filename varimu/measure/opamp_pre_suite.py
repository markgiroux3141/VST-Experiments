"""The op-amp mic preamps' profile (the chains build-out's WP4): the SSL 4000 E's 82E01.

    report = run(name, genome, circuit="ssl_4000e")   # varimu unit --circuit ssl_4000e --name NAME

One suite, a `PREAMPS` entry per circuit: its nominal setting and gain, its gain control
and the drawing's law for it, its rails, the value that loads its output and the figures
it is compared with (a reissue's or a manual's: `vs_published`, a reference, never a pass
or a rejection). Conditions as the UA 610's (varimu.measure.ua610_suite): a 150 ohm
generator (the circuit's RSRC), levels in dBu, gain from the generator's EMF; the V76's
tones, spectra and level readings (varimu.measure.preamp_suite). Sections:

- screen: an idle render (the output quiet) and 1 kHz at the preamp's response level
  (+4 dBu; the 424's -10 dBV) out at the nominal setting
  (no oscillation riding on it, the gain within 6 dB of the nominal);
- gain: 1 kHz at each point of the gain control, against the drawing's law plus the
  input's (the transformer's) gain read at the lowest point; the pad's step if it has one;
- response: the multitone at that level out, re 1 kHz, at the nominal setting and at the
  gain control's ends;
- input impedance at the mic terminals (`ia`); output impedance (the multitone with the
  load at its value and at 1 MOhm);
- distortion: THD of 1 kHz against level to past clipping at the nominal setting (the 1%
  output level); 20 Hz at -20 and -2.5 dBu at the input (the input transformer's figures).

Not modelled: noise (no noise block), hum, the line input.

Results: reports/units/<name>/report.json, response.png.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from varimu.circuit import spec
from varimu.measure import generic
from varimu.measure import preamp_suite as pre
from varimu.sim import runner
from varimu.sim.io import TransientSettings, full_scale

REPORT_DIR = pre.REPORT_DIR
MAX_JOBS: int | None = None
LF_IN_DBU = (-20.0, -2.5)


def _ssl_law_db(x: float) -> float:
    """82E01: (1 + 10k x / (R9 || R10)) R71 / (10k (1 - x) + R69), T4 unity
    (data/schematics/ssl_4000e/README.md)."""
    r9_10 = 619.0 * 10e3 / (619.0 + 10e3)
    return float(20 * np.log10((1 + 10e3 * x / r9_10) * 10.7e3 / (10e3 * (1 - x) + 619.0)))


@dataclass(frozen=True)
class Preamp:
    circuit: str
    nominal: Mapping[str, Any]
    nominal_gain_db: float
    gain_key: str
    gain_points: tuple[float, ...]
    law_db: Callable[[float], float]  # the drawing's gain after the input stage
    load_key: str  # the value loading `out` (z_out: it at 1 MOhm)
    published: Mapping[str, float] = field(default_factory=dict)
    published_source: str = ""
    pad_key: str | None = None
    response_out_db: float = 4.0  # dBu out: the screen's tone, the multitones
    sweep_out_db: tuple[float, ...] = (-10, 0, 4, 8, 12, 14, 16, 18, 20, 21, 22, 23, 24, 26)


def _porta_law_db(trim: float) -> float:
    """424 U101A: (R102 + Rw) / (Rw + R102 k) with TRIM's reverse audio track
    (tascam_portastudio.yaml; data/schematics/tascam_424/README.md)."""
    from varimu.circuit import parts

    above, below = parts.pot("R", "t", "w", "b", 10e3, trim, 0.1, reverse=True)
    up, low = above.r_ohm, below.r_ohm + 100.0
    k, rw = low / (up + low), up * low / (up + low)
    return float(20 * np.log10((470e3 + rw) / (rw + 470e3 * k)))


def _api_law_db(gain: float) -> float:
    """312: the 2520's 1 + 47k / (470 + GAIN's reverse audio track) and the AP2503's 1:3
    (api_312.yaml, the 1972 sheet's Figs. 1 and 2)."""
    from varimu.circuit import parts

    r = parts.rheostat("R", "a", "b", 25e3, gain, 0.15, reverse=True).r_ohm
    return float(20 * np.log10((1 + 47e3 / (470.0 + r)) * 3.0))


def _neve_law_db(sensitivity: float) -> float:
    """1073: EK20033's labels, the gain about minus the setting in dBm (neve_1073.yaml)."""
    return float(-sensitivity)


def _helios_law_db(gain: float) -> float:
    """Helios (IA-H9): the mic amp's 1 + 47k / R(GAIN) (SW2's R1-R8), T1's 1:10, the EQ CUT
    divider R35 / R36 (into R25's 240 ohm) and the output amp's 1 + 47k / 8.2k (helios.yaml)."""
    r = {20: 56e3, 30: 22e3, 40: 5.1e3, 50: 1.5e3, 60: 460.0, 70: 110.0}[int(gain)]
    cut = 5.1e3 / (5.1e3 + 27e3 + 240.0)
    return float(20 * np.log10((1 + 47e3 / r) * 10.0 * cut * (1 + 47e3 / 8.2e3)))


def _tg_law_db(coarse: float) -> float:
    """TG12345: the input transformer's 1:3.16 and Amplifier D's nominal 25 dB, less COARSE's
    attenuation (emi_tg12345.yaml; the handbook's 3.2, 3.4.1, 12.27)."""
    return float(20 * np.log10(3.16) + 25.0 - coarse)


PREAMPS = {
    "ssl_4000e": Preamp(
        circuit="ssl_4000e",
        nominal={"mic_gain": 0.3, "pad": 0, "phase": 0},
        nominal_gain_db=34.0,
        gain_key="mic_gain",
        gain_points=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
        law_db=_ssl_law_db,
        load_key="r16_ohm",
        published={
            "min_gain_db": 20.0,
            "max_gain_db": 70.0,
            "z_in_ohm": 1300.0,
            "flat_tol_db": 0.175,
            "pad_db": -20.0,
        },  # fmt: skip
        published_source="rev: SSL's Revival 4000 (a reissue: 'the exact same Jensen "
        "JT-115K-E ... circuit'), Mic Input to Insert Send (data/schematics/ssl_4000e/README.md)",
        pad_key="pad",
    ),
    "tascam_portastudio": Preamp(
        circuit="tascam_portastudio",
        nominal={"trim": 0.5},
        nominal_gain_db=19.0,
        gain_key="trim",
        gain_points=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
        law_db=_porta_law_db,
        load_key="r114_ohm",
        published={"min_gain_db": 0.0, "max_gain_db": 40.0},
        response_out_db=-8.0,  # -10 dBV, the machine's nominal level
        sweep_out_db=(-20, -10, -5, 0, 2, 4, 5, 6, 7, 8, 9, 10, 12),
        published_source="sm: the 424's MIC/LINE jacks, '-50 ~ -10 dBV' (a 40 dB range to "
        "-10 dBV; data/schematics/tascam_424/README.md)",
    ),
    "neve_1073": Preamp(
        circuit="neve_1073",
        nominal={"sensitivity": -50, "impedance": 1},
        nominal_gain_db=50.0,
        gain_key="sensitivity",
        gain_points=(-20, -25, -30, -35, -40, -45, -50, -55, -60, -65, -70, -75, -80),
        law_db=_neve_law_db,
        load_key="r_load_ohm",
        published={"min_gain_db": 20.0, "max_gain_db": 80.0},
        published_source="neve: EK20033's mic positions -20 to -80 dBm; AMS Neve's 1073 "
        "(mic gain +20 to +80 dB in 5 dB steps; data/schematics/neve_1073/README.md)",
    ),
    "api_312": Preamp(
        circuit="api_312",
        nominal={"gain": 0.6, "pad": 0, "tap": 0},
        nominal_gain_db=47.0,
        gain_key="gain",
        gain_points=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
        law_db=_api_law_db,
        load_key="r_load_ohm",
        published={"max_gain_db": 69.0, "flat_tol_db": 0.25, "pad_db": -20.0},  # Z in: "> 1500"
        published_source="api: the 312 cut sheet (69 dB most gain, 20 dB pad) and the 1972 "
        "circuit sheet's Fig. 1 (input impedance > 1500 ohm, +-0.25 dB 20-20 kHz; "
        "data/schematics/api_312/README.md)",
        pad_key="pad",
    ),
    "emi_tg12345": Preamp(
        circuit="emi_tg12345",
        nominal={"coarse": 0, "fine": 0},
        nominal_gain_db=35.0,
        gain_key="coarse",
        gain_points=(55, 50, 45, 40, 35, 30, 25, 20, 15, 10, 5, 0),  # least gain first
        law_db=_tg_law_db,
        load_key="r_load_ohm",
        published={"max_gain_db": 40.0},
        published_source="hb: the TG12345 Mk II handbook (1:3.16, Amplifier D 25 +-5 dB, "
        "COARSE 5 dB steps; >= 1.4 V rms into 3k; data/schematics/emi_tg12345/README.md)",
    ),
    "helios": Preamp(
        circuit="helios",
        nominal={"gain": 50, "pad": 0, "hpf": 0},
        nominal_gain_db=50.0,
        gain_key="gain",
        gain_points=(20, 30, 40, 50, 60, 70),
        law_db=_helios_law_db,
        load_key="r_load_ohm",
        published={"min_gain_db": 20.0, "max_gain_db": 70.0, "pad_db": -20.0},
        published_source="web: the IA-H9 schematic's GAIN labels 20-70 and the pad's 1:1 tap "
        "of the Sowter 7490 (1:10; data/schematics/helios_ia_h9/README.md)",
        pad_key="pad",
    ),
}


def _job(
    p: Preamp, emf_v: np.ndarray, genome: Mapping[str, Any], ov: Mapping, label: str, s
) -> Any:
    fs_v = full_scale(s, spec.load_circuit(spec.circuit_path(p.circuit)))[0]
    return runner.RenderJob(emf_v / fs_v, {**genome, **p.nominal, **ov}, label, circuit=p.circuit)


def multitone(out_db: float, gain_db: float, fs: int) -> np.ndarray:
    """The V76's multitone (TONES at equal EMF), about out_db out in total at gain_db."""
    return pre.multitone(gain_db + pre.RESPONSE_OUT_DB - out_db, fs)


def lf_tone(in_dbu: float, freq_hz: float, fs: int) -> np.ndarray:
    """A tone of `in_dbu` EMF (pre.tone's fade and length), whatever the gain."""
    return pre.tone(in_dbu, 0.0, freq_hz, fs)


def screen(p: Preamp, genome: Mapping[str, Any], s: TransientSettings) -> tuple[dict, dict]:
    fs = s.sample_rate
    x = pre.tone(p.response_out_db, p.nominal_gain_db, 1000.0, fs)
    idle, nominal = runner.render_many(
        [
            _job(p, np.zeros(int(1.0 * fs)), genome, {}, "idle", s),
            _job(p, x, genome, {}, "1k nominal", s),
        ],
        settings=s,
        max_jobs=MAX_JOBS,
    )
    lv = pre.tone_levels(nominal, x, 1000.0)
    checks = {
        "idle_quiet": generic.quiet(idle.output[int(0.05 * fs) :]),
        "nominal_no_spurs": generic.no_spurs(lv["harmonics"]),
        "nominal_gain": generic.gain(lv["gain_db"], p.nominal_gain_db),
    }
    return checks, {"idle_out_dbfs": checks["idle_quiet"]["value"], "nominal": pre._clean(lv)}


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    circuit: str = "ssl_4000e",
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """Screen the genome; if it passes, measure everything, write the report."""
    del clips  # no program clips yet
    p = PREAMPS[circuit]
    t0 = time.perf_counter()
    genome = dict(genome or {})
    out_dir = REPORT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    s = settings or TransientSettings.from_sim_settings(engine="configured")
    c = spec.load_circuit(spec.circuit_path(p.circuit))
    report: dict[str, Any] = {
        "name": name,
        "circuit": p.circuit,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "genome": genome,
        "nominal_setting": dict(p.nominal),
        "published_source": p.published_source,
    }
    log(f"{name}: screen")
    checks, screen_info = screen(p, genome, s)
    report["screen"] = screen_info
    report["checks"] = checks
    report["plausible"] = all(ch["passes"] for ch in checks.values())
    if not report["plausible"]:
        log(f"{name}: rejected: {[k for k, ch in checks.items() if not ch['passes']]}")
        _write(out_dir, report)
        return report

    fs = s.sample_rate
    g_nom = screen_info["nominal"]["gain_db"]
    q = spec.resolve(c, genome)
    jobs, inputs, keys = [], [], []

    def add(key, x, ov, label):
        keys.append(key)
        inputs.append(x)
        jobs.append(_job(p, x, genome, ov, label, s))

    lo, hi = p.gain_points[0], p.gain_points[-1]
    for g in p.gain_points:  # -10 dBu out at the most gain: below clipping everywhere
        add(("gain", g), pre.tone(-10.0, 75.0, 1000.0, fs), {p.gain_key: g}, f"gain {g}")
    if p.pad_key:
        add(("pad", 1), pre.tone(-10.0, 75.0, 1000.0, fs), {p.gain_key: hi, p.pad_key: 1}, "pad")
    for k, ov in (("nominal", {}), ("min", {p.gain_key: lo}), ("max", {p.gain_key: hi})):
        gain = g_nom if k == "nominal" else None
        x = multitone(p.response_out_db, gain if gain is not None else 0.0, fs)
        if k == "max":
            x = multitone(p.response_out_db, p.published.get("max_gain_db", 70.0), fs)
        elif k == "min":
            x = multitone(p.response_out_db, p.published.get("min_gain_db", 20.0), fs)
        add(("resp", k), x, ov, f"response {k}")
    add(
        ("zout", "open"), multitone(p.response_out_db, g_nom, fs), {p.load_key: 1.0e6}, "z_out open"
    )
    for out_db in p.sweep_out_db:
        add(("sweep", out_db), pre.tone(out_db, g_nom, 1000.0, fs), {}, f"sweep {out_db} dB")
    for in_dbu in LF_IN_DBU:  # at the least gain: the input stage's own distortion
        add(("lf", in_dbu), lf_tone(in_dbu, 20.0, fs), {p.gain_key: lo}, f"20 Hz {in_dbu} dBu in")
    log(f"{name}: {len(jobs)} renders")
    renders = runner.render_many(jobs, settings=s, max_jobs=MAX_JOBS)
    got = dict(zip(keys, zip(renders, inputs, strict=True), strict=True))
    lim = pre._limits
    pub = p.published

    rows = {g: pre._clean(pre.tone_levels(*got[("gain", g)], 1000.0)) for g in p.gain_points}
    input_db = rows[lo]["gain_db"] - p.law_db(lo)
    law = [
        {
            "at": g,
            "gain_db": rows[g]["gain_db"],
            "input_plus_law_db": round(input_db + p.law_db(g), 2),
        }
        for g in p.gain_points
    ]
    report["gain"] = {
        "law": law,
        "input_stage_db": round(input_db, 2),
        "range_db": [rows[lo]["gain_db"], rows[hi]["gain_db"]],
    }
    vs: dict[str, Any] = {}
    if "min_gain_db" in pub:
        vs["min_gain"] = lim(rows[lo]["gain_db"], pub["min_gain_db"] - 2, pub["min_gain_db"] + 2)
        vs["max_gain"] = lim(rows[hi]["gain_db"], pub["max_gain_db"] - 2, pub["max_gain_db"] + 2)
    if p.pad_key:
        step = (
            pre._clean(pre.tone_levels(*got[("pad", 1)], 1000.0))["gain_db"] - rows[hi]["gain_db"]
        )
        report["gain"]["pad_step_db"] = round(step, 2)
        if "pad_db" in pub:
            vs["pad"] = lim(step, pub["pad_db"] - 1.5, pub["pad_db"] + 1.5)
    spectra = {k[1]: pre.spectrum(r, x) for k, (r, x) in got.items() if k[0] == "resp"}
    tones, at = pre.TONES, pre.at
    db = {k: 20 * np.log10(np.abs(h)) for k, h in spectra.items()}
    rel = {k: d - at(d, 1000.0) for k, d in db.items()}
    band = (tones >= 20) & (tones <= 20000)
    points = (10, 20, 50, 100, 1000, 5000, 10000, 15000, 20000, 40000)
    report["response"] = {
        "tones_hz": tones.tolist(),
        "rel_db": {k: np.round(r, 3).tolist() for k, r in rel.items()},
        "at_db": {k: {f"{f:g}": round(at(r, f), 2) for f in points} for k, r in rel.items()},
    }
    if "flat_tol_db" in pub:
        worst = max(float(np.max(np.abs(r[band]))) for r in rel.values())
        vs["flat_20_20k"] = lim(worst, None, pub["flat_tol_db"])
    r_src = q["source_impedance_ohm"]
    h_term = pre.spectrum(*got[("resp", "nominal")], node="ia")
    z_in = r_src * np.abs(h_term / (1.0 - h_term))
    report["input_impedance"] = {
        "z_ohm": np.round(z_in, 1).tolist(),
        "at_ohm": {f"{f:g}": round(float(np.interp(f, tones, z_in)), 1) for f in (40, 1000, 10000)},
    }
    if "z_in_ohm" in pub:
        z1k = float(np.interp(1000.0, tones, z_in))
        vs["z_in_1k"] = lim(z1k, 0.85 * pub["z_in_ohm"], 1.15 * pub["z_in_ohm"])
    z = pre.z_out(pre.spectrum(*got[("zout", "open")]), spectra["nominal"], q[p.load_key])
    report["output_impedance"] = {
        "z_ohm": np.round(z, 2).tolist(),
        "at_1k_ohm": round(at(z, 1000.0), 2),
    }
    srows = [pre._clean(pre.tone_levels(*got[("sweep", lv)], 1000.0)) for lv in p.sweep_out_db]
    outs, thd = np.array([r["out_db"] for r in srows]), np.array([r["thd_pct"] for r in srows])

    def level_at(pct: float) -> float | None:
        i = np.nonzero(thd >= pct)[0]
        if len(i) == 0 or i[0] == 0:
            return None
        j = i[0]
        return round(
            float(np.interp(np.log(pct), np.log(thd[j - 1 : j + 1]), outs[j - 1 : j + 1])), 2
        )

    report["distortion"] = {
        "sweep_1k": {"rows": srows, "out_db_at_0p1pct": level_at(0.1),
                     "out_db_at_1pct": level_at(1.0), "out_db_at_3pct": level_at(3.0)},
        "at_20hz_least_gain": {f"{v:+g} dBu in": pre._clean(pre.tone_levels(*got[("lf", v)], 20.0))
                               for v in LF_IN_DBU},
    }  # fmt: skip
    report["vs_published"] = vs
    report["meets_published"] = f"{sum(ch['meets'] for ch in vs.values())}/{len(vs)}"
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plots(out_dir, report)
    log(f"{name}: within {report['meets_published']} of the published figures (a reference)")
    return report


def _write(out_dir: Path, report: Mapping[str, Any]) -> None:
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8"
    )


def _plots(out_dir: Path, report: Mapping[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f = np.array(report["response"]["tones_hz"])
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
    ax = axes[0, 0]
    for k, r in report["response"]["rel_db"].items():
        ax.semilogx(f, r, label=k, lw=2.0 if k == "nominal" else 1.0)
    ax.set_ylim(-6, 3)
    ax.set_title(f"{report['circuit']}: response re 1 kHz")
    ax = axes[0, 1]
    ax.semilogx(f, report["input_impedance"]["z_ohm"], label="|Z in| at the mic terminals")
    ax.set_title("Input impedance")
    ax.set_ylabel("ohm")
    ax = axes[1, 0]
    law = report["gain"]["law"]
    ax.plot([r["at"] for r in law], [r["gain_db"] for r in law], "o-", label="measured")
    ax.plot(
        [r["at"] for r in law],
        [r["input_plus_law_db"] for r in law],
        "--",
        label="the drawing's law",
    )
    ax.set_title("Gain (1 kHz, from the generator's EMF)")
    ax.set_xlabel("gain control")
    ax.set_ylabel("dB")
    for a in (axes[0, 0], axes[0, 1]):
        a.set_xlim(10, 45000)
    ax = axes[1, 1]
    rows = report["distortion"]["sweep_1k"]["rows"]
    o = [r["out_db"] for r in rows]
    ax.semilogy(o, [r["thd_pct"] for r in rows], "o-", label="THD")
    ax.semilogy(o, [r["k2_pct"] for r in rows], ".--", label="k2")
    ax.semilogy(o, [r["k3_pct"] for r in rows], ".--", label="k3")
    ax.set_xlabel("output (dBu)")
    ax.set_ylabel("%")
    ax.set_title("1 kHz at the nominal setting")
    for a in axes.flat:
        a.grid(True, which="both", alpha=0.3)
        a.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

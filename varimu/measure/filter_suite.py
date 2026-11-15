"""The Pultec HLF-3C's profile (docs/EQ_PLAN.md EQ1): `varimu unit --circuit pultec_hlf3c`.

A passive LC filter is linear, so its response per position comes from the AC analysis of
the built IR (varimu.measure.ac, the reference that checks the renders), relative to the key
at OUT (the line straight through: the brochure's "insertion loss: zero" is against it):
- every LOW CUT-OFF and HIGH CUT-OFF position's -3 dB frequency against the panel's, its
  peak at the knee and its slope an octave pair into the stop band;
- the -40 dB frequency against the brochure's curves, read by eye (`BROCHURE_40DB_HZ`);
- one transient render through the configured engine at the brochure's maximum level
  (+28 dBm) on two positions, against the AC analysis (the engine's agreement and the
  network's linearity at full level).

The screen (`checks`) rejects only what no working unit could do: a path that doesn't
pass with both selectors OFF, a cutoff more than an octave from its knob, a slope under
10 dB / octave, a render that doesn't follow the AC analysis.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from varimu.circuit import builder, spec
from varimu.measure import ac
from varimu.measure import preamp_suite as pre
from varimu.sim import runner
from varimu.sim.io import TransientSettings

CIRCUIT = "pultec_hlf3c"
REPORT_DIR = pre.REPORT_DIR

LOW_HZ = (50, 80, 100, 150, 250, 500, 750, 1000, 1500, 2000)
HIGH_HZ = (1500, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 12000, 15000)

# The brochure's curves cross 40 dB of attenuation at these frequencies (read by eye off
# data/schematics/pultec_hlf3c/brochure.png rendered at 400 dpi, ~+-10%; a curve hidden
# behind its neighbours is None; the high-cut curves above 6 kc leave the chart at 30 kc).
BROCHURE_40DB_HZ: dict[str, dict[int, float | None]] = {
    "low": {
        50: 10.0,
        80: 14.0,
        100: 19.0,
        150: 29.0,
        250: 50.0,
        500: 100.0,
        750: 165.0,
        1000: None,
        1500: 300.0,
        2000: 420.0,
    },
    "high": {
        1500: 6500.0,
        2000: 9100.0,
        3000: 15000.0,
        4000: 19000.0,
        5000: 24000.0,
        6000: 27000.0,
    },
}
BROCHURE_SOURCE = (
    "man: the HLF-3C sheet's LOW / HIGH CUT-OFF CONTROL families, read by eye at 400 dpi "
    "(data/schematics/pultec_hlf3c/README.md)"
)

F_HZ = np.geomspace(5.0, 40_000.0, 4000)


def _ir(circuit, genome: Mapping[str, Any], ov: Mapping[str, Any]):
    return builder.build_ir(circuit, spec.resolve(circuit, {**genome, **ov}))


def response_db(circuit, genome: Mapping[str, Any], ov: Mapping[str, Any]) -> np.ndarray:
    """|V(out)| in dB re the key at OUT, on F_HZ."""
    ref = ac.transfer(_ir(circuit, genome, {"filter_in": 0}), F_HZ, "out")
    h = ac.transfer(_ir(circuit, genome, {**ov, "filter_in": 1}), F_HZ, "out")
    return 20.0 * np.log10(np.abs(h) / np.abs(ref))


def _crossing(r: np.ndarray, level_db: float, rising: bool) -> float:
    """The first frequency where the response passes `level_db` (log-interpolated)."""
    idx = np.where(r > level_db)[0] if rising else np.where(r < level_db)[0]
    if idx.size == 0 or idx[0] == 0:
        return float("nan")
    i = idx[0]
    a, b = r[i - 1], r[i]
    t = (level_db - a) / (b - a)
    return float(np.exp(np.log(F_HZ[i - 1]) + t * (np.log(F_HZ[i]) - np.log(F_HZ[i - 1]))))


def position(circuit, genome, band: str, f_knob: int) -> dict[str, Any]:
    ov = {"low_cut_hz": f_knob} if band == "low" else {"high_cut_hz": f_knob}
    r = response_db(circuit, genome, ov)
    rising = band == "low"
    f3 = _crossing(r, -3.0, rising)
    f40 = _crossing(r, -40.0, rising)
    # Slope between 2 and 3 octaves out (low: f / 4 .. f / 8; high: 4 f .. 8 f, inside 40 kHz).
    if rising:
        fa, fb = f_knob / 8.0, f_knob / 4.0
    else:
        fb = min(8.0 * f_knob, 39_000.0)
        fa = fb / 2.0
    slope = abs(np.interp(fb, F_HZ, r) - np.interp(fa, F_HZ, r)) / np.log2(fb / fa)
    pub = BROCHURE_40DB_HZ[band].get(f_knob)
    return {
        "knob_hz": f_knob,
        "f_3db_hz": f3,
        "f_3db_ratio": f3 / f_knob,
        "peak_db": float(r.max()),
        "slope_db_per_oct": float(slope),
        "f_40db_hz": f40,
        "brochure_40db_hz": pub,
        "vs_brochure_40db": None if pub is None or not np.isfinite(f40) else f40 / pub,
    }


def transient_check(circuit, genome, s: TransientSettings) -> dict[str, Any]:
    """A +28 dBm tone through the engine on two positions, against the AC analysis."""
    from varimu.sim import fast

    fs = s.sample_rate
    rows = []
    # +28 dBm into 600 ohm: 19.5 V rms across the load, so 2 x that as the source's EMF.
    emf_peak = 2.0 * np.sqrt(2.0) * np.sqrt(10 ** (28 / 10) * 1e-3 * 600.0)
    for ov, f_tone in (({"low_cut_hz": 100}, 100.0), ({"high_cut_hz": 5000}, 5000.0)):
        ir = _ir(circuit, genome, ov)
        n = int(0.5 * fs)
        t = np.arange(n) / fs
        fade = np.minimum(1.0, t / 0.05)
        x = emf_peak * fade * np.sin(2 * np.pi * f_tone * t)
        y = fast.run_transient(ir, x, settings=s).vectors["v(out)"]
        tail = slice(n // 2, n)
        ref = np.sin(2 * np.pi * f_tone * t[tail]), np.cos(2 * np.pi * f_tone * t[tail])
        amp = np.hypot(*(2 * np.mean(y[tail] * r) for r in ref))
        h = ac.transfer(ir, [f_tone], "out")[0]
        want = emf_peak * abs(h)
        resid = y[tail] - (
            2 * np.mean(y[tail] * ref[0]) * ref[0] + 2 * np.mean(y[tail] * ref[1]) * ref[1]
        )
        rows.append(
            {
                "setting": dict(ov),
                "tone_hz": f_tone,
                "out_v_peak": float(amp),
                "ac_v_peak": float(want),
                "error_db": float(20 * np.log10(amp / want)),
                "residual_db": float(
                    20 * np.log10(np.sqrt(np.mean(resid**2)) / (amp / np.sqrt(2)))
                ),
            }
        )
    return {"level_dbm": 28.0, "rows": rows}


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    del clips  # a linear filter: its response says it all
    t0 = time.perf_counter()
    genome = dict(genome or {})
    out_dir = REPORT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    s = settings or TransientSettings.from_sim_settings(engine="configured")
    circuit = spec.load_circuit(spec.circuit_path(CIRCUIT))
    log(f"{name}: responses")
    through = response_db(circuit, genome, {"low_cut_hz": 0, "high_cut_hz": 0})
    low = [position(circuit, genome, "low", f) for f in LOW_HZ]
    high = [position(circuit, genome, "high", f) for f in HIGH_HZ]
    log(f"{name}: transient at +28 dBm")
    tr = transient_check(circuit, genome, s)
    rows = low + high
    checks = {
        "passes_when_off": {
            "value_db": float(np.max(np.abs(through))),
            "passes": bool(np.max(np.abs(through)) < 0.1),
        },
        "cutoffs_near_their_knobs": {
            "ratios": [r["f_3db_ratio"] for r in rows],
            "passes": all(0.5 < r["f_3db_ratio"] < 2.0 for r in rows),
        },
        "slopes": {
            "min_db_per_oct": min(r["slope_db_per_oct"] for r in rows),
            "passes": all(r["slope_db_per_oct"] > 10.0 for r in rows),
        },
        "render_follows_ac": {
            "max_error_db": max(abs(r["error_db"]) for r in tr["rows"]),
            "passes": all(abs(r["error_db"]) < 0.1 for r in tr["rows"]),
        },
    }
    report = {
        "name": name,
        "circuit": CIRCUIT,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "genome": genome,
        "checks": checks,
        "plausible": all(c["passes"] for c in checks.values()),
        "through_max_dev_db": float(np.max(np.abs(through))),
        "low_cut": low,
        "high_cut": high,
        "brochure_source": BROCHURE_SOURCE,
        "transient": tr,
        "seconds": round(time.perf_counter() - t0, 1),
    }
    _write(out_dir, report)
    _plot(out_dir, circuit, genome)
    log(f"{name}: written to {out_dir}")
    return report


def _write(out_dir: Path, report: Mapping[str, Any]) -> None:
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def _plot(out_dir: Path, circuit, genome) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), sharey=True)
    for ax, band, knobs in ((axes[0], "low", LOW_HZ), (axes[1], "high", HIGH_HZ)):
        for f in knobs:
            ov = {"low_cut_hz": f} if band == "low" else {"high_cut_hz": f}
            ax.semilogx(F_HZ, response_db(circuit, genome, ov), lw=1.2, color="#3b6ea5")
        for f40 in BROCHURE_40DB_HZ[band].values():
            if f40 is not None:
                ax.plot([f40], [-40], "o", ms=4, color="#c0504d")
        ax.set_xlim(10, 30_000)
        ax.set_ylim(-45, 3)
        ax.grid(True, which="both", alpha=0.3)
        ax.set_xlabel("Hz")
        ax.set_title(f"{band.upper()} CUT-OFF (dots: the brochure's -40 dB points)")
    axes[0].set_ylabel("dB re the key at OUT")
    fig.tight_layout()
    fig.savefig(out_dir / "response.png", dpi=110)
    plt.close(fig)

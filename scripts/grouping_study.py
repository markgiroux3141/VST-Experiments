"""Grouping cues across recording chains: per track vs on the bus (docs/SCENE_ANALYSIS.md).

Two questions the separation study's energetic pre-screen can't answer:

1. **The bus experiment.** The same device on each track (dev(t) + dev(m)) against the
   two tracks summed into one device (dev(t + m)). What the ear meets in the second case
   that it doesn't in the first is the interaction residual dev(t + m) - dev(t) - dev(m):
   intermodulation and shared gain. Measured: its energy, and the grouping measures of
   `varimu.separation.grouping` on each source's share of the mix (`grouping.shares`).
   Devices: the 5E3 and speaker at the study's setting and hotter (saturation), the 670
   driven hot at TC 1 (compression), the EQP-1A (nearly linear: the control).
2. **The study's conditions.** The grouping measures on the separation study's audio
   (cache/separation/conditions/, each track at -23 LUFS, the target -6 dB under the
   masker), plus flutter and room variants of the masker computed here (no renders):
   does a wobbling or reverberant accompaniment lose its harmonic-cancellation benefit
   (de Cheveigne 2021)?
3. **Intervals** (`--only intervals`). Two sustained tones through the 5E3 alone and
   together: does the interaction residual sit on the common root's harmonic series
   (octaves, fifths) or on none (the other equal-tempered intervals)?

The sources are the study's dry target and masker (cache/separation/conditions/dry/),
each at -23 LUFS, then one gain for both so the louder peaks at -12 dBFS into a device.
Renders run at production through the cached runner, `--jobs` at a time at the runner's
priority (another session may need the CPU). Writes reports/separation/grouping.json.

    uv run --extra fast python scripts/grouping_study.py [--only conditions bus intervals]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varimu.separation import flutter, grouping, metrics, room  # noqa: E402
from varimu.sim import io, runner  # noqa: E402

COND_DIR = ROOT / "cache" / "separation" / "conditions"
OUT = ROOT / "reports" / "separation" / "grouping.json"
INPUT_PEAK_DBFS = -12.0
MIX_DB = -6.0  # the target under the masker, as the study's demo mixes

# name -> (circuit or None for the 670, overrides)
BUS_DEVICES = {
    "eqp1a": (
        "pultec_eqp1a",
        {
            "lf_freq_hz": 100,
            "lf_boost": 0.5,
            "lf_atten": 0.3,
            "hf_boost_freq_khz": 5,
            "hf_boost": 0.4,
            "bandwidth": 0.6,
            "hf_atten": 0.5,
            "hf_atten_freq_khz": 10,
        },
    ),
    "5e3": ("fender_5e3", {"volume_bright": 0.5, "tone": 0.6}),
    "5e3_hot": ("fender_5e3", {"volume_bright": 0.85, "tone": 0.6}),
    "670_hot": (None, {"input_atten_db": 0.0, "ac_threshold": 1.0, "time_constant": 1}),
}


def load(path: Path) -> np.ndarray:
    x, fs = sf.read(path, dtype="float64")
    return x


def rounded(d):
    if isinstance(d, dict):
        return {str(k): rounded(v) for k, v in d.items()}
    if isinstance(d, float):
        return round(d, 4)
    return d


def measures(t, m, fs, *, t_clean=None, m_clean=None, notes=None) -> dict:
    """The grouping measures, plus the glimpse proportion, with the target at MIX_DB."""
    g = 10 ** (MIX_DB / 20)
    out = grouping.all_measures(
        t * g, m, fs, t_clean=None if t_clean is None else t_clean * g, m_clean=m_clean
    )
    out["glimpse_notes"] = metrics.glimpse_proportion(t * g, m, fs, notes=notes)
    out["coherence"] = {
        "cross": out["coherence"]["cross"],
        "within": out["coherence"]["within"],
        "by_rate": {k: v[0] for k, v in out["coherence"]["rates"].items()},
    }
    out["harmonic"] = {k: out["harmonic"][k] for k in ("gain_db", "m_gain_db", "residual_db")}
    out["envelope_snr"] = out["envelope_snr"]["snr_env_db"]
    return out


def bus_experiment(fs: int, jobs: int) -> dict:
    t0, m0 = load(COND_DIR / "dry" / "target.wav"), load(COND_DIR / "dry" / "masker.wav")
    n = min(len(t0), len(m0))
    t0, m0 = metrics.match_loudness(t0[:n], fs), metrics.match_loudness(m0[:n], fs)
    g = 10 ** (INPUT_PEAK_DBFS / 20) / max(np.abs(t0).max(), np.abs(m0).max())
    t0, m0 = t0 * g, m0 * g
    settings = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production")
    keys = [(d, k) for d in BUS_DEVICES for k in ("t", "m", "tm", "z")]
    inputs = {"t": t0, "m": m0, "tm": t0 + m0, "z": np.zeros_like(t0)}
    rjobs = [
        runner.RenderJob(
            samples=inputs[k],
            overrides=BUS_DEVICES[d][1],
            label=f"grouping bus {d} {k}",
            circuit=BUS_DEVICES[d][0],
        )
        for d, k in keys
    ]
    done = runner.render_many(rjobs, settings=settings, max_jobs=jobs)
    out = dict(zip(keys, (r.output for r in done), strict=True))
    rows = {"dry": measures(*(metrics.match_loudness(x, fs) for x in (t0, m0)), fs, notes=t0)}
    for d in BUS_DEVICES:
        yt, ym, ytm, y0 = (out[(d, k)] for k in ("t", "m", "tm", "z"))
        n = min(map(len, (yt, ym, ytm, y0)))
        # The device's idle output (hum, its supply's ripple) belongs to neither source:
        # each render is taken relative to the device's response to silence.
        idle_db = 10 * np.log10(np.sum(y0[:n] ** 2) / np.sum(yt[:n] ** 2))
        yt, ym, ytm = yt[:n] - y0[:n], ym[:n] - y0[:n], ytm[:n] - y0[:n]
        resid = ytm - yt - ym
        # For listening, each mix at -20 LUFS (loudness lies); the residual at the bus's gain.
        gain = 10 ** ((-20.0 - metrics.loudness_lufs(yt + ym, fs)) / 20)
        gain_bus = 10 ** ((-20.0 - metrics.loudness_lufs(ytm, fs)) / 20)
        st, sm = ytm - ym, ytm - yt  # grouping.shares, from the renders
        # Scale both to the study's convention: each share at -23 LUFS, the target -6 dB.
        gt_p = 10 ** ((-23.0 - metrics.loudness_lufs(yt, fs)) / 20)
        gm_p = 10 ** ((-23.0 - metrics.loudness_lufs(ym, fs)) / 20)
        per = measures(yt * gt_p, ym * gm_p, fs, notes=t0[:n])
        bus = measures(st * gt_p, sm * gm_p, fs, t_clean=yt * gt_p, m_clean=ym * gm_p, notes=t0[:n])

        # Gain change through the device (the 670's compression): the source's level out
        # over in, alone and in the mix.
        def lufs(x):
            return metrics.loudness_lufs(x, fs)

        rows[d] = {
            "residual_db": 10 * np.log10(np.sum(resid**2) / np.sum(ytm**2)),
            "idle_db_re_target": idle_db,
            "gain_t_alone_db": lufs(yt) - lufs(t0[:n]),
            "gain_t_in_mix_db": lufs(st) - lufs(t0[:n]),
            "gain_m_alone_db": lufs(ym) - lufs(m0[:n]),
            "gain_m_in_mix_db": lufs(sm) - lufs(m0[:n]),
            "per_track": per,
            "bus": bus,
            # The target's most favourable reading: its own render alone against
            # everything else in the bus mix (the masker and all the intermodulation).
            "bus_target_clean": measures(
                yt * gt_p, sm * gm_p, fs, t_clean=yt * gt_p, m_clean=ym * gm_p, notes=t0[:n]
            ),
        }
        d_out = ROOT / "cache" / "separation" / "grouping" / d
        d_out.mkdir(parents=True, exist_ok=True)
        for name, x in (
            ("per_track", (yt + ym) * gain),
            ("bus", ytm * gain_bus),
            ("residual", resid * gain_bus),
        ):
            sf.write(d_out / f"{name}.wav", x.astype(np.float32), fs, subtype="FLOAT")
        print(f"{d}: residual {rows[d]['residual_db']:+.1f} dB re the bus mix")
    return rows


def condition_measures(fs: int) -> dict:
    rows = {}
    dry_t = load(COND_DIR / "dry" / "target.wav")
    for d in sorted(p for p in COND_DIR.iterdir() if p.is_dir()):
        t, m = load(d / "target.wav"), load(d / "masker.wav")
        n = min(len(t), len(m), len(dry_t))
        rows[d.name] = measures(t[:n], m[:n], fs, notes=dry_t[:n])
        print(f"condition {d.name} done")
    # Variants of the masker (the target dry): flutter at several depths, a room, both.
    dry_m = load(COND_DIR / "dry" / "masker.wav")
    n = min(len(dry_t), len(dry_m))
    t, m = dry_t[:n], dry_m[:n]
    hall = room.impulse_response(room.ROOMS["hall"], (2.0, 2.0, 1.2), (4.3, 1.2, 1.5), fs)
    from scipy.signal import fftconvolve

    def in_hall(x):
        return metrics.match_loudness(fftconvolve(x, hall)[: len(x)], fs)

    for scale in (1, 4, 16):
        mf = metrics.match_loudness(flutter.apply(m, fs, 2, flutter.TOTAL_RMS * scale), fs)
        rows[f"masker_flutter_x{scale}"] = measures(t, mf, fs, notes=t)
        rows[f"masker_flutter_x{scale}_hall"] = measures(t, in_hall(mf), fs, notes=t)
        print(f"masker flutter x{scale} done")
    rows["masker_hall"] = measures(t, in_hall(m), fs, notes=t)
    # A performance reference: the masker 30 ms late (an ensemble's onset asynchrony).
    late = np.concatenate([np.zeros(int(0.03 * fs)), m])[:n]
    rows["masker_30ms_late"] = measures(t, late, fs, notes=t)
    return rows


# Two sustained tones through the 5E3 at once: does the intermodulation fall on a common
# root? (Herbst 2017-2019: distorted power chords stay pleasant, dense ones don't.)
INTERVALS = {"octave": 12, "fifth": 7, "major_third": 4, "tritone": 6, "minor_second": 1}
LOW_HZ = 220.0


def _tone(f0: float, fs: int, seconds: float = 2.5) -> np.ndarray:
    tt = np.arange(int(seconds * fs)) / fs
    x = sum(np.sin(2 * np.pi * k * f0 * tt) / k for k in range(1, 11) if k * f0 < 8000)
    fade = np.minimum(1.0, np.minimum(tt, tt[-1] - tt) / 0.05)
    x = x * fade
    return x * 10 ** (INPUT_PEAK_DBFS / 20) / np.abs(x).max()


def _best_root(ratio: float, max_q: int = 5) -> tuple[int, int, float]:
    """The just ratio p / q (q <= max_q) nearest `ratio`, and its mistuning in %."""
    best = min(
        ((round(ratio * q), q) for q in range(1, max_q + 1)),
        key=lambda pq: abs(pq[0] / pq[1] / ratio - 1),
    )
    return best[0], best[1], 100 * (best[0] / best[1] / ratio - 1)


def interval_experiment(fs: int, jobs: int) -> dict:
    from scipy import signal as sg

    circuit, overrides = BUS_DEVICES["5e3"]
    settings = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production")
    lo = _tone(LOW_HZ, fs)
    inputs = {("z", "z"): np.zeros_like(lo), ("lo", "lo"): lo}
    for name, semis in INTERVALS.items():
        hi = _tone(LOW_HZ * 2 ** (semis / 12), fs)
        inputs[(name, "hi")] = hi
        inputs[(name, "both")] = lo + hi
    keys = list(inputs)
    done = runner.render_many(
        [
            runner.RenderJob(
                samples=inputs[k],
                overrides=overrides,
                label=f"grouping interval {k[0]} {k[1]}",
                circuit=circuit,
            )
            for k in keys
        ],
        settings=settings,
        max_jobs=jobs,
    )
    y = {k: r.output for k, r in zip(keys, done, strict=True)}
    n = min(len(v) for v in y.values())
    y0 = y[("z", "z")][:n]
    ylo = y[("lo", "lo")][:n] - y0
    sos = sg.butter(4, 4000.0, fs=fs, output="sos")
    core = slice(int(0.3 * fs), n - int(0.3 * fs))

    def comb_db(x, f0):
        x = sg.sosfiltfilt(sos, x)
        times = np.array([0.0, n / fs])
        c = grouping._comb(x, fs, times, np.array([f0, f0]))
        return 10 * np.log10(np.sum(c[core] ** 2) / np.sum(x[core] ** 2))

    rows = {}
    for name, semis in INTERVALS.items():
        yhi = y[(name, "hi")][:n] - y0
        yboth = y[(name, "both")][:n] - y0
        r = yboth - ylo - yhi
        p, q, mis = _best_root(2 ** (semis / 12))
        root = LOW_HZ / q
        rows[name] = {
            "residual_db": 10 * np.log10(np.sum(r[core] ** 2) / np.sum((ylo + yhi)[core] ** 2)),
            "just_ratio": f"{p}:{q}",
            "mistuning_pct": mis,
            "root_hz": root,
            # A comb at the root's period: very negative = the residual sits on the root's
            # series; about +3 dB = unrelated to it (a comb doubles random content's energy).
            "residual_root_comb_db": comb_db(r, root),
            "per_track_root_comb_db": comb_db(ylo + yhi, root),
        }
        print(f"interval {name}: {rows[name]}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--only", nargs="*", default=["bus", "conditions"])
    a = ap.parse_args()
    fs = io.TransientSettings.from_sim_settings(engine="circuitsim").sample_rate
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    if "conditions" in a.only:
        res["conditions"] = rounded(condition_measures(fs))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(res, indent=1))
    if "bus" in a.only:
        res["bus"] = rounded(bus_experiment(fs, a.jobs))
        res["bus_devices"] = {
            k: {"circuit": v[0] or "fairchild_670", "set": v[1]} for k, v in BUS_DEVICES.items()
        }
    if "intervals" in a.only:
        res["intervals"] = rounded(interval_experiment(fs, a.jobs))
    res["measures"] = (
        "coherence: cross-source envelope correlation, 2-32 Hz (higher = fused); onsets: "
        "share of target onsets within 30 ms of a masker onset (higher = fused); harmonic "
        "gain_db: the target's SNR gain from cancelling the masker at its F0 (higher = "
        "separable), m_gain_db the reverse, residual_db what survives both combs; "
        "envelope_snr: mr-sEPSM SNRenv (higher = separable); glimpse_notes: Cooke's "
        "proportion on the dry notes' cells. Target -6 dB under the masker, each -23 LUFS."
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()

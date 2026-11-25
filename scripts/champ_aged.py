"""PB2's first spike (docs/PART_NOISE_PLAN.md): the Fender 5F1 aged, its carbon resistors'
excess noise in the coupled simulation, realistic and exaggerated.

    uv run --extra listen --extra fast python scripts/champ_aged.py [--seconds 10] [--unit 1]

Production quality, B5's noise on (Johnson, tube shot and flicker, the mains' wander) in every
render, so the floor is the amp's own. For each condition (new, played, cap_job, wreck):
pass 1 (the aged amp, excess sources at zero) then pass 2 (the excess noise injected); on
cap_job also x10, x100, x1000 the excess noise. Two programs: the dry guitar at VOLUME 0.5,
and idle (nothing plugged in... the input at 0 V) at VOLUME 1.0.

-> reports/part_noise/champ/:
- audio/playing/<cond>[_xN].wav: loudness-matched (-23 LUFS), the amp as heard;
- audio/idle/<cond>[_xN].wav: one fixed gain for all (the floor's real level: turn it up);
- audio/excess_only/<program>_<cond>[_xN].wav: pass 2 - pass 1, what the excess noise adds,
  one fixed gain per program;
- summary.json: each condition's bias, rails, hum and noise in dB SPL at 1 m, levels.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder
from varimu.circuit.spec import load_circuit
from varimu.config import load_sim_settings
from varimu.part_noise import aging
from varimu.sim import fast
from varimu.sim.io import load_audio

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "part_noise" / "champ"
CIRCUIT = REPO / "config" / "circuits" / "fender_5f1.yaml"
P_REF = 20e-6
EXAGGERATIONS = (10.0, 100.0, 1000.0)
LUFS_TARGET = -23.0


def program_playing(seconds: float, fs: int) -> np.ndarray:
    x = load_audio(REPO / "data" / "clips" / "Dry Guitar.wav", fs)[: int(seconds * fs)]
    x = x * 10 ** (-11.5 / 20) / np.max(np.abs(x))  # peaks 0.27 V (full scale 1 V: a pickup)
    f = int(0.02 * fs)
    x[:f] *= np.linspace(0, 1, f)
    return x


def spl_db(p: np.ndarray) -> float:
    return 20 * math.log10(max(float(np.sqrt(np.mean(p**2))), 1e-30) / P_REF)


def band_spl_db(p: np.ndarray, fs: int, f0: float, width: float = 2.0) -> float:
    spec = np.fft.rfft(p * np.hanning(p.size))
    f = np.fft.rfftfreq(p.size, 1 / fs)
    keep = np.abs(f - f0) < width
    # Hann's coherent gain 0.5 and its noise bandwidth 1.5 bins: the line's rms.
    amp = 2 * np.sqrt(np.sum(np.abs(spec[keep]) ** 2) / 1.5) / (0.5 * p.size)
    return 20 * math.log10(max(amp / math.sqrt(2), 1e-30) / P_REF)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--idle-seconds", type=float, default=6.0)
    ap.add_argument("--unit", type=int, default=1, help="the aging draws' seed (UNIT #)")
    ap.add_argument("--only", nargs="*", default=list(aging.CONDITIONS))
    ap.add_argument(
        "--rank",
        metavar="COND",
        help="instead: each resistor's excess noise alone, idle at VOLUME 1.0 on COND "
        "(-> rank_<COND>.json: which parts matter)",
    )
    args = ap.parse_args()
    if args.rank:
        return rank(args)
    import pyloudnorm
    import soundfile as sf

    settings = load_sim_settings()
    fs = settings.sample_rate
    seed = settings.seed
    spec = load_circuit(CIRCUIT)
    full_scale_pa = 30.0  # the circuit file's output_pascals_peak
    programs = {
        "playing": (program_playing(args.seconds, fs), 0.5),
        "idle": (np.zeros(int(args.idle_seconds * fs)), 1.0),
    }

    jobs = {}  # (program, cond) -> (ir, noisy, x)
    for prog, (x, volume) in programs.items():
        base = builder.build(spec, {"volume": volume}, noise=seed).ir
        for name in args.only:
            ir, noisy = aging.apply(base, aging.CHAMP_5F1, aging.CONDITIONS[name], args.unit)
            jobs[(prog, name)] = (aging.with_sources(ir, noisy), noisy, x)

    workers = max(1, (os.cpu_count() or 4) - 2)
    t0 = time.perf_counter()

    def pass1(key):
        ir, noisy, x = jobs[key]
        return key, fast.run_transient(ir, x, controls=aging.zero_controls(noisy, len(x))).vectors

    with ThreadPoolExecutor(workers) as pool:
        first = dict(pool.map(pass1, jobs))
    print(f"pass 1: {len(first)} renders, {time.perf_counter() - t0:.0f} s", flush=True)

    second_keys = [(k, 1.0) for k in jobs]
    second_keys += [
        ((p, "cap_job"), e) for p in programs for e in EXAGGERATIONS if (p, "cap_job") in jobs
    ]

    def pass2(item):
        key, ex = item
        ir, noisy, x = jobs[key]
        ctl = aging.excess_controls(first[key], noisy, fs, seed, exaggerate=ex)
        return (key, ex), fast.run_transient(ir, x, controls=ctl).vectors

    with ThreadPoolExecutor(workers) as pool:
        second = dict(pool.map(pass2, second_keys))
    print(f"pass 2: {len(second)} renders, {time.perf_counter() - t0:.0f} s", flush=True)

    def tag(name, ex):
        return name if ex == 1.0 else f"{name}_x{int(ex)}"

    meter = pyloudnorm.Meter(fs)
    summary = {"seed": seed, "unit": args.unit, "conditions": {}, "renders": {}}
    for name in args.only:
        c = aging.CONDITIONS[name]
        summary["conditions"][name] = {
            "title": c.title,
            "drift_mean": c.drift_mean,
            "drift_sd": c.drift_sd,
            "ni_add_db": c.ni_add_db,
            "coupling_leak_ohm": c.coupling_leak_ohm,
            "electro_c": c.electro_c,
            "electro_esr": c.electro_esr,
            "source": c.source,
        }
        if ("idle", name) in first:
            v = first[("idle", name)]
            rk6 = next(e for e in jobs[("idle", name)][0].elements() if e.name == "RK6").r_ohm
            summary["conditions"][name]["idle"] = {
                "v6v6_grid_minus_cathode_v": float(np.mean(v["v(g6)"]) - np.mean(v["v(k6)"])),
                "v6v6_cathode_ma": float(np.mean(v["v(k6)"]) / rk6 * 1e3),
                "b1_v": float(np.mean(v["v(b1)"])),
                "b1_ripple_v_rms": float(np.std(v["v(b1)"] - np.mean(v["v(b1)"]))),
                "volume_wiper_dc_v": float(np.mean(v["v(vol)"])),
                "out_db_spl": spl_db(v["v(out)"]),
                "hum_60hz_db_spl": band_spl_db(v["v(out)"], fs, 60.0),
                "hum_120hz_db_spl": band_spl_db(v["v(out)"], fs, 120.0),
            }

    # Fixed gains: idle and excess-only per program, from their loudest.
    idle_peak = max(float(np.max(np.abs(second[k]["v(out)"]))) for k in second if k[0][0] == "idle")
    gain_idle = 10 ** (-1 / 20) / idle_peak if idle_peak > 0 else 1.0
    diff = {k: second[k]["v(out)"] - first[k[0]]["v(out)"] for k in second}
    gain_diff = {}
    for prog in programs:
        peaks = [float(np.max(np.abs(d))) for k, d in diff.items() if k[0][0] == prog]
        if peaks:
            gain_diff[prog] = 10 ** (-1 / 20) / max(max(peaks), 1e-30)

    def write(path: Path, y: np.ndarray) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        peak = float(np.max(np.abs(y)))
        if peak > 0.99:
            y = y * (0.99 / peak)
        sf.write(path, y.astype(np.float32), fs, subtype="FLOAT")

    for (key, ex), vec in sorted(second.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        prog, name = key
        out = vec["v(out)"]
        t = tag(name, ex)
        entry = {"out_db_spl": spl_db(out), "excess_only_db_spl": spl_db(diff[(key, ex)])}
        if prog == "playing":
            y = out / full_scale_pa
            lufs = meter.integrated_loudness(y)
            entry["lufs_at_full_scale"] = lufs
            write(OUT / "audio" / "playing" / f"{t}.wav", y * 10 ** ((LUFS_TARGET - lufs) / 20))
        else:
            entry["idle_file_gain_db"] = 20 * math.log10(gain_idle)
            write(OUT / "audio" / "idle" / f"{t}.wav", out * gain_idle)
        write(OUT / "audio" / "excess_only" / f"{prog}_{t}.wav", diff[(key, ex)] * gain_diff[prog])
        entry["excess_only_file_gain_db"] = 20 * math.log10(gain_diff[prog])
        summary["renders"][f"{prog}/{t}"] = entry
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    for name, c in summary["conditions"].items():
        i = c.get("idle", {})
        print(
            f"{name:8s} 6V6 grid-cathode {i.get('v6v6_grid_minus_cathode_v', 0):+7.2f} V, "
            f"Ik {i.get('v6v6_cathode_ma', 0):5.1f} mA, B+1 {i.get('b1_v', 0):6.1f} V "
            f"ripple {i.get('b1_ripple_v_rms', 0):6.3f} V, idle {i.get('out_db_spl', 0):5.1f} dB "
            f"SPL (120 Hz {i.get('hum_120hz_db_spl', 0):5.1f})"
        )
    for k, e in summary["renders"].items():
        print(
            f"{k:26s} out {e['out_db_spl']:6.1f} dB SPL, excess alone "
            f"{e['excess_only_db_spl']:6.1f} dB SPL"
        )
    print(f"total {time.perf_counter() - t0:.0f} s")


def rank(args) -> None:
    """Each noisy resistor's excess noise alone at the output, idle (VOLUME 1.0), dB SPL."""
    settings = load_sim_settings()
    fs, seed = settings.sample_rate, settings.seed
    spec = load_circuit(CIRCUIT)
    x = np.zeros(int(args.idle_seconds * fs))
    base = builder.build(spec, {"volume": 1.0}, noise=seed).ir
    ir, noisy = aging.apply(base, aging.CHAMP_5F1, aging.CONDITIONS[args.rank], args.unit)
    ir = aging.with_sources(ir, noisy)
    zero = aging.zero_controls(noisy, len(x))
    v1 = fast.run_transient(ir, x, controls=zero).vectors
    full = aging.excess_controls(v1, noisy, fs, seed)

    def one(r: aging.Noisy):
        ctl = dict(zero)
        ctl[aging.control_name(r.name)] = full[aging.control_name(r.name)]
        v2 = fast.run_transient(ir, x, controls=ctl).vectors
        i = (v1.get(f"v({r.a})", 0.0) - v1.get(f"v({r.b})", 0.0)) / r.r_ohm
        return r.name, {
            "r_ohm": r.r_ohm,
            "ni_db": r.ni_db,
            "mean_current_ma": float(np.mean(i) * 1e3),
            "out_db_spl": spl_db(v2["v(out)"] - v1["v(out)"]),
        }

    with ThreadPoolExecutor(max(1, (os.cpu_count() or 4) - 2)) as pool:
        res = dict(pool.map(one, noisy))
    order = sorted(res, key=lambda k: -res[k]["out_db_spl"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"rank_{args.rank}.json").write_text(json.dumps({k: res[k] for k in order}, indent=2))
    for k in order:
        e = res[k]
        print(
            f"{k:6s} {e['r_ohm'] / 1e3:8.1f}k NI {e['ni_db']:+5.1f} dB "
            f"I {e['mean_current_ma']:+8.3f} mA -> {e['out_db_spl']:6.1f} dB SPL"
        )


if __name__ == "__main__":
    main()

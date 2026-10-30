"""What B5's noise does to the tube synth (device builder B5; TUBE_SYNTH_PLAN.md S4).

    uv run --extra fast python scripts/noise_synth_study.py [--seconds 10] [--pitch -15 -5]

tube_synth.yaml at production (Jiles-Atherton cores), a held note per pitch voltage, four
variants: noise off; all of it; the circuit's (resistors and tubes) without the mains
wander; the mains wander alone. Per variant: the oscillator's cycle-to-cycle jitter and its
slow wander (100 ms means) in cents, the output level's wander (100 ms rms) in dB, the
floor between the harmonics re the fundamental, and the output with no key down (dBFS).
-> reports/tube_synth/noise/summary.json, pitch.png
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy.signal import welch

from varimu.circuit import builder, spec
from varimu.circuit import ir as I
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io
from varimu.synth import vco

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "tube_synth" / "noise"
PANEL = {"cutoff": 0.7, "resonance": 0.3, "attack": 0.05, "release": 0.3, "wave": 1.0}
KEY_UP_V, KEY_DOWN_V = -110.0, -1.0
FULL_SCALE_V = 3.5  # tube_synth.yaml full_scale.output_volts_peak
VARIANTS = ("off", "all", "circuit", "mains")


def circuit_ir(variant: str) -> I.CircuitIR:
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "tube_synth.yaml")
    p = spec.resolve(s, PANEL)
    if variant == "off":
        ir = builder.build_ir(s, p, cores="ja", noise=False)
    else:
        ir = builder.build_ir(s, p, cores="ja")
    if variant == "circuit":
        ir = dataclasses.replace(ir, noise=I.NoiseSpec(ir.noise.seed, ir.noise.rate_hz))
    if variant == "mains":
        secs = tuple(
            dataclasses.replace(
                sec,
                elements=tuple(
                    e for e in sec.elements if not isinstance(e, I.NoiseCurrent | I.TubeNoise)
                ),
            )
            for sec in ir.sections
        )
        ir = dataclasses.replace(ir, sections=secs)
    probes = ("out", "o_t")
    return dataclasses.replace(ir, probes=tuple(I.VoltageProbe(n) for n in probes))


def render(variant: str, pitch_v: float, seconds: float, key: bool) -> dict[str, np.ndarray]:
    fs = io.load_sim_settings().sample_rate
    n = int(seconds * fs)
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production"),
        full_scale_volts_peak=1.0,
    )
    controls = {
        "gate": np.full(n, KEY_DOWN_V if key else KEY_UP_V),
        "pitch": np.full(n, pitch_v),
    }
    v = fast.run_transient(circuit_ir(variant), np.zeros(n), settings=st, controls=controls)
    return {k.removeprefix("v(").removesuffix(")"): x for k, x in v.vectors.items()}


def readings(v: dict[str, np.ndarray], fs: int) -> dict:
    tank, out = v["o_t"], v["out"]
    skip = int(0.5 * fs)  # past the attack
    f0 = vco.frequency(tank[skip:], fs)
    t, f = vco.cycle_frequencies(tank[skip:], fs, lowpass_hz=3 * f0)
    c = vco.cents(f, f0)
    jitter = float(np.std(np.diff(c)) / np.sqrt(2))
    slow = vco.cents(vco.smoothed(t, f, 0.1), f0)
    w = int(0.1 * fs)
    seg = out[skip : skip + (len(out) - skip) // w * w].reshape(-1, w)
    level_db = 20 * np.log10(np.sqrt(np.mean(seg**2, axis=1)))
    # The floor between the harmonics, re the fundamental (Welch, 1 Hz-ish bins).
    ff, s = welch(out[skip:], fs=fs, nperseg=2**16)
    h = np.arange(1, int(20000 / f0) + 1) * f0
    near = np.min(np.abs(ff[:, None] - h[None, :]), axis=1) < max(15.0, 0.02 * f0)
    band = (ff > 100) & (ff < 20000) & ~near
    fund = s[np.argmin(np.abs(ff - f0))]
    step = max(1, len(t) // 400)
    return {
        "f0_hz": f0,
        "jitter_cents_rms": jitter,
        "wander_cents_rms": float(np.std(slow)),
        "wander_cents_pp": float(np.ptp(slow)),
        "level_db_rms": float(np.std(level_db)),
        "floor_db_re_fundamental_per_bin": float(10 * np.log10(np.median(s[band]) / fund)),
        "pitch_trace": (t[::step].tolist(), slow[::step].tolist()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--pitch", type=float, nargs="*", default=[-15.0, -5.0])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    fs = io.load_sim_settings().sample_rate
    jobs = [(var, pv, True) for pv in args.pitch for var in VARIANTS]
    jobs += [(var, args.pitch[0], False) for var in ("off", "all")]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {j: ex.submit(render, j[0], j[1], args.seconds if j[2] else 2.0, j[2]) for j in jobs}
        res = {j: f.result() for j, f in futs.items()}
    print(f"rendered {len(jobs)} runs in {time.perf_counter() - t0:.0f} s")
    out: dict = {"seconds": args.seconds, "panel": PANEL, "held": {}, "key_up": {}}
    for pv in args.pitch:
        out["held"][str(pv)] = {}
        for var in VARIANTS:
            r = readings(res[(var, pv, True)], fs)
            out["held"][str(pv)][var] = r
            print(
                f"pitch {pv:+.0f} V {var:8s} f0 {r['f0_hz']:7.1f} Hz  jitter "
                f"{r['jitter_cents_rms']:.4f} c  wander {r['wander_cents_rms']:.3f} c rms "
                f"({r['wander_cents_pp']:.2f} pp)  level {r['level_db_rms']:.4f} dB  floor "
                f"{r['floor_db_re_fundamental_per_bin']:.1f} dB/bin"
            )
    for var in ("off", "all"):
        y = res[(var, args.pitch[0], False)]["out"][int(0.5 * fs) :]
        dbfs = 20 * np.log10(np.sqrt(np.mean((y - np.mean(y)) ** 2)) / FULL_SCALE_V)
        out["key_up"][var] = {"rms_dbfs": float(dbfs)}
        print(f"key up, {var}: {dbfs:.1f} dBFS rms")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    plot(out, args.out / "pitch.png")


def plot(out: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pitches = list(out["held"])
    fig, axes = plt.subplots(len(pitches), 1, figsize=(9, 3.2 * len(pitches)), squeeze=False)
    for ax, pv in zip(axes[:, 0], pitches, strict=True):
        for var, r in out["held"][pv].items():
            t, c = r["pitch_trace"]
            ax.plot(t, c, label=var, lw=1)
        ax.set_title(f"pitch {pv} V: the held note's pitch (100 ms means)")
        ax.set_xlabel("s")
        ax.set_ylabel("cents re its mean")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=110)


if __name__ == "__main__":
    main()

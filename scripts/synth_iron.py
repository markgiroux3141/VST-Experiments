"""The tube synth's iron crackling (docs/PART_NOISE_PLAN.md): Barkhausen avalanches in its four
mumetall cores (the reactor filter's TA / TB, the oscillator's OTA / OTB), driven by each core's
own irreversible magnetization, injected at the core nodes (`varimu.part_noise.iron`).

    uv run --extra listen --extra fast python scripts/synth_iron.py [--only SCENARIO ...]
        [--stress 1 10 100 1000]

Draft quality (what Play plays) with the app's partition and the synth's own noise on. Per
scenario: pass 1 (no avalanches, STRESS 0), the cores' B replayed through their models, then a
pass 2 per STRESS. -> reports/part_noise/synth_iron/:
- audio/<scenario>/stress_<N>.wav: loudness-matched (-23 LUFS) within the scenario;
- audio/crackle_only/<scenario>_stress_<N>.wav: pass 2 - pass 1, one gain per scenario;
- <scenario>.png: each core's irreversible drive and the crackle's spectrogram at the top STRESS;
- summary.json.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import re
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit import ir as irm
from varimu.config import CONFIG_DIR
from varimu.part_noise import iron, rng_for
from varimu.sim import fast, io

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "reports" / "part_noise" / "synth_iron"
OUT = OUT_ROOT
SYNTH = CONFIG_DIR / "circuits" / "tube_synth.yaml"
PARTITION = (
    "resonance",
    "|",
    "input",
    "filter",
    "cutoff",
    "|",
    "envelope",
    "|",
    "ring",
    "|",
    "oscillator",
    "pitch",
    "|",
    "saw pitch",
    "saw",
    "|",
    "lfo",
    "|",
    "power supply",
    "bias supply",
    "saw supply",
)  # fmt: skip  (varimu-app's panel.rs, tube_synth)
CORES = ("ta_core", "tb_core", "ota_core", "otb_core")
TARGETS = {"filter": CORES[:2], "osc": CORES[2:], "all": CORES}
KEY_UP_V, KEY_DOWN_V = -110.0, -1.0
GM_S = 1e-6
LUFS_TARGET = -23.0
FULL_SCALE_V = 3.5  # tube_synth.yaml's output_volts_peak


def tuning() -> tuple[np.ndarray, np.ndarray]:
    """varimu-app's TUBE_SYNTH_TUNING (HIGH range): (Hz, pitch volts)."""
    text = (REPO / "crates" / "varimu-app" / "src" / "panel.rs").read_text(encoding="utf-8")
    block = text.split("const TUBE_SYNTH_TUNING: &[(f64, f64)] = &[", 1)[1].split("];", 1)[0]
    pairs = re.findall(r"\(([\d.]+), (-?[\d.]+)\)", block)
    pts = np.array([[float(a), float(b)] for a, b in pairs])
    return pts[:, 0], pts[:, 1]


def pitch_v(hz: float) -> float:
    f, v = tuning()
    return float(np.interp(math.log(hz), np.log(f), v))


def note_hz(name: str) -> float:
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    semis = names[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
    return 440.0 * 2 ** (semis / 12)


def keys(t, notes, legato=False):
    """(gate, pitch) for notes [(name, on_s, off_s)]: the pitch holds after a release."""
    gate = np.full(t.size, KEY_UP_V)
    pitch = np.full(t.size, pitch_v(note_hz(notes[0][0])))
    for i, (name, on, off) in enumerate(notes):
        gate[(t >= on) & (t < off)] = KEY_DOWN_V
        end = notes[i + 1][1] if i + 1 < len(notes) else t[-1] + 1
        pitch[(t >= on) & (t < end)] = pitch_v(note_hz(name))
    if legato:
        gate[(t >= notes[0][1]) & (t < notes[-1][2])] = KEY_DOWN_V
    return gate, pitch


SCENARIOS = {
    # name: (panel, notes, legato, seconds, what it shows)
    "sweep": (
        {"env_amount": 0.6, "cutoff": 0.25, "attack": 0.6, "decay": 0.6, "sustain": 0.6,
         "release": 0.5, "resonance": 0.5},
        [("A2", 0.2, 3.2)], False, 4.5,
        "one long note, the envelope sweeping the filter's iron up and down",
    ),
    "wobble": (
        {"env_amount": 0.0, "cutoff": 0.2, "attack": 0.0, "sustain": 1.0, "release": 0.3,
         "wobble": 0.8, "lfo_rate": 0.3, "resonance": 0.5},
        [("A2", 0.2, 4.8)], False, 5.0,
        "a held note, the LFO (~0.4 Hz) sweeping the cutoff: the iron moved slowly and steadily",
    ),
    "riff": (
        {"env_amount": 0.8, "cutoff": 0.1, "attack": 0.0, "decay": 0.3, "sustain": 0.2,
         "release": 0.2, "resonance": 0.6},
        [("A2", 0.2, 0.55), ("C3", 0.7, 1.05), ("E3", 1.2, 1.55), ("A3", 1.7, 2.05),
         ("G3", 2.2, 2.55), ("E3", 2.7, 3.3)], False, 4.0,
        "plucks: a fast filter snap per note, then the decay's slower sweep",
    ),
    "glide": (
        {"env_amount": 0.3, "cutoff": 0.25, "attack": 0.1, "sustain": 0.8, "release": 0.4,
         "glide": 0.6, "resonance": 0.4},
        [("A2", 0.2, 1.2), ("A3", 1.2, 2.2), ("A2", 2.2, 3.2), ("E3", 3.2, 4.2)], True, 4.8,
        "legato octaves with GLIDE: the oscillator's reactor iron swept by the pitch",
    ),
}  # fmt: skip


def build(panel: dict) -> irm.CircuitIR:
    s = spec.load_circuit(SYNTH)
    ir = builder.build_ir(s, spec.resolve(s, panel), cores="ja")
    els = []
    for core in CORES:
        ctl = f"bk_{core}"
        # Into the core node: a Vccs's current enters its negative node.
        els.append(irm.Vccs(f"GBK_{core}", "0", core, ctl, "0", GM_S))
        els.append(irm.Resistor(f"RBK_{core}", ctl, "0", 1e6))
    return dataclasses.replace(
        ir,
        sections=(*ir.sections, irm.Section("barkhausen", tuple(els))),
        controls=(*ir.controls, *(irm.Control(f"bk_{c}", f"bk_{c}") for c in CORES)),
    )


def settings() -> io.TransientSettings:
    return dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        partition=PARTITION,
    )


def replay(args):
    core, b, fs = args
    return iron.replay(core, b, fs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=list(SCENARIOS))
    ap.add_argument("--stress", nargs="*", type=float, default=[1.0, 10.0, 100.0, 1000.0])
    ap.add_argument("--model", choices=["landscape", "abbm"], default="landscape")
    ap.add_argument(
        "--inject",
        choices=list(TARGETS),
        default="filter",
        help="which iron crackles: the filter's (its crackle alone is pass 2 - pass 1), the "
        "oscillator's (a free-running oscillator's phase walks away under any nudge, so its "
        "effect is the pitch jitter, no difference file) or all",
    )
    args = ap.parse_args()
    global OUT
    OUT = OUT_ROOT / f"{args.model}_{args.inject}"
    targets = TARGETS[args.inject]
    import pyloudnorm
    import soundfile as sf

    sim = io.load_sim_settings()
    fs, seed = sim.sample_rate, sim.seed
    st = settings()
    t0 = time.perf_counter()
    jobs = {}
    for name in args.only:
        panel, notes, legato, dur, _ = SCENARIOS[name]
        n = int(dur * fs)
        t = np.arange(n) / fs
        gate, pitch = keys(t, notes, legato)
        base = {"gate": gate, "pitch": pitch, "key": np.zeros(n), "pressure": np.zeros(n),
                "pitch2": np.zeros(n)}  # fmt: skip
        jobs[name] = (build(panel), base, n)

    def run(name, inject):
        ir, base, n = jobs[name]
        ctl = dict(base)
        for c in CORES:
            ctl[f"bk_{c}"] = inject.get(c, np.zeros(n)) / GM_S
        return fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl).vectors

    with ThreadPoolExecutor(2) as pool:  # each run takes ~7 threads (the partition)
        first = dict(zip(args.only, pool.map(lambda k: run(k, {}), args.only), strict=True))
    print(f"pass 1: {time.perf_counter() - t0:.0f} s", flush=True)

    tasks = [(name, core) for name in args.only for core in CORES]

    def core_of(name: str, c: str):
        return jobs[name][0].model(f"CORE_{c.split('_')[0].upper()}")

    work = [(core_of(nm, c), iron.core_b(first[nm], c), fs) for nm, c in tasks]
    with ProcessPoolExecutor() as pool:
        replays = list(pool.map(replay, work))
    drive = dict(zip(tasks, replays, strict=True))
    print(f"replays: {time.perf_counter() - t0:.0f} s", flush=True)

    def injections(name, stress):
        out = {}
        for c in targets:
            r = drive[(name, c)]
            core = core_of(name, c)
            dm = iron.avalanches(r, fs, stress, rng_for(seed, f"barkhausen:{c}"), args.model)
            out[c] = iron.injection_current(core, dm, r.dh_db)
        return out

    keys2 = [(nm, s) for nm in args.only for s in args.stress]
    with ThreadPoolExecutor(2) as pool:
        second = dict(zip(keys2, pool.map(lambda k: run(k[0], injections(*k)), keys2), strict=True))
    print(f"pass 2: {time.perf_counter() - t0:.0f} s", flush=True)

    meter = pyloudnorm.Meter(fs)

    def write(path: Path, y: np.ndarray) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        peak = float(np.max(np.abs(y)))
        if peak > 0.99:
            y = y * (0.99 / peak)
        sf.write(path, y.astype(np.float32), fs, subtype="FLOAT")

    summary = {"seed": seed, "model": args.model, "s_max_realistic_ms": iron.S_MAX_REALISTIC,
               "source": iron.SOURCE, "scenarios": {}}  # fmt: skip
    for name in args.only:
        prog = first[name]["v(out)"]
        rms = float(np.sqrt(np.mean(prog**2)))
        entry = {"what": SCENARIOS[name][4], "cores": {}, "stress": {}}
        for c in CORES:
            theta = drive[(name, c)].theta
            b = iron.core_b(first[name], c)
            entry["cores"][c] = {
                "b_mean_t": float(np.mean(b)),
                "b_range_t": [float(b.min()), float(b.max())],
                "theta_mean_ms_per_s": float(np.mean(theta)),
                "theta_p99_ms_per_s": float(np.quantile(theta, 0.99)),
                "m_irr_range_ms": float(np.ptp(drive[(name, c)].m_irr)),
            }
        y0 = prog / FULL_SCALE_V
        write(OUT / "audio" / name / "stress_0.wav",
              y0 * 10 ** ((LUFS_TARGET - meter.integrated_loudness(y0)) / 20))  # fmt: skip
        entry["pitch_jitter_cents"] = {"0": jitter(first[name], fs)}
        for st_ in args.stress:
            entry["pitch_jitter_cents"][f"{st_:g}"] = jitter(second[(name, st_)], fs)
        diffs = {s: second[(name, s)]["v(out)"] - prog for s in args.stress}
        top = max(float(np.max(np.abs(d))) for d in diffs.values())
        gain = 10 ** (-1 / 20) / max(top, 1e-30)
        for s in args.stress:
            y = second[(name, s)]["v(out)"] / FULL_SCALE_V
            lufs = meter.integrated_loudness(y)
            write(OUT / "audio" / name / f"stress_{s:g}.wav", y * 10 ** ((LUFS_TARGET - lufs) / 20))
            if args.inject == "filter":
                write(OUT / "audio" / "crackle_only" / f"{name}_stress_{s:g}.wav", diffs[s] * gain)
            d_rms = float(np.sqrt(np.mean(diffs[s] ** 2)))
            entry["stress"][f"{s:g}"] = {
                "crackle_re_program_db": 20 * math.log10(max(d_rms, 1e-30) / rms),
                "crackle_peak_re_program_rms_db": 20
                * math.log10(max(float(np.max(np.abs(diffs[s]))), 1e-30) / rms),
            }
        entry["crackle_only_gain_db"] = 20 * math.log10(gain)
        summary["scenarios"][name] = entry
        plot(OUT / f"{name}.png", name, drive, first[name], diffs[max(args.stress)], fs)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    for name, e in summary["scenarios"].items():
        cores = ", ".join(
            f"{c} B {v['b_mean_t']:+.2f} T theta {v['theta_mean_ms_per_s']:.3f}"
            for c, v in e["cores"].items()
        )
        print(f"{name}: {cores}")
        for s, v in e["stress"].items():
            print(
                f"   STRESS {s:>5s}: crackle {v['crackle_re_program_db']:+6.1f} dB re the note "
                f"(peaks {v['crackle_peak_re_program_rms_db']:+6.1f}), pitch jitter "
                f"{e['pitch_jitter_cents'][s]:.2f} c (none {e['pitch_jitter_cents']['0']:.2f})"
            )
    print(f"total {time.perf_counter() - t0:.0f} s")


def jitter(vectors: dict, fs: int) -> float:
    """The oscillator's cycle-to-cycle pitch jitter (cents): the median absolute change of
    successive cycles' frequency, robust to the glides' steps."""
    from varimu.synth import vco

    t, f = vco.cycle_frequencies(vectors["v(o_buf)"], fs, lowpass_hz=3000.0)
    c = vco.cents(f[f > 0], 110.0)
    return float(np.median(np.abs(np.diff(c)))) if c.size > 2 else float("nan")


def plot(path: Path, name: str, drive, vectors, diff, fs) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy import signal

    fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    t = np.arange(diff.size) / fs
    for c in CORES:
        theta = drive[(name, c)].theta
        k = max(1, int(0.005 * fs))
        ax[0].plot(t[::k], np.convolve(theta, np.ones(k) / k, "same")[::k], lw=0.8, label=c)
    ax[0].set_ylabel("|dM_irr/dt| (Ms/s)")
    ax[0].set_yscale("log")
    ax[0].legend(fontsize=7)
    ax[0].set_title(f"{name}: {SCENARIOS[name][4]}", fontsize=9)
    ax[1].plot(t, vectors["v(out)"], lw=0.5)
    ax[1].set_ylabel("out (V)")
    f, tt, s = signal.spectrogram(diff, fs, nperseg=4096, noverlap=3072)
    db = 10 * np.log10(s + 1e-30)
    top = np.quantile(db, 0.999)
    ax[2].pcolormesh(tt, f, db, vmin=top - 70, vmax=top, shading="auto")
    ax[2].set_yscale("symlog", linthresh=200)
    ax[2].set_ylim(20, 20000)
    ax[2].set_ylabel("crackle alone, top STRESS (Hz)")
    ax[2].set_xlabel("s")
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


if __name__ == "__main__":
    main()

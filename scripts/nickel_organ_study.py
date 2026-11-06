"""The Nickel Organ's first experiment (docs/INVENTED_DEVICES.md I1; docs/NICKEL_ORGAN_PLAN.md):
one key's loop with POLARIZE swept from zero to saturation, what remanence does at zero
bias, and how hard strikes move the strip's memory. -> reports/nickel_organ/first_experiment/:
summary.json, study.png, audio/*.wav (each part at one scale, so levels compare).

    uv run python scripts/nickel_organ_study.py [--note 69] [--sustain 0.75]
        [--only sweep remanence memory]

Each setting powers a fresh key on (its strip demagnetized, POLARIZE ramped up from zero)
unless the part says otherwise. The levels are the line out's components at the
fundamental, at half of it (the parametric loop's sub-octave) and at twice it, over the
held note's last half second.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from varimu.nickel import organ  # noqa: E402
from varimu.nickel import spec as nspec  # noqa: E402
from varimu.nickel import voice as nvoice  # noqa: E402

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "nickel_organ" / "first_experiment"
FS = organ.FS
POLARIZE = (0.0, 0.02, 0.05, 0.1, 0.18, 0.25, 0.35, 0.5, 0.75, 1.0)
HOLD_S = 1.6
VELOCITY = 100


def component_db(y: np.ndarray, f: float) -> float:
    """The level (dB re 1 V rms) of y's component at f (a Hann window's peak bin near f)."""
    w = np.hanning(len(y))
    sp = np.abs(np.fft.rfft(y * w)) * 2 / w.sum() / np.sqrt(2)
    fr = np.fft.rfftfreq(len(y), 1 / FS)
    k = (fr > 0.97 * f) & (fr < 1.03 * f)
    return float(20 * np.log10(sp[k].max() + 1e-12))


def held(vc: nvoice.Voice, sustain: float, polarize: float, velocity: int = VELOCITY):
    """Strike, hold HOLD_S, release, 0.3 s of tail: (audio, tip peak um, lamp peak K)."""
    vc.strike(velocity)
    y = vc.run(int(HOLD_S * FS), sustain=sustain, polarize=polarize)
    tip = float(np.abs(vc.probe["tip_m"] - vc.probe["tip_m"].mean()).max() * 1e6)
    lamp = float(vc.probe["lamp_k"].max())
    vc.release()
    tail = vc.run(int(0.3 * FS), sustain=sustain, polarize=polarize)
    return np.concatenate([y, tail]), tip, lamp


def levels(y: np.ndarray, f1: float) -> dict[str, float]:
    seg = y[int((HOLD_S - 0.5) * FS) : int(HOLD_S * FS)]
    return {
        "f1_db": component_db(seg, f1),
        "sub_db": component_db(seg, f1 / 2),
        "f2_db": component_db(seg, 2 * f1),
        "rms_v": float(np.sqrt(np.mean(seg**2))),
        "strike_rms_v": float(np.sqrt(np.mean(y[: int(0.1 * FS)] ** 2))),
    }


def fresh(note: int, polarize: float, trim: float) -> nvoice.Voice:
    vc = nvoice.make_voice(note, noise=True)
    vc.trim = trim
    organ._power_on(vc, polarize)
    return vc


def sweep(note: int, sustain: float, trim: float, audio: dict) -> list[dict]:
    rows = []
    for pol in POLARIZE:
        t = time.perf_counter()
        vc = fresh(note, pol, trim)
        m0 = vc.m1
        y, tip, lamp = held(vc, sustain, pol)
        row = {"polarize": pol, "m_bias_over_ms": m0 / vc.p.ni.ms, "tip_um": tip, "lamp_k": lamp,
               **levels(y, float(vc.bar.freq_hz[0]))}  # fmt: skip
        rows.append(row)
        audio[f"sweep_polarize_{pol:.2f}"] = y
        print(f"  POLARIZE {pol:.2f}: M/Ms {row['m_bias_over_ms']:.3f}, held {row['rms_v']:.3g} V "
              f"(f1 {row['f1_db']:.1f}, f/2 {row['sub_db']:.1f}, 2f {row['f2_db']:.1f} dB), "
              f"tip {tip:.1f} um, lamp {lamp:.0f} K  [{time.perf_counter() - t:.0f} s]",
              flush=True)  # fmt: skip
    return rows


def remanence(note: int, sustain: float, trim: float, audio: dict) -> dict:
    """Zero bias, a fresh (demagnetized) strip against one that was played at the default
    bias and then had POLARIZE turned to zero: the remanent magnetization is the bias."""
    d = nspec.load()
    pol0 = nspec.v(d, "panel.polarize")
    f1 = None
    out = {}
    vc = fresh(note, 0.0, trim)
    y, tip, lamp = held(vc, sustain, 0.0)
    f1 = float(vc.bar.freq_hz[0])
    m = vc.m1 / vc.p.ni.ms
    out["virgin"] = {"m_over_ms": m, "tip_um": tip, "lamp_k": lamp, **levels(y, f1)}
    audio["remanence_virgin_zero_bias"] = y
    vc = fresh(note, pol0, trim)
    held(vc, sustain, pol0)  # played at the default bias
    vc.run(int(0.05 * FS), sustain=sustain, polarize=0.0, ramp_s=0.05)  # POLARIZE to zero
    vc.run(int(0.05 * FS), sustain=sustain, polarize=0.0)
    m_rem = vc.m1
    y, tip, lamp = held(vc, sustain, 0.0)
    m = m_rem / vc.p.ni.ms
    out["remanent"] = {"m_over_ms": m, "tip_um": tip, "lamp_k": lamp, **levels(y, f1)}
    audio["remanence_after_play_zero_bias"] = y
    # SUSTAIN fully up at zero bias, struck hard: does the parametric loop start?
    y, tip, lamp = held(vc, 1.0, 0.0, velocity=127)
    out["remanent_full_sustain"] = {"tip_um": tip, "lamp_k": lamp, **levels(y, f1)}
    audio["remanence_full_sustain_zero_bias"] = y
    vc = fresh(note, 0.0, trim)
    y, tip, lamp = held(vc, 1.0, 0.0, velocity=127)
    out["virgin_full_sustain"] = {"tip_um": tip, "lamp_k": lamp, **levels(y, f1)}
    audio["virgin_full_sustain_zero_bias"] = y
    for k, v in out.items():
        print(f"  {k}: " + ", ".join(f"{a} {b:.3g}" for a, b in v.items()), flush=True)
    return out


def memory(note: int, trim: float) -> dict:
    """The strip's magnetization before and after strikes at the default bias, loop open."""
    d = nspec.load()
    pol0 = nspec.v(d, "panel.polarize")
    out = {}
    for vel in (20, 64, 127):
        vc = fresh(note, pol0, trim)
        ms = [vc.m1 / vc.p.ni.ms]
        for _ in range(3):
            vc.strike(vel)
            vc.run(int(0.4 * FS), sustain=0.0, polarize=pol0)
            vc.release()
            vc.run(int(0.3 * FS), sustain=0.0, polarize=pol0)
            ms.append(vc.m1 / vc.p.ni.ms)
        out[str(vel)] = {"m_over_ms": ms, "peak_stress_mpa": vc.peak_stress_pa / 1e6}
        print(f"  velocity {vel}: M/Ms after 0-3 strikes {[round(m, 4) for m in ms]}, "
              f"peak stress {vc.peak_stress_pa / 1e6:.1f} MPa", flush=True)  # fmt: skip
    return out


def plot(rows: list[dict], note: int, path: Path) -> None:
    pol = [r["polarize"] for r in rows]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    for k, lab in (("f1_db", "fundamental"), ("sub_db", "f / 2"), ("f2_db", "2 f")):
        ax[0].plot(pol, [r[k] for r in rows], "o-", label=lab)
    ax[0].set_xlabel("POLARIZE")
    ax[0].set_ylabel("held note, dB re 1 V rms")
    ax[0].set_title(f"key {note}: the held note's components")
    ax[0].legend()
    ax[0].grid(alpha=0.3)
    ax[1].plot(pol, [r["m_bias_over_ms"] for r in rows], "o-", label="M / Ms at bias")
    ax[1].plot(pol, [r["lamp_k"] / 3000 for r in rows], "s-", label="lamp peak / 3000 K")
    ax[1].set_xlabel("POLARIZE")
    ax[1].legend()
    ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def write_audio(audio: dict, prefix: str) -> None:
    group = {k: v for k, v in audio.items() if k.startswith(prefix)}
    if not group:
        return
    peak = max(float(np.abs(v).max()) for v in group.values())
    for k, v in group.items():
        sf.write(OUT / "audio" / f"{k}.wav", (0.89 * v / peak).astype(np.float32), FS,
                 subtype="FLOAT")  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--note", type=int, default=69)
    ap.add_argument("--sustain", type=float, default=0.75)
    ap.add_argument("--only", nargs="*", default=["sweep", "remanence", "memory"])
    args = ap.parse_args()
    (OUT / "audio").mkdir(parents=True, exist_ok=True)
    trim = organ.voicing([args.note], progress=True)[args.note]["trim"]
    summary_path = OUT / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    summary.update({"note": args.note, "sustain": args.sustain, "trim": trim, "velocity": VELOCITY})
    audio: dict[str, np.ndarray] = {}
    t0 = time.perf_counter()
    if "sweep" in args.only:
        print("POLARIZE sweep", flush=True)
        rows = sweep(args.note, args.sustain, trim, audio)
        summary["sweep"] = rows
        plot(rows, args.note, OUT / "study.png")
        write_audio(audio, "sweep_")
    if "remanence" in args.only:
        print("Remanence at zero bias", flush=True)
        summary["remanence"] = remanence(args.note, args.sustain, trim, audio)
        write_audio(audio, "remanence_")
        write_audio(audio, "virgin_")
    if "memory" in args.only:
        print("The strip's memory of strikes", flush=True)
        summary["memory"] = memory(args.note, trim)
    summary["seconds"] = time.perf_counter() - t0
    summary_path.write_text(json.dumps(summary, indent=1))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()

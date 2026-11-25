"""PB0, the parts bench (docs/PART_NOISE_PLAN.md): each part's noise alone, boosted to hear it.

    uv run --extra listen python scripts/part_noise_bench.py [--only NAME ...] [--seed N]

-> reports/part_noise/bench/:
- audio/same_gain/<group>/<name>.wav: each group through one fixed gain (summary.json), as in
  the video: real relative levels within a group (hiss: Johnson noise near the quietest);
- audio/matched/<name>.wav: every part at -23 LUFS (character, not level);
- spectra.png: the hiss group's densities at the part (V/sqrt(Hz)) with the theory's lines;
- spectrograms/<name>.png; summary.json (levels, gains, every value with its source).
Every file is band-limited to 20 Hz - 20 kHz (an audio band, as a listener hears it).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy import signal

from varimu.config import load_sim_settings
from varimu.devices import noise
from varimu.part_noise import bench, resistor

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "part_noise" / "bench"
LUFS_TARGET = -23.0
SAME_GAIN_PEAK_DBFS = -1.0


def band(x: np.ndarray, rate_hz: float) -> np.ndarray:
    sos = np.vstack(
        [
            signal.butter(2, 20.0, "highpass", fs=rate_hz, output="sos"),
            signal.butter(4, 20000.0, "lowpass", fs=rate_hz, output="sos"),
        ]
    )
    y = signal.sosfiltfilt(sos, x)
    fade = int(0.02 * rate_hz)
    y[:fade] *= np.linspace(0.0, 1.0, fade)
    y[-fade:] *= np.linspace(1.0, 0.0, fade)
    return y


def write(path: Path, x: np.ndarray, rate_hz: float) -> float:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    peak = float(np.max(np.abs(x)))
    lowered = 0.0
    if peak > 0.99:  # never clip a file: lower it and say so
        lowered = 20 * math.log10(0.99 / peak)
        x = x * (0.99 / peak)
    sf.write(path, x.astype(np.float32), int(rate_hz), subtype="FLOAT")
    return lowered


def spectrogram(path: Path, x: np.ndarray, rate_hz: float, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    f, t, s = signal.spectrogram(x, rate_hz, nperseg=4096, noverlap=3072)
    fig, ax = plt.subplots(figsize=(10, 4))
    db = 10 * np.log10(s + 1e-30)
    top = np.quantile(db, 0.999)
    ax.pcolormesh(t, f, db, vmin=top - 70, vmax=top, shading="auto")
    ax.set_yscale("symlog", linthresh=200)
    ax.set_ylim(20, 20000)
    ax.set_xlabel("s")
    ax.set_ylabel("Hz")
    ax.set_title(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def spectra(path: Path, raw: dict, rate_hz: float) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    for name, x in raw.items():
        if bench.BY_NAME[name].group != "hiss":
            continue
        f, p = signal.welch(x, rate_hz, nperseg=2**16)
        keep = (f >= 5) & (f <= 40000)
        ax.loglog(f[keep], np.sqrt(p[keep]), lw=1, label=name)
    f = np.logspace(np.log10(5), np.log10(40000), 200)
    johnson = 4 * noise.K_B * bench.BENCH_T_K * bench.R_OHM
    for label, ni in (("carbon comp", 0.0), ("aged", 10.0), ("metal film", -25.0)):
        theory = resistor.excess_k(ni) * bench.DC_V**2 / f + johnson
        ax.loglog(f, np.sqrt(theory), "k:", lw=0.8)
        ax.annotate(f"theory: {label}", (6, math.sqrt(theory[0])), fontsize=7)
    ax.axhline(math.sqrt(johnson), color="k", ls=":", lw=0.8)
    ax.set_xlabel("Hz")
    ax.set_ylabel("V / sqrt(Hz) at the part")
    ax.set_title(
        "PB0: the hiss group's noise densities (dotted: theory, Johnson + excess at 100 V)"
    )
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def jsonable(v):
    if isinstance(v, (tuple, list)):
        return [jsonable(x) for x in v]
    if hasattr(v, "__dataclass_fields__"):
        return {k: jsonable(getattr(v, k)) for k in v.__dataclass_fields__}
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    return v


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", help="part names (default: all)")
    ap.add_argument("--seed", type=int, default=None, help="default: sim_settings' seed")
    args = ap.parse_args()
    import pyloudnorm

    settings = load_sim_settings()
    rate = float(settings.sample_rate)
    seed = settings.seed if args.seed is None else args.seed
    names = args.only or [p.name for p in bench.PARTS]
    raw = {}
    for name in names:
        print(f"rendering {name} ...", flush=True)
        raw[name] = bench.render(name, seed, rate)
    banded = {k: band(v, rate) for k, v in raw.items()}

    hiss = [k for k in banded if bench.BY_NAME[k].group == "hiss"]
    gains = {}  # one fixed gain per group: its parts' real relative levels
    for group in sorted({bench.BY_NAME[k].group for k in banded}):
        members = [k for k in banded if bench.BY_NAME[k].group == group]
        loudest = max(float(np.max(np.abs(banded[k]))) for k in members)
        gains[group] = SAME_GAIN_PEAK_DBFS - 20 * math.log10(loudest)
    meter = pyloudnorm.Meter(int(rate))
    summary = {
        "seed": seed,
        "rate_hz": rate,
        "seconds": bench.SECONDS,
        "same_gain_db": gains,
        "lufs_matched": LUFS_TARGET,
        "parts": {},
    }
    ref = None
    if "johnson_100k" in banded:
        ref = float(np.sqrt(np.mean(banded["johnson_100k"] ** 2)))
    for name, y in banded.items():
        part = bench.BY_NAME[name]
        rms = float(np.sqrt(np.mean(y**2)))
        entry = {
            "title": part.title,
            "group": part.group,
            "values": {k: {"value": jsonable(v), "source": s} for k, (v, s) in part.values.items()},
        }
        if part.group == "hiss":
            entry["rms_uv_20hz_20khz"] = rms * 1e6
            entry["peak_uv"] = float(np.max(np.abs(y))) * 1e6
            if ref:
                entry["re_johnson_100k_db"] = 20 * math.log10(rms / ref)
        g = gains[part.group]
        lowered = write(
            OUT / "audio" / "same_gain" / part.group / f"{name}.wav", y * 10 ** (g / 20), rate
        )
        entry["same_gain_dbfs_rms"] = 20 * math.log10(max(rms, 1e-30)) + g + lowered
        # Bring it near -20 dBFS rms first: microvolts are below BS.1770's -70 LUFS gate.
        pre = y * (0.1 / max(rms, 1e-30))
        lufs = meter.integrated_loudness(pre)
        entry["lowered_matched_db"] = write(
            OUT / "audio" / "matched" / f"{name}.wav", pre * 10 ** ((LUFS_TARGET - lufs) / 20), rate
        )
        spectrogram(OUT / "spectrograms" / f"{name}.png", y, rate, f"{name}: {part.title}")
        summary["parts"][name] = entry
    if hiss:
        spectra(OUT / "spectra.png", raw, rate)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "summary.json"
    if args.only and path.exists():  # keep the other parts' entries
        old = json.loads(path.read_text())
        old["parts"].update(summary["parts"])
        summary["parts"] = old["parts"]
    path.write_text(json.dumps(summary, indent=2))
    for name, e in summary["parts"].items():
        level = e.get("rms_uv_20hz_20khz")
        if level is None:
            at = e["same_gain_dbfs_rms"]
            print(f"{name:30s} {e['group']:10s} {at:+7.1f} dBFS rms at its group's gain")
        else:
            print(
                f"{name:30s} {level:10.2f} uV rms {e.get('re_johnson_100k_db', 0):+7.1f} dB "
                "re Johnson 100k"
            )
    print("same gains:", {k: round(v, 1) for k, v in gains.items()})


if __name__ == "__main__":
    main()

"""The plate reverb's report (docs/REVERB_PLAN.md, E6 / E7) -> reports/reverb/.

    uv run --extra fast python scripts/plate_report.py [--quality draft-1x] [--decays 1 2 2.5 4.5]

For each DECAY setting: the whole device's impulse response (config/circuits/
plate_reverb.yaml: an impulse into the drive amplifier, the plate, the pickup amplifier),
each octave band's decay by Schroeder's backward integration (T20 x 3; the same run without
the impulse subtracted: the supply's hum is deterministic), against the decay
the EMT 140's measured curves give at that setting (varimu.devices.plate.decay_table).
Also: the brochure's three curves against the loss mechanisms' formulas (the cross-check
of varimu.devices.plate.physics_decay), and the response's spectrogram at 2.5 s.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.signal import butter, sosfilt  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.devices import plate as pl  # noqa: E402
from varimu.devices.library import load_plate  # noqa: E402
from varimu.sim import fast  # noqa: E402
from varimu.sim.io import TransientSettings  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "reverb"
BANDS_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]


def band_t60(y: np.ndarray, fs: float, fc: float) -> float:
    """T60 of the octave band at fc: Schroeder's integral, its -5 to -25 dB, times 3."""
    sos = butter(4, [fc / np.sqrt(2), fc * np.sqrt(2)], btype="band", fs=fs, output="sos")
    e = sosfilt(sos, y) ** 2
    sch = np.cumsum(e[::-1])[::-1]
    db = 10 * np.log10(sch / sch[0] + 1e-30)
    t = np.arange(len(db)) / fs
    sel = (db <= -5) & (db >= -25)
    if sel.sum() < 10:
        return float("nan")
    slope = np.polyfit(t[sel], db[sel], 1)[0]
    return float(-60.0 / slope)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quality", default="draft-1x")
    ap.add_argument("--decays", type=float, nargs="+", default=[1.0, 2.0, 2.5, 4.5])
    ap.add_argument("--seconds", type=float, default=7.0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    comp = load_plate("EMT140@1")
    sp = spec.load_circuit(REPO / "config/circuits/plate_reverb.yaml")
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=args.quality)
    st = dataclasses.replace(st, settle_s=1.0)
    fs = float(st.sample_rate)
    n = int(args.seconds * fs)
    x = np.zeros(n)
    x[int(0.01 * fs)] = 2.0  # volts into the drive amplifier, one sample
    summary: dict = {"quality": args.quality, "settings": {}}
    fig, ax = plt.subplots(figsize=(9, 5.5))
    colours = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    ir_25 = None
    for k, d in enumerate(args.decays):
        c = builder.build(sp, {"decay_500hz_s": d}, cores="linear")
        t0 = time.perf_counter()
        r = fast.run_transient(c.ir, x, settings=st)
        wall = time.perf_counter() - t0
        # The same run without the impulse: the supply's hum and ripple, deterministic,
        # subtracted so the bands measure the plate's response only.
        quiet = np.asarray(
            fast.run_transient(c.ir, np.zeros_like(x), settings=st).vectors["v(out)"]
        )
        full = np.asarray(r.vectors["v(out)"])
        y = full - quiet
        start = int(0.01 * fs)
        y = y[start:]
        # The hum: the mains ripple's harmonics (120 Hz at 60 Hz mains) over the run's last
        # 2 s (the supply's slow settling isn't hum).
        tail = quiet[-int(2 * fs) :]
        spec_ = np.fft.rfft(tail - tail.mean()) / len(tail) * 2
        fr = np.fft.rfftfreq(len(tail), 1 / fs)
        hum = np.sqrt(
            sum(np.abs(spec_[np.argmin(np.abs(fr - 120 * h))]) ** 2 / 2 for h in range(1, 9))
        )
        t60 = [band_t60(y, fs, f) for f in BANDS_HZ]
        table = pl.decay_table(comp, d)
        want = [
            pl.SIX_LN10 / float(pl.energy_decay(table, np.array([f], float))[0]) for f in BANDS_HZ
        ]
        summary["settings"][f"{d:g}"] = {
            "bands_hz": BANDS_HZ,
            "t60_measured_s": [round(v, 3) for v in t60],
            "t60_curves_s": [round(v, 3) for v in want],
            "peak_v": float(np.abs(y).max()),
            "hum_120hz_rms_v": float(hum),
            "render_wall_s": round(wall, 1),
        }
        col = colours[k % len(colours)]
        ax.semilogx(BANDS_HZ, t60, "o-", color=col, label=f"DECAY {d:g} s: measured (octave bands)")
        ax.semilogx(
            BANDS_HZ, want, "--", color=col, alpha=0.7, label=f"DECAY {d:g} s: the EMT curves"
        )
        rows = zip(BANDS_HZ, t60, want, strict=True)
        print(f"DECAY {d:g} s: " + ", ".join(f"{f} Hz {m:.2f} ({w:.2f})" for f, m, w in rows))
        if abs(d - 2.5) < 1e-9:
            ir_25 = y
    ax.set_xlabel("Hz")
    ax.set_ylabel("T60 (s)")
    ax.set_title("Plate reverb: decay per octave band, measured from the device's impulse response")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "plate_decay.png", dpi=120)
    plt.close(fig)

    # The brochure's curves against the loss formulas.
    f = np.geomspace(50, 14000, 200)
    phys = pl.physics_decay(comp, f)
    fig, ax = plt.subplots(figsize=(9, 5))
    for curve in comp.decay_curves_s:
        t500 = curve[comp.decay_f_hz.index(500.0)]
        ax.semilogx(comp.decay_f_hz, curve, "o-", ms=3, label=f"EMT 140: {t500:.1f} s at 500 Hz")
    for name, s in phys.items():
        ax.semilogx(f, pl.SIX_LN10 / s, label=f"formula: {name}")
    ax.set_ylim(0, 14)
    ax.set_xlabel("Hz")
    ax.set_ylabel("T60 (s)")
    ax.set_title("The measured decay (brochure, 1971) and the loss mechanisms' formulas")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "plate_losses.png", dpi=120)
    plt.close(fig)

    def brochure_at(hz: float) -> float:
        return float(np.interp(np.log(hz), np.log(comp.decay_f_hz), comp.decay_curves_s[0]))

    def formulas_at(hz: float) -> float:
        return float(pl.SIX_LN10 / pl.physics_decay(comp, np.array([hz]))["total"][0])

    summary["physics_vs_brochure_undamped"] = {
        str(hz): {"brochure_s": round(brochure_at(hz), 2), "formulas_s": round(formulas_at(hz), 2)}
        for hz in (100.0, 500.0, 1000.0, 4000.0, 10000.0)
    }

    if ir_25 is not None:
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.specgram(ir_25, NFFT=2048, Fs=fs, noverlap=1536, cmap="magma", vmin=-160)
        ax.set_ylim(0, 16000)
        ax.set_xlabel("s")
        ax.set_ylabel("Hz")
        ax.set_title("Plate reverb at DECAY 2.5 s: the impulse response's spectrogram")
        fig.tight_layout()
        fig.savefig(OUT / "plate_spectrogram.png", dpi=120)
        plt.close(fig)
    (OUT / "plate_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()

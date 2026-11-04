"""The Side Man's bass drum, D2a (docs/DRUM_PLAN.md): config/circuits/sideman_bd.yaml's idle
point against schematic 501648's typical voltages, a hit over the RING trim (R106: pitch,
ring time, level), repeated hits (J's recovery between strikes) and audio to listen to, in
reports/drums/sideman_bd/: summary.json, study.png and audio/ (WAVs at the circuit's full
scale, so a weak hit is weak).

    uv run --extra fast python scripts/sideman_study.py [--quality production|draft]
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
import soundfile as sf  # noqa: E402
from scipy.signal import hilbert  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.circuit.ir import VoltageProbe  # noqa: E402
from varimu.config import CONFIG_DIR  # noqa: E402
from varimu.sim import fast, io  # noqa: E402
from varimu.synth import vco  # noqa: E402

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "drums" / "sideman_bd"
CIRCUIT = CONFIG_DIR / "circuits" / "sideman_bd.yaml"
FS = 96000
RINGS = (0.3, 0.4, 0.5, 0.62, 0.8, 1.0)
# dwg 501648's typical voltages (11 MOhm meter, no signal)
DRAWING_V = {"p": 174.0, "k": 1.5, "pp": 205.0, "pk": 2.2}
KEY_S = 0.02  # how long the commutator grounds the key line (provisional: not printed)
LEAD_S = 0.2  # idle before the first hit
PROBES = ("out", "p", "g", "k", "j", "pp", "pk")


def gate_levels(s: spec.CircuitSpec) -> tuple[float, float]:
    v = s.values
    return float(v["gate_off_v"]["value"]), float(v["gate_on_v"]["value"])


def render(s, sets, hits_s, dur_s, quality):
    ir = builder.build_ir(s, spec.resolve(s, sets))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in PROBES))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    n = int(dur_s * FS)
    t = np.arange(n) / FS
    up, down = gate_levels(s)
    gate = np.full(n, up)
    for h in hits_s:
        gate[(t >= h) & (t < h + KEY_S)] = down
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls={"gate": gate}).vectors
    return {p: np.asarray(v[f"v({p})"]) for p in PROBES}


def envelope_db(y: np.ndarray) -> np.ndarray:
    e = np.abs(hilbert(y))
    w = int(0.01 * FS)
    e = np.convolve(e, np.ones(w) / w, mode="same")
    return 20 * np.log10(np.maximum(e, 1e-12) / e.max())


def hit_metrics(v: dict, i0: int) -> dict:
    idle = {p: float(np.mean(v[p][i0 - 2000 : i0])) for p in v}
    out = v["out"][i0:] - idle["out"]
    plate = v["p"][i0:] - idle["p"]
    m = {
        "idle_v": {p: round(idle[p], 2) for p in ("out", "p", "g", "k", "j", "pp", "pk")},
        "out_peak_v": round(float(np.abs(out).max()), 3),
        "plate_swing_v": round(float(np.abs(plate).max()), 2),
    }
    tc, f = vco.cycle_frequencies(plate, FS)
    m["pitch_hz"] = {
        f"{int(at * 1000)}ms": round(float(f[j]), 1)
        for at in (0.005, 0.02, 0.05, 0.1, 0.2, 0.4)
        if (j := int(np.searchsorted(tc, at))) < len(f)
        and np.abs(plate[int(at * FS) :]).max() > 1e-3 * m["plate_swing_v"]
    }
    e = envelope_db(out)
    pk = int(np.argmax(e))
    for lvl in (-20, -40, -60):
        after = np.flatnonzero(e[pk:] < lvl)
        m[f"t_{-lvl}db_ms"] = round((pk + after[0]) / FS * 1000, 1) if len(after) else None
    return m, tc, f


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quality", default="production")
    args = ap.parse_args()
    s = spec.load_circuit(CIRCUIT)
    fs_out = float(s.full_scale[1])
    (OUT / "audio").mkdir(parents=True, exist_ok=True)
    summary: dict = {"quality": args.quality, "key_s": KEY_S, "drawing_v": DRAWING_V}
    fig, axes = plt.subplots(3, 1, figsize=(11, 11))

    # one hit per RING setting
    rings = {}
    t0 = time.perf_counter()
    for ring in RINGS:
        dur = 2.5
        v = render(s, {"ring": ring}, [LEAD_S], dur, args.quality)
        i0 = int(LEAD_S * FS)
        m, tc, f = hit_metrics(v, i0)
        rings[str(ring)] = m
        print(f"RING {ring}: {m}")
        y = v["out"][i0:] - m["idle_v"].get("out", 0.0)
        sf.write(OUT / "audio" / f"hit_ring{ring}.wav", (y / fs_out).astype(np.float32), FS)
        t = np.arange(len(y)) / FS
        axes[0].plot(t[: int(0.6 * FS)], y[: int(0.6 * FS)], lw=0.6, label=f"RING {ring}")
        keep = tc < 0.8
        axes[1].plot(tc[keep] * 1000, f[keep], label=f"RING {ring}")
    elapsed = time.perf_counter() - t0
    summary["rings"] = rings
    summary["speed_x_real_time"] = round(elapsed / (len(RINGS) * 2.5), 3)
    d = rings["0.62"]["idle_v"]
    summary["idle_vs_drawing"] = {k: {"model": d[k], "drawing": x} for k, x in DRAWING_V.items()}

    # repeated hits: quarters, eighths, sixteenths at 120 BPM (J recovers through R100)
    beat = 0.5
    hits = [LEAD_S + i * beat for i in range(4)]
    hits += [hits[-1] + beat + i * beat / 2 for i in range(8)]
    hits += [hits[-1] + beat / 2 + i * beat / 4 for i in range(16)]
    dur = hits[-1] + 1.5
    v = render(s, {}, hits, dur, args.quality)
    y = v["out"] - np.mean(v["out"][: int(0.1 * FS)])
    peaks = []
    for a, b in zip(hits, hits[1:] + [dur], strict=True):
        seg = y[int(a * FS) : int(min(b, a + 0.06) * FS)]
        peaks.append(float(np.abs(seg).max()))
    summary["repeats_peak_db"] = {
        name: [round(20 * np.log10(p / peaks[0]), 2) for p in ps]
        for name, ps in (
            ("quarters", peaks[:4]),
            ("eighths", peaks[4:12]),
            ("sixteenths", peaks[12:]),
        )
    }
    print("repeats (dB re the first):", summary["repeats_peak_db"])
    sf.write(OUT / "audio" / "repeats_120bpm.wav", (y / fs_out).astype(np.float32), FS)
    t = np.arange(len(y)) / FS
    axes[2].plot(t, y, lw=0.4)
    axes[2].plot(t, v["j"] / 22.0 * np.abs(y).max(), lw=0.8, label="J (scaled; -22 V at rest)")

    # a figure to listen to: a Side Man style bass drum line at 120 BPM, RING at the drawing's
    bar = [0.0, 1.0, 1.5, 2.0, 3.0]
    hits = [LEAD_S + 4 * beat * b + x * beat for b in range(4) for x in bar]
    v = render(s, {}, hits, hits[-1] + 1.5, args.quality)
    y = v["out"] - np.mean(v["out"][: int(0.1 * FS)])
    sf.write(OUT / "audio" / "figure_120bpm.wav", (y / fs_out).astype(np.float32), FS)

    axes[0].set(xlabel="s", ylabel="V at the amplifier's input", title="A hit over RING (R106)")
    axes[1].set(xlabel="ms", ylabel="Hz", title="Pitch per cycle (the plate)", ylim=(40, 120))
    axes[2].set(xlabel="s", ylabel="V", title="Quarters, eighths, sixteenths at 120 BPM")
    for ax in axes:
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "study.png", dpi=110)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()

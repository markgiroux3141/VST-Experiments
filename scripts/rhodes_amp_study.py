# ruff: noqa: E501
"""The Suitcase power amp measured (config/circuits/rhodes_suitcase_100w.yaml): gain, the
clipping power into the speakers, THD against level, the rails' sag, the frequency response.

    uv run --extra fast python scripts/rhodes_amp_study.py [--quality draft|production]

A 1 kHz tone enters at ACCESSORY IN (the preamp's VOLUME and tone flat, the vibrato off, so
`pre_a` is a clean tone), at rising levels; the amp's own figures are read between `pre_a`
and the output node `a_amp` (the power amp board's input is `pre_a` through fig11-3's 680 ohm).
Power into the speakers is the mean of v * i across the fuse's 20 mOhm (the two 8 ohm drivers
in series: 16 ohm nominal, their own impedance at 1 kHz in the report). The live (terminal)
build is used: the electrical circuit is identical, the sound-pressure readout isn't needed.
Writes reports/rhodes/suitcase_amp/amp.json and amp.png.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varimu.circuit import builder  # noqa: E402
from varimu.circuit.spec import load_circuit, resolve  # noqa: E402

CIRCUIT = ROOT / "config" / "circuits" / "rhodes_suitcase_100w.yaml"
OUT = ROOT / "reports" / "rhodes" / "suitcase_amp"
FUSE_OHM = 0.02


def settings(quality: str):
    from varimu.sim import io

    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    return dataclasses.replace(st, newton_reltol=1e-5, newton_vntol=1e-5, settle_s=0.4)


def run(spec, st, x: np.ndarray, **controls) -> dict[str, np.ndarray]:
    from varimu.sim import fast

    q = dict(resolve(spec))
    q.update(accessory_in=1, vibrato=0, volume=1.0, bass=0.5, treble=0.5)
    q.update(controls)
    ir = builder.build_ir(spec, q, speaker_readout=False)
    return {
        k[2:-1]: np.asarray(v) for k, v in fast.run_transient(ir, x, settings=st).vectors.items()
    }


def tone(amp: float, f_hz: float, dur_s: float, fs: float) -> np.ndarray:
    t = np.arange(int(dur_s * fs)) / fs
    return amp * np.sin(2 * np.pi * f_hz * t) * np.clip(t / 0.02, 0, 1)


def harmonics(y: np.ndarray, f_hz: float, fs: float, frac=0.5, nh=10) -> list[float]:
    y = y[int(frac * len(y)) :]
    t = np.arange(len(y)) / fs
    w = np.hanning(len(y))
    return [
        2 * abs(np.sum(w * y * np.exp(-2j * np.pi * k * f_hz * t))) / np.sum(w)
        for k in range(1, nh + 1)
    ]


def point(spec, st, level: float, f_hz: float = 1000.0, dur_s: float = 0.5) -> dict:
    fs = st.sample_rate
    v = run(spec, st, tone(level, f_hz, dur_s, fs))
    k = int(0.25 * fs)
    seg = lambda n: v[n][-k:]  # noqa: E731
    pre, amp, spk = seg("pre_a"), seg("a_amp"), seg("a_spk")
    cur = (amp - spk) / FUSE_OHM
    p_w = float(np.mean(spk * cur))
    h = harmonics(v["a_amp"], f_hz, fs)
    h_pre = harmonics(v["pre_a"], f_hz, fs)
    return {
        "level": level,
        "pre_peak_v": float(np.max(np.abs(pre))),
        "out_peak_v": float(np.max(np.abs(amp))),
        "gain_db": 20 * np.log10(h[0] / h_pre[0]),
        "power_w": p_w,
        "thd_pct": 100 * float(np.sqrt(sum(x * x for x in h[1:])) / h[0]),
        "thd_pre_pct": 100 * float(np.sqrt(sum(x * x for x in h_pre[1:])) / h_pre[0]),
        "z_ohm": float(h[0] / (2 * np.sqrt(2) * np.sqrt(np.mean(cur**2)) / 2**0.5 * 1.0))
        if False
        else float(np.sqrt(np.mean(spk**2)) / np.sqrt(np.mean(cur**2))),
        "vp_v": float(np.mean(v["vp"][-k:])),
        "vn_v": float(np.mean(v["vn"][-k:])),
        "vp_ripple_v": float(np.ptp(v["vp"][-k:])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", default="draft")
    a = ap.parse_args()
    spec = load_circuit(CIRCUIT)
    st = settings(a.quality)
    levels = [0.0003, 0.001, 0.003, 0.01, 0.02, 0.03, 0.045, 0.06, 0.08, 0.12, 0.2]
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(lambda lv: point(spec, st, lv), levels))
    for r in rows:
        print(
            f"in {r['level']:.4f}: pre {r['pre_peak_v']:6.3f} V -> out {r['out_peak_v']:6.2f} V pk, "
            f"gain {r['gain_db']:5.2f} dB, {r['power_w']:6.2f} W, THD {r['thd_pct']:6.3f} % "
            f"(pre {r['thd_pre_pct']:.3f}), |Z| {r['z_ohm']:.1f}, rails {r['vp_v']:.1f}/{r['vn_v']:.1f} "
            f"ripple {r['vp_ripple_v']:.2f}"
        )
    fs_hz = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 40000]
    with ThreadPoolExecutor(max_workers=6) as ex:
        resp = list(
            ex.map(lambda f: point(spec, st, 0.003, f_hz=f, dur_s=0.5 if f >= 100 else 0.8), fs_hz)
        )
    g0 = next(r for f, r in zip(fs_hz, resp, strict=True) if f == 1000)["gain_db"]
    print("response re 1 kHz (power amp, pre_a -> a_amp):")
    for f, r in zip(fs_hz, resp, strict=True):
        print(f"  {f:6d} Hz {r['gain_db'] - g0:+6.2f} dB")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "amp.json").write_text(
        json.dumps(
            {
                "quality": a.quality,
                "levels": rows,
                "response": dict(
                    zip(map(str, fs_hz), [r["gain_db"] - g0 for r in resp], strict=True)
                ),
            },
            indent=1,
        )
    )
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(1, 3, figsize=(14, 4))
        ax[0].loglog([r["power_w"] for r in rows], [max(r["thd_pct"], 1e-4) for r in rows], "o-")
        ax[0].set(
            xlabel="power into the speakers (W)", ylabel="THD (%)", title="THD vs power, 1 kHz"
        )
        ax[1].semilogx(fs_hz, [r["gain_db"] - g0 for r in resp], "o-")
        ax[1].set(xlabel="Hz", ylabel="dB re 1 kHz", title="power amp response")
        ax[2].plot([r["pre_peak_v"] for r in rows], [r["out_peak_v"] for r in rows], "o-")
        ax[2].set(xlabel="pre_a peak (V)", ylabel="output peak (V)", title="transfer")
        for x in ax:
            x.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(OUT / "amp.png", dpi=110)
    except ImportError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

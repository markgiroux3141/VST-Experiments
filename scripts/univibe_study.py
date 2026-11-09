"""The Uni-Vibe measured and heard (docs/MODULATION_PLAN.md, MD1) -> reports/univibe/.

    uv run --extra fast --extra listen python scripts/univibe_study.py
        [--only rates sweep listen] [--clip "Dry Guitar.wav" --start 0 --seconds 12]
        [--quality production]

- rates: SPEED against the LFO's rate (the DAFx-19 paper: toe to heel ~0-7.6 Hz), the
  lamp's temperature swing and each cell's resistance range, at full INTENSITY
  (rates.json, rates.png);
- sweep: pink noise through CHORUS at INTENSITY 0.7 and ~2 Hz, its spectrogram (the
  paper's Fig. 9: the notches sweeping, a second one below the first) with the lamp's
  temperature and the cells' resistances under it (sweep.png);
- listen: a clip at -18 dBFS rms (0 dBFS = the circuit's 1 V peak: a guitar's level) through
  CHORUS and VIBRATO at three speeds, every file matched to -23 LUFS integrated (CLAUDE.md:
  loudness lies), plus the dry clip (listen/*.wav).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.circuit.ir import VoltageProbe  # noqa: E402
from varimu.config import REPO_ROOT  # noqa: E402
from varimu.devices.library import load_device  # noqa: E402
from varimu.sim import fast  # noqa: E402
from varimu.sim.io import TransientSettings, full_scale, load_audio, write_audio  # noqa: E402

OUT = REPO_ROOT / "reports" / "univibe"
CIRCUIT = "univibe"
TARGET_LUFS = -23.0
CELLS = [f"ps{k}" for k in range(1, 5)] + [f"l{k}b" for k in range(1, 5)]


def run(sets: dict, x: np.ndarray, quality: str, probes: list[str]) -> tuple[dict, int]:
    c = spec.load_circuit(spec.circuit_path(CIRCUIT))
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    ir = builder.build_ir(c, spec.resolve(c, sets))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    return fast.run_transient(ir, x, settings=st).vectors, st.sample_rate


def cell_ohms(v: dict) -> np.ndarray:
    cell = load_device("PDVP9203@1")
    g = [(v[f"v(ps{k})"] - v[f"v(l{k}b)"]) * cell.s_unit_s for k in range(1, 5)]
    return 1.0 / (cell.g_dark_s + np.maximum(np.array(g), 0.0))


def lfo_hz(y: np.ndarray, fs: int) -> float:
    y = y - y.mean()
    z = np.where((y[:-1] < 0) & (y[1:] >= 0))[0]
    return float(fs / np.mean(np.diff(z))) if len(z) > 2 else 0.0


def rates(quality: str) -> None:
    speeds = np.linspace(0.0, 1.0, 11)
    fs = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality).sample_rate
    n = round(6.0 * fs)
    m = round(3.0 * fs)
    probes = ["spd", "lt", "vc", *CELLS]

    def one(sp):
        v, _ = run({"speed": float(sp), "intensity": 1.0}, np.zeros(n), quality, probes)
        t_k = v["v(lt)"][-m:] - v["v(vc)"][-m:] + 300.0
        r = cell_ohms({k: a[-m:] for k, a in v.items()})
        return {
            "speed": float(sp),
            "lfo_hz": lfo_hz(v["v(spd)"][-m:], fs),
            "lfo_pp_v": float(np.ptp(v["v(spd)"][-m:])),
            "lamp_k": [float(t_k.min()), float(t_k.max())],
            "cell_min_ohm": r.min(axis=1).tolist(),
            "cell_max_ohm": r.max(axis=1).tolist(),
        }

    with ThreadPoolExecutor(6) as ex:
        rows = list(ex.map(one, speeds))
    (OUT / "rates.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    fig, ax = plt.subplots(1, 3, figsize=(14, 4))
    ax[0].plot(speeds, [r["lfo_hz"] for r in rows], "o-")
    ax[0].axhline(7.6, ls=":", c="k", label="paper: toe ~7.6 Hz")
    ax[0].set(xlabel="SPEED", ylabel="LFO (Hz)", title="rate")
    ax[0].legend()
    ax[1].fill_between(speeds, *np.array([r["lamp_k"] for r in rows]).T, alpha=0.4)
    ax[1].set(xlabel="SPEED", ylabel="filament (K)", title="lamp swing, INTENSITY 1")
    for k in range(4):
        ax[2].fill_between(
            speeds,
            [r["cell_min_ohm"][k] for r in rows],
            [r["cell_max_ohm"][k] for r in rows],
            alpha=0.25,
            label=f"LDR{k + 1}",
        )
    ax[2].set(yscale="log", xlabel="SPEED", ylabel="ohm", title="cell resistance range")
    ax[2].legend()
    fig.tight_layout()
    fig.savefig(OUT / "rates.png", dpi=120)
    for r in rows:
        print(
            f"  speed {r['speed']:.1f}: {r['lfo_hz']:.2f} Hz, {r['lfo_pp_v']:.1f} V p-p, "
            f"lamp {r['lamp_k'][0]:.0f}-{r['lamp_k'][1]:.0f} K"
        )


def sweep(quality: str) -> None:
    fs = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality).sample_rate
    n = round(5.0 * fs)
    rng = np.random.default_rng([2026, 11, 9])
    w = rng.standard_normal(n)
    b, a = [0.049922, -0.095993, 0.050612, -0.004408], [1, -2.494956, 2.017265, -0.522189]
    x = signal.lfilter(b, a, w)  # pink (Paul Kellet's / Smith's 3-pole approximation)
    x *= 0.05 / np.std(x)
    v, _ = run({"speed": 0.45, "intensity": 0.7}, x, quality, ["out", "lt", "vc", *CELLS])
    y = v["v(out)"][fs:]
    f, t, sxx = signal.spectrogram(y, fs, nperseg=4096, noverlap=3584)
    fig, ax = plt.subplots(3, 1, figsize=(10, 9), sharex=True, height_ratios=[3, 1, 1])
    ax[0].pcolormesh(t, f, 10 * np.log10(sxx + 1e-20), shading="auto", cmap="magma")
    ax[0].set(yscale="log", ylim=(40, 20e3), ylabel="Hz", title="CHORUS, pink noise in")
    tt = np.arange(len(y)) / fs
    ax[1].plot(tt, v["v(lt)"][fs:] - v["v(vc)"][fs:] + 300.0)
    ax[1].set(ylabel="filament (K)")
    r = cell_ohms({k: a[fs:] for k, a in v.items()})
    for k in range(4):
        ax[2].plot(tt, r[k], label=f"LDR{k + 1}")
    ax[2].set(yscale="log", ylabel="ohm", xlabel="s")
    ax[2].legend()
    fig.tight_layout()
    fig.savefig(OUT / "sweep.png", dpi=120)


def listen(quality: str, clip: str, start: float, seconds: float) -> None:
    from varimu.listen.matching import integrated_lufs

    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    fs = st.sample_rate
    c = spec.load_circuit(spec.circuit_path(CIRCUIT))
    v_in, v_out = full_scale(st, c)
    x = load_audio(REPO_ROOT / "data" / "clips" / clip, fs)
    x = x[int(start * fs) : int((start + seconds) * fs)]
    x = x * 10 ** (-18 / 20) / (np.std(x) + 1e-30)
    stem = Path(clip).stem.replace(" ", "_")
    variants = {
        f"{mode}_{name}": {"mode": m, "speed": sp, "intensity": 0.8}
        for mode, m in (("chorus", 0), ("vibrato", 1))
        for name, sp in (("slow", 0.15), ("mid", 0.45), ("fast", 0.85))
    }

    def one(item):
        name, sets = item
        r = fast.run_transient(builder.build(c, sets).ir, x * v_in, settings=st)
        return name, np.asarray(r.vectors["v(out)"]) / v_out

    def to_lufs(y):
        return y * 10 ** ((TARGET_LUFS - integrated_lufs(y, fs)) / 20)

    d = OUT / "listen"
    with ThreadPoolExecutor(len(variants)) as ex:
        outs = dict(ex.map(one, variants.items()))
    write_audio(d / f"{stem}_dry.wav", to_lufs(x), fs)
    for name, y in outs.items():
        write_audio(d / f"{stem}_{name}.wav", to_lufs(y - y.mean()), fs)
        print(f"  {name}: {20 * np.log10(np.std(y) / np.std(x)):+.1f} dB re the input")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", default=["rates", "sweep", "listen"])
    ap.add_argument("--quality", default="production")
    ap.add_argument("--clip", default="Dry Guitar.wav")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=12.0)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if "rates" in a.only:
        rates("draft")
    if "sweep" in a.only:
        sweep(a.quality)
    if "listen" in a.only:
        listen(a.quality, a.clip, a.start, a.seconds)
    print(f"done in {time.time() - t0:.0f} s -> {OUT}")


if __name__ == "__main__":
    main()

"""The gas-tube sawtooth's reference (HYBRID_PHYSICS_PLAN.md H1): RCA's 884 sweep oscillator
simulated directly, -> reports/hybrid/.

    uv run --extra fast python scripts/thyratron_study.py [--seconds S] [--rate HZ] [--only R,F ...]

config/circuits/rca_884_sweep.yaml at every S1 range (C2..C8) and both ends of R6 (fine 0:
the range's top, 1: its bottom), in circuitsim at production (esdirk4, local error control)
with its output at `--rate` (default 32 x 96 kHz, oversample 1: no decimation, the reset as
the engine resolves it). Per setting:
- the pitch: periods from the ramp's upward crossings of its midpoint (interpolated);
- the textbook charge-to-strike formula, T = R C ln((B - V_low) / (B - V_strike)), with
  the run's own V_low and V_strike (the timing physics alone) and with the sheet's a priori
  values (the strike on the average control characteristic at the grid's bias, the 16 V
  drop); R = R5 + R6's share, B and the voltages relative to the cathode;
- RCA's table (approximate; rca_884.provenance.yaml) for comparison;
- the reset: its length (the anode node falling from 90% to 10% of its swing), the peak
  current, the plasma's state through it;
- the cost: wall-clock per second of audio.
Plots: the waveforms (a few periods, the reset magnified), pitch against the table and the
formula. Audio: each setting's output decimated to 96 kHz (scipy resample_poly), at one gain.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.devices.library import load_device
from varimu.sim import fast, io

OUT = REPO_ROOT / "reports" / "hybrid"
CIRCUIT = CONFIG_DIR / "circuits" / "rca_884_sweep.yaml"
FS_AUDIO = 96000
PROBES = ("out", "a", "g", "k", "w")


def run(setting: tuple[int, float], seconds: float, rate: int) -> dict:
    rng, fine = setting
    s = spec.load_circuit(CIRCUIT)
    vals = spec.resolve(s, {"range": rng, "fine": fine})
    ir = builder.build_ir(s, vals)
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in PROBES))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production"),
        sample_rate=rate,
        oversample=1,
        full_scale_volts_peak=1.0,
        settle_s=0.0,
    )
    n = int(seconds * rate)
    t0 = time.perf_counter()
    res = fast.run_transient(ir, np.zeros(n), settings=st)
    wall = time.perf_counter() - t0
    v = {p: np.asarray(res.vectors[f"v({p})"]) for p in PROBES}
    return {"range": rng, "fine": fine, "values": vals, "v": v, "wall_s": wall, "rate": rate}


def periods(y: np.ndarray, rate: int) -> tuple[np.ndarray, float, float]:
    """Upward crossings of the ramp's midpoint (interpolated) in the run's second half (the
    cathode's bias settles with R11 C11, ~40 ms); the ramp's low and high levels there."""
    y = y[len(y) // 2 :]
    lo, hi = np.percentile(y, 0.5), np.percentile(y, 99.5)
    mid = 0.5 * (lo + hi)
    k = np.where((y[:-1] < mid) & (y[1:] >= mid))[0]
    t = (k + (mid - y[k]) / (y[k + 1] - y[k])) / rate
    return t, float(lo), float(hi)


def analyse(r: dict) -> dict:
    rate = r["rate"]
    vals = r["values"]
    vk = r["v"]["k"]
    y = r["v"]["out"] - vk
    t_up, lo, hi = periods(y, rate)
    out = {"range": r["range"], "fine": r["fine"], "wall_s": r["wall_s"]}
    if len(t_up) < 3:
        out["oscillates"] = False
        return out
    per = np.diff(t_up)
    f = 1.0 / per.mean()
    # the ramp's extremes over the measured periods (t_up counts from the run's middle)
    i0 = len(y) // 2 + int(t_up[0] * rate)
    seg = y[i0 : len(y) // 2 + int(t_up[-1] * rate)]
    v_low, v_strike = float(seg.min()), float(seg.max())
    c = vals[f"c{r['range']}_f"]
    r_ch = vals["r5_ohm"] + r["fine"] * vals["r6_ohm"]
    b = vals["b_plus_v"] - float(np.median(vk[len(vk) // 2 :]))
    t_formula = r_ch * c * np.log((b - v_low) / (b - v_strike))
    tube = load_device("884@1")
    from varimu.devices.thyratron_fit import strike_vg

    bias = -float(np.median(vk[len(vk) // 2 :]))
    # the sheet's strike at this bias: invert the model's control characteristic
    from scipy.optimize import brentq

    v_s0 = brentq(lambda va: strike_vg(tube, va) - bias, 20.0, 400.0)
    t_apriori = r_ch * c * np.log((b - 16.0) / (b - v_s0))
    # the reset: the last full one
    k_hi = i0 + int(np.argmax(seg))
    after = y[k_hi : k_hi + int(2e-3 * rate)]
    a90 = v_low + 0.9 * (v_strike - v_low)
    a10 = v_low + 0.1 * (v_strike - v_low)
    j90 = int(np.argmax(after < a90))
    j10 = int(np.argmax(after < a10))
    ia = (r["v"]["out"] - r["v"]["a"]) / vals["r4_ohm"]
    out.update(
        oscillates=True,
        f_hz=float(f),
        period_spread=float(per.std() / per.mean()),
        v_low=v_low,
        v_strike=v_strike,
        formula_f_hz=float(1.0 / t_formula),
        apriori_f_hz=float(1.0 / t_apriori),
        apriori_strike_v=float(v_s0),
        bias_v=bias,
        reset_90_10_s=float((j10 - j90) / rate),
        peak_ia_a=float(ia[k_hi : k_hi + int(1e-4 * rate)].max()),
        audio_s=len(y) / rate,
        wall_per_audio_s=r["wall_s"] / (len(y) / rate),
    )
    return out


def plot(results: list[dict], analyses: list[dict], table: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    # pitch vs RCA's table
    for fine, mk, key in ((0.0, "o", "f_r6_min_hz"), (1.0, "s", "f_r6_max_hz")):
        a = [x for x in analyses if x["fine"] == fine and x.get("oscillates")]
        rs = [x["range"] for x in a]
        ax[0, 0].semilogy(rs, [x["f_hz"] for x in a], mk + "-", label=f"simulated, R6 {key[5:8]}")
        ax[0, 0].semilogy(rs, [x["formula_f_hz"] for x in a], mk + ":", alpha=0.6,
                          label=f"formula (run's levels), R6 {key[5:8]}")  # fmt: skip
        ax[0, 0].semilogy(
            list(range(2, 9)), [table[key][f"c{n}"] for n in range(2, 9)], mk + "--", color="k",
            alpha=0.5, label=f"RCA table, R6 {key[5:8]}",
        )  # fmt: skip
    ax[0, 0].set_xlabel("S1 (C2..C8)")
    ax[0, 0].set_ylabel("Hz")
    ax[0, 0].legend(fontsize=7)
    ax[0, 0].set_title("pitch: the reference against RCA's (approximate) table")
    # waveforms: the middle range, a few periods; the reset magnified
    pick = next(
        (r for r, a in zip(results, analyses, strict=True) if r["range"] == 5 and r["fine"] == 0),
        results[0],
    )
    rate = pick["rate"]
    y = pick["v"]["out"] - pick["v"]["k"]
    n = len(y)
    t = np.arange(n) / rate
    m = t > t[-1] - 4.0 / max(a.get("f_hz", 100.0) for a in analyses if a["range"] == pick["range"])
    ax[0, 1].plot(t[m] * 1e3, y[m])
    ax[0, 1].set_xlabel("ms")
    ax[0, 1].set_ylabel("V (anode node to cathode)")
    ax[0, 1].set_title(f"C{pick['range']}, R6 at {pick['fine']}: the sweep")
    k_hi = int(np.argmax(y[int(0.5 * n) :])) + int(0.5 * n)
    w = slice(max(k_hi - int(5e-6 * rate), 0), k_hi + int(80e-6 * rate))
    tt = (np.arange(n)[w] - k_hi) / rate * 1e6
    ax[1, 0].plot(tt, y[w], label="anode node (V)")
    ax[1, 0].plot(tt, pick["v"]["a"][w] - pick["v"]["k"][w], label="anode (V)")
    ax[1, 0].plot(tt, (pick["v"]["g"][w] - pick["v"]["k"][w]) * 5, label="grid x5 (V)")
    ax2 = ax[1, 0].twinx()
    ax2.plot(tt, pick["v"]["w"][w] - pick["v"]["k"][w], "k:", label="ln x (state)")
    ax2.set_ylabel("ln x")
    ax[1, 0].set_xlabel("us from the strike")
    ax[1, 0].legend(fontsize=7, loc="upper right")
    ax[1, 0].set_title("the reset (the reference's own resolution)")
    # cost
    a = [x for x in analyses if x.get("oscillates")]
    ax[1, 1].semilogy([x["f_hz"] for x in a], [x["wall_per_audio_s"] for x in a], "o")
    ax[1, 1].set_xscale("log")
    ax[1, 1].set_xlabel("pitch (Hz)")
    ax[1, 1].set_ylabel("wall s per audio s")
    ax[1, 1].set_title(f"the reference's cost (production, output at {rate / 1e6:.3f} MHz)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=0.5)
    ap.add_argument("--rate", type=int, default=32 * FS_AUDIO)
    ap.add_argument("--only", nargs="*", help="settings as RANGE,FINE (e.g. 5,0)")
    ap.add_argument("--workers", type=int, default=7)
    args = ap.parse_args()
    settings = [(n, f) for n in range(2, 9) for f in (0.0, 1.0)]
    if args.only:
        settings = [(int(x.split(",")[0]), float(x.split(",")[1])) for x in args.only]
    OUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run, s, args.seconds, args.rate) for s in settings]
        results = [f.result() for f in futs]
    analyses = [analyse(r) for r in results]
    import yaml

    table = yaml.safe_load((REPO_ROOT / "data/datasheets/published_points.yaml").read_text())[
        "884"
    ]["sweep_circuit"]
    for a in analyses:
        key = "f_r6_min_hz" if a["fine"] == 0 else "f_r6_max_hz"
        a["rca_table_hz"] = table[key][f"c{a['range']}"]
        print(json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in a.items()}))
    (OUT / "rca_884_sweep.json").write_text(json.dumps(analyses, indent=1))
    plot(results, analyses, table, OUT / "rca_884_sweep.png")
    # audio
    import soundfile as sf
    from scipy.signal import resample_poly

    adir = OUT / "audio"
    adir.mkdir(exist_ok=True)
    ys = []
    for r in results:
        y = r["v"]["out"] - r["v"]["k"]
        ys.append(resample_poly(y - y.mean(), FS_AUDIO, r["rate"]))
    gain = 0.5 / max(np.max(np.abs(y)) for y in ys)
    for r, y in zip(results, ys, strict=True):
        sf.write(
            adir / f"rca884_c{r['range']}_fine{r['fine']:.0f}.wav",
            (y * gain).astype(np.float32),
            FS_AUDIO,
            subtype="FLOAT",
        )
    print("wrote", OUT / "rca_884_sweep.json", OUT / "rca_884_sweep.png", adir)


if __name__ == "__main__":
    main()

"""AM5, dispersion before saturation (docs/ANALOG_MAGIC_FABLE.md).

Step 1: each stage's small-signal phase from a -40 dBFS sweep (checked at -50 dBFS), the
chain's cumulative group delay and a fitted count of first-order high-pass poles. The chain
is a 1960s path: V76 mic pre -> EQP-1A (its default panel) -> 670 (below threshold) -> the
351 (record, tape, playback) -> the 351 again (the mix-down) -> the 670 again (the master).
No lathe or cartridge (not built).
Step 2: that phase as an all-pass FIR (unit magnitude).
Step 3: the commutator: for a saturating stage S and a program x, y1 = S(AP(x)) (the
historical order) against y2 = AP(S(x)); the character part of their difference is the
interaction (minus infinity if dispersion and saturation commuted). Seeds held equal (noise
off; the tape machine without grain or flutter).

-> reports/magic/dispersion/ (summary.json, dispersion.png, the largest case's pair
loudness-matched for an ABX).

  uv run --extra fast --extra listen python scripts/dispersion_study.py [--step 1 3]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from functools import partial

import numpy as np

from varimu.config import REPO_ROOT
from varimu.listen import difference
from varimu.magic import dispersion as dp
from varimu.magic import fingerprints as fp
from varimu.magic import render
from varimu.sim.io import load_audio, write_audio

OUT = REPO_ROOT / "reports" / "magic" / "dispersion"
CHAIN = [
    "telefunken_v76",
    "pultec_eqp1a",
    "fairchild_670",
    "ampex_351",
    "ampex_351",
    "fairchild_670",
]
PROGRAMS = {
    "drums": "drums_setmefree.wav",
    "voice": "vocal_longwayhome.wav",
    "bass": "bass_areasontoleave.wav",
}


def stage_fn(name: str):
    if name == "ampex_351":
        return lambda x: render.ampex_351(x, noise=False, tail_s=0.0)["out"]
    return lambda x: render.through(name, x, noise=False)["out"]


def step1(fs: int) -> dict:
    res = {}
    for name in dict.fromkeys(CHAIN):
        t = time.time()
        r40 = dp.small_signal(stage_fn(name), fs, level_dbfs=-40.0)
        r50 = dp.small_signal(stage_fn(name), fs, level_dbfs=-50.0)
        sel = (r40["f"] > 20) & (r40["f"] < 20000)
        dmag = np.max(np.abs(20 * np.log10(np.abs(r40["H"][sel] / r50["H"][sel]))))
        dph = np.max(np.abs(np.degrees(np.angle(r40["H"][sel] / r50["H"][sel]))))
        res[name] = {
            "f": r40["f"],
            "H": r40["H"],
            "delay_s": r40["delay_s"],
            "linearity_db": float(dmag),
            "linearity_deg": float(dph),
        }
        print(
            f"  {name}: delay {r40['delay_s'] * 1e3:.2f} ms, -40 vs -50 dBFS within "
            f"{dmag:.3f} dB / {dph:.2f} deg ({time.time() - t:.0f} s)",
            flush=True,
        )
    return res


def chain_response(stages: dict) -> tuple[np.ndarray, np.ndarray]:
    f = stages[CHAIN[0]]["f"]
    H = np.ones_like(f, dtype=complex)
    for name in CHAIN:
        H = H * stages[name]["H"]
    return f, H


def program(name: str, seconds: float, fs: int) -> np.ndarray:
    x = load_audio(REPO_ROOT / "data" / "clips" / PROGRAMS[name], fs)
    # The loudest 10 s (by rms over 1 s hops) of the clip.
    w = int(seconds * fs)
    if len(x) > w:
        hop = fs
        e = [np.mean(x[s : s + w] ** 2) for s in range(0, len(x) - w, hop)]
        s0 = int(np.argmax(e)) * hop
        x = x[s0 : s0 + w]
    x = x * 10 ** (-18 / 20) / (np.std(x) + 1e-30)
    f = int(0.02 * fs)
    x[:f] *= np.linspace(0, 1, f)
    x[-f:] *= np.linspace(1, 0, f)
    return x


SAT_STAGES = {
    "tape_0dB": partial(render.tape_print, drive_db=0.0, noise_seed=None, flutter=False),
    "tape_+6dB": partial(render.tape_print, drive_db=6.0, noise_seed=None, flutter=False),
    "tape_+12dB": partial(render.tape_print, drive_db=12.0, noise_seed=None, flutter=False),
    "670_in+6dB": "670:6",
    "670_in+12dB": "670:12",
    "5e3_vol0.7": "5e3",
}


def sat_fn(name: str):
    s = SAT_STAGES[name]
    if callable(s):
        return lambda x: s(x)["out"]
    if s.startswith("670"):
        g = 10 ** (float(s.split(":")[1]) / 20)
        return lambda x: render.through("fairchild_670", x * g, noise=False)["out"]
    return lambda x: render.through("fender_5e3", x, overrides={"volume_bright": 0.7}, noise=False)[
        "out"
    ]


def step3(fs: int, fir: np.ndarray) -> dict:
    progs = {k: program(k, 10.0, fs) for k in PROGRAMS}
    ap = {k: dp.apply_fir(fir, x) for k, x in progs.items()}
    jobs = []
    for s in SAT_STAGES:
        for p in progs:
            jobs.append((s, p, "S(x)", progs[p]))
            jobs.append((s, p, "S(AP(x))", ap[p]))
    from concurrent.futures import ThreadPoolExecutor

    from varimu.sim.runner import default_jobs

    t0 = time.time()

    def one(j):
        s, p, tag, x = j
        return (s, p, tag), sat_fn(s)(x)

    with ThreadPoolExecutor(default_jobs()) as ex:
        outs = dict(ex.map(one, jobs))
    print(f"  step 3 renders: {(time.time() - t0) / 60:.1f} min", flush=True)
    res = {"programs": {}, "cases": {}}
    for p, x in progs.items():
        res["programs"][p] = {
            "crest_x": fp.crest_by_band(x, fs),
            "crest_ap_x": fp.crest_by_band(ap[p], fs),
            "asym_x": fp.asymmetry(x, fs),
            "asym_ap_x": fp.asymmetry(ap[p], fs),
        }
    best = None
    for s in SAT_STAGES:
        for p, x in progs.items():
            sx = outs[(s, p, "S(x)")]
            y1 = outs[(s, p, "S(AP(x))")][: len(x)]
            y2 = dp.apply_fir(fir, sx)[: len(x)]
            lv = difference.levels(y1, y2)
            stage_char = difference.levels(x, sx[: len(x)])["character"]
            gain_db = 20 * np.log10(np.std(sx[: len(x)]) / np.std(x))
            gain_ap_db = 20 * np.log10(np.std(y1) / np.std(ap[p]))
            res["cases"][f"{s} {p}"] = {
                "interaction": lv,
                "stage_character_db": stage_char,
                "gain_db": gain_db,
                "gain_ap_db": gain_ap_db,
            }
            print(
                f"  {s:12s} {p:6s}: interaction character {lv['character']:6.1f} dB "
                f"(stage's own character {stage_char:6.1f}; gain {gain_db:+.2f} / after AP "
                f"{gain_ap_db:+.2f} dB)",
                flush=True,
            )
            if best is None or lv["character"] > best[0]:
                best = (lv["character"], s, p, y1, y2)
    if best:
        from varimu.listen.matching import match_loudness

        _, s, p, y1, y2 = best
        (m1, m2), _ = match_loudness([y1, y2], fs)
        write_audio(OUT / "abx" / f"{s}_{p}_historical_S_of_AP.wav", m1, fs)
        write_audio(OUT / "abx" / f"{s}_{p}_AP_of_S.wav", m2, fs)
        res["largest"] = f"{s} {p}"
    return res


def plot(stages: dict, f: np.ndarray, H: np.ndarray) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(13, 4.5))
    for name, s in stages.items():
        ax[0].semilogx(s["f"], 1e3 * dp.group_delay(s["f"], s["H"]), label=name)
    ax[0].semilogx(f, 1e3 * dp.group_delay(f, H), "k", lw=2, label="chain (6 stages)")
    ax[0].set(
        xlim=(15, 20000),
        ylim=(-1, None),
        xlabel="Hz",
        ylabel="group delay (ms)",
        title="group delay per stage and the chain",
    )
    for name, s in stages.items():
        ax[1].semilogx(
            s["f"],
            20 * np.log10(np.abs(s["H"]) / np.abs(s["H"][np.argmin(np.abs(s["f"] - 1000))])),
            label=name,
        )
    ax[1].set(
        xlim=(15, 30000),
        ylim=(-30, 10),
        xlabel="Hz",
        ylabel="dB re 1 kHz",
        title="magnitude per stage",
    )
    for a in ax:
        a.grid(True, which="both", alpha=0.3)
        a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "dispersion.png", dpi=110)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--step", nargs="+", type=int, default=[1, 3])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fs = render.sample_rate()
    summ_path = OUT / "summary.json"
    summ = json.loads(summ_path.read_text()) if summ_path.exists() else {}
    stages = step1(fs)
    f, H = chain_response(stages)
    gd = dp.group_delay(f, H)
    poles = dp.fit_poles(f, H)
    summ["step1"] = {
        n: {
            "delay_s": s["delay_s"],
            "linearity_db": s["linearity_db"],
            "linearity_deg": s["linearity_deg"],
            "group_delay_ms": {
                str(fc): float(1e3 * np.interp(fc, s["f"], dp.group_delay(s["f"], s["H"])))
                for fc in (20, 40, 80, 160, 1000)
            },
        }
        for n, s in stages.items()
    }
    summ["chain"] = {
        "stages": CHAIN,
        "fit": poles,
        "group_delay_ms": {
            str(fc): float(1e3 * np.interp(fc, f, gd))
            for fc in (20, 30, 40, 60, 80, 120, 160, 250, 500, 1000)
        },
    }
    print(f"chain: {json.dumps(summ['chain'], default=float)}", flush=True)
    plot(stages, f, H)
    fir = dp.allpass_fir(f, H, fs)
    _, hf = __import__("scipy.signal", fromlist=["freqz"]).freqz(
        fir, worN=np.geomspace(20, 20000, 300), fs=fs
    )
    summ["allpass_flat_db"] = float(np.max(np.abs(20 * np.log10(np.abs(hf)))))
    print(f"all-pass FIR flat within {summ['allpass_flat_db']:.3f} dB 20 Hz-20 kHz", flush=True)
    np.save(OUT / "chain_allpass_fir.npy", fir)
    summ_path.write_text(json.dumps(summ, indent=1, default=float))
    if 3 in a.step:
        summ["step3"] = step3(fs, fir)
        summ_path.write_text(json.dumps(summ, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())

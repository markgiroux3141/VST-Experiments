"""AM6, noise-forced gain staging (docs/ANALOG_MAGIC_FABLE.md): per stage and input level L
(-40 to +6 dBFS rms in 3 dB steps, a 6 s voice excerpt), the output's noise (seed 1 on
silence, A-weighted), its distortion (the character part of difference.decompose(input,
output): what no fixed filter explains, A-weighted) and its signal; the impairment
(noise^2 + character^2) / signal^2 and the level L* where it is least, against the
project's operating level (0 VU = -18 dBFS rms). L* is also given with the noise's power
halved and doubled (flicker and mains wander are provisional, varimu/devices/noise.py).

-> reports/magic/levels/ (summary.json, levels.png).

  uv run --extra fast --extra listen python scripts/noise_forced_levels.py [--only STAGE ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np

from varimu.config import REPO_ROOT
from varimu.listen import difference
from varimu.magic import levels as lvmod
from varimu.magic import null, render
from varimu.sim.io import load_audio

OUT = REPO_ROOT / "reports" / "magic" / "levels"
LEVELS_DB = np.arange(-40.0, 6.01, 3.0)
STAGES = ("telefunken_v76", "fairchild_670", "pultec_eqp1a", "ampex_351")
OPERATING_DBFS_RMS = -18.0  # 0 VU (CLAUDE.md's convention, the 351's alignment)


def program(fs: int, seconds: float = 6.0) -> np.ndarray:
    x = load_audio(REPO_ROOT / "data" / "clips" / "vocal_longwayhome.wav", fs)
    w = int(seconds * fs)
    e = [np.mean(x[s : s + w] ** 2) for s in range(0, max(len(x) - w, 1), fs)]
    s0 = int(np.argmax(e)) * fs
    x = x[s0 : s0 + w]
    x = x / np.std(x)  # 0 dBFS rms; scaled per level
    f = int(0.02 * fs)
    x[:f] *= np.linspace(0, 1, f)
    x[-f:] *= np.linspace(1, 0, f)
    return x


def job(stage: str, x: np.ndarray, noise) -> dict:
    if stage == "ampex_351":
        return {"fn": render.ampex_351, "x": x, "noise": noise, "tail_s": 0.0}
    return {"circuit": stage, "x": x, "noise": noise}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="+", default=list(STAGES))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fs = render.sample_rate()
    x = program(fs)
    jobs, keys = [], []
    for st in a.only:
        jobs.append(job(st, np.zeros_like(x), 1))
        keys.append((st, "noise"))
        for L in LEVELS_DB:
            jobs.append(job(st, x * 10 ** (L / 20), False))
            keys.append((st, float(L)))
    # Longest first: the 351.
    order = sorted(range(len(jobs)), key=lambda i: keys[i][0] != "ampex_351")
    t0 = time.time()
    print(f"{len(jobs)} renders of {len(x) / fs:.0f} s", flush=True)
    outs = render.through_many([jobs[i] for i in order])
    ys = {keys[i]: o["out"] for i, o in zip(order, outs, strict=True)}
    print(f"rendered in {(time.time() - t0) / 60:.1f} min", flush=True)
    summ_path = OUT / "summary.json"
    summ = json.loads(summ_path.read_text()) if summ_path.exists() else {}
    e = fs // 4
    for st in a.only:
        n_a = lvmod.a_rms(ys[(st, "noise")], fs)
        rows = []
        for L in LEVELS_DB:
            u = x * 10 ** (L / 20)
            y = ys[(st, float(L))][: len(u)]
            if st == "ampex_351":
                # The transport's wow and flutter is a time base no fixed filter explains: it
                # would count as "character" at every level (-6.5 dB re signal before this).
                # Removed first, as AM2's dewarped stage does.
                tt, dl = null.delay_track(u, y, fs)
                y = null.dewarp(y, fs, tt, dl)
            d = difference.decompose(u, y)
            # The character part, referred to the output (decompose maps the output onto the
            # input: scale back by the output / input gain).
            g = np.std(y) / np.std(u)
            ch = d.character[e:-e] * g
            rows.append(
                {
                    "level_db": float(L),
                    "signal_a": lvmod.a_rms(y, fs),
                    "character_a": lvmod.a_rms(ch, fs, 0.0),
                    "character": float(np.std(ch)),
                }
            )
        sig = np.array([r["signal_a"] for r in rows])
        ch = np.array([r["character_a"] for r in rows])
        res = {"noise_a_rms": n_a, "rows": rows}
        # A part of the character that scales with the signal (the 351's residual flutter and
        # modulation noise; decompose's own floor elsewhere) is the same ratio at every level:
        # it can't move the optimum, only bury it in wobble. L* is found on the rest, the
        # character's power over that floor (the least ratio on the grid).
        floor = float(np.min(ch / sig))
        excess = np.maximum(ch**2 - (floor * sig) ** 2, 0.0)
        res["character_floor_db_re_signal"] = float(20 * np.log10(floor))
        for tag, k in (("L_star", 1.0), ("L_star_noise_half", 0.5), ("L_star_noise_double", 2.0)):
            imp = (k * n_a**2 + excess) / sig**2
            res[tag] = lvmod.optimum(LEVELS_DB, imp)
        edge = {float(LEVELS_DB[0]): "below the grid", float(LEVELS_DB[-1]): "above the grid"}
        res["L_star_at_edge"] = edge.get(res["L_star"])
        imp = (n_a**2 + ch**2) / sig**2
        i = int(np.argmin((n_a**2 + excess) / sig**2))
        res["impairment_min_db"] = float(10 * np.log10(imp[i]))
        res["at_L_star"] = {
            "noise_db_re_signal": float(20 * np.log10(n_a / sig[i])),
            "character_db_re_signal": float(20 * np.log10(ch[i] / sig[i])),
            "character_over_floor_db_re_signal": over_db(excess[i], sig[i]),
            "distortion_percent": float(100 * ch[i] / sig[i]),
        }
        res["operating_dbfs_rms"] = OPERATING_DBFS_RMS
        j = int(np.argmin(np.abs(LEVELS_DB - OPERATING_DBFS_RMS)))
        res["at_operating"] = {
            "noise_db_re_signal": float(20 * np.log10(n_a / sig[j])),
            "character_db_re_signal": float(20 * np.log10(ch[j] / sig[j])),
            "character_over_floor_db_re_signal": over_db(excess[j], sig[j]),
        }
        summ[st] = res
        at = res["at_L_star"]
        ov = at["character_over_floor_db_re_signal"]
        print(
            f"{st}: L* {res['L_star']:+.1f} dBFS rms (noise x0.5 "
            f"{res['L_star_noise_half']:+.1f}, x2 {res['L_star_noise_double']:+.1f}"
            f"{'; ' + res['L_star_at_edge'] if res['L_star_at_edge'] else ''}); at L*: noise "
            f"{at['noise_db_re_signal']:.1f}, character {at['character_db_re_signal']:.1f}"
            f" (over its floor {'none' if ov is None else f'{ov:.1f}'}) dB re signal;"
            f" floor {res['character_floor_db_re_signal']:.1f}",
            flush=True,
        )
    summ_path.write_text(json.dumps(summ, indent=1, default=float))
    plot(summ)
    return 0


def over_db(excess: float, sig: float) -> float | None:
    """The character over its floor in dB re the signal; None where it is all floor."""
    return float(10 * np.log10(excess / sig**2)) if excess > 0 else None


def plot(summ: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(summ)
    fig, axes = plt.subplots(1, n, figsize=(4.5 * n, 4), squeeze=False)
    for ax, (st, r) in zip(axes[0], summ.items(), strict=True):
        L = np.array([q["level_db"] for q in r["rows"]])
        sig = np.array([q["signal_a"] for q in r["rows"]])
        ch = np.array([q["character_a"] for q in r["rows"]])
        ax.plot(L, 20 * np.log10(r["noise_a_rms"] / sig), label="noise re signal (A)")
        ax.plot(L, 20 * np.log10(ch / sig), label="character re signal (A)")
        fl = 10 ** (r["character_floor_db_re_signal"] / 20)
        ex = np.maximum(ch**2 - (fl * sig) ** 2, 1e-30)
        ax.plot(L, 10 * np.log10(ex / sig**2), ls="--", label="character over its floor")
        ax.plot(L, 10 * np.log10((r["noise_a_rms"] ** 2 + ch**2) / sig**2), "k", label="impairment")
        ax.axvline(r["L_star"], color="k", ls=":", label=f"L* {r['L_star']:+.1f}")
        ax.axvline(r["operating_dbfs_rms"], color="r", ls="--", label="0 VU")
        ax.set(title=st, xlabel="input dBFS rms", ylabel="dB re output signal")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "levels.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())

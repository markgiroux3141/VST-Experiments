"""Stage 1's done-when checks: the trained net in the bench (closed loop) against JA.

Every test item runs through the bench with the net (`NumpyNet`, items of one length
batched) and with the core's linear limit (the baseline), and both are compared with the
teacher's run (JA, from teacher.py):

- stable: every output finite, Newton converged; the idle item's last 10 s silent;
- residual: rms(e_net - e_ja) / rms(e_ja) (dB) per random item, at or below -60 dB;
- THD vs level (20 Hz, 50 Hz, 1 kHz; -40..+20 dBu): within 1 dB of JA's where JA's is
  above -120 dB, below -120 dB where JA's is;
- remanence: the -20 dBu tone after a loud burst (residual and THD), and the remanent B.

Writes runs/<name>/eval/summary.json and plots (THD vs level, B-H loops).

    uv run --extra ml python -m spike.neural_core.evaluate [--name v1]
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import torch

from spike.neural_core.bench import LinearCore, run, t101_bench
from spike.neural_core.model import TorchNet
from spike.neural_core.model_inc import IncNet
from spike.neural_core.signals import THD_CYCLES
from spike.neural_core.teacher import OUT_DIR, load
from spike.neural_core.train import rel_err_db, s_lin

THD_FLOOR_DB = -120.0
THD_TOL_DB = 1.0
RESIDUAL_MAX_DB = -60.0


def thd_db(e: np.ndarray, f_hz: float, fs: int) -> float:
    n = int(round(THD_CYCLES * fs / f_hz))
    spec = np.abs(np.fft.rfft(e[-n:]))
    k = THD_CYCLES
    harm = [spec[k * m] for m in range(2, 11) if k * m < len(spec)]
    return float(20 * np.log10(np.sqrt(np.sum(np.square(harm))) / spec[k]))


def run_grouped(bench, seqs_v, make_core) -> list[dict[str, np.ndarray]]:
    """Run every sequence, batching those of equal length."""
    out: list[dict | None] = [None] * len(seqs_v)
    by_len: dict[int, list[int]] = {}
    for i, v in enumerate(seqs_v):
        by_len.setdefault(len(v), []).append(i)
    for idx in by_len.values():
        r = run(bench, np.stack([seqs_v[i] for i in idx]), make_core(len(idx)))
        for j, i in enumerate(idx):
            out[i] = {k: (x[j] if x.ndim == 2 else x) for k, x in r.items()}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", default="v1")
    args = ap.parse_args()
    run_dir = OUT_DIR / "runs" / args.name
    eval_dir = run_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    log = json.loads((run_dir / "log.json").read_text())

    items, seqs, info = load("test")
    fs = info["fs_hz"]
    bench = t101_bench()
    slope = s_lin()
    a = log["args"]
    net = IncNet(a["width"], a["depth"]) if "width" in a else TorchNet(a["hidden"])
    net.load_state_dict(torch.load(run_dir / "net.pt", map_location="cpu"))
    cell = net.to_numpy(slope)

    def make_net(n):
        cell.reset(n)
        return cell

    t0 = time.perf_counter()
    nets = run_grouped(bench, seqs["v"], make_net)
    t_net = time.perf_counter() - t0
    lins = run_grouped(bench, seqs["v"], lambda n: LinearCore(bench.core_model(), n))
    print(f"closed loop: {t_net:.0f} s for the net (numpy, batched)")

    summary: dict = {"name": args.name, "items": {}}
    stable = all(np.all(np.isfinite(r["e"])) for r in nets)
    fam_res: dict[str, list[tuple[float, float]]] = {}
    thd_rows = []
    for (name, meta), ja_e, ja_b, rn, rl in zip(
        items, seqs["e"], seqs["b"], nets, lins, strict=True
    ):
        row = {
            "residual_db": rel_err_db(rn["e"], ja_e),
            "linear_residual_db": rel_err_db(rl["e"], ja_e),
            "newton_max": int(rn["newton"].max()),
        }
        if "family" in meta:
            fam_res.setdefault(meta["family"], []).append(
                (row["residual_db"], row["linear_residual_db"])
            )
        if name.startswith("thd/"):
            f = meta["f_hz"]
            row |= {
                "thd_ja_db": thd_db(ja_e, f, fs),
                "thd_net_db": thd_db(rn["e"], f, fs),
                "thd_linear_db": thd_db(rl["e"], f, fs),
            }
            ja, nt = row["thd_ja_db"], row["thd_net_db"]
            row["thd_ok"] = abs(nt - ja) <= THD_TOL_DB if ja > THD_FLOOR_DB else nt <= THD_FLOOR_DB
            thd_rows.append((meta["f_hz"], meta["dbu"], ja, nt, row["thd_linear_db"]))
        if name == "remanence":
            k = int(meta["tone_from_s"] * fs)
            row |= {
                "tone_residual_db": rel_err_db(rn["e"][k:], ja_e[k:]),
                "remanent_b_ja_t": float(ja_b[k - 1]),
                "remanent_b_net_t": float(rn["b"][k - 1]),
                "tone_thd_ja_db": thd_db(ja_e[k:], 1000, fs),
                "tone_thd_net_db": thd_db(rn["e"][k:], 1000, fs),
            }
        if name == "idle":
            k = int((meta["silent_from_s"] + 0.3) * fs)
            last = slice(len(ja_e) - fs, None)
            row |= {
                "idle_peak_e_ja_v": float(np.abs(ja_e[k:]).max()),
                "idle_peak_e_net_v": float(np.abs(rn["e"][k:]).max()),
                "idle_last_s_rms_e_net_v": float(np.sqrt(np.mean(rn["e"][last] ** 2))),
                "b_end_ja_t": float(ja_b[-1]),
                "b_end_net_t": float(rn["b"][-1]),
            }
        summary["items"][name] = row

    fam = {
        f: {
            "residual_db": float(np.mean([a for a, _ in v])),
            "worst_db": float(np.max([a for a, _ in v])),
            "linear_residual_db": float(np.mean([b for _, b in v])),
        }
        for f, v in sorted(fam_res.items())
    }
    worst = max(x["worst_db"] for x in fam.values())
    idle = summary["items"]["idle"]
    rem = summary["items"]["remanence"]
    verdict = {
        "stable": bool(
            stable and idle["idle_peak_e_net_v"] <= 10 * idle["idle_peak_e_ja_v"] + 1e-9
        ),
        "residual": worst <= RESIDUAL_MAX_DB,
        "thd": all(summary["items"][n]["thd_ok"] for n in summary["items"] if n.startswith("thd/")),
        "remanence": rem["tone_residual_db"] <= RESIDUAL_MAX_DB
        and abs(rem["tone_thd_net_db"] - rem["tone_thd_ja_db"]) <= THD_TOL_DB,
    }
    summary |= {"families": fam, "verdict": verdict, "closed_loop_s": t_net}
    (eval_dir / "summary.json").write_text(json.dumps(summary, indent=1))

    print("\nresidual vs JA, closed loop (dB re signal): net mean / worst | linear core")
    for f, x in fam.items():
        net_db, worst_db, lin_db = x["residual_db"], x["worst_db"], x["linear_residual_db"]
        print(f"  {f:11s} {net_db:7.1f} / {worst_db:6.1f} | {lin_db:6.1f}")
    print("\nTHD (dB): f, dBu, JA, net, linear")
    for f, dbu, ja, nt, li in thd_rows:
        print(f"  {f:5.0f} {dbu:+4d} {ja:8.1f} {nt:8.1f} {li:8.1f}")
    print(
        f"\nremanence: tone residual {rem['tone_residual_db']:.1f} dB, THD JA "
        f"{rem['tone_thd_ja_db']:.1f} / net {rem['tone_thd_net_db']:.1f} dB, remanent B JA "
        f"{rem['remanent_b_ja_t'] * 1e3:.3f} / net {rem['remanent_b_net_t'] * 1e3:.3f} mT"
    )
    print(
        f"idle: peak e after the burst JA {idle['idle_peak_e_ja_v']:.3g} / net "
        f"{idle['idle_peak_e_net_v']:.3g} V; B at the end JA {idle['b_end_ja_t'] * 1e3:.3f} / "
        f"net {idle['b_end_net_t'] * 1e3:.3f} mT"
    )
    print(f"\nverdict: {verdict}")
    plots(eval_dir, thd_rows, items, seqs, nets)


def plots(eval_dir, thd_rows, items, seqs, nets) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(14, 4), sharey=True)
    for ax, f in zip(axes, sorted({r[0] for r in thd_rows}), strict=True):
        rows = [r for r in thd_rows if r[0] == f]
        lv = [r[1] for r in rows]
        ax.plot(lv, [r[2] for r in rows], "o-", label="JA (teacher)")
        ax.plot(lv, [r[3] for r in rows], "x--", label="net")
        ax.plot(lv, [r[4] for r in rows], ":", color="grey", label="linear core")
        ax.axhline(THD_FLOOR_DB, color="k", lw=0.5)
        ax.set_title(f"{f:.0f} Hz")
        ax.set_xlabel("source level (dBu)")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("THD (dB)")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(eval_dir / "thd_vs_level.png", dpi=120)
    plt.close(fig)

    names = [n for n, _ in items]
    picks = [
        n
        for n in ("thd/50hz/+10dbu", "thd/20hz/+20dbu", "thd/1000hz/-20dbu", "remanence")
        if n in names
    ]
    fig, axes = plt.subplots(1, len(picks), figsize=(4 * len(picks), 4))
    for ax, n in zip(np.atleast_1d(axes), picks, strict=True):
        i = names.index(n)
        ax.plot(seqs["h"][i], seqs["b"][i] * 1e3, lw=0.8, label="JA")
        ax.plot(nets[i]["h"], nets[i]["b"] * 1e3, lw=0.8, ls="--", label="net")
        ax.set_title(n)
        ax.set_xlabel("H (A/m)")
        ax.grid(alpha=0.3)
    np.atleast_1d(axes)[0].set_ylabel("B (mT)")
    np.atleast_1d(axes)[0].legend()
    fig.tight_layout()
    fig.savefig(eval_dir / "bh_loops.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()

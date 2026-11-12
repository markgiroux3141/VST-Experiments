"""The moving head (docs/TAPE_PARTICLES.md, "The moving head"): Sound Talk No. 21's bias
curves at 1 and 15 kHz from the particles fitted to the static data (the bench's `none`
variant: SW particles, the switching distribution fitted to No. 20 + Hc), on the Preisach
medium's geometry, against SCOTCH111@3's Preisach medium in the same configuration. Each
model then gets No. 21's one bias scale (scripts/tape_switching_study.py's protocol).

Configurations: `nodemag` (no coating field: every cell independent; the Preisach medium's
`demag_iterations=0`), `local` (each cell's own perpendicular demagnetization, -Ms M_y,
from the step before: the long-wavelength limit of the coating's field, which a 3D-random
coating can't do without), `demag` (the medium's demagnetization fixed point, Anderson: it
doesn't converge with particles, see the doc), `causal` (the coating's field from the
present pattern, every cell in absolute time: `strip.tone_coupled`, the medium's wavelength
cut) and `causal_full` (the same from the whole pattern).

    uv run --extra fast python scripts/tape_particle_no21.py [--configs nodemag demag]
        [--n 512] [--points 16] [--parts particles preisach plot]
-> reports/tape/particles/no21.{json,png}
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time

import numpy as np

from varimu.config import REPO_ROOT
from varimu.devices import library
from varimu.devices.tape_machine import TapeMachineSpec, tone_harmonics
from varimu.tape_particles import bench as bn
from varimu.tape_particles import no21
from varimu.tape_particles import strip as sp

OUT = REPO_ROOT / "reports" / "tape" / "particles"
HC_REF = 19981.835714600664  # SCOTCH111@3's hc median (the switching study's bias grid unit)
LOW = 0.05 * HC_REF  # the switching study's small signal (deep-gap peak, A/m)


def biases(points: int) -> np.ndarray:
    return np.geomspace(0.3 * HC_REF, 6.0 * HC_REF, points)


def particle_spec() -> bn.BenchSpec:
    f = json.loads((OUT / "bench_none.json").read_text())["fit"]["none"]
    return bn.BenchSpec(interactions="none", hk_median_a_m=f["hk_median_a_m"],
                        sigma_ln_hk=f["sigma_ln_hk"])


def numerics(config: str, f_hz: float) -> sp.Numerics:
    if config == "nodemag":
        # Cells are independent: one wavelength, no guards.
        return sp.Numerics(demag_iterations=0, guard_waves=0, read_waves=1)
    if config == "local":
        # Each cell's own perpendicular demagnetization only: still independent.
        return sp.Numerics(demag_iterations=0, guard_waves=0, read_waves=1, local_demag=True)
    if f_hz < 5e3:
        return sp.Numerics(guard_waves=1, read_waves=1)
    return sp.Numerics()


def run_particles(config, n, points, log, seed=1, m=16, seeds=None, **num_kw):
    """The particles' curves; with `seeds`, each a different particle sample (cells of other
    particles, as along a real tape), the complex fundamentals averaged."""
    spec = particle_spec()
    mach = sp.Machine()
    seeds = list(seeds) if seeds else [seed]
    samples = [sp.sample(spec, n, seed=sd) for sd in seeds]
    out = {"spec": dataclasses.asdict(spec) | {"sources": None}, "n": n, "seeds": seeds}
    for f in (1e3, 15e3):
        num = dataclasses.replace(numerics(config, f), steps_per_cycle=m, **num_kw)
        amps, per_seed, infos = [], [], []
        for b in biases(points):
            t0 = time.time()
            rs = []
            for parts in samples:
                if config.startswith("causal"):
                    lm = "none" if config == "causal_full" else "medium"
                    r, info = sp.tone_coupled(spec, parts, mach, num, f, LOW, b, lam_min=lm)
                else:
                    r, info = sp.tone(spec, parts, mach, num, f, LOW, b)
                rs.append(r)
            r = complex(np.mean(rs))
            amps.append(abs(r))
            per_seed.append([[x.real, x.imag] for x in rs])
            infos.append({"seconds": time.time() - t0, "steps": info["steps"],
                          "demag_changes": info.get("demag_changes")})
            log(f"  particles {config} {f:g} Hz bias {b / HC_REF:.2f} Hc: {20 * math.log10(abs(r)):.2f} dB ({time.time() - t0:.0f} s)")
        out[f"{f:g}"] = {"amp": amps, "db": (20 * np.log10(amps)).tolist(), "runs": infos,
                         "per_seed": per_seed}
    out["no21"] = no21.fit(biases(points), out["1000"]["db"], out["15000"]["db"])
    # The seed-to-seed spread of the fit: each sample's curves fitted on their own.
    if len(seeds) > 1:
        fits = []
        for k in range(len(seeds)):
            c1 = [20 * math.log10(abs(complex(*x[k]))) for x in out["1000"]["per_seed"]]
            c15 = [20 * math.log10(abs(complex(*x[k]))) for x in out["15000"]["per_seed"]]
            fits.append(no21.fit(biases(points), c1, c15))
        out["no21_per_seed"] = fits
    return out


def run_preisach(config, points, log):
    spec = TapeMachineSpec(speed_m_s=0.381, f_bias_hz=70e3, rec_gap_m=51e-6, flutter=False,
                           ds_m=0.381 / 70e3 / 7.62)
    if config == "nodemag":
        spec = dataclasses.replace(spec, demag_iterations=0)
    tape = library.load_tape("SCOTCH111@3")
    out = {}
    for f in (1e3, 15e3):
        amps = []
        for b in biases(points):
            t0 = time.time()
            amps.append(abs(tone_harmonics(spec, tape, f, LOW, b, harmonics=1)[0]))
            log(f"  preisach {config} {f:g} Hz bias {b / HC_REF:.2f} Hc: {20 * math.log10(amps[-1]):.2f} dB ({time.time() - t0:.0f} s)")
        out[f"{f:g}"] = {"amp": amps, "db": (20 * np.log10(amps)).tolist()}
    out["no21"] = no21.fit(biases(points), out["1000"]["db"], out["15000"]["db"])
    return out


def plot(res):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 3, figsize=(17, 4.8))
    styles = {"particles": "-o", "preisach": "--s"}
    for key, r in res.items():
        if not isinstance(r, dict) or "no21" not in r:
            continue
        model, config = key.split("/")
        f = r["no21"]
        lab = f"{model}, {config} (rms {f['rms_db_1k']:.2f} / {f.get('rms_db_15k', float('nan')):.2f} dB)"
        ax[0].plot(no21.NO21_MA, f["model_1k_db"], styles[model], ms=3, label=lab)
        ax[1].plot(no21.NO21_MA, f["model_15k_db"], styles[model], ms=3, label=lab)
        ax[2].plot(no21.NO21_MA, f["diff_15k_1k_db"], styles[model], ms=3, label=lab)
    if "preisach_full" in res:
        f = res["preisach_full"]
        for i, k in enumerate(("model_1k_db", "model_15k_db", "diff_15k_1k_db")):
            ax[i].plot(no21.NO21_MA, f[k], ":", color="gray", label="Preisach medium, demag + image (switching study)")
    ax[0].plot(no21.NO21_MA, no21.NO21_1K, "ks-", lw=2, label="No. 21")
    ax[1].plot(no21.NO21_MA, no21.NO21_15K, "ks-", lw=2, label="No. 21")
    d = (no21.NO21_15K - no21.NO21_1K) - (no21.NO21_15K[0] - no21.NO21_1K[0])
    ax[2].plot(no21.NO21_MA, d, "ks-", lw=2, label="No. 21")
    for a, t in zip(ax, ("1 kHz", "15 kHz", "15k - 1k (re 2 mA)"), strict=True):
        a.set(xlabel="bias (mA; each model's scale fitted)", ylabel="dB", title=f"No. 21, {t}")
        a.grid(alpha=0.3)
        a.legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(OUT / "no21.png", dpi=110)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--configs", nargs="+", default=["nodemag"])
    ap.add_argument("--parts", nargs="+", default=["particles", "preisach", "plot"])
    ap.add_argument("--n", type=int, default=512)
    ap.add_argument("--points", type=int, default=16)
    ap.add_argument("--m", type=int, default=16)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seeds", type=int, nargs="+", default=None)
    ap.add_argument("--tag", default="")
    ap.add_argument("--floor-oe", type=float, default=None)
    ap.add_argument("--layers", type=int, default=None)
    a = ap.parse_args()
    path = OUT / "no21.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    sw = json.loads((REPO_ROOT / "reports" / "tape" / "switching_study.json").read_text())
    res["preisach_full"] = {k: v for k, v in sw["base"]["no21"].items()}

    def log(s):
        print(s, flush=True)

    for c in a.configs:
        if "particles" in a.parts:
            kw = {k: v for k, v in (("floor_a_m", a.floor_oe and a.floor_oe * bn.OE), ("layers", a.layers)) if v}
            res[f"particles/{c}{a.tag}"] = run_particles(c, a.n, a.points, log, a.seed, a.m, a.seeds, **kw)
            path.write_text(json.dumps(res, indent=1, default=float))
            log(json.dumps({k: v for k, v in res[f"particles/{c}{a.tag}"]["no21"].items()}, default=float)[:900])
        if "preisach" in a.parts:
            res[f"preisach/{c}"] = run_preisach(c, a.points, log)
            path.write_text(json.dumps(res, indent=1, default=float))
            log(json.dumps({k: v for k, v in res[f"preisach/{c}"]["no21"].items()}, default=float)[:900])
    if "plot" in a.parts:
        plot(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The decisive bench (docs/TAPE_PARTICLES.md, "The bench"): does a box of interacting
Stoner-Wohlfarth needles, fitted to the same static data as the Preisach model (Sound Talk
No. 20's remanence curve and Eilers' Hc), record over a wider range of bias than the
Preisach model does? No. 21 needs ~3 dB more width in bias than the Preisach medium gives.

Parts:
- `fit`: each variant's switching distribution (H_K median, log spread) fitted to No. 20 +
  Hc on the bench, at the meter's 60 Hz (the GPU; -> reports/tape/particles/bench_fit.json);
- `curves`: a "0-D No. 21": every particle in the box sees the field a particle at depth y
  of the coating sees as it passes the Ampex 300's 51 um record gap at 15 ips with a 70 kHz
  bias (Hx and Hy of `varimu.devices.tape.head_field`, deep-gap Hg(t) = s + B sin), a small
  DC signal s (the long-wavelength limit), the remanence after the pass read along the tape
  over the coating's depths, against B; ± s on the same particles and seeds; the same
  histories through SCOTCH111@3's vector Preisach (with the perpendicular demagnetization
  N_y = 1 applied self-consistently, as the bench's sample_demag does);
- `plot`.

Variants: `dynamic` (the physics: every step's interaction field from every particle's
state), `frozen` (the erased state's interaction field held: a static interaction per
particle, the Preisach picture), `none` (no interactions). Each is fitted to the static data
on its own.

    uv run --extra fast python scripts/tape_particle_bench.py [--parts fit curves plot]
        [--variants dynamic frozen none] [--n 2000]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time

import numpy as np

from varimu.config import REPO_ROOT
from varimu.devices import library
from varimu.devices.tape import HeadGeometry, Orientation, head_field
from varimu.tape_particles import bench as bn
from varimu.tape_particles import runner
from varimu.tape_particles import static as st

OUT = REPO_ROOT / "reports" / "tape" / "particles"
OE = bn.OE
DATA = REPO_ROOT / "data" / "datasheets" / "scotch_111_remanence.csv"
HC_EILERS = 21486.0  # A/m, 270 Oe (Eilers' table, published_points.yaml SCOTCH111)
SIGMA_PHI = 0.01e-8 / 6.35e-3  # Bulletin 20's reading error (Wb/m)
METER_M = 32  # steps per 60 Hz cycle (remanence); HC_M for the coercivity loop
HC_M = 160

# The Ampex 300 of No. 21 (scripts/tape_switching_study.py's no21_spec: 15 ips, 70 kHz,
# 51 um record gap; the poles and spacing are TapeMachineSpec's defaults).
SPEED = 0.381
F_BIAS = 70e3
HEAD = HeadGeometry(51e-6, 3e-3, 3e-3)
SPACING = 0.5e-6
COATING = 12.7e-6
NO21_MA = np.arange(2.0, 9.0)
NO21_1K = np.array([-20.4, -11.0, -4.0, -0.6, 0.0, -0.8, -3.3])
NO21_15K = np.array([-13.8, -6.6, -2.0, 0.0, -1.7, -4.1, -7.1])


#: Not fitted: the interactions at 0.6 of their physical strength, H_K and its spread from the
#: exploration grid's best point there (No. 20 rms 4.4 reading errors, Hc 251 Oe): would strong
#: dynamic interactions widen the bias curves?
STRONG = {"hk_median_a_m": 900.0 * OE, "sigma_ln_hk": 0.2, "interaction_scale": 0.6}


def spec_of(variant: str, **kw) -> bn.BenchSpec:
    base = "dynamic" if variant == "dynamic_strong" else variant
    return bn.BenchSpec(interactions=base, **kw)


# --- The static fit -------------------------------------------------------------------


def erased(box, spec, seed, gpu=True):
    """The AC-erased state (the frozen variant's is erased with its interactions live: the
    field it then holds is the erased state's)."""
    es = spec.with_(interactions="dynamic") if spec.interactions == "frozen" else spec
    return runner.erase(box, es, seed=seed, gpu=gpu)


def static_curves(box, spec, gpu=True, seed=1):
    d = np.loadtxt(DATA, delimiter=",", skiprows=1)
    p0 = erased(box, spec, seed, gpu)
    hp = np.r_[d[:, 0], 2000.0 * OE]
    h = st.loop_history(hp, METER_M, 2.0, "remanence")
    # Each loop and its mirror (-H) on the same erased state: half their difference is the
    # remanence without the finite box's erased residual (the particles a loop never
    # switched are in the same state in both).
    happ = np.zeros((h.shape[0], 2 * h.shape[1], 3))
    happ[:, : h.shape[1], 0] = h
    happ[:, h.shape[1] :, 0] = -h
    fin, _, _ = runner.bench_run(box, spec, happ, 1 / (60 * METER_M), seed=seed, gpu=gpu, p0=p0)
    r = 0.5 * (fin[: h.shape[1], 0] - fin[h.shape[1] :, 0])
    rem = r[:-1] / r[-1]
    fin = r[:, None]
    hh = st.loop_history(np.array([1000.0 * OE]), HC_M, 1.0, "descending")
    happ = np.zeros((len(hh), 1, 3))
    happ[:, 0, 0] = hh[:, 0]
    _, tr, _ = runner.bench_run(
        box, spec, happ, 1 / (60 * HC_M), seed=seed, gpu=gpu, trace=True, p0=p0
    )
    i0 = HC_M + HC_M // 4
    hb, mb = hh[i0 - 1 :, 0], tr[i0 - 1 :, 0, 0]
    j = int(np.argmax(mb <= 0.0))
    hc = float("nan")
    if j > 0:
        f = mb[j - 1] / (mb[j - 1] - mb[j])
        hc = float(-(hb[j - 1] + f * (hb[j] - hb[j - 1])))
    return d, rem, fin[-1, 0], hc, (hb, mb)


def fit_variant(variant: str, n: int, seed: int, log, fit_scale: bool = True) -> dict:
    """The switching distribution (H_K median, log spread) and, with interactions, their
    strength (`interaction_scale`: the interactions' share of the physical p Ms_p; the
    research's packing is uncertain by 0.28-0.40 and the period Ms_p by 56-74 emu/g) fitted
    to No. 20 + Hc."""
    from scipy.optimize import minimize

    spec0 = spec_of(variant)
    box0 = bn.make_box(spec0, n, seed=seed)
    d = np.loadtxt(DATA, delimiter=",", skiprows=1)
    top = d[:, 1].max()
    cache = {}
    scaled = fit_scale and variant != "none"

    def unpack(x):
        return float(np.exp(x[0])), float(abs(x[1])), float(abs(x[2])) if scaled else 1.0

    def cost(x):
        key = tuple(np.round(x, 5))
        if key in cache:
            return cache[key][0]
        hk, sg, sc = unpack(x)
        spec = spec0.with_(hk_median_a_m=hk, sigma_ln_hk=sg, interaction_scale=sc)
        box = bn.retune(box0, spec, seed=seed)
        _, rem, sat, hc, _ = static_curves(box, spec, seed=seed)
        r = np.r_[(rem * top - d[:, 1]) / SIGMA_PHI, (hc - HC_EILERS) / (0.1 * HC_EILERS)]
        c = float(np.sum(r**2)) if np.isfinite(hc) else 1e9
        cache[key] = (c, rem, sat, hc)
        log(f"  {variant}: hk {hk / OE:7.1f} Oe sigma {sg:.3f} scale {sc:.3f} -> cost {c:9.1f}"
            f" Hc {hc / OE:6.1f} Oe")
        return c

    best = None
    grid = [(h, sg, sc) for h in (500.0, 700.0, 1000.0) for sg in (0.1, 0.25)
            for sc in ((0.15, 0.4) if scaled else (1.0,))]
    for h, sg, sc in grid:
        x = np.array([math.log(h * OE), sg] + ([sc] if scaled else []))
        c = cost(x)
        if best is None or c < best[0]:
            best = (c, x)
    x0 = best[1]
    steps = [0.12, 0.06] + ([0.08] if scaled else [])
    simplex = [x0] + [x0 + np.eye(len(x0))[i] * steps[i] for i in range(len(x0))]
    r = minimize(cost, x0, method="Nelder-Mead",
                 options={"xatol": 0.004, "fatol": 0.5, "maxfev": 70, "initial_simplex": simplex})
    x = r.x
    c, rem, sat, hc = cache[tuple(np.round(x, 5))]
    hk, sg, sc = unpack(x)
    return {
        "variant": variant,
        "n": n,
        "seed": seed,
        "hk_median_a_m": hk,
        "hk_median_oe": hk / OE,
        "sigma_ln_hk": sg,
        "interaction_scale": sc,
        "cost": c,
        "rms_reading_errors": float(math.sqrt(np.mean(((rem * top - d[:, 1]) / SIGMA_PHI) ** 2))),
        "hc_a_m": hc,
        "hc_oe": hc / OE,
        "saturation_remanence": float(sat),
        "remanence_model": (rem * top).tolist(),
        "remanence_data": d[:, 1].tolist(),
        "h_peak_a_m": d[:, 0].tolist(),
        "evaluations": len(cache),
    }


# --- The 0-D bias curves ----------------------------------------------------------------


def depths(k: int = 3) -> np.ndarray:
    return (np.arange(k) + 0.5) * COATING / k


def head_trace(y_m: float, floor_a_m: float, peak_a_m: float, m: int):
    """(times, Hx / Hg, Hy / Hg) for a particle at depth y passing the gap, sampled m times per
    bias cycle, over where the head's field reaches floor at the peak deep-gap field."""
    x = np.linspace(-3e-3, 3e-3, 600001)
    hx, hy = head_field(HEAD, x, np.full_like(x, SPACING + y_m))
    on = np.hypot(hx, hy) * peak_a_m >= floor_a_m
    x0, x1 = x[on].min(), x[on].max()
    t = np.arange(int((x1 - x0) / SPEED * F_BIAS * m) + 1) / (F_BIAS * m)
    xs = x0 + SPEED * t
    fx, fy = head_field(HEAD, xs, np.full_like(xs, SPACING + y_m))
    return t, fx, fy


def histories(biases, s_a_m, ys, m, floor):
    """steps x reps x 3, reps ordered (bias, depth, sign); zero-padded to the longest."""
    hs = []
    for b in biases:
        for y in ys:
            t, fx, fy = head_trace(y, floor, b + s_a_m, m)
            for sg in (1.0, -1.0):
                hg = sg * s_a_m + b * np.sin(2 * math.pi * F_BIAS * t)
                hs.append(np.stack([hg * fx, hg * fy, np.zeros_like(t)], axis=1))
    steps = max(len(h) for h in hs)
    out = np.zeros((steps, len(hs), 3))
    for k, h in enumerate(hs):
        out[: len(h), k] = h
    return out


def depth_weights(ys) -> np.ndarray:
    """The 1 kHz (381 um) read's e^{-k(d + y)}, normalized."""
    k = 2 * math.pi / (SPEED / 1e3)
    w = np.exp(-k * (SPACING + ys))
    return w / w.sum()


def bench_curve(box, spec, biases, s_a_m, ys, m, floor, seeds, gpu=True, log=print):
    """Per bias: the read remanence (M_x and M_y antithetic halves, depth-weighted, mean over
    seeds) and its seed-to-seed standard error."""
    h = histories(biases, s_a_m, ys, m, floor)
    w = depth_weights(ys)
    per_seed = []
    for sd in seeds:
        t0 = time.time()
        p0 = erased(box, spec, sd, gpu)
        fin, _, info = runner.bench_run(box, spec, h, 1 / (F_BIAS * m), seed=sd, gpu=gpu, p0=p0)
        f = fin.reshape(len(biases), len(ys), 2, 3)
        rec = 0.5 * (f[:, :, 0] - f[:, :, 1])  # bias x depth x 3
        per_seed.append(np.einsum("bdc,d->bc", rec, w))
        log(f"    seed {sd}: {h.shape[0]} steps x {h.shape[1]} reps, {time.time() - t0:.0f} s")
    a = np.array(per_seed)  # seeds x bias x 3
    return a.mean(axis=0), a.std(axis=0, ddof=1) / math.sqrt(len(seeds)) if len(seeds) > 1 else None


def preisach_curve(biases, s_a_m, ys, m, floor, tape=None, demag_iters=12):
    """The same histories through SCOTCH111@3's vector Preisach, M_y's perpendicular
    demagnetization (N_y = 1, Ms of the coating) applied self-consistently."""
    tape = tape or library.load_tape("SCOTCH111@3")
    pre = tape.ensemble()
    cs, sn, wt = tape.orientation.axes()
    out = np.zeros((len(biases), 3))
    w = depth_weights(ys)
    for bi, b in enumerate(biases):
        for di, y in enumerate(ys):
            t, fx, fy = head_trace(y, floor, b + s_a_m, m)
            res = []
            for sg in (1.0, -1.0):
                hg = sg * s_a_m + b * np.sin(2 * math.pi * F_BIAS * t)
                hx, hy = hg * fx, hg * fy
                my = 0.0
                for _ in range(demag_iters):
                    hye = hy - tape.ms_a_m * my
                    mx_new = my_new = 0.0
                    for c, s_, ww in zip(cs, sn, wt, strict=True):
                        hist = np.r_[c * hx + s_ * hye, -s_ * tape.ms_a_m * my][None, :]
                        mm = float(pre.state_after(hist)[0])
                        mx_new += ww * c * mm
                        my_new += ww * s_ * mm
                    if abs(my_new - my) < 1e-6:
                        my = my_new
                        break
                    my = 0.5 * (my + my_new)
                res.append((mx_new, my_new))
            out[bi, 0] += w[di] * 0.5 * (res[0][0] - res[1][0])
            out[bi, 1] += w[di] * 0.5 * (res[0][1] - res[1][1])
    return out


# --- The anhysteretic remanence (the recording's transfer curve) -------------------------

ARM_DC_OE = np.array([2.0, 5.0, 10.0, 20.0, 40.0, 70.0, 110.0, 160.0, 230.0, 320.0])


def arm_history(dc_a_m, ac_a_m=1500.0 * OE, cycles=40, m=16):
    """steps x len(dc): a 70 kHz AC field along the tape decaying linearly to 0 over
    `cycles`, a steady dc_a_m on it, then (2 steps) the dc removed."""
    k = np.arange(1, cycles * m + 1)
    ac = ac_a_m * (1 - k / len(k)) * np.sin(2 * math.pi * k / m)
    h = ac[:, None] + np.asarray(dc_a_m, float)[None, :]
    return np.vstack([h, np.zeros((2, h.shape[1]))])


def bench_arm(box, spec, seeds, m=16, gpu=True, log=print):
    dc = np.r_[ARM_DC_OE, -ARM_DC_OE] * OE
    h = arm_history(dc, m=m)
    happ = np.zeros((h.shape[0], h.shape[1], 3))
    happ[:, :, 0] = h
    out = []
    for sd in seeds:
        p0 = erased(box, spec, sd, gpu)
        fin, _, _ = runner.bench_run(box, spec, happ, 1 / (F_BIAS * m), seed=sd, gpu=gpu, p0=p0)
        k = len(ARM_DC_OE)
        out.append(0.5 * (fin[:k, 0] - fin[k:, 0]))
    a = np.array(out)
    return a.mean(axis=0), (a.std(axis=0, ddof=1) / math.sqrt(len(seeds)) if len(seeds) > 1 else None)


def preisach_arm(tape=None, m=16):
    tape = tape or library.load_tape("SCOTCH111@3")
    pre = tape.ensemble()
    cs, _, wt = tape.orientation.axes()
    dc = ARM_DC_OE * OE
    h = arm_history(np.r_[dc, -dc], m=m).T  # histories x steps
    mx = sum(w * c * pre.state_after(c * h) for c, w in zip(cs, wt, strict=True))
    k = len(dc)
    return 0.5 * (mx[:k] - mx[k:])


def knee_db(dc_a_m, arm) -> float | None:
    """The 3% THD level over the 1% level of a sine through the odd transfer curve arm(dc)
    (the switching study's `erf_level`, on this curve)."""
    x = np.r_[-dc_a_m[::-1], 0.0, dc_a_m]
    y = np.r_[-arm[::-1], 0.0, arm]
    th = np.linspace(0, 2 * math.pi, 4096, endpoint=False)

    def thd(a):
        sp_ = np.abs(np.fft.rfft(np.interp(a * np.sin(th), x, y)))
        return float(np.hypot(sp_[3], sp_[5]) / sp_[1])

    def level(target):
        lo, hi = dc_a_m[0], dc_a_m[-1]
        if thd(hi) < target:
            return None
        for _ in range(50):
            mid = math.sqrt(lo * hi)
            lo, hi = (mid, hi) if thd(mid) < target else (lo, mid)
        return math.sqrt(lo * hi)

    a1, a3 = level(0.01), level(0.03)
    return None if a1 is None or a3 is None else 20 * math.log10(a3 / a1)


def width_numbers(biases, amp) -> dict:
    """Peak position and the rise / fall widths (dB of bias) of a bias curve amp(B)."""
    db = 20 * np.log10(np.maximum(np.abs(amp), 1e-12))
    lb = 20 * np.log10(biases)
    fine = np.linspace(lb[0], lb[-1], 4000)
    c = np.interp(fine, lb, db)
    k = int(np.argmax(c))
    out = {"peak_bias_db": float(fine[k]), "peak_db": float(c[k])}
    for drop in (3.0, 10.0, 20.0):
        below = np.where(c[:k] <= c[k] - drop)[0]
        out[f"rise_{drop:g}db"] = float(fine[k] - fine[below[-1]]) if len(below) else None
        above = np.where(c[k:] <= c[k] - drop)[0]
        out[f"fall_{drop:g}db"] = float(fine[k + above[0]] - fine[k]) if len(above) else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--parts", nargs="+", default=["fit", "curves", "plot"])
    ap.add_argument("--variants", nargs="+", default=["dynamic", "frozen", "none"])
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--m", type=int, default=16, help="steps per bias cycle")
    ap.add_argument("--signal-oe", type=float, default=20.0)
    ap.add_argument("--floor-oe", type=float, default=60.0)
    ap.add_argument("--points", type=int, default=16)
    ap.add_argument("--depths", type=int, default=3)
    ap.add_argument("--out", default="bench.json")
    ap.add_argument("--cpu", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / a.out
    res = json.loads(path.read_text()) if path.exists() else {}

    def log(msg):
        print(msg, flush=True)

    def save():
        path.write_text(json.dumps(res, indent=1, default=float))

    if "fit" in a.parts:
        for v in a.variants:
            t0 = time.time()
            log(f"fit {v} (N {a.n})")
            res.setdefault("fit", {})[v] = fit_variant(v, a.n, a.seed, log)
            res["fit"][v]["seconds"] = time.time() - t0
            f = res["fit"][v]
            log(f"fit {v}: hk {f['hk_median_oe']:.1f} Oe, sigma {f['sigma_ln_hk']:.3f}, scale "
                f"{f['interaction_scale']:.3f}, rms "
                f"{f['rms_reading_errors']:.2f} reading errors, Hc {f['hc_oe']:.1f} Oe ({time.time() - t0:.0f} s)")
            save()
    if "curves" in a.parts:
        biases = np.geomspace(150.0, 2500.0, a.points) * OE
        ys = depths(a.depths)
        s = a.signal_oe * OE
        floor = a.floor_oe * OE
        cur = res.setdefault("curves", {})
        cur["bias_a_m"] = biases.tolist()
        cur["settings"] = {"m": a.m, "signal_oe": a.signal_oe, "floor_oe": a.floor_oe,
                           "depths": a.depths, "n": a.n, "seeds": a.seeds}
        t0 = time.time()
        # (always recomputed: ~1 min on the CPU)
        pc = preisach_curve(biases, s, ys, a.m, floor)
        cur["preisach_m"] = pc.tolist()
        cur["preisach"] = {"m": pc.tolist(), **width_numbers(biases, pc[:, 0])}
        log(f"preisach ({time.time() - t0:.0f} s): {json.dumps(width_numbers(biases, pc[:, 0]))}")
        save()
        for v in a.variants:
            f = STRONG if v == "dynamic_strong" else res["fit"][v]
            spec = spec_of(v, hk_median_a_m=f["hk_median_a_m"], sigma_ln_hk=f["sigma_ln_hk"],
                           interaction_scale=f.get("interaction_scale", 1.0))
            box = bn.make_box(spec, a.n, seed=a.seed)
            t0 = time.time()
            mean, se = bench_curve(box, spec, biases, s, ys, a.m, floor,
                                   seeds=list(range(1, a.seeds + 1)), gpu=not a.cpu, log=log)
            cur[v] = {"m": mean.tolist(), "se": None if se is None else se.tolist(),
                      "seconds": time.time() - t0, **width_numbers(biases, mean[:, 0])}
            log(f"{v} ({time.time() - t0:.0f} s): {json.dumps(width_numbers(biases, mean[:, 0]))}")
            save()
    if "arm" in a.parts:
        arm = res.setdefault("arm", {"dc_a_m": (ARM_DC_OE * OE).tolist()})
        pa = preisach_arm()
        arm["preisach"] = {"m": pa.tolist(), "knee_db": knee_db(ARM_DC_OE * OE, pa)}
        log(f"preisach ARM: {np.round(pa, 4)} knee {arm['preisach']['knee_db']}")
        for v in a.variants:
            f = STRONG if v == "dynamic_strong" else res["fit"][v]
            spec = spec_of(v, hk_median_a_m=f["hk_median_a_m"], sigma_ln_hk=f["sigma_ln_hk"],
                           interaction_scale=f.get("interaction_scale", 1.0))
            box = bn.make_box(spec, a.n, seed=a.seed)
            mean, se = bench_arm(box, spec, list(range(1, a.seeds + 1)), gpu=not a.cpu, log=log)
            arm[v] = {"m": mean.tolist(), "se": None if se is None else se.tolist(),
                      "knee_db": knee_db(ARM_DC_OE * OE, mean)}
            log(f"{v} ARM: {np.round(mean, 4)} knee {arm[v]['knee_db']}")
            save()
    if "plot" in a.parts:
        plot(res)
    return 0


def plot(res: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 3, figsize=(17, 4.8))
    fits = res.get("fit", {})
    for v, f in fits.items():
        hp = np.array(f["h_peak_a_m"]) / OE
        if v == next(iter(fits)):
            ax[0].plot(hp, np.array(f["remanence_data"]) / 1.575e-6, "ks", label="Sound Talk No. 20 (#111)")
        ax[0].plot(hp, np.array(f["remanence_model"]) / 1.575e-6, "o-", ms=3,
                   label=f"{v}: Hk {f['hk_median_oe']:.0f} Oe, s {f['sigma_ln_hk']:.2f}, Hc {f['hc_oe']:.0f}")
    ax[0].set(xlabel="peak field (Oe)", ylabel='remanent flux (lines per 1/4")',
              title="static fit (60 Hz meter)")
    cur = res.get("curves", {})
    if "bias_a_m" in cur:
        b = np.array(cur["bias_a_m"]) / OE
        for k in ("preisach", "dynamic", "frozen", "none"):
            if k not in cur:
                continue
            m = np.array(cur[k]["m"])[:, 0]
            db = 20 * np.log10(np.abs(m))
            lab = "SCOTCH111@3 Preisach" if k == "preisach" else f"particles, {k}"
            ax[1].semilogx(b, db - db.max(), "o-" if k != "preisach" else "k-", ms=3, label=lab)
            se = cur[k].get("se")
            if se is not None:
                e = 20 * np.log10(1 + 2 * np.abs(np.array(se)[:, 0]) / np.abs(m))
                ax[1].fill_between(b, db - db.max() - e, db - db.max() + e, alpha=0.2)
        ax[1].set(xlabel="peak deep-gap bias field (Oe)", ylabel="dB re peak", ylim=(-30, 2),
                  title="0-D bias curves: remanence along the tape after the pass")
        # No. 21's 1 kHz curve against the data's own bias, its peak placed on the Preisach's.
        if "preisach" in cur:
            pk = 10 ** (cur["preisach"]["peak_bias_db"] / 20) / OE
            ax[1].semilogx(pk * NO21_MA / 6.0, NO21_1K, "ks--", label="No. 21, 1 kHz (bias scaled: peak on the Preisach's)")
        rows = [k for k in ("preisach", "dynamic", "frozen", "none") if k in cur]
        keys = ["rise_10db", "rise_20db", "fall_3db"]
        x = np.arange(len(keys))
        for i, k in enumerate(rows):
            ax[2].bar(x + 0.2 * i, [cur[k].get(q) or 0 for q in keys], 0.2, label=k)
        # No. 21: 1 kHz rise 20.4 dB over 2 -> 6 mA (9.5 dB of bias), -11.0 at 3 mA (6.0 dB below).
        ax[2].plot([0.3], [20 * math.log10(6 / 3)], "k*", ms=12, label="No. 21: -11 dB at 6.0 dB below the peak")
        ax[2].set_xticks(x + 0.3, ["bias for -10 dB (rise)", "bias for -20 dB (rise)", "bias for -3 dB (over-bias)"])
        ax[2].set(ylabel="dB of bias from the peak", title="widths")
    for a_ in ax:
        a_.grid(alpha=0.3)
        a_.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "bench.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())

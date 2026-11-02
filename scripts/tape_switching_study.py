"""A study, not a fit (docs/TAPE_PLAN.md, "Gaps" 3): does frequency-dependent switching
(thermal activation, Sharrock's law) explain the three checks that say the tape's particles
switch too uniformly? Nothing in varimu/ changes: each variant is a Scotch 111 ensemble with
its switching fields mapped from Bulletin 20's 60 Hz loops to the bias's rate, run through
the medium as it stands (the Rust kernel).

**The mapping.** A particle with energy barrier K V (kappa = K V / kT) and athermal switching
field H0 switches, within a time t, at Hc(t) = H0 [1 - (L / kappa)^n], L = ln(f0 t / ln 2)
(Sharrock, J. Appl. Phys. 76, 6413 (1994); n = 1/2 for aligned Stoner-Wohlfarth particles,
~0.735 for random ones). Bulletin 20's ensemble is the 60 Hz one (L60); recording sets each
particle within a bias period (Lb < L60), so Hc_b = Hc_60 r(kappa), r = (1 - (Lb / kappa)^n)
/ (1 - (L60 / kappa)^n): harder, and by more for small barriers. Which variable is
independent of the barrier decides the spread:
- `hc60`: the 60 Hz switching field independent of kappa: ln Hc_b = ln Hc_60 + ln r, the
  spread widens by r's (the plan's hypothesis);
- `h0`: the athermal field independent of kappa (shape anisotropy from the aspect ratio, the
  barrier from the volume): part of the 60 Hz spread is thermal and shrinks at bias rates,
  so the spread narrows.
Monte Carlo over particles; the bias-rate ensemble is fitted as a lognormal (median, sigma
of ln) and replaces the tape's switching distribution while it records. The interaction
field (dipolar, static) is unchanged.

**Times** (provisional, model knowledge): t = 0.1 rad of the drive's cycle (the field within
~0.5% of its peak), f0 = 1e9 Hz; the 60 Hz meter's loop traced ~30 times (L60 = 16.3), a
cell at the bias's trailing edge sees ~1 peak near its last (the zone's field falls ~15% per
bias cycle at 15 ips): Lb = 5.8 at 70 kHz, 5.5 at 100 kHz.

**The barrier.** The noise fit's particle (1.62e-21 m^3, SCOTCH111@3) with coherent rotation,
K V = mu0 Ms_p H0 V / 2 (Ms_p of gamma-Fe2O3 ~360 kA/m: provisional, model knowledge, 74
emu/g at 4.9 g/cm^3; H0 ~ 1.1 Hc): kappa ~1950. Incoherent reversal switches a smaller
volume (an activation volume), so smaller kappa are run too; no gamma-Fe2O3 tape value was
found to cite.

**The checks** (each against the base SCOTCH111@3):
1. `no21`: Sound Talk No. 21's bias curves (Type B on an Ampex 300: 15 ips, 70 kHz, 0.002"
   record gap; read off the figure, TAPE_PLAN.md TM2 step 7), one bias scale (A/m per mA)
   and an offset per curve fitted.
2. `level`: the 3% THD level at 400 Hz over the 1% level (0 VU), the first print's machine
   at 15 ips aligned on the variant (the manual: 6 dB; the 351's profile +3.8 dB). Also the
   ideal anhysteretic's (erf of the interaction field) for comparison.
3. `b14`: Bulletin 14's permissible level at 7 kHz re 400 Hz, 7.5 ips (3M: +4 dB).
4. `diag`: not physical: the bias-rate spread set to 0.45 / 0.6, to see whether any
   switching spread can move the checks.

5. `level_diag`: the level check with the medium's mechanisms off one at a time (demag, the
   head's image, orientation) and with more bias cycles per freezing (the bias 4x faster,
   the record gap 51 um), to see what steepens the medium past the anhysteretic.

    uv run --extra fast python scripts/tape_switching_study.py [--parts mapping no21 level b14]
        [--variants base k150_hc60 ...]
    uv run --extra fast python scripts/tape_switching_study.py --parts level_diag \
        --out switching_level_diag.json
    uv run --extra fast python scripts/tape_switching_study.py --parts plot
-> reports/tape/switching_study.{json,png}, switching_level_diag.json (~45 min in all)
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
from varimu.devices.tape_machine import TapeMachineSpec, align, tone_harmonics

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import tape_bulletin14 as b14  # noqa: E402

OUT = REPO_ROOT / "reports" / "tape"
MU0 = 4e-7 * math.pi
KT_J = 1.380649e-23 * 293.0
F0_HZ = 1e9
W_RAD = 0.1
METER_LOOPS = 30
MS_PARTICLE_A_M = 3.6e5

# No. 21, Type B, dB re each curve's peak at 2..8 mA (TAPE_PLAN.md TM2 step 7, read off the
# figure; 15 kHz from its peak and the 15k - 1k differential).
NO21_MA = np.arange(2.0, 9.0)
NO21_1K = np.array([-20.4, -11.0, -4.0, -0.6, 0.0, -0.8, -3.3])
NO21_15K = np.array([-13.8, -6.6, -2.0, 0.0, -1.7, -4.1, -7.1])


def l_of(f_hz: float, cycles: float = 1.0) -> float:
    return math.log(F0_HZ * W_RAD / (2 * math.pi * f_hz) / math.log(2.0)) + math.log(cycles)


L60 = l_of(60.0, METER_LOOPS)


def kappa_noise_volume(tape) -> float:
    """K V / kT of the noise fit's particle, coherent rotation, H0 = 1.1 Hc median."""
    v = tape.noise.particle_volume_m3
    h0 = 1.1 * tape.preisach.hc_median_a_m
    return MU0 * MS_PARTICLE_A_M * h0 * v / (2.0 * KT_J)


def sharrock_map(
    hc_median: float,
    sigma_ln: float,
    kappa_median: float,
    sigma_ln_kappa: float,
    n: float,
    independent: str,
    f_bias_hz: float,
    particles: int = 400_000,
    seed: int = 1,
) -> dict:
    """The bias-rate ensemble's lognormal fit (see the module docs)."""
    rng = np.random.default_rng([seed, int(kappa_median), int(1000 * n)])
    lb = l_of(f_bias_hz)
    kap = kappa_median * np.exp(sigma_ln_kappa * rng.standard_normal(particles))

    def red(lv):
        return 1.0 - np.clip(lv / kap, 0.0, 1.0) ** n

    out = {"L60": L60, "Lb": lb}
    if independent == "hc60":
        hc60 = hc_median * np.exp(sigma_ln * rng.standard_normal(particles))
        ok = kap > L60
        hcb = hc60[ok] * red(lb)[ok] / red(L60)[ok]
    else:
        # ln H0 normal, its spread the 60 Hz spread less the thermal part's (both ~normal).
        th = np.log(np.clip(red(L60), 1e-12, None))
        var0 = sigma_ln**2 - float(np.var(th[kap > L60]))
        if var0 <= 0:
            return out | {"feasible": False, "thermal_sigma_60": float(np.std(th[kap > L60]))}
        z = rng.standard_normal(particles)
        mu = math.log(hc_median)
        for _ in range(30):  # the median of Hc_60 at the fitted one
            h0 = np.exp(mu + math.sqrt(var0) * z)
            hc60 = h0[kap > L60] * red(L60)[kap > L60]
            mu += math.log(hc_median) - float(np.median(np.log(hc60)))
        hcb = h0[kap > lb] * red(lb)[kap > lb]
        out["sigma60_check"] = float(np.std(np.log(hc60)))
        out["blocked_only_at_bias"] = float(np.mean((kap > lb) & (kap <= L60)))
    lh = np.log(hcb)
    out |= {
        "feasible": True,
        "hc_median_a_m": float(np.exp(np.median(lh))),
        "sigma_ln_hc": float(np.std(lh)),
        "r_median": float(np.exp(np.median(lh)) / hc_median),
        "skew": float(np.mean(((lh - lh.mean()) / lh.std()) ** 3)),
    }
    return out


def variants(tape) -> dict:
    k_noise = kappa_noise_volume(tape)
    return {
        "base": None,
        "coherent_hc60": dict(kappa=k_noise, sk=0.6, n=0.5, ind="hc60"),
        "k400_hc60": dict(kappa=400.0, sk=0.6, n=0.5, ind="hc60"),
        "k150_hc60": dict(kappa=150.0, sk=0.6, n=0.5, ind="hc60"),
        "k150_h0": dict(kappa=150.0, sk=0.6, n=0.5, ind="h0"),
        "k60_hc60_n735": dict(kappa=60.0, sk=0.6, n=0.735, ind="hc60"),
        "diag_sigma045": dict(sigma=0.45),
        "diag_sigma060": dict(sigma=0.60),
    }


def tape_at(tape, v, f_bias_hz: float):
    """(the tape with the variant's bias-rate ensemble, the mapping's numbers)."""
    p = tape.preisach
    if v is None:
        return tape, {}
    if "sigma" in v:
        info = {"hc_median_a_m": p.hc_median_a_m, "sigma_ln_hc": v["sigma"]}
    else:
        info = sharrock_map(
            p.hc_median_a_m, p.sigma_ln_hc, v["kappa"], v["sk"], v["n"], v["ind"], f_bias_hz
        )
        if not info["feasible"]:
            return None, info
    pre = dataclasses.replace(
        p, hc_median_a_m=info["hc_median_a_m"], sigma_ln_hc=info["sigma_ln_hc"]
    )
    return dataclasses.replace(tape, preisach=pre), info


# --- 1. No. 21 ----------------------------------------------------------------------------


def no21_spec() -> TapeMachineSpec:
    v, fb = 0.381, 70e3
    return TapeMachineSpec(
        speed_m_s=v, f_bias_hz=fb, rec_gap_m=51e-6, flutter=False, ds_m=v / fb / 7.62
    )


def no21(tape, hc_ref: float) -> dict:
    spec = no21_spec()
    biases = np.geomspace(0.25 * hc_ref, 8.0 * hc_ref, 30)
    low = 0.05 * hc_ref
    curves = {}
    for f in (1e3, 15e3):
        out = [abs(tone_harmonics(spec, tape, f, low, b, harmonics=1)[0]) for b in biases]
        curves[f] = 20 * np.log10(np.array(out))
    lb = np.log(biases)
    best = None
    for s in np.geomspace(0.1 * hc_ref, 1.0 * hc_ref, 500):  # A/m per mA
        x = np.log(s * NO21_MA)
        if x[0] < lb[0] or x[-1] > lb[-1]:
            continue
        r = []
        for f, data in ((1e3, NO21_1K), (15e3, NO21_15K)):
            m = np.interp(x, lb, curves[f])
            r.append(m - data - np.mean(m - data))
        cost = float(np.mean(np.concatenate(r) ** 2))
        if best is None or cost < best[0]:
            best = (cost, s, r)
    _, s, r = best
    x = np.log(s * NO21_MA)
    m1, m15 = (np.interp(x, lb, curves[f]) for f in (1e3, 15e3))
    m1, m15 = m1 - m1.max(), m15 - m15.max()
    diff = (m15 - m1) - (m15[0] - m1[0])
    fine = np.linspace(lb[0], lb[-1], 2000)

    def peak_ma(f):
        return float(math.exp(fine[np.argmax(np.interp(fine, lb, curves[f]))]) / s)

    return {
        "scale_a_m_per_ma": float(s),
        "scale_oe_per_ma": float(s / (1000 / (4 * math.pi))),
        "rms_db_1k": float(np.sqrt(np.mean(r[0] ** 2))),
        "rms_db_15k": float(np.sqrt(np.mean(r[1] ** 2))),
        "model_1k_db": m1.tolist(),
        "model_15k_db": m15.tolist(),
        "diff_15k_1k_db": diff.tolist(),
        "peak_ma_1k": peak_ma(1e3),
        "peak_ma_15k": peak_ma(15e3),
        "bias_a_m": biases.tolist(),
        "curve_1k_db": curves[1e3].tolist(),
        "curve_15k_db": curves[15e3].tolist(),
    }


# --- 2. The 3% level ----------------------------------------------------------------------


def thd_fn(spec, tape, hg_bias, low):
    f0 = 400.0
    lin = np.array(
        [
            abs(tone_harmonics(spec, tape, n * f0, low, hg_bias, harmonics=1)[0]) / low
            for n in (1, 2, 3)
        ]
    )

    def thd(a):
        h = np.abs(tone_harmonics(spec, tape, f0, a, hg_bias, harmonics=3)) / lin
        return float(np.hypot(h[1], h[2]) / h[0]), (h[1] / h[0], h[2] / h[0])

    return thd


def level_at(thd, target, lo, hi, steps=12):
    for _ in range(steps):
        mid = math.sqrt(lo * hi)
        lo, hi = (mid, hi) if thd(mid)[0] < target else (lo, mid)
    return math.sqrt(lo * hi)


#: What steepens the medium's saturation past the anhysteretic's (the level check only):
#: the medium's mechanisms switched off one at a time (not physical variants).
LEVEL_DIAG = {
    "no_demag": dict(spec=dict(demag_iterations=0)),
    "no_image": dict(spec=dict(head_image=False)),
    "aligned_kappa20": dict(kappa=20.0),
    # More bias cycles per freezing: the bias 4x faster (cells scaled with its wavelength),
    # or a longer record gap (a gentler trailing edge).
    "bias_400k": dict(spec=dict(f_bias_hz=400e3, ds_m=0.5e-6 / 4)),
    "rec_gap_51um": dict(spec=dict(rec_gap_m=51e-6)),
}


def level(tape, **spec_kw) -> dict:
    spec = TapeMachineSpec(flutter=False, **spec_kw)
    al = align(spec, tape)
    hc = tape.preisach.hc_median_a_m
    thd = thd_fn(spec, tape, al.hg_bias, 0.05 * hc)
    a1 = al.hg_0vu
    a3 = level_at(thd, 0.03, a1, 6.0 * a1)
    pts = {f"{d:+g}": thd(a1 * 10 ** (d / 20)) for d in (0.0, 3.0, 6.0)}
    return {
        "hg_bias_over_hc": al.hg_bias / hc,
        "hg_0vu_a_m": a1,
        "level_3pct_db": 20 * math.log10(a3 / a1),
        "thd_h2_h3": {k: [v[0], *v[1]] for k, v in pts.items()},
    }


def erf_level() -> dict:
    """The ideal anhysteretic, M = erf(h / (sqrt 2 sigma_Hi)) (the Preisach model's, for
    hysterons the bias reaches), and the oriented mixture: the 3% level over the 1%."""
    from scipy.special import erf

    th = np.linspace(0, 2 * math.pi, 4096, endpoint=False)
    tape = library.load_tape("SCOTCH111@3")
    cs, _, wt = tape.orientation.axes()

    def thd(a, oriented):
        x = a * np.sin(th)
        m = sum(w * c * erf(x * c) for c, w in zip(cs, wt, strict=True)) if oriented else erf(x)
        sp = np.abs(np.fft.rfft(m))
        return float(np.hypot(sp[3], sp[5]) / sp[1])  # odd: no even harmonics

    out = {}
    for oriented in (False, True):

        def f(a, oriented=oriented):
            return (thd(a, oriented), None)

        a1 = level_at(f, 0.01, 0.01, 5.0, 40)
        a3 = level_at(f, 0.03, 0.01, 5.0, 40)
        out["oriented" if oriented else "scalar"] = 20 * math.log10(a3 / a1)
    return out


# --- 3. Bulletin 14 -----------------------------------------------------------------------


def bulletin14(tape) -> dict:
    al = align(TapeMachineSpec(flutter=False), tape)
    hc = tape.preisach.hc_median_a_m
    spec = TapeMachineSpec(flutter=False).at_speed(7.5 * 0.0254)
    res = {}
    for f in (400.0, 7000.0):
        sw = b14.sweep(spec, tape, f, al.hg_bias, hc)
        res[f] = {t: b14.permissible(np.array(b14.LEVELS_OVER_HC), sw, t) for t in b14.CRITERIA_DB}
    return {f"{t:g}db": 20 * math.log10(res[7000.0][t] / res[400.0][t]) for t in b14.CRITERIA_DB}


def plot(res: dict) -> None:
    """No. 21's curves per variant against the bulletin, and the level / Bulletin 14 checks."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [k for k, v in res.items() if isinstance(v, dict) and "no21" in v]
    show = ("base", "k150_hc60", "k150_h0", "k60_hc60_n735", "diag_sigma045")
    fig, ax = plt.subplots(1, 4, figsize=(19, 4.6))
    for i, (key, data, f) in enumerate(
        (("model_1k_db", NO21_1K, "1 kHz"), ("model_15k_db", NO21_15K, "15 kHz"))
    ):
        ax[i].plot(NO21_MA, data, "ks-", lw=2, label="No. 21 (Type B)")
        for n in show:
            if n in res and "no21" in res[n]:
                ax[i].plot(NO21_MA, res[n]["no21"][key], "o-", ms=3, label=n)
        ax[i].set(xlabel="bias (mA; the model's scale fitted)", ylabel="dB re peak",
                  title=f"No. 21 at {f}, 15 ips")  # fmt: skip
        ax[i].legend(fontsize=7)
    x = np.arange(len(names))
    ax[2].bar(x, [res[n]["level"]["level_3pct_db"] for n in names])
    ax[2].axhline(6.0, color="k", ls="--", label="351 manual: 6 dB")
    ax[2].axhspan(4.1, 4.5, color="C2", alpha=0.3, label="Sound Talk No. 1 (output dB)")
    if "erf_level_db" in res:
        ax[2].axhline(res["erf_level_db"]["oriented"], color="C3", ls=":", label="ideal erf")
    ax[2].set(ylabel="dB", title="3% THD level over the 1% (400 Hz, 15 ips)")
    ax[3].bar(x - 0.2, [res[n]["b14"]["-40db"] for n in names], 0.4, label="-40 dB criterion")
    ax[3].bar(x + 0.2, [res[n]["b14"]["-30db"] for n in names], 0.4, label="-30 dB criterion")
    ax[3].axhline(4.0, color="k", ls="--", label="No. 14: +4 dB")
    ax[3].set(ylabel="dB", title="No. 14: permissible field at 7 kHz re 400 Hz (7.5 ips)")
    for a in ax[2:]:
        a.set_xticks(x, names, rotation=60, ha="right", fontsize=7)
        a.legend(fontsize=7)
    for a in ax:
        a.grid(alpha=0.3)
    fig.suptitle("Frequency-dependent switching (Sharrock) against the three checks")
    fig.tight_layout()
    fig.savefig(OUT / "switching_study.png", dpi=110)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--parts", nargs="+", default=["mapping", "no21", "level", "b14"])
    ap.add_argument("--variants", nargs="+")
    ap.add_argument("--tape", default="SCOTCH111@3")
    ap.add_argument("--out", default="switching_study.json")
    a = ap.parse_args()
    tape = library.load_tape(a.tape)
    hc_ref = tape.preisach.hc_median_a_m
    path = OUT / a.out
    res = json.loads(path.read_text()) if path.exists() else {}
    res["kappa_noise_volume"] = kappa_noise_volume(tape)
    res["L60"] = L60
    if "level" in a.parts:
        res["erf_level_db"] = erf_level()
        print("erf 3% over 1%:", res["erf_level_db"], flush=True)
    if "plot" in a.parts:
        plot(res)
        return 0
    if "level_diag" in a.parts:
        for name, d in LEVEL_DIAG.items():
            if name in res.get("level_diag", {}):
                continue
            tv = tape
            if "kappa" in d:
                tv = dataclasses.replace(
                    tape, orientation=dataclasses.replace(tape.orientation, kappa=d["kappa"])
                )
            res.setdefault("level_diag", {})[name] = level(tv, **d.get("spec", {}))
            print(f"level_diag {name}:", json.dumps(res["level_diag"][name])[:300], flush=True)
            path.write_text(json.dumps(res, indent=1, default=float))
        return 0
    vs = variants(tape)
    for name in a.variants or list(vs):
        v = vs[name]
        row = res.setdefault(name, {"spec": v})
        t0 = time.time()
        for part, fb in (("no21", 70e3), ("level", 100e3), ("b14", 100e3)):
            tv, info = tape_at(tape, v, fb)
            if "mapping" in a.parts:
                row[f"mapping_{fb / 1e3:g}k"] = info
            if tv is None:
                print(f"{name}: infeasible {info}", flush=True)
                break
            if part not in a.parts:
                continue
            if part == "no21":
                row[part] = no21(tv, hc_ref)
            elif part == "level":
                row[part] = level(tv)
            else:
                row[part] = bulletin14(tv)
            print(f"{name} {part} ({time.time() - t0:.0f} s):", flush=True)
            show = {k: x for k, x in row[part].items() if not isinstance(x, list)}
            print("   ", json.dumps(show, default=float)[:600], flush=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(res, indent=1, default=float))
        if "mapping" in a.parts:
            print(f"{name} mapping:", json.dumps(row.get("mapping_70k"), default=float), flush=True)
        path.write_text(json.dumps(res, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())

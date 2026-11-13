"""A study, not a fit (docs/TAPE_PLAN.md, "Over-bias options (2026-11-12, overnight study)"):
the cheap model terms that could widen Sound Talk No. 21's bias curves, each an opt-in
variant (varimu.tape_variants: nothing in varimu/devices changes, so no IR, render, cache
key or alignment moves), measured with the switching study's checks
(scripts/tape_switching_study.py), out of sample: no variant's parameter is fitted to No. 21.

Why: the vector Preisach medium's bias curves are narrower in bias than #111's (TM2 step 7):
they peak at lower bias, the 1 kHz rise is too steep (-5.5 against -11.0 dB at 3 mA), and
the 15k - 1k spread at over-bias reaches -6.4..-6.8 dB against -10.4. Sharrock switching
was closed (<= 0.4 dB). The candidates (the plan's untried list, the literature study
D:/Claude Code Projects/VST-chirp/docs/TAPE_PARTICLE_RESEARCH.md sections 2 and 5):

1. `moving_*`: the moving Preisach model (Della Torre), each hysteron in H + alpha Ms M, M the
   cell's own magnetization followed through every bias cycle (circuitsim's forward kernel).
   alpha > 0: magnetizing, what acicular coatings usually need (Cerchez, Stoleriu & Stancu,
   JOAM 5, 351 (2003): "usually positive" for acicular systems, from agglomeration; no
   gamma-Fe2O3 number found; the literature study's provisional 0.1-0.3 Hc, i.e. alpha Ms
   ~30-80 Oe, alpha ~0.03-0.09 on #111's Ms); alpha < 0: demagnetizing, as particulate
   gamma-Fe2O3's negative Henkel plots suggest. Vajda & Della Torre (IEEE Trans. Magn. 27,
   4757, 1991) found commercial gamma-Fe2O3 tapes follow the moving model. Every variant's
   ensemble is refitted to Bulletin 20 and Eilers' Hc with the mean field on (the B-H
   meter's loops followed with it): the fit's own residual is a constraint on alpha that
   No. 21 doesn't enter.
2. `static_*`: the same mean field frozen at the recorded remanence, inside the medium's
   demagnetization fixed point (the literature study's cheaper form; same refit).
3. `head_*`: the record head's field against current, from a magnetic circuit with
   mumetall's measured amplitude permeability, eddy-limited at 70 / 100 kHz, saturating at
   0.8 T (`tape_variants.HeadLaw`); the head's dimensions unprinted, so bounded: the core's
   reluctance ratio 250-1000 (l_c / g ~ 500, the throat), laminations 0.1-0.35 mm, the
   pole tips' flux concentration 1-3. Plus `stretch`: what power law Hg = s I^p would fit
   No. 21 on the base model's curves (a diagnostic, not a model: p is fitted to No. 21).
5. `astroid_*`: each axis driven by the Stoner-Wohlfarth astroid's equivalent field instead
   of the field's projection (`tape_variants.astroid_drive`; the particle bench's finding,
   docs/TAPE_PARTICLES.md on the `tape-particles` branch: the over-bias fall is switching
   in the head's rotating field), refitted to Bulletin 20 with the astroid in the loops;
   kappa 1.5 (the base's) and 3.
6. `exact*` (2026-11-12, second round): the record head's gap exact (Westmijze's head by
   its Schwarz-Christoffel map, `tape_variants.exact_head_field`; docs/TAPE_HEAD_RESEARCH.md
   1.3-1.6), in place of Karlqvist's linear ramp across the mouth: no free parameter, no
   refit (the head doesn't enter the static loops). `exact` on the base tape,
   `exact_astroid_k15` with the astroid's tape (its Bulletin 20 fit).
7. Step 3 of the second round: what TM2 tuned under the projection rule, re-derived with the
   astroid and the exact gap both in, No. 21 held out of every fit: the in-plane orientation
   (`exact_astroid_k*`, each refitted to Bulletin 20: its residual is the held-out
   discriminator), an out-of-plane share (`exact_astroid_o3d_*`: the Bingham axes of 4., the
   astroid on 3D axes, `tape_variants.astroid_drive`), and the head's image
   (`exact_astroid_k15_noimage`).
4. `o3d_*`: the easy axes in 3D (a Bingham density exp(kappa u_x^2 - lam u_y^2): lam > 0
   keeps them in the tape's plane, the coating's flow), refitted to Bulletin 20 and Hc. The
   base model spreads them in the head's x-y plane (kappa 1.5, fitted to No. 21 in TM2).

**The checks** (as the switching study's, its functions):
- `no21`: No. 21's bias curves (Type B, Ampex 300, 15 ips, 70 kHz, 0.051 mm record gap), one
  bias scale (A/m per mA) and an offset per curve fitted; rms per curve, the 1 kHz rise at
  3 mA (-11.0), the over-bias fall at 8 mA (1k -3.3, 15k -7.1, 15k - 1k -10.4), the peaks'
  positions in dB of bias against the data's.
- `level`: the 3% THD level over the 1% at 400 Hz, 15 ips (the first print's machine,
  aligned on the variant; 12.7 um record gap as in the switching study), and `level51` the
  same on the 351's 51 um gap (Sound Talk No. 1: ~4.1-4.5 dB of output, ~4.4-4.8 of input).
- `b14`: Bulletin 14's permissible level at 7 kHz re 400 Hz, 7.5 ips (3M: +4 dB).
- `cost`: one No. 21 recording (1 kHz at the base's peak bias) timed per variant, against
  the base, on the same thread count.

    uv run --extra fast python scripts/tape_overbias_study.py [--parts fit no21 level b14
        level51 cost] [--variants base moving_p06 ...] [--threads 6]
    uv run --extra fast python scripts/tape_overbias_study.py --parts plot
-> reports/tape/overbias_study.{json,png}
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import math
import sys
import time

import numpy as np

from varimu import tape_variants as tv
from varimu.config import REPO_ROOT
from varimu.devices import library, tape_fit
from varimu.devices.fit import load_csv
from varimu.devices.preisach import PreisachParams
from varimu.devices.tape import Orientation
from varimu.devices.tape_machine import tone_harmonics

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import tape_switching_study as sw  # noqa: E402

OUT = REPO_ROOT / "reports" / "tape"
NO21_MA = sw.NO21_MA
OE = 1000.0 / (4.0 * math.pi)


def variants() -> dict:
    """name -> what it changes (see the module docs)."""
    v: dict = {"base": {}}
    for a in (0.03, 0.06, 0.09):
        v[f"moving_p{round(100 * a):02d}"] = {"moving": a}
    for a in (-0.05, -0.10):
        v[f"moving_m{round(-100 * a):02d}"] = {"moving": a}
    v["static_p06"] = {"static": 0.06}
    v["static_m10"] = {"static": -0.10}
    # The head: (reluctance ratio, laminations, flux concentration at the tips).
    v["head_typical"] = {"head": (250.0, 0.1e-3, 1.0)}
    v["head_lossy"] = {"head": (1000.0, 0.35e-3, 3.0)}
    v["o3d_iso"] = {"o3d": (0.0, 0.0)}
    v["o3d_k15"] = {"o3d": (1.5, 0.0)}
    v["o3d_k15_plane"] = {"o3d": (1.5, 3.0)}
    v["o3d_k3_plane"] = {"o3d": (3.0, 3.0)}
    v["astroid_k15"] = {"astroid": 1.5}
    v["astroid_k3"] = {"astroid": 3.0}
    # The astroid without the head's image (the image carried the over-bias fall under the
    # projection rule: TM2 step 7): the pair the astroid upsets.
    v["astroid_k15_noimage"] = {"astroid": 1.5, "noimage": True}
    # The exact record gap (second round), alone and with the astroid.
    v["exact"] = {"exact_gap": True}
    v["exact_astroid_k15"] = {"astroid": 1.5, "exact_gap": True}
    # Step 3: TM2's choices re-derived with both in.
    for k in (0.5, 1.0, 2.0, 3.0, 5.0):
        v[f"exact_astroid_k{k:g}".replace(".", "")] = {"astroid": k, "exact_gap": True}
    # (0, 0) and (0.75, 0): the squareness #111's packing implies (S 0.53-0.57, nearly
    # unoriented: docs/TAPE_PARTICLE_RESEARCH.md 1.1), a prior No. 21 doesn't enter.
    for k, lam in ((0.0, 0.0), (0.75, 0.0), (1.5, 0.0), (1.5, 3.0), (3.0, 0.0), (3.0, 3.0)):
        name = f"exact_astroid_o3d_k{k:g}_l{lam:g}".replace(".", "")
        v[name] = {"astroid": k, "lam": lam, "exact_gap": True}
    v["exact_astroid_k15_noimage"] = {"astroid": 1.5, "exact_gap": True, "noimage": True}
    return v


def refit(base, spec: dict, res_row: dict):
    """The variant's tape: its ensemble refitted to Bulletin 20 and Hc (moving / static: with
    the mean field; o3d: with its axes), cached in the row."""
    if "fit" in res_row:
        f = res_row["fit"]
        pre = PreisachParams(
            f["hc_median_a_m"], f["sigma_ln_hc"], f["sigma_hi_a_m"], f["h_max_a_m"], n_table=1024
        )
        return dataclasses.replace(
            base, preisach=pre, ms_a_m=f["ms_a_m"], orientation=orientation_of(base, spec)
        )
    pub = library._published()["SCOTCH111"]
    rows = load_csv("scotch_111_remanence.csv")
    o = orientation_of(base, spec)
    alpha = spec.get("moving", spec.get("static"))
    t0 = time.time()
    if "astroid" in spec:
        fit = tv.fit_preisach_astroid(
            rows[:, 0], rows[:, 1], pub["coercivity_a_m"], pub["oxide_m"], o
        )
    elif alpha is not None:
        fit = tv.fit_preisach(
            rows[:, 0], rows[:, 1], pub["coercivity_a_m"], pub["oxide_m"], alpha, orientation=o
        )
    else:
        fit = tape_fit.fit_preisach(
            rows[:, 0], rows[:, 1], pub["coercivity_a_m"], pub["oxide_m"], orientation=o
        )
    p = fit.params
    res_row["fit"] = {
        "hc_median_a_m": p.hc_median_a_m,
        "sigma_ln_hc": p.sigma_ln_hc,
        "sigma_hi_a_m": p.sigma_hi_a_m,
        "h_max_a_m": p.h_max_a_m,
        "ms_a_m": fit.ms_a_m,
        "saturation_remanence": fit.saturation_remanence,
        "coercivity_oe": fit.coercivity_a_m / OE,
        "rms_reading_errors": fit.rms_sigma,
        "alpha_ms_oe": None if alpha is None else alpha * fit.ms_a_m / OE,
        "seconds": time.time() - t0,
    }
    if isinstance(o, tv.Orientation3D):
        res_row["fit"]["ratios"] = o.ratios()
    print("  fit:", json.dumps(res_row["fit"], default=float), flush=True)
    return refit(base, spec, res_row)


def orientation_of(base, spec):
    if "o3d" in spec:
        k, lam = spec["o3d"]
        return tv.Orientation3D(k, lam)
    if "astroid" in spec and "lam" in spec:
        return tv.Orientation3D(spec["astroid"], spec["lam"])
    if "astroid" in spec:
        return Orientation(spec["astroid"], base.orientation.n)
    return base.orientation


def head_law(spec: dict, f_hz: float) -> tv.HeadLaw | None:
    if "head" not in spec:
        return None
    ratio, lam, conc = spec["head"]
    return tv.HeadLaw(reluctance_ratio=ratio, area_ratio=conc, f_hz=f_hz, lamination_m=lam)


@contextlib.contextmanager
def options(spec: dict, tape, f_bias_hz: float, threads: int):
    """The variant's kernel options around a check."""
    with contextlib.ExitStack() as st:
        st.enter_context(
            tv.variant_kernel(
                mean_field=spec.get("moving", 0.0),
                ms_a_m=tape.ms_a_m,
                threads=threads,
                head_law=head_law(spec, f_bias_hz),
                astroid="astroid" in spec,
                exact_gap=spec.get("exact_gap", False),
            )
        )
        if "static" in spec:
            st.enter_context(tv.static_mean_field(spec["static"], tape.ms_a_m))
        yield


def data_peak_ma(data: np.ndarray) -> float:
    """A curve's peak in mA: the parabola in ln(mA) through the top three points."""
    i = int(np.argmax(data))
    x = np.log(NO21_MA[i - 1 : i + 2])
    c = np.polyfit(x, data[i - 1 : i + 2], 2)
    return float(math.exp(-c[1] / (2 * c[0])))


def summarize_no21(r: dict) -> dict:
    d1, d15 = sw.NO21_1K, sw.NO21_15K
    return {
        "rms_1k": r["rms_db_1k"],
        "rms_15k": r["rms_db_15k"],
        "rise_1k_3ma": r["model_1k_db"][1],
        "fall_1k_8ma": r["model_1k_db"][-1],
        "fall_15k_8ma": r["model_15k_db"][-1],
        "spread_8ma": r["diff_15k_1k_db"][-1],
        "peak_1k_db_of_bias": 20 * math.log10(r["peak_ma_1k"] / data_peak_ma(d1)),
        "peak_15k_db_of_bias": 20 * math.log10(r["peak_ma_15k"] / data_peak_ma(d15)),
        "scale_oe_per_ma": r["scale_oe_per_ma"],
    }


def stretch(base_no21: dict) -> dict:
    """The power law Hg = s I^p that fits No. 21 best on the base model's own curves (a
    diagnostic: how far the bias axis would need stretching; p 1 is the base)."""
    lb = np.log(np.array(base_no21["bias_a_m"]))
    curves = {1e3: np.array(base_no21["curve_1k_db"]), 15e3: np.array(base_no21["curve_15k_db"])}
    best = None
    for p in np.linspace(0.5, 1.2, 71):
        for s in np.geomspace(20 * OE, 3000 * OE, 400):
            x = np.log(s) + p * np.log(NO21_MA)
            if x[0] < lb[0] or x[-1] > lb[-1]:
                continue
            r = []
            for f, data in ((1e3, sw.NO21_1K), (15e3, sw.NO21_15K)):
                m = np.interp(x, lb, curves[f])
                r.append(m - data - np.mean(m - data))
            cost = float(np.mean(np.concatenate(r) ** 2))
            if best is None or cost < best[0]:
                best = (cost, p, s, r)
    _, p, s, r = best
    x = np.log(s) + p * np.log(NO21_MA)
    m1 = np.interp(x, lb, curves[1e3])
    m15 = np.interp(x, lb, curves[15e3])
    m1, m15 = m1 - m1.max(), m15 - m15.max()
    return {
        "p": float(p),
        "rms_1k": float(np.sqrt(np.mean(r[0] ** 2))),
        "rms_15k": float(np.sqrt(np.mean(r[1] ** 2))),
        "rise_1k_3ma": float(m1[1]),
        "spread_8ma": float((m15 - m1)[-1] - (m15 - m1)[0]),
        "model_1k_db": m1.tolist(),
        "model_15k_db": m15.tolist(),
    }


def cost(tape, spec: dict, threads: int) -> dict:
    """Seconds for one No. 21 recording (1 kHz, the base's peak bias, a low level) and the
    moving solver's counters."""
    import circuitsim

    s = sw.no21_spec()
    hc = library.load_tape("SCOTCH111@3").preisach.hc_median_a_m
    bias = 2.4 * hc
    with options(spec, tape, s.f_bias_hz, threads):
        circuitsim.tape_moving_stats()
        t0 = time.time()
        tone_harmonics(s, tape, 1e3, 0.05 * hc, bias, harmonics=1)
        dt = time.time() - t0
        solves, fails, worst = circuitsim.tape_moving_stats()
    return {"seconds": dt, "solves": solves, "fails": fails, "worst_residual": worst}


def anhysteretic_knee(tape, alpha: float) -> dict:
    """The ideal anhysteretic with the mean field (a decaying AC from saturation on a steady
    h, 1000 half cycles; the moving model followed through it) and its knee: the 3% THD
    level over the 1% of a sine through it (the switching study's `erf_level`, +4.9 dB for
    the base model's erf). The medium's own steepening (few bias cycles per freezing) comes
    on top."""
    pre = tape.ensemble()
    a = alpha * tape.ms_a_m
    hs = np.linspace(0.0, 900.0, 181) * OE
    n = 1000
    amp = 2.0 * pre.p.h_max_a_m * (1.0 - np.arange(n) / n)
    sign = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    hist = hs[:, None] + (amp * sign)[None, :]
    hist = np.concatenate([hist, hs[:, None]], axis=1)
    m = tv.along_x_rust(pre, hist, tape.orientation, a)
    h_all = np.r_[-hs[:0:-1], hs]
    m_all = np.r_[-m[:0:-1], m]
    th = np.linspace(0, 2 * math.pi, 2048, endpoint=False)

    def thd(x):
        y = np.interp(x * np.sin(th), h_all, m_all)
        sp = np.abs(np.fft.rfft(y))
        return float(np.hypot(sp[3], sp[5]) / sp[1])

    def level(target):
        lo, hi = 1.0 * OE, 890.0 * OE
        for _ in range(50):
            mid = math.sqrt(lo * hi)
            lo, hi = (mid, hi) if thd(mid) < target else (lo, mid)
        return math.sqrt(lo * hi)

    a1, a3 = level(0.01), level(0.03)
    slope = float(np.polyfit(hs[:6], m[:6], 1)[0])
    return {
        "level_3pct_db": 20 * math.log10(a3 / a1),
        "h_1pct_oe": a1 / OE,
        "chi_an_per_oe": slope * OE,
        "m_at_300oe": float(np.interp(300 * OE, hs, m)),
    }


def level_lite(tape, spec: dict, base_level: dict, threads: int, **spec_kw) -> dict:
    """The knee at 400 Hz, 15 ips on the medium at the base model's aligned bias (A/m,
    not re-aligned: the alignment costs ~50x more with the moving kernel), THD at six levels
    re the base's 0 VU, the 1% and 3% crossings interpolated in ln THD."""
    from varimu.devices.tape_machine import TapeMachineSpec

    s = TapeMachineSpec(flutter=False, **spec_kw)
    hc0 = library.load_tape("SCOTCH111@3").preisach.hc_median_a_m
    bias = base_level["hg_bias_over_hc"] * hc0
    a0 = base_level["hg_0vu_a_m"]
    db = np.array([-4.0, -1.0, 2.0, 4.0, 6.0, 8.0])
    with options(spec, tape, s.f_bias_hz, threads):
        thd = sw.thd_fn(s, tape, bias, 0.05 * hc0)
        vals = np.array([thd(a0 * 10 ** (d / 20))[0] for d in db])
    lt = np.log(vals)
    x1 = float(np.interp(math.log(0.01), lt, db))
    x3 = float(np.interp(math.log(0.03), lt, db))
    return {"db": db.tolist(), "thd": vals.tolist(), "level_1pct_db_re_base": x1,
            "level_3pct_db": x3 - x1}  # fmt: skip


#: Print-through's period numbers (the literature study, section 3.3: Manly, Audio Sept.
#: 1977, redrawing Lippert, Daniel & Axon, Westmijze; 3M Sound Talk Nos. 10 and 38).
PRINT_DATA = {
    "db_5min": -52.0,
    "db_1week": -40.0,
    "db_per_decade": 3.45,
    "db_per_10k": 1.8,
    "decay_db_3min_after_5min_print": -6.0,
    "pre_over_post_db_max": 12.0,
    "level_law_db_per_db": "1 (Manly) / 2 (3M No. 10)",
}


def print_part(tape, base_row: dict) -> dict:
    """Candidate 4 as an estimate: the barrier tail of `tape_variants.PrintThrough` with the
    switching study's barrier bracket (K V / kT at the median particle 60 / 150 / 400, and
    the noise fit's coherent 1950) and the volume spread 0.6 / 1.0 (the literature study's
    provisional sigma_ln V), printing a 0 VU tone at the print's peak wavelength (2 pi x the
    overall thickness, 1.24 kHz at 15 ips) through the base into the outer turn; against
    the period numbers (PRINT_DATA). Nothing fitted."""
    from varimu.devices.tape_machine import TapeMachineSpec, _record

    spec = TapeMachineSpec(flutter=False)
    lvl = base_row["level"]
    hc = tape.preisach.hc_median_a_m
    a0, bias = lvl["hg_0vu_a_m"], lvl["hg_bias_over_hc"] * hc
    total = tape.coating_m + tape.base_m
    lam = 2 * math.pi * total
    f = spec.speed_m_s / lam
    ds = spec.ds_m
    cells = 600e-6 + np.arange(int(round(5 * lam / ds))) * ds
    with tv.variant_kernel(threads=2):
        mx, _ = _record(
            spec, tape, lambda t: a0 * np.sin(2 * math.pi * f * t), bias, 0.0,
            (cells[-1] + 600e-6) / spec.speed_m_s, cells, a0,
        )  # fmt: skip
    mid = (cells >= cells[0] + lam) & (cells < cells[0] + 4 * lam)
    ph = np.exp(-1j * 2 * math.pi * cells[mid] / lam)
    m0 = float(np.abs((mx[:, mid] * ph).mean(axis=1) * 2).mean()) * tape.ms_a_m
    cs, sn, wt = tape.orientation.axes()
    c2x, c2y = float((wt * cs * cs).sum()), float((wt * sn * sn).sum())
    out = {"m0_a_m": m0, "m0_over_ms": m0 / tape.ms_a_m, "f_hz": f, "lam_m": lam,
           "cos2_x": c2x, "cos2_y": c2y, "data": PRINT_DATA, "cases": {}}  # fmt: skip
    k = 2 * math.pi / lam
    out["h_stray_oe"] = (
        0.5 * m0 * (1 - math.exp(-k * tape.coating_m)) * math.exp(-k * tape.base_m) / OE
    )
    week, five = 7 * 86400.0, 300.0
    # The moment against the barrier: mu0 Ms_p V / kT = 2 kappa / H0, H0 the athermal
    # switching field (the switching study's ~1.1 Hc) or the particle's shape anisotropy
    # field (160 kA/m, aspect 5: the literature study's 1.4).
    for h0n, h0 in (("hc", 1.1 * hc), ("hk", 160e3)):
        for km in (60.0, 150.0, 400.0, 1950.0):
            for sg in (0.6, 1.0):
                pt = tv.PrintThrough(km, sg, h0, 0.35 * 3.6e5, c2x, c2y)

                def db(t, temp=293.15, apart=0.0, sense=1, m=m0, lam_m=lam, pt=pt):
                    return tv.print_ratio_db(
                        pt, m, lam_m, tape.coating_m, tape.base_m, t, temp, apart, sense
                    )

                lams = np.geomspace(0.03, 3.0, 60) * lam
                peak = lams[int(np.argmax([db(1000.0, lam_m=x) for x in lams]))]
                out["cases"][f"{h0n}_k{km:g}_s{sg:g}"] = {
                    "db_5min": db(five),
                    "db_1week": db(week),
                    "db_per_decade": (db(1e5) - db(1e3)) / 2,
                    "db_per_10k": db(1000.0, 303.15) - db(1000.0),
                    "decay_db_3min_after_5min_print": db(five, apart=180.0) - db(five),
                    "pre_over_post_db": db(five) - db(five, sense=-1),
                    "level_law_db_per_db": (db(five) - db(five, m=m0 * 10 ** (-0.5))) / 10.0 + 1.0,
                    "peak_lambda_over_2pi_total": float(peak / lam),
                }
                case = out["cases"][f"{h0n}_k{km:g}_s{sg:g}"]
                print(f"  print {h0n} k{km:g} s{sg:g}:", json.dumps(case), flush=True)
    return out


def plot(res: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [n for n in variants() if n in res and "no21" in res[n]]
    fig, ax = plt.subplots(2, 3, figsize=(19, 9.5))
    groups = (
        (
            "astroid, moving mean field",
            [n for n in names if n.startswith(("base", "moving", "astroid"))],
        ),
        (
            "static mean field / head / 3D axes",
            [n for n in names if not n.startswith(("moving", "astroid"))],
        ),
    )
    for row, (title, ns) in enumerate(groups):
        for i, (key, data, f) in enumerate(
            (("model_1k_db", sw.NO21_1K, "1 kHz"), ("model_15k_db", sw.NO21_15K, "15 kHz"))
        ):
            a = ax[row, i]
            a.plot(NO21_MA, data, "ks-", lw=2.5, label="No. 21 (Type B)")
            for n in ns:
                a.plot(NO21_MA, res[n]["no21"][key], "o-", ms=3, lw=1, label=n)
            if row == 1 and "stretch" in res:
                a.plot(
                    NO21_MA, res["stretch"][key], "k:", label=f"stretch p {res['stretch']['p']:.2f}"
                )
            a.set(xlabel="bias (mA; scale fitted)", ylabel="dB re peak", title=f"{f}: {title}")
            a.legend(fontsize=7)
            a.grid(alpha=0.3)
    x = np.arange(len(names))

    def get(n, part, key):
        return res[n].get(part, {}).get(key, np.nan)

    a = ax[0, 2]
    a.bar(x - 0.2, [get(n, "summary", "rms_1k") for n in names], 0.4, label="rms 1 kHz")
    a.bar(x + 0.2, [get(n, "summary", "rms_15k") for n in names], 0.4, label="rms 15 kHz")
    a.axhline(2.0, color="k", ls="--", lw=1, label="done-when +-2 dB")
    a.set(ylabel="dB", title="No. 21 rms after one bias scale")
    a = ax[1, 2]
    a.plot(x, [get(n, "level", "level_3pct_db") for n in names], "o", label="3% over 1%, 12.7 um")
    a.plot(x, [get(n, "level51", "level_3pct_db") for n in names], "s", label="3% over 1%, 51 um")
    a.plot(
        x,
        [get(n, "level_lite", "level_3pct_db") for n in names],
        "D",
        mfc="none",
        label="the same at the base's bias (lite), 12.7 um",
    )
    a.plot(
        x,
        [get(n, "level_lite51", "level_3pct_db") for n in names],
        "s",
        mfc="none",
        label="lite, 51 um",
    )
    a.plot(x, [get(n, "b14", "-40db") for n in names], "^", label="No. 14 at 7 kHz (-40 dB)")
    a.axhspan(4.1, 4.8, color="C2", alpha=0.25, label="Sound Talk No. 1")
    a.axhline(4.0, color="k", ls="--", lw=1, label="No. 14: +4 dB")
    a.set(ylabel="dB", title="the knee and Bulletin 14")
    for a in (ax[0, 2], ax[1, 2]):
        a.set_xticks(x, names, rotation=60, ha="right", fontsize=7)
        a.legend(fontsize=7)
        a.grid(alpha=0.3)
    fig.suptitle("Over-bias options: each variant against No. 21, the knee and No. 14")
    fig.tight_layout()
    fig.savefig(OUT / "overbias_study.png", dpi=110)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--parts", nargs="+", default=["fit", "cost", "no21", "level", "b14"])
    ap.add_argument("--variants", nargs="+")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--out", default="overbias_study.json")
    a = ap.parse_args()
    path = OUT / a.out
    res = json.loads(path.read_text()) if path.exists() else {}

    def save():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(res, indent=1, default=float))

    if "plot" in a.parts:
        plot(res)
        return 0
    base = library.load_tape("SCOTCH111@3")
    if "print" in a.parts:
        res["print"] = print_part(base, res["base"])
        save()
        return 0
    vs = variants()
    for name in a.variants or list(vs):
        spec = vs[name]
        row = res.setdefault(name, {})
        row["spec"] = spec
        # The head's variants keep the base's tape; the astroid's fit is the head's too.
        head_only = not (set(spec) - {"head", "exact_gap"})
        if "astroid" in spec and "fit" not in row:
            tape_keys = {k: x for k, x in spec.items() if k not in ("exact_gap", "noimage")}
            same = next((n for n, x in vs.items() if x == tape_keys and n != name), None)
            if same and "fit" in res.get(same, {}):
                row["fit"] = res[same]["fit"]
        tape = base if name == "base" or head_only else refit(base, spec, row)
        save()
        parts = ("cost", "anh", "no21", "level", "level_lite", "level51", "level_lite51", "b14")
        for part in parts:
            if part not in a.parts or part in row:
                continue
            t0 = time.time()
            if part == "cost":
                row[part] = cost(tape, spec, a.threads)
            elif part == "no21":
                no21_spec = sw.no21_spec
                if spec.get("noimage"):
                    sw.no21_spec = lambda f=no21_spec: dataclasses.replace(f(), head_image=False)
                try:
                    with options(spec, tape, 70e3, a.threads):
                        r = sw.no21(tape, tape.preisach.hc_median_a_m)
                finally:
                    sw.no21_spec = no21_spec
                row[part] = r
                row["summary"] = summarize_no21(r)
                if name == "base":
                    res["stretch"] = stretch(r)
            elif part == "level":
                with options(spec, tape, 100e3, a.threads):
                    row[part] = sw.level(tape)
            elif part == "anh":
                row[part] = anhysteretic_knee(tape, spec.get("moving", spec.get("static", 0.0)))
            elif part == "level_lite":
                row[part] = level_lite(tape, spec, res["base"]["level"], a.threads)
            elif part == "level_lite51":
                row[part] = level_lite(
                    tape, spec, res["base"]["level51"], a.threads, rec_gap_m=51e-6
                )
            elif part == "level51":
                with options(spec, tape, 100e3, a.threads):
                    row[part] = sw.level(tape, rec_gap_m=51e-6)
            else:
                with options(spec, tape, 100e3, a.threads):
                    row[part] = sw.bulletin14(tape)
            row.setdefault("seconds", {})[part] = time.time() - t0
            show = row.get("summary") if part == "no21" else row[part]
            show = {k: v for k, v in show.items() if not isinstance(v, list)}
            text = json.dumps(show, default=float)[:500]
            print(f"{name} {part} ({time.time() - t0:.0f} s):", text, flush=True)
            save()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""A study before a model change (docs/TAPE_PLAN.md, "Gaps" 4): the heads' provisional
geometry against sourced anchors: on the medium alone (the first print's machine), and the
aligned 351's low end by block (nothing in varimu/ changes).

1. `contour`: the repro head's low-frequency contour, |sinc(k g / 2) - cos(k e_c) R(k)|
   (varimu.devices.tape.head_hx_spectrum's bracket; at audio wavelengths the spacing and
   thickness terms are ~1), its pole length and relaxation fitted to Nortronics' measured
   15 ips curves (web: https://www.discolathe.com/.pdfs/Nortronics_Silvr_pp1-9.pdf, "Design
   Digest" Fig. 3, read by eye at 400 dpi, ~+-0.3 dB: the long-pole WP series and the
   "extra long pole" PR / Studio series), against the current 3 mm / 3 mm.
2. `gap`: the record gap 12.7 um (the ATR sheet's test gap, now in the 351) against 25 um and
   51 um (0.002", the Ampex 300's in Sound Talk No. 21; Minneapolis Magnetics fits one
   replacement to the 300 / 350 / 400): each aligned as the first print is, then the 3% THD
   level over the 1% (400 Hz, 15 ips; #111 ~4.1-4.5 dB, Sound Talk No. 1), Bulletin 14 at
   7 kHz re 400 Hz (7.5 ips; +4 dB) and the low-level response re 1 kHz at 15 ips.
3. `machine`: the aligned 351 (varimu.measure.tape_align, its cache) split into blocks at
   30-200 Hz, the repro contour that makes it flattest, and the contour Ampex's measured
   electronics needed for a flat machine. This calibrated the circuit's pole_m / relax_m
   (TAPE_PLAN.md Gaps 4, 2026-11-02); rerun on the aligned machine it checks them.

    uv run --extra fast python scripts/tape_heads_study.py [--parts contour gap machine]
-> reports/tape/heads_study.{json,png} (~20 min, `machine` ~3 min more)
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
from varimu.devices.tape_machine import TapeMachineSpec, align, tone_harmonics

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import tape_switching_study as sw  # noqa: E402

OUT = REPO_ROOT / "reports" / "tape"
F_HZ = np.array([20, 30, 40, 50, 70, 100, 150, 200, 300, 500, 1000.0])
# dB re each curve's flat level (15 and 5 dB on the figure).
NORTRONICS = {
    "WP": np.array([-5.0, 0.0, 2.0, 3.0, 2.2, 0.7, -1.2, -0.5, 0.3, 0.0, 0.0]),
    "PR": np.array([0.0, 1.8, 1.5, 0.3, -1.0, -0.1, -0.2, 0.0, 0.0, 0.0, 0.0]),
}
RESPONSE_HZ = (100.0, 1e3, 5e3, 10e3, 15e3)


def contour_db(pole_m: float, relax_m: float, f_hz, v: float, gap_m: float) -> np.ndarray:
    k = 2 * math.pi * np.asarray(f_hz) / v
    ec = gap_m / 2 + pole_m + relax_m / 2
    r = np.sinc(k * relax_m / (2 * math.pi)) if relax_m > 0 else 1.0
    return 20 * np.log10(np.abs(np.sinc(k * gap_m / (2 * math.pi)) - np.cos(k * ec) * r))


def contour() -> dict:
    spec = TapeMachineSpec()
    v, g = spec.speed_m_s, spec.rep_gap_m
    out = {
        "current": {
            "pole_m": spec.pole_m,
            "relax_m": spec.relax_m,
            "db": contour_db(spec.pole_m, spec.relax_m, F_HZ, v, g).tolist(),
        }
    }
    for name, data in NORTRONICS.items():
        best = None
        for p in np.arange(0.5, 20.01, 0.25) * 1e-3:
            for r in np.arange(0.0, 30.01, 0.25) * 1e-3:
                m = contour_db(p, r, F_HZ, v, g)
                m = m - m[-3:].mean()
                c = float(np.sqrt(np.mean((m - data) ** 2)))
                if best is None or c < best[0]:
                    best = (c, p, r, m)
        c, p, r, m = best
        out[name] = {"rms_db": c, "pole_m": float(p), "relax_m": float(r), "db": m.tolist()}
        print(f"{name}: rms {c:.2f} dB, pole {p * 1e3:.2f} mm, relax {r * 1e3:.2f} mm", flush=True)
    return out


LF_HZ = (30.0, 40.0, 50.0, 70.0, 100.0, 200.0, 1000.0)


def machine(tape) -> dict:
    """The aligned 351's low end by block, re 1 kHz: record electronics (input -> head
    current), the medium's recorded flux (the ideal reproducer's EMF over f, the circuit's
    record gap), the 6 dB/oct of the EMF, the reproduce electronics (EMF -> out); then the
    repro contour (pole, relaxation) that makes their sum flattest 30 Hz-1 kHz (the worst
    deviation), and the contour a flat machine needed with Ampex's measured electronics
    (manual p94, data/datasheets/ampex_351_response_15ips.csv)."""
    import csv

    from varimu.circuit import spec as cspec
    from varimu.measure import tape_align as ta
    from varimu.sim import fast

    b = ta.Bench.load()
    al = ta.aligned()
    ov = al.overrides
    p = cspec.resolve(cspec.load_circuit(cspec.circuit_path(ta.CIRCUIT)), ov)
    f = np.array(LF_HZ)

    def resp(ir, probe, amp):
        t = np.arange(int(1.6 * b.fs)) / b.fs
        ph = np.random.default_rng(1).uniform(0, 2 * math.pi, len(f))
        x = amp * sum(np.sin(2 * math.pi * fi * t + q) for fi, q in zip(f, ph, strict=True))
        v = fast.run_transient(ir, x, settings=b.settings).vectors[f"v({probe})"]
        w = slice(int(0.6 * b.fs), None)
        d = ta._db(ta.fit(v[w], b.fs, f) / ta.fit(x[w], b.fs, f))
        return d - d[-1]

    rec = resp(ta.record_ir(b, ov), "rbc", b.vu_peak_v(-10) / 4)
    rep = resp(ta.repro_ir(b, ov), "out", 1e-4)
    spec = TapeMachineSpec(flutter=False, rec_gap_m=p["rec_gap_m"])
    low = 0.05 * tape.preisach.hc_median_a_m
    hb = 3.0 * tape.preisach.hc_median_a_m
    med = []
    for fi in f:
        _, ideal = tone_harmonics(spec, tape, fi, low, hb, harmonics=1, waves=1, ideal=True)
        med.append(abs(ideal[0]) / fi)
    med = 20 * np.log10(np.array(med) / med[-1])
    emf = 20 * np.log10(f / f[-1])
    rest = rec + med + emf + rep
    v, g = p["speed_m_s"], p["rep_gap_m"]
    fd = np.geomspace(30.0, 1000.0, 90)
    restd = np.interp(np.log(fd), np.log(f), rest)
    best = None
    for pm in np.arange(0.25, 25.01, 0.25) * 1e-3:
        for rm in np.arange(0.0, 40.01, 0.25) * 1e-3:
            d = contour_db(pm, rm, np.r_[fd, 1000.0], v, g)
            worst = float(np.abs(d[:-1] - d[-1] + restd).max())
            if best is None or worst < best[0]:
                best = (worst, float(pm), float(rm))
    now = contour_db(p["pole_m"], p["relax_m"], f, v, g)
    now = now - now[-1]
    rows = list(csv.DictReader((REPO_ROOT / "data/datasheets/ampex_351_response_15ips.csv").open()))
    amp = {}
    for r in rows:
        amp.setdefault(r["curve"], {})[float(r["f_hz"])] = float(r["db"])
    ampex = {}
    for fi in (30.0, 50.0, 100.0, 200.0):
        i = LF_HZ.index(fi)
        a_rep = amp["reproduce"][fi] - amp["reproduce"][1000.0]
        ampex[f"{fi:g}"] = -(amp["record"][fi] + med[i] + emf[i] + a_rep)
    out = {
        "f_hz": list(LF_HZ),
        "record_db": rec.tolist(),
        "medium_flux_db": med.tolist(),
        "emf_db": emf.tolist(),
        "reproduce_db": rep.tolist(),
        "circuit_contour": {"pole_m": p["pole_m"], "relax_m": p["relax_m"], "db": now.tolist()},
        "machine_db": (rest + now).tolist(),
        "flattest": {"worst_db": best[0], "pole_m": best[1], "relax_m": best[2]},
        "contour_needed_with_ampex_electronics_db": ampex,
    }  # fmt: skip
    print(json.dumps(out, indent=1), flush=True)
    return out


def gap(tape) -> dict:
    out = {}
    for g in (12.7e-6, 25e-6, 51e-6):
        t0 = time.time()
        spec = TapeMachineSpec(flutter=False, rec_gap_m=g)
        lv = sw.level(tape, rec_gap_m=g)
        al = align(spec, tape)
        low = 0.05 * tape.preisach.hc_median_a_m
        resp = {
            f: abs(tone_harmonics(spec, tape, f, low, al.hg_bias, harmonics=1)[0])
            for f in RESPONSE_HZ
        }
        hc = tape.preisach.hc_median_a_m
        slow = TapeMachineSpec(flutter=False, rec_gap_m=g).at_speed(7.5 * 0.0254)
        perm = {}
        for f in (400.0, 7000.0):
            s = sw.b14.sweep(slow, tape, f, al.hg_bias, hc)
            perm[f] = {
                t: sw.b14.permissible(np.array(sw.b14.LEVELS_OVER_HC), s, t)
                for t in sw.b14.CRITERIA_DB
            }
        crit = sw.b14.CRITERIA_DB
        out[f"{g * 1e6:g}um"] = {
            "level": lv,
            "response_re_1k_db": {
                f"{f:g}": 20 * math.log10(r / resp[1e3]) for f, r in resp.items()
            },
            "b14": {f"{t:g}db": 20 * math.log10(perm[7000.0][t] / perm[400.0][t]) for t in crit},
        }
        row = out[f"{g * 1e6:g}um"]
        print(
            f"gap {g * 1e6:g} um ({time.time() - t0:.0f} s): 3% {lv['level_3pct_db']:+.2f} dB, "
            f"b14 {row['b14']}, response {row['response_re_1k_db']}",
            flush=True,
        )
    return out


def plot(res: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(13, 4.6))
    c = res.get("contour", {})
    for name, d in NORTRONICS.items():
        ax[0].semilogx(F_HZ, d, "s-", lw=2, label=f"Nortronics {name} (15 ips)")
        if name in c:
            p, r = c[name]["pole_m"] * 1e3, c[name]["relax_m"] * 1e3
            ax[0].semilogx(
                F_HZ, c[name]["db"], "o--", label=f"model, pole {p:.2f} / relax {r:.2f} mm"
            )
    if "current" in c:
        ax[0].semilogx(F_HZ, c["current"]["db"], "k:", lw=2, label="current 3 / 3 mm")
    ax[0].set(xlabel="Hz at 15 ips", ylabel="dB", title="repro head contour")
    ax[0].legend(fontsize=7)
    g = res.get("gap", {})
    if g:
        names = list(g)
        x = np.arange(len(names))
        ax[1].bar(
            x - 0.25,
            [g[n]["level"]["level_3pct_db"] for n in names],
            0.25,
            label="3% level (dB over 1%)",
        )
        ax[1].bar(
            x, [g[n]["b14"]["-40db"] for n in names], 0.25, label="No. 14 at 7 kHz (-40 dB crit.)"
        )
        ax[1].bar(
            x + 0.25,
            [g[n]["response_re_1k_db"]["15000"] for n in names],
            0.25,
            label="15 kHz re 1 kHz",
        )
        ax[1].axhspan(4.1, 4.5, color="C0", alpha=0.2)
        ax[1].axhline(4.0, color="C1", ls="--")
        ax[1].set_xticks(x, [f"record gap {n}" for n in names])
        ax[1].set(ylabel="dB", title="record gap (medium alone, aligned each)")
        ax[1].legend(fontsize=7)
    for a in ax:
        a.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(OUT / "heads_study.png", dpi=110)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--parts", nargs="+", default=["contour", "gap"])
    ap.add_argument("--tape", default="SCOTCH111@3")
    a = ap.parse_args()
    path = OUT / "heads_study.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    if "contour" in a.parts:
        res["contour"] = contour()
    if "gap" in a.parts:
        res["gap"] = gap(library.load_tape(a.tape))
    if "machine" in a.parts:
        res["machine"] = machine(library.load_tape(a.tape))
    path.write_text(json.dumps(res, indent=1, default=float))
    plot(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Where a chain's character comes from, how far units of it spread, and what bending it does
(2026-11-14; follows scripts/chain_passes.py and chain_spike.py; the user away, every call mine).

    uv run --extra fast --extra listen python scripts/chain_study.py
        [--only attribution units bends whatif] [--workers N]

Three studies on the repeated-pass experiment (scripts/chain_passes.py: its staging, H, metrics):

- **attribution** (U47 -> V76): each transformer's core as Jiles-Atherton alone, the others in
  their linear limit (the builder's `cores="linear"` element for that core spliced in), and all
  linear (the tubes' character alone). Which iron makes the character says whose data matters.
- **units**: UNIT_SEEDS tolerance draws (passive_spread 1: every part and tube uniform across its
  class's band) of three chains; the spread of their tone (H) and character.
- **bends** (U47 -> V76): conditions past the nominal, realistic first, then out of range. Each is
  a physical cause (BENDS has the reason for every number).

Reports in reports/chain_study/<study>/ (README.md), passes cached in cache/chain_passes/ like
chain_passes' (each variant keys apart by a marker in its `over`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chain_passes as cp  # noqa: E402
import chain_spike as cs  # noqa: E402

from varimu.circuit import builder  # noqa: E402
from varimu.config import REPO_ROOT  # noqa: E402
from varimu.sim import fast  # noqa: E402

OUT = REPO_ROOT / "reports" / "chain_study"
TAG = "production"
STEMS = ("bass", "guitar", "harmonies", "lead vocal")
CORES = ("BV8_U47", "T85_V76", "L86_V76", "L88_V76", "T89_V76")
CORE_NAMES = {
    "BV8_U47": "BV8 (U47 output)",
    "T85_V76": "T85 (V76 input, 1:30)",
    "L86_V76": "L86 (V2 plate choke)",
    "L88_V76": "L88 (V4 plate choke)",
    "T89_V76": "T89 (V76 output, 9:1)",
}
UNIT_SEEDS = tuple(range(1, 9))
UNIT_CHAINS = {"u47_v76": "v76", "r44_ua610": "ua610", "sm57_api312": "api312"}
UNIT_STEMS = ("bass", "lead vocal")
UNIT_PASSES = 4
ATTR_PASSES = 4
BEND_PASSES = 8
FREQS = (50, 100, 200, 500, 2000, 5000, 10000, 15000)


class Variant:
    """A chain variant cp.passes / cp.measure_h can run: `name` (the circuit, cp's keys), `over`
    (its overrides plus a marker, so its caches key apart), `noise`, `fs`, `run(p, seed)`."""

    def __init__(self, label: str, chain: str, over: dict, ir=None, spike=None):
        self.label = label
        self.base = cp.Chain(chain, False, over)
        self.name = chain
        self.over = {**over, "__variant": label}
        self.noise = False
        self.fs = self.base.fs
        self.ir = ir
        self.spike = spike

    def run(self, p: np.ndarray, seed: int | None = None) -> np.ndarray:
        if self.spike is not None:
            return self.spike.out(p, seed)
        front, ctl = self.base.entries(p)
        r = fast.run_transient(self.ir, front, settings=self.base.s, controls=ctl or None)
        return np.asarray(r.vectors["v(out)"], float) / self.base.out_fs


def cores_ja(chain: str, over: dict, keep: tuple[str, ...]):
    """The chain's IR with only `keep`'s cores Jiles-Atherton, the rest in their linear limit."""
    c = cp.Chain(chain, False, over).c
    ja = builder.build(c, over).ir
    lin = {e.name: e for e in builder.build(c, over, cores="linear").ir.elements()}
    drop = [k for k in CORES if k not in keep]
    secs = []
    for s in ja.sections:
        es = []
        for e in s.elements:
            hit = [k for k in drop if e.name == f"X{k}_CORE"]
            es.append(lin[f"R{hit[0]}_core"] if hit else e)
        secs.append(replace(s, elements=tuple(es)))
    models = tuple(m for m in ja.models if m.name not in {f"CORE_{k}" for k in drop})
    return replace(ja, sections=tuple(secs), models=models)


def tired_vf14(over: dict):
    """The U47's VF14 at half its emission (Koren's Ip ~ E1^ex / kg1: kg1 doubled)."""
    c = cp.Chain("u47_v76", False, over).c
    ir = builder.build(c, over).ir
    models = tuple(
        replace(m, plate=replace(m.plate, kg1=m.plate.kg1 * 2.0)) if m.name == "VF14T_V1_u47" else m
        for m in ir.models
    )
    return replace(ir, models=models)


NOM = dict(cp.CHAIN_SET["u47_v76"])  # {"gain_db_v76": 24}
# Every bend: (label, why, spl_db, how). Realistic ones first.
BENDS = (
    ("loud_115", "a loud source (a guitar cab or kick at 115 dB SPL), the V76 turned down 15 dB to "
     "9 dB: realistic, the capsule and tube driven hard", 115.0, {"over": {"gain_db_v76": 9}}),
    ("brownout", "mains at the V76's lowest rating, 198 V (10 % low), the NG's 300 V scaled with "
     "it to 270 V", 100.0, {"over": NOM | {"mains_v_rms_v76": 198.0, "ng_open_v_u47": 270.0}}),
    ("weak_ng", "a weak NG rectifier: 220 V open circuit instead of 300 (the U47's 105 V rail "
     "drops with it)", 100.0, {"over": NOM | {"ng_open_v_u47": 220.0}}),
    ("tired_vf14", "an aged VF14: half its emission (kg1 doubled)", 100.0, {"ir": "tired_vf14"}),
    ("small_bv8", "a BV8 on a quarter of the core area with twice the turns: the same "
     "inductance, twice the flux density", 100.0,
     {"over": NOM | {"bv8_core_area_m2_u47": 0.25e-4, "bv8_turns_u47": 5200}}),
    ("hum_heavy", "dried-out filter capacitors: the NG's ripple 40 dB and T90's field 20 dB over "
     "spike-2's calibration (out of spec)", 100.0, {"spike": {"hum"}, "cal": {"ripple_v": 100.0,
                                                                               "stray_v": 10.0}}),
    ("microphonic", "a VF14 Neumann would have rejected: its modes' peaks at -20 dB re the "
     "capsule's signal (30 dB over chain_spike's invented 'selected' tube)", 100.0,
     {"spike": {"microphonics"}, "micro_db": -20.0}),
)  # fmt: skip


# Sourced alternatives for the chain's provisional transformer values (found 2026-11-14 by a
# web search; data/schematics/{neumann_u47,telefunken_v76}/README.md "Found 2026-11-14"):
# options for the user, not changes to the circuit files.
GD = "groupdiy.com/threads/"
WHATIFS = (
    ("bv8_c30", "BV8 primary self-capacitance 30 pF, not the provisional 150 pF (originals "
     "measured 16-28 pF apparent, 'a little over 30 pF' true: " + GD
     + "bv08-transformer-capacitance-comparable-to-mic-cable-capacitance.83565/page-3, forum)",
     {"bv8_c_pri_f_u47": 30e-12}),
    ("bv8_l180", "BV8 primary 180 H in the linear limit, not 91 H (clones measured 150 H (AMI) "
     "and 211 H (Haufe), level unstated: " + GD + "bv-08-transformer-laminations-alloy.52099/, "
     "forum); the joint gap 6.26 -> 1.65 um", {"bv8_gap_m_u47": 1.65e-6}),
    ("t85_dcr3", "T85 primary 3 ohm per half, not the calibrated 77 (a 1974 unit measured ~3 + 3 "
     "ohm and 2.7 H: " + GD + "v76-input-transformers-acting-weird.77981/, forum; another 6.5 "
     "ohm total)", {"t85_r_half_ohm_v76": 3.0}),
    ("t89_dcr", "T89 650 / 11 ohm, not the provisional 360 / 5 (" + GD
     + "v76-output-transformer.57129, forum, the reading's origin unknown)",
     {"t89_r_pri_ohm_v76": 650.0, "t89_r_sec_ohm_v76": 11.0}),
)  # fmt: skip
WHATIFS = WHATIFS + (
    ("sourced_all", "all four together", {k: v for _l, _w, o in WHATIFS for k, v in o.items()}),
)


def bend_variant(label: str, how: dict, cal: dict) -> Variant:
    over = how.get("over", NOM)
    if "spike" in how:
        c = dict(cal)
        for k, f in how.get("cal", {}).items():
            c[k] = cal[k] * f
        sp = cs.Spike(how["spike"], 100.0, NOM["gain_db_v76"], c)
        if "micro_db" in how:
            sp.micro_peak_db = how["micro_db"]
        return Variant(label, "u47_v76", over, spike=sp)
    ir = (
        tired_vf14(over)
        if how.get("ir") == "tired_vf14"
        else builder.build(cp.Chain("u47_v76", False, over).c, over).ir
    )
    return Variant(label, "u47_v76", over, ir=ir)


def h_points(f_ms, h_ms) -> dict:
    ok = np.isfinite(h_ms)
    fm, hm = f_ms[ok], h_ms[ok]
    i1k = np.argmin(np.abs(fm - 1000))
    pts = {"1k_abs_db": round(float(20 * np.log10(np.abs(hm[i1k]))), 2)}
    for fq in FREQS:
        i = np.argmin(np.abs(fm - fq))
        pts[str(fq)] = round(float(20 * np.log10(np.abs(hm[i]) / np.abs(hm[i1k]))), 2)
    return pts


def rows_for(ys, dry, fs, f_ms, h_ms, shown, spl) -> dict:
    out = {}
    for k in shown:
        if k > len(ys):
            continue
        row = cp.residuals(ys, dry, spl, f_ms, h_ms, k, fs)
        row["vs_dry"] = cp.char_db(cp.to_spl(dry, 94.0, fs), ys[k - 1], fs)
        if k > 1:
            eq = cp.apply_power(ys[k - 1], f_ms, h_ms, -(k - 1), fs)
            row["eqnull_vs_p1"] = cp.char_db(ys[0], eq, fs)
        out[f"p{k}"] = row
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="*", default=["attribution", "units", "bends", "whatif"])
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()
    fs = cp._settings(False).sample_rate
    dry = {s: cp.load_stem(s, fs) for s in STEMS}
    cal = cs.calibrate()
    t0 = time.perf_counter()
    jobs: dict = {}
    hs: dict = {}
    variants: dict = {}
    with ThreadPoolExecutor(args.workers) as ex:
        if "attribution" in args.only:
            cfgs = {"all_ja": CORES, "all_linear": ()} | {f"only_{k}": (k,) for k in CORES}
            for lab, keep in cfgs.items():
                v = Variant(lab, "u47_v76", NOM, ir=cores_ja("u47_v76", NOM, keep))
                variants[("attribution", lab)] = (v, 100.0, STEMS, ATTR_PASSES)
        if "units" in args.only:
            for ch, sfx in UNIT_CHAINS.items():
                base_over = dict(cp.CHAIN_SET[ch])
                spl = cp.CHAIN_SPL_DB.get(ch, 100.0)
                variants[("units", f"{ch}/nominal")] = (
                    cp.Chain(ch, False, base_over),
                    spl,
                    UNIT_STEMS,
                    UNIT_PASSES,
                )
                for k in UNIT_SEEDS:
                    o = base_over | {f"passive_spread_{sfx}": 1.0, f"passive_seed_{sfx}": k}
                    variants[("units", f"{ch}/unit{k}")] = (
                        cp.Chain(ch, False, o),
                        spl,
                        UNIT_STEMS,
                        UNIT_PASSES,
                    )
        if "bends" in args.only:
            variants[("bends", "nominal")] = (
                cp.Chain("u47_v76", False, NOM),
                100.0,
                STEMS,
                BEND_PASSES,
            )
            for lab, _why, spl, how in BENDS:
                variants[("bends", lab)] = (bend_variant(lab, how, cal), spl, STEMS, BEND_PASSES)
        if "whatif" in args.only:
            variants[("whatif", "nominal")] = (
                cp.Chain("u47_v76", False, NOM),
                100.0,
                STEMS,
                ATTR_PASSES,
            )
            for lab, _why, o in WHATIFS:
                variants[("whatif", lab)] = (
                    cp.Chain("u47_v76", False, NOM | o),
                    100.0,
                    STEMS,
                    ATTR_PASSES,
                )
        hf = {k: ex.submit(cp.measure_h, v, spl, TAG) for k, (v, spl, _s, _n) in variants.items()}
        hs = {k: f.result() for k, f in hf.items()}
        jf = {
            (k, s): ex.submit(cp.passes, v, s, dry[s], n, spl, TAG)
            for k, (v, spl, stems, n) in variants.items()
            for s in stems
        }
        jobs = {k: f.result() for k, f in jf.items()}
    print(f"renders done in {(time.perf_counter() - t0) / 60:.1f} min", flush=True)
    report(variants, hs, jobs, dry, fs)


def report(variants, hs, jobs, dry, fs) -> None:
    cp.OUT = OUT
    studies: dict = {}
    for (study, lab), (_v, spl, stems, n) in variants.items():
        f_ms, h_ms = hs[(study, lab)]
        shown = tuple(k for k in (1, 2, 4, 8) if k <= n)
        e = {"spl_db": spl, "h_db_re_1k": h_points(f_ms, h_ms), "stems": {}}
        for s in stems:
            ys = jobs[((study, lab), s)]
            e["stems"][s] = rows_for(ys, dry[s], fs, f_ms, h_ms, shown, spl)
            d = OUT / study / s / lab.replace("/", "_")
            if study in ("bends", "whatif") or (
                study == "units" and lab.endswith(("unit1", "unit2", "unit3", "nominal"))
            ):
                cp.write(d / "p1.wav", ys[0], fs)
                cp.write(d / f"p{n}.wav", ys[n - 1], fs)
                if study == "bends":
                    cp.write(
                        d / f"p{n}_eqnull.wav",
                        cp.apply_power(ys[n - 1], f_ms, h_ms, -(n - 1), fs),
                        fs,
                    )
            if study == "attribution":
                cp.write(d / "p1.wav", ys[0], fs)
        studies.setdefault(study, {})[lab] = e
    for s in STEMS:
        cp.write(OUT / f"dry_{s}.wav", dry[s], fs)
    for study, e in studies.items():
        (OUT / study).mkdir(parents=True, exist_ok=True)
        (OUT / study / "summary.json").write_text(json.dumps(e, indent=1), encoding="utf-8")
    why = {lab: w for lab, w, _s, _h in BENDS} | {lab: w for lab, w, _o in WHATIFS}
    (OUT / "variants_why.json").write_text(json.dumps(why, indent=1), encoding="utf-8")
    print("written", list(studies))


if __name__ == "__main__":
    main()

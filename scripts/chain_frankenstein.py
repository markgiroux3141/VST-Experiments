"""Frankenstein: the U47 -> V76 with exotic iron and tubes, through repeated passes (2026-11-14,
the user's ask: "a transformer with an osmium or uranium core, or one the size of a large room ...
let's go full frankenstein").

    uv run --extra fast --extra listen python scripts/chain_frankenstein.py [--workers N]

The BV8 (the U47's output transformer: chain_study's attribution found it the iron that distorts)
gets other cores, each **rewound to the nominal's linear-limit inductance** (91 H), so what changes
is the material's nonlinearity rather than the bass. More turns of the same wire on the same
geometry: DCR x n, leakage x n^2, n the turns' ratio. The scaling is provisional, model knowledge:

- `air_core_osmium_uranium`: osmium (chi ~ 1.5e-5) and uranium (chi ~ 4e-4) are paramagnetic, not
  ferromagnetic. Their core is an air core: mu_r 1.0004 at most. Modelled as a gap the length of the
  path. It takes ~255,000 turns for 91 H, with the coupling an air core gives (leakage 0.2 x L, k ~
  0.9, AIR_LEAKAGE_SHARE) and the winding capacitance of ~100x the layers (AIR_C_PRI_F).
- `victorian_iron`, `power_steel`: config/magnetics.yaml's soft_iron_ewing (Ewing, 1885) and
  grain_oriented_si_steel.
- `nickel`: pure nickel, the Nickel Organ's JA fit (config/nickel/organ.yaml).
- `tool_steel`: hardened carbon tool steel, a hard material (Hc ~ 3-4 kA/m, TOOL_STEEL: provisional,
  model knowledge; Bozorth, Ferromagnetism, hardened carbon steels): mostly hysteresis.
- `room_sized`: the BV8 x100 in every dimension (core area 1 m^2, path 9 m, gap x100), the same turns
  of wire 100x thicker. Inductance x100, DCR /100, leakage x100, winding capacitance x100 (both
  scale with length), so the leakage-capacitance resonance falls 100x: ~41 kHz -> ~410 Hz.

Tubes in the VF14's place, normally heated (the underheated cathode's -0.32 V shift off):
`tube_12ax7`, `tube_2a3` (a power triode at a microphone's 105 V), `tube_56` (a 1930s triode). And
`monster`: room-sized, tool steel, 2A3.

The V76's gain is re-picked per variant (its nearest switch position) so that the 1 kHz level
matches the nominal's. Passes 1-4 at 100 dB SPL on three stems, chain_passes' staging. Reports in
reports/chain_frankenstein/ (README.md).
"""

# ruff: noqa: E501  (sources and reasons kept on one line in the variant tables)
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chain_passes as cp  # noqa: E402
import chain_study as st  # noqa: E402

from varimu.circuit import builder  # noqa: E402
from varimu.config import REPO_ROOT  # noqa: E402
from varimu.devices.core import MU0, MagneticCore, materials  # noqa: E402
from varimu.devices.library import load_device  # noqa: E402

OUT = REPO_ROOT / "reports" / "chain_frankenstein"
CHAIN = "u47_v76"
STEMS = ("bass", "guitar", "lead vocal")
PASSES = 4
SPL = 100.0
V76_STEPS = (3, 9, 18, 24, 34, 40, 46, 52, 58, 64, 70, 76)
# Hardened carbon tool steel (provisional: model knowledge; Bozorth, "Ferromagnetism" (1951): hardened
# carbon / tungsten magnet steels Hc ~ 4-5 kA/m, Br ~ 1 T; a JA set of that order, not a fit).
TOOL_STEEL = {
    "ms_a_per_m": 1.5e6,
    "a_a_per_m": 2500.0,
    "k_a_per_m": 3500.0,
    "c": 0.1,
    "alpha": 1.0e-4,
}
AIR_LEAKAGE_SHARE = 0.2  # provisional: model knowledge (coupled air-core coils, k ~ 0.9)
AIR_C_PRI_F = 1.0e-9  # provisional: model knowledge (a ~255,000-turn layer winding's capacitance)
SCALE = 100.0  # room_sized: x100 in every dimension

VARIANTS = {
    "nominal": {},
    "air_core_osmium_uranium": {"core": "air"},
    "victorian_iron": {"core": "soft_iron_ewing"},
    "power_steel": {"core": "grain_oriented_si_steel"},
    "nickel": {"core": "nickel"},
    "tool_steel": {"core": "tool_steel"},
    "room_sized": {"scale": SCALE},
    "tube_12ax7": {"tube": "12AX7@1"},
    "tube_2a3": {"tube": "2A3@1"},
    "tube_56": {"tube": "56@1"},
    "monster": {"scale": SCALE, "core": "tool_steel", "tube": "2A3@1"},
}


def nickel_ja() -> dict:
    import yaml

    d = yaml.safe_load((REPO_ROOT / "config" / "nickel" / "organ.yaml").read_text(encoding="utf-8"))

    def val(v):
        return float(v["value"] if isinstance(v, dict) else v)

    def find(o, key):
        if isinstance(o, dict):
            if key in o:
                return o[key]
            for v in o.values():
                r = find(v, key)
                if r is not None:
                    return r
        return None

    ja = find(d, "ja") or {}
    return {k: val(ja[k]) if k in ja else val(find(d, k))
            for k in ("ms_a_per_m", "a_a_per_m", "k_a_per_m", "c", "alpha")}  # fmt: skip


def ja_of(core: str) -> dict:
    if core == "tool_steel":
        return dict(TOOL_STEEL)
    if core == "nickel":
        return nickel_ja()
    m = materials()[core]
    return {k: float(m[k]) for k in ("ms_a_per_m", "a_a_per_m", "k_a_per_m", "c", "alpha")}


def mu_r(ja: dict) -> float:
    return 1.0 + MagneticCore("x", path_m=1.0, **ja).initial_susceptibility()


def build(spec: dict, gain_db: int):
    """(over, IR, notes) for a variant at a V76 gain."""
    c = cp.Chain(CHAIN, False, {"gain_db_v76": gain_db}).c
    q = cp.Chain(CHAIN, False, {"gain_db_v76": gain_db}).q
    over: dict = {"gain_db_v76": gain_db}
    notes: dict = {}
    n0 = float(q["bv8_turns_u47"])
    area, path, gap = (
        float(q[k]) for k in ("bv8_core_area_m2_u47", "bv8_core_path_m_u47", "bv8_gap_m_u47")
    )
    rp, rs, lk, cpri = (float(q[k]) for k in ("bv8_r_pri_ohm_u47", "bv8_r_sec_ohm_u47", "bv8_leakage_h_u47",
                                               "bv8_c_pri_f_u47"))  # fmt: skip
    mu_nom = mu_r(ja_of("mumetall"))
    l_nom = n0**2 * MU0 * area / (path / mu_nom + gap)
    notes["bv8_l_nominal_h"] = round(l_nom, 1)
    s = spec.get("scale", 1.0)
    if s != 1.0:
        area, path, gap = area * s * s, path * s, gap * s
        rp, rs, lk, cpri = rp / s, rs / s, lk * s, cpri * s
        notes["scale"] = s
    ja = None
    core = spec.get("core")
    if core == "air":
        gap = path  # mu_eff ~ 1 (the mumetall in the model sees no field)
        n = n0 * math.sqrt((path / mu_nom + path) / (path / mu_nom + float(q["bv8_gap_m_u47"])))
        l_new = n**2 * MU0 * area / (path / mu_nom + gap)
        notes |= {"turns": round(n), "mu_r": 1.0, "l_h": round(l_new, 1)}
        rp, rs = rp * n / n0, rs * n / n0
        lk, cpri = AIR_LEAKAGE_SHARE * l_new, AIR_C_PRI_F
        n0_new = n
    elif core:
        ja = ja_of(core)
        mu = mu_r(ja)
        l_target = l_nom * s  # the room-sized one keeps its x100
        n = math.sqrt(l_target * (path / mu + gap) / (MU0 * area))
        notes |= {"turns": round(n), "mu_r": round(mu, 1), "l_h": round(l_target, 1)}
        rp, rs, lk = rp * n / n0, rs * n / n0, lk * (n / n0) ** 2
        n0_new = n
    else:
        n0_new = n0
    if s != 1.0 or core:
        over |= {"bv8_core_area_m2_u47": area, "bv8_core_path_m_u47": path, "bv8_gap_m_u47": gap,
                 "bv8_turns_u47": float(round(n0_new)), "bv8_r_pri_ohm_u47": rp, "bv8_r_sec_ohm_u47": rs,
                 "bv8_leakage_h_u47": lk, "bv8_c_pri_f_u47": cpri}  # fmt: skip
        notes |= {"r_pri_ohm": round(rp, 1), "leakage_h": round(lk, 4), "c_pri_f": cpri}
        notes["leak_c_resonance_hz"] = round(1 / (2 * math.pi * math.sqrt(lk * cpri)))
    if spec.get("tube"):
        over["space_charge_v_u47"] = 0.0
    ir = builder.build(c, over).ir
    models = list(ir.models)
    for i, m in enumerate(models):
        if ja and m.name == "CORE_BV8_U47":
            models[i] = MagneticCore(m.name, path_m=m.path_m, **ja)
        if spec.get("tube") and m.name == "VF14T_V1_u47":
            t = load_device(spec["tube"])
            models[i] = replace(
                m, plate=t.plate, grid=t.grid, c_gk=t.c_gk, c_gp=t.c_gp, c_pk=t.c_pk
            )
    return over, replace(ir, models=tuple(models)), notes


def variant(label: str, gain_db: int) -> tuple[st.Variant, dict]:
    over, ir, notes = build(VARIANTS[label], gain_db)
    return st.Variant(f"frank-{label}", CHAIN, over, ir=ir), notes


PEAK_MARGIN_DB = 1.0
# The air core's 62 kOhm, high-leakage BV8 has so high an output impedance that the V76's own input
# loading sets its sound: at 34 dB the pad is out, its 2.5 kHz resonance goes undamped and drives the
# V76 past full scale (vocal peaks +1.5 dBFS, residual -27 dB); at 18 dB, padded, the U47 delivers
# 0.06 V and it's clean (-53 dB). The rule's H at 24 dB (padded) doesn't predict 34: it stays at 24.
GAIN_FIX = {"air_core_osmium_uranium": 24}


def predicted_peak_db(x: np.ndarray, f_ms, h_ms, fs: int) -> float:
    """The output peak (dBFS) H predicts for stem `x` at SPL: the linear prediction, absolute."""
    y = cp.apply_power(cp.to_spl(x, SPL, fs), f_ms, h_ms, 1, fs) * 10 ** (level_1k(f_ms, h_ms) / 20)
    return float(20 * np.log10(np.max(np.abs(y))))


def level_1k(f_ms, h_ms) -> float:
    ok = np.flatnonzero(np.isfinite(h_ms))
    return float(20 * np.log10(np.abs(h_ms[ok[np.argmin(np.abs(f_ms[ok] - 1000))]])))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--only", nargs="*", default=list(VARIANTS))
    args = ap.parse_args()
    fs = cp._settings(False).sample_rate
    dry = {s: cp.load_stem(s, fs) for s in STEMS}
    t0 = time.perf_counter()
    with ThreadPoolExecutor(args.workers) as ex:
        first = {lab: variant(lab, 24) for lab in args.only}
        h24 = {lab: ex.submit(cp.measure_h, v, SPL, "production") for lab, (v, _n) in first.items()}
        h24 = {lab: f.result() for lab, f in h24.items()}
        # The V76's gain: the highest switch position whose predicted output peak (the stems at SPL
        # through H at 24 dB, shifted by the step) stays within PEAK_MARGIN_DB of the nominal's. A
        # match at 1 kHz put the resonant variants' peaks past full scale (the first run).
        pk = {
            lab: max(predicted_peak_db(dry[s], *h24[lab], fs) for s in STEMS) for lab in args.only
        }
        ref = pk.get("nominal", -9.0)
        chosen, notes = {}, {}
        for lab in args.only:
            ok = [x for x in V76_STEPS if pk[lab] + (x - 24) <= ref + PEAK_MARGIN_DB]
            g = max(ok) if ok else V76_STEPS[0]
            g = GAIN_FIX.get(lab, g)
            chosen[lab] = variant(lab, g) if g != 24 else first[lab]
            notes[lab] = chosen[lab][1] | {
                "v76_gain_db": g,
                "level_1k_at_24_db_re_nominal": round(
                    level_1k(*h24[lab]) - level_1k(*h24["nominal"]), 2
                )
                if "nominal" in h24
                else None,
                "predicted_peak_at_24_dbfs": round(pk[lab], 2),
            }
        print(json.dumps(notes, indent=1), flush=True)
        hs = {lab: ex.submit(cp.measure_h, v, SPL, "production") for lab, (v, _n) in chosen.items()}
        hs = {lab: f.result() for lab, f in hs.items()}
        jobs = {(lab, s): ex.submit(cp.passes, v, s, dry[s], PASSES, SPL, "production")
                for lab, (v, _n) in chosen.items() for s in STEMS}  # fmt: skip
        ys = {k: f.result() for k, f in jobs.items()}
    print(f"renders done in {(time.perf_counter() - t0) / 60:.1f} min", flush=True)
    report(notes, hs, ys, dry, fs, args.only)


def report(notes, hs, ys, dry, fs, labels) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cp.OUT = OUT
    summary: dict = {}
    for lab in labels:
        f_ms, h_ms = hs[lab]
        e = {"notes": notes[lab], "h_db_re_1k": st.h_points(f_ms, h_ms), "stems": {}}
        for s in STEMS:
            y = ys[(lab, s)]
            e["stems"][s] = {
                f"p{k}": cp.residuals(y, dry[s], SPL, f_ms, h_ms, k, fs) for k in (1, 2, 4)
            }
            e["stems"][s]["peaks_dbfs"] = [cp.peak_dbfs(x) for x in y]
            cp.write(OUT / s / lab / "p1.wav", y[0], fs)
            cp.write(OUT / s / lab / f"p{PASSES}.wav", y[-1], fs)
        summary[lab] = e
    for s in STEMS:
        cp.write(OUT / s / "dry.wav", dry[s], fs)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    plot(hs, labels, OUT / "responses.png")
    f = lambda v: "  n/a" if v is None else f"{v:5.1f}"  # noqa: E731
    for lab, e in summary.items():
        cells = " | ".join(
            " ".join(f(e["stems"][s][p]["residual_vs_dry"]) for p in ("p1", "p4")) for s in STEMS
        )
        print(
            f"{lab:26s} {cells}   H50 {e['h_db_re_1k']['50']:6.1f} H10k {e['h_db_re_1k']['10000']:6.1f}"
        )


def plot(hs, labels, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    for lab in labels:
        f, h = hs[lab]
        ok = np.isfinite(h)
        f, h = f[ok], h[ok]
        db = 20 * np.log10(np.abs(h) / np.abs(h[np.argmin(np.abs(f - 1000))]))
        ax.semilogx(
            f,
            np.convolve(db, np.ones(15) / 15, mode="same"),
            label=lab,
            lw=1.6 if lab == "nominal" else 0.9,
        )
    ax.set_xlim(20, 30000)
    ax.set_ylim(-40, 20)
    ax.grid(True, which="both", alpha=0.3)
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB re 1 kHz, one pass")
    ax.set_title("U47 -> V76, Frankenstein variants")
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()

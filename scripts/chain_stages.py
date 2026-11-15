"""Where in the U47 -> V76 its character is made: the character each stage adds, from probes along
the signal path in one pass (2026-11-14; follows scripts/chain_study.py's attribution, which found
the character nearly unchanged with every core linear).

    uv run --extra fast --extra listen python scripts/chain_stages.py [--workers N]

One pass at chain_passes' staging (100 dB SPL, the V76 at 24 dB), cores Jiles-Atherton and all
linear. Probes: the free-field pressure (the input), the VF14's grid g_u47 and plate a_u47, the
BV8's primary op_u47 and secondary ia_v76 (the V76's input), V1's grid g1_v76 (T85's secondary),
V2's plate pl2_v76 (the V1-V2 feedback pair), V3's grid g3_v76 (after the filters), V4's plate
pl4_v76 (the V3-V4 pair) and `out` (T89's secondary). Each stage's character is
difference.levels(its input, its output): what no fixed filter from one to the other explains.
The cumulative column is the input pressure against each node. The decomposition's floor (its
fit leaks tone into character ~30 dB below the tone) shows on the linear stages.
Writes reports/chain_study/stages.json.

Caveat (found later the same day): `char_db`'s fitted decomposition has a floor as large as
what it measures on this chain (scripts/chain_passes.residual_db's docstring), so these per-stage
figures mostly show that floor: the linear stages read -34 to -66 dB on their own.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chain_passes as cp  # noqa: E402
import chain_study as st  # noqa: E402

from varimu.circuit.ir import VoltageProbe  # noqa: E402
from varimu.sim import fast  # noqa: E402

NODES = ("g_u47", "a_u47", "op_u47", "ia_v76", "g1_v76", "pl2_v76", "g3_v76", "pl4_v76", "out")
STAGES = {
    "g_u47": "capsule (linear: the floor)",
    "a_u47": "VF14 (grid -> plate)",
    "op_u47": "C2 coupling",
    "ia_v76": "BV8",
    "g1_v76": "pad + T85",
    "pl2_v76": "V1 + V2 (feedback pair)",
    "g3_v76": "filters",
    "pl4_v76": "V3 + V4 (feedback pair)",
    "out": "T89",
}


def run(cfg: str, stem: str, fs: int) -> dict:
    keep = st.CORES if cfg == "ja" else ()
    v = st.Variant(cfg, "u47_v76", st.NOM, ir=st.cores_ja("u47_v76", st.NOM, keep))
    ir = replace(v.ir, probes=tuple(VoltageProbe(n) for n in NODES))
    p = cp.to_spl(cp.load_stem(stem, fs), 100.0, fs)
    front, ctl = v.base.entries(p)
    r = fast.run_transient(ir, front, settings=v.base.s, controls=ctl or None)
    sig = {"p": p} | {n: np.asarray(r.vectors[f"v({n})"], float) for n in NODES}
    out = {"stage": {}, "cumulative": {}}
    prev = "p"
    for n in NODES:
        out["stage"][n] = cp.char_db(sig[prev], sig[n], fs)
        out["cumulative"][n] = cp.char_db(sig["p"], sig[n], fs)
        prev = n
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    fs = cp._settings(False).sample_rate
    with ThreadPoolExecutor(args.workers) as ex:
        jobs = {(c, s): ex.submit(run, c, s, fs) for c in ("ja", "linear") for s in st.STEMS}
        res = {k: f.result() for k, f in jobs.items()}
    out = {c: {s: res[(c, s)] for s in st.STEMS} for c in ("ja", "linear")}
    path = st.OUT / "stages.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for c in ("ja", "linear"):
        print(f"== cores {c}: per-stage character (cumulative), dB re signal")
        print(f"{'stage':30s}" + "".join(f"{s:>20s}" for s in st.STEMS))
        for n in NODES:
            cells = []
            for s in st.STEMS:
                r = out[c][s]
                cells.append(
                    f"{r['stage'][n]['character']:6.1f} ({r['cumulative'][n]['character']:6.1f})"
                )
            print(f"{STAGES[n]:30s}" + "".join(f"{x:>20s}" for x in cells))


if __name__ == "__main__":
    main()

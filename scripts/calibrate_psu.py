"""Derive the power supply's unprinted nominals from the values the 670 was set up to.

The drawing doesn't print T302's voltage, L302's resistance or where the B+ ADJ trim
(R313) sits; it prints what they produce. This finds, on the idle unit at the nominal
genome after the supply settles (circuitsim, production settings):

- t302_hv_half_rms_v: the unregulated rail at the middle of the printed "(420V TO 450V)";
- l302_r_ohm: C303 (the 6386 cathode return) at the measured -6.2 V
  (web: https://groupdiy.com/threads/fairchild-670-questions.32169/);
- b_plus_adj: the regulated rail at the printed "(ADJ. TO 240 V.)";

and reports the 6386 bank currents, which ZERO sets (the meter's ZERO position reads
the total plate current; measured ~26 mA per bank, same thread).

    uv run --extra fast python scripts/calibrate_psu.py [--settle 1.5] [--iterations 4]

It prints the values to put in config/circuits/fairchild_670.yaml.
"""

from __future__ import annotations

import argparse
import dataclasses

import numpy as np

from varimu.circuit import netlist as nl
from varimu.circuit.ir import VoltageProbe
from varimu.sim import fast
from varimu.sim.io import TransientSettings

UR_TARGET_V = 435.0  # the middle of "(420V TO 450V)"
NB2_TARGET_V = -6.2
BP_TARGET_V = 240.0
NODES = ("ur", "bp", "nb2", "nb3", "nb4", "sg", "ka", "ta", "kb", "tb", "k1")


def steady(overrides: dict, settle_s: float) -> dict[str, float]:
    """Mean of each node over the last 0.1 s (six 60 Hz cycles) of an idle run."""
    ir = nl.build(overrides).ir
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(n) for n in NODES))
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    s = dataclasses.replace(s, settle_s=0.0)
    n = int(settle_s * s.sample_rate)
    r = fast.run_transient(ir, np.zeros(n), settings=s)
    tail = int(0.1 * s.sample_rate)
    return {k: float(np.mean(r.vectors[f"v({k})"][-tail:])) for k in NODES}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settle", type=float, default=1.5, help="idle run length, s")
    ap.add_argument("--iterations", type=int, default=4)
    args = ap.parse_args()
    p = nl.resolve()
    x = {k: p[k] for k in ("t302_hv_half_rms_v", "l302_r_ohm", "b_plus_adj")}
    for it in range(args.iterations):
        v = steady(x, args.settle)
        r_k = p["r103_r104_ohm"]
        ia, ib = (v["ka"] - v["ta"]) / r_k, (v["kb"] - v["tb"]) / r_k
        print(
            f"[{it}] {x} -> ur {v['ur']:.2f} V, bp {v['bp']:.3f} V, nb2 {v['nb2']:.3f} V, "
            f"nb3 {v['nb3']:.3f} V, nb4 {v['nb4']:.3f} V, sg {v['sg']:.2f} V, k1 {v['k1']:.3f} V, "
            f"banks {1e3 * ia:.2f} / {1e3 * ib:.2f} mA"
        )
        # Proportional updates: the unregulated rail scales with the winding voltage; the
        # drop across L302 with its resistance (the bank current barely moves with it); the
        # divider fraction at the 6084 grid with 1 / bp.
        x["t302_hv_half_rms_v"] *= (UR_TARGET_V + 40) / (v["ur"] + 40)  # ~40 V of drops
        i_l302 = 2 * (ia + ib)  # both channels' 6386 banks
        drop = NB2_TARGET_V - v["nb2"]
        x["l302_r_ohm"] += drop / i_l302  # C303 = C302 + I R
        # wiper fraction f = (100k + (1 - adj) 250k) / 500k scales as bp_now / bp_target
        f = (p["r314_ohm"] + (1 - x["b_plus_adj"]) * p["r313_ohm"]) / (
            p["r312_ohm"] + p["r313_ohm"] + p["r314_ohm"]
        )
        f *= v["bp"] / BP_TARGET_V
        total = p["r312_ohm"] + p["r313_ohm"] + p["r314_ohm"]
        x["b_plus_adj"] = 1 - (f * total - p["r314_ohm"]) / p["r313_ohm"]
        x = {k: round(val, 4) for k, val in x.items()}
    print("nominals:", x)


if __name__ == "__main__":
    main()

"""The filter contour generator alone (docs/MINIMOOG_PLAN.md, MM4): gate on / off, the envelope's shape.

    uv run --extra fast python scripts/minimoog_contour_study.py [--attack A] [--decay D] [--sustain S]
        [--gate-s 1.0] [--total-s 3.0] [--quality production|draft-1x]
"""

import argparse
import dataclasses
import sys

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.sim import fast
from varimu.sim.io import TransientSettings

FS = 96000.0
CIRCUIT = CONFIG_DIR / "circuits" / "minimoog_contour.yaml"


def build(overrides=None):
    s = spec.load_circuit(CIRCUIT)
    return builder.build_ir(s, spec.resolve(s, overrides or {}), "ja")


def run(ir, gate, quality="production"):
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    st = dataclasses.replace(st, settle_s=0.2)
    x = np.zeros(len(gate))
    r = fast.run_transient(ir, x, settings=st, controls={"gate": gate})
    return {k[2:-1]: np.asarray(v) for k, v in r.vectors.items() if k.startswith("v(")}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--attack", type=float, default=0.0)
    p.add_argument("--decay", type=float, default=0.5)
    p.add_argument("--sustain", type=float, default=0.5)
    p.add_argument("--gate-s", type=float, default=1.0)
    p.add_argument("--total-s", type=float, default=3.0)
    p.add_argument("--quality", default="production")
    a = p.parse_args()
    ir = build({"attack": a.attack, "decay": a.decay, "sustain": a.sustain})
    n = int(FS * a.total_s)
    gate = np.zeros(n)
    gate[int(0.2 * FS) : int((0.2 + a.gate_s) * FS)] = 5.0
    v = run(ir, gate, a.quality)
    out, env = v["outn"], v["env"]
    times = [0.0, 0.1, 0.19, 0.2, 0.202, 0.205, 0.21, 0.25, 0.3, 0.5, 0.7, 1.0, 1.19, 1.21, 1.3, 1.6, 2.0, 2.9]
    for t in times:
        i = min(int(t * FS), n - 1)
        print(
            f"t={t:5.3f}  env {env[i]:6.3f}  out {out[i]:6.3f}  col1 {v['col1'][i]:6.3f}  "
            f"tb {v['tb'][i]:6.3f}  e7 {v['e7'][i]:6.3f}"
        )


if __name__ == "__main__":
    sys.exit(main())

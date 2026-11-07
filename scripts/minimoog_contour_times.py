"""Envelope times of the filter contour generator against the panel's ranges (MM4).

The Model D's panel: ATTACK TIME 1 ms to 10 s, DECAY TIME 1 ms to 10 s (the operation manual's
published ranges). Attack = gate on to the output's peak; decay = peak to 1 / e of its fall toward
the
SUSTAIN level; release = gate off to 1 / e of the fall toward 0.

    uv run --extra fast python scripts/minimoog_contour_times.py [--attack-only | --decay-only]
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import minimoog_contour_study as cs  # noqa: E402

FS = cs.FS
T_ON = 0.2


def one(attack, decay, sustain, gate_s, total_s):
    ir = cs.build({"attack": attack, "decay": decay, "sustain": sustain})
    n = int(FS * total_s)
    gate = np.zeros(n)
    gate[int(T_ON * FS) : int((T_ON + gate_s) * FS)] = 5.0
    v = cs.run(ir, gate)
    return v["outn"], v["env"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--attack-only", action="store_true")
    p.add_argument("--decay-only", action="store_true")
    a = p.parse_args()
    if not a.decay_only:
        print(
            "ATTACK (decay 0, sustain 1): time from key-down to the peak (out within 2% of its max)"
        )
        for k in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
            tot = 14.0 if k >= 0.8 else 4.0
            out, _ = one(k, 0.0, 1.0, tot - 0.5, tot)
            seg = out[int(T_ON * FS) :]
            pk = seg.max()
            t10 = np.argmax(seg > 0.1 * pk) / FS
            tpk = np.argmax(seg > 0.98 * pk) / FS
            print(
                f"  attack {k:.1f}: peak {pk:5.2f} V, 10% at {t10 * 1e3:8.1f} ms, "
                f"98% at {tpk * 1e3:9.1f} ms"
            )
    if not a.attack_only:
        print("DECAY (attack 0, sustain 0): peak to 1/e of the fall to the idle level, key held")
        for k in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
            tot = 40.0 if k >= 0.8 else 8.0
            out, _ = one(0.0, k, 0.0, tot - 0.5, tot)
            seg = out[int(T_ON * FS) :]
            pk = seg.max()
            ipk = int(np.argmax(seg))
            tail = seg[-1]
            target = tail + (pk - tail) / np.e
            t = np.argmax(seg[ipk:] < target) / FS
            print(
                f"  decay {k:.1f}: peak {pk:5.2f} V, 1/e after {t * 1e3:9.1f} ms "
                f"(end {tail:5.2f} V)"
            )


if __name__ == "__main__":
    sys.exit(main())

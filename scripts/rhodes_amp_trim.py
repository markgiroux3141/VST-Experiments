"""The Suitcase power amp's factory trims (config/circuits/rhodes_suitcase_100w.yaml,
scripts/make_rhodes_suitcase_100w.py), on the nominal unit, with the input silent and the
speakers connected:

    uv run --extra fast python scripts/rhodes_amp_trim.py [--write] [--iq-ma 25]

1. OFFSET ADJUST (R8): the DC voltage at the output node (before the fuse) to 0 V.
2. BIAS ADJ (R12): the output stage's quiescent current, read as the voltage across Q8's
   emitter resistor, to IQ_MA (a provisional target: fig11-3 and the manual publish none;
   25 mA is 10 mV across the 0.4 ohm pair, what a ~50 W class AB output stage of this kind
   is usually set to; the pot can't go much higher: CR4-CR7 clamp the bias string at ~29 mA
   with these diodes, which is the circuit's own limit, the pot only lowers it).

Both are found together (they interact a little): a Newton step on the pair of rotations
with a finite-difference Jacobian, per board. The runs are short drafts (Newton 1e-5, no
speaker readout: the electrical load is the same) averaged over whole mains cycles.
--write puts the four rotations into the generator's constants and regenerates the circuit.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varimu.circuit import builder  # noqa: E402
from varimu.circuit.spec import load_circuit, resolve  # noqa: E402

GEN = ROOT / "scripts" / "make_rhodes_suitcase_100w.py"
CIRCUIT = ROOT / "config" / "circuits" / "rhodes_suitcase_100w.yaml"
IQ_MA = 25.0
R_EMIT = 0.4


def settings():
    from varimu.sim import io

    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    return dataclasses.replace(st, newton_reltol=1e-5, newton_vntol=1e-5, settle_s=0.4)


def measure(spec, x: str, bias: float, offset: float, others: dict) -> tuple[float, float]:
    """(output offset in V, Q8's quiescent current in mA) of board `x`."""
    from varimu.sim import fast

    st = settings()
    q = dict(resolve(spec))
    q.update(accessory_in=1, vibrato=0, **others)
    q[f"bias_{x}"], q[f"offset_{x}"] = bias, offset
    ir = builder.build_ir(spec, q, speaker_readout=False)
    n = int(0.12 * st.sample_rate)
    v = fast.run_transient(ir, np.zeros(n), settings=st).vectors
    k = int(0.05 * st.sample_rate)  # three mains cycles at 60 Hz
    out = float(np.mean(v[f"v({x}_amp)"][-k:]))
    iq = 1000.0 * (float(np.mean(v[f"v({x}_e8)"][-k:])) - out) / R_EMIT
    return out, iq


def trim_board(spec, x: str, iq_ma: float, others: dict, verbose=True) -> tuple[float, float]:
    b, o = 0.5, 0.5
    for _it in range(8):
        f0 = np.array(measure(spec, x, b, o, others))
        err = f0 - np.array([0.0, iq_ma])
        if verbose:
            print(f"  {x}: bias {b:.4f} offset {o:.4f} -> out {f0[0]:+.4f} V, Iq {f0[1]:.2f} mA")
        if abs(err[0]) < 1e-3 and abs(err[1]) < 0.3:
            break
        h = 0.02
        fb = (np.array(measure(spec, x, min(b + h, 1.0), o, others)) - f0) / h
        fo = (np.array(measure(spec, x, b, min(o + h, 1.0), others)) - f0) / h
        jac = np.column_stack([fb, fo])
        step = np.linalg.lstsq(jac, -err, rcond=1e-6)[0]
        b = float(np.clip(b + np.clip(step[0], -0.3, 0.3), 0.0, 1.0))
        o = float(np.clip(o + np.clip(step[1], -0.3, 0.3), 0.0, 1.0))
    return b, o


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--iq-ma", type=float, default=IQ_MA)
    a = ap.parse_args()
    spec = load_circuit(CIRCUIT)
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(trim_board, spec, "a", a.iq_ma, {})
        fb = ex.submit(trim_board, spec, "b", a.iq_ma, {})
        (ba, oa), (bb, ob) = fa.result(), fb.result()
    print(f"A: BIAS {ba:.4f} OFFSET {oa:.4f}   B: BIAS {bb:.4f} OFFSET {ob:.4f}")
    if a.write:
        text = GEN.read_text(encoding="utf-8")
        for name, val in (("OFFSET_A", oa), ("OFFSET_B", ob), ("BIAS_A", ba), ("BIAS_B", bb)):
            text, k = re.subn(rf"^{name} = [0-9.]+", f"{name} = {val:.4f}", text, flags=re.M)
            assert k == 1, name
        GEN.write_text(text, encoding="utf-8")
        import subprocess

        subprocess.run([sys.executable, str(GEN)], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

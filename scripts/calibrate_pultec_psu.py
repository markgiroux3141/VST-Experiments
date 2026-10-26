"""Derive the Pultec EQP-1A's mains transformer voltage from the drawing's rail voltage.

    uv run --extra fast python scripts/calibrate_pultec_psu.py

DWG E-72,658-2 prints the supply's voltages ("typical average values read on an
11 megohm voltmeter, no input signal"): +355 V at the 6X4 cathode, +345, +325,
+290 and +250 V down the RC filter. The PCC-55's HV winding isn't documented, so
`pcc55_hv_half_rms_v` is set so that the settled +325 V node (b2: after the
first two filter sections, where the ripple is under 0.1 V) reads 325 V at the
nominal genome. Idle runs of 6 s from the DC operating point (the mains at their
peak), averaged over the last 0.5 s; secant steps on the voltage. Prints the value
for config/circuits/pultec_eqp1a.yaml and every printed rail next to the run's.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io

CIRCUIT = CONFIG_DIR / "circuits" / "pultec_eqp1a.yaml"
TARGET_NODE, TARGET_V = "b2", 325.0
RUN_S, AVERAGE_S = 6.0, 0.5
DRAWING_V = {"b0": 355.0, "b1": 345.0, "b2": 325.0, "b3": 290.0, "b4": 250.0, "htr": 60.0}


def rails(hv_rms: float) -> dict[str, float]:
    s = spec.load_circuit(CIRCUIT)
    c = builder.build(s, {"pcc55_hv_half_rms_v": hv_rms}, cores="ja")
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim"), settle_s=0.0
    )
    x = np.zeros(int(RUN_S * st.sample_rate))
    v = fast.run_transient(c.ir, x, settings=st).vectors
    n = int(AVERAGE_S * st.sample_rate)
    return {k: float(np.mean(v[f"v({k})"][-n:])) for k in DRAWING_V}


def main() -> None:
    s = spec.load_circuit(CIRCUIT)
    x0 = float(s.values["pcc55_hv_half_rms_v"]["value"])
    f0 = rails(x0)[TARGET_NODE] - TARGET_V
    x1 = x0 * TARGET_V / (TARGET_V + f0)
    for _ in range(6):
        r = rails(x1)
        f1 = r[TARGET_NODE] - TARGET_V
        print(f"hv {x1:.2f} V rms: {TARGET_NODE} {r[TARGET_NODE]:.2f} V")
        if abs(f1) < 0.05:
            break
        x0, f0, x1 = x1, f1, x1 - f1 * (x1 - x0) / (f1 - f0)
    print(f"\npcc55_hv_half_rms_v: {x1:.1f}")
    for k, d in DRAWING_V.items():
        print(f"  {k:4s} drawing {d:6.1f} V   sim {r[k]:7.2f} V")


if __name__ == "__main__":
    main()

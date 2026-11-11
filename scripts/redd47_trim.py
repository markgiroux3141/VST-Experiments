"""Trim the REDD.47's FINE GAIN preset (VR1) for 40 dB at the mid position (CHAINS_PLAN.md WP28).

    uv run --extra fast python scripts/redd47_trim.py [--write]

REDD.M47 p. 5: "the pre-set gain control should be re-adjusted to give the nominal ... insertion
gain at the mid-position of the switch" (the gain from the input terminals into the 200 ohm test
load, 1 kHz). The fraction of VR1's 5k in circuit (`fine_gain`) is solved for 40.00 dB; `--write`
puts it into config/circuits/emi_redd47.yaml.
"""

from __future__ import annotations

import argparse
import re

import numpy as np
from scipy.optimize import brentq

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.measure import metrics
from varimu.sim import fast
from varimu.sim.io import TransientSettings

CIRCUIT = CONFIG_DIR / "circuits" / "emi_redd47.yaml"
TARGET_DB = 40.0


def gain_db(u, over: dict, f0: float = 1000.0) -> float:
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    t = np.arange(int(0.3 * fs)) / fs
    x = 1e-3 * np.sqrt(2) * np.sin(2 * np.pi * f0 * t) * np.minimum(1, t / 0.05)
    v = fast.run_transient(builder.build(u, over).ir, x, settings=s).vectors
    o = metrics.harmonics(v["v(out)"][-fs // 5 :], f0, fs).amps[0]
    i = metrics.harmonics(v["v(ia)"][-fs // 5 :], f0, fs).amps[0]
    return float(20 * np.log10(o / i))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    u = spec.load_circuit(CIRCUIT)
    lo, hi = gain_db(u, {"gain": 40, "fine_gain": 1.0}), gain_db(u, {"gain": 40, "fine_gain": 0.0})
    print(f"VR1 range at 40: {lo:.2f} .. {hi:.2f} dB")
    if not lo <= TARGET_DB <= hi:
        raise SystemExit("40 dB is outside VR1's range")
    x = brentq(lambda f: gain_db(u, {"gain": 40, "fine_gain": f}) - TARGET_DB, 0.0, 1.0, xtol=1e-4)
    print(f"fine_gain {x:.4f}")
    for g in (34, 40, 46):
        print(g, round(gain_db(u, {"gain": g, "fine_gain": x}), 2), "dB")
    if args.write:
        text = CIRCUIT.read_text(encoding="utf-8")
        text, n = re.subn(r"(  fine_gain: \{value: )[0-9.]+", rf"\g<1>{x:.4f}", text)
        if n != 1:
            raise SystemExit("emi_redd47.yaml: no fine_gain line")
        CIRCUIT.write_text(text, encoding="utf-8")
        print("written")


if __name__ == "__main__":
    main()

"""Fit the Jensen JT-115K-E's unknowns to Jensen's sheet (docs/CHAINS_PLAN.md WP4, step 2).

The circuit is Jensen's test circuit 1, config/circuits/jt115k_test.yaml (150 ohm source,
150k load); levels are at the primary's terminals, as Jensen's "all levels are input",
and responses are from the source's EMF (the sheet's "-3 dB at 2.5 Hz" includes the
150 ohm source's loading). Ratio and DC resistances are the sheet's; the primary's turns
are provisional (1300: with 19.7 / 2465 ohm, ~0.17 / ~0.063 mm wire on a ~3 mm core, see
the circuit file). One figure per unknown, in turn:

1. the core's area: 1% THD at 20 Hz at -2.5 dBu (the sheet's "maximum 20 Hz input level");
2. the joint gap: -3 dB at 2.5 Hz (the front page's bandwidth), redone after step 1;
3. the leakage and the secondary's capacitance: -0.13 dB at 20 kHz and -3 dB at 90 kHz,
   on the linear-core build's AC analysis (varimu.measure.ac: 90 kHz is past the 96 kHz
   grid's Nyquist; the transient agrees with it within 0.011 dB at 20 kHz).

Steps 1 and 2 depend on each other a little; they are iterated twice. Prints the values to
copy into jt115k_test.yaml and ssl_4000e.yaml and the checks (input impedance, gain, the
20 Hz response, THD at -20 dBu) the fit doesn't target. ~5 min (`--hf`: step 3 alone, from
the circuit file's area and gap).

    uv run --extra fast python scripts/fit_jt115k.py [--hf]
"""

from __future__ import annotations

import sys

import numpy as np
from scipy.optimize import brentq, least_squares

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.measure import ac
from varimu.measure.transformer_sheet import measure, response_db

CIRCUIT = CONFIG_DIR / "circuits" / "jt115k_test.yaml"
F_HF = np.array([1e3, 20e3, 90e3])


def main() -> None:
    c = spec.load_circuit(CIRCUIT)
    q = spec.resolve(c)
    keys = ("jt_core_area_m2", "jt_gap_m", "jt_leakage_h", "jt_c_sec_f")
    ov = {k: q[k] for k in keys}

    for it in range(0 if "--hf" in sys.argv else 2):

        def thd_excess(log_a: float) -> float:
            o = dict(ov, jt_core_area_m2=np.exp(log_a))
            return np.log(measure(c, o, 20.0, -2.5)["thd"] / 0.01)

        a = brentq(thd_excess, np.log(5e-6), np.log(1.2e-5), xtol=0.01)
        ov["jt_core_area_m2"] = float(np.exp(a))
        print(f"[{it}] area {ov['jt_core_area_m2']:.4g} m^2", flush=True)

        def lf_excess(log_g: float) -> float:
            return response_db(c, dict(ov, jt_gap_m=np.exp(log_g)), 2.5) + 3.0

        ov["jt_gap_m"] = float(np.exp(brentq(lf_excess, np.log(2e-7), np.log(2e-5), xtol=0.01)))
        print(f"[{it}] gap {ov['jt_gap_m']:.4g} m", flush=True)

    def hf(v: np.ndarray) -> np.ndarray:
        o = dict(ov, jt_leakage_h=float(np.exp(v[0])), jt_c_sec_f=float(np.exp(v[1])))
        h = ac.transfer(builder.build_ir(c, spec.resolve(c, o), cores="linear"), F_HF, "out")
        db = 20 * np.log10(np.abs(h / h[0]))
        return np.array([db[1] + 0.13, db[2] + 3.0])

    x0 = np.log([ov["jt_leakage_h"], ov["jt_c_sec_f"]])
    r = least_squares(hf, x0, diff_step=1e-4, xtol=1e-6)
    ov["jt_leakage_h"], ov["jt_c_sec_f"] = (float(v) for v in np.exp(r.x))
    print(f"leakage {ov['jt_leakage_h']:.4g} H, c_sec {ov['jt_c_sec_f']:.4g} F", flush=True)

    print("\nfitted:", {k: float(f"{v:.4g}") for k, v in ov.items()})
    m1 = measure(c, ov, 1000.0)
    print(f"1 kHz, -20 dBu: gain {m1['gain_db']:.2f} dB (jensen 19.75), "
          f"Zin {m1['zin_ohm']:.0f} ohm (1400), THD {100 * m1['thd']:.4f}% (0.001)")  # fmt: skip
    for f, ref in ((2.5, -3.0), (20.0, -0.26), (20e3, -0.13)):
        print(f"{f:g} Hz re 1 kHz: {response_db(c, ov, f):+.2f} dB (jensen {ref:+.2f})")
    h = ac.transfer(builder.build_ir(c, spec.resolve(c, ov), cores="linear"), F_HF, "out")
    print(
        f"90 kHz re 1 kHz (AC, linear core): {20 * np.log10(abs(h[2] / h[0])):+.2f} dB"
        " (jensen -3.00)"
    )
    for lv, ref in ((-20.0, 0.065), (-2.5, 1.0)):
        print(f"20 Hz THD at {lv} dBu: {100 * measure(c, ov, 20.0, lv)['thd']:.3f}% (jensen {ref})")


if __name__ == "__main__":
    main()

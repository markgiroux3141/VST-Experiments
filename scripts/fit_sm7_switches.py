"""Fit the SM7's switch networks to the sheet's traces (docs/CHAINS_PLAN.md WP15).

    uv run python scripts/fit_sm7_switches.py [--write]

Shure's SM7B specification draws the bass roll-off (50-356 Hz) and the presence (0.7-10 kHz)
settings over the flat response (data/datasheets/shure_sm7_response.csv, digitized by
scripts/digitize_shure_sm7.py). Shure's network isn't published: config/circuits/shure_sm7.yaml
has the simplest passive forms (the roll-off a shunt L-R across the coil; the presence a series R
parallel to a series L-C into a shunt R), and their values are fitted here by small-signal AC
analysis of the whole microphone (varimu.measure.ac on the built IR: the cartridge's motional
impedance included), on axis into the open circuit the sheet's curves are measured in. Each
setting's response over the flat's, in dB, against the traces' difference from the flat trace; the
roll-off absolutely (both meet above the roll-off), the presence up to a constant (the chart draws
its curve re the flat's level; a passive emphasis cuts the rest). `--write` puts the values into
the circuit file.
"""

from __future__ import annotations

import argparse
import csv
import re

import numpy as np
from scipy.optimize import least_squares

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, DATA_DIR
from varimu.measure import ac

PATH = CONFIG_DIR / "circuits" / "shure_sm7.yaml"


def traces() -> dict[str, np.ndarray]:
    out: dict[str, list] = {}
    with open(DATA_DIR / "datasheets" / "shure_sm7_response.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.setdefault(r["setting"], []).append((float(r["freq_hz"]), float(r["db"])))
    return {k: np.array(v) for k, v in out.items()}


def targets() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    t = traces()
    fl = t["flat"]

    def rel(name):
        f, db = t[name][:, 0], t[name][:, 1]
        return f, db - np.interp(np.log(f), np.log(fl[:, 0]), fl[:, 1])

    return {"rolloff": rel("rolloff"), "presence": rel("presence")}


def response_db(c, over: dict, f: np.ndarray) -> np.ndarray:
    ir = builder.build(c, over, cores="linear").ir
    h = ac.transfer(ir, f, "out", drives={"p_rear": np.zeros(len(f), complex)})
    return 20 * np.log10(np.abs(h))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    c = spec.load_circuit(PATH)
    tg = targets()

    f_b, d_b = tg["rolloff"]
    flat_b = response_db(c, {}, f_b)

    def res_b(x):
        lb, rb = np.exp(x)
        r = response_db(c, {"bass_rolloff": 1, "lb_h": lb, "rb_ohm": rb}, f_b) - flat_b
        return r - d_b

    sb = least_squares(res_b, np.log([0.2, 50.0]), bounds=(np.log([1e-3, 0.01]), np.log([20, 5e3])))
    lb, rb = np.exp(sb.x)
    rms_b = float(np.sqrt(np.mean(sb.fun**2)))
    mx_b = float(np.abs(sb.fun).max())
    print(f"roll-off: L {lb:.4g} H, R {rb:.4g} ohm; rms {rms_b:.2f} dB, max {mx_b:.2f}")

    f_p, d_p = tg["presence"]
    flat_p = response_db(c, {}, f_p)

    def res_p(x):
        rp, lp, cp = np.exp(x)
        r = response_db(c, {"presence": 1, "rp_ohm": rp, "lp_h": lp, "cp_f": cp}, f_p) - flat_p
        e = r - d_p
        return e - e.mean()  # up to a constant (the chart's re-normalization)

    best = None
    for f0 in (2500.0, 4000.0):
        for lp0 in (0.01, 0.05):
            cp0 = 1 / ((2 * np.pi * f0) ** 2 * lp0)
            s = least_squares(
                res_p, np.log([800.0, lp0, cp0]),
                bounds=(np.log([10.0, 1e-4, 1e-10]), np.log([1e5, 2.0, 1e-4])),
            )  # fmt: skip
            if best is None or s.cost < best.cost:
                best = s
    rp, lp, cp = np.exp(best.x)
    r_p = response_db(c, {"presence": 1, "rp_ohm": rp, "lp_h": lp, "cp_f": cp}, f_p) - flat_p
    off = float(np.mean(r_p - d_p))
    rms_p = float(np.sqrt(np.mean(best.fun**2)))
    f0 = 1 / (2 * np.pi * np.sqrt(lp * cp))
    print(
        f"presence: R {rp:.4g} ohm, L {lp:.4g} H, C {cp:.4g} F (f0 {f0:.0f} Hz); rms "
        f"{rms_p:.2f} dB, max {np.abs(best.fun).max():.2f}; its level {off:+.2f} dB re the chart's"
    )
    f1k = np.array([1000.0])
    lvl = response_db(c, {"presence": 1, "rp_ohm": rp, "lp_h": lp, "cp_f": cp}, f1k)
    print(f"presence at 1 kHz re flat: {float(lvl[0] - response_db(c, {}, f1k)[0]):+.2f} dB")
    if args.write:
        text = PATH.read_text(encoding="utf-8")
        src_b = "fit: scripts/fit_sm7_switches.py, to the sheet's roll-off trace"
        src_p = "fit: scripts/fit_sm7_switches.py, to the sheet's presence trace (against rsh_ohm)"
        for key, val, src in (
            ("lb_h", lb, src_b), ("rb_ohm", rb, src_b),
            ("rp_ohm", rp, src_p), ("lp_h", lp, src_p), ("cp_f", cp, src_p),
        ):  # fmt: skip
            text, n = re.subn(
                rf"  {key}: \{{value: [^,]+, source: \"[^\"]*\"\}}",
                f'  {key}: {{value: {val:.4g}, source: "{src}"}}',
                text,
            )
            assert n == 1, key
        PATH.write_text(text, encoding="utf-8")
        print("written", PATH)


if __name__ == "__main__":
    main()

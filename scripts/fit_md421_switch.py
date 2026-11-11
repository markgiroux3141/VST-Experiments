"""Fit the MD 421's bass roll-off switch to the sheet's traces (docs/CHAINS_PLAN.md WP14).

    uv run python scripts/fit_md421_switch.py [--write]

The sheet draws the four roll-off positions over M (flat; data/datasheets/
sennheiser_md421_response.csv, digitized by scripts/digitize_md421.py). Sennheiser's network
isn't published: config/circuits/sennheiser_md421.yaml has, per position, a shunt L-R across the
coil (the simplest passive form), fitted here as scripts/fit_sm7_switches.py fits the SM7's: by
small-signal AC analysis of the whole microphone (the cartridge's motional impedance included),
on axis into the sheet's open circuit, each position's response over M against its trace's
difference from M (50 Hz - 16 kHz). `--write` puts the values into the circuit file.
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

PATH = CONFIG_DIR / "circuits" / "sennheiser_md421.yaml"


def targets() -> dict[int, tuple[np.ndarray, np.ndarray]]:
    t: dict[str, list] = {}
    with open(DATA_DIR / "datasheets" / "sennheiser_md421_response.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t.setdefault(r["trace"], []).append((float(r["freq_hz"]), float(r["dbv_per_pa"])))
    m = np.array(t["M"])
    out = {}
    for n in range(1, 5):
        v = np.array(t[f"dip{n}"])
        v = v[(v[:, 0] >= m[0, 0]) & (v[:, 0] <= m[-1, 0])]
        out[n] = (v[:, 0], v[:, 1] - np.interp(np.log(v[:, 0]), np.log(m[:, 0]), m[:, 1]))
    return out


def response_db(c, over: dict, f: np.ndarray) -> np.ndarray:
    ir = builder.build(c, over, cores="linear").ir
    h = ac.transfer(ir, f, "out", drives={"p_rear": np.zeros(len(f), complex)})
    return 20 * np.log10(np.abs(h))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    c = spec.load_circuit(PATH)
    fitted = {}
    for n, (f, d) in targets().items():
        flat = response_db(c, {}, f)

        def res(x, n=n, f=f, d=d, flat=flat):
            lb, rb = np.exp(x)
            over = {"bass": n, f"lb{n}_h": lb, f"rb{n}_ohm": rb}
            return response_db(c, over, f) - flat - d

        best = None
        for lb0 in (0.01, 0.1, 1.0):
            for rb0 in (10.0, 300.0):
                s = least_squares(
                    res, np.log([lb0, rb0]), bounds=(np.log([1e-4, 0.01]), np.log([50.0, 1e5]))
                )
                if best is None or s.cost < best.cost:
                    best = s
        lb, rb = np.exp(best.x)
        fitted[n] = (lb, rb)
        rms = float(np.sqrt(np.mean(best.fun**2)))
        i = int(np.argmax(np.abs(best.fun)))
        mx = float(abs(best.fun[i]))
        print(f"position {n}: L {lb:.4g} H, R {rb:.4g} ohm; rms {rms:.2f} dB, max {mx:.2f}", end="")
        print(f" at {f[i]:.0f} Hz")
    if args.write:
        text = PATH.read_text(encoding="utf-8")
        src = "fit: scripts/fit_md421_switch.py, to the sheet's trace of this position re M"
        for n, (lb, rb) in fitted.items():
            for key, val in ((f"lb{n}_h", lb), (f"rb{n}_ohm", rb)):
                text, k = re.subn(
                    rf"  {key}: \{{value: [^,]+, source: \"[^\"]*\"\}}",
                    f'  {key}: {{value: {val:.4g}, source: "{src}"}}',
                    text,
                )
                assert k == 1, key
        PATH.write_text(text, encoding="utf-8")
        print("written", PATH)


if __name__ == "__main__":
    main()

"""The Uni-Vibe's photocells trimmed to a measured unit (docs/MODULATION_PLAN.md, MD1).

Each cell's illuminance at 2856 K (`ldrN_lux` in config/circuits/univibe.yaml: its place in
the lamp's box, the one thing about the light path the sources don't give) is set so that its
minimum resistance over the sweep, at full INTENSITY and over SPEED, is the DAFx-19 paper's
measured minimum (Darabundit, Wedelich, Bischoff, Table 1: 12.7, 6.86, 7.69, 6.22 kOhm;
the paper's unit was measured over 14 speeds and 11 intensities, so its minimum is the
whole wavetable's). A cell's resistance falls about as the 0.9th power of its light near
there, so each pass scales the lux by (R_min / target)^(1 / 0.9); three passes converge to
~1%.

    uv run --extra fast python scripts/univibe_trim.py [--write] [--passes 3]

Prints each pass and the resulting maxima beside the paper's (2.79, 2.59, 3.32, 4.16 MOhm);
--write puts the lux values into the circuit file (their sources say where they came from).
"""

from __future__ import annotations

import argparse
import dataclasses
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.devices.library import load_device
from varimu.sim import fast, io

CIRCUIT = "univibe"
TARGET_MIN_OHM = (12.7e3, 6.86e3, 7.69e3, 6.22e3)  # DAFx-19 Table 1, "min. (k)"
PAPER_MAX_OHM = (2.79e6, 2.59e6, 3.32e6, 4.16e6)  # Table 1, "max. (M)"
PAPER_AVG_OHM = (0.405e6, 0.233e6, 0.29e6, 0.240e6)  # Table 1, "avg (M)"
SPEEDS = (0.25, 0.5, 0.75, 1.0)
RUN_S = 6.0  # the LFO starts at its amplitude (C20's kick); the last 3 s are measured
MEASURE_S = 3.0
SLOPE = 0.9  # the PDV-P9203's sensitivity (log R per log lux)


def cell_resistances(lux: list[float], speed: float, intensity: float = 1.0) -> np.ndarray:
    """Each cell's resistance (4, n) over the measured stretch of a run, silent input."""
    s = spec.load_circuit(spec.circuit_path(CIRCUIT))
    sets = {f"ldr{k + 1}_lux": lux[k] for k in range(4)}
    sets |= {"speed": speed, "intensity": intensity}
    ir = builder.build_ir(s, spec.resolve(s, sets))
    probes = [f"ps{k}" for k in range(1, 5)] + [f"l{k}b" for k in range(1, 5)]
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    n = round(RUN_S * st.sample_rate)
    v = fast.run_transient(ir, np.zeros(n), settings=st).vectors
    m = round(MEASURE_S * st.sample_rate)
    cell = load_device(str(spec.resolve(s)["ldr_model"]))
    out = []
    for k in range(1, 5):
        g = (v[f"v(ps{k})"][-m:] - v[f"v(l{k}b)"][-m:]) * cell.s_unit_s
        out.append(1.0 / (cell.g_dark_s + np.maximum(g, 0.0)))
    return np.array(out)


def sweep(lux: list[float]) -> dict[float, np.ndarray]:
    with ThreadPoolExecutor(len(SPEEDS)) as ex:
        runs = list(ex.map(lambda sp: cell_resistances(lux, sp), SPEEDS))
    return dict(zip(SPEEDS, runs, strict=True))


def write(lux: list[float]) -> None:
    path = spec.circuit_path(CIRCUIT)
    text = path.read_text(encoding="utf-8")
    for k in range(4):
        pat = re.compile(rf"^  ldr{k + 1}_lux: \{{value: [^,]+, source: \"[^\"]*\"\}}$", re.M)
        src = (
            f"scripts/univibe_trim.py: LDR{k + 1}'s illuminance at 2856 K (its place in the "
            f"lamp's box), trimmed so its minimum resistance at full INTENSITY over SPEED is "
            f"the DAFx-19 paper's measured {TARGET_MIN_OHM[k] / 1e3:g} kOhm (Table 1)"
        )
        new = f'  ldr{k + 1}_lux: {{value: {lux[k]:.1f}, source: "{src}"}}'
        text, count = pat.subn(new, text)
        if count != 1:
            raise SystemExit(f"ldr{k + 1}_lux: not found in {path}")
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--passes", type=int, default=3)
    args = ap.parse_args()
    s = spec.load_circuit(spec.circuit_path(CIRCUIT))
    vals = spec.resolve(s)
    lux = [float(vals[f"ldr{k}_lux"]) for k in range(1, 5)]
    for p in range(args.passes):
        runs = sweep(lux)
        rmin = np.min([r.min(axis=1) for r in runs.values()], axis=0)
        print(f"pass {p + 1}: lux {[round(x, 1) for x in lux]}")
        print("  min kOhm   " + "  ".join(f"{x / 1e3:7.2f}" for x in rmin))
        lux = [float(lux[k] * (rmin[k] / TARGET_MIN_OHM[k]) ** (1.0 / SLOPE)) for k in range(4)]
    runs = sweep(lux)
    print(f"final lux {[round(x, 1) for x in lux]}")
    for sp, r in runs.items():
        print(
            f"  speed {sp:4.2f}: min kOhm "
            + " ".join(f"{x / 1e3:7.2f}" for x in r.min(axis=1))
            + "   max MOhm "
            + " ".join(f"{x / 1e6:5.2f}" for x in r.max(axis=1))
            + "   mean MOhm "
            + " ".join(f"{x / 1e6:5.3f}" for x in r.mean(axis=1))
        )
    print("  paper:          min kOhm " + " ".join(f"{x / 1e3:7.2f}" for x in TARGET_MIN_OHM))
    print("                  max MOhm " + " ".join(f"{x / 1e6:5.2f}" for x in PAPER_MAX_OHM))
    print("                  avg MOhm " + " ".join(f"{x / 1e6:5.3f}" for x in PAPER_AVG_OHM))
    if args.write:
        write(lux)


if __name__ == "__main__":
    main()

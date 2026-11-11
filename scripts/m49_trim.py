"""The M 49 c's two values chosen on test (docs/CHAINS_PLAN.md WP29): BV 11's ratio and C4.

    uv run --extra fast python scripts/m49_trim.py [--write]

No winding data of the BV 11 were found (data/schematics/neumann_m49/README.md): its ratio is
fitted to the product description's source resistance, 200 ohm (+-20%), at 1 kHz (the output
with RLOAD's 1000 ohm against an open output). C4 ("ca. 8 pF abgleichen / selected" on the
drawing, grid to anode) is fitted to the product description's "gain of microphone amplifier at
1 kc/s: 0 dB": the output into 1000 ohm over the calibrating voltage at St1 pin 8 (the cal line,
probe `cal`), cardioid. The two interact a little (the ratio scales the gain), so they are solved
in turn until both hold. `--write` puts them into config/circuits/neumann_m49.yaml.
"""

from __future__ import annotations

import argparse
import re

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.sim import fast
from varimu.sim.io import TransientSettings

PATH = CONFIG_DIR / "circuits" / "neumann_m49.yaml"
F_HZ = 1000.0
CAL_V = 0.01  # 10 mV peak at the calibrating input: small signal
TARGET_OHM = 200.0
TARGET_GAIN_DB = 0.0


def _amp(y: np.ndarray, fs: float) -> float:
    t = np.arange(len(y)) / fs
    c = np.exp(-2j * np.pi * F_HZ * t)
    return float(2 * abs(np.mean(y * c)))


def measure(c, sets: dict) -> dict:
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    n = int(0.5 * fs)
    tail = int(0.1 * fs)
    z = np.zeros(n)
    out = {}
    for name, load in (("loaded", None), ("open", 1e9)):
        over = {"cal_v": CAL_V, "cal_hz": F_HZ, "pattern": 4, **sets}
        if load is not None:
            over["r_load_ohm"] = load
        ir = builder.build_ir(c, spec.resolve(c, over))
        v = fast.run_transient(ir, z, settings=s, controls={"p_rear": z}).vectors
        out[name] = _amp(np.asarray(v["v(out)"])[-tail:], fs)
        if name == "loaded":
            out["cal"] = _amp(np.asarray(v["v(cal)"])[-tail:], fs)
    out["z_ohm"] = 1000.0 * (out["open"] / out["loaded"] - 1.0)
    out["gain_db"] = 20 * np.log10(out["loaded"] / out["cal"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    c = spec.load_circuit(PATH)
    p = spec.resolve(c)
    ratio, c4 = p["t_ratio"], p["c4_f"]
    for it in range(4):
        m = measure(c, {"t_ratio": ratio, "c4_f": c4})
        print(
            f"it {it}: ratio {ratio:.5f} C4 {c4 * 1e12:.2f} pF -> {m['z_ohm']:.1f} ohm, "
            f"gain {m['gain_db']:+.2f} dB",
            flush=True,
        )
        if abs(m["z_ohm"] - TARGET_OHM) < 1.0 and abs(m["gain_db"] - TARGET_GAIN_DB) < 0.02:
            break
        # the source impedance goes with the ratio squared (the winding resistances aside)
        ratio *= np.sqrt(TARGET_OHM / m["z_ohm"])
        m2 = measure(c, {"t_ratio": ratio, "c4_f": c4})
        # the gain: a secant on C4 (more C4, more Miller loading at the grid, less gain)
        dc = 0.5e-12
        m3 = measure(c, {"t_ratio": ratio, "c4_f": c4 + dc})
        slope = (m3["gain_db"] - m2["gain_db"]) / dc
        c4 = c4 + (TARGET_GAIN_DB - m2["gain_db"]) / slope
    m = measure(c, {"t_ratio": ratio, "c4_f": c4})
    print(f"final: ratio {ratio:.5f} C4 {c4 * 1e12:.3f} pF:", end=" ")
    print(f"{m['z_ohm']:.1f} ohm, {m['gain_db']:+.3f} dB")
    if args.write:
        text = PATH.read_text(encoding="utf-8")
        text = re.sub(
            r"  t_ratio: \{value: [^,]+, source: \"[^\"]*\"\}",
            f"  t_ratio: {{value: {ratio:.5f}, source: \"fit: scripts/m49_trim.py, pd's source "
            f"resistance 200 ohm at 1 kHz (BV 11's ratio unpublished)\"}}",
            text,
        )
        text = re.sub(
            r"  c4_f: \{value: [^,]+, source: \"[^\"]*\"\}",
            f"  c4_f: {{value: {c4:.4g}, source: \"fit: scripts/m49_trim.py, sch: C4 'ca. 8 pF "
            f"abgleichen / selected' for pd's 'gain of microphone amplifier at 1 kc/s: 0 dB' (the "
            f'output into 1000 ohm over the calibrating voltage, cardioid)"}}',
            text,
        )
        PATH.write_text(text, encoding="utf-8")
        print("written", PATH)


if __name__ == "__main__":
    main()

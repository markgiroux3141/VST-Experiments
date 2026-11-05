"""The SM57 into its loads (SM57_PLAN.md SM5's loading checks) -> reports/mics/sm57_loading.json.

    uv run --extra fast python scripts/sm57_loading.py

The circuit (config/circuits/shure_sm57.yaml: the cartridge, the transformer, the H / L
switch) renders tones at the front entry, the rear at zero (a front-only drive: the loads
change the electrical side, not the acoustics' share), into each load in place of the open
circuit's RLOAD: the level re open circuit per frequency, and the output impedance from two
loads (Thevenin at 1 kHz). The published figures to compare (data/schematics/shure_sm57/
README.md): hau, "into 2,000 ohm ... about 1 dB ... into 250 ohm ... 6 dB" (an SM57 / SM58
of the 310 ohm era); the ratings (s68 'H' 150-250 ohm, 'L' 30-50 ohm; c88 '310 ohms actual';
ee18 a vintage SM57 '228 ohm' at 1.28 kHz). The JA core at a low level (a tone of 0.1 Pa
peak, 74 dB SPL) as a quiet source sees it.
"""

from __future__ import annotations

import json

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.sim import fast
from varimu.sim.io import TransientSettings

LOADS_OHM = (150.0, 250.0, 600.0, 2000.0, 2500.0, 1.0e6)
TONES_HZ = np.array([50.0, 100.0, 1000.0, 5000.0, 10000.0])
PEAK_PA = 0.1


def render(load_ohm: float, impedance: int, s: TransientSettings) -> np.ndarray:
    c = spec.load_circuit(spec.circuit_path("shure_sm57"))
    values = {"impedance": impedance, "load_ohm": load_ohm}
    ir = builder.build(c, values, cores="ja").ir
    fs = s.sample_rate
    t = np.arange(int(1.5 * fs)) / fs
    x = sum(PEAK_PA * np.sin(2 * np.pi * f * t) for f in TONES_HZ) * np.minimum(1, t / 0.05)
    v = fast.run_transient(ir, x, settings=s, controls={"p_rear": np.zeros_like(x)})
    y = v.vectors["v(out)"]
    k, n = int(0.5 * fs), fs
    bins = TONES_HZ.astype(int)
    return np.fft.rfft(y[k : k + n])[bins] / np.fft.rfft(x[k : k + n])[bins]


def main() -> None:
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    out = {"tones_hz": TONES_HZ.tolist(), "settings": {}}
    for imp, label in ((0, "H"), (1, "L")):
        h = {load: render(load, imp, s) for load in LOADS_OHM}
        open_ = h[1.0e6]
        rel = {f"{int(load)} ohm": (20 * np.log10(abs(h[load] / open_))).round(2).tolist()
               for load in LOADS_OHM[:-1]}  # fmt: skip
        # Thevenin at 1 kHz from two loads: V = E R / (R + Z) -> Z = R (E / V - 1)
        i = int(np.argmin(abs(TONES_HZ - 1000.0)))
        z = {f"{int(r)} ohm": round(float(abs(r * (open_[i] / h[r][i] - 1))), 1)
             for r in (150.0, 600.0, 2500.0)}  # fmt: skip
        out["settings"][label] = {
            "open_circuit_mv_per_pa_1khz": round(float(abs(open_[i])) * 1e3, 4),
            "re_open_circuit_db": rel,
            "output_impedance_ohm_1khz": z,
        }
        print(label, json.dumps(out["settings"][label], indent=1), flush=True)
    path = REPO_ROOT / "reports" / "mics" / "sm57_loading.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("->", path)


if __name__ == "__main__":
    main()

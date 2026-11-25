"""How much the contour generators' diodes matter (MINIMOOG_BACKLOG.md "Authenticity first", item
4): Fig 9-7 draws 1N34A germanium diodes where the circuit has the 1N4148 standing in (no germanium
card; Microsemi's 1N34A sheet gives only limits: VF <= 1.0 V at 5 mA, IR <= 30 uA at 10 V).

A sensitivity check, not a model: the contour file is copied (cache/minimoog/units/) with the
diodes' instance at SPICE area AREA (saturation current x AREA: the forward drop ~N Vt ln AREA
lower, ~0.3 V at 750, roughly germanium's; no germanium leakage, slope or series resistance), and
the filter contour's peak, its fastest attack (ATTACK 0) and decay (DECAY 0) measured against the
nominal file at production, as scripts/minimoog_contour_times.py measures them.

    uv run --extra fast python scripts/minimoog_diode_sensitivity.py [--area 750]

Writes reports/minimoog/units/diode_sensitivity.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import minimoog_contour_study as cs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "cache" / "minimoog" / "units"
OUT = ROOT / "reports" / "minimoog" / "units"
T_ON = 0.2


def lowered(area: float) -> Path:
    d = yaml.safe_load(cs.CIRCUIT.read_text(encoding="utf-8"))
    d["devices"]["DD"] = {
        **d["devices"]["DD"],
        "area": {"value": area, "source": "minimoog_diode_sensitivity.py: a lower forward drop"},
    }
    WORK.mkdir(parents=True, exist_ok=True)
    p = WORK / f"minimoog_contour_area{area:g}.yaml"
    p.write_text(yaml.safe_dump(d, sort_keys=False, width=10**9), encoding="utf-8")
    return p


def measure(path: Path) -> dict:
    cs.CIRCUIT = path
    fs = cs.FS
    out = {}
    # the fastest attack: gate held, ATTACK 0, DECAY long, SUSTAIN at the top: time to the peak
    ir = cs.build({"attack": 0.0, "decay": 0.6, "sustain": 1.0})
    n = int(fs * 0.4)
    gate = np.zeros(n)
    gate[int(T_ON * fs) :] = 5.0
    env = cs.run(ir, gate)["outn"]
    seg = env[int(T_ON * fs) :]
    k = int(np.argmax(seg))
    out["peak_v"] = float(seg[k])
    out["idle_v"] = float(env[int(0.15 * fs)])
    ten, ninety = (seg > out["idle_v"] + f * (seg[k] - out["idle_v"]) for f in (0.1, 0.9))
    out["attack_10_90_ms"] = 1e3 * (np.argmax(ninety) - np.argmax(ten)) / fs
    out["attack_to_peak_ms"] = 1e3 * k / fs
    # the fastest decay: ATTACK 0, DECAY 0, SUSTAIN 0: 1 / e of the fall from the peak
    ir = cs.build({"attack": 0.0, "decay": 0.0, "sustain": 0.0})
    env = cs.run(ir, gate)["outn"]
    seg = env[int(T_ON * fs) :]
    k = int(np.argmax(seg))
    floor = float(seg[-1])
    tail = seg[k:]
    out["decay_1e_ms"] = 1e3 * np.argmax(tail < floor + (seg[k] - floor) / np.e) / fs
    out["sustain0_v"] = floor
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--area", type=float, default=750.0)
    a = ap.parse_args()
    nominal_path = cs.CIRCUIT
    rep = {"area": a.area, "nominal": measure(nominal_path), "lowered": measure(lowered(a.area))}
    print(json.dumps(rep, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "diode_sensitivity.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

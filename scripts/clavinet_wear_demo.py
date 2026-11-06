"""The Clavinet's wear heard (docs/CLAVINET_PLAN.md, "Variation and wear"): the demo phrase
(scripts/clavinet_render.py's) through the live circuit (config/circuits/clavinet_d6_live.yaml:
the strings as circuitsim's medium, as the app plays them) at a few ages, and a second
unit at the same age -> reports/clavinet/wear/<name>.wav, each matched to -23 LUFS
(the project's rule: loudness lies) with a .json of the settings and the gain.

    uv run --extra fast --extra listen python scripts/clavinet_wear_demo.py
        [--ages 0 0.5 1 2] [--unit 1] [--other-unit 2] [--quality draft]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.listen.matching import TARGET_LUFS, integrated_lufs
from varimu.sim import fast, io

sys.path.insert(0, str(Path(__file__).parent))
from clavinet_render import demo_events  # noqa: E402

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "clavinet" / "wear"
CIRCUIT = CONFIG_DIR / "circuits" / "clavinet_d6_live.yaml"


def render(sets: dict, quality: str) -> tuple[np.ndarray, int, float]:
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets))
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    events = demo_events()
    n = int((events[-1].t_s + 1.5) * st.sample_rate)
    notes = [(e.t_s, e.kind, e.note, e.value) for e in events]
    t0 = time.time()
    v = fast.run_transient(ir, np.zeros(n), settings=st, notes=notes).vectors
    return np.asarray(v["v(out)"]), st.sample_rate, time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ages", type=float, nargs="+", default=[0.0, 0.5, 1.0, 2.0])
    ap.add_argument("--unit", type=int, default=1)
    ap.add_argument("--other-unit", type=int, default=2, help="a second instrument at age 1")
    ap.add_argument("--quality", default="draft")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    runs = [(f"age_{a:g}_unit_{args.unit}", a, args.unit) for a in args.ages]
    if args.other_unit:
        runs.append((f"age_1_unit_{args.other_unit}", 1.0, args.other_unit))
    summary = {}
    for name, age, unit in runs:
        sets = {"wear_age": age, "wear_unit": unit}
        y, fs, secs = render(sets, args.quality)
        lufs = integrated_lufs(y, fs)
        gain_db = TARGET_LUFS - lufs
        out = y * 10 ** (gain_db / 20)
        sf.write(OUT / f"{name}.wav", out.astype(np.float32), fs, subtype="FLOAT")
        summary[name] = {
            "settings": sets,
            "quality": args.quality,
            "lufs_before": lufs,
            "gain_db": gain_db,
            "peak_after": float(np.max(np.abs(out))),
            "render_s": secs,
        }
        print(f"{name}: {lufs:.1f} LUFS, gain {gain_db:+.1f} dB, {secs:.0f} s")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

"""Tube synth #14, the ring prototype's CPU: Python's draft run (the app's partition, a key
held at -15 V, 3 s plus the 1 s settle) of the synth and of ring_study.py's variants,
interleaved and repeated (this desktop drifts +-10%): the best wall time of each.

    uv run --extra fast python scripts/ring_cpu.py [--repeat 3]
"""

from __future__ import annotations

import argparse
import argparse as _a
import json

import ring_study as rs

CONFIGS = {
    # name: (option, ring, ring's thread: True alone, else in the input group)
    "base": None,
    "lfo ring (own thread)": ("lfo", True, True),
    "lfo ring (input thread)": ("lfo", True, False),
    "vco2 alone": ("vco2", False, True),
    "vco2 + ring (own thread)": ("vco2", True, True),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    v = _a.Namespace(
        diode="silicon", ring=1.0, wave2=0.0, r_carrier=2.2e3, r_ct_return=22e3, r_load=2.4e3,
        c_tank2=28e-9, osc_off=True, c_wien=1e-6, c_comp=1e-9,
    )  # fmt: skip
    jobs = {}
    for name, c in CONFIGS.items():
        if c is None:
            jobs[name] = (rs.prototype_path(), rs.BASE_PARTITION)
        else:
            opt, ring, alone = c
            v.no_ring = not ring
            jobs[name] = (rs.synth_variant(v, opt), rs.partition_for(opt, alone, ring))
    best = {k: float("inf") for k in jobs}
    for _ in range(a.repeat):
        for name, (path, part) in jobs.items():
            _, wall, _ = rs.run_synth(path, {}, -15.0, a.seconds, part, ["out"])
            best[name] = min(best[name], wall)
            print(f"{name:28s} {wall:6.2f} s", flush=True)
    per_s = {k: round(w / (a.seconds + 1.0), 3) for k, w in best.items()}
    print(json.dumps(per_s, indent=1))
    (rs.HERE / "cpu.json").write_text(
        json.dumps({"seconds": a.seconds, "wall_per_s": per_s}, indent=1)
    )


if __name__ == "__main__":
    main()

"""The Ampex 300-4's print speed (docs/PERIOD_GEAR_BACKLOG.md, PG1, decision 7: one
multi-rate island for the four record sides, its speed measured first).

Production (sim_settings' circuitsim block, JA cores, the circuit's noise off), one job alone,
the 1 s settle counted: a tone per track at 0 VU (-18 dBFS rms: 400, 1000, 2500, 6300 Hz),
long enough for the repro heads to read some (the head distance, 133 ms, then `--seconds`).
Variants: `cpu` / `gpu` (the tape's recording kernel, TAPE_SPEED_PLAN.md P5), and `351` (the
one-channel machine at the same panel, for scale). With CIRCUITSIM_PART_TIMING=1 circuitsim
prints each part's busy and waiting time.

    CIRCUITSIM_PART_TIMING=1 uv run --extra fast python scripts/ampex_300_4_speed.py [cpu gpu 351]
-> reports/multitrack/deck/speed.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import time

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.sim import fast
from varimu.sim.io import TransientSettings

OUT = REPO_ROOT / "reports" / "multitrack" / "deck"
TONES_HZ = (400.0, 1000.0, 2500.0, 6300.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("variants", nargs="*", default=["gpu"])
    ap.add_argument("--seconds", type=float, default=0.2)
    a = ap.parse_args()
    st0 = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st0.sample_rate
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "speed.json"
    res = json.loads(log.read_text()) if log.exists() else {}
    for v in a.variants:
        name = "ampex_351" if v.startswith("351") else "ampex_300_4"
        c = spec.load_circuit(spec.circuit_path(name))
        v_in, v_out = c.full_scale
        p = spec.resolve(c)
        delay = p["head_distance_m"] / p["speed_m_s"]
        n = int((delay + a.seconds) * fs)
        t = np.arange(n) / fs
        amp = v_in * 10 ** (-18 / 20) * math.sqrt(2.0)
        tones = [amp * np.sin(2 * math.pi * f * t) for f in TONES_HZ]
        ir = builder.build(c, {}, cores="ja", noise=False).ir
        st = dataclasses.replace(st0, tape_gpu="gpu" in v)
        controls = {} if name == "ampex_351" else {f"in{k}": tones[k - 1] for k in (2, 3, 4)}
        t0, c0 = time.time(), time.process_time()
        r = fast.run_transient(ir, tones[0], settings=st, controls=controls or None)
        el, cpu = time.time() - t0, time.process_time() - c0
        audio_s = n / fs + st.settle_s
        outs = [o for o in ("out", "out_2", "out_3", "out_4") if f"v({o})" in r.vectors]
        late = slice(int(delay * fs) + 2000, None)
        levels = {
            o: 20 * math.log10(np.std(r.vectors[f"v({o})"][late]) / v_out + 1e-30) for o in outs
        }
        row = {
            "circuit": name,
            "x_real_time": el / audio_s,
            "seconds": el,
            "cpu_s": cpu,
            "audio_s": audio_s,
            "out_dbfs_rms": levels,
        }
        res[v] = row
        log.write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(v, json.dumps(row), flush=True)


if __name__ == "__main__":
    main()

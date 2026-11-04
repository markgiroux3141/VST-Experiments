"""VARISPEED on the Ampex 351 slap echo, heard as the app plays it (docs/DELAY_PLAN.md, "The
351 echo"): the live tier (an events build at draft-1x, the reduced tape) streamed block by
block (`circuitsim.Stream`, as varimu-app's Live), the capstan's supply frequency turned
between blocks (`Stream.update`, a knob's path), so the motor's glide and hunting and the
repeats' pitch bends come out of the transport.

    uv run --extra fast --extra listen python scripts/varispeed_demo.py \
        [--clip "Dry Guitar.wav"] [--seconds 8] [--repeat 0.35] [--moves glide jump wobble]

Moves (the supply frequency against time; held at 60 Hz before and after):
- glide: 60 -> 45 Hz over 1.5 s, held, -> 75 Hz over 1.5 s, held, back to 60;
- jump: 60 -> 50 Hz in one block (the rotor hunts at 2.5 Hz, Q 3), later back to 60;
- wobble: 60 +- 4 Hz at 0.8 Hz (a hand on the oscillator's dial).
Writes reports/delay/audio/<clip>_varispeed_<move>.wav (the slap alone) and _mix.wav (the
dry plus the slap at 30%), and the supply's trajectory beside each (.csv: time, Hz).
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.sim import fast
from varimu.sim.io import TransientSettings, load_audio, resample

OUT = REPO_ROOT / "reports" / "delay" / "audio"
CIRCUIT = "ampex_351_echo"
BLOCK = 512
WET = 0.3


def supply(move: str, t: float) -> float:
    if move == "glide":
        segs = [(1.0, 60.0), (2.5, 45.0), (3.5, 45.0), (5.0, 75.0), (6.0, 75.0), (7.0, 60.0)]
        prev_t, prev_f = 0.0, 60.0
        for t1, f1 in segs:
            if t < t1:
                return prev_f + (f1 - prev_f) * (t - prev_t) / (t1 - prev_t)
            prev_t, prev_f = t1, f1
        return 60.0
    if move == "jump":
        return 50.0 if 1.5 <= t < 4.5 else 60.0
    if move == "wobble":
        return 60.0 + 4.0 * math.sin(2 * math.pi * 0.8 * t) if 1.0 <= t < 6.0 else 60.0
    raise ValueError(move)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clip", default="Dry Guitar.wav")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--repeat", type=float, default=0.35)
    ap.add_argument("--moves", nargs="+", default=["glide", "jump", "wobble"])
    a = ap.parse_args()
    import circuitsim
    import soundfile as sf

    s = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft-1x")
    c = spec.load_circuit(spec.circuit_path(CIRCUIT))
    v_in, v_out = c.full_scale
    x = load_audio(REPO_ROOT / "data" / "clips" / a.clip, s.sample_rate)
    x = x[int(a.start * s.sample_rate) : int((a.start + a.seconds) * s.sample_rate)]
    x = resample(x, s.sample_rate, s.host)
    x = x / (np.sqrt(np.mean(x**2)) * math.sqrt(2) / 10 ** (-18 / 20))  # -18 dBFS rms
    rate = s.host
    base = {"repeat": a.repeat}

    def ir_at(f: float):
        return builder.build(
            c, {**base, "capstan_hz": f}, cores="linear", noise=False, events=True
        ).ir

    stem = Path(a.clip).stem.replace(" ", "_")
    for move in a.moves:
        ir = ir_at(supply(move, 0.0))
        st = circuitsim.Stream(
            ir.to_json(),
            1.0 / s.sim_rate,
            x[0] * v_in,
            s.method,
            solver=s.solver,
            reltol=s.newton_reltol,
            vntol=s.newton_vntol,
            input_order=s.input_order,
            newton_reuse=s.newton_reuse,
            tube_tables=s.tube_tables,
            partition=fast.partition_sections(ir, s) or None,
            partition_coupling=s.partition_coupling,
        )
        st.process(np.full(int(s.settle_s * rate), x[0] * v_in))
        ys, track, last = [], [], None
        for b0 in range(0, len(x), BLOCK):
            f = round(supply(move, b0 / rate), 3)
            if f != last:
                st.update(ir_at(f).to_json())
                last = f
            track.append((b0 / rate, f))
            ys.append(np.asarray(st.process(x[b0 : b0 + BLOCK] * v_in)["v(out)"]) / v_out)
        y = np.concatenate(ys)
        n = min(len(y), len(x))
        OUT.mkdir(parents=True, exist_ok=True)
        name = f"{stem}_varispeed_{move}"
        sf.write(OUT / f"{name}.wav", y[:n].astype(np.float32), rate, subtype="FLOAT")
        mix = (1 - WET) * x[:n] + WET * y[:n]
        sf.write(OUT / f"{name}_mix.wav", mix.astype(np.float32), rate, subtype="FLOAT")
        np.savetxt(OUT / f"{name}.csv", np.array(track), delimiter=",", header="t_s,supply_hz")
        print(f"{name}: peak {20 * math.log10(np.abs(y).max() + 1e-30):.1f} dBFS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

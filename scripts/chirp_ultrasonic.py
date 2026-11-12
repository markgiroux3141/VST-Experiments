"""A diagnostic (the 300-4's 5.4 kHz chirp, docs/PERIOD_GEAR_BACKLOG.md PG1): the Ampex 300-4
and the Ampex 351 run at the production engine's own rate (192 kHz, oversample 1: no
decimation) on the same bass excerpt, their probes kept, so what lies above the audio band
(the bias's residue, the oscillator) can be seen before the decimation folds it.

    uv run --extra fast python scripts/chirp_ultrasonic.py BASS.wav OUTDIR [--seconds 1.2]
        [--only deck|351] [--deck-trim-db 11.6] [--a351-trim-db 11.1]

Writes OUTDIR/<machine>.npz (every probe at 192 kHz, the input) and prints each machine's
oscillator frequency (the erase head's node `ers`) and the strongest lines 20-96 kHz in
`out` and `rh` (the repro head). Nothing in varimu/ changes.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import threading
from pathlib import Path

import numpy as np
from scipy.signal import welch

from varimu.circuit import builder, spec
from varimu.measure import tape_align as ta
from varimu.sim import fast
from varimu.sim.io import TransientSettings, load_audio

FS = 192_000


def lines(x: np.ndarray, lo: float, hi: float, n: int = 6) -> list[tuple[float, float]]:
    f, p = welch(x, FS, nperseg=1 << 15, noverlap=3 << 13)
    m = (f >= lo) & (f <= hi)
    ff, pp = f[m], p[m]
    tot = float(np.sum(p))
    out = []
    order = np.argsort(pp)[::-1]
    for i in order:
        if all(abs(ff[i] - g) > 300 for g, _ in out):
            out.append((float(ff[i]), float(10 * np.log10(pp[i] * (f[1] - f[0]) / tot))))
        if len(out) == n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bass")
    ap.add_argument("outdir")
    ap.add_argument("--seconds", type=float, default=1.2)
    ap.add_argument("--only", choices=["deck", "351"])
    ap.add_argument("--deck-trim-db", type=float, default=11.6)
    ap.add_argument("--a351-trim-db", type=float, default=11.1)
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    st = dataclasses.replace(st, sample_rate=FS, oversample=1)
    x = load_audio(Path(a.bass), FS)[: int(a.seconds * FS)]

    jobs = []
    if a.only in (None, "deck"):
        c = spec.load_circuit(spec.circuit_path("ampex_300_4"))
        ir = builder.build(c, cores="ja").ir
        z = np.zeros_like(x)
        ctl = {k: z for k in ("in2", "in3", "in4")}
        jobs.append(("deck", ir, c.full_scale, a.deck_trim_db, ctl))
    if a.only in (None, "351"):
        al = ta.aligned()
        c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
        ir = builder.build(c, al.overrides, cores="ja").ir
        jobs.append(("351", ir, c.full_scale, a.a351_trim_db, None))

    res = {}

    def run(job) -> None:
        name, ir, (v_in, _), trim, ctl = job
        u = x * v_in * 10 ** (trim / 20)
        r = fast.run_transient(ir, u, settings=st, controls=ctl)
        res[name] = r.vectors
        np.savez(out / f"{name}.npz", x=x, **{k: v for k, v in r.vectors.items()})

    th = [threading.Thread(target=run, args=(j,)) for j in jobs]
    for t in th:
        t.start()
    for t in th:
        t.join()
    for name, v in res.items():
        print(f"== {name}")
        if "v(ers)" in v:
            print(
                "  ers (oscillator):",
                [(round(f), round(d, 1)) for f, d in lines(v["v(ers)"], 50e3, 96e3, 3)],
            )
        for k in ("v(rh)", "v(out)"):
            if k in v:
                print(
                    f"  {k} 20-96 kHz:",
                    [(round(f), round(d, 1)) for f, d in lines(v[k], 20e3, 96e3)],
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())

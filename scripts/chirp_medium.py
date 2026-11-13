"""A diagnostic (the 300-4's 5.4 kHz chirp, docs/PERIOD_GEAR_BACKLOG.md PG1): the tape medium
alone (circuitsim's TapeStream, literal bias at the circuit's substeps), fed an ideal head
field (a pure sine bias plus a 60 Hz tone), at each machine's oscillator frequency, so the
circuit's numerics are out of the picture.

    uv run --extra fast python scripts/chirp_medium.py [--seconds 0.6] [--bias-ma 2.94]
        [--audio-ma 0.6] [--fb 92994 95865 ...] [--machines deck 351]

Prints, per (machine's medium, bias frequency), the EMF's level in 5.2-5.8 kHz and at the
predicted beat |m fs - 2 n f_b| (the bias's extrema against the substep grid) re the 60 Hz
tone, and writes reports/tape/chirp/medium.json. Nothing in varimu/ changes.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import Tape
from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta

FS = 192_000.0
OUT = REPO_ROOT / "reports" / "tape" / "chirp"


def medium(name: str):
    if name == "deck":
        c = spec.load_circuit(spec.circuit_path("ampex_300_4"))
        ir = builder.build(c, cores="ja").ir
    else:  # "351", or "351lo": its 7-1/2 ips tape part
        c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
        over = dict(ta.aligned().overrides)
        if name == "351lo":
            over["speed"] = 0
        ir = builder.build(c, over, cores="ja").ir
    tapes = [e for e in ir.elements() if isinstance(e, Tape)]
    t = tapes[0]
    return t.medium


def beat(m: int, fb: float) -> float:
    fsub = m * FS
    n = round(fsub / (2 * fb))
    return abs(fsub - n * 2 * fb)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=0.6)
    ap.add_argument("--bias-ma", type=float, default=2.94, help="rms (the 351's alignment)")
    ap.add_argument("--audio-ma", type=float, default=0.6, help="the 60 Hz tone, rms")
    ap.add_argument("--head-a-m-per-a", type=float, default=8.0e6)
    ap.add_argument("--fb", type=float, nargs="+", default=[92_994.0, 95_865.0])
    ap.add_argument("--machines", nargs="+", default=["deck", "351"])
    ap.add_argument(
        "--substeps",
        type=int,
        nargs="+",
        default=None,
        help="override the literal bias's substeps (default: the circuit's)",
    )
    ap.add_argument("--out", default="medium.json")
    ap.add_argument("--gpu", action="store_true", help="the f32 GPU kernel (a diagnosis)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--tone-hz", type=float, default=60.0)
    ap.add_argument(
        "--ds-um",
        type=float,
        nargs="+",
        default=None,
        help="override the cells' length (default: the circuit's)",
    )
    a = ap.parse_args()
    import circuitsim

    OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    jobs = []
    for mach in a.machines:
        med = medium(mach)
        for m in a.substeps or [med.bias_substeps]:
            for ds in a.ds_um or [med.ds_m * 1e6]:
                for fb in a.fb:
                    md = dataclasses.replace(med, bias_substeps=m, ds_m=ds * 1e-6)
                    jobs.append((mach, md, m, fb))

    def run(job):
        mach, med, m, fb = job
        med = dataclasses.replace(med, f_bias_hz=fb)
        params = json.dumps(dataclasses.asdict(med))
        n = int((a.seconds + med.head_distance_m / med.speed_m_s + 0.05) * FS)
        k = np.arange(n * m)
        t = (k + 1 - 2 * m) / (m * FS)
        hb = a.bias_ma * 1e-3 * math.sqrt(2) * a.head_a_m_per_a
        ha = a.audio_ma * 1e-3 * math.sqrt(2) * a.head_a_m_per_a
        env = np.clip(t / 0.02, 0.0, 1.0)
        h = env * (
            ha * np.sin(2 * math.pi * a.tone_hz * t) + hb * np.sin(2 * math.pi * fb * t + 0.3)
        )
        y = np.asarray(circuitsim.tape_stream_run(params, FS, h, chunk=20 * m * 48, gpu=a.gpu))
        d = int(med.head_distance_m / med.speed_m_s * FS) + int(0.05 * FS)
        y = y[d:]
        np.save(
            OUT
            / f"emf_{mach}_m{m}_ds{round(med.ds_m * 1e9)}_fb{int(fb)}_a{int(a.tone_hz * 10)}.npy",
            y,
        )
        w = np.hanning(len(y))
        sp = np.abs(np.fft.rfft(y * w)) ** 2
        f = np.fft.rfftfreq(len(y), 1 / FS)
        ref = sp[(f > a.tone_hz - 5) & (f < a.tone_hz + 5)].sum()

        def band(lo, hi):
            return 10 * math.log10(sp[(f >= lo) & (f < hi)].sum() / ref + 1e-300)

        bt = beat(m, fb)
        lines = []
        mm = (f > 1000) & (f < 90_000)
        order = np.argsort(sp[mm])[::-1]
        for i in order:
            fi = float(f[mm][i])
            if all(abs(fi - g) > 400 for g, _ in lines):
                lines.append((round(fi), round(10 * math.log10(sp[mm][i] / ref), 1)))
            if len(lines) == 5:
                break
        return {
            "machine": mach,
            "substeps": m,
            "ds_um": med.ds_m * 1e6,
            "f_bias_hz": fb,
            "beat_hz": round(bt),
            "band_5k2_5k8_db_re_60hz": round(band(5200, 5800), 1),
            "at_beat_db_re_60hz": round(band(bt - 300, bt + 300), 1) if bt < 95_000 else None,
            "strongest_lines_1k_90k": lines,
        }

    with ThreadPoolExecutor(min(a.jobs, len(jobs))) as ex:
        rows = list(ex.map(run, jobs))
    for r in rows:
        print(json.dumps(r))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / a.out).write_text(json.dumps({"args": vars(a), "rows": rows}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

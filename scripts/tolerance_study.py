"""Transient accuracy vs solver settings on the full slice (handoff item 5).

    uv run python scripts/tolerance_study.py

Renders the same excerpts under several settings and compares each with a
tight reference (gear, reltol 1e-5, 4x oversampling). Reports the output
error relative to the signal, the CV error, and the wall-clock cost.
Results go to reports/slice/tolerance_study.json.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np

from varimu.config import DATA_DIR, REPO_ROOT, load_sim_settings
from varimu.measure import signals
from varimu.sim import runner
from varimu.sim.io import TransientSettings, load_audio

OUT = REPO_ROOT / "reports" / "slice" / "tolerance_study.json"

VARIANTS = {
    "default (gear 1e-3, 2x)": {},
    "gear 1e-4, 2x": {"reltol": 1e-4},
    "gear 1e-3, 1x": {"oversample": 1},
    "gear 1e-3, 4x": {"oversample": 4},
    "trap 1e-3, 2x": {"method": "trap"},
    "trap 1e-4, 2x": {"method": "trap", "reltol": 1e-4},
    "gear 1e-5, 4x": {"reltol": 1e-5, "oversample": 4},
}
# reltol 1e-5 fails to start ("timestep too small" at a bridge diode near t=0),
# so the reference is gear at 1e-4 with 4x oversampling.
REFERENCE = {"reltol": 1e-4, "oversample": 4}


def excerpts():
    st = load_sim_settings()
    fs = st.sample_rate
    spec = next(s for s in signals.default_library() if s.name == "burst_1000hz_0dbfs")
    burst = signals.render(spec, sample_rate=fs, seed=st.seed)
    a = burst.meta["burst_start"]
    out = {"burst attack (0 dBFS, TC1)": (burst.samples[a - fs // 10 : a + int(0.4 * fs)], 1)}
    clips = sorted(
        p for p in (DATA_DIR / "clips").glob("*") if p.suffix.lower() in {".wav", ".flac"}
    )
    if clips:
        out[f"clip {clips[0].name[:24]} 1 s (TC2)"] = (load_audio(clips[0], fs)[:fs], 2)
    return out


def err_db(x, ref):
    return float(20 * np.log10(np.std(x - ref) / np.std(ref)))


def main() -> None:
    base = TransientSettings.from_sim_settings()
    results = {}
    for name, (x, tc) in excerpts().items():
        ov = {"input_atten_db": 0.0, "ac_threshold": 0.8, "time_constant": tc}
        jobs = {"reference": dataclasses.replace(base, **REFERENCE)}
        jobs.update({k: dataclasses.replace(base, **v) for k, v in VARIANTS.items()})
        renders = {}
        # Parallel by hand: render_many takes one settings object.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(4, runner.default_jobs())) as ex:
            futs = {
                k: ex.submit(runner.render, runner.RenderJob(x, ov, f"tol:{k}"), settings=s)
                for k, s in jobs.items()
            }
            renders, failed = {}, {}
            for k, f in futs.items():
                try:
                    renders[k] = f.result()
                except Exception as e:  # a variant that can't run is a result too
                    lines = str(e).splitlines() or [repr(e)]
                    why = next((ln for ln in lines if "too small" in ln), lines[-1])
                    failed[k] = f"{lines[0]} | {why.strip()[:200]}"
        ref = renders["reference"]
        rows = {k: {"failed": v} for k, v in failed.items()}
        for k, r in renders.items():
            rows[k] = {
                "realtime_factor": round(r.meta["realtime_factor"], 1),
                "sim_points": r.meta["sim_points"],
                "out_err_db": None if k == "reference" else round(err_db(r.output, ref.output), 1),
                "cv_max_err_v": None
                if k == "reference"
                else round(float(np.max(np.abs(r.vectors["v(cv)"] - ref.vectors["v(cv)"]))), 3),
            }
        results[name] = rows
        print(name)
        for k, v in rows.items():
            print(f"  {k:26s} {v}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"reference": REFERENCE, "results": results}, indent=1))


if __name__ == "__main__":
    main()

"""The native app's render against Python's, bit for bit (docs/NATIVE_APP_PLAN.md, R2).

    uv run --extra fast python scripts/app_render_agreement.py [--quality production]
        [--only pultec_eqp1a fairchild_670] [--seconds 0.25]

For each device, an excerpt of the arpeggio clip with some knobs away from their
defaults goes through `varimu.sim.fast.run_transient` (Python, the reference) and
through crates/varimu-app's render (`cargo run --release --example render`); every
probe is compared value by value. Same IR, engine and resampling, so every value must
be equal: exit 1 otherwise. Run it after a change to the app's render or resampling,
or to circuitsim, the builder or a circuit (renders take ~15x real time at production,
plus 1 s of settling each).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT
from varimu.sim import fast, runner
from varimu.sim.io import TransientSettings, load_audio

CLIP = REPO_ROOT / "data" / "clips" / "Arpeggio04b_120_m_D#_16b.WAV"
START_S = 1.0
# Knobs away from the defaults (values as a render's overrides take them).
CASES = {
    "pultec_eqp1a": {"lf_boost": 0.6, "hf_boost": 0.4, "hf_boost_freq_khz": 8},
    "fairchild_670": {"input_atten_db": 6.0, "time_constant": 1},
}


def python_render(name: str, x: np.ndarray, s: TransientSettings) -> dict[str, np.ndarray]:
    circuit = None if name == "fairchild_670" else name
    ir = runner.build_circuit(runner.RenderJob(x, CASES[name], circuit=circuit), s).ir
    return fast.run_transient(ir, x * s.full_scale_volts_peak, settings=s).vectors


def rust_render(name: str, x: np.ndarray, quality: str, work: Path) -> dict[str, np.ndarray]:
    inp = work / f"{name}_x.f64"
    x.astype("<f8").tofile(inp)
    out = work / name
    sets = [a for k, v in CASES[name].items() for a in ("--set", f"{k}={v}")]
    cmd = ["cargo", "run", "-q", "--release", "-p", "varimu-app", "--example", "render", "--",
           "--circuit", name, "--input", str(inp), "--quality", quality,
           "--probes", str(out), *sets]  # fmt: skip
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    return {f"v({p.stem})": np.fromfile(p, "<f8") for p in out.glob("*.f64")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quality", default="production")
    ap.add_argument("--only", nargs="*", default=list(CASES))
    ap.add_argument("--seconds", type=float, default=0.25)
    a = ap.parse_args()
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality=a.quality)
    clip = load_audio(CLIP, s.sample_rate)
    i = int(START_S * s.sample_rate)
    x = clip[i : i + int(a.seconds * s.sample_rate)]
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        for name in a.only:
            t0 = time.perf_counter()
            want = python_render(name, x, s)
            t1 = time.perf_counter()
            got = rust_render(name, x, a.quality, Path(tmp))
            t2 = time.perf_counter()
            if sorted(want) != sorted(got):
                print(f"{name}: probes {sorted(want)} vs {sorted(got)}")
                ok = False
                continue
            values = sum(len(v) for v in want.values())
            differ = sum(int(np.sum(want[k].view("<u8") != got[k].view("<u8"))) for k in want)
            worst = max(float(np.max(np.abs(want[k] - got[k]))) for k in want)
            print(
                f"{name} ({a.quality}): {len(want)} probes, {values} values, {differ} differ "
                f"(worst {worst:.1e} V); python {t1 - t0:.1f} s, rust {t2 - t1:.1f} s"
            )
            ok &= differ == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

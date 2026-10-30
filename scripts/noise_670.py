"""The 670's idle noise with B5's noise sources on (device builder B5's done-when).

    uv run --extra fast python scripts/noise_670.py [--seconds 3]

fairchild_670.yaml at its defaults (the factory adjustment), production, Jiles-Atherton
cores, silence in, noise forced on (the file has no `noise` block: its renders don't move)
and off. The output across its 600 ohm load, 20 Hz-20 kHz: the idle output (hum and noise)
and the noise alone (on minus off: the hum is the same in both and cancels), in dBm, next
to the published figure (vs_670 style, never a rejection): noise ~70 dB below +4 dBm, i.e.
-66 dBm, bandwidth unstated (dealers' and the reissue's spec sheets, e.g. web:
https://www.vintagedigital.com.au/?p=143911; not checked against an original Fairchild
document). -> reports/noise/670_idle.json
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "noise" / "670_idle.json"
DBM_V = np.sqrt(1e-3 * 600.0)  # 0 dBm across 600 ohm
PUBLISHED_DBM = 4.0 - 70.0


def run(noise: bool, seconds: float) -> np.ndarray:
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "fairchild_670.yaml")
    ir = builder.build_ir(s, spec.resolve(s), cores="ja", noise=noise)
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production")
    fs = st.sample_rate
    return fast.run_transient(ir, np.zeros(int(seconds * fs)), settings=st).vectors["v(out)"]


def band_dbm(v: np.ndarray, fs: int) -> float:
    sos = butter(4, [20.0, 20000.0], btype="band", fs=fs, output="sos")
    y = sosfiltfilt(sos, v - np.mean(v))[int(0.1 * fs) :]
    return float(20 * np.log10(np.sqrt(np.mean(y**2)) / DBM_V))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=3.0)
    args = ap.parse_args()
    fs = io.load_sim_settings().sample_rate
    t0 = time.perf_counter()
    with ThreadPoolExecutor(2) as ex:
        off, on = ex.map(lambda n: run(n, args.seconds), (False, True))
    out = {
        "seconds": args.seconds,
        "idle_off_dbm": band_dbm(off, fs),
        "idle_on_dbm": band_dbm(on, fs),
        "noise_alone_dbm": band_dbm(on - off, fs),
        "published_dbm": PUBLISHED_DBM,
        "published_source": "~70 dB below +4 dBm (dealers' / reissue spec sheets)",
        "wall_s": time.perf_counter() - t0,
    }
    out["noise_vs_published_db"] = out["noise_alone_dbm"] - PUBLISHED_DBM
    for k, v in out.items():
        print(f"{k}: {v:.2f}" if isinstance(v, float) else f"{k}: {v}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

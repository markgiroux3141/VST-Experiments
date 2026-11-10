"""The Minimoog noise generator's factory trim (config/circuits/minimoog_noise.yaml;
docs/MINIMOOG_PLAN.md MM5), after Folkman's 'Noise Level' (TECHNICAL SERVICE MANUAL p. 14):
"factory-
set to yield -5dB maximum in the white position". Read here (provisional) as: the white noise at
board 3's pin 5, into the mixer's 25K NOISE pot, 5 dB under an oscillator's sawtooth into its own
LEVEL pot (rms, both at full level; the saw is oscillator 1's at the draft, +-1.75 V). The NOISE
LEVEL trim (R26) is solved for it; the white and pink spectra are reported.

    uv run --extra fast python scripts/minimoog_noise_trim.py [--write]

--write puts noise_level_trim into the circuit file. Writes reports/minimoog/noise/trim.json.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io

CIRCUIT = CONFIG_DIR / "circuits" / "minimoog_noise.yaml"
OUT = Path(__file__).resolve().parents[1] / "reports" / "minimoog" / "noise"
SAW_RMS_V = 1.75 / np.sqrt(3.0)  # a +-1.75 V sawtooth (Fig 9-2's levels at 9B)
TARGET_DB = -5.0
SECONDS = 2.0
SKIP_S = 0.5  # the coupling capacitors settle


def settings() -> io.TransientSettings:
    s = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    return dataclasses.replace(
        s, host_rate=48000, oversample=2, full_scale_volts_peak=1.0, newton_reltol=1e-5,
        newton_vntol=1e-5, settle_s=0.2,
    )  # fmt: skip


def run(trim: float) -> dict:
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {"noise_level_trim": trim}), "linear")
    st = settings()
    n = int(SECONDS * st.sample_rate)
    r = fast.run_transient(ir, np.zeros(n), settings=st)
    k = int(SKIP_S * st.sample_rate)
    return {
        "rate": st.sample_rate,
        "wn": np.asarray(r.vectors["v(wn)"])[k:],
        "pn": np.asarray(r.vectors["v(pn)"])[k:],
    }


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.std(x) / SAW_RMS_V))


def slope_db_per_octave(x: np.ndarray, rate: float, lo=200.0, hi=6400.0) -> float:
    """The spectrum's slope (Welch, a straight line over log frequency between lo and hi)."""
    from scipy.signal import welch

    f, p = welch(x, rate, nperseg=8192)
    m = (f >= lo) & (f <= hi)
    return float(np.polyfit(np.log2(f[m]), 10 * np.log10(p[m]), 1)[0])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    grid = np.linspace(0.0, 1.0, 11)
    with ThreadPoolExecutor(len(grid)) as ex:
        runs = list(ex.map(run, grid))
    levels = [rms_db(r["wn"]) for r in runs]
    # the white level falls as R26 turns up (less gain): interpolate the target on the grid
    order = np.argsort(levels)
    trim = float(np.interp(TARGET_DB, np.array(levels)[order], grid[order]))
    r = run(trim)
    rate = r["rate"]
    summary = {
        "trim": trim,
        "white_db_re_saw": rms_db(r["wn"]),
        "pink_db_re_saw": rms_db(r["pn"]),
        "white_slope_db_per_octave": slope_db_per_octave(r["wn"], rate),
        "pink_slope_db_per_octave": slope_db_per_octave(r["pn"], rate),
        "white_peak_v": float(np.abs(r["wn"]).max()),
        "grid": [{"trim": float(g), "white_db": lv} for g, lv in zip(grid, levels, strict=True)],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trim.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    if a.write:
        text = CIRCUIT.read_text(encoding="utf-8")
        text, n = re.subn(r"(\n  noise_level_trim: \{value: )[^,]+", rf"\g<1>{trim:.4f}", text)
        if n != 1:
            raise SystemExit("noise_level_trim not found once")
        CIRCUIT.write_text(text, encoding="utf-8")
        print(f"wrote {CIRCUIT.name}")


if __name__ == "__main__":
    main()

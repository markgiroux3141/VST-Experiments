"""The Telefunken V72's calibrations (the chains build-out's WP1).

    uv run --extra fast python scripts/v72_trim.py [--check]

Three values in config/circuits/telefunken_v72.yaml are set here, two of them as the
factory set them (data/schematics/telefunken_v72/README.md):

- `t4_hv_rms_v`, the mains transformer's HV winding (no published figure): THD 0.3% at
  1 kHz, +17 dB out, the Braunbuch's (sheet 4, point 6e) and the datasheet's maximum
  (5.5 V into 300 ohm). V42 drives the output transformer in class A, so its current, set
  by the supply, sets where it clips;
- `c40_f`, the trimmer C40 ("ca. 40 pF", set for the 15 kHz response: sheet 2): 15 kHz
  -0.3 dB re 1 kHz, the middle of sheet 4's 0-0.6 dB;
- `r20_ohm`, R20 ("5 kOhm abgegl.", trimmed for the gain: sheet 2): 34.0 dB at 1 kHz,
  +6 dB out, re the 200 ohm generator's EMF (sheet 3).

They interact a little, so the three run in turn twice. Prints the values; `--check`
prints what the file's give and exits 1 when one is off by more than its tolerance.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.measure import metrics
from varimu.sim import fast
from varimu.sim.io import TransientSettings

PATH = CONFIG_DIR / "circuits" / "telefunken_v72.yaml"
GAIN_DB = 34.0
THD_MAX_PCT, MAX_OUT_DB = 0.3, 17.0
HF_HZ, HF_DB = 15000.0, -0.3
V_REF = 0.775
TOL = {"gain": 0.02, "thd": 0.01, "hf": 0.03}


def _run(c, over: dict, x_emf_v: np.ndarray, st) -> np.ndarray:
    """v(out) of an input in EMF volts behind the circuit's 200 ohm generator."""
    ir = builder.build_ir(c, spec.resolve(c, over))
    return fast.run_transient(ir, x_emf_v, settings=st).vectors["v(out)"]


def _tone(out_db: float, f_hz: float, fs: int, seconds: float = 0.6) -> np.ndarray:
    t = np.arange(int(seconds * fs)) / fs
    emf = V_REF * np.sqrt(2) * 10 ** ((out_db - GAIN_DB) / 20)
    return emf * np.minimum(1.0, t / 0.1) * np.sin(2 * np.pi * f_hz * t)


def gain_db(c, over: dict, st) -> float:
    """1 kHz, +6 dB out, re the EMF."""
    fs = st.sample_rate
    x = _tone(6.0, 1000.0, fs)
    h = metrics.harmonics(_run(c, over, x, st)[-int(0.25 * fs) :], 1000.0, fs)
    return float(20 * np.log10(h.amps[0] / np.max(np.abs(x))))


def thd_pct(c, over: dict, st) -> float:
    """THD of 1 kHz at +17 dB out."""
    fs = st.sample_rate
    out = _run(c, over, _tone(MAX_OUT_DB, 1000.0, fs), st)[-int(0.25 * fs) :]
    return float(100 * metrics.harmonics(out, 1000.0, fs).thd)


def hf_db(c, over: dict, st) -> float:
    """15 kHz re 1 kHz, the two at +3 dB out each (+6 dB in total, the specs' level)."""
    fs = st.sample_rate
    x = (_tone(3.0, 1000.0, fs) + _tone(3.0, HF_HZ, fs)) / 1.0
    out = _run(c, over, x, st)
    n = int(0.5 * fs)  # 0.5 s: both tones on whole cycles
    sx, so = np.fft.rfft(x[-n:]), np.fft.rfft(out[-n:])
    k1, k2 = int(1000.0 * n / fs), int(HF_HZ * n / fs)
    return float(20 * np.log10(abs(so[k2] / sx[k2]) / abs(so[k1] / sx[k1])))


def bisect(f, lo: float, hi: float, target: float, tol: float, log) -> float:
    flo, fhi = f(lo) - target, f(hi) - target
    if flo * fhi > 0:
        raise SystemExit(f"not bracketed: {lo} -> {flo + target}, {hi} -> {fhi + target}")
    while True:
        mid = 0.5 * (lo + hi)
        fm = f(mid) - target
        log(f"  {mid:.5g} -> {fm + target:.4f}")
        if abs(fm) < tol:
            return mid
        if (fm < 0) == (flo < 0):
            lo, flo = mid, fm
        else:
            hi = mid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the file's values are off")
    args = ap.parse_args()
    c = spec.load_circuit(PATH)
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    if args.check:
        got = {"gain": gain_db(c, {}, st), "thd": thd_pct(c, {}, st), "hf": hf_db(c, {}, st)}
        want = {"gain": GAIN_DB, "thd": THD_MAX_PCT, "hf": HF_DB}
        print(", ".join(f"{k} {got[k]:.3f} (target {want[k]})" for k in got))
        return int(any(abs(got[k] - want[k]) > 2 * TOL[k] for k in got))
    q = spec.resolve(c)
    ov = {k: q[k] for k in ("t4_hv_rms_v", "c40_f", "r20_ohm")}
    for _ in range(2):
        print("r20_ohm:")
        ov["r20_ohm"] = bisect(
            lambda r: gain_db(c, {**ov, "r20_ohm": r}, st), 0.0, 20.0e3, GAIN_DB,
            TOL["gain"], print,
        )  # fmt: skip
        print("t4_hv_rms_v:")
        ov["t4_hv_rms_v"] = bisect(
            lambda v: -thd_pct(c, {**ov, "t4_hv_rms_v": v}, st), 220.0, 300.0, -THD_MAX_PCT,
            TOL["thd"], print,
        )  # fmt: skip
        print("c40_f:")
        ov["c40_f"] = bisect(
            lambda cf: -hf_db(c, {**ov, "c40_f": cf}, st), 1.0e-12, 60.0e-12, -HF_DB,
            TOL["hf"], print,
        )  # fmt: skip
    print({k: float(f"{v:.4g}") for k, v in ov.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())

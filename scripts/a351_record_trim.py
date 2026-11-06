"""The Ampex 351 direct monitor's RECORD CALIBRATE (the chains build-out's WP7).

    uv run --extra fast python scripts/a351_record_trim.py [--check] [--gains]

Sets RECORD CALIBRATE 4R12 as the manual's alignment does (man p 83: with the operating level
recorded, RECORD CALIBRATE for 0 VU on the meter's RECORD LEVEL position): -10 dBm at 500 Hz
into the unbalanced bridge, RECORD LEVEL at the machine's aligned setting
(reports/tape/ampex_351_alignment.json), +8 dBm across the 600 ohm line load. The output is
linear in the wiper's rotation (2R37's 1 MEG barely loads it), so two runs and a ratio find
it; a third checks. Prints the rotation for `RECORD_CALIBRATE` in scripts/make_351_record.py;
`--check` exits 1 when the generated file's is off by more than 0.05 dB.

`--gains` prints the microphone gain (the output re the source's EMF, 1 kHz, 0.1 mV in)
at RECORD LEVEL's rotations, for the chain list's labels (config/chains.yaml).
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from varimu.circuit import builder, spec
from varimu.sim import fast
from varimu.sim.io import TransientSettings

NAME = "ampex_351_record"
IN_V_RMS = 0.2449  # -10 dBm (man p 11: the bridge's operating level)
OUT_V_RMS = 1.9494  # +8 dBm into 600 ohm (man p 11, p 79: 0 VU)
F_HZ = 500.0
TOL_DB = 0.05
#: RECORD LEVEL's rotations in the chain list (config/chains.yaml), labelled by --gains.
LEVELS = (0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.7, 1.0)


def _out_rms(c, over: dict, f_hz: float, in_v_rms: float, st) -> float:
    fs = st.sample_rate
    t = np.arange(int(0.6 * fs)) / fs
    x = in_v_rms * np.sqrt(2) * np.sin(2 * np.pi * f_hz * t)
    ir = builder.build_ir(c, spec.resolve(c, over))
    y = fast.run_transient(ir, x, settings=st).vectors["v(out)"]
    seg = y[-int(0.2 * fs) :]
    return float(np.sqrt(np.mean((seg - seg.mean()) ** 2)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--gains", action="store_true")
    args = ap.parse_args()
    c = spec.load_circuit(spec.circuit_path(NAME))
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    p = spec.resolve(c, {})
    bridge = {"input_transfer": 1}

    if args.check:
        got = _out_rms(c, bridge, F_HZ, IN_V_RMS, st)
        err_db = 20 * np.log10(got / OUT_V_RMS)
        print(f"record_calibrate {p['record_calibrate']:.4f}: {err_db:+.3f} dB re +8 dBm")
        sys.exit(0 if abs(err_db) <= TOL_DB else 1)

    if args.gains:
        for lev in LEVELS:
            got = _out_rms(c, {"record_level": lev}, 1000.0, 1e-4, st)
            print(f"record_level {lev:.2f}: {20 * np.log10(got / 1e-4):5.1f} dB")
        return

    r = 0.2
    for _ in range(3):
        got = _out_rms(c, {**bridge, "record_calibrate": r}, F_HZ, IN_V_RMS, st)
        print(f"  record_calibrate {r:.4f}: {20 * np.log10(got / OUT_V_RMS):+.3f} dB re +8 dBm")
        r *= OUT_V_RMS / got
    print(f"RECORD_CALIBRATE = {r:.4f}")


if __name__ == "__main__":
    main()

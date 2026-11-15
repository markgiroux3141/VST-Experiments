"""Calibrate the hum pickups whose makers published a hum figure (2026-11-14).

`uv run --extra fast --extra listen python scripts/hum_calibrate.py [--check]`

Each circuit below gets a trial `hum` block (its pickup at a trial area), is rendered on silence
in the maker's reference field, and its output hum is compared with the published figure; the
hum is linear in the area, so area = trial x 10^((published - measured) / 20). Without --check it
prints the areas to write into the circuit files' `hum` blocks; with --check it measures the files'
own blocks and fails past 0.5 dB.

The figures (sources in each circuit's data/schematics README):
- RCA 44-BX: hum pickup -115 dBm, hum field 1e-3 gauss (link M), US mains 60 Hz;
- RCA 77-DX: -128 dBm, 1e-3 gauss;
- STC / Coles 4038: +4 dB re 0.0002 dyne/cm^2 equivalent SPL for 1 mG at 50 Hz (BBC Monograph 4,
  p19-21; the brochure: < +5 dB);
- Shure SM7B: 11 dB equivalent SPL per milli-oersted at 60 Hz (Shure's spec sheet; our SM7 is
  fitted to the SM7B's curves);
- EV RE20: hum pickup -130 dBm in a 60 Hz field of 1 millioersted, typical (EV's product page,
  web: https://products.electrovoice.com/na/en/re20; 150 ohm), at its transformer (the hum-bucking
  coil cancels the moving coil's: CHAINS_PLAN.md NH5);
- Sennheiser MD 421: magnetic-field sensitivity < 5 uV / 5 uT at 50 Hz (the MD 421-II's
  specification, web: https://www.sennheiser.com/globalassets/digizuite/47848-en-md-421-ii-product-specification-v1.1-en.pdf;
  a bound, taken at its value: 0.1 uV in 1e-7 T, the hum linear in the field).

dBm is read as the available power E^2 / (4 R) of the open-circuit hum E behind the rated
impedance R (250 ohm at the 44-BX's and 77-DX's default straps): RCA's matched-load level.
Equivalent SPL: the 1 kHz on-axis SPL whose open-circuit output equals the hum's.
1 gauss = 1 oersted in air = 100 uT.
"""

from __future__ import annotations

import argparse
import dataclasses
import math
import sys

import numpy as np

from varimu.circuit import builder, spec
from varimu.sim import fast

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import chain_passes as cp  # noqa: E402

FIELD_T = 1e-7  # 1 mG = 1 mOe in air
TRIAL = 1e-6  # m^2 per turn (transformers), m^2 turn-area (coils)
CAL = [
    # circuit, pickup part, kind of pickup, hz, ("dbm", target, rated ohm) | ("eq_spl", target)
    ("rca_44bx", "T1", "area_m2", 60.0, ("dbm", -115.0, 250.0)),
    ("rca_77dx", "T1", "area_m2", 60.0, ("dbm", -128.0, 250.0)),
    ("coles_4038", "T1", "area_m2", 50.0, ("eq_spl", 4.0)),
    ("shure_sm7", "MC", "turn_area_m2", 60.0, ("eq_spl", 11.0)),
    ("ev_re20", "T1", "area_m2", 60.0, ("dbm", -130.0, 150.0)),
    ("sennheiser_md421", "MC", "turn_area_m2", 50.0, ("v_rms", 1.0e-7)),
]
SECONDS = 1.0


def _settings():
    return cp._settings(True)  # draft: the hum is linear and tiny


def hum_rms_v(name: str, block: dict | None, field_t: float) -> float:
    """The open-circuit hum at `out` (V rms, all harmonics) in `field_t` (`block` None: the
    file's own)."""
    c = spec.load_circuit(spec.circuit_path(name))
    if block is not None:
        c = dataclasses.replace(c, hum=block)
    ir = builder.build(c, {}, hum=field_t).ir
    s = _settings()
    n = int(SECONDS * s.sample_rate)
    x = np.zeros(n)
    controls = {"p_rear": np.zeros(n)} if any(k.name == "p_rear" for k in ir.controls) else None
    v = np.asarray(fast.run_transient(ir, x, settings=s, controls=controls).vectors["v(out)"])
    v = v[n // 4 :] - np.mean(v[n // 4 :])
    return float(np.sqrt(np.mean(v**2)))


def sensitivity_v_per_pa(name: str) -> float:
    """Open-circuit output at 1 kHz on axis, V rms per Pa rms (the chain's entries)."""
    ch = cp.Chain(name, True, {})
    fs = ch.fs
    t = np.arange(int(0.3 * fs)) / fs
    p = np.sqrt(2) * np.sin(2 * np.pi * 1000.0 * t) * np.minimum(1.0, t / 0.02)
    y = ch.run(p) * ch.out_fs  # volts
    seg = y[len(y) // 2 :]
    return float(np.sqrt(np.mean((seg - seg.mean()) ** 2)))


def measured_db(name: str, target: tuple, e_rms: float) -> float:
    if target[0] == "dbm":
        r = target[2]
        return 10 * math.log10(e_rms**2 / (4 * r) / 1e-3)
    if target[0] == "v_rms":  # in dB re 1 V, so the target compares as 20 log10
        return 20 * math.log10(e_rms)
    s = sensitivity_v_per_pa(name)
    return 20 * math.log10(e_rms / s / 20e-6)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="measure the files' own hum blocks")
    args = ap.parse_args()
    bad = False
    for name, part, kind, hz, target in CAL:
        if args.check:
            block = None
        else:
            block = {
                "hz": {"value": hz, "source": "trial"},
                "field_t": {"value": FIELD_T, "source": "trial"},
                "pickups": {part: {kind: {"value": TRIAL, "source": "trial"}}},
            }
        e = hum_rms_v(name, block, FIELD_T)
        got = measured_db(name, target, e)
        want = 20 * math.log10(target[1]) if target[0] == "v_rms" else target[1]
        unit = {"dbm": "dBm", "eq_spl": "dB eq SPL", "v_rms": "dBV"}[target[0]]
        if args.check:
            ok = abs(got - want) <= 0.5
            bad |= not ok
            print(f"{name:12s} {got:7.2f} {unit} (published {want:+.1f}) {'ok' if ok else 'OFF'}")
        else:
            area = TRIAL * 10 ** ((want - got) / 20)
            print(
                f"{name:12s} trial {got:7.2f} {unit} -> {part}: {kind} {area:.4g} "
                f"(published {want:+.1f})"
            )
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()

"""AM10 step 1, the floor's gate (docs/ANALOG_MAGIC_FABLE.md): is a microphone's response to
its stand's vibration, driven by a kick drum through the floor, within 40 dB of the same
kick's sound at that mic? If not for any mic type, the package closes as inaudible.

In the mic's frame an acceleration a of its body is an inertial force on the diaphragm: a
pressure difference p_eq = sigma a, sigma the moving system's mass per area (from the
fitted component files). The floor's acceleration under the stand: the kick's force into an
infinite plate's point mobility Y = 1 / (8 sqrt(D rho h)), spread to the stand's distance r
as a bending wave (|H0(kr) - (2i/pi) K0(kr)|, the infinite plate's Green's function), times
the share of the beater's force that reaches the floor (`FLOOR_SHARE`), the stand rigid
(transmissibility 1: the worst case). Two floors: 22 mm softwood boards alone (an upper
bound: no joists) and a 150 mm concrete slab.

-> reports/magic/floor/ (summary.json, README.md written by hand).

  uv run --extra listen python scripts/floor_gate.py
"""

from __future__ import annotations

import json
import sys

import numpy as np
from scipy import signal, special

from varimu.config import REPO_ROOT
from varimu.drums import drum

OUT = REPO_ROOT / "reports" / "magic" / "floor"
FS = 48000
R_STAND_M = 1.5  # the stand from the kick (the doc's case)
# provisional: model knowledge (the beater's force is mostly internal to the kick + pedal +
# player system; the vertical force the floor sees is a fraction of it. 1.0 is the bound.)
FLOOR_SHARE = (1.0, 0.1)
FLOORS = {
    # provisional: model knowledge (softwood boards, E along the grain ~10 GPa, 500 kg/m^3)
    "softwood_22mm_boards": {"E_pa": 10e9, "rho": 500.0, "h_m": 0.022, "nu": 0.3},
    # provisional: model knowledge (normal concrete, E ~30 GPa, 2400 kg/m^3)
    "concrete_150mm": {"E_pa": 30e9, "rho": 2400.0, "h_m": 0.150, "nu": 0.2},
}
# Moving mass per area of each mic's moving system, from the fitted components
# (config/components/...): sigma = m / S or rho t for a bare film (no air load: a lower bound).
MICS = {
    "SM57 (R57@4: 60.1 mg on 2.01 cm^2)": 6.0106e-05 / 2.0106e-04,
    "D112 (R_D112@1: 0.657 g on 10.2 cm^2)": 6.5666e-04 / 1.0179e-03,
    "RE20 (R_RE20@1: 0.15 g on 7.07 cm^2)": 1.5e-04 / 7.0686e-04,
    "U47 K47 (K47@3: 6 um PET film, 1390 kg/m^3)": 6.0e-06 * 1390.0,
    "44-BX ribbon (RIBBON_44BX@2: 1.5 mg on 2.81 cm^2)": 1.50e-06 / 2.8059e-04,
}
# The acoustic drive of a gradient mic is the front-rear pressure difference, p k d_eff
# (times the near field's sqrt(1 + 1 / (k r)^2)), not p: the inertial force meets the
# diaphragm directly. d_eff on axis and the mount (rigid clip, or a shock mount's
# second-order isolation at f0 / zeta): all provisional: model knowledge (typical paths
# around a capsule / ribbon, typical shock mounts), the doc's "approximation for gradient
# capsules" made explicit. d_eff None: a pressure capsule (the doc's form).
GRADIENT = {
    "SM57": (0.03, None),
    "D112": (0.05, None),
    "RE20": (0.04, None),
    "U47": (0.02, (10.0, 0.2)),
    "44-BX": (0.03, (8.0, 0.2)),
}
C_M_S = 343.2
THIRDS = [float(1000 * 2 ** (k / 3)) for k in range(-17, -2)]  # 20-500 Hz


def plate(fl):
    D = fl["E_pa"] * fl["h_m"] ** 3 / (12 * (1 - fl["nu"] ** 2))
    m = fl["rho"] * fl["h_m"]
    return D, m


def floor_accel_per_force(f, fl, r):
    """|a / F| at distance r from a point force on an infinite thin plate (m/s^2 per N)."""
    D, m = plate(fl)
    w = 2 * np.pi * f
    k = (w**2 * m / D) ** 0.25
    # Velocity Green's function: v = F * (w / (8 D k^2)) * (H0^(2)(kr) - (2i/pi) K0(kr)) * i ...
    # At r = 0 it is 1 / (8 sqrt(D m)); |.| of the bracket at kr is used for the spread.
    kr = k * r
    spread = np.abs(special.hankel2(0, kr) - 2j / np.pi * special.k0(kr))
    y0 = 1.0 / (8 * np.sqrt(D * m))
    return (
        w * y0 * spread
    )  # |H0(0) - (2i/pi)K0(0)| -> 1 (finite part), so spread re the drive point


def band_levels(x, fs):
    f, p = signal.welch(x, fs, nperseg=min(len(x), 1 << 14))
    out = []
    for fc in THIRDS:
        s = (f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6))
        out.append(float(np.sum(p[s]) * (f[1] - f[0])))
    return np.array(out)


def main() -> int:
    d2 = drum.load("kick_22")
    prep = drum.prepare(d2)
    hit = drum.run(prep, fs=FS, seconds=1.5, velocity_m_s=4.0)
    r_mic = d2.drum.mic_distance_m
    p_ac = hit.pressure_pa * r_mic / R_STAND_M  # the kick's sound at the stand's mic
    P_ac = band_levels(p_ac, FS)
    F = band_levels(hit.force_n, FS)
    summ = {
        "kick": {
            "peak_force_n": float(np.abs(hit.force_n).max()),
            "peak_pressure_pa_at_mic": float(np.abs(p_ac).max()),
            "peak_spl_db_at_mic": float(20 * np.log10(np.abs(p_ac).max() / 2e-5)),
        },
        "bands_hz": THIRDS,
        "cases": {},
    }
    for fname, fl in FLOORS.items():
        for share in FLOOR_SHARE:
            g = np.array([floor_accel_per_force(fc, fl, R_STAND_M) for fc in THIRDS])
            A = F * (share * g) ** 2  # acceleration power per band
            for mic, sigma in MICS.items():
                d_eff, mount = GRADIENT[mic.split()[0]]
                f = np.array(THIRDS)
                k = 2 * np.pi * f / C_M_S
                grad = (k * d_eff) ** 2 * (1 + 1 / (k * R_STAND_M) ** 2)
                tr = 1.0
                if mount is not None:
                    f0, z = mount
                    q = f / f0
                    tr = (1 + (2 * z * q) ** 2) / ((1 - q**2) ** 2 + (2 * z * q) ** 2)
                P_eq = A * sigma**2 * tr
                diff_p = 10 * np.log10(P_eq / P_ac)
                diff = 10 * np.log10(P_eq / (P_ac * grad))
                key = f"{fname} share {share:g} | {mic}"
                summ["cases"][key] = {
                    "sigma_kg_m2": sigma,
                    "pressure_reference_max_db": float(diff_p.max()),
                    "d_eff_m": d_eff,
                    "mount": mount,
                    "vibration_re_acoustic_db": [round(float(v), 1) for v in diff],
                    "max_db": float(diff.max()),
                    "at_hz": THIRDS[int(np.argmax(diff))],
                    "accel_rms_m_s2": float(np.sqrt(A.sum())),
                    "passes_gate": bool(diff.max() > -40.0),
                }
                print(
                    f"{key}: worst band {diff.max():+.1f} dB at "
                    f"{THIRDS[int(np.argmax(diff))]:.0f} Hz "
                    f"(floor accel {np.sqrt(A.sum()):.3g} m/s^2 rms) -> "
                    f"{'PASSES' if diff.max() > -40 else 'closed'}",
                    flush=True,
                )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

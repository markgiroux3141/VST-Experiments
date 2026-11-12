"""Print-through from thermal activation (docs/TAPE_PARTICLES.md, "Print-through"): a
prediction, not a fit. The `none` fit's particles (Stoner-Wohlfarth, K V_act / kT median
150, the volume's log spread 0.9: both provisional) in the AC-erased state sit in a weak
steady field H (the next layer's recording, through the base) for a storage time t at 293
K, then in no field for `t_off` (the reel rewound and played); the remanence left is the
print. The master equation over a constant field is exact in one step of any length, so
every storage time is one step.

The level against the signal, at the print's peak wavelength (TAPE_PARTICLE_RESEARCH.md
3.3: lambda = 2 pi x the overall thickness, 307 um at 15 ips for #111) and long-wavelength
recording: the field of the next layer's magnetization M through the base d (36.1 um) over
the coating delta is H = M (1 - e^{-k delta}) e^{-k d} / 2 (a slab's charge sheets), so
print / signal = chi_print(t) (1 - e^{-k delta}) e^{-k d} / 2, chi_print = M_print / H in
the coating's own units (packing x Ms_p).

Against Manly (Audio, Sept. 1977, Fig. 1, research 3.4): -52 dB at 5 min, -40 dB after a
week at room temperature for 1950-vintage tape, 3.45 dB per decade of time.

    uv run python scripts/tape_particle_print.py -> reports/tape/particles/print.json
"""

from __future__ import annotations

import json
import math
import sys

import numpy as np

from varimu.config import REPO_ROOT
from varimu.tape_particles import bench as bn
from varimu.tape_particles import ensemble as ens

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import tape_particle_no21 as tn  # noqa: E402

OUT = REPO_ROOT / "reports" / "tape" / "particles"


def print_susceptibility(spec, n, seed, h_a_m, t_s, t_off_s=10.0, temp_k=293.0):
    s = spec.with_(temp_k=temp_k)
    box = bn.make_box(s.with_(packed=False), n, seed=seed)
    parts = box.particles()
    out = []
    for t in t_s:
        res = []
        for sg in (1.0, -1.0):
            p = np.full(n, 0.5)
            h = np.zeros((n, 3))
            h[:, 0] = sg * h_a_m
            p, _ = ens.step(parts, h, p, t, s)
            p, m = ens.step(parts, np.zeros((n, 3)), p, t_off_s, s)
            res.append((box.v * m[:, 0]).sum() / box.v.sum())
        out.append(0.5 * (res[0] - res[1]))
    return np.array(out) / h_a_m


def main() -> int:
    spec = tn.particle_spec()
    ms_coat = spec.packing * spec.ms_p_a_m
    t_s = np.array([60.0, 300.0, 3600.0, 86400.0, 604800.0, 2.6e6, 3.15e7])
    lam = 2 * math.pi * 48.8e-6  # research 3.3: 2 pi x #111's overall thickness
    k = 2 * math.pi / lam
    geo = (1 - math.exp(-k * 12.7e-6)) * math.exp(-k * 36.1e-6) / 2
    res = {"t_s": t_s.tolist(), "geometry_factor": geo, "lambda_m": lam, "runs": {}}
    for kv in (60.0, 150.0, 400.0):
        sp_ = spec.with_(kv_kt_median=kv)
        for h_oe in (2.0, 10.0):
            chis = []
            for seed in (1, 2):
                box_spec = sp_
                p = print_susceptibility(box_spec, 40000, seed, h_oe * bn.OE, t_s)
                chis.append(p)
            m = np.mean(chis, axis=0)  # M_frac per A/m
            chi = m * ms_coat  # M_print / H, the coating's own units
            db = 20 * np.log10(np.maximum(np.abs(chi) * geo, 1e-12))
            slope = float(np.polyfit(np.log10(t_s[1:5]), db[1:5], 1)[0])
            res["runs"][f"kv{kv:g}_h{h_oe:g}"] = {
                "chi": chi.tolist(),
                "print_db": db.tolist(),
                "db_per_decade_5min_1week": slope,
            }
            print(f"KV/kT {kv:g}, H {h_oe:g} Oe: {np.round(db, 1)} dB, {slope:.2f} dB/decade")
    (OUT / "print.json").write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

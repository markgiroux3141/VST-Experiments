"""The validation ladder's first rung (docs/TAPE_PARTICLES.md): one Stoner-Wohlfarth particle
against the analytic astroid and hysteresis loops, and thermal activation against the
Neel-Brown / Sharrock switching field at two sweep rates (athermal SW, then the 60 Hz meter
and a 70 kHz bias half-cycle). -> reports/tape/particles/sw_validation.{png,json}

    uv run python scripts/tape_particle_validate.py
"""

from __future__ import annotations

import json
import math
import sys

import numpy as np

from varimu.config import REPO_ROOT
from varimu.tape_particles import ensemble as ens
from varimu.tape_particles import sw

OUT = REPO_ROOT / "reports" / "tape" / "particles"


def loop(psi: float, e0_kt: float, f_hz: float, m: int = 1000, hmax: float = 1.5):
    """One particle's M along the field over a sinusoidal loop (reduced field h = H / H_K)."""
    spec = ens.ParticleSpec(f0_hz=1e9)
    n = np.array([[math.cos(psi), math.sin(psi), 0.0]])
    parts = ens.Particles(n, np.array([1.0]), np.array([1.0]), np.array([e0_kt]), np.zeros((1, 3)))
    k = np.arange(1, 2 * m + 1)
    h = hmax * np.cos(2 * math.pi * k / m)
    p = np.array([1.0])
    out = []
    for hk in h:
        p, mm = ens.step(parts, np.array([[hk, 0.0, 0.0]]), p, 1.0 / (f_hz * m), spec)
        out.append(mm[0, 0])
    return h[m:], np.array(out[m:])


def analytic_loop(psi: float, h: np.ndarray, branch: int) -> np.ndarray:
    """The athermal SW loop's M along the field: the state's energy minimum, followed from
    saturation (branch +1: descending from +h, -1 ascending)."""
    th = math.pi * (0 if branch > 0 else 1)
    out = []
    for hv in h:
        # Minimize e = 1/2 sin^2(t) - h cos(t - psi) by Newton from the last minimum.
        for _ in range(60):
            f = math.sin(th) * math.cos(th) + hv * math.sin(th - psi)
            d = math.cos(2 * th) + hv * math.cos(th - psi)
            if d <= 0:  # the minimum vanished: jump to the other one
                th = th + math.pi * 0.9
                continue
            th -= f / d
        out.append(math.cos(th - psi))
    return np.array(out)


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))
    psi = np.linspace(0.001, math.pi / 2 - 0.001, 91)
    hs = np.linspace(0.3, 1.2, 9001)
    num = []
    for p in psi:
        dp, *_ = sw.barriers(-hs * math.cos(p), hs * math.sin(p))
        num.append(hs[np.argmax(dp == 0)])
    num = np.array(num)
    ana = sw.astroid_hsw(psi)
    res["astroid_max_rel_err"] = float(np.max(np.abs(num / ana - 1)))
    ax[0].plot(np.degrees(psi), ana, "k-", label="astroid (analytic)")
    ax[0].plot(np.degrees(psi), num, "C1.", ms=3, label="grid + Newton barrier = 0")
    ax[0].set(
        xlabel="field angle to the easy axis (deg)",
        ylabel="h_sw = H_sw / H_K",
        title=f"switching field (max error {100 * res['astroid_max_rel_err']:.2f}%)",
    )
    for i, deg in enumerate((10, 45, 80)):
        p = math.radians(deg)
        h, m = loop(p, 1e6, 60.0)
        desc = h[: len(h) // 2]
        ax[1].plot(h, m, f"C{i}-", lw=1, label=f"{deg} deg, kMC master eq. (athermal)")
        ax[1].plot(desc, analytic_loop(p, desc, 1), f"C{i}:", lw=2, label=f"{deg} deg, analytic")
        res[f"loop_{deg}_max_err"] = float(
            np.max(np.abs(m[: len(desc)] - analytic_loop(p, desc, 1)))
        )
    ax[1].set(xlabel="h", ylabel="m along the field", title="single-particle loops")
    # Thermal: the switching field against K V / kT and rate, psi = 0 (Sharrock n = 1/2).
    kvs = np.geomspace(40, 4000, 6)
    for f, c in ((60.0, "C0"), (70e3, "C3")):
        hsw = []
        for kv in kvs:
            h, m = loop(0.0, 2.0 * kv, f, m=2000, hmax=1.2)
            desc = slice(0, len(h) // 2)
            j = int(np.argmax(m[desc] < 0))
            hsw.append(-h[desc][j])
        hsw = np.array(hsw)
        # Sharrock: Hc = H_K (1 - sqrt(ln(f0 t / ln 2) / (K V / kT))), t the time the field
        # spends near the switching field: ~1 / (2 pi f h_sw) per unit of h.
        t = 1.0 / (2 * math.pi * f * np.maximum(np.sqrt(1.2**2 - hsw**2), 1e-3)) * 0.02
        shar = 1 - np.sqrt(np.log(1e9 * t / math.log(2)) / kvs)
        ax[2].semilogx(kvs, hsw, c + "o", label=f"kMC, {f:g} Hz loop")
        ax[2].semilogx(kvs, shar, c + "--", label=f"Sharrock n = 1/2, {f:g} Hz (dh 0.02)")
        res[f"thermal_hsw_{f:g}hz"] = dict(
            zip([f"{k:.0f}" for k in kvs], hsw.tolist(), strict=True)
        )
    ax[2].set(xlabel="K V / kT", ylabel="h_sw (field along the axis)", title="thermal activation")
    for a in ax:
        a.grid(alpha=0.3)
        a.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "sw_validation.png", dpi=110)
    (OUT / "sw_validation.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if not isinstance(v, dict)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

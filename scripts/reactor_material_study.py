"""Tube synth S1, material step: a core's incremental permeability under DC bias.

A saturable reactor's inductance follows the core's incremental permeability at its DC
operating point. This measures it on the Jiles-Atherton reference alone (no circuit, no
engine: varimu.synth.reactor.incremental_permeability, whose docstring has the method)
and compares it with Gans' law.

No published curve of incremental permeability against DC bias was found for mumetall
(searched 2026-10-29: Vacuumschmelze / Matthey, Carpenter HyMu 80, Magnetics, Arnold,
Reference Data for Radio Engineers 1946; the one measurement found, IEEE 1464206, is
paywalled). So the reference is Gans' law of reversible permeability (provisional:
model knowledge; Gans 1910, shown against measured materials in Bozorth,
Ferromagnetism, 1951): chi_rev / chi_rev(0) = 3 L'(x) with M / Ms = L(x), L the
Langevin function. It is a theory with scatter in real materials, so the comparison
is loose (a factor of 2). A measured curve replaces it when one is found or measured.

Also tabulated: the cutoff span an LC filter gets from the reactor over the bias range,
for a few air-gap ratios (1 / mu_eff = 1 / mu + gap / path).

    uv run python scripts/reactor_material_study.py [--material mumetall] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from varimu.devices.core import MU0, core_model, materials
from varimu.synth.reactor import gans_ratio, incremental_permeability

ROOT = Path(__file__).resolve().parents[1]
H_DC_A_PER_M = (0.0, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
RIPPLES_T = (0.5e-3, 5e-3)  # peak-to-peak flux density of the signal on the bias
GAP_RATIOS = (0.0, 1e-5, 1e-4, 1e-3)  # gap length / magnetic path length
GANS_TOLERANCE = 2.0  # JA / Gans within this factor (loose: Gans is a theory)
SPAN_H_MAX_A_PER_M = 100.0  # the bias range the cutoff span is quoted over


def study(material: str) -> dict:
    core = core_model("study", material, path_m=0.1)
    ms = core.ms_a_per_m
    rows = []
    for db in RIPPLES_T:
        mu0_inc = None
        for h_dc in H_DC_A_PER_M:
            b_dc, mu = incremental_permeability(core, h_dc, db)
            mu0_inc = mu if mu0_inc is None else mu0_inc
            m_over_ms = (b_dc / MU0 - h_dc) / ms
            gans = mu0_inc * gans_ratio(m_over_ms)
            rows.append(
                {
                    "ripple_t": db,
                    "h_dc_a_per_m": h_dc,
                    "b_dc_t": b_dc,
                    "m_over_ms": m_over_ms,
                    "mu_inc": mu,
                    "mu_gans": gans,
                    "ja_over_gans": mu / gans,
                }
            )
    spans = []
    for db in RIPPLES_T:
        sel = [r for r in rows if r["ripple_t"] == db]
        mu_lo_bias = sel[0]["mu_inc"]
        mu_hi_bias = next(r["mu_inc"] for r in sel if r["h_dc_a_per_m"] == SPAN_H_MAX_A_PER_M)
        for g in GAP_RATIOS:
            l_max = 1.0 / (1.0 / mu_lo_bias + g)
            l_min = 1.0 / (1.0 / mu_hi_bias + g)
            ratio = l_max / l_min
            spans.append(
                {
                    "ripple_t": db,
                    "gap_ratio": g,
                    "mu_eff_max": l_max,
                    "mu_eff_min": l_min,
                    "inductance_ratio": ratio,
                    "cutoff_octaves": 0.5 * np.log2(ratio),
                }
            )
    # Checked over the bias range the filter uses; past it (M / Ms ~ 0.99) Gans' law is
    # weakest and the JA core sits ~2x above it (21 vs 10 at 300 A/m).
    checked = [r for r in rows if 0.0 < r["h_dc_a_per_m"] <= SPAN_H_MAX_A_PER_M]
    worst = max(checked, key=lambda r: abs(np.log(r["ja_over_gans"])))
    return {
        "material": material,
        "source": materials()[material]["source"],
        "reference": "Gans' law (provisional: model knowledge), normalized to the JA "
        "value at zero bias for the same ripple",
        "rows": rows,
        "cutoff_span_over_bias_a_per_m": [0.0, SPAN_H_MAX_A_PER_M],
        "spans": spans,
        "worst_ja_over_gans": worst["ja_over_gans"],
        "worst_at": {"h_dc_a_per_m": worst["h_dc_a_per_m"], "ripple_t": worst["ripple_t"]},
        "within_tolerance": bool(
            all(1 / GANS_TOLERANCE <= r["ja_over_gans"] <= GANS_TOLERANCE for r in checked)
        ),
        "tolerance_factor": GANS_TOLERANCE,
    }


def plot(result: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.5))
    for db, color in zip(RIPPLES_T, ("C0", "C1"), strict=True):
        sel = [r for r in result["rows"] if r["ripple_t"] == db and r["h_dc_a_per_m"] > 0]
        h = [r["h_dc_a_per_m"] for r in sel]
        ax.loglog(h, [r["mu_inc"] for r in sel], "o-", color=color, label=f"JA, {db * 1e3:g} mT pp")
        ax.loglog(
            h,
            [r["mu_gans"] for r in sel],
            "--",
            color=color,
            label=f"Gans' law, {db * 1e3:g} mT pp",
        )
    ax.set_xlabel("DC bias H (A/m)")
    ax.set_ylabel("incremental relative permeability")
    ax.set_title(f"{result['material']}: incremental permeability under DC bias")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--material", default="mumetall")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "tube_synth")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result = study(args.material)
    stem = f"incremental_permeability_{args.material}"
    (args.out / f"{stem}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    plot(result, args.out / f"{stem}.png")
    print(
        f"{args.material}: JA vs Gans worst {result['worst_ja_over_gans']:.2f} at "
        f"{result['worst_at']}; within x{GANS_TOLERANCE:g}: {result['within_tolerance']}"
    )
    for r in result["rows"]:
        print(
            f"  {r['ripple_t'] * 1e3:4.1f} mT  H {r['h_dc_a_per_m']:6.1f}  "
            f"B {r['b_dc_t'] * 1e3:6.1f} mT  mu_inc {r['mu_inc']:8.0f}  "
            f"Gans {r['mu_gans']:8.0f}  ratio {r['ja_over_gans']:.2f}"
        )
    for s in result["spans"]:
        print(
            f"  {s['ripple_t'] * 1e3:4.1f} mT  gap/path {s['gap_ratio']:7.0e}  "
            f"L ratio {s['inductance_ratio']:7.1f}  cutoff {s['cutoff_octaves']:.2f} octaves"
        )


if __name__ == "__main__":
    main()

"""Fit the 5E3 output transformer's unpublished construction to its reproduction's
measured figures and write the design (docs/COMPONENT_EDITOR_PLAN.md C2 step 5).

    uv run python scripts/fit_ot_5e3.py [--show]   # -> config/designs/ot_5e3.yaml

Targets: Amplified Parts P-TGO-002 (data/schematics/fender_5e3/README.md): 8000 ohm CT :
8 ohm; DCR Green-Red 147.2, Red-Yellow 195.3, secondary 0.493 ohm; 3.67 H per primary half
(1 kHz, 1 V, open circuit); leakage Green-Red 40.47 mH, Red-Yellow 19.31 mH (1 kHz, 1 V,
the secondary shorted).

What the figures say about the construction (the fit's assumptions):
- the low-resistance half (Green-Red) is wound first, on the bobbin, and the other half
  (Red-Yellow) over it: its turns are longer;
- the secondary is wound last, outside both: the inner half, farther from it, has the
  larger leakage (with the secondary between the halves both leakages would be alike);
- one primary half over the other can't make a 1.33 resistance ratio by turn length alone
  in this window with the leakages measured (that takes ~6 mm per half), so the outer half
  is wound with thinner wire: the fit picks both sizes from the wire table.

Free values: turns per half (from the inner half's resistance), the two wire sizes (a
search over the table), the interlayer paper and the insulation between the halves and
before the secondary (least squares on the outer half's resistance and both leakages), the
secondary wire (nearest resistance) and the joint gap (the inductance). The search runs on
the 1D leakage formula; the winner is refined on the 2D field solution (`leakage_method:
field`: the formula runs 3-7% low with paper this thick) and written with it.

Result (2026-11-04): one wire in both halves fits best; no construction of one half over the
other reaches the 1.33 resistance ratio here with these leakages (the outer half's comes out
~8% low; a thinner outer wire overshoots by ~10%). Everything else is
provisional, sourced in the design file. The compiler is Rust (varimu-components); this
script only drives it: `cargo build --release -p varimu-components` first.
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import brentq, least_squares

REPO = Path(__file__).resolve().parents[1]
EXE = (
    REPO
    / "target"
    / "release"
    / ("varimu-components.exe" if sys.platform == "win32" else "varimu-components")
)
OUT = REPO / "config" / "designs" / "ot_5e3.yaml"
SCRATCH = REPO / "cache" / "fit_ot_5e3"

SHEET = "web: https://www.amplifiedparts.com/sites/default/files/associated_files/p-tgo-002.pdf"
TARGET = {
    "dcr_a": 147.2,
    "dcr_b": 195.3,
    "dcr_s": 0.493,
    "l_open": 3.67,
    "leak_a": 40.47e-3,
    "leak_b": 19.31e-3,
}
RATIO = 2.0 / math.sqrt(8000.0 / 8.0)  # secondary turns per primary half

# Provisional construction values (model knowledge; each in the design with its source).
TRAVERSE_M = 1.313 * 0.0254 - 2 * (0.8e-3 + 1.5e-3)
PITCH = 1.0 / 0.85


@dataclass
class Params:
    turns: int
    wire_a: str
    wire_b: str
    wire_s: str
    interlayer_m: float
    ab_m: float
    bs_m: float
    gap_m: float
    method: str = "formula"


def overall_m(wire: str) -> float:
    """The overall diameter the compiler takes (wire.yaml's nominal: the middle of
    [min, max] where none is printed)."""
    data = yaml.safe_load(
        (REPO / "config" / "transformer" / "wire.yaml").read_text(encoding="utf-8")
    )
    w = wire.split()
    if w[0] == "AWG":
        row = data["awg"]["overall"][int(w[1])][w[2]]
        scale = 0.0254
    else:
        row = data["metric"]["overall"][float(w[0])][f"grade{w[3]}"]
        scale = 1e-3
    return (row[1] if len(row) == 3 else 0.5 * (row[0] + row[1])) * scale


def layers(turns: int, wire: str) -> int:
    per_layer = math.floor(TRAVERSE_M / (overall_m(wire) * PITCH))
    return math.ceil(turns / per_layer)


def v(x, source: str) -> str:
    return f'{{value: {x}, source: "{source}"}}'


FIT = "derived: scripts/fit_ot_5e3.py to P-TGO-002 (" + SHEET + ")"
MK = "provisional: model knowledge"
SRC = {
    "design": (
        "Fender 5E3 output transformer (original Triad 50246; 8 k CT : 8 ohm): the construction"
        " isn't published (frames only), so it is fitted to the reproduction's DC resistances,"
        f" inductance and leakage, {SHEET}"
    ),
    "lamination": (
        "derived: the 2-3/4 x 2-1/4 in frames of reproductions (data/schematics/fender_5e3/"
        "README.md; P-TGO-002 draws 2.285 in across the frame) hold the EI-87 lamination"
        " (2.625 x 2.187 in); bounds EI-75 to EI-100"
    ),
    "material": (
        f"{MK} (silicon-steel EI laminations; the only silicon steel in config/magnetics.yaml,"
        " as the 5E3 circuit used it before; the era's non-oriented M-19 is an option)"
    ),
    "stack": "web: Tube Amp Doctor quotes a 1 in stack (data/schematics/fender_5e3/README.md)",
    "stacking_factor": (
        "web: McLyman, Transformer and Inductor Design Handbook 3rd ed. Table 3-1 (14 mil"
        " laminations interleaved 1x1: 0.90), https://coefs.charlotte.edu/mnoras/files/2013/03/"
        "Transformer-and-Inductor-Design-Handbook_Chapter_3.pdf"
    ),
    "stacking": f"{MK} (push-pull output transformers, ungapped: E and I interleaved)",
    "gap": (
        f"{FIT}: 3.67 H per half (1 kHz, 1 V) in the material model; also stands in for the"
        " low-field permeability of the era's steel"
    ),
    "wall": f"{MK} (a paper or fibre tube, ~1 mm)",
    "cheek": f"{MK} (fibre flanges, ~0.8 mm)",
    "margin": f"{MK} (creepage margin each end, ~1.5 mm)",
    "pitch": (
        "web: https://lantern.mediahist.org/catalog/radiobroadcast16gardrich_0045 (Radio"
        " Broadcast Nov 1929 p.48: turns per layer = winding length / wire diameter x a space"
        " factor of 85% for small wires)"
    ),
    "arrangement": (
        f"{MK} (layer-wound primary halves and secondary, no interleaving: what the measured"
        " asymmetries imply, scripts/fit_ot_5e3.py)"
    ),
    "layers": "derived: turns / turns per layer (the traverse over the wire at the pitch factor)",
    "enamel": f"{MK} (heavy-build enamelled magnet wire)",
    "interlayer": (
        f"{FIT}: the outer half's resistance and the leakages (bounds 0.025-0.13 mm, 0.001-0.005"
        " in kraft)"
    ),
    "kraft_layers": f"{MK} (kraft interlayer paper)",
    "kraft_wraps": f"{MK} (kraft wraps between windings)",
    "turns": f"{FIT}: the inner half's resistance",
    "wire": f"{FIT}: the wire table searched (one size in both halves fits best)",
    "sec_turns": "derived: 8000 ohm CT : 8 ohm, secondary turns 2 / sqrt(8000 / 8) of a half",
    "sec_wire": f"{FIT}: the secondary resistance, nearest size",
    "v_rms": "derived: 15 W into 8000 ohm (P-TGO-002), sqrt(P Z)",
    "f_hz": f"{MK} (a guitar amp OT rated near its lowest note, ~70-80 Hz)",
}


def winding(label: str, turns: tuple, wire: str, n_layers: int, interlayer: float | None) -> str:
    out = (
        f"  - winding: {label}\n"
        f"    turns: {v(*turns)}\n"
        f"    layers: {v(n_layers, SRC['layers'])}\n"
        f"    wire: {v(wire, SRC['wire'] if label != 's' else SRC['sec_wire'])}\n"
        f"    enamel: {v('enamel', SRC['enamel'])}\n"
    )
    if interlayer is not None:
        out += (
            f"    interlayer: {{thickness_m: {v(f'{interlayer:.4e}', SRC['interlayer'])},"
            f" dielectric: {v('kraft_dry', SRC['kraft_layers'])}}}\n"
        )
    return out


def insulation(t_m: float, what: str) -> str:
    th = v(f"{t_m:.4e}", f"{FIT}: {what} (bounds 0.05-2.0 mm)")
    return (
        f"  - insulation: {{thickness_m: {th}, dielectric: {v('kraft_dry', SRC['kraft_wraps'])}}}\n"
    )


def design_text(p: Params) -> str:
    ns = round(RATIO * p.turns)
    lines = [
        "# The Fender 5E3's output transformer by its construction, fitted to the measured",
        "# figures of Amplified Parts' reproduction P-TGO-002 (data/schematics/fender_5e3/).",
        "# Written by scripts/fit_ot_5e3.py (its docstring lists what the figures imply about",
        "# the construction); compiled and saved by `cargo run -p varimu-components -- save",
        "# config/designs/ot_5e3.yaml`.",
        "name: OT_5E3",
        "kind: transformer",
        f'source: "{SRC["design"]}"',
        "core:",
        f"  lamination: {v('EI-87', SRC['lamination'])}",
        f"  material: {v('grain_oriented_si_steel', SRC['material'])}",
        f"  stack_m: {v(0.0254, SRC['stack'])}",
        f"  stacking_factor: {v(0.90, SRC['stacking_factor'])}",
        f"  stacking: {v('interleaved', SRC['stacking'])}",
        f"  joint_gap_m: {v(f'{p.gap_m:.4e}', SRC['gap'])}",
        "bobbin:",
        f"  wall_m: {v(1.0e-3, SRC['wall'])}",
        f"  cheek_m: {v(0.8e-3, SRC['cheek'])}",
        f"  margin_m: {v(1.5e-3, SRC['margin'])}",
        f"  pitch_factor: {v(round(PITCH, 4), SRC['pitch'])}",
        f"arrangement: {v('layer', SRC['arrangement'])}",
        "windings: [pa, pb, s]",
        "sections:",
    ]
    body = (
        winding("pa", (p.turns, SRC["turns"]), p.wire_a, layers(p.turns, p.wire_a), p.interlayer_m)
        + insulation(p.ab_m, "between the primary halves")
        + winding(
            "pb", (p.turns, SRC["turns"]), p.wire_b, layers(p.turns, p.wire_b), p.interlayer_m
        )
        + insulation(p.bs_m, "between the primary and the secondary")
        + winding("s", (ns, SRC["sec_turns"]), p.wire_s, layers(ns, p.wire_s), None)
    )
    tail = []
    if p.method == "field":
        tail.append("leakage_method: field")
    tail += [
        "rating:",
        "  windings: [pa, pb]",
        f"  v_rms: {v(round(math.sqrt(15.0 * 8000.0), 2), SRC['v_rms'])}",
        f"  f_hz: {v(70.0, SRC['f_hz'])}",
    ]
    return "\n".join(lines) + "\n" + body + "\n".join(tail) + "\n"


def compile_report(p: Params) -> dict:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    f = SCRATCH / "trial.yaml"
    f.write_text(design_text(p), encoding="utf-8")
    out = subprocess.run(
        [str(EXE), "compile", str(f), "--yaml"], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    return yaml.safe_load(out.stdout)


def figures(p: Params) -> dict:
    d = compile_report(p)
    r, w = d["report"], d["report"]["windings"]
    return {
        "dcr_a": w["pa"]["dcr_ohm"],
        "dcr_b": w["pb"]["dcr_ohm"],
        "dcr_s": w["s"]["dcr_ohm"],
        "l_open": w["pa"]["magnetizing_h"] + d["compiled"]["windings"]["pa"]["leak"],
        "leak_a": r["short_circuit_h"]["pa (s shorted)"],
        "leak_b": r["short_circuit_h"]["pb (s shorted)"],
        "warnings": r["warnings"],
        "window": r["window"],
    }


def fit_for(wire_a: str, wire_b: str) -> tuple[Params, float]:
    p = Params(1000, wire_a, wire_b, "AWG 22 heavy", 0.05e-3, 0.25e-3, 0.5e-3, 10e-6)
    best = None
    for _ in range(3):
        # Turns: the inner half's resistance (it doesn't depend on the insulation outside it).
        def dcr_a(n: float) -> float:
            p.turns = round(n)
            return figures(p)["dcr_a"] - TARGET["dcr_a"]

        n = brentq(dcr_a, 300, 4000, xtol=0.5)
        p.turns = round(n)

        # The insulations: the outer half's resistance and both leakages.
        def res(x: np.ndarray) -> np.ndarray:
            p.interlayer_m, p.ab_m, p.bs_m = (float(y) * 1e-3 for y in x)
            f = figures(p)
            return np.log([f[k] / TARGET[k] for k in ("dcr_b", "leak_a", "leak_b")])

        sol = least_squares(
            res,
            [p.interlayer_m * 1e3, p.ab_m * 1e3, p.bs_m * 1e3],
            bounds=([0.025, 0.05, 0.05], [0.13, 2.0, 2.0]),
            diff_step=1e-3,
        )
        p.interlayer_m, p.ab_m, p.bs_m = (float(y) * 1e-3 for y in sol.x)
        best = float(np.sqrt(np.mean(sol.fun**2)))
    # The secondary: the nearest size.
    errs = []
    for g in range(18, 27):
        p.wire_s = f"AWG {g} heavy"
        errs.append((abs(math.log(figures(p)["dcr_s"] / TARGET["dcr_s"])), p.wire_s))
    p.wire_s = min(errs)[1]

    # The joint gap: the inductance.
    def l_open(g_um: float) -> float:
        p.gap_m = g_um * 1e-6
        return math.log(figures(p)["l_open"] / TARGET["l_open"])

    p.gap_m = brentq(l_open, 0.01, 500.0, xtol=1e-3) * 1e-6
    return p, best


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--show", action="store_true", help="print every wire pair's fit")
    args = ap.parse_args()
    if not EXE.exists():
        sys.exit(f"{EXE} missing: cargo build --release -p varimu-components")
    results = []
    awg = [f"AWG {g} heavy" for g in range(33, 38)]
    metric = [
        f"{d} mm grade 1"
        for d in ("0.112", "0.12", "0.125", "0.13", "0.14", "0.15", "0.16", "0.18")
    ]
    pairs = [(a, b) for fam in (awg, metric) for i, a in enumerate(fam) for b in fam[i : i + 3]]
    for wa, wb in pairs:
        a, b = wa, wb
        try:
            p, rms = fit_for(wa, wb)
        except (ValueError, RuntimeError) as err:
            print(f"{a} / {b}: no fit ({str(err).strip()[:80]})")
            continue
        f = figures(p)
        # Only window warnings disqualify (a coupled leakage is fine).
        bad = [w for w in f["warnings"] if not w.startswith("leakage:")]
        results.append((rms if not bad else rms + 10.0, p, f))
        if args.show:
            print(
                f"{a} / {b}: {p.turns} turns, rms {100 * rms:.2f}%, " + ("; ".join(bad) or "fits")
            )
    rms, p, f = min(results, key=lambda r: r[0])
    # Refine on the 2D field solution (the formula runs 3-7% low with paper this thick):
    # the same wires and turns, the insulations and then the gap again.
    p.method = "field"

    def res(x: np.ndarray) -> np.ndarray:
        p.interlayer_m, p.ab_m, p.bs_m = (float(y) * 1e-3 for y in x)
        g = figures(p)
        return np.log([g[k] / TARGET[k] for k in ("dcr_b", "leak_a", "leak_b")])

    sol = least_squares(
        res,
        [p.interlayer_m * 1e3, p.ab_m * 1e3, p.bs_m * 1e3],
        bounds=([0.025, 0.05, 0.05], [0.13, 2.0, 2.0]),
        diff_step=1e-3,
        max_nfev=40,
    )
    p.interlayer_m, p.ab_m, p.bs_m = (float(y) * 1e-3 for y in sol.x)

    def l_open(g_um: float) -> float:
        p.gap_m = g_um * 1e-6
        return math.log(figures(p)["l_open"] / TARGET["l_open"])

    p.gap_m = brentq(l_open, 0.01, 500.0, xtol=1e-3) * 1e-6
    f = figures(p)
    OUT.write_text(design_text(p), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)}: {p}")
    for k, want in TARGET.items():
        print(f"  {k}: {f[k]:.6g} (target {want:.6g}, {100 * (f[k] / want - 1):+.2f}%)")
    print(f"  window: {f['window']}")
    for w in f["warnings"]:
        print(f"  warning: {w}")


if __name__ == "__main__":
    main()

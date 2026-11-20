"""Fit a gramophone's provisional values to Maxfield and Harrison's (1926) Fig. 20
(data/datasheets/maxfield_harrison_1926_fig20.csv; docs/PHONO_PLAN.md G2):
`victor_exhibition` to curve B ("one of the best commercial machines previously on the
market"), `victor_orthophonic` to curve A (the Orthophonic).

The target is the shape of the reproducer's output (gramophone.output_row) per groove
velocity (the level is free: the figure's scale is relative). Fitted, in log space within
physical bounds, with a weak pull toward the starting values, only what is provisional: for
the Victor the sound-box's diaphragm thickness and damping, the stylus bar's lever ratio,
pivot springs and masses, the air chamber, the tone arm's bore and the horn; for the
Orthophonic the soft compliances, the losses, the horn's length and the neck (its design
values are the paper's). The needle is not fitted: its stiffness is the paper's
needle-point compliance (see config).

    uv run python scripts/fit_gramophone.py [--machine victor_exhibition] [--write] [--show]
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # threaded small solves ran ~100x slower

import argparse
import csv
import re
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from varimu.phono import gramophone as gr

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data" / "datasheets" / "maxfield_harrison_1926_fig20.csv"
PRIOR = 0.05  # dB of residual per natural-log unit away from the start
FLOOR_DB = 10.0  # below the curve's first point the model stays this far under it
ENVELOPE_DB = 6.0  # on a dense grid the model may rise this far over the curve's line
CURVE = "B"

# machine: (curve, lowest and highest frequency fitted, [(block, key, lower, upper)])
PARAMS_VICTOR = [
    ("soundbox", "diaphragm_thickness_m", 8e-5, 3e-4),
    ("soundbox", "diaphragm_q", 2.0, 20.0),
    ("soundbox", "lever_ratio", 0.6, 1.5),
    ("soundbox", "pivot_stiffness_n_m", 200.0, 2e4),
    ("soundbox", "pivot_resistance_ns_m", 0.03, 3.0),
    ("soundbox", "chuck_mass_kg", 5e-5, 1e-3),
    ("soundbox", "link_mass_kg", 2e-5, 5e-4),
    ("soundbox", "cavity_height_m", 3e-4, 3e-3),
    ("arm", "tube_radius_out_m", 0.012, 0.025),
    ("horn", "length_m", 0.4, 0.9),
    ("horn", "mouth_radius_m", 0.15, 0.35),
]
PARAMS_ORTHO = [
    ("orthophonic", "soft_compliance_hz", 15.0, 90.0),
    ("orthophonic", "loss_q", 5.0, 100.0),
    ("orthophonic", "horn_length_m", 1.2, 2.4),
    ("orthophonic", "neck_length_m", 0.01, 0.08),
]
MACHINES = {
    "victor_exhibition": ("B", 238.0, 3900.0, PARAMS_VICTOR),
    "victor_orthophonic": ("A", 115.0, 3900.0, PARAMS_ORTHO),
}
PARAMS = PARAMS_VICTOR


def target(curve: str, lo: float, hi: float):
    with DATA.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["curve"] == curve]
    f = np.array([float(r["f_hz"]) for r in rows])
    level = np.array([float(r["level_db"]) for r in rows])
    keep = (f >= lo) & (f <= hi)
    return f[keep], level[keep]


def model_db(spec: dict, f: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.abs(gr.reproducer_response(spec, f) / (2j * np.pi * f)))


def with_params(spec: dict, x: np.ndarray) -> dict:
    out = {k: dict(v) for k, v in spec.items()}
    for (block, key, _, _), v in zip(PARAMS, np.exp(x), strict=True):
        out[block][key] = float(v)
    return out


def shape_error(spec: dict, f, level) -> np.ndarray:
    e = model_db(spec, f) - level
    return e - e.mean()


def guards(spec: dict, f, level) -> np.ndarray:
    """Penalties the read points alone can't see: a resonance below the curve's first
    point (where the figure's curve drops to its floor: nothing is plotted under it) or
    between two read points. Both relative to the shape's best level offset."""
    off = np.mean(level - model_db(spec, f))
    below = np.geomspace(0.55 * f[0], 0.95 * f[0], 8)
    floor = np.maximum(0.0, model_db(spec, below) + off - (level[0] - FLOOR_DB))
    dense = np.geomspace(f[0], f[-1], 120)
    line = np.interp(np.log(dense), np.log(f), level)
    over = np.maximum(0.0, model_db(spec, dense) + off - line - ENVELOPE_DB)
    return np.concatenate([floor, over])


def write(machine: str, spec: dict, rms_db: float) -> None:
    path = ROOT / "config" / "phono" / f"{machine}.yaml"
    text = path.read_text(encoding="utf-8")
    for block, key, _, _ in PARAMS:
        start = re.search(rf"^{block}:\s*$", text, re.M).end()
        nxt = re.search(r"^\S", text[start:], re.M)
        end = start + (nxt.start() if nxt else len(text) - start)
        body = text[start:end]
        line = re.compile(rf"^  {key}: \{{value: [^,]+, source: \"(.*)\"\}}$", re.M)
        m = line.search(body)
        if m is None:
            raise KeyError(f"{block}.{key}")
        old = m.group(1)
        old = re.sub(r"^fitted: [^;]*; was \S+ \(", "", old)
        old = old[:-1] if old.endswith(")") and "fitted:" in m.group(0) else old
        src = (
            f"fitted: Maxfield and Harrison 1926 Fig. 20 curve {CURVE} by "
            f"scripts/fit_gramophone.py "
            f"({rms_db:.1f} dB rms over the curve's shape); was {spec['_start'][block][key]:.4g} "
            f"({old})"
        )
        new_line = f'  {key}: {{value: {spec[block][key]:.4g}, source: "{src}"}}'
        body = body[: m.start()] + new_line + body[m.end() :]
        text = text[:start] + body + text[end:]
    path.write_text(text, encoding="utf-8", newline="\n")
    print("wrote", path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--machine", default="victor_exhibition")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    global PARAMS, CURVE
    CURVE, lo_hz, hi_hz, PARAMS = MACHINES[args.machine]
    spec = gr.load(args.machine)
    f, level = target(CURVE, lo_hz, hi_hz)
    x0 = np.log([spec[b][k] for b, k, _, _ in PARAMS])
    lo = np.log([p[2] for p in PARAMS])
    hi = np.log([p[3] for p in PARAMS])
    x0 = np.clip(x0, lo + 1e-9, hi - 1e-9)

    def resid(x):
        sp = with_params(spec, x)
        return np.concatenate([shape_error(sp, f, level), guards(sp, f, level), PRIOR * (x - x0)])

    e0 = shape_error(spec, f, level)
    best = None
    # A few starts: the double peak has more than one basin.
    starts = [x0] + [
        x0 + np.random.default_rng([7, i]).uniform(-0.7, 0.7, len(x0)) for i in range(7)
    ]
    for s in starts:
        r = least_squares(resid, np.clip(s, lo + 1e-9, hi - 1e-9), bounds=(lo, hi), x_scale=1.0)
        if best is None or r.cost < best.cost:
            best = r
    fitted = with_params(spec, best.x)
    e1 = shape_error(fitted, f, level)
    rms0, rms1 = np.sqrt(np.mean(e0**2)), np.sqrt(np.mean(e1**2))
    print(f"shape rms {rms0:.2f} dB -> {rms1:.2f} dB (max {np.abs(e1).max():.1f})")
    g0, g1 = guards(spec, f, level), guards(fitted, f, level)
    print(f"guards (dB over): before max {g0.max():.1f}, after max {g1.max():.1f}")
    for (b, k, _, _), a, c in zip(PARAMS, np.exp(x0), np.exp(best.x), strict=True):
        print(f"  {b}.{k}: {a:.4g} -> {c:.4g}")
    for fi, li, a, c in zip(f, level, e0, e1, strict=True):
        print(f"  {fi:6.0f} Hz  {CURVE} {li:5.1f}  before {a:+5.1f}  after {c:+5.1f}")
    if args.show:
        import matplotlib.pyplot as plt

        ff = np.geomspace(150, 5000, 300)
        off = np.mean(level - model_db(fitted, f))
        off0 = np.mean(level - model_db(spec, f))
        plt.semilogx(f, level, "ko", label=f"M&H Fig. 20 {CURVE}")
        plt.semilogx(ff, model_db(spec, ff) + off0, label="before")
        plt.semilogx(ff, model_db(fitted, ff) + off, label="fitted")
        plt.legend()
        plt.grid(True, which="both", alpha=0.3)
        plt.show()
    if args.write:
        fitted["_start"] = spec
        write(args.machine, fitted, rms1)


if __name__ == "__main__":
    main()

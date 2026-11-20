"""Fits one axis of the Westrex 3D cutter to Nelson and Stafford's (JAES 1964) Fig. 6, the
response without feedback (data/datasheets/westrex_3d_response.csv, curve open_loop), then sets
the loop gain for their 28 dB of feedback and the amplifier's poles to Fig. 7 (closed_loop).
Fixed from the papers: the coil form's mass (NS64: "a mass of 0.4 g") and the drive coil's
resistance (NS64: twice the 3C's impedance; the 3A's coil is 5.6 ohm, DF58). The rest is fitted
(their sources say so). Writes the values into config/phono/westrex_3d.yaml with --write.

    uv run python scripts/fit_westrex_3d.py [--write] [--show]
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from varimu.phono import cylinder as cy
from varimu.phono import lathe as la

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "datasheets" / "westrex_3d_response.csv"
CONFIG = ROOT / "config" / "phono" / "westrex_3d.yaml"
OPEN = ["suspension_n_m", "bl_t_m", "drive_coil_h", "torque_tube_n_m", "torque_tube_ns_m",
        "tip_mass_kg", "lacquer_resistance_ns_m"]  # fmt: skip
SOURCE = "fitted: NS64 Fig. {fig} by scripts/fit_westrex_3d.py ({note})"


def curve(name: str):
    with CSV.open() as fh:
        rows = [r for r in csv.DictReader(fh) if r["curve"] == name]
    return np.array([float(r["f_hz"]) for r in rows]), np.array(
        [float(r["level_db"]) for r in rows]
    )


def with_open(cut: dict, x) -> dict:
    c = dict(cut)
    for k, v in zip(OPEN, np.exp(x), strict=True):
        c[k] = float(v)
    return c


def open_db(cut: dict, f) -> np.ndarray:
    vt, _ = la.open_loop(la.Axis.from_spec(cut), f)
    return 20 * np.log10(np.abs(vt))


def closed_db(cut: dict, f, fb_db: float) -> np.ndarray:
    ax = la.Axis.from_spec(cut)
    fl, fh = cut["low_pole_hz"], cut["high_pole_hz"]
    g = la.gain_for_feedback(ax, fb_db, fl, fh)
    h, _ = la.closed_loop(ax, f, g, fl, fh)
    return 20 * np.log10(np.abs(h))


def shape(model: np.ndarray, level: np.ndarray, weights: np.ndarray) -> np.ndarray:
    e = model - level
    return (e - np.average(e, weights=weights)) * weights


def fit_open(cut: dict, f, level):
    w = np.where(f <= 12000, 1.0, 0.5)
    x0 = np.log([cut[k] for k in OPEN])

    def res(x):
        return np.concatenate([shape(open_db(with_open(cut, x), f), level, w), 0.02 * (x - x0)])

    best = least_squares(res, x0, method="lm", max_nfev=4000)
    return with_open(cut, best.x), best


def rms(model, level):
    e = model - level
    return float(np.sqrt(np.mean((e - e.mean()) ** 2)))


def write(values: dict, figs: dict) -> None:
    text = CONFIG.read_text(encoding="utf-8")
    for key, val in values.items():
        fig, note = figs[key]
        pat = re.compile(rf"^(  {key}): \{{value: [^,]+, source: \"(.*)\"\}}$", re.M)
        m = pat.search(text)
        if m is None:
            raise KeyError(key)
        old = m.group(2)
        old = old.split("; was ")[-1] if old.startswith("fitted:") else old
        src = SOURCE.format(fig=fig, note=note) + f"; was {old}"
        text = (
            text[: m.start()] + f'  {key}: {{value: {val:.6g}, source: "{src}"}}' + text[m.end() :]
        )
    CONFIG.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    spec = cy.load("westrex_3d")
    cut, fb_db = spec["cutter"], spec["cutter"]["feedback_db"]
    fo, lo = curve("open_loop")
    fc, lc = curve("closed_loop")
    r0 = rms(open_db(cut, fo), lo)
    cut1, best = fit_open(cut, fo, lo)
    r1 = rms(open_db(cut1, fo), lo)
    print(f"open loop: rms {r0:.2f} -> {r1:.2f} dB ({best.nfev} evaluations)")
    for k in OPEN:
        print(f"  {k:26s} {cut[k]:.4g} -> {cut1[k]:.4g}")
    # The closed loop is a check, not a fit: the amplifier's two poles don't shape it (a fit
    # runs them to any bound given), and the card trims what remains (lathe.fit_card).
    cut2 = cut1
    c1 = rms(closed_db(cut2, fc, fb_db), lc)
    print(f"closed loop ({fb_db:.0f} dB of feedback, a check): {c1:.2f} dB rms from Fig. 7")
    ax = la.Axis.from_spec(cut2)
    f0 = la.resonance_hz(ax, np.geomspace(100, 5000, 4000))
    print(f"resonance {f0:.0f} Hz")
    if args.show:
        import matplotlib.pyplot as plt

        f = np.geomspace(20, 20000, 400)
        fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4))
        m = open_db(cut2, f)
        a.semilogx(f, m - m.max(), label="model")
        a.semilogx(fo, lo, "o", label="NS64 Fig. 6")
        mc = closed_db(cut2, f, fb_db)
        off = np.mean(lc - closed_db(cut2, fc, fb_db))
        b.semilogx(f, mc + off, label="model")
        b.semilogx(fc, lc, "o", label="NS64 Fig. 7")
        for x in (a, b):
            x.grid(True, which="both", alpha=0.3)
            x.legend()
        out = ROOT / "reports" / "phono" / "record_player" / "westrex_3d_fit.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=110, bbox_inches="tight")
        print("->", out)
    if args.write:
        figs = {k: ("6", f"open loop {r1:.2f} dB rms") for k in OPEN}
        write({k: cut2[k] for k in OPEN}, figs)
        print("wrote", CONFIG)


if __name__ == "__main__":
    main()

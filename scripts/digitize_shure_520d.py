"""Digitize Figure 1 of Shure's Model 520D data sheet (1980), the typical frequency response
(docs/CHAINS_PLAN.md WP30).

    uv run python scripts/digitize_shure_520d.py [--overlay PNG]

The scan (data/schematics/shure_green_bullet/shure_520d_data_sheet_1980_p1.png, 1237 x 1600 px):
the chart's frame runs x 143-541 px (20 Hz-20 kHz), y 594.5-771.5 px (+20 / -20 dB, 5 dB rules
every 22.1 px, 0 dB at y 683); the decade rules 100 / 1000 / 10000 Hz sit at x 236 / 368 / 501,
so x = 236 + 132.5 log10(f / 100). The curve is the thick trace: per pixel column the dark pixels
off the horizontal rules, their mean row; columns on a vertical rule are skipped (interpolated). On
the steep fall past 5.5 kHz a column holds a near-vertical run, so there the trace is read per row
(the run's column for each level). Resampled to twelfth octaves. Writes
data/datasheets/shure_520d_response.csv (freq_hz, db: as plotted, 0 dB the chart's)."""

from __future__ import annotations

import argparse
import csv

import numpy as np
from PIL import Image

from varimu.config import DATA_DIR

SCAN = DATA_DIR / "schematics" / "shure_green_bullet" / "shure_520d_data_sheet_1980_p1.png"
OUT = DATA_DIR / "datasheets" / "shure_520d_response.csv"
X_100, PX_PER_DECADE = 236.0, 132.5
Y_TOP, Y_BOTTOM = 594.5, 771.5  # +20, -20 dB
H_RULES = [594, 595, 617, 639, 661, 683, 705, 727, 749, 771, 772]
V_RULES = [196, 236, 276, 299, 316, 329, 339, 348, 355, 362, 368, 408, 431, 448, 461, 471, 480,
           488, 495, 501]  # fmt: skip
X_STEEP = 466  # from here on the trace falls nearly vertically
X_END = 486  # the trace ends at ~7.1 kHz (x 483); rules past it


def x_to_f(x):
    return 100.0 * 10 ** ((np.asarray(x, float) - X_100) / PX_PER_DECADE)


def y_to_db(y):
    return 20.0 - 40.0 * (np.asarray(y, float) - Y_TOP) / (Y_BOTTOM - Y_TOP)


def trace(dark):
    off_rule = np.ones(dark.shape[0], bool)
    for r in H_RULES:
        off_rule[r - 1 : r + 2] = False
    xs, ys = [], []
    for x in range(200, X_STEEP):
        if any(abs(x - v) <= 1 for v in V_RULES):
            continue
        rows = np.flatnonzero(dark[600:768, x] & off_rule[600:768]) + 600
        if rows.size == 0:
            continue
        # the trace's own run: the largest cluster of adjacent rows
        runs = np.split(rows, np.flatnonzero(np.diff(rows) > 2) + 1)
        run = max(runs, key=len)
        xs.append(x)
        ys.append(run.mean())
    # the steep fall: per row, the dark columns right of X_STEEP
    for y in range(600, 768):
        if not off_rule[y]:
            continue
        cols = np.flatnonzero(dark[y, X_STEEP:X_END]) + X_STEEP
        cols = np.array([c for c in cols if all(abs(c - v) > 1 for v in V_RULES)])
        if cols.size == 0:
            continue
        runs = np.split(cols, np.flatnonzero(np.diff(cols) > 2) + 1)
        run = max(runs, key=len)
        xs.append(run.mean())
        ys.append(y)
    order = np.argsort(xs)
    return np.asarray(xs)[order], np.asarray(ys)[order]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--overlay", help="write the scan's chart with the trace drawn on it")
    args = ap.parse_args()
    gray = np.asarray(Image.open(SCAN).convert("L"), float)
    xs, ys = trace(gray < 128)
    f = x_to_f(xs)
    db = y_to_db(ys)
    # the steep part's per-row samples are not monotone in x: keep the trace monotone in f
    keep = np.r_[True, np.diff(f) > 0]
    f, db = f[keep], db[keep]
    grid = 2.0 ** (np.arange(np.ceil(12 * np.log2(f[0])), np.floor(12 * np.log2(f[-1])) + 1) / 12)
    out = np.interp(np.log(grid), np.log(f), db)
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz", "db"])
        for fi, di in zip(grid, out, strict=True):
            w.writerow([f"{fi:.1f}", f"{di:.2f}"])
    print(f"{len(grid)} points, {grid[0]:.0f}-{grid[-1]:.0f} Hz -> {OUT}")
    if args.overlay:
        img = Image.open(SCAN).convert("RGB").crop((130, 580, 560, 800))
        a = np.asarray(img).copy()
        for fi, di in zip(grid, out, strict=True):
            x = int(round(X_100 + PX_PER_DECADE * np.log10(fi / 100))) - 130
            y = int(round(Y_TOP + (20 - di) / 40 * (Y_BOTTOM - Y_TOP))) - 580
            a[max(y - 1, 0) : y + 2, max(x - 1, 0) : x + 2] = (255, 0, 0)
        Image.fromarray(a).resize((a.shape[1] * 3, a.shape[0] * 3)).save(args.overlay)


if __name__ == "__main__":
    main()

"""Digitize Shure's SM7B product specification (2009) from the PDF's vector paths
(docs/CHAINS_PLAN.md WP15).

    uv run --with pymupdf python scripts/digitize_shure_sm7.py

The frequency response chart (page 1, frame x 358.8-532.5 pt, y 522.2-611.0 pt: +20 to -20 dB,
5 dB rules every 11.12 pt; frequency on the rules 50 / 100 / 1000 / 10000 Hz at x 382.28 / 400.95
/ 457.38 / 515.04 and the frame's 20 / 20000 Hz, interpolated in log f between them): drawing 74
the flat setting (solid), 75 the bass roll-off (dashed, below ~400 Hz), 76 the presence boost
(dotted, above ~700 Hz). The polar chart's key points are read in scripts/fit_sm7.py. Writes
data/datasheets/shure_sm7_response.csv (setting, freq_hz, db: as plotted, 0 dB the chart's)."""

from __future__ import annotations

import csv

import numpy as np
import pymupdf

from varimu.config import DATA_DIR

PDF = DATA_DIR / "schematics" / "shure_sm7" / "us_pro_SM7B_specsheet.pdf"
OUT = DATA_DIR / "datasheets" / "shure_sm7_response.csv"
KNOT_X = [358.81, 382.28, 400.95, 457.38, 515.04, 532.46]
KNOT_LOGF = list(np.log10([20.0, 50.0, 100.0, 1000.0, 10000.0, 20000.0]))
Y_TOP, Y_BOTTOM = 522.19, 611.02  # +20, -20 dB
TRACES = {74: "flat", 75: "rolloff", 76: "presence"}


def _points(items, n=16):
    pts = []
    for it in items:
        if it[0] == "l":
            pts += [(it[1].x, it[1].y), (it[2].x, it[2].y)]
        elif it[0] == "c":
            p0, p1, p2, p3 = (np.array([q.x, q.y]) for q in it[1:5])
            for t in np.linspace(0, 1, n):
                b = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
                pts.append(tuple(b + 3 * (1 - t) * t**2 * p2 + t**3 * p3))
    return np.array(pts)


def main() -> None:
    dr = pymupdf.open(PDF)[0].get_drawings()
    grid = 10 ** np.arange(np.log10(50), np.log10(20000) + 1e-9, np.log10(2) / 6)
    rows = []
    for i, name in TRACES.items():
        p = _points(dr[i]["items"])
        f = 10 ** np.interp(p[:, 0], KNOT_X, KNOT_LOGF)
        db = 20.0 - (p[:, 1] - Y_TOP) / (Y_BOTTOM - Y_TOP) * 40.0
        o = np.argsort(f)
        f, db = f[o], db[o]
        for g in grid:
            if f[0] <= g <= f[-1]:
                rows.append((name, round(float(g), 1), round(float(np.interp(g, f, db)), 2)))
        print(name, f"{f[0]:.0f}-{f[-1]:.0f} Hz", len(p))
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["setting", "freq_hz", "db"])
        w.writerows(rows)
    print("wrote", OUT, len(rows))


if __name__ == "__main__":
    main()

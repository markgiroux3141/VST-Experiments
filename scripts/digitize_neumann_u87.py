"""Digitize the U 87 i's frequency responses (Neumann's operating instructions, copi0042.pdf, p. 10:
omni, cardioid, figure-8 on axis) by tracing the bold curve (docs/CHAINS_PLAN.md WP22).

    uv run --with pymupdf python scripts/digitize_neumann_u87.py

The page is a 300 dpi render of the PDF's scan. Calibration (found on the render: the box's
edges and grid lines): x, the 100 / 1000 / 10000 Hz lines at 445 / 905 / 1363 px (20 Hz the left
edge at 124); y, 2 dB grid lines 8.51 px apart, each plot's 0 dB line at its long row (533.5,
1285.5, 2038.5 px). The bold curve survives a 5 x 5 erosion (the grid and the +-2 dB tolerance
lines are 1-2 px), then each column's run nearest the last point is taken. Each curve is given
re its own value at 1 kHz (the drawing's calibration mark). Writes
data/datasheets/neumann_u87_response.csv (pattern, freq_hz, db_re_1k) and its provenance.
"""

from __future__ import annotations

import argparse
import csv

import numpy as np

from varimu.config import DATA_DIR

PDF = DATA_DIR / "schematics" / "neumann_u87" / "copi0042.pdf"
OUT = DATA_DIR / "datasheets" / "neumann_u87_response.csv"
X100, PX_DECADE = 445.0, 459.0
PX_DB = 8.514
PLOTS = {
    "omni": (533.5, 400, 700),
    "cardioid": (1285.5, 1150, 1450),
    "figure8": (2038.5, 1900, 2200),
}
FREQS = np.round(np.geomspace(40.0, 20000.0, 55), 1)


def _page() -> np.ndarray:
    import pymupdf

    d = pymupdf.open(PDF)
    pix = d[9].get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    return a < 128


def _erode(b: np.ndarray, k: int) -> np.ndarray:
    out = b.copy()
    for dy in range(-(k // 2), k // 2 + 1):
        for dx in range(-(k // 2), k // 2 + 1):
            out &= np.roll(np.roll(b, dy, 0), dx, 1)
    return out


def trace(b: np.ndarray, zero: float, lo: int, hi: int) -> dict[float, float]:
    e = _erode(b[lo:hi], 5)
    x_start = int(X100 + PX_DECADE * np.log10(40.0 / 100.0)) + 3
    x_end = int(X100 + PX_DECADE * np.log10(20000.0 / 100.0)) - 3
    pts: dict[int, float] = {}
    last = zero - lo
    for x in range(x_start, x_end):
        col = np.where(e[:, x])[0]
        if len(col) == 0:
            continue
        runs = np.split(col, np.where(np.diff(col) > 1)[0] + 1)
        centres = [r.mean() for r in runs]
        c = min(centres, key=lambda y: abs(y - last))
        if abs(c - last) > 40 and pts:
            continue
        pts[x] = c
        last = c
    xs = np.array(sorted(pts))
    ys = np.array([pts[x] for x in xs]) + lo
    f = 100.0 * 10 ** ((xs - X100) / PX_DECADE)
    db = (zero - ys) / PX_DB
    return dict(zip(f.tolist(), db.tolist(), strict=True))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args()
    b = _page()
    rows = []
    for name, (zero, lo, hi) in PLOTS.items():
        t = trace(b, zero, lo, hi)
        f, db = np.array(list(t)), np.array(list(t.values()))
        o = np.argsort(f)
        f, db = f[o], db[o]
        g = np.interp(np.log10(FREQS), np.log10(f), db, left=np.nan, right=np.nan)
        ref = float(np.interp(np.log10(1000.0), np.log10(f), db))
        for fr, v in zip(FREQS, g, strict=True):
            if np.isfinite(v):
                rows.append((name, float(fr), round(float(v) - ref, 2)))
        print(name, "1 kHz at", round(ref, 2), "dB on the drawing;", len(t), "columns")
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pattern", "freq_hz", "db_re_1k"])
        w.writerows(rows)
    print("wrote", OUT, len(rows))


if __name__ == "__main__":
    main()

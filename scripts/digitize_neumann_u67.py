"""Digitize the U 67's frequency responses (Neumann's 1966 specification sheets, coutant.org's
1966mar.pdf, p. 7: omni, cardioid 0 and 180 degrees, figure-8; docs/CHAINS_PLAN.md WP28).

    uv run --with pymupdf python scripts/digitize_neumann_u67.py [--overlay PNG]

The page is the PDF's own 8-bit scan (2384 x 3274), turned upright (90 deg clockwise).
Calibration (found on it: the rules' pixel rows and columns): x, the 100 / 1000 Hz rules at 1016 /
1810 px (794 px a decade; 20 Hz and 20 kHz the frame's edges at 465 / 2845); y, the 5 dB rules
~19.85 px a dB, each chart's 0 dB rule at 499.5 (omni), 892 (cardioid), 1683 (figure-8). The bold
curves (the flat setting, on axis) survive a 5 x 5 erosion (the grid and the dashed curves are
2-3 px); each column's run nearest the previous point is taken. The cardioid's 180 deg curve is
dashed: read on the raw pixels below its 0 deg curve with the rules' rows masked, from 200 Hz
(below that the flat and bass-cut settings' 180 deg curves part) to 18 kHz, gaps between dashes
interpolated. Each on-axis curve is given re its own value at 1 kHz; the 180 deg curve re the
cardioid's on-axis 1 kHz. Writes data/datasheets/neumann_u67_response.csv (pattern, angle_deg,
freq_hz, db_re_1k).
"""

from __future__ import annotations

import argparse
import csv

import numpy as np

from varimu.config import DATA_DIR

PDF = DATA_DIR / "schematics" / "neumann_u67" / "coutant_1966mar.pdf"
OUT = DATA_DIR / "datasheets" / "neumann_u67_response.csv"
X1K, PX_DECADE = 1810.0, 794.0
PX_DB = 19.85
# chart: (0 dB row, top row, bottom row) of the search band
PLOTS = {
    "omni": (499.5, 380, 720),
    "cardioid": (892.0, 775, 1500),
    "figure8": (1683.0, 1565, 1925),
}
RULE_ROWS = [
    399,
    400,
    401,
    497,
    498,
    499,
    500,
    501,
    502,
    503,
    504,
    596,
    597,
    598,
    697,
    698,
    699,
    700,
    701,
    702,
    793,
    794,
    891,
    892,
    893,
    991,
    992,
    1089,
    1090,
    1187,
    1188,
    1189,
    1287,
    1288,
    1289,
    1387,
    1388,
    1389,
    1485,
    1486,
    1487,
    1488,
    1489,
]
FREQS = np.round(np.geomspace(20.0, 20000.0, 61), 1)


def page() -> np.ndarray:
    import pymupdf

    d = pymupdf.open(PDF)
    e = d.extract_image(d[6].get_images()[0][0])
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(e["image"])).convert("L").rotate(-90, expand=True)
    return np.asarray(im) < 128


def x_of(f: np.ndarray | float) -> np.ndarray:
    return X1K + PX_DECADE * np.log10(np.asarray(f, float) / 1000.0)


def f_of(x: np.ndarray) -> np.ndarray:
    return 1000.0 * 10.0 ** ((np.asarray(x, float) - X1K) / PX_DECADE)


def _erode(b: np.ndarray, k: int) -> np.ndarray:
    out = b.copy()
    for dy in range(-(k // 2), k // 2 + 1):
        for dx in range(-(k // 2), k // 2 + 1):
            out &= np.roll(np.roll(b, dy, 0), dx, 1)
    return out


def _runs(col: np.ndarray) -> list[float]:
    idx = np.where(col)[0]
    if idx.size == 0:
        return []
    out, start = [], idx[0]
    for a, b in zip(idx[:-1], idx[1:], strict=False):
        if b != a + 1:
            out.append(0.5 * (start + a))
            start = b
    out.append(0.5 * (start + idx[-1]))
    return out


def trace_bold(b: np.ndarray, zero: float, lo: int, hi: int, f_lo: float, f_hi: float):
    e = _erode(b[lo:hi], 5)
    xs = np.arange(int(x_of(f_lo)) + 4, int(x_of(f_hi)) - 4)
    pts: dict[int, float] = {}
    # start at 1 kHz near the 0 dB rule and walk both ways
    order = [xs[xs >= X1K], xs[xs < X1K][::-1]]
    for seq in order:
        last = zero - lo
        for x in seq:
            runs = _runs(e[:, x])
            if not runs:
                continue
            y = min(runs, key=lambda r, last=last: abs(r - last))
            if abs(y - last) > 25:
                continue
            pts[int(x)] = y + lo
            last = y
    xk = np.array(sorted(pts))
    return xk, np.array([pts[k] for k in xk])


def trace_dashed(b: np.ndarray, below: tuple[np.ndarray, np.ndarray], f_lo, f_hi, start_db):
    """The cardioid's 180 deg curve: thin pixels, below the 0 deg curve, rules masked."""
    m = b.copy()
    for r in RULE_ROWS:
        m[r] = False
    zero = PLOTS["cardioid"][0]
    xs = np.arange(int(x_of(f_lo)), int(x_of(f_hi)))
    pts: dict[int, float] = {}
    last = zero - start_db * PX_DB
    bx, by = below
    for x in xs:
        top = np.interp(x, bx, by) + 25
        col = m[:, x].copy()
        col[: int(top)] = False
        col[1484:] = False
        runs = _runs(col)
        if not runs:
            continue
        y = min(runs, key=lambda r, last=last: abs(r - last))
        if abs(y - last) > (60 if not pts else 12):
            continue
        pts[int(x)] = y
        last = y
    xk = np.array(sorted(pts))
    return xk, np.array([pts[k] for k in xk])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlay", help="write an overlay PNG of the traces")
    args = ap.parse_args()
    b = page()
    rows = []
    traces = {}
    for name, (zero, lo, hi) in PLOTS.items():
        xk, yk = trace_bold(b, zero, lo, hi, 20.0, 20000.0)
        traces[name] = (xk, yk)
        db = -(yk - zero) / PX_DB
        ref = np.interp(x_of(1000.0), xk, db)
        f_ok = FREQS[(x_of(FREQS) >= xk[0]) & (x_of(FREQS) <= xk[-1])]
        for f in f_ok:
            rows.append((name, 0, float(f), round(float(np.interp(x_of(f), xk, db) - ref), 2)))
        if name == "cardioid":
            card_ref = ref
    xk, yk = trace_dashed(b, traces["cardioid"], 200.0, 18000.0, -14.0)
    traces["cardioid180"] = (xk, yk)
    zero = PLOTS["cardioid"][0]
    db = -(yk - zero) / PX_DB
    f_ok = FREQS[(x_of(FREQS) >= xk[0]) & (x_of(FREQS) <= xk[-1])]
    for f in f_ok:
        rows.append(
            ("cardioid", 180, float(f), round(float(np.interp(x_of(f), xk, db) - card_ref), 2))
        )
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pattern", "angle_deg", "freq_hz", "db_re_1k"])
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} rows)")
    for name in ("omni", "cardioid", "figure8"):
        sel = [r for r in rows if r[0] == name and r[1] == 0]
        print(name, [(r[2], r[3]) for r in sel[::6]])
    print("180", [(r[2], r[3]) for r in rows if r[1] == 180][::4])
    if args.overlay:
        from PIL import Image

        rgb = np.stack([~b * 255] * 3, -1).astype(np.uint8)
        for xk, yk in traces.values():
            for x, y in zip(xk, yk, strict=False):
                rgb[int(round(y)) - 1 : int(round(y)) + 2, x] = (255, 0, 0)
        Image.fromarray(rgb[350:1950, 400:2900]).resize((1250, 800)).save(args.overlay)


if __name__ == "__main__":
    main()

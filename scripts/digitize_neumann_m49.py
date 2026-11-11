"""Digitize the M 49 c's frequency responses and the cardioid's off-axis levels (Neumann's
product description "M 49 - M 50 - 910-02-01", recordinghacks.com's M49-M50.pdf; p. 7 the
frequency responses, p. 8 the polar diagrams; docs/CHAINS_PLAN.md WP29).

    uv run --with pymupdf python scripts/digitize_neumann_m49.py [--overlay DIR]

Frequency responses. Page 7 is a 1-bit scan (2416 x 3464) printed sideways, turned upright
(90 deg clockwise): four charts, the M 49's omni, cardioid, figure-8 (top to bottom; the
pattern symbols drawn in each) and the M 50's (not read). Calibration (found on the image: the
rules' pixel columns and rows, per chart, since the scan is skewed ~0.1 deg):
  x: log frequency fitted to each chart's rules at 20 (the frame), 50, 100, 200, 500, 1k, 2k,
  5k, 10k and 20 kHz (the frame), ~877 px a decade, residuals <= 5 px (the 200 Hz rule sits
  ~1.3% low in frequency). The rule labelled "15" sits at 15.8 kHz on that fit; it is not used.
  y: the five 5 dB rules (+10 ... -10) of each chart traced column by column (thin runs only)
  and fitted as straight lines (each falls 3-6 px across the chart: the skew); a point's dB is
  interpolated between the rules at its column (their spacing alternates 104-112 px, ~21.7 px
  a dB, so the interpolation is piecewise).
The bold curves survive a 5 x 5 erosion (the rules are 2-3 px); each column's run nearest the
previous point is taken, walking from 1 kHz outwards. Each on-axis curve is given re its own
value at 1 kHz.

Polars. Page 8 (same format, not turned) has the M 49's omni (top right), figure-8 (top left)
and cardioid (bottom right) and the M 50's (bottom left): 100 Hz thin solid, 1 kHz bold, 5 kHz
dash-dot, 10 kHz dashed, 15 kHz dash-dot-dot. Rings 0 (the frame), 5, 10, 15, 20 dB down,
linear in dB (radii 396.5, 317.5, 238.3, 160.0, 81.7 px about the cardioid chart's centre
(1828.6, 2632) by circle fits, 15.9 px a dB; every curve meets the 0 dB ring at 0 deg). The
cardioid's crossings with its 180 deg ray (the image's -x), 90 deg (+y) and 270 deg (-y) rays
were READ BY EYE on zoomed crops of the page (x 1500-1860, y 2430-2830 at 2x and x 1640-1800,
y 2540-2725 at 4.5x for 180 deg; x 1660-2060, y 2630-3040 at 2x and x 1748-1908, y 2770-2970 at
4x for 90 deg) to identify each curve by its line style, and the radius of each measured on the
pixels (the stroke's centre on rows / columns just off the drawn axis, or a line fitted to the
stroke across it); they are POLAR_CARDIOID below, with the rings' radii measured along the same
ray. 90 deg is the mean of the 90 and 270 deg rays. 15 kHz at 90 / 270 deg and the figure-8 at
90 deg run inside the 20 dB ring (the chart's centre) and are not given. At 180 deg the 100 Hz
curve and the 15 kHz curve's rear lobe touch (r 109.5 / 107.5 px, +-1.5 px).
An off-axis level is converted to re the pattern's on-axis 1 kHz: on-axis(f) re 1 kHz + polar(f).
Writes data/datasheets/neumann_m49_response.csv (pattern, angle_deg, freq_hz, db_re_1k).
"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

import numpy as np

from varimu.config import DATA_DIR

PDF = DATA_DIR / "schematics" / "neumann_m49" / "M49-M50.pdf"
OUT = DATA_DIR / "datasheets" / "neumann_m49_response.csv"
FREQS = np.round(np.geomspace(20.0, 20000.0, 61), 1)
RULE_FREQS = np.array([20.0, 50.0, 100.0, 200.0, 500.0, 1e3, 2e3, 5e3, 10e3, 20e3])
RULE_DB = np.array([10.0, 5.0, 0.0, -5.0, -10.0])
# chart: rule columns at RULE_FREQS (px, the upright page), rule rows +10 ... -10 near x 740
PLOTS = {
    "omni": (
        [439.0, 785.0, 1049.0, 1307.5, 1661.0, 1924.0, 2185.0, 2534.0, 2801.0, 3065.0],
        [93.0, 205.0, 311.0, 422.5, 528.0],
    ),
    "cardioid": (
        [438.0, 782.5, 1048.0, 1306.0, 1660.0, 1923.0, 2185.5, 2535.5, 2802.0, 3064.5],
        [594.0, 705.0, 811.5, 919.0, 1025.0],
    ),
    "figure8": (
        [432.0, 779.0, 1043.0, 1304.0, 1657.5, 1921.0, 2183.0, 2533.0, 2800.0, 3062.0],
        [1095.0, 1202.0, 1312.0, 1419.0, 1529.0],
    ),
}
# the cardioid polar (page 8 as extracted): centre, and per ray (angle_deg) the rings' radii
# at 20, 15, 10, 5, 0 dB down along it and each curve's radius there (px; read by eye on zoomed
# crops, the docstring); 90 and 270 are averaged into angle 90
POLAR_CENTRE = (1828.6, 2632.0)
POLAR_CARDIOID = {
    180: (
        (82.0, 160.0, 239.0, 319.0, 400.0),
        {100: 109.5, 1000: 133.5, 5000: 278.6, 10000: 200.4, 15000: 107.5},
    ),
    90: ((81.5, 159.5, 237.0, 316.0, 396.0), {100: 293.4, 1000: 267.0, 5000: 224.8, 10000: 122.5}),
    270: ((80.5, 159.5, 238.0, 318.0, 398.0), {100: 294.5, 1000: 268.6, 5000: 228.4, 10000: 126.2}),
}


def _image(index: int):
    import pymupdf
    from PIL import Image

    d = pymupdf.open(PDF)
    e = d.extract_image(d[index].get_images()[0][0])
    return Image.open(io.BytesIO(e["image"])).convert("L")


def page_response() -> np.ndarray:
    return np.asarray(_image(6).rotate(-90, expand=True)) < 128


def _erode(b: np.ndarray, k: int) -> np.ndarray:
    out = b.copy()
    for dy in range(-(k // 2), k // 2 + 1):
        for dx in range(-(k // 2), k // 2 + 1):
            out &= np.roll(np.roll(b, dy, 0), dx, 1)
    return out


def _runs(col: np.ndarray) -> list[tuple[float, int]]:
    """(centre, length) of each run of dark pixels."""
    idx = np.where(col)[0]
    if idx.size == 0:
        return []
    out, start = [], idx[0]
    for a, b in zip(idx[:-1], idx[1:], strict=False):
        if b != a + 1:
            out.append((0.5 * (start + a), int(a - start + 1)))
            start = b
    out.append((0.5 * (start + idx[-1]), int(idx[-1] - start + 1)))
    return out


class Chart:
    """One response chart's calibration: x <-> frequency, (x, y) -> dB."""

    def __init__(self, b: np.ndarray, cols: list[float], rows: list[float]):
        A = np.c_[np.ones(len(RULE_FREQS)), np.log10(RULE_FREQS / 1000.0)]
        self.fit, *_ = np.linalg.lstsq(A, np.asarray(cols), rcond=None)
        self.col_residual = np.asarray(cols) - A @ self.fit
        self.x0, self.x1 = cols[0], cols[-1]
        self.rules = [self._rule(b, r) for r in rows]

    def _rule(self, b: np.ndarray, row0: float) -> tuple[float, float]:
        """A rule as row = a + s * x, from its thin runs column by column."""
        xs, ys = [], []
        for x in range(int(self.x0) + 6, int(self.x1) - 6):
            lo = int(row0) - 10
            for c, n in _runs(b[lo : int(row0) + 11, x]):
                if n <= 4:
                    xs.append(x)
                    ys.append(c + lo)
        xs, ys = np.array(xs, float), np.array(ys, float)
        keep = np.ones(len(xs), bool)
        for _ in range(4):
            s, a = np.polyfit(xs[keep], ys[keep], 1)
            keep = np.abs(ys - (a + s * xs)) < 1.5
        return float(a), float(s)

    def x_of(self, f):
        return self.fit[0] + self.fit[1] * np.log10(np.asarray(f, float) / 1000.0)

    def rows_at(self, x: float) -> np.ndarray:
        return np.array([a + s * x for a, s in self.rules])

    def db(self, x: float, y: float) -> float:
        rows = self.rows_at(x)
        # rows increase downwards, dB decreases; linear beyond the outer rules
        if y < rows[0]:
            return float(RULE_DB[0] + (rows[0] - y) * 5.0 / (rows[1] - rows[0]))
        if y > rows[-1]:
            return float(RULE_DB[-1] - (y - rows[-1]) * 5.0 / (rows[-1] - rows[-2]))
        return float(np.interp(y, rows, RULE_DB))


def trace_bold(b: np.ndarray, chart: Chart) -> tuple[np.ndarray, np.ndarray]:
    rows = chart.rows_at(chart.x_of(1000.0))
    lo, hi = int(rows[0]) - 30, int(rows[-1]) + 30
    e = _erode(b[lo:hi], 5)
    xs = np.arange(int(chart.x0) + 6, int(chart.x1) - 6)
    x1k = chart.x_of(1000.0)
    pts: dict[int, float] = {}
    for seq in (xs[xs >= x1k], xs[xs < x1k][::-1]):
        last = rows[2] - lo
        for x in seq:
            runs = [c for c, _ in _runs(e[:, x])]
            if not runs:
                continue
            y = min(runs, key=lambda r, last=last: abs(r - last))
            if abs(y - last) > 25:
                continue
            pts[int(x)] = y + lo
            last = y
    xk = np.array(sorted(pts))
    return xk, np.array([pts[k] for k in xk])


def polar_db(rings: tuple[float, ...], r: float) -> float:
    """dB down at radius r, interpolated between the rings measured along the ray."""
    return float(np.interp(r, rings, [20.0, 15.0, 10.0, 5.0, 0.0]))


def polar_readings() -> dict[int, dict[int, float]]:
    """{angle_deg: {freq_hz: dB down re that frequency's 0 deg}} for the cardioid."""
    out: dict[int, dict[int, float]] = {}
    for ang, (rings, curves) in POLAR_CARDIOID.items():
        out[ang] = {f: polar_db(rings, r) for f, r in curves.items()}
    both = {f: 0.5 * (out[90][f] + out[270][f]) for f in out[90]}
    return {180: out[180], 90: both}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlay", help="a directory for overlay PNGs of the traces and polar reads")
    args = ap.parse_args()
    b = page_response()
    rows: list[tuple[str, int, float, float]] = []
    traces = {}
    onaxis = {}
    for name, (cols, rule_rows) in PLOTS.items():
        chart = Chart(b, cols, rule_rows)
        xk, yk = trace_bold(b, chart)
        traces[name] = (chart, xk, yk)
        db = np.array([chart.db(x, y) for x, y in zip(xk, yk, strict=True)])
        ref = float(np.interp(chart.x_of(1000.0), xk, db))
        onaxis[name] = lambda f, xk=xk, db=db, ref=ref, c=chart: float(
            np.interp(c.x_of(f), xk, db) - ref
        )
        f_lo, f_hi = (1000.0 * 10 ** ((x - chart.fit[0]) / chart.fit[1]) for x in (xk[0], xk[-1]))
        print(
            f"{name}: traced {f_lo:.1f} Hz - {f_hi:.0f} Hz; rule columns' residuals "
            f"{np.round(chart.col_residual, 1).tolist()} px; rules' slopes "
            f"{[round(s * 2000, 1) for _, s in chart.rules]} px over 2000 px"
        )
        for f in FREQS[(chart.x_of(FREQS) >= xk[0]) & (chart.x_of(FREQS) <= xk[-1])]:
            rows.append((name, 0, float(f), round(onaxis[name](f), 2)))
    polar = polar_readings()
    for ang in (90, 180):
        for f, down in sorted(polar[ang].items()):
            rows.append(("cardioid", ang, float(f), round(onaxis["cardioid"](f) - down, 2)))
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pattern", "angle_deg", "freq_hz", "db_re_1k"])
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} rows)")
    shown = (30, 50, 100, 1e3, 3e3, 5e3, 7e3, 1e4, 1.5e4)
    for name in PLOTS:
        print(name, [(f, round(onaxis[name](f), 2)) for f in shown])
    for ang in (90, 180):
        print(f"cardioid {ang} deg, dB down:", {f: round(v, 2) for f, v in polar[ang].items()})
    if args.overlay:
        _overlays(Path(args.overlay), b, traces)


def _overlays(out: Path, b: np.ndarray, traces) -> None:
    from PIL import Image, ImageDraw

    out.mkdir(parents=True, exist_ok=True)
    rgb = np.stack([~b * 255] * 3, -1).astype(np.uint8)
    for chart, xk, yk in traces.values():
        for x, y in zip(xk, yk, strict=False):
            rgb[int(round(y)) - 1 : int(round(y)) + 2, x] = (255, 0, 0)
        for a, s in chart.rules:
            for x in range(int(chart.x0), int(chart.x1), 6):
                rgb[int(round(a + s * x)), x] = (0, 160, 255)
    Image.fromarray(rgb[40:1580, 400:3100]).save(out / "response_overlay.png")
    im = _image(7).convert("RGB")
    d = ImageDraw.Draw(im)
    cx, cy = POLAR_CENTRE
    colours = {
        100: (0, 160, 0),
        1000: (255, 0, 0),
        5000: (255, 140, 0),
        10000: (0, 90, 255),
        15000: (200, 0, 200),
    }
    for ang, (rings, curves) in POLAR_CARDIOID.items():
        ux, uy = {180: (-1, 0), 90: (0, 1), 270: (0, -1)}[ang]
        for r in rings:
            d.ellipse(
                [cx + ux * r - 3, cy + uy * r - 3, cx + ux * r + 3, cy + uy * r + 3],
                outline=(0, 200, 200),
            )
        for f, r in curves.items():
            x, y = cx + ux * r, cy + uy * r
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=colours[f])
    im.crop((1380, 2180, 2280, 3080)).resize((1350, 1350)).save(out / "polar_overlay.png")


if __name__ == "__main__":
    main()

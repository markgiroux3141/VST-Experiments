"""Digitize the EMT 140 TS brochure's reverberation-time curves into CSV.

Reproduces data/datasheets/emt_140ts_decay.csv from
data/datasheets/sources/emt_140ts_1971.pdf (provenance: emt_140ts.provenance.yaml).
Needs PyMuPDF and numpy:

    uv run --with pymupdf python scripts/digitize_emt140.py [--show DIR]

Page 2's plot ("Reverberation times as a function of frequencies for various distances
between reverberation and damping plates") is a raster scan: white curves on a green
ground with black grid lines. The page is rendered at 6x around the plot; the axes come
from the grid lines (vertical lines matched to their printed ticks, log frequency;
horizontal lines every 2 s), and each curve is the white pixels' run tracked column by
column from a start point, the run nearest the curve's last position. The three curves
are labelled by their decay at 500 Hz ("4,5 s", "2 s", "1 s"); the top one starts at
100 Hz, the other two at 50 Hz (the "1 s" curve dashed below 100 Hz).
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np

REPO = Path(__file__).resolve().parents[1]
PDF = REPO / "data/datasheets/sources/emt_140ts_1971.pdf"
OUT = REPO / "data/datasheets/emt_140ts_decay.csv"
ZOOM = 6
# The plot's region on page 2 (fractions of the page).
CLIP = (0.51, 0.555, 0.895, 0.79)
# Vertical grid lines from the left frame: the printed ticks (Hz). The right frame
# (about 14 kHz) is no tick.
TICKS_HZ = [
    40,
    50,
    60,
    80,
    100,
    200,
    300,
    400,
    500,
    600,
    800,
    1000,
    2000,
    3000,
    4000,
    5000,
    6000,
    8000,
    10000,
]
# Horizontal lines from the bottom frame: 0, 2, ..., 14 s.
TICKS_S = [0, 2, 4, 6, 8, 10, 12, 14]
# Each curve: its label (s at 500 Hz) and a start (Hz, s) read off the plot, near which
# the tracking begins.
CURVES = [(4.5, 100.0, 10.2), (2.0, 50.0, 2.2), (1.0, 100.0, 0.75)]
STEP_PX = 6  # one point every this many columns


def render() -> np.ndarray:
    doc = fitz.open(PDF)
    page = doc[1]
    r = page.rect
    clip = fitz.Rect(r.width * CLIP[0], r.height * CLIP[1], r.width * CLIP[2], r.height * CLIP[3])
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=clip)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return a[:, :, :3].astype(int)


def lines(dark: np.ndarray, axis: int, frac: float) -> list[float]:
    """Centres of runs of rows/columns that are dark over `frac` of their length."""
    share = dark.mean(axis=axis)
    idx = np.flatnonzero(share > frac)
    out, run = [], [idx[0]]
    for i in idx[1:]:
        if i == run[-1] + 1:
            run.append(i)
        else:
            out.append(float(np.mean(run)))
            run = [i]
    out.append(float(np.mean(run)))
    return out


def fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    b, a = np.polyfit(xs, ys, 1)
    res = max(abs(a + b * x - y) for x, y in zip(xs, ys, strict=True))
    return a, b, res


def runs(col: np.ndarray) -> list[float]:
    """Centres of white runs 3-40 px long in a column."""
    idx = np.flatnonzero(col)
    if idx.size == 0:
        return []
    out, run = [], [idx[0]]
    for i in idx[1:]:
        if i == run[-1] + 1:
            run.append(i)
        else:
            if 3 <= len(run) <= 40:
                out.append(float(np.mean(run)))
            run = [i]
    if 3 <= len(run) <= 40:
        out.append(float(np.mean(run)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--show", type=Path, help="write the render with the tracked points here")
    args = ap.parse_args()
    img = render()
    dark = img.sum(axis=2) < 200
    white = (img > 215).all(axis=2)
    vx = lines(dark, axis=0, frac=0.35)
    # The plot's own lines, top frame to bottom frame (the green panel's edge is below).
    hy = sorted(lines(dark, axis=1, frac=0.35))[: len(TICKS_S)]
    if len(vx) != len(TICKS_HZ) + 1 or len(hy) != len(TICKS_S):
        raise SystemExit(f"grid: {len(vx)} vertical lines {vx}, {len(hy)} horizontal {hy}")
    ax, bx, rx = fit(vx[: len(TICKS_HZ)], [math.log10(f) for f in TICKS_HZ])
    ay, by, ry = fit(sorted(hy, reverse=True), TICKS_S)
    print(f"x: log10 f = {ax:.5f} + {bx:.6f} x (max residual {rx:.4f} decades)")
    print(f"y: T = {ay:.4f} + {by:.6f} y (max residual {ry:.4f} s)")
    x_of = lambda f: (math.log10(f) - ax) / bx  # noqa: E731
    y_of = lambda t: (t - ay) / by  # noqa: E731
    left, right = int(vx[0]) + 3, int(vx[-1]) - 3
    rows = []
    marks = []
    for label, f0, t0 in CURVES:
        x0 = int(round(x_of(f0)))
        y = y_of(t0)
        pts = {}
        for x in range(max(x0, left), right, 1):
            cand = runs(white[:, x])
            if cand:
                near = min(cand, key=lambda c: abs(c - y))
                if abs(near - y) < 12:
                    y = near
                    pts[x] = y
        for x in sorted(pts):
            if (x - x0) % STEP_PX == 0:
                f = 10 ** (ax + bx * x)
                t = ay + by * pts[x]
                rows.append((label, f, t))
                marks.append((x, pts[x]))
    OUT.write_text(
        "curve_t500_s,f_hz,t60_s\n" + "".join(f"{c},{f:.1f},{t:.3f}\n" for c, f, t in rows),
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(REPO)}: {len(rows)} points")
    for label in sorted({r[0] for r in rows}, reverse=True):
        pts = [(f, t) for c, f, t in rows if c == label]
        at = lambda hz, pts=pts: min(pts, key=lambda p: abs(math.log(p[0] / hz)))  # noqa: E731
        print(
            f"  {label} s curve: {pts[0][0]:.0f}-{pts[-1][0]:.0f} Hz; "
            + ", ".join(f"{hz} Hz {at(hz)[1]:.2f} s" for hz in (100, 500, 1000, 4000, 10000))
        )
    if args.show:
        out = img.copy()
        for x, y in marks:
            out[int(y) - 2 : int(y) + 3, x - 2 : x + 3] = (255, 0, 0)
        args.show.mkdir(parents=True, exist_ok=True)
        pix = fitz.Pixmap(
            fitz.csRGB, out.shape[1], out.shape[0], out.astype(np.uint8).tobytes(), False
        )
        pix.save(args.show / "emt_140ts_tracked.png")


if __name__ == "__main__":
    main()

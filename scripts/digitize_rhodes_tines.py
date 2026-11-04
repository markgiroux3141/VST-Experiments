"""Digitize the Rhodes service manual's tine cutting chart into per-key tine lengths.

Reproduces data/datasheets/rhodes_tine_lengths.csv from
data/datasheets/sources/rhodes_tine_cutting_chart.pdf (provenance:
rhodes_tine_cutting_chart.provenance.yaml). Needs PyMuPDF and numpy:

    uv run --with pymupdf python scripts/digitize_rhodes_tines.py [--show DIR]

Figure 6-2 of the 1979 service manual ("Tine Cutting Measurement Chart", page 6-3) is a
full-size cutting guide: a tone generator laid with its inside flush against the guide's
frame, the tine cut where its bar ends. The scan is one raster image, 150 px per inch
across a letter-width page (1275 px over 8.5 in). Two blocks of bars: the left block's
frame on the left (bars labelled "0-(1-7)", "1-8", ... "46-53": the 73-key numbering, then
the 88-key one), the right block's frame on the right ("47-54" ... "81-88", bars running
leftwards). Each bar's length is its dark run from the frame's outer edge (where the
chart's "measurement area" arrow starts) to its end, the first white gap of at least
`GAP_PX` (the labels sit a few px past the ends).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np

REPO = Path(__file__).resolve().parents[1]
PDF = REPO / "data/datasheets/sources/rhodes_tine_cutting_chart.pdf"
OUT = REPO / "data/datasheets/rhodes_tine_lengths.csv"
PX_PER_IN = 150.0  # the scan's horizontal resolution (1275 px over 8.5 in)
MM_PER_PX = 25.4 / PX_PER_IN
GAP_PX = 3
DARK = 110
LEFT_ROWS = 47  # "0-(1-7)", "1-8", ..., "46-53"
RIGHT_ROWS = 35  # "47-54", ..., "81-88"


def image() -> np.ndarray:
    page = fitz.open(PDF)[0]
    xref = page.get_images()[0][0]
    pix = fitz.Pixmap(fitz.open(PDF), xref)
    if pix.n != 1:
        pix = fitz.Pixmap(fitz.csGRAY, pix)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, stop) of the True runs of a 1-D mask."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1), strict=True))


def frame(dark: np.ndarray, x0: int, x1: int) -> tuple[int, int, int, int]:
    """The vertical frame line within columns [x0, x1): (outer-left x, outer-right x,
    top y, bottom y), the column with the longest dark run."""
    best = (0, 0, 0, 0)
    for x in range(x0, x1):
        for a, b in runs(dark[:, x]):
            if b - a > best[0]:
                best = (b - a, x, a, b)
    _, x, top, bottom = best
    cols = [c for c in range(x0, x1) if dark[top + 20 : bottom - 20, c].mean() > 0.95]
    return min(cols), max(cols), top, bottom


def bars(dark: np.ndarray, side: str, expect: int) -> list[tuple[int, int, int]]:
    """(row y, frame's outer x, bar end x) per bar, top to bottom."""
    h, w = dark.shape
    if side == "left":
        fx0, fx1, top, bottom = frame(dark, 0, w // 4)
        probe = fx1 + 6
    else:
        fx0, fx1, top, bottom = frame(dark, w // 2, w)
        probe = fx0 - 6
    rows = [(a + b) // 2 for a, b in runs(dark[top:bottom, probe]) if b - a >= 3]
    rows = [top + y for y in rows]
    if len(rows) != expect:
        raise SystemExit(f"{side}: found {len(rows)} bars, expected {expect}")
    out = []
    for y in rows:
        line = dark[y - 1 : y + 2].any(axis=0)
        if side == "left":
            x, gap = fx1, 0
            while gap < GAP_PX and x < w - 1:
                x += 1
                gap = 0 if line[x] else gap + 1
            out.append((y, fx0, x - GAP_PX))
        else:
            x, gap = fx0, 0
            while gap < GAP_PX and x > 0:
                x -= 1
                gap = 0 if line[x] else gap + 1
            out.append((y, fx1, x + GAP_PX))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--show", type=Path, help="write an overlay PNG of the found bars here")
    args = ap.parse_args()
    img = image()
    dark = img < DARK
    left = bars(dark, "left", LEFT_ROWS)
    right = bars(dark, "right", RIGHT_ROWS)

    lines = ["key,bar_73,free_length_m"]
    rows = []
    for i, (_, fx, end) in enumerate(left):
        length_m = (end - fx + 1) * MM_PER_PX / 1000
        keys = range(1, 8) if i == 0 else [i + 7]
        rows += [(k, i, length_m) for k in keys]
    for j, (_, fx, end) in enumerate(right):
        bar = 81 - j  # top to bottom: "81-88" ... "47-54"
        rows.append((bar + 7, bar, (fx - end + 1) * MM_PER_PX / 1000))
    rows.sort()
    assert [r[0] for r in rows] == list(range(1, 89))
    lines += [f"{k},{b},{m:.5f}" for k, b, m in rows]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{OUT}: key 1 {rows[0][2] * 1000:.1f} mm ... key 88 {rows[-1][2] * 1000:.1f} mm")

    if args.show:
        args.show.mkdir(parents=True, exist_ok=True)
        rgb = np.stack([img] * 3, axis=-1).copy()
        for y, fx, end in left + right:
            a, b = sorted((fx, end))
            rgb[y - 1 : y + 2, a : b + 1] = (255, 0, 0)
        pix = fitz.Pixmap(fitz.csRGB, img.shape[1], img.shape[0], rgb.tobytes(), False)
        pix.save(args.show / "rhodes_tine_chart_overlay.png")


if __name__ == "__main__":
    main()

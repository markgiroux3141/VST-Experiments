"""Digitize the RCA 884's average control characteristic into CSV (HYBRID_PHYSICS_PLAN.md H1).

Reproduces data/datasheets/rca_884_control.csv from data/datasheets/sources/rca_884_1944.pdf
(provenance: rca_884.provenance.yaml). Needs PyMuPDF:

    uv run --with pymupdf python scripts/digitize_884.py [--overlays DIR]

Page 4 is one scanned image (~300 dpi): "plate volts for starting discharge" against the
grid volts, Ef 6.3 V, one curve from -30 V (300 V) to about -4 V (~28 V). The grid lines
(1 V a division across, 5 V a division up) are found per axis and the axes fitted to them
(grid volts 0 at the grid's right edge, plate volts 0 at its bottom line); the curve is
the thick line left after opening the dark pixels (scripts/digitize_2d21.py's mask and
tracer), seeded where it crosses 150 V.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from digitize_2d21 import axis_map, curve_mask, family, grid_lines, page_image, write  # noqa: E402
from digitize_ge6386 import overlay, runs  # noqa: E402

PDF = REPO / "data/datasheets/sources/rca_884_1944.pdf"
OUT = REPO / "data/datasheets"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--overlays", type=Path, help="write a PPM overlay here for a visual check")
    args = ap.parse_args()
    img = page_image(fitz.open(PDF), 3)
    frame = (140, 300, 925, 1840)
    cols = grid_lines(img, (150, 1700, 925, 1850), "col")  # the window's last line: 0 V
    rows = grid_lines(img, (160, 300, 300, 1840), "row")  # its last line: 0 V
    vg = axis_map(cols[::-1], 0.0, -1.0)
    va = axis_map(rows[::-1], 0.0, 5.0)
    mask = curve_mask(img, frame)
    x0, y0, x1, y1 = frame
    inside = lambda q: y0 + 8 <= q[0] <= y1 - 8 and x0 + 8 <= q[1] <= x1 - 8  # noqa: E731
    row = int(round(rows[::-1][30]))  # 150 V
    cr = runs(mask[row, x0:x1], x0)
    if len(cr) != 1:
        raise SystemExit(f"row {row}: {len(cr)} crossings, expected 1")
    pts = family(mask, [(0.0, row, int(round(cr[0])))], inside)
    ctl = np.stack([pts[:, 0], vg(pts[:, 1]), va(pts[:, 2]), pts[:, 1], pts[:, 2]], 1)
    if args.overlays:
        args.overlays.mkdir(parents=True, exist_ok=True)
        overlay(img, ctl, frame, args.overlays / "control_884.ppm")
    ctl = ctl[np.argsort(ctl[:, 1])]
    write(OUT / "rca_884_control.csv", "vg_v,va_v", ctl[:, 1:3])


if __name__ == "__main__":
    main()

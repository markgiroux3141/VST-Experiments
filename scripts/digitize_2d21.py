"""Digitize the Sylvania 2D21 data sheet's curves into CSV (HYBRID_PHYSICS_PLAN.md H1).

Reproduces data/datasheets/sylvania_2d21_{control,grid_before,grid_during}.csv from
data/datasheets/sources/sylvania_2d21_1954.pdf (provenance: sylvania_2d21.provenance.yaml).
Needs PyMuPDF:

    uv run --with pymupdf python scripts/digitize_2d21.py [--overlays DIR]

Each page is one scanned image (300 dpi). The curves are drawn ~6 px thick, the grid
lines 2-4 px: opening the dark pixels with a 5 x 5 square keeps the curves and drops the
grid and most lettering. Axes come from the grid lines, found per plot (`grid_lines`) and
matched to the printed ticks. Each curve is seeded where it crosses a column (or row) at
which every curve of the family is separate, in the family's order, and traced in both
directions with digitize_ge6386.trace (steps along the curve, snapping to the mask
across it). Where a family's curves run within a few pixels of each other the tracer can
jump between them, so each plot keeps only the stretch the overlays show is clean (the
`keep` limits below). With --overlays, the traced points are drawn over each page.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from scipy import ndimage as ndi
from scipy.sparse.csgraph import connected_components

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from digitize_ge6386 import _snap, overlay, runs  # noqa: E402

PDF = REPO / "data/datasheets/sources/sylvania_2d21_1954.pdf"
OUT = REPO / "data/datasheets"
# Grid volts right of which the during-conduction curves are cut (they meet there).
FLOAT_V = -0.9


def page_image(doc: fitz.Document, page: int) -> np.ndarray:
    """The page's scan at its own resolution (grey, 0-255)."""
    pix = fitz.Pixmap(doc, doc[page].get_images(full=True)[0][0])
    if pix.n > 1:
        pix = fitz.Pixmap(fitz.csGRAY, pix)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)


def curve_mask(img: np.ndarray, frame, size: int = 4, min_area: int = 300) -> np.ndarray:
    dark = img < 140
    x0, y0, x1, y1 = frame
    op = np.zeros_like(dark)
    op[y0:y1, x0:x1] = ndi.binary_opening(dark[y0:y1, x0:x1], structure=np.ones((size, size)))
    lab, n = ndi.label(op, structure=np.ones((3, 3)))
    area = ndi.sum(op, lab, np.arange(1, n + 1))
    return np.isin(lab, 1 + np.where(area >= min_area)[0])


def grid_lines(img: np.ndarray, frame, axis: str) -> np.ndarray:
    """Centres of the grid lines across `frame` ("col": vertical lines, "row": horizontal)."""
    x0, y0, x1, y1 = frame
    win = img[y0:y1, x0:x1] < 140
    prof = win.mean(0) if axis == "col" else win.mean(1)
    return np.array(runs(prof > 0.5, x0 if axis == "col" else y0))


def axis_map(lines: np.ndarray, first: float, pitch: float):
    """Value of a pixel: a straight line through the grid lines, the first at `first`,
    one `pitch` apart (fitted to every line, so one missing or extra line is caught)."""
    k = np.round((lines - lines[0]) / np.median(np.diff(lines)))
    a, b = np.polyfit(k, lines, 1)
    return lambda p: first + (np.asarray(p, float) - b) / a * pitch


def trace(mask, seed, hint, inside, step=4.0, max_miss=20, max_steps=2000):
    """digitize_ge6386.trace with a step limit (a curve ending in a circle would loop)."""
    y, x = int(seed[0]), int(seed[1])
    yy, xx = np.nonzero(mask[y - 30 : y + 31, x - 30 : x + 31])
    k = np.argmin((yy - 30) ** 2 + (xx - 30) ** 2)
    near = (yy - yy[k]) ** 2 + (xx - xx[k]) ** 2 < 400
    pts = np.stack([yy[near], xx[near]], 1).astype(float)
    v = np.linalg.svd(pts - pts.mean(0), full_matrices=False)[2][0]
    d = v if v @ np.asarray(hint) > 0 else -v
    p = _snap(mask, np.array([y - 30 + yy[k], x - 30 + xx[k]], float), d, half=15, max_run=40)
    out, miss = [p.copy()], 0
    for _ in range(max_steps):
        q = p + step * d
        if not inside(q):
            break
        s = _snap(mask, q, d)
        if s is None:
            miss += 1
            if miss > max_miss:
                break
            p = q
            continue
        miss = 0
        nd = (s - p) / np.linalg.norm(s - p)
        d = 0.6 * d + 0.4 * nd
        d /= np.linalg.norm(d)
        p = s
        out.append(s.copy())
    return out


def family(mask, seeds, inside):
    """Trace each (label, row, col) seed both ways; points (label, col, row)."""
    out = []
    for lab, yp, xc in seeds:
        for hint in ((-1, 0.3), (1, -0.3), (0.3, 1), (-0.3, -1)):
            out += [(lab, x, y) for y, x in trace(mask, (yp, xc), hint, inside)]
    a = np.array(out, float)
    _, keep = np.unique(np.round(a / [1, 3, 3]), axis=0, return_index=True)
    a = a[np.sort(keep)]
    return a[np.lexsort((a[:, 1], a[:, 0]))]


def seeds_on_col(mask, col: int, labels, rows=(0, None)):
    cr = runs(mask[rows[0] : rows[1], col], rows[0])
    if len(cr) != len(labels):
        raise SystemExit(f"column {col}: {len(cr)} crossings, expected {len(labels)}")
    return [(lab, int(round(y)), col) for lab, y in zip(labels, cr, strict=True)]


def write(path: Path, header: str, a: np.ndarray) -> None:
    np.savetxt(path, a, delimiter=",", header=header, comments="", fmt="%.6g")
    print(f"wrote {path.relative_to(REPO)}: {len(a)} points")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--overlays", type=Path, help="write PPM overlays here for visual checks")
    args = ap.parse_args()
    if args.overlays:
        args.overlays.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF)

    # Page 2: average control characteristics, printed rotated. Image x is the plate
    # voltage (20 V a division, 0 V at the right frame), image y the control-grid voltage
    # (0.4 V a division, +16 V at the top line). Curves for shield-grid volts
    # -3, -2, -1.5, -1, 0, +2, +8 (top to bottom at 650 V); grid resistor 0.1 Mohm. The
    # bottom curve is printed "+3" here and "+8" on RCA's original of the same plot
    # (rca_2d21_1948.pdf, p. 3): +8 is taken, the only reading under which the family's
    # spacing is regular (~0.35-0.4 V of control grid per shield-grid volt from 0 V up).
    img = page_image(doc, 1)
    frame = (500, 680, 2262, 2995)
    cols = grid_lines(img, (500, 2700, 2275, 2950), "col")
    rows = grid_lines(img, (1950, 680, 2240, 3000), "row")
    va = axis_map(cols[::-1], 0.0, 20.0)  # right frame first: 0 V, then 20 V a line
    vg = axis_map(rows, 16.0, -0.4)
    mask = curve_mask(img, frame)
    seed_mask = curve_mask(img, frame, size=5)
    labels = [-3.0, -2.0, -1.5, -1.0, 0.0, 2.0, 8.0]
    x0, y0, x1, y1 = frame
    inside = lambda q: y0 + 8 <= q[0] <= y1 - 8 and x0 + 8 <= q[1] <= x1 - 8  # noqa: E731
    col600 = int(round(cols[::-1][30]))  # 600 V
    pts = family(mask, seeds_on_col(seed_mask, col600, labels, (700, 2990)), inside)
    ctl = np.stack([pts[:, 0], va(pts[:, 1]), vg(pts[:, 2]), pts[:, 1], pts[:, 2]], 1)
    ctl = ctl[(ctl[:, 1] >= 0.0) & (ctl[:, 1] <= 660.0)]
    if args.overlays:
        overlay(img, ctl, frame, args.overlays / "control.ppm")
    write(OUT / "sylvania_2d21_control.csv", "vg2_v,va_v,vg1_v", ctl[:, :3])

    # Page 3: average grid characteristics during anode conduction (shield grid 0 V).
    # x: control-grid volts, -8 V at the left frame, 0.2 V a division; y: grid current,
    # +2 mA at the top frame, 0.2 mA a division. Curves for anode current 25, 50, 100,
    # 150, 200 mA (top to bottom at -6 V) and 300 mA (only right of ~-1.3 V). Near
    # -0.6 V every curve passes through the same point (the grid floating) and then rises
    # to electron current: kept only left of it (FLOAT_V), where they are apart.
    img = page_image(doc, 2)
    frame = (530, 772, 2034, 2696)
    cols = grid_lines(img, (530, 2300, 2034, 2696), "col")
    rows = grid_lines(img, (560, 772, 900, 2696), "row")
    vg = axis_map(cols, -8.0, 0.2)
    ig = axis_map(rows, 2.0, -0.2)
    mask = curve_mask(img, frame)
    x0, y0, x1, y1 = frame
    inside = lambda q: y0 + 8 <= q[0] <= y1 - 8 and x0 + 8 <= q[1] <= x1 - 8  # noqa: E731
    col = int(round(cols[10]))  # -6 V
    seeds = seeds_on_col(curve_mask(img, frame, size=5), col, [25.0, 50.0, 100.0, 150.0, 200.0])
    row = int(round(rows[int(round((2.0 + 6.5) / 0.2))]))  # -6.5 mA: only the 300 mA curve
    right = runs(mask[row, int(round(cols[30])) : x1], int(round(cols[30])))  # right of -2 V
    seeds.append((300.0, row, int(round(right[0]))))
    pts = family(mask, seeds, inside)
    dur = np.stack([pts[:, 0], vg(pts[:, 1]), ig(pts[:, 2]), pts[:, 1], pts[:, 2]], 1)
    dur = dur[(dur[:, 1] <= FLOAT_V) & (dur[:, 1] >= -7.02)]  # the curves start at -7 V
    if args.overlays:
        overlay(img, dur, frame, args.overlays / "grid_during.ppm")
    write(
        OUT / "sylvania_2d21_grid_during.csv",
        "ia_a,vg1_v,ig1_a",
        np.stack([dur[:, 0] * 1e-3, dur[:, 1], dur[:, 2] * 1e-3], 1),
    )

    # Page 5: average grid characteristics before anode conduction (shield grid 0 V). x:
    # control-grid volts printed unsigned (negative, as RCA's copy of the plot labels
    # them), -16 V at the left frame, 0.4 V a division; y: grid current, +0.04 uA at the
    # top frame, 0.002 uA a division. Curves for anode volts 25, 200, 400, 600 (top to
    # bottom at -12 V), each ending where conduction starts (a circle; the 25 V curve's
    # end is its lowest point, after which the trace rises with the discharge).
    img = page_image(doc, 4)
    frame = (462, 762, 1960, 2680)
    cols = grid_lines(img, (462, 2350, 1960, 2680), "col")
    rows = grid_lines(img, (480, 762, 560, 2680), "row")
    vg = axis_map(cols, -16.0, 0.4)
    ig = axis_map(rows, 0.04, -0.002)
    mask = curve_mask(img, frame)
    x0, y0, x1, y1 = frame
    inside = lambda q: y0 + 8 <= q[0] <= y1 - 8 and x0 + 8 <= q[1] <= x1 - 8  # noqa: E731
    col = int(round(cols[10]))  # -12 V
    seeds = seeds_on_col(curve_mask(img, frame, size=5), col, [25.0, 200.0, 400.0, 600.0])
    # The steep drops (the tracer loses the knees): more seeds where the drops cross a row
    # right of -6 V, left to right: at -0.030 uA the 600, 400 and 25 V curves (then the
    # 25 V trace's rise with the discharge; the 200 V curve ends at -0.027), above the
    # "CONDUCTION STARTS" lettering; at -0.020 uA the 400, 200 and 25 V curves.
    lo = int(round(cols[25]))
    for ua, labs in ((0.030, [600.0, 400.0, 25.0]), (0.020, [400.0, 200.0, 25.0])):
        row = int(round(rows[int(round((0.04 + ua) / 0.002))]))
        cr = runs(mask[row, lo : int(round(cols[-1])) - 4], lo)
        if len(cr) < len(labs):
            raise SystemExit(f"row {row}: {len(cr)} crossings, expected {len(labs)}")
        seeds += [(v, row, int(round(x))) for v, x in zip(labs, cr, strict=False)]
    pts = family(mask, seeds, inside)
    bef = np.stack([pts[:, 0], vg(pts[:, 1]), ig(pts[:, 2]), pts[:, 1], pts[:, 2]], 1)
    kept = []
    for va_v in np.unique(bef[:, 0]):
        c = bef[bef[:, 0] == va_v]
        c = c[np.argsort(c[:, 1])]
        # The curve is its largest run of points chained within 12 px (drops a dash of
        # another line, or a lettering stroke the tracer wandered onto).
        d = np.hypot(c[:, 3][:, None] - c[:, 3][None, :], c[:, 4][:, None] - c[:, 4][None, :])
        _, lab = connected_components(d < 12.0, directed=False)
        c = c[lab == np.bincount(lab).argmax()]
        c = c[: np.argmin(c[:, 2]) + 1]  # up to the conduction start
        if va_v == 600.0:  # the tracer's last steps follow the label's arrow to the circle
            c = c[(c[:, 2] > -0.036) | (c[:, 1] > -4.05)]
        kept.append(c)
    bef = np.concatenate(kept)
    if args.overlays:
        overlay(img, bef, frame, args.overlays / "grid_before.ppm")
    write(
        OUT / "sylvania_2d21_grid_before.csv",
        "va_v,vg1_v,ig1_a",
        np.stack([bef[:, 0], bef[:, 1], bef[:, 2] * 1e-6], 1),
    )


if __name__ == "__main__":
    main()

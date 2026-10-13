"""Digitize the GE 6386 datasheet (ET-T1113, 8-54) curves into CSV.

Reproduces data/datasheets/ge_6386_{plate,transfer,cascode_gm}.csv from
data/datasheets/sources/ge_6386_ET-T1113.pdf. Requires `pdftoppm` (poppler) on PATH.

    uv run python scripts/digitize_ge6386.py [--overlays DIR]

Method: render at 400 dpi, threshold, then morphologically open with a radius-3
diamond. That removes the thin grid lines and lettering but keeps the thick
curves. Axes are calibrated from the detected grid lines, with a quadratic
correction for scan distortion. Each curve is seeded where it crosses a row
between grid lines and traced in both directions. The tracer bridges small
gaps and refuses wide blobs (label text, junctions). With --overlays, the
traced points are drawn over each page so they can be checked by eye.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

REPO = Path(__file__).resolve().parents[1]
PDF = REPO / "data/datasheets/sources/ge_6386_ET-T1113.pdf"
OUT = REPO / "data/datasheets"
DPI = 400


def render_page(pdf: Path, page: int, tmp: Path) -> np.ndarray:
    stem = tmp / f"p{page}"
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            str(DPI),
            "-gray",
            "-f",
            str(page),
            "-l",
            str(page),
            str(pdf),
            str(stem),
        ],
        check=True,
    )
    raw = next(tmp.glob(f"p{page}*.pgm")).read_bytes()
    parts = raw.split(maxsplit=4)
    w, h = int(parts[1]), int(parts[2])
    return np.frombuffer(parts[4][-w * h :], np.uint8).reshape(h, w)


def runs(m: np.ndarray, start: int = 0) -> list[float]:
    idx = np.where(m)[0]
    if len(idx) == 0:
        return []
    return [start + g.mean() for g in np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)]


def grid_cal(dark: np.ndarray, p0: float, p1: float, ndiv: int, axis: int, lo: int) -> np.ndarray:
    """Quadratic map pixel -> grid-division index, fitted to the detected grid lines."""
    lines = np.array(runs(dark.mean(axis) > 0.6, lo))
    pitch = (p1 - p0) / ndiv
    k = np.round((lines - p0) / pitch)
    ok = np.abs(lines - (p0 + k * pitch)) < abs(pitch) * 0.25
    return np.polyfit(lines[ok], k[ok], 2)


def curve_mask(dark: np.ndarray, radius: int = 3, min_area: int = 400) -> np.ndarray:
    st = ndi.iterate_structure(ndi.generate_binary_structure(2, 1), radius)
    op = ndi.binary_opening(dark, structure=st)
    lab, n = ndi.label(op, structure=np.ones((3, 3)))
    area = ndi.sum(op, lab, np.arange(1, n + 1))
    return np.isin(lab, 1 + np.where(area >= min_area)[0])


def _snap(mask, p, d, half=9, max_run=14):
    nrm = np.array([-d[1], d[0]])
    ts = np.arange(-half, half + 1)
    pts = p[None, :] + ts[:, None] * nrm[None, :]
    yi, xi = np.round(pts[:, 0]).astype(int), np.round(pts[:, 1]).astype(int)
    ok = (yi >= 0) & (yi < mask.shape[0]) & (xi >= 0) & (xi < mask.shape[1])
    hit = np.zeros(len(ts), bool)
    hit[ok] = mask[yi[ok], xi[ok]]
    if not hit.any():
        return None
    idx = np.where(hit)[0]
    best = min(np.split(idx, np.where(np.diff(idx) > 1)[0] + 1), key=lambda r: abs(ts[r].mean()))
    return None if len(best) > max_run else p + ts[best].mean() * nrm


def trace(mask, seed, hint, inside, step=5.0, max_miss=8):
    """Follow a curve from `seed` (y, x) in the direction closest to `hint`."""
    y, x = int(seed[0]), int(seed[1])
    yy, xx = np.nonzero(mask[y - 30 : y + 31, x - 30 : x + 31])
    k = np.argmin((yy - 30) ** 2 + (xx - 30) ** 2)
    near = (yy - yy[k]) ** 2 + (xx - xx[k]) ** 2 < 400
    pts = np.stack([yy[near], xx[near]], 1).astype(float)
    v = np.linalg.svd(pts - pts.mean(0), full_matrices=False)[2][0]
    d = v if v @ np.asarray(hint) > 0 else -v
    p = _snap(mask, np.array([y - 30 + yy[k], x - 30 + xx[k]], float), d, half=15, max_run=40)
    out, miss = [p.copy()], 0
    while True:
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


def digitize(img, frame, xval, yval, labels, seed_rows=(), seeds=(), exclude=(), min_y=-np.inf):
    """Trace labelled curves. Seeds come from crossings of `seed_rows` (y-values,
    curves in label order, left to right) and/or explicit (label, x, y) value seeds."""
    dark = img < 140
    x0, y0, x1, y1 = frame
    mask = np.zeros_like(dark)
    mask[y0:y1, x0:x1] = curve_mask(dark[y0:y1, x0:x1])
    for ex in exclude:
        mask[ex[1] : ex[3], ex[0] : ex[2]] = False
    ys, xs = np.arange(y0, y1), np.arange(x0, x1)
    px = lambda v: xs[np.argmin(np.abs(xval(xs) - v))]  # noqa: E731
    py = lambda v: ys[np.argmin(np.abs(yval(ys) - v))]  # noqa: E731
    inside = lambda q: y0 + 10 <= q[0] <= y1 - 10 and x0 + 10 <= q[1] <= x1 - 10  # noqa: E731

    seed_px = []
    for yv in seed_rows:
        yp = py(yv)
        cr = runs(mask[yp, x0 + 14 : x1 - 14], x0 + 14)
        if len(cr) == len(labels):
            seed_px += [(lab, yp, xc) for lab, xc in zip(labels, cr, strict=True)]
        else:
            print(f"  seed row {yv}: {len(cr)} crossings, expected {len(labels)}; skipped")
    seed_px += [(lab, py(yv), px(xv)) for lab, xv, yv in seeds]

    rows = []
    for lab, yp, xc in seed_px:
        for hint in ((-1, 0.3), (1, -0.3)):
            rows += [(lab, x, y) for y, x in trace(mask, (yp, xc), hint, inside)]
    rows = np.array(rows)
    _, keep = np.unique(
        np.stack([rows[:, 0], np.round(rows[:, 1] / 4)], 1), axis=0, return_index=True
    )
    rows = rows[keep]
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    vals = np.stack([rows[:, 0], xval(rows[:, 1]), yval(rows[:, 2]), rows[:, 1], rows[:, 2]], 1)
    return vals[vals[:, 2] >= min_y]


def overlay(img, pts, frame, path):
    ov = np.stack([np.where(img < 140, 90, 255)] * 3, -1).astype(np.uint8)
    colors = [(255, 0, 0), (0, 160, 0), (0, 0, 255), (200, 0, 200), (0, 170, 170)]
    for k, lab in enumerate(np.unique(pts[:, 0])):
        for *_, x, y in pts[pts[:, 0] == lab]:
            ov[int(y) - 2 : int(y) + 3, int(x) - 2 : int(x) + 3] = colors[k % 5]
    x0, y0, x1, y1 = frame
    ov = ov[y0 - 40 : y1 + 40, x0 - 40 : x1 + 40]
    with open(path, "wb") as f:
        f.write(f"P6 {ov.shape[1]} {ov.shape[0]} 255\n".encode())
        f.write(ov.tobytes())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--overlays", type=Path, help="write PPM overlays here for visual checks")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as td:
        pages = {p: render_page(PDF, p, Path(td)) for p in (3, 4, 5)}

    # Page 5, lower plot: average plate characteristics, each section.
    # Frame 0..400 V (x), 0..35 mA (y); grid 4 V x 0.5 mA.
    img = pages[5]
    win = img[2190:3665, 890:2975] < 140
    cx = grid_cal(win, 902.0, 2961.5, 100, 0, 890)
    cy = grid_cal(win, 3652.0, 2200.0, 70, 1, 2190)
    ec = [0, -2, -4, -6, -8, -10, -12, -14, -17, -20, -25, -30, -40, -50, -70]
    # Explicit seeds (Vp, Ip mA) located with a row-crossing pass and checked on the overlay.
    seeds = [
        (0, 104.2, 20.51),
        (-2, 139.5, 20.51),
        (-4, 169.9, 19.50),
        (-6, 195.7, 18.51),
        (-8, 213.6, 16.75),
        (-10, 228.4, 14.75),
        (-12, 240.7, 13.50),
        (-14, 255.1, 12.75),
        (-17, 270.1, 11.50),
        (-20, 287.8, 10.99),
        (-25, 302.9, 9.50),
        (-30, 315.9, 8.25),
        (-40, 355.0, 7.00),
        (-50, 363.0, 4.75),
        (-70, 375.0, 2.00),
    ]
    plate = digitize(
        img,
        (890, 2190, 2975, 3665),
        lambda x: np.polyval(cx, x) * 4.0,
        lambda y: np.polyval(cy, y) * 0.5,
        ec,
        seeds=seeds,
        exclude=[(2650, 2190, 2975, 2530)],
        min_y=0.5,
    )
    # Below ~1.5 mA the curves for Ec >= -30 V converge and the tracer can't
    # tell them apart. The flat Ec <= -40 V curves stay separate.
    plate = plate[(plate[:, 2] >= 1.5) | (plate[:, 0] <= -40)]
    if args.overlays:
        overlay(img, plate, (902, 2200, 2962, 3652), args.overlays / "plate.ppm")
    write(
        OUT / "ge_6386_plate.csv",
        "vg_v,vp_v,ip_a",
        np.stack([plate[:, 0], plate[:, 1], plate[:, 2] * 1e-3], 1),
    )

    # Page 4, lower plot: average transfer characteristics, each section.
    # Frame -56..0 V (x), 0..40 mA (y); grid 2 V x 2 mA.
    img = pages[4]
    transfer = digitize(
        img,
        (395, 2212, 2431, 3676),
        lambda x: -56 + (x - 399.0) * 56.0 / (2426.0 - 399.0),
        lambda y: (3671.0 - y) * 40.0 / (3671.0 - 2216.0),
        [300, 250, 200, 150, 100],
        seed_rows=[9],
        exclude=[(395, 2212, 1240, 2700)],
        min_y=0.4,
    )
    if args.overlays:
        overlay(img, transfer, (399, 2216, 2426, 3671), args.overlays / "transfer.ppm")
    write(
        OUT / "ge_6386_transfer.csv",
        "vp_v,vg_v,ip_a",
        np.stack([transfer[:, 0], transfer[:, 1], transfer[:, 2] * 1e-3], 1),
    )

    # Page 3, upper plot: transconductance vs grid-1 voltage, cascode connection,
    # Eb = 250 V, upper grid fed from Ecc2 through a 470k/470k divider.
    # Frame -60..0 V (x), log 10..10000 umho (y).
    img = pages[3]
    gm = digitize(
        img,
        (1145, 432, 2418, 1878),
        lambda x: -60 + (x - 1149.0) * 60.0 / (2414.0 - 1149.0),
        lambda y: 10 ** (4 - 3 * (y - 436.0) / (1873.0 - 436.0)),
        [300, 250, 200, 150],
        seed_rows=[450, 25],
        exclude=[(1145, 432, 1880, 1460)],
    )
    if args.overlays:
        overlay(img, gm, (1149, 436, 2414, 1873), args.overlays / "cascode_gm.ppm")
    write(
        OUT / "ge_6386_cascode_gm.csv",
        "ecc2_v,vg1_v,gm_s",
        np.stack([gm[:, 0], gm[:, 1], gm[:, 2] * 1e-6], 1),
    )


def write(path: Path, header: str, a: np.ndarray) -> None:
    np.savetxt(path, a, delimiter=",", header=header, comments="", fmt="%.6g")
    print(f"wrote {path.relative_to(REPO)}: {len(a)} points")


if __name__ == "__main__":
    main()

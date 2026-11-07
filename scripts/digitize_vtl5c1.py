"""Digitize the VTL5C1 and VTL5C2 Vactrols' curves from PerkinElmer's sheet (the Rhodes Suitcase
vibrato's optocoupler stand-ins, docs/RHODES_PLAN.md "The Suitcase").

    uv run --with pymupdf python scripts/digitize_vtl5c1.py [--part VTL5C2] [--check]

The sheet (data/datasheets/vactrol/perkinelmer_vtl5c1_5c2.pdf) carries its curves as bitmaps.
Its "Output Resistance vs. Input Current" plot is traced automatically: the curves are drawn
~5 px thick, the grid 1-2 px, so per pixel column the thick white runs are the curves, ordered
top to bottom (the light-adapt conditions 3, 2, 1, 4 where all four are drawn). The axes are
calibrated on the plot's grid lines (decades found as the long thin lines). As a check, curve 1
(dark adapted, 25 C) must pass the sheet's table: 20 kOhm at 1 mA, 600 at 10, 200 at 40
(VTL5C2: 5.5 kOhm, 800, 200).

The "Response Time" plot's four curves (turn-on and turn-off at 10 and 40 mA, after light adapt
condition 2) cross and two are dashed: they were read by eye at the grid's lines and are written
as given in RESPONSE below (in log R within ~5%; the provenance sidecar says so). The VTL5C2's
(RESPONSE_5C2) were read from the thick strokes' centres per pixel column (the plot's 1-2 px
grid eroded away), each assigned to its curve by eye, skipping columns where curves cross or a
dash's gap hides one.

Writes data/datasheets/<part>_resistance.csv (curve, i_a, r_ohm: curves 1 and 2) and
data/datasheets/<part>_response.csv (curve, t_s, r_ohm); provenance: <part>.provenance.yaml.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parents[1]
PDF = ROOT / "data" / "datasheets" / "vactrol" / "perkinelmer_vtl5c1_5c2.pdf"
DATASHEETS = ROOT / "data" / "datasheets"

# Read by eye from the sheet's VTL5C1 "Response Time" plot (turn-on: the top axis, 0-12 ms;
# turn-off: the bottom axis, 0-30 ms; ohms on the log axis): (curve, t_ms, R_ohm).
RESPONSE = [
    ("on_40mA", 0.0, 20000.0),
    ("on_40mA", 0.25, 2500.0),
    ("on_40mA", 0.5, 1000.0),
    ("on_40mA", 0.8, 700.0),
    ("on_40mA", 1.0, 560.0),
    ("on_40mA", 2.0, 400.0),
    ("on_40mA", 3.0, 330.0),
    ("on_40mA", 4.0, 290.0),
    ("on_40mA", 6.4, 250.0),
    ("on_10mA", 0.55, 100000.0),
    ("on_10mA", 1.0, 40000.0),
    ("on_10mA", 1.5, 20000.0),
    ("on_10mA", 2.0, 12000.0),
    ("on_10mA", 2.8, 7500.0),
    ("on_10mA", 4.0, 4600.0),
    ("on_10mA", 6.0, 3000.0),
    ("on_10mA", 8.0, 2200.0),
    ("on_10mA", 10.0, 1700.0),
    ("on_10mA", 12.5, 1300.0),
    ("off_40mA", 0.0, 200.0),
    ("off_40mA", 2.5, 1000.0),
    ("off_40mA", 5.0, 2000.0),
    ("off_40mA", 10.0, 5300.0),
    ("off_40mA", 15.0, 20000.0),
    ("off_40mA", 20.0, 60000.0),
    ("off_40mA", 21.5, 100000.0),
    ("off_10mA", 0.0, 1500.0),
    ("off_10mA", 5.0, 5000.0),
    ("off_10mA", 10.0, 14000.0),
    ("off_10mA", 15.0, 38000.0),
    ("off_10mA", 19.5, 100000.0),
]

# The VTL5C2's "Response Time" plot (turn-on: 0-12 ms; turn-off: 0-240 ms): (curve, t_ms,
# R_ohm), the strokes' centres (see the docstring).
RESPONSE_5C2 = [
    *(("on_40mA", t, r) for t, r in (
        (0.3, 4329), (0.5, 2807), (0.75, 1971), (1.0, 1445), (1.5, 965), (2.0, 749),
        (2.5, 590), (3.0, 497), (4.0, 383), (5.0, 311), (6.0, 273), (7.0, 243), (8.0, 220),
        (9.0, 204), (10.0, 190), (11.0, 177))),
    *(("on_10mA", t, r) for t, r in (
        (0.3, 12240), (0.5, 7492), (0.75, 4653), (1.0, 3267), (2.5, 986), (5.0, 574),
        (6.0, 507), (7.0, 452), (8.0, 412), (9.0, 388), (10.0, 391), (11.0, 383))),
    *(("off_40mA", t, r) for t, r in (
        (5.0, 336), (10.0, 534), (20.0, 972), (30.0, 1657), (40.0, 2519), (50.0, 3774),
        (60.0, 5222), (70.0, 7546), (80.0, 10072), (100.0, 16694), (120.0, 26117),
        (140.0, 39696), (160.0, 59042), (180.0, 85317))),
    *(("off_10mA", t, r) for t, r in (
        (5.0, 574), (10.0, 841), (30.0, 2014), (40.0, 3537), (50.0, 5074), (60.0, 6970),
        (70.0, 9507), (80.0, 12328), (100.0, 20141), (120.0, 31057), (140.0, 46528),
        (160.0, 68705), (180.0, 99281))),
]  # fmt: skip

# Per part: the resistance plot's bitmap (page 2's image index), the table's dark-adapted
# on-resistances at 1, 10, 40 mA and the factors the plot's curve 1 must meet them within,
# the response points. The VTL5C2's plot reads 433 ohm at 10 mA against the table's 800
# "typ." (its curves converge there; above ~17 mA they merge and aren't traced).
PARTS = {
    "VTL5C1": (0, (20e3, 600.0, 200.0), (1.1, 1.5, 1.5), RESPONSE),
    "VTL5C2": (1, (5.5e3, 800.0, 200.0), (1.1, 2.0, 1.5), RESPONSE_5C2),
}


def bitmap(index: int) -> np.ndarray:
    import pymupdf

    doc = pymupdf.open(PDF)
    page = doc[1]
    xref = page.get_images(full=True)[index][0]
    pix = pymupdf.Pixmap(doc, xref)
    if pix.n >= 4:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return a[..., :3].mean(axis=2) > 128  # white strokes on black


def calibration(w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The plot's decade lines: columns / rows white over most of the plot (thin grid)."""
    cols = np.flatnonzero(w.mean(axis=0) > 0.75)
    rows = np.flatnonzero(w.mean(axis=1) > 0.75)

    def groups(ix):
        out, cur = [], [ix[0]]
        for i in ix[1:]:
            if i - cur[-1] <= 2:
                cur.append(i)
            else:
                out.append(np.mean(cur))
                cur = [i]
        out.append(np.mean(cur))
        return np.array(out)

    return groups(cols), groups(rows)


def runs(col: np.ndarray, min_len: int) -> list[float]:
    """Centres of the white runs at least min_len long in a pixel column."""
    out, start = [], None
    for i, v in enumerate(np.append(col, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append(0.5 * (start + i - 1))
            start = None
    return out


def trace_resistance(index: int = 0) -> dict[str, list[tuple[float, float]]]:
    w = bitmap(index)
    xs, ys = calibration(w)
    # the decades: x 0.1, 1, 10, 100 mA; y 100k .. 100 ohm (top to bottom)
    x0, x3 = xs.min(), xs.max()
    y0, y3 = ys.min(), ys.max()
    to_ma = lambda px: 10 ** (-1 + 3 * (px - x0) / (x3 - x0))  # noqa: E731
    to_ohm = lambda py: 10 ** (5 - 3 * (py - y0) / (y3 - y0))  # noqa: E731
    curves: dict[str, list[tuple[float, float]]] = {"1": [], "2": []}
    for px in range(int(x0) + 3, int(x3) - 3):
        if np.min(np.abs(xs - px)) < 4:
            continue  # skip the vertical grid lines
        r = [c for c in runs(w[int(y0) + 2 : int(y3) - 1, px], 4)]
        r = [c + int(y0) + 2 for c in r]
        ma = to_ma(px)
        if ma > 40.5:
            continue  # the curves end at 40 mA
        if len(r) == 4:  # top to bottom: conditions 3, 2, 1, 4
            curves["2"].append((ma, to_ohm(r[1])))
            curves["1"].append((ma, to_ohm(r[2])))
        elif len(r) == 3 and ma < 2.0:  # condition 3 not yet drawn (above 100k)
            curves["2"].append((ma, to_ohm(r[0])))
            curves["1"].append((ma, to_ohm(r[1])))
        elif len(r) == 2 and ma < 1.0:  # conditions 1 and 4 only (2 is above 100k)
            curves["1"].append((ma, to_ohm(r[0])))
    # the labels' arrows cross the curves: a column there can count an arrow as a curve.
    # Drop the points more than 8% (in R) off their running median over 15 columns.
    for name, pts in curves.items():
        p = np.array(pts)
        lr = np.log(p[:, 1])
        med = np.array([np.median(lr[max(0, i - 7) : i + 8]) for i in range(lr.size)])
        curves[name] = [tuple(x) for x in p[np.abs(lr - med) < np.log(1.08)]]
    return curves


def check(curves, table=(20e3, 600.0, 200.0), tols=(1.1, 1.5, 1.5)) -> list[str]:
    """The calibration: curve 1 on the table at 1 mA within 10%. The sheet's plot and table
    disagree higher up (the VTL5C1's plot's curve 1 ends near 140 ohm at 40 mA, the table says
    200 "typ."; 500 against 600 at 10 mA): those are checked only within 50%."""
    errs = []
    c1 = np.array(curves["1"])
    for ma, want, tol in zip((1.0, 10.0, 40.0), table, tols, strict=True):
        if ma > c1[:, 0].max() * 1.05:
            continue  # past the trace's end (the VTL5C2's curves merge above ~17 mA)
        got = float(np.exp(np.interp(np.log(ma), np.log(c1[:, 0]), np.log(c1[:, 1]))))
        if abs(np.log(got / want)) > np.log(tol):
            errs.append(f"curve 1 at {ma} mA: {got:.0f} ohm, the table says {want:.0f}")
    return errs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--part", default="VTL5C1", choices=sorted(PARTS))
    ap.add_argument("--check", action="store_true", help="only check the table points")
    args = ap.parse_args()
    index, table, tols, response = PARTS[args.part]
    out_r = DATASHEETS / f"{args.part.lower()}_resistance.csv"
    out_t = DATASHEETS / f"{args.part.lower()}_response.csv"
    curves = trace_resistance(index)
    errs = check(curves, table, tols)
    c1 = np.array(curves["1"])
    for ma in (1.0, 10.0, 40.0):
        if ma > c1[:, 0].max() * 1.05:
            continue
        got = np.exp(np.interp(np.log(ma), np.log(c1[:, 0]), np.log(c1[:, 1])))
        print(f"curve 1 at {ma:4.0f} mA: {got:7.0f} ohm")
    if errs:
        print("\n".join(errs))
        sys.exit(1)
    if args.check:
        return
    with out_r.open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, lineterminator="\n")
        wr.writerow(["curve", "i_a", "r_ohm"])
        for name, pts in curves.items():
            pts = np.array(pts)
            # thin to ~40 points per curve, evenly in log current
            grid = np.geomspace(pts[:, 0].min(), pts[:, 0].max(), 40)
            r = np.exp(np.interp(np.log(grid), np.log(pts[:, 0]), np.log(pts[:, 1])))
            for i, rr in zip(grid, r, strict=True):
                wr.writerow([name, f"{i * 1e-3:.4g}", f"{rr:.4g}"])
    with out_t.open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, lineterminator="\n")
        wr.writerow(["curve", "t_s", "r_ohm"])
        for name, t_ms, r in response:
            wr.writerow([name, f"{t_ms * 1e-3:.4g}", f"{r:.4g}"])
    print(
        f"wrote {out_r.name} ({sum(len(v) for v in curves.values())} traced points), {out_t.name}"
    )


if __name__ == "__main__":
    main()

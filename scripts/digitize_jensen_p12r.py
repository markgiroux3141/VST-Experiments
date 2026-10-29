"""Digitize the Jensen P12R sheet's curves (8 ohm) into CSV from the PDF's vector paths.

Reproduces data/datasheets/jensen_p12r_{response,impedance}.csv from
data/datasheets/sources/jensen_p12r_2022.pdf (provenance: jensen_p12r.provenance.yaml).
Needs PyMuPDF, which the project doesn't depend on:

    uv run --with pymupdf python scripts/digitize_jensen_p12r.py

The sheet's page 2 plot is vector graphics, so nothing is traced: each curve is one path,
its vertices are the data. Axes from the grey grid lines: vertical lines at 30, 40, ...,
6000 Hz (log; the 20 Hz line is the frame) and horizontal lines matched to the +55 ...
+105 tick labels (the +50 and +110 ticks sit on the frame). The page clips the plot at
its right edge (about 8.5 kHz), but the paths run on to 20 kHz; the CSVs keep every vertex
and the provenance says which part was printed.
"""

from __future__ import annotations

import math
from pathlib import Path

import fitz  # PyMuPDF

REPO = Path(__file__).resolve().parents[1]
PDF = REPO / "data/datasheets/sources/jensen_p12r_2022.pdf"
OUT = REPO / "data/datasheets"
GRID_GREY = (0.933, 0.933, 0.933)
RED = (0.702, 0.137, 0.09)  # the 8 ohm curves (blue: 16 ohm)


def fit_line(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Least-squares y = a + b x; returns (a, b, max |residual|)."""
    n = len(pairs)
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    b = sum((x - mx) * (y - my) for x, y in pairs) / sum((x - mx) ** 2 for x, _ in pairs)
    a = my - b * mx
    return a, b, max(abs(a + b * x - y) for x, y in pairs)


def main() -> None:
    page = fitz.open(PDF)[1]
    drawings = page.get_drawings()
    vx, hy = set(), set()
    for d in drawings:
        if tuple(round(c, 3) for c in (d.get("color") or ())) != GRID_GREY:
            continue
        for it in d["items"]:
            if it[0] == "l" and abs(it[1].x - it[2].x) < 1e-3:
                vx.add(round(it[1].x, 4))
            elif it[0] == "l" and abs(it[1].y - it[2].y) < 1e-3:
                hy.add(round(it[1].y, 4))
    freqs = [m * dec for dec in (10, 100, 1000) for m in range(1, 10) if m * dec >= 30]
    xs = sorted(vx)
    ax, bx, rx = fit_line([(x, math.log10(f)) for x, f in zip(xs, freqs, strict=False)])
    ticks = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                t = sp["text"].strip()
                if t.startswith("+") and t[1:].isdigit():
                    yc = (sp["bbox"][1] + sp["bbox"][3]) / 2
                    g = min(hy, key=lambda y, yc=yc: abs(y - yc))
                    if abs(g - yc) < 1.0:
                        ticks.append((g, float(t[1:])))
    ay, by, ry = fit_line(ticks)
    print(f"x: {len(xs)} grid lines, max residual {rx:.1e} decades; "
          f"y: {len(ticks)} ticks, max residual {ry:.3f} dB; "
          f"page edge at {10 ** (ax + bx * page.rect.width):.0f} Hz")  # fmt: skip

    curves = {}
    for d in drawings:
        col = tuple(round(c, 3) for c in (d.get("color") or ()))
        if col != RED or (d.get("width") or 0) < 0.9:
            continue
        pts = []
        for it in d["items"]:
            if it[0] == "l":
                pts += [it[1], it[2]]
            elif it[0] == "c":
                pts += [it[1], it[4]]
        xy = []
        for p in pts:
            f, db = 10 ** (ax + bx * p.x), ay + by * p.y
            if not xy or (abs(xy[-1][0] - f), abs(xy[-1][1] - db)) != (0.0, 0.0):
                xy.append((f, db))
        # The response is the longer of the two red paths, the impedance the shorter.
        curves[len(d["items"])] = xy
    # (A third, short red path is the legend's sample line.)
    (_, resp), (_, imp) = sorted(curves.items(), reverse=True)[:2]
    for name, xy, header in (
        ("response", resp, "f_hz,spl_db"),
        ("impedance", imp, "f_hz,trace_db"),
    ):
        path = OUT / f"jensen_p12r_{name}.csv"
        path.write_text(
            header + "\n" + "".join(f"{f:.3f},{v:.3f}\n" for f, v in xy),
            encoding="utf-8",
            newline="\n",
        )
        print(f"{path.name}: {len(xy)} points, {xy[0][0]:.1f}-{xy[-1][0]:.0f} Hz")


if __name__ == "__main__":
    main()

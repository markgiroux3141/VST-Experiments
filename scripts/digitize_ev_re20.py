"""Digitize EV's RE20 data sheet (Rev G, 07/2010) from the PDF's vector paths.

Page 2: the frequency response (four traces: 0 and 180 deg, bass-tilt off solid / on dashed)
and the polar diagram (above / below 700 Hz).  Writes data/datasheets/ev_re20_response.csv and
ev_re20_polar.csv (provenance: ev_re20.provenance.yaml).

    uv run --with pymupdf python scripts/digitize_ev_re20.py PDF [--plot]

The sheet's graph is relative (a 5 dB grid, no absolute level): dB are re the 0 deg
switch-off curve at 1 kHz.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[1]


def bezier_points(items, n=24):
    pts = []
    for it in items:
        if it[0] == "l":
            pts += [(it[1].x, it[1].y), (it[2].x, it[2].y)]
        elif it[0] == "c":
            p0, p1, p2, p3 = (np.array([q.x, q.y]) for q in it[1:5])
            for t in np.linspace(0, 1, n):
                pts.append(tuple((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3))
    return np.array(pts)


def main(pdf: str) -> None:
    page = pymupdf.open(pdf)[1]
    dr = page.get_drawings()
    # frequency axis: the thick vertical rules are 50 100 200 500 1k 2k 5k 10k Hz
    xs = np.array([92.8, 116.6, 139.5, 167.3, 192.2, 213.9, 242.6, 267.2])
    fs = np.array([50, 100, 200, 500, 1000, 2000, 5000, 10000.0])
    a, b = np.polyfit(np.log10(fs), xs, 1)
    # level axis: horizontal rules read from drawing 6 (frame + 5 dB grid)
    hs = sorted({round(it[1].y, 1) for it in dr[6]["items"] if it[0] == "l" and abs(it[1].y - it[2].y) < 0.2})
    print("horizontal rules y:", hs, " per 5 dB:", np.diff(hs))
    ypdb = float(np.median(np.diff(hs))) / 5.0
    curves = {"0_off": 82, "0_tilt": 83, "180_off": 84, "180_tilt": 85}
    raw = {}
    for name, i in curves.items():
        pts = bezier_points(dr[i]["items"])
        f = 10 ** ((pts[:, 0] - b) / a)
        raw[name] = (f, pts[:, 1])
    f_ref = 1000.0
    f0, y0 = raw["0_off"]
    yref = float(np.interp(np.log10(f_ref), np.log10(f0[np.argsort(f0)]), y0[np.argsort(f0)]))
    grid = 10 ** np.arange(np.log10(20), np.log10(20000) + 1e-9, np.log10(2) / 3)
    rows = []
    for name, (f, y) in raw.items():
        o = np.argsort(f)
        f, y = f[o], y[o]
        for g in grid:
            if f[0] <= g <= f[-1]:
                rows.append((name, round(g, 1), round(-(float(np.interp(g, f, y)) - yref) / ypdb, 2)))
    out = ROOT / "data" / "datasheets" / "ev_re20_response.csv"
    out.write_text("trace,freq_hz,db_re_0deg_1khz\n" + "\n".join(f"{n},{f},{d}" for n, f, d in rows) + "\n")
    print("wrote", out, len(rows))
    # polar: centre = bbox of drawing 119 (outer ring), 0 deg up, 5 dB per ring division
    ring = dr[119]["rect"]
    cx, cy = (ring.x0 + ring.x1) / 2, (ring.y0 + ring.y1) / 2
    r_outer = (ring.x1 - ring.x0) / 2
    print("polar centre", cx, cy, "outer r", r_outer)
    # rings every 9.6 pt = 5 dB; dB are re each curve's own 0 deg radius (the sheet prints no level)
    per_db = 9.6 / 5.0
    prow = []
    r0_above = 0.0
    for name, i in (("above_700", 121), ("below_700", 122)):
        pts = bezier_points(dr[i]["items"], 8)
        dx, dy = pts[:, 0] - cx, cy - pts[:, 1]
        r = np.hypot(dx, dy)
        ang = np.degrees(np.arctan2(dx, dy))  # 0 up, +right
        near0 = np.abs(ang) < 6
        r0 = float(np.mean(r[near0])) if near0.any() else r0_above  # the dashed trace's 0 deg part is not in the file
        r0_above = r0
        o = np.argsort(ang)
        grid_a = np.arange(-180, 181, 15.0)
        for g in grid_a:
            if ang[o][0] - 1 <= g <= ang[o][-1] + 1:
                prow.append((name, g, round((float(np.interp(g, ang[o], r[o])) - r0) / per_db, 2)))
    lines = ["trace,angle_deg,db_re_0deg"] + [f"{n},{a_},{d}" for n, a_, d in prow]
    (ROOT / "data" / "datasheets" / "ev_re20_polar.csv").write_text(chr(10).join(lines) + chr(10))
    print("polar rows", len(prow))


if __name__ == "__main__":
    main(sys.argv[1])

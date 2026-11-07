"""Digitize Sennheiser's MD 421-II product specification (V1.1) from the PDF's vector paths.

Page 2: the frequency response (the nominal bass control position M solid, the other four
positions' dips dotted, absolute level in dBV for 1 Pa) and the polar diagram (125-1000 Hz
the left half, 2000-16000 Hz the right, 0 dB at the outer ring, 5 dB per ring to 25 dB).
Writes data/datasheets/sennheiser_md421_{response,polar}.csv (provenance:
sennheiser_md421.provenance.yaml).

    uv run --with pymupdf python scripts/digitize_md421.py PDF
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
NL = chr(10)


def points(items, n=16):
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
    dr = pymupdf.open(pdf)[1].get_drawings()
    # frequency: the major rules are 20 50 100 200 500 1k 2k 5k 10k 20k Hz
    xs = np.array([70.35, 103.15, 128.0, 152.8, 185.6, 210.4, 235.2, 268.05, 292.9, 317.7])
    fs = np.array([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000.0])
    a, b = np.polyfit(np.log10(fs), xs, 1)
    # level: rules every 16.5 pt = 10 dB, -40 dBV at y 667.65, -90 at 750.0
    y40, y90 = 667.65, 750.0
    def dbv(y):
        return -40.0 - (y - y40) / (y90 - y40) * 50.0

    # drawings 78-81 the four dips' dotted traces, 82 the M position (solid); order them by
    # their level at 50 Hz (a lower trace is a stronger roll-off): position M, then 1 .. 4
    traces = {}
    for i in (78, 79, 80, 81, 82):
        p = points(dr[i]["items"])
        f = 10 ** ((p[:, 0] - b) / a)
        o = np.argsort(f)
        traces[i] = (f[o], dbv(p[o, 1]))
    def at50(i):
        f, d = traces[i]
        return float(np.interp(50.0, f, d))
    order = sorted(traces, key=lambda i: -at50(i))  # highest first: M, then rolling off more
    grid = 10 ** np.arange(np.log10(40), np.log10(20000) + 1e-9, np.log10(2) / 3)
    rows = []
    for rank, i in enumerate(order):
        f, d = traces[i]
        for g in grid:
            if f[0] <= g <= f[-1]:
                rows.append(("M" if rank == 0 else f"dip{rank}", round(g, 1), round(float(np.interp(g, f, d)), 2)))
    out = ROOT / "data" / "datasheets" / "sennheiser_md421_response.csv"
    out.write_text(NL.join(["trace,freq_hz,dbv_per_pa"] + [f"{n},{f},{d}" for n, f, d in rows]) + NL)
    print("response rows", len(rows))
    # polar
    rings_r = (12.8, 26.7, 40.6, 54.7, 68.5, 82.1)  # 25 .. 0 dB
    per_db = (82.1 - 12.8) / 25.0
    cy = 486.4
    prow = []
    legend = {  # drawing: (centre x, Hz)
        126: (404.1, 125), 124: (404.1, 250), 123: (404.1, 500), 125: (404.1, 1000),
        121: (419.1, 2000), 120: (419.1, 4000), 119: (419.1, 8000), 122: (419.1, 16000),
    }  # fmt: skip
    for i, (cx, hz) in legend.items():
        p = points(dr[i]["items"], 8)
        side = -1.0 if cx < 410 else 1.0
        dx, dy = (p[:, 0] - cx) * side, cy - p[:, 1]
        r = np.hypot(dx, dy)
        ang = np.degrees(np.arctan2(dx, dy))  # 0 up, 180 down
        o = np.argsort(ang)
        for g in np.arange(0, 181, 15.0):
            if ang[o][0] - 1 <= g <= ang[o][-1] + 1:
                prow.append((hz, g, round(-(82.1 - float(np.interp(g, ang[o], r[o]))) / per_db, 2)))
    (ROOT / "data" / "datasheets" / "sennheiser_md421_polar.csv").write_text(
        NL.join(["freq_hz,angle_deg,db_re_axis"] + [f"{h},{g},{d}" for h, g, d in prow]) + NL
    )
    print("polar rows", len(prow))


if __name__ == "__main__":
    main(sys.argv[1])

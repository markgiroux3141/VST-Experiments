"""Figure 16 of Dickason's G12H(55) Test Bench (Voice Coil, Feb 2015): its 1-V free-air
impedance curve from the PDF's vector path, for the G12M's voice coil
(data/datasheets/voicecoil_g12h55.provenance.yaml).

    uv run --no-project --with pymupdf python scripts/digitize_g12h55_impedance.py         data/schematics/marshall_1987/voicecoil_2015-02_g12h55_testbench.pdf         data/datasheets/voicecoil_g12h55_impedance.csv
"""
import sys
import pymupdf as fitz
pdf = sys.argv[1]
d = fitz.open(pdf)
p = d[1]
items = []
for dr in p.get_drawings():
    r = dr["rect"]
    if 300 < r.x0 and r.x1 < 560 and 440 < r.y0 and r.y1 < 565:
        pts = []
        for it in dr["items"]:
            if it[0] == "l":
                pts += [it[1], it[2]]
            elif it[0] == "c":
                pts += [it[1], it[2], it[3], it[4]]
            elif it[0] == "re":
                pts += [it[1].tl, it[1].br]
        items.append((dr.get("color"), dr.get("width"), len(dr["items"]), r, pts))
items.sort(key=lambda t: -t[2])
for c, w, n, r, _ in items[:8]:
    print(c, w, n, [round(v, 1) for v in (r.x0, r.y0, r.x1, r.y1)])
# vertical / horizontal grid lines: short paths of one line each
vs = sorted({round(it[4][0].x, 2) for it in items if it[2] == 1 and len(it[4]) == 2 and abs(it[4][0].x - it[4][1].x) < 0.01})
hs = sorted({round(it[4][0].y, 2) for it in items if it[2] == 1 and len(it[4]) == 2 and abs(it[4][0].y - it[4][1].y) < 0.01})
print("vertical", len(vs), vs[:5], vs[-5:])
print("horizontal", len(hs), hs[:5], hs[-5:])

import math
X0, X1, Y0, Y1 = 321.2, 510.8, 560.6, 455.6  # frame: 10 Hz .. 20 kHz, 10 .. 300 ohm
curve = items[0][4]
rows = []
for pt in curve:
    lf = 1 + (pt.x - X0) / (X1 - X0) * (math.log10(20000) - 1)
    lz = 1 + (Y0 - pt.y) / (Y0 - Y1) * (math.log10(300) - 1)
    rows.append((10**lf, 10**lz))
rows.sort()
out = []
for f, z in rows:
    if not out or f > out[-1][0] * 1.0005:
        out.append((f, z))
with open(sys.argv[2], "w", newline="\n") as fh:
    fh.write("f_hz,z_ohm\n")
    for f, z in out:
        fh.write(f"{f:.3f},{z:.3f}\n")
print(len(out), "points", out[0], out[-1])
for target in (57, 300, 1000, 5000, 10000, 20000):
    f, z = min(out, key=lambda r: abs(math.log(r[0] / target)))
    print(f"  {f:.0f} Hz: {z:.1f} ohm")

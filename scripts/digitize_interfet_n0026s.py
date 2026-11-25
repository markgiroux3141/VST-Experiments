"""Digitize InterFET's N0026S geometry sheet (IF35506.R01, p. 3, "Typical Output @ VGS(OFF) =
-2.5V"): the process InterFET's 2N4302 / 2N4303 / 2N4304 are made on (their sheet IF35094.R00:
"InterFET N0026S Geometry"), the -2.5 V family's IDSS 5.8 mA inside the 2N4303's 4-10 mA. The
Minimoog's glide JFETs Q10 / Q13 are 2N4303s (Fig 9-7; docs/MINIMOOG_BACKLOG.md "Authenticity
first", item 4).

The chart is vector (Excel): each curve's line segments are read from the PDF's drawings by their
colour, mapped to volts and amperes through the chart's frame (VDS 0-10 V across x 319.1-481.9 pt,
ID 0-7 mA from y 238.1 up to 135.4 pt: the ticks' and grid lines' positions), and the points in
saturation (VDS >= 3 V, where the curves are flat) written out.

    uv run --no-project --with pymupdf --with numpy python scripts/digitize_interfet_n0026s.py

Writes data/datasheets/interfet_n0026s_output.csv (its provenance sidecar is hand-written beside).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data" / "datasheets" / "transistors" / "interfet_n0026s_geometry.pdf"
OUT = ROOT / "data" / "datasheets" / "interfet_n0026s_output.csv"
FRAME = pymupdf.Rect(318.0, 130.0, 483.0, 239.0)  # the -2.5 V chart, top right of p. 3
X0, X10 = 319.1, 481.9  # VDS 0 and 10 V
Y0, Y7 = 238.1, 135.4  # ID 0 and 7 mA
COLOURS = {  # the legend's curves by stroke colour (RGB rounded to 0.01)
    (0.31, 0.51, 0.74): 0.0,
    (0.75, 0.31, 0.3): -0.8,
    (0.97, 0.59, 0.27): -1.5,
    (0.61, 0.73, 0.35): -2.2,
}
VDS_MIN_V = 3.0


def main() -> None:
    page = pymupdf.open(PDF)[2]
    pts: dict[float, set] = {v: set() for v in COLOURS.values()}
    for d in page.get_drawings():
        col = tuple(round(c, 2) for c in (d["color"] or ()))
        if col in COLOURS and FRAME.contains(d["rect"]):
            for item in d["items"]:
                pts[COLOURS[col]].update((q.x, q.y) for q in item[1:] if hasattr(q, "x"))
    rows = []
    for vgs, ps in pts.items():
        a = np.array(sorted(ps))
        vds = (a[:, 0] - X0) / (X10 - X0) * 10.0
        i_d = (Y0 - a[:, 1]) / (Y0 - Y7) * 7e-3
        keep = vds >= VDS_MIN_V
        rows += [(vgs, v, i) for v, i in zip(vds[keep], i_d[keep], strict=True)]
    with OUT.open("w", newline="\n", encoding="utf-8") as f:
        f.write("vgs_v,vds_v,id_a\n")
        for vgs, vds, i in rows:
            f.write(f"{vgs:.1f},{vds:.3f},{i:.4e}\n")
    print(f"{len(rows)} points -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

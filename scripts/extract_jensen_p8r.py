"""The Jensen P8R reissue's curves from its product page's chart data (Plotly series in the
page's Drupal settings, saved verbatim as data/schematics/fender_5f1/jensen_p8r_curves.json):
the 4 ohm unit's response on the IEC baffle at 1 W, 1 m and its free-air impedance, written as
the P12R's CSVs (data/datasheets/jensen_p8r.provenance.yaml).

    uv run python scripts/extract_jensen_p8r.py
"""

import json
import math

from varimu.config import REPO_ROOT

SRC = REPO_ROOT / "data" / "schematics" / "fender_5f1" / "jensen_p8r_curves.json"
OUT = REPO_ROOT / "data" / "datasheets"


def main() -> None:
    chart = json.loads(SRC.read_text(encoding="utf-8"))["frequency_response_charts"][0]
    series = {s["name"]: s for s in chart["series"]}
    spl, z = series["Sound Pressure - 4 \u03a9"], series["Impedance - 4 \u03a9"]
    with open(OUT / "jensen_p8r_response.csv", "w", newline="\n") as fh:
        fh.write("f_hz,spl_db\n")
        for f, y in zip(spl["x"], spl["y"], strict=True):
            fh.write(f"{f:.3f},{y:.3f}\n")
    # The impedance as a trace in dB (the fit's form: trace = z0 + kz 20 log10 |Z|), here with
    # a true ohm axis (kz 1, z0 0).
    with open(OUT / "jensen_p8r_impedance.csv", "w", newline="\n") as fh:
        fh.write("f_hz,trace_db\n")
        for f, y in zip(z["x"], z["y"], strict=True):
            fh.write(f"{f:.3f},{20 * math.log10(y):.4f}\n")
    print("wrote", OUT / "jensen_p8r_response.csv", OUT / "jensen_p8r_impedance.csv")


if __name__ == "__main__":
    main()

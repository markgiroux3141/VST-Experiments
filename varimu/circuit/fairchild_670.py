"""What is 670-specific about the 670's circuit file (config/circuits/fairchild_670.yaml).

Its derived values (the file's `derived`: each is the function of that name here,
of the resolved parameters) lump channel 2's pairs of parallel parts into one
part each: channel 2 is idle (left/right mode, no input) and draws on the
shared rails only (the file's "channel 2" section). Plus the 6386 banks'
triodes and the AC THRESHOLD section's load, for the code that works on the
670 (setup, measurements).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# The 6386 triodes of each bank (sch: V101A/V102A + V103B/V104B on one side).
BANK_TRIODES = {
    "a": ("V101A", "V102A", "V103B", "V104B"),
    "b": ("V101B", "V102B", "V103A", "V104A"),
}


def ch2_6386_parallel(p: Mapping[str, Any]) -> int:
    """Channel 2's two 6386 banks as one device: twice the triodes per side."""
    if int(p["v6386_per_side"]) != len(BANK_TRIODES["a"]):
        raise ValueError("v6386_per_side: the banks are the drawing's four triodes each")
    return 2 * int(p["v6386_per_side"])


def ch2_6386_cathode_ohm(p: Mapping[str, Any]) -> float:
    """The two banks' cathode branches (680 + their part of the BALANCE pot) in parallel."""
    b, rk, rp = p["balance"], p["r103_r104_ohm"], p["r105_ohm"]
    ka, kb = rk + b * rp, rk + (1 - b) * rp
    return ka * kb / (ka + kb)


def ch2_6386_plate_ohm(p: Mapping[str, Any]) -> float:
    """R211 and both plate branches (meter shunt and T202 half) in parallel."""
    return p["r111_ohm"] + 0.5 * (p["r107_r108_ohm"] + p["t102_r_half_ohm"])


def ch2_12bh7_cathode_ohm(p: Mapping[str, Any]) -> float:
    """12BH7 cathodes: R224 || R225, and both feedback resistors to R234 || R235."""
    r34, r35 = p["r134_ohm"], p["r135_ohm"]
    r_fb = p["r_fb_ohm"] / 2 + r34 * r35 / (r34 + r35)
    return 1 / (2 / p["r124_r125_ohm"] + 1 / r_fb)


def threshold_section_load_ohm(p: Mapping[str, Any], total: float) -> float:
    """What one AC THRESHOLD section and its tap resistor load a T103 secondary half
    with (the wiper's 12AX7 grid draws nothing): the track above the tap in series with
    the rest of it in parallel with R113 / R114."""
    lo, r = p["ac_threshold_tap"] * total, p["r113_r114_ohm"]
    return (1 - p["ac_threshold_tap"]) * total + lo * r / (lo + r)

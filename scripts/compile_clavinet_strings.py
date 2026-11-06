"""The Clavinet's strings compiled for circuitsim (docs/CLAVINET_PLAN.md, CL3): saves the next
version of the component D6_STRINGS (kind clav_strings, varimu/clavinet/compile.py) when the
compiled data changed.

    uv run python scripts/compile_clavinet_strings.py [--check]

`--check` exits 1 when the latest version's data isn't what the code compiles now (the
instrument's file, the fits or the compiler changed: a new version is due, and the circuits
that pin the old one keep it until they are moved). The fits recompute themselves when
they are stale (cache/clavinet/, ~5 min cold).
"""

from __future__ import annotations

import argparse
import sys
import time

from varimu.clavinet import compile as cc
from varimu.devices import versions


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a new version is due")
    args = ap.parse_args()
    t0 = time.perf_counter()
    data = cc.compile_strings()
    _, blob = cc.pack(data)
    print(
        f"compiled {len(data['header']['keys'])} keys in {time.perf_counter() - t0:.1f} s"
        f" ({len(blob) / 1e6:.1f} MB)"
    )
    if args.check:
        have = versions.versions(cc.COMPONENT)
        same = bool(have) and cc.is_current(f"{cc.COMPONENT}@{have[-1]}", data)
        print(f"{cc.COMPONENT}: {'current' if same else 'a new version is due'}")
        sys.exit(0 if same else 1)
    ref = cc.save(cc.COMPONENT, data)
    print(f"saved {ref}" if ref else f"{cc.COMPONENT}: unchanged, nothing saved")


if __name__ == "__main__":
    main()

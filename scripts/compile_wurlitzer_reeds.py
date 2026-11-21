"""The 200A's reeds compiled for circuitsim (docs/WURLITZER_PLAN.md, WZ4): saves the next
version of the component WURLI_REEDS (kind ep_reeds, varimu/wurlitzer/compile.py) when the
compiled data changed.

    uv run python scripts/compile_wurlitzer_reeds.py [--check]

`--check` exits 1 when the latest version's data isn't what the code compiles now (the
instrument's file, the field maps or the compiler changed: a new version is due, and the
circuits that pin the old one keep it until they are moved).
"""

from __future__ import annotations

import argparse
import sys
import time

from varimu.devices import versions
from varimu.wurlitzer import compile as wc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a new version is due")
    args = ap.parse_args()
    t0 = time.perf_counter()
    data = wc.compile_reeds()
    print(f"compiled {len(data['keys'])} keys in {time.perf_counter() - t0:.1f} s")
    if args.check:
        have = versions.versions(wc.COMPONENT)
        same = bool(have) and wc._dump(wc.load_data(f"{wc.COMPONENT}@{have[-1]}")) == wc._dump(data)
        print(f"{wc.COMPONENT}: {'current' if same else 'a new version is due'}")
        sys.exit(0 if same else 1)
    ref = wc.save(wc.COMPONENT, data)
    print(f"saved {ref}" if ref else f"{wc.COMPONENT}: unchanged, nothing saved")


if __name__ == "__main__":
    main()

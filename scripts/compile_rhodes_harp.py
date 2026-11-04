"""The Rhodes harp compiled for circuitsim (docs/RHODES_PLAN.md, RH3): saves the next version
of the component MK1_HARP (kind ep_harp, varimu/rhodes/compile.py) when the compiled data
changed.

    uv run python scripts/compile_rhodes_harp.py [--check]

`--check` exits 1 when the latest version's data isn't what the code compiles now (the
instrument's file, the key fits or the compiler changed: a new version is due, and the
circuits that pin the old one keep it until they are moved).
"""

from __future__ import annotations

import argparse
import sys
import time

from varimu.devices import versions
from varimu.rhodes import compile as hc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a new version is due")
    args = ap.parse_args()
    t0 = time.perf_counter()
    data = hc.compile_harp()
    print(f"compiled {len(data['keys'])} keys in {time.perf_counter() - t0:.1f} s")
    if args.check:
        have = versions.versions(hc.COMPONENT)
        same = bool(have) and hc._dump(hc.load_data(f"{hc.COMPONENT}@{have[-1]}")) == hc._dump(data)
        print(f"{hc.COMPONENT}: {'current' if same else 'a new version is due'}")
        sys.exit(0 if same else 1)
    ref = hc.save(hc.COMPONENT, data)
    print(f"saved {ref}" if ref else f"{hc.COMPONENT}: unchanged, nothing saved")


if __name__ == "__main__":
    main()

"""Compile the Novachord's keys for the live tier (docs/NOVACHORD_PLAN.md, NV4;
varimu/novachord/compile.py) and save them as the next NOVACHORD_KEYS version when they
changed.

    uv run --extra fast python scripts/compile_novachord_keys.py [--check] [--quality draft]

The reference (config/circuits/novachord.yaml) is rendered once with every key up (cached in
cache/novachord/; ~1.5 min at draft). --check: exit 1 when the latest version isn't this
compile (the reference circuit or the compile changed). A new version is pinned by the live
circuit only when scripts/make_novachord.py's KEYS_COMPONENT moves to it.
"""

from __future__ import annotations

import argparse
import sys

from varimu.devices import versions
from varimu.novachord import compile as nc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quality", default="draft")
    args = ap.parse_args()
    data = nc.compile_keys(args.quality)
    if args.check:
        have = versions.versions(nc.COMPONENT)
        if not have:
            print("no version saved yet")
            return 1
        latest = nc.load(f"{nc.COMPONENT}@{have[-1]}")
        same = nc._dump(latest) == nc._dump(data)
        print(f"{nc.COMPONENT}@{have[-1]} {'is current' if same else 'is stale'}")
        return 0 if same else 1
    ref = nc.save(data)
    print(f"saved {ref}" if ref else "unchanged (the latest version is this compile)")
    for n, d in data["provenance"]["lock"].items():
        print(f"  {n}: f0 {d['f0_hz']} Hz, worst frame rms {d['worst_frame_rms_v']} V")
    return 0


if __name__ == "__main__":
    sys.exit(main())

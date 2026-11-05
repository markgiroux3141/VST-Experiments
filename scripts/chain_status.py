"""Which chains of the list are available, and what blocks the rest (docs/CHAINS_PLAN.md).

    uv run python scripts/chain_status.py [--blocked-only]

Reads config/chains.yaml (varimu/chains.py). A chain is available when every stage's
circuit is built (its file exists and has its port); a blocked one names its missing
circuits with the work package that builds each, and its needs; then what each work
package opens (CHAINS_PLAN.md's "Opens" column). Also says whether each
available chain's composed file exists (scripts/compose_chain.py --all writes them).
Always exits 0: a report.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from varimu import chains as chain_list


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--blocked-only", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # the labels' arrows on a cp1252 console
    cl = chain_list.load()
    avail = cl.available()
    print(f"chains available: {len(avail)} of {len(cl.chains)}")
    if not args.blocked_only:
        print("\navailable:")
        for c in avail:
            composed = "" if c.path.is_file() else "   (not composed: compose_chain.py --all)"
            print(f"  {c.id:<16} {c.label}{composed}")
    print("\nblocked:")
    by_wp: defaultdict[int, list[str]] = defaultdict(list)
    for c in cl.chains:
        if c.available:
            continue
        missing = ", ".join(f"{s.name} (WP{s.wp})" for s in c.missing)
        needs = ", ".join(
            n + (f" (WP{cl.needs[n]['wp']})" if "wp" in cl.needs[n] else "") for n in c.needs
        )
        note = f"; {c.needs_note}" if c.needs_note else ""
        print(f"  {c.id:<16} {c.label}\n  {'':<16} missing {missing}; needs {needs}{note}")
        wps = [s.wp or 0 for s in c.missing] + [cl.needs[n].get("wp", 0) for n in c.needs]
        by_wp[max(wps)].append(c.id)
    print("\nwhat each WP opens (the blocked chains by the last WP they wait on):")
    for wp, ids in sorted(by_wp.items()):
        print(f"  WP{wp:<3} {len(ids)}: {', '.join(ids)}")


if __name__ == "__main__":
    main()

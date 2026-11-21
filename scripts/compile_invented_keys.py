"""Compile the invented keyboards (docs/INVENTED_LIVE_PLAN.md) into component versions of
kind invented_keys: config/components/<name>/<N>.yaml + <N>.keys.json.

    uv run python scripts/compile_invented_keys.py [--check] [NAME ...]

--check: exit 1 when a compiled keyboard differs from its latest version (a new one is due).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from varimu.invented.keys import compile as kc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    due = 0
    for name, fn in kc.models().items():
        if args.names and name not in args.names:
            continue
        data = fn()
        latest = kc.latest(name)
        sha = hashlib.sha256(kc.dump(data).encode("utf-8")).hexdigest()
        same = latest is not None and kc.files(latest)[1] == sha
        if args.check:
            print(f"{name}: {'current' if same else 'a new version is due'} ({latest})")
            due += not same
            continue
        ref = kc.save(name, data)
        print(f"{name}: {'unchanged at ' + str(latest) if ref is None else 'saved ' + str(ref)}")
    return 1 if due else 0


if __name__ == "__main__":
    sys.exit(main())

"""Compile the Victorian synth's keyboard of reeds for circuitsim's `reeds` medium: the
component GRAY_REEDS's next version, `config/components/gray_reeds/<N>.yaml` and its
`<N>.reeds.json` (docs/VICTORIAN_SYNTH_PLAN.md; varimu/victorian/compile.py).

    uv run python scripts/compile_victorian_reeds.py [--check]

The first run tunes every reed with the Python reference (two passes on all cores but two;
cached in cache/victorian/tuning.json). A version is saved only when the data changed; moving
the circuit (config/circuits/victorian_voice.yaml's `reeds_model`) to it is an explicit edit.
`--check` exits 1 when the latest version differs from what the config and the code give now.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from varimu.victorian import compile as vcompile  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    data = vcompile.keyboard(progress=True)
    if a.check:
        have = vcompile.latest()
        same = have is not None and vcompile.load(have) == json.loads(vcompile.dump(data))
        print(f"{have} up to date" if same else "stale: rerun without --check")
        return 0 if same else 1
    ref = vcompile.save(data)
    if ref is None:
        print(f"unchanged: {vcompile.latest()}")
    else:
        print(f"saved {ref} ({len(data['keys'])} keys)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""A scene's sources recorded in its room through its mics' chains (ROOM_LOOP_PLAN.md R3)
-> reports/rooms/<scene>/ (or --out).

    uv run --extra fast python scripts/room_print.py config/scenes/NAME.yaml [--solo]
        [--out DIR] [--quality production|draft|draft-1x] [--workers N] [--wave HZ]
        [--balance]

The scene format and what is written: varimu/rooms/scene.py's docstring. `--solo` also
prints each source alone through every mic (the bleed matrix in render.json). `--wave HZ`
puts the wave solver under HZ (0: off; else the scene's `wave_crossover_hz`). `--balance`
writes the scene's live balance instead of printing it (each source's stereo stem through
the chains' linear proxies: varimu/rooms/balance.py). Progress goes to stdout as
`progress F` lines and step lines (the native app's Room view reads them).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from varimu.config import REPO_ROOT
from varimu.rooms.scene import load_scene, render


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scene", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--solo", action="store_true")
    ap.add_argument("--quality")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--wave", type=float)
    ap.add_argument("--balance", action="store_true")
    args = ap.parse_args()
    scene = load_scene(args.scene)
    if args.quality:
        scene.quality = args.quality
    if args.wave is not None:
        scene.wave_crossover_hz = args.wave or None
    out = args.out or REPO_ROOT / "reports" / "rooms" / scene.name

    def log(line: str) -> None:
        print(line, flush=True)

    if args.balance:
        from varimu.rooms.balance import prepare

        prepare(scene, out, log=log)
        print(f"wrote {out}", file=sys.stderr)
        return
    result = render(scene, out, solo=args.solo, workers=args.workers, log=log)
    print(json.dumps({k: v for k, v in result.items() if k != "mics"}, indent=1))
    for m in result["mics"]:
        print(m["name"], m["rms_dbfs"], "dBFS rms", m.get("bleed", ""))
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()

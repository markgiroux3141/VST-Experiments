"""A listening demo of directional sources (docs/ROOM_LOOP_PLAN.md "Later": a source's
directivity) -> reports/rooms/source_demo/.

    uv run --extra fast --extra listen python scripts/room_source_demo.py [--seconds 20]

An electric guitar (David Tyo's "Long Way Home", Cambridge-MT multitrack, the user's copy;
never committed) played through a 1x12 combo (varimu/rooms/directivity.py `amp_1x12`: a 15 cm
cone on a 25 cm sphere for its cabinet), its cone 40 cm off the floor in the live room (7 x 5.5
x 3.2 m, furnished), 95 dB SPL on its axis at 1 m; a spaced pair of clean small omnis 2.6 m
away (`omni_clean`, 30 dB). The wave solver below 500 Hz (the cabinet in its grid).

Variants (each `room_pair.wav` at -18 LUFS, so what changes is the timbre and the room, not
the level; `levels.json` has the raw levels):
- `toward/`: the amp faces the pair;
- `away/`: the amp faces the wall behind it, 1.4 m back (the pair hears the room and the
  cabinet's back);
- `omni/`: the same source as an omni (every source before directivity).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT
from varimu.rooms.scene import balance, load_scene, render

STEMS = Path("D:/Audio files for mixing/DavidTyo_LongWayHome/DavidTyo_LongWayHome")
OUT = REPO_ROOT / "reports" / "rooms" / "source_demo"
ROOM = {
    "floor_m": [[0, 0], [7, 0], [7, 5.5], [0, 5.5]],
    "ceiling": {"type": "flat", "height_m": 3.2},
    "materials": {"walls": "furnished_wall", "floor": "wood_floor", "ceiling": "gypsum_on_studs"},
    "source": "provisional: model knowledge (the live room of docs/ROOM_LOOP_PLAN.md R5)",
}
VARIANTS = {"toward": ("amp_1x12", 90.0), "away": ("amp_1x12", -90.0), "omni": (None, 0.0)}
PAIR = {"chain": "omni_clean", "set": {"gain_db_clean": 30}}


def _log(line: str) -> None:
    if not line.startswith("progress"):
        print("  ", line, flush=True)


def main() -> None:
    import pyloudnorm
    import soundfile as sf

    from varimu.sim.io import load_audio

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--stems", type=Path, default=STEMS)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fs = 96000
    clip = OUT / "guitar.wav"
    x = load_audio(args.stems / "12_ElecGtr1.wav", fs)[: int(args.seconds * fs)]
    sf.write(clip, x.astype("<f4"), fs, subtype="FLOAT")
    levels = {}
    for variant, (pattern, az) in VARIANTS.items():
        scene = {
            "name": f"source_demo_{variant}",
            "room": ROOM,
            "sources": [{"name": "amp", "clip": str(clip), "spl_db": 95,
                         "position_m": [3.5, 1.4, 0.4], "directivity": pattern,
                         "aim": {"azimuth_deg": az}}],
            "mics": [
                {"name": name, "position_m": [3.5 + dx, 4.0, 1.6], "aim": {"azimuth_deg": -90},
                 **PAIR, "pan": pan}
                for name, dx, pan in (("room L", -0.5, -1.0), ("room R", 0.5, 1.0))
            ],
            "settings": {"quality": "production", "seed": 0, "wave_crossover_hz": 500},
        }  # fmt: skip
        print("render", variant, flush=True)
        res = render(load_scene(scene), OUT / variant, log=_log)
        tr = {m["name"]: sf.read(OUT / variant / m["file"])[0] for m in res["mics"]}
        n = max(len(y) for y in tr.values())
        pair = np.zeros((2, n))
        for m in res["mics"]:
            gl, gr = balance(m["pan"])
            y = np.pad(tr[m["name"]], (0, n - len(tr[m["name"]])))
            pair += np.stack([gl * y, gr * y])
        lufs = pyloudnorm.Meter(fs).integrated_loudness(pair.T)
        out = (pair * 10 ** ((-18 - lufs) / 20)).T.astype("<f4")
        sf.write(OUT / variant / "room_pair.wav", out, fs, subtype="FLOAT")
        mics_db = {m["name"]: m["rms_dbfs"] for m in res["mics"]}
        levels[variant] = {"lufs_raw": round(float(lufs), 2), "mics_rms_dbfs": mics_db}
        (OUT / "levels.json").write_text(json.dumps(levels, indent=1), encoding="utf-8")
        print(variant, levels[variant], flush=True)


if __name__ == "__main__":
    main()

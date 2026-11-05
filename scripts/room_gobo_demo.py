"""A listening demo of objects and edge diffraction (docs/ROOM_LOOP_PLAN.md R11): two players
in the live room, each on a close omni, without and with a gobo between them ->
reports/rooms/gobo_demo/.

    uv run --extra fast --extra listen python scripts/room_gobo_demo.py [--seconds 20]

The performance: the lead vocal (92 dB SPL at 1 m) and an acoustic guitar (88) of David Tyo's
"Long Way Home" (Cambridge-MT multitrack, the user's copy; never committed), 1.8 m apart in
the 7 x 5.5 x 3.2 m furnished room, each on the clean small omni (`omni_clean`, 30 dB) 0.3 m
in front. Omnis on purpose: they hear the other player as well as their own, so the gobo is
all the isolation there is. The wave solver runs below 500 Hz in both (round the gobo's
edges by itself there), the geometric model above with the gobo's edges diffracting.

Variants: `open/` and `gobo/` (a 1.4 x 1.8 m gobo, 8 cm, heavy drapes, between them) in the
live room; `treated_open/` and `treated_gobo/` the same in the same room treated (drapes on the
walls, carpet, an acoustic-tile ceiling), where the reverberant bleed is small and the gobo's
shadow is most of the story. In each:
`<spot>.wav` (both players), `<spot>__<player>.wav` (one player alone: `guitar_spot__vocal.wav`
is the vocal's bleed into the guitar's mic). Every file of a room's two variants carries the
same gain (its open guitar spot at -18 LUFS), so the bleed's drop is heard as it is.
`bleed.json`: each spot's level of each player, per octave.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT
from varimu.rooms.scene import load_scene, render

STEMS = Path("D:/Audio files for mixing/DavidTyo_LongWayHome/DavidTyo_LongWayHome")
OUT = REPO_ROOT / "reports" / "rooms" / "gobo_demo"
ROOM = {
    "floor_m": [[0, 0], [7, 0], [7, 5.5], [0, 5.5]],
    "ceiling": {"type": "flat", "height_m": 3.2},
    "materials": {"walls": "furnished_wall", "floor": "wood_floor", "ceiling": "gypsum_on_studs"},
    "source": "provisional: model knowledge (the live room of docs/ROOM_LOOP_PLAN.md R5)",
}
TREATED = {**ROOM, "materials": {"walls": "heavy_drapes", "floor": "carpet_on_pad",
                                 "ceiling": "acoustic_tile"}}  # fmt: skip
VARIANTS = {"open": (ROOM, False), "gobo": (ROOM, True), "treated_open": (TREATED, False),
            "treated_gobo": (TREATED, True)}  # fmt: skip
GOBO = {"name": "gobo", "center_m": [3.5, 2.9, 0.9], "size_m": [1.4, 0.08, 1.8], "yaw_deg": 90,
        "material": "heavy_drapes"}  # fmt: skip
SPOT = {"chain": "omni_clean", "set": {"gain_db_clean": 30}}


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
    clips = OUT / "sources"
    clips.mkdir(exist_ok=True)
    for name, stem in (("vocal", "17_LeadVox"), ("guitar", "11_AcousticGtr2")):
        x = load_audio(args.stems / f"{stem}.wav", fs)[: int(args.seconds * fs)]
        sf.write(clips / f"{name}.wav", x.astype("<f4"), fs, subtype="FLOAT")
    results = {}
    for variant, (base, with_gobo) in VARIANTS.items():
        room = {**base, "objects": [GOBO]} if with_gobo else base
        scene = {
            "name": f"gobo_demo_{variant}",
            "room": room,
            "sources": [
                {"name": "vocal", "clip": str(clips / "vocal.wav"), "spl_db": 92,
                 "position_m": [2.6, 2.75, 1.6]},
                {"name": "guitar", "clip": str(clips / "guitar.wav"), "spl_db": 88,
                 "position_m": [4.4, 2.75, 1.0]},
            ],
            "mics": [
                {"name": "vocal spot", "position_m": [2.6, 3.05, 1.6], "aim": {"azimuth_deg": -90},
                 **SPOT, "pan": -0.3},
                {"name": "guitar spot", "position_m": [4.4, 3.05, 1.0],
                 "aim": {"azimuth_deg": -90}, **SPOT, "pan": 0.3},
            ],
            "settings": {"quality": "production", "seed": 0, "wave_crossover_hz": 500},
        }  # fmt: skip
        print("render", variant, flush=True)
        results[variant] = render(load_scene(scene), OUT / variant, solo=True, log=_log)
    # one gain for every file of a room: its open guitar spot at -18 LUFS
    gains = {}
    for ref_v in ("open", "treated_open"):
        ref, _ = sf.read(OUT / ref_v / "guitar_spot.wav")
        gains[ref_v] = 10 ** ((-18.0 - pyloudnorm.Meter(fs).integrated_loudness(ref)) / 20)
    for variant in VARIANTS:
        gain = gains["treated_open" if variant.startswith("treated") else "open"]
        for f in (OUT / variant).glob("*.wav"):
            if f.name == "mix.wav":
                continue
            y, _ = sf.read(f)
            sf.write(f, (gain * y).astype("<f4"), fs, subtype="FLOAT")
    bleed = {
        v: {m["name"]: {**m["bleed"], "intermod_db": m["intermod_db"]} for m in r["mics"]}
        for v, r in results.items()
    }
    (OUT / "bleed.json").write_text(json.dumps(bleed, indent=1), encoding="utf-8")
    for a, b in (("open", "gobo"), ("treated_open", "treated_gobo")):
        for spot, other in (("guitar spot", "vocal"), ("vocal spot", "guitar")):
            o = np.array(bleed[a][spot][other]["octaves_db"])
            g = np.array(bleed[b][spot][other]["octaves_db"])
            print(f"{b} {spot}: {other}'s bleed with the gobo, per octave (dB):",
                  " ".join(f"{x:+.1f}" for x in g - o))  # fmt: skip


if __name__ == "__main__":
    main()

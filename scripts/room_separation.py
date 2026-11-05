"""The room separation experiment (docs/ROOM_LOOP_PLAN.md R5): two sources in a live room,
each spot-miked through a chain, a spaced omni pair as room mics panned hard left and
right; how well do the two separate, per pair of spot chains?

    uv run --extra fast --extra listen python scripts/room_separation.py [--render-only]
        [--analyse-only] [--quality production] [--room shoebox|poly]

Sources: the separation study's dry synth lines (cache/separation/conditions/dry/: the
target melody, the same with one note changed, the arpeggio masker; run
scripts/separation_study.py first), 8 s each, both 90 dB SPL at 1 m. The room: 7 x 5.5 x
3.2 m, furnished walls, a wood floor, a gypsum ceiling (RT60 0.44-0.84 s). A (the target)
and B (the masker) 2.5 m apart at 1.3 m; each spot 0.3 m from its source on the side
toward the other source, aimed at it (the other source ~157 deg off axis: in a cardioid's
rear). The room pair: two pressure omnis 1 m apart, 2.3 m out, 2 m up, through the clean
preamp (the user's open call 2, decided: the classic spaced pair; the swap condition
cancels its bias).

Spot chains per condition (CONDITIONS): the same chain on both (U47 -> V76, or the clean
omni chain), the opposite chains both ways round, and the pattern control (B through the
U47 in omni: B's pattern as the clean omni's, its texture the U47 -> V76's).

Every scene renders with each source alone through every mic (varimu.rooms.scene `solo`),
once with the target and once with the changed target, into reports/rooms/separation/
<condition>/<variant>/. The mixes are built from the solos (the room is linear; the
chains' intermodulation is reported per mic), so the target's level in the mix is a
fader: per mix (spots centred or panned +-0.5; room pair off, -6 or 0 dB re the spots)
the target's and the masker's stereo stems are each matched to -23 LUFS and the target
set 6 dB under (the separation study's operating point). Metrics (varimu.rooms.binaural):
the monaural glimpse proportion on the notes' cells (the study's), the better-ear glimpse
proportion (each cell's better channel), and the binaural masking level difference per
band (the equalization-cancellation model, Lavandier & Culling 2010) folded into an
effective target-to-masker ratio. -> reports/rooms/separation/summary.json; the stereo
mixes for the listening staircase (scripts/room_separation_listen.py) in each
condition's folder.

`--room poly` (ROOM_LOOP_PLAN.md R8) renders the same room as a floor plan through
varimu.rooms.polyroom (image sources to 4 reflections, the ray-traced tail) into
reports/rooms/separation/polyroom/, with `compare.json` there: each table cell's change from
the shoebox's.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from varimu.config import REPO_ROOT
from varimu.rooms.scene import load_scene, render

DRY = REPO_ROOT / "cache" / "separation" / "conditions" / "dry"
OUT = REPO_ROOT / "reports" / "rooms" / "separation"

ROOM = {
    "dims_m": [7.0, 5.5, 3.2],
    "materials": {"walls": "furnished_wall", "floor": "wood_floor", "ceiling": "gypsum_on_studs"},
    "source": "provisional: model knowledge (a live tracking room, 7 x 5.5 x 3.2 m, furnished)",
}
POLY_ROOM = {
    "floor_m": [[0.0, 0.0], [7.0, 0.0], [7.0, 5.5], [0.0, 5.5]],
    "ceiling": {"type": "flat", "height_m": 3.2},
    "materials": ROOM["materials"],
    "source": ROOM["source"],
}
A_POS, B_POS = [2.0, 2.55, 1.3], [4.5, 2.55, 1.3]
# Spots 0.3 m from their source toward the other one, aimed back at it.
SPOT_A = {"position_m": [2.28, 2.45, 1.3], "aim": {"azimuth_deg": 160.35}}
SPOT_B = {"position_m": [4.22, 2.45, 1.3], "aim": {"azimuth_deg": 19.65}}
ROOM_L = {"position_m": [2.75, 4.85, 2.0], "aim": {"azimuth_deg": -90, "elevation_deg": -15}}
ROOM_R = {"position_m": [3.75, 4.85, 2.0], "aim": {"azimuth_deg": -90, "elevation_deg": -15}}

U47C = {"chain": "u47_v76", "set": {"pattern_u47": 0, "gain_db_v76": 34}}
U47O = {"chain": "u47_v76", "set": {"pattern_u47": 1, "gain_db_v76": 34}}
OMNI = {"chain": "omni_clean", "set": {"gain_db_clean": 40}}
ROOM_CHAIN = {"chain": "omni_clean", "set": {"gain_db_clean": 40}}  # 50 clipped the room pair

CONDITIONS = {
    "same_u47": (U47C, U47C),
    "same_omni": (OMNI, OMNI),
    "opposite": (U47C, OMNI),
    "swapped": (OMNI, U47C),
    "pattern_control": (U47C, U47O),
}
VARIANTS = {"target": "target.wav", "changed": "target_changed.wav"}
MIXES = {
    "centre_room_off": (0.0, None),
    "centre_room_-6": (0.0, -6.0),
    "centre_room_0": (0.0, 0.0),
    "panned_room_off": (0.5, None),
    "panned_room_-6": (0.5, -6.0),
}
TMR_DB = -6.0


def scene(cond: str, variant: str, quality: str, room: str = "shoebox") -> dict:
    a, b = CONDITIONS[cond]
    return {
        "name": f"separation_{cond}_{variant}",
        "room": POLY_ROOM if room == "poly" else ROOM,
        "sources": [
            {"name": "A", "clip": str(DRY / VARIANTS[variant]), "spl_db": 90, "position_m": A_POS},
            {"name": "B", "clip": str(DRY / "masker.wav"), "spl_db": 90, "position_m": B_POS},
        ],
        "mics": [
            {"name": "spot A", **SPOT_A, **a, "pan": -0.5},
            {"name": "spot B", **SPOT_B, **b, "pan": 0.5},
            {"name": "room L", **ROOM_L, **ROOM_CHAIN, "pan": -1.0},
            {"name": "room R", **ROOM_R, **ROOM_CHAIN, "pan": 1.0},
        ],
        "settings": {"quality": quality, "seed": 0},
    }


def render_all(quality: str, room: str, out) -> None:
    for cond in CONDITIONS:
        for variant in VARIANTS:
            d = out / cond / variant
            sc = scene(cond, variant, quality, room)
            done = d / "scene.json"
            if (
                (d / "render.json").exists()
                and done.exists()
                and json.loads(done.read_text()) == sc
            ):
                print("have", d)
                continue
            print("render", d, flush=True)
            render(load_scene(sc), d, solo=True, log=lambda s: None)
            done.write_text(json.dumps(sc, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--analyse-only", action="store_true")
    ap.add_argument("--quality", default="production")
    ap.add_argument("--room", choices=["shoebox", "poly"], default="shoebox")
    args = ap.parse_args()
    out = OUT / "polyroom" if args.room == "poly" else OUT
    if not args.analyse_only:
        render_all(args.quality, args.room, out)
    if args.render_only:
        return
    from varimu.rooms.binaural import analyse

    summary = analyse(out, list(CONDITIONS), MIXES, TMR_DB)
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary["table"], indent=1))
    if args.room == "poly" and (OUT / "summary.json").exists():
        old = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
        diff = {
            cond: {
                mix: [round(a - b, 3) for a, b in zip(row, old["table"][cond][mix], strict=True)]
                for mix, row in mixes.items()
            }
            for cond, mixes in summary["table"].items()
        }
        own = {
            cond: {
                m: [
                    c["mics"][m].get("own_minus_other_db"),
                    old["conditions"][cond]["mics"][m].get("own_minus_other_db"),
                ]
                for m in c["mics"]
            }
            for cond, c in summary["conditions"].items()
        }
        cmp = {
            "what": "polyroom minus shoebox, per table cell (columns as table_columns)",
            "table_columns": summary["table_columns"],
            "difference": diff,
            "own_minus_other_db (poly, shoebox)": own,
        }
        (out / "compare.json").write_text(json.dumps(cmp, indent=1), encoding="utf-8")
        print(json.dumps(diff, indent=1))


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()

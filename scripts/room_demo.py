"""A listening demo of room shapes (docs/ROOM_LOOP_PLAN.md R6): one performance recorded
in four rooms through the same mics -> reports/rooms/demo/.

    uv run --extra fast --extra listen python scripts/room_demo.py [--seconds 20]
        [--only ROOM ...] [--stems DIR] [--wave HZ --out DIR]

`--wave HZ` puts the wave solver under HZ (ROOM_LOOP_PLAN.md R10; e.g. --wave 500 --out
reports/rooms/demo_wave: the same rooms with their modes, beside reports/rooms/demo/).

The performance: David Tyo's "Long Way Home" (Cambridge-MT multitrack, the user's copy;
educational use, never committed): the lead vocal, an acoustic guitar and the piano, from
the start, each placed in the room as a point source (vocal 92 dB SPL at 1 m, guitar 88,
piano 90). The mics, the same in every room: the vocal on the U47 -> V76 (cardioid, 0.3 m),
the guitar on the clean small omni (0.3 m), no spot on the piano (it reaches the mics through
the room), and a spaced pair of clean omnis 1 m apart out in the room.

The rooms (every one through varimu.rooms.polyroom, the shoebox too, so the tails are
computed alike):
- `shoebox`: 7 x 5.5 m, a flat 3.2 m ceiling, furnished walls, wood floor, gypsum ceiling (the
  separation experiment's room): parallel walls.
- `splayed_gable`: the same materials and about the same floor area, no two walls parallel,
  a gable ceiling 2.8 m at the eaves to 4.6 m at the ridge.
- `angled`: the shoebox's volume (123 m^3), floor area and materials, its walls splayed and its
  ceiling a shed (2.6 to 3.8 m, 3.2 on average): the shoebox's A/B, only the shape differs.
- `vaulted_hall`: a 14 x 9 m hall with cut corners, furnished walls, a plaster barrel vault
  5.5 to 9 m: a long, live tail.
- `treated_studio`: an angled room with drapes on the walls, carpet and an acoustic-tile shed
  ceiling (2.7 to 3.6 m): dry.

Per room: each mic's print, `mix.wav` (stereo: the vocal spot near the centre, the guitar
spot right, the room pair hard left / right 6 dB under the spots), `room_pair.wav` (the
room mics alone: the room's sound), every file at -18 LUFS; and `dry.wav` (the stems
summed, no room) beside the rooms. reports/rooms/demo/demo.json lists the rooms' RT60s.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT
from varimu.rooms.polyroom import PolyRoom
from varimu.rooms.scene import balance, load_scene, render

STEMS = Path("D:/Audio files for mixing/DavidTyo_LongWayHome/DavidTyo_LongWayHome")
OUT = REPO_ROOT / "reports" / "rooms" / "demo"
LUFS = -18.0

FURNISHED = {"walls": "furnished_wall", "floor": "wood_floor", "ceiling": "gypsum_on_studs"}
HALL = {"walls": "furnished_wall", "floor": "wood_floor", "ceiling": "plaster"}
TREATED = {"walls": "heavy_drapes", "floor": "carpet_on_pad", "ceiling": "acoustic_tile"}
ROOMS = {
    "shoebox": {
        "floor_m": [[0, 0], [7, 0], [7, 5.5], [0, 5.5]],
        "ceiling": {"type": "flat", "height_m": 3.2},
        "materials": FURNISHED,
    },
    "splayed_gable": {
        "floor_m": [[0, 0], [7.4, 0.5], [7.9, 5.6], [3.6, 6.4], [-0.5, 5.0]],
        "ceiling": {"type": "gable", "height_m": 2.8, "peak_m": 4.6, "axis_deg": 5},
        "materials": FURNISHED,
    },
    "angled": {
        "floor_m": [[0.0, 0.0], [6.88, 0.46], [7.34, 5.21], [3.35, 5.95], [-0.46, 4.65]],
        "ceiling": {"type": "shed", "height_m": 2.6, "peak_m": 3.8, "axis_deg": 30},
        "materials": FURNISHED,
    },
    "vaulted_hall": {
        "floor_m": [[1.5, 0], [12.5, 0], [14, 1.5], [14, 7.5], [12.5, 9], [1.5, 9], [0, 7.5],
                    [0, 1.5]],
        "ceiling": {"type": "vault", "height_m": 5.5, "peak_m": 9.0, "axis_deg": 90, "facets": 8},
        "materials": HALL,
    },
    "treated_studio": {
        "floor_m": [[0, 0], [6.2, 0.4], [6.6, 4.8], [4.2, 5.6], [0.3, 5.0]],
        "ceiling": {"type": "shed", "height_m": 2.7, "peak_m": 3.6, "axis_deg": 90},
        "materials": TREATED,
    },
}  # fmt: skip
ROOM_SOURCE = "provisional: model knowledge (demo rooms, docs/ROOM_LOOP_PLAN.md R6)"

# Gains with headroom: the vocal spot sees ~102 dB SPL (34 dB on the V76 peaked +2.7 dBFS,
# into its clip), the guitar spot ~98 (40 dB on the clean preamp met its +-12.7 V swing).
VOCAL = {"chain": "u47_v76", "set": {"pattern_u47": 0, "gain_db_v76": 24}}
GUITAR = {"chain": "omni_clean", "set": {"gain_db_clean": 30}}
OMNI = {"chain": "omni_clean", "set": {"gain_db_clean": 40}}


def layout(room: dict) -> tuple[list[dict], list[dict]]:
    """Sources and mics placed about the floor's centroid: the vocal and the guitar 2.2 m
    apart, the piano 2 m behind them, each spot 0.3 m toward the other source, the room
    pair out front 2.6 m (4 m in the hall)."""
    floor = np.array(room["floor_m"], float)
    cx, cy = floor.mean(0)
    hall = room["ceiling"]["height_m"] > 4
    out = 4.0 if hall else 2.6
    v, g, p = (
        (cx - 1.1, cy - 0.8, 1.6),
        (cx + 1.1, cy - 0.8, 1.0),
        (cx, cy - 2.6 + (0.6 if not hall else 0), 1.0),
    )
    sources = [
        {"name": "vocal", "position_m": list(v), "spl_db": 92, "stem": "17_LeadVox"},
        {"name": "guitar", "position_m": list(g), "spl_db": 88, "stem": "11_AcousticGtr2"},
        {"name": "piano", "position_m": list(p), "spl_db": 90, "stem": "15_Piano"},
    ]  # fmt: skip

    def spot(src, other, chain, name, pan):
        s, o = np.array(src), np.array(other)
        d = (o - s)[:2] / np.linalg.norm((o - s)[:2])
        pos = s + 0.3 * np.r_[d, 0]
        back = s - pos
        return {
            "name": name, "position_m": pos.round(3).tolist(),
            "aim": {"azimuth_deg": round(float(np.degrees(np.arctan2(back[1], back[0]))), 2)},
            **chain, "pan": pan,
        }  # fmt: skip

    mics = [
        spot(v, g, VOCAL, "vocal spot", -0.1),
        spot(g, v, GUITAR, "guitar spot", 0.45),
    ]
    for name, dx, pan in (("room L", -0.5, -1.0), ("room R", 0.5, 1.0)):
        mics.append(
            {"name": name, "position_m": [cx + dx, cy + out - 0.8, 2.2 if not hall else 3.0],
             "aim": {"azimuth_deg": -90, "elevation_deg": -15}, **OMNI, "pan": pan}
        )  # fmt: skip
    return sources, mics


def _lufs(x: np.ndarray, fs: int) -> float:
    import pyloudnorm

    return float(pyloudnorm.Meter(fs).integrated_loudness(x.T if x.ndim == 2 else x))


def _norm(x: np.ndarray, fs: int) -> np.ndarray:
    return x * 10 ** ((LUFS - _lufs(x, fs)) / 20)


NOTES = {
    "shoebox": "Parallel walls and a flat ceiling: the early reflections arrive in a regular "
    "pattern (the floor / ceiling pair, the wall pairs); a faint flutter at ~15 ms in the tail "
    "(the furnished walls' scattering keeps it mild).",
    "angled": "The shoebox's volume, materials and RT, only the shape changed: the early "
    "reflections spread out in time and direction, the faint flutter gone. Expect a subtle "
    "difference: in a furnished room the walls' scattering already does much of what angling "
    "does. The A/B: shoebox/room_pair.wav against angled/room_pair.wav.",
    "splayed_gable": "Bigger (168 m^3) and taller in the middle: a little longer tail, smoother, "
    "the ceiling's reflections no longer arriving together.",
    "vaulted_hall": "A big hall (~990 m^3) with a hard plaster vault: a long, enveloping tail; "
    "the room pair is mostly room. Listen to how the spots stay close and the piano sits back.",
    "treated_studio": "Drapes, carpet and an acoustic-tile ceiling: dry. The spots are nearly the "
    "dry sources through their chains; the room pair is close and dull.",
}


def write_readme(summary: dict) -> None:
    rows = []
    for name in ROOMS:
        if name not in summary:
            continue
        r = summary[name]
        room = r["room"]
        ce = room["ceiling"]
        ceiling = ce["type"] + (
            f" {ce['height_m']:g} m" if ce["type"] == "flat"
            else f" {ce['height_m']:g} to {ce['peak_m']:g} m"
        )  # fmt: skip
        poly = PolyRoom(room["floor_m"], ce["type"], ce["height_m"], ce.get("peak_m"),
                        ce.get("axis_deg", 0.0), ce.get("facets", 8))  # fmt: skip
        rt = r["rt60_s"]
        rows.append(
            f"| `{name}/` | {len(room['floor_m'])} walls, {ceiling} | {poly.volume_m3():.0f} m^3 "
            f"| {rt['500']:.2f} / {rt['1000']:.2f} / {rt['4000']:.2f} | {NOTES.get(name, '')} |"
        )
    text = (
        """# Room shapes: a listening demo

Generated by `scripts/room_demo.py` (docs/ROOM_LOOP_PLAN.md R6). One performance, David Tyo's
"Long Way Home" (Cambridge-MT multitrack: lead vocal, acoustic guitar, piano; educational use),
recorded in each room through the same mics: the vocal on the **U47 -> V76** (cardioid, 0.3 m),
the guitar on the **clean small omni** (0.3 m), no spot on the piano (2 m behind them: heard
only through the room), and a **spaced pair of clean omnis** out in the room.

Every file is at -18 LUFS, so turn nothing up or down between them.

- `dry.wav`: the three stems summed, no room, no mics (the reference).
- `<room>/mix.wav`: the spots near the centre / right, the room pair hard left and right, 6 dB
  under the spots. What a session would sound like.
- `<room>/room_pair.wav`: the room mics alone: the room itself. The clearest way to hear shape.
- `<room>/*.wav`: each mic's print (its chain's level).

| Folder | Shape | Volume | RT60 500 / 1k / 4k Hz (s) | Listen for |
|---|---|---|---|---|
"""
        + "\n".join(rows)
        + """

Suggested order: `dry.wav`, then `shoebox/room_pair.wav` against `angled/room_pair.wav` (the
shape alone), then the mixes from `treated_studio` (dry) to `vaulted_hall` (wet).

How it is made: every room through `varimu/rooms/polyroom.py` (image sources up to four
reflections, each path checked against the walls; the tail's level and decay ray-traced from
the shape), each mic's two capsule entries through its body's diffraction, the chains
simulated at production (`varimu/rooms/scene.py`).
"""
    )
    (OUT / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    import soundfile as sf

    from varimu.sim.io import load_audio

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--stems", type=Path, default=STEMS)
    ap.add_argument("--readme", action="store_true", help="only rewrite README.md")
    ap.add_argument("--wave", type=float, help="the wave solver below this (Hz)")
    ap.add_argument("--out", type=Path, help="the output folder (default reports/rooms/demo)")
    args = ap.parse_args()
    global OUT
    if args.out:
        OUT = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    if args.readme:
        write_readme(json.loads((OUT / "demo.json").read_text()))
        return
    OUT.mkdir(parents=True, exist_ok=True)
    fs = 96000
    clips = OUT / "sources"
    clips.mkdir(exist_ok=True)
    sources0, _ = layout(ROOMS["shoebox"])
    dry = []
    for s in sources0:
        x = load_audio(args.stems / f"{s['stem']}.wav", fs)[: int(args.seconds * fs)]
        sf.write(clips / f"{s['name']}.wav", x.astype("<f4"), fs, subtype="FLOAT")
        dry.append(x * 10 ** ((s["spl_db"] - 90) / 20) / np.sqrt(np.mean(x**2)))
    d = np.sum(dry, axis=0)
    sf.write(OUT / "dry.wav", _norm(np.stack([d, d]), fs).T.astype("<f4"), fs, subtype="FLOAT")

    summary = json.loads((OUT / "demo.json").read_text()) if (OUT / "demo.json").exists() else {}
    for name, room in ROOMS.items():
        if args.only and name not in args.only:
            continue
        sources, mics = layout(room)
        ce = room["ceiling"]
        poly = PolyRoom(room["floor_m"], ce["type"], ce["height_m"], ce.get("peak_m"),
                        ce.get("axis_deg", 0.0))  # fmt: skip
        for item in sources + mics:
            assert poly.inside(np.array(item["position_m"])), (name, item["name"])
        scene = {
            "name": f"demo_{name}",
            "room": {**room, "source": ROOM_SOURCE},
            "sources": [
                {
                    "name": s["name"],
                    "clip": str(clips / f"{s['name']}.wav"),
                    "spl_db": s["spl_db"],
                    "position_m": s["position_m"],
                }
                for s in sources
            ],  # fmt: skip
            "mics": mics,
            "settings": {"quality": "production", "seed": 0,
                         "wave_crossover_hz": args.wave},
        }  # fmt: skip
        d = OUT / name
        print("render", name, flush=True)
        res = render(load_scene(scene), d, log=lambda s: None)
        hot = [m["name"] for m in res["mics"] if m["peak_dbfs"] > -3.5]
        if hot:
            print(f"  warning: {hot} peak within 3.5 dB of full scale", flush=True)
        tracks = {m["name"]: sf.read(d / m["file"])[0] for m in res["mics"]}
        n = max(len(y) for y in tracks.values())
        tracks = {k: np.pad(y, (0, n - len(y))) for k, y in tracks.items()}
        pans = {m["name"]: m["pan"] for m in res["mics"]}

        def stereo(names, gains, tracks=tracks, pans=pans, n=n):
            acc = np.zeros((2, n))
            for k in names:
                gl, gr = balance(pans[k])
                acc += gains[k] * np.stack([gl * tracks[k], gr * tracks[k]])
            return acc

        # spots each at the same loudness, the room pair 6 dB under the spots
        g = {k: 10 ** ((-23 - _lufs(tracks[k], fs)) / 20) for k in ("vocal spot", "guitar spot")}
        spots = stereo(["vocal spot", "guitar spot"], g)
        room_pair = stereo(["room L", "room R"], {"room L": 1.0, "room R": 1.0})
        rg = 10 ** ((_lufs(spots, fs) - 6 - _lufs(room_pair, fs)) / 20)
        mix = spots + rg * room_pair
        sf.write(d / "mix.wav", _norm(mix, fs).T.astype("<f4"), fs, subtype="FLOAT")
        sf.write(d / "room_pair.wav", _norm(room_pair, fs).T.astype("<f4"), fs, subtype="FLOAT")
        summary[name] = {
            "rt60_s": res["rt60_s"],
            "peaks_dbfs": {m["name"]: m["peak_dbfs"] for m in res["mics"]},
            "room": room,
            "files": ["mix.wav", "room_pair.wav"] + [m["file"] for m in res["mics"]],
            "wall_s": res["wall_s"],
        }
        (OUT / "demo.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(name, "RT60", res["rt60_s"], f"{res['wall_s']} s", flush=True)
        write_readme(summary)


if __name__ == "__main__":
    main()

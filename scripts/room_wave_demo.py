"""A listening demo of the wave solver and a material per wall (docs/ROOM_LOOP_PLAN.md R7, R10)
-> reports/rooms/wave_demo/.

    uv run --extra fast --extra listen python scripts/room_wave_demo.py [--seconds 20]
        [--only VARIANT ...] [--crossover 500]

The performance: the kick, the bass (as an amp on the floor) and the piano of David Tyo's
"Long Way Home" (Cambridge-MT multitrack, the user's copy; educational use, never committed),
from the start, each a point source (kick 92 dB SPL at 1 m, bass 90, piano 86), recorded by a
spaced pair of clean small omnis (`omni_clean`, 30 dB) 1 m apart out in the room, panned hard
left and right: the room as the bass hears it.

Variants (each `<variant>/room_pair.wav` at -18 LUFS):
- `small_geometric`, `small_wave`: a small room, 4.2 x 3.4 x 2.5 m, furnished: its modes are far
  apart (the lowest at 41, 50, 65 Hz), the geometric model alone against the wave solver below
  the crossover;
- `shoebox_geometric`, `shoebox_wave`: the 7 x 5.5 x 3.2 m live room the same way;
- `shoebox_dead_front` (R7, wave on): the shoebox with heavy drapes on the wall behind the
  players and plaster on the wall behind the pair (a "live end, dead end" room the other way
  round), against `shoebox_wave`.

`levels.png` and `levels.json`: each variant's third-octave levels at the pair (25 Hz-2 kHz).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT
from varimu.rooms.scene import balance, load_scene, render

STEMS = Path("D:/Audio files for mixing/DavidTyo_LongWayHome/DavidTyo_LongWayHome")
OUT = REPO_ROOT / "reports" / "rooms" / "wave_demo"
LUFS = -18.0
ROOM_SOURCE = "provisional: model knowledge (demo rooms, docs/ROOM_LOOP_PLAN.md R7 / R10)"
FURNISHED = {"walls": "furnished_wall", "floor": "wood_floor", "ceiling": "gypsum_on_studs"}
SMALL = {"floor_m": [[0, 0], [4.2, 0], [4.2, 3.4], [0, 3.4]],
         "ceiling": {"type": "flat", "height_m": 2.5}, "materials": FURNISHED}  # fmt: skip
SHOEBOX = {"floor_m": [[0, 0], [7, 0], [7, 5.5], [0, 5.5]],
           "ceiling": {"type": "flat", "height_m": 3.2}, "materials": FURNISHED}  # fmt: skip
DEAD_FRONT = {
    **SHOEBOX,
    "materials": {**FURNISHED, "faces": {"wall 0": "heavy_drapes", "wall 2": "plaster"}},
}
VARIANTS = {
    "small_geometric": (SMALL, False),
    "small_wave": (SMALL, True),
    "shoebox_geometric": (SHOEBOX, False),
    "shoebox_wave": (SHOEBOX, True),
    "shoebox_dead_front": (DEAD_FRONT, True),
}
STEM = {"kick": ("01_Kick", 92.0), "bass": ("09_Bass", 90.0), "piano": ("15_Piano", 86.0)}
PAIR = {"chain": "omni_clean", "set": {"gain_db_clean": 30}}
THIRDS_HZ = 1000 * 2 ** (np.arange(-16, 4) / 3)


def layout(room: dict) -> tuple[list[dict], list[dict]]:
    """The players in the front half (wall 0, y = 0, behind them), the pair facing them."""
    fl = np.array(room["floor_m"], float)
    w, d = fl[:, 0].max(), fl[:, 1].max()
    sources = [
        {"name": "kick", "position_m": [0.42 * w, 0.30 * d, 0.4]},
        {"name": "bass", "position_m": [0.66 * w, 0.24 * d, 0.45]},
        {"name": "piano", "position_m": [0.30 * w, 0.18 * d, 1.0]},
    ]
    y = 0.30 * d + min(2.2, 0.45 * d)
    mics = [
        {"name": name, "position_m": [0.5 * w + dx, y, 1.6],
         "aim": {"azimuth_deg": -90}, **PAIR, "pan": pan}
        for name, dx, pan in (("room L", -0.5, -1.0), ("room R", 0.5, 1.0))
    ]  # fmt: skip
    return sources, mics


def _lufs(x: np.ndarray, fs: int) -> float:
    import pyloudnorm

    return float(pyloudnorm.Meter(fs).integrated_loudness(x.T if x.ndim == 2 else x))


def thirds_db(x: np.ndarray, fs: int) -> list[float]:
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / fs)
    out = []
    for fc in THIRDS_HZ:
        sel = (f >= fc / 2 ** (1 / 6)) & (f < fc * 2 ** (1 / 6))
        out.append(round(float(10 * np.log10(spec[sel].sum() + 1e-30)), 2))
    return out


def main() -> None:
    import soundfile as sf

    from varimu.sim.io import load_audio

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--crossover", type=float, default=500.0)
    ap.add_argument("--stems", type=Path, default=STEMS)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fs = 96000
    clips = OUT / "sources"
    clips.mkdir(exist_ok=True)
    dry = []
    for name, (stem, spl) in STEM.items():
        x = load_audio(args.stems / f"{stem}.wav", fs)[: int(args.seconds * fs)]
        sf.write(clips / f"{name}.wav", x.astype("<f4"), fs, subtype="FLOAT")
        dry.append(x * 10 ** ((spl - 90) / 20) / np.sqrt(np.mean(x**2)))
    d = np.sum(dry, axis=0)
    d = np.stack([d, d])
    sf.write(OUT / "dry.wav", (d * 10 ** ((LUFS - _lufs(d, fs)) / 20)).T.astype("<f4"), fs,
             subtype="FLOAT")  # fmt: skip
    levels_path = OUT / "levels.json"
    levels = json.loads(levels_path.read_text()) if levels_path.exists() else {}
    for variant, (room, wave_on) in VARIANTS.items():
        if args.only and variant not in args.only:
            continue
        sources, mics = layout(room)
        scene = {
            "name": f"wave_demo_{variant}",
            "room": {**room, "source": ROOM_SOURCE},
            "sources": [{**s, "clip": str(clips / f"{s['name']}.wav"), "spl_db": STEM[s["name"]][1]}
                        for s in sources],  # fmt: skip
            "mics": mics,
            "settings": {"quality": "production", "seed": 0,
                         "wave_crossover_hz": args.crossover if wave_on else None},
        }  # fmt: skip
        out = OUT / variant
        print("render", variant, flush=True)
        res = render(load_scene(scene), out, log=lambda s: print("  ", s, flush=True)
                     if not s.startswith("progress") else None)  # fmt: skip
        tr = {m["name"]: sf.read(out / m["file"])[0] for m in res["mics"]}
        n = max(len(y) for y in tr.values())
        pair = np.zeros((2, n))
        for m in res["mics"]:
            gl, gr = balance(m["pan"])
            y = np.pad(tr[m["name"]], (0, n - len(tr[m["name"]])))
            pair += np.stack([gl * y, gr * y])
        g = 10 ** ((LUFS - _lufs(pair, fs)) / 20)
        sf.write(out / "room_pair.wav", (g * pair).T.astype("<f4"), fs, subtype="FLOAT")
        levels[variant] = {
            "thirds_hz": [round(float(f), 1) for f in THIRDS_HZ],
            "db": thirds_db(g * pair.sum(0), fs),
            "rt60_s": res["rt60_s"],
            "wall_s": res["wall_s"],
            "peaks_dbfs": {m["name"]: m["peak_dbfs"] for m in res["mics"]},
        }
        levels_path.write_text(json.dumps(levels, indent=1), encoding="utf-8")
        print(variant, res["wall_s"], "s", levels[variant]["peaks_dbfs"], flush=True)
    plot(levels)


def plot(levels: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, room in zip(axes, ("small", "shoebox"), strict=True):
        for v, lv in levels.items():
            if not v.startswith(room):
                continue
            ax.semilogx(lv["thirds_hz"], lv["db"], marker="o", ms=3, label=v)
        ax.set_title(f"{room}: the room pair, third octaves (-18 LUFS)")
        ax.set_xlabel("Hz")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend()
    axes[0].set_ylabel("dB")
    fig.tight_layout()
    fig.savefig(OUT / "levels.png", dpi=110)


if __name__ == "__main__":
    main()

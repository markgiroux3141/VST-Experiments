"""The virtual head in a room (docs/BINAURAL_PLAN.md B4): sources placed round a head in one
of the room presets (config/rooms/), the room engine's image sources, diffraction and
diffuse tail each reaching each ear through its HRTF from its own direction
(varimu.binaural.room) -> reports/binaural/listen/rooms/<scene>_<room>_<head>.wav (96 kHz
stereo float32, -20 LUFS, left = left ear).

Scenes (positions as azimuth from the nose, counter-clockwise = to the left, and distance):
- band: "Did she mention my name"'s stems round the listener, lead vocal in front (0 deg,
  1.5 m), guitar back-left (135 deg, 2 m), harmonies straight behind (180 deg, 2 m), bass to
  the right (-90 deg, 2 m); 20 s from the loudest part.
- tour: pink-noise bursts at 2 m going clockwise from the front, 45 deg apart (as
  binaural_demo.py's tour, without the elevations), then front-left 30 / back-left 150
  alternating four times.

The head's ears are 1.2 m above the floor (seated), at the room's centre, facing +x.

    uv run --extra fast --extra binaural --extra listen python scripts/binaural_room.py \\
        [--scenes band tour] [--rooms treated_studio stone_chapel] [--heads pp1]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from binaural_demo import FS, _read, load_head, normalize, pink  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "binaural" / "listen" / "rooms"
STEMS = ROOT / "stems" / "Did she mention my name" / "full"
EAR_HEIGHT_M = 1.2


def room_of(name: str):
    from varimu.rooms.scene import load_scene

    sc = load_scene({"name": "x", "room": {"preset": name}, "sources": [], "mics": []})
    return sc.room


def centre_of(room) -> np.ndarray:
    if hasattr(room, "floor"):
        c = room.floor.mean(axis=0)
    else:
        c = 0.5 * np.asarray(room.dims_m[:2])
    return np.array([c[0], c[1], EAR_HEIGHT_M])


def band_sources() -> list[tuple[str, float, float, np.ndarray]]:
    names = {
        "lead vocal": (0, 1.5),
        "guitar": (135, 2.0),
        "harmonies": (180, 2.0),
        "bass": (-90, 2.0),
    }
    xs = {}
    for n in names:
        x, fs = sf.read(STEMS / f"{n}.wav", dtype="float64", always_2d=True)
        xs[n] = x.mean(1)
    mix = sum(xs.values())
    seconds = 20.0
    w = int(seconds * fs)
    cs = np.concatenate([[0.0], np.cumsum(mix**2)])
    lo = int(np.argmax(cs[w:] - cs[:-w]))
    from fractions import Fraction

    from scipy.signal import resample_poly

    q = Fraction(FS, int(fs)).limit_denominator(1000)
    out = []
    for n, (az, d) in names.items():
        y = resample_poly(xs[n][lo : lo + w], q.numerator, q.denominator)
        r = int(0.02 * FS)
        y[:r] *= np.linspace(0, 1, r)
        y[-r:] *= np.linspace(1, 0, r)
        out.append((n, az, d, y))
    return out


def tour_sources():
    bursts = []
    for k in range(3):
        b = pink(int(0.25 * FS), 100 + k)
        r = int(0.005 * FS)
        b[:r] *= np.linspace(0, 1, r)
        b[-r:] *= np.linspace(1, 0, r)
        bursts += [b, np.zeros(int(0.06 * FS))]
    x = np.concatenate(bursts)
    slot = len(x) + int(0.9 * FS)  # the room's tail between positions
    order = [0, -45, -90, -135, 180, 135, 90, 45] + [30, 150] * 4
    out = []
    for k, az in enumerate(order):
        y = np.zeros(slot * len(order))
        y[k * slot : k * slot + len(x)] = x
        out.append((f"pos{k}_{az}", az, 2.0, y))
    # one source per distinct position: sum the slots that share it
    merged: dict[float, list] = {}
    for n, az, d, y in out:
        if az in merged:
            merged[az][3] = merged[az][3] + y
        else:
            merged[az] = [n, az, d, y]
    return [tuple(v) for v in merged.values()]


def render(scene: str, room_name: str, head_name: str) -> Path:
    from varimu.binaural.room import head_mics
    from varimu.rooms import shoebox

    room = room_of(room_name)
    centre = centre_of(room)
    srcs = band_sources() if scene == "band" else tour_sources()
    pos = [
        centre + d * np.array([np.cos(np.radians(az)), np.sin(np.radians(az)), 0.0])
        for _, az, d, _ in srcs
    ]
    head = load_head(head_name)
    mics = head_mics(head, centre, facing_deg=0.0)
    t0 = time.perf_counter()
    h = shoebox.responses(room, pos, mics, FS, log=print)
    print(f"  room responses {h.shape} in {time.perf_counter() - t0:.0f} s")
    from scipy.signal import fftconvolve

    n = max(len(s[3]) for s in srcs) + h.shape[-1]
    y = np.zeros((2, n))
    for si, (_, _, _, x) in enumerate(srcs):
        for e in range(2):
            c = fftconvolve(x, h[si, e, 0])
            y[e, : len(c)] += c
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{scene}_{room_name}_{head_name}.wav"
    sf.write(path, normalize(y).T.astype(np.float32), FS)
    print(f"{scene} in {room_name} through {head_name}: {path}")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenes", nargs="*", default=["band", "tour"])
    ap.add_argument("--rooms", nargs="*", default=["treated_studio", "stone_chapel"])
    ap.add_argument("--heads", nargs="*", default=["pp1"])
    args = ap.parse_args(argv)
    for s in args.scenes:
        for r in args.rooms:
            for h in args.heads:
                render(s, r, h)


if __name__ == "__main__":
    _ = _read
    main()

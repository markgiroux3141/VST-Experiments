"""The separation plan's cheap first experiment (docs/SEPARATION_PLAN.md).

    uv run --extra listen --extra fast python scripts/separation_study.py [--jobs 3]
        [--only AXIS ...]

Two tube-synth lines in the same register (the target, a melody, and the masker, an
arpeggio; one patch, the worst case), plus the target with one note changed (for the
listening staircase, scripts/separation_listen.py). Each goes through a chain per
condition; each processed track is matched to -23 LUFS on its own; then:

- axis `devices`: the 670 (factory adjustment), the EQP-1A (a boost / cut setting), the
  5E3 through its speaker (sound pressure at 1 m), same chain on both or different;
- axis `flutter`: a record pass's wow and flutter (varimu.separation.flutter): one shared
  pass, independent passes, the target or the masker only;
- axis `room`: image-source rooms (varimu.separation.room), near (0.3 m) / far (2.5 m) in a
  home room, and the booth against a live hall.

Per condition: the target's glimpse proportion at -6 dB under the masker, and the
energetic separation in dB (how far the target can drop and keep the dry pair's
proportion at -6 dB). Grouping cues (flutter, onsets) don't show in it; the staircase
measures them.
-> reports/separation/summary.json; audio in cache/separation/conditions/<name>/
   (target.wav, target_changed.wav, masker.wav, demo_-6db.wav).
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.separation import flutter, metrics, phrases, room
from varimu.sim import io, runner

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "separation"
AUDIO_DIR = ROOT / "cache" / "separation" / "conditions"

BPM = 100.0
SECONDS = 6.5
PANEL = {"cutoff": 0.6, "resonance": 0.3, "attack": 0.05, "release": 0.25, "wave": 0.7}
# A3-G4. The target: a melody; the changed note is the 7th (D4 -> E4, beat 4).
TARGET: list[phrases.Note] = [
    (57, 0.0, 0.9),
    (60, 1.0, 0.45),
    (62, 1.5, 0.45),
    (64, 2.0, 0.9),
    (67, 3.0, 0.9),
    (64, 4.0, 0.45),
    (62, 4.5, 0.45),
    (60, 5.0, 0.9),
    (62, 6.0, 0.9),
    (64, 7.0, 0.45),
    (60, 7.5, 0.45),
    (57, 8.0, 1.6),
]
CHANGED_INDEX = 6
CHANGED_KEY = 64
# The masker: eighth-note arpeggios (Am, F, C, G) in the same octave, offbeat to the
# melody's quarter notes half the time.
_CHORDS = [(57, 60, 64), (53, 57, 60), (55, 60, 64), (55, 59, 62)]
MASKER: list[phrases.Note] = [(_CHORDS[(i // 4) % 4][i % 3], 0.5 * i, 0.4) for i in range(19)]
INPUT_PEAK_DBFS = -12.0  # each source into a device

DEVICES = {
    "670": (None, {}),
    "eqp1a": (
        "pultec_eqp1a",
        {
            "lf_freq_hz": 100,
            "lf_boost": 0.5,
            "lf_atten": 0.3,
            "hf_boost_freq_khz": 5,
            "hf_boost": 0.4,
            "bandwidth": 0.6,
            "hf_atten": 0.5,
            "hf_atten_freq_khz": 10,
        },
    ),
    "5e3": ("fender_5e3", {"volume_bright": 0.5, "tone": 0.6}),
}

NEAR, FAR = ((2.0, 2.0, 1.2), (2.0, 2.3, 1.2)), ((2.0, 2.0, 1.2), (4.3, 1.2, 1.5))


def conditions() -> dict[str, dict]:
    """name -> {axis, target, masker}: each side a list of steps ("dev:670",
    "flutter:SEED", "room:ROOM:near|far")."""
    c: dict[str, dict] = {"dry": {"axis": "baseline", "target": [], "masker": []}}
    for a in DEVICES:
        c[f"both_{a}"] = {"axis": "devices", "target": [f"dev:{a}"], "masker": [f"dev:{a}"]}
    for a in DEVICES:
        for b in DEVICES:
            if a != b:
                c[f"T{a}_M{b}"] = {
                    "axis": "devices",
                    "target": [f"dev:{a}"],
                    "masker": [f"dev:{b}"],
                }
    c["flutter_shared"] = {"axis": "flutter", "target": ["flutter:1"], "masker": ["flutter:1"]}
    c["flutter_independent"] = {"axis": "flutter", "target": ["flutter:1"], "masker": ["flutter:2"]}
    c["flutter_target_only"] = {"axis": "flutter", "target": ["flutter:1"], "masker": []}
    c["flutter_masker_only"] = {"axis": "flutter", "target": [], "masker": ["flutter:2"]}
    c["flutter_independent_x4"] = {
        "axis": "flutter",
        "target": ["flutter:1:4"],
        "masker": ["flutter:2:4"],
    }
    c["room_both_near"] = {
        "axis": "room",
        "target": ["room:home:near"],
        "masker": ["room:home:near"],
    }
    c["room_both_far"] = {"axis": "room", "target": ["room:home:far"], "masker": ["room:home:far"]}
    c["room_Tnear_Mfar"] = {
        "axis": "room",
        "target": ["room:home:near"],
        "masker": ["room:home:far"],
    }
    c["room_Tfar_Mnear"] = {
        "axis": "room",
        "target": ["room:home:far"],
        "masker": ["room:home:near"],
    }
    c["room_Tbooth_Mhall"] = {
        "axis": "room",
        "target": ["room:booth:near"],
        "masker": ["room:hall:far"],
    }
    c["room_Thall_Mbooth"] = {
        "axis": "room",
        "target": ["room:hall:far"],
        "masker": ["room:booth:near"],
    }
    return c


def sources(fs: int, jobs: int) -> dict[str, np.ndarray]:
    changed = list(TARGET)
    k, start, length = changed[CHANGED_INDEX]
    changed[CHANGED_INDEX] = (CHANGED_KEY, start, length)
    lines = {"target": TARGET, "target_changed": changed, "masker": MASKER}
    with ThreadPoolExecutor(max_workers=min(jobs, 3)) as ex:
        futs = {
            k: ex.submit(phrases.render, v, bpm=BPM, seconds=SECONDS, panel=PANEL)
            for k, v in lines.items()
        }
        out = {k: f.result() for k, f in futs.items()}
    # One gain for all three (the changed target stays as loud as the target).
    peak = max(np.abs(v).max() for v in out.values())
    g = 10 ** (INPUT_PEAK_DBFS / 20) / peak
    return {k: v * g for k, v in out.items()}


def device_renders(
    src: dict[str, np.ndarray], needed: set[str], jobs: int
) -> dict[tuple[str, str], np.ndarray]:
    settings = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production")
    keys = [(d, k) for d in sorted(needed) for k in src]
    rjobs = [
        runner.RenderJob(
            samples=src[k],
            overrides=DEVICES[d][1],
            label=f"separation {d} {k}",
            circuit=DEVICES[d][0],
        )
        for d, k in keys
    ]
    done = runner.render_many(rjobs, settings=settings, max_jobs=jobs)
    return {key: r.output for key, r in zip(keys, done, strict=True)}


def chain(
    x: np.ndarray, steps: list[str], name: str, fs: int, devs: dict, rirs: dict
) -> np.ndarray:
    y = x
    for st in steps:
        kind, *args = st.split(":")
        if kind == "dev":
            y = devs[(args[0], name)]
        elif kind == "flutter":
            scale = float(args[1]) if len(args) > 1 else 1.0
            y = flutter.apply(y, fs, int(args[0]), flutter.TOTAL_RMS * scale)
        elif kind == "room":
            h = rirs[(args[0], args[1])]
            y = _fftconv(y, h, len(y) + int(1.5 * fs))
        else:
            raise ValueError(st)
    return y


def _fftconv(x: np.ndarray, h: np.ndarray, n: int) -> np.ndarray:
    from scipy.signal import fftconvolve

    return fftconvolve(x, h)[:n]


def same_length(xs: list[np.ndarray]) -> list[np.ndarray]:
    n = max(len(x) for x in xs)
    return [np.pad(x, (0, n - len(x))) for x in xs]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--jobs", type=int, default=3, help="parallel renders (another session may need the CPU)"
    )
    ap.add_argument("--only", nargs="*", help="axes: devices flutter room")
    a = ap.parse_args()

    fs = io.TransientSettings.from_sim_settings(engine="circuitsim").sample_rate
    conds = conditions()
    if a.only:
        conds = {k: v for k, v in conds.items() if v["axis"] in ("baseline", *a.only)}
    src = sources(fs, a.jobs)
    print("sources rendered")

    steps = [s for c in conds.values() for side in ("target", "masker") for s in c[side]]
    needed = {s.split(":")[1] for s in steps if s.startswith("dev:")}
    devs = device_renders(src, needed, a.jobs) if needed else {}
    if needed:
        print("device renders done")
    rirs = {}
    for s in steps:
        if s.startswith("room:"):
            _, rname, where = s.split(":")
            if (rname, where) not in rirs:
                pos = NEAR if where == "near" else FAR
                rirs[(rname, where)] = room.impulse_response(room.ROOMS[rname], *pos, fs)

    rows = {}
    ref: dict[str, float] = {}
    dry = np.pad(src["target"], (0, int(1.5 * fs)))
    for name, c in conds.items():
        t = chain(src["target"], c["target"], "target", fs, devs, rirs)
        tc = chain(src["target_changed"], c["target"], "target_changed", fs, devs, rirs)
        m = chain(src["masker"], c["masker"], "masker", fs, devs, rirs)
        t, tc, m, notes = same_length([t, tc, m, dry])
        # One gain for the target and its changed copy: the target's.
        g_t = 10 ** ((metrics.TARGET_LUFS - metrics.loudness_lufs(t, fs)) / 20)
        t, tc, m = t * g_t, tc * g_t, metrics.match_loudness(m, fs)
        row = {"axis": c["axis"], "target": c["target"], "masker": c["masker"]}
        # "all": every cell the processed target fills; "notes": only the dry target's cells.
        for kind, mask in (("all", None), ("notes", notes)):
            prop = metrics.glimpse_proportion(t * 10 ** (-6 / 20), m, fs, notes=mask)
            if name == "dry":
                ref[kind] = prop
            level = metrics.level_for_proportion(t, m, fs, ref[kind], notes=mask)
            row[f"glimpse_{kind}_at_-6db"] = round(prop, 4)
            row[f"energetic_{kind}_db"] = round(-6.0 - level, 2)
        rows[name] = row
        d = AUDIO_DIR / name
        d.mkdir(parents=True, exist_ok=True)
        for fname, x in (("target", t), ("target_changed", tc), ("masker", m)):
            sf.write(d / f"{fname}.wav", x.astype(np.float32), fs, subtype="FLOAT")
        demo = t * 10 ** (-6 / 20) + m
        sf.write(
            d / "demo_-6db.wav",
            (demo / max(1.0, np.abs(demo).max() * 1.12)).astype(np.float32),
            fs,
            subtype="FLOAT",
        )
        print(
            f"{name:24s} energetic: all cells {row['energetic_all_db']:+6.2f} dB, "
            f"the notes' cells {row['energetic_notes_db']:+6.2f} dB"
        )

    summary = {
        "sample_rate": fs,
        "bpm": BPM,
        "panel": PANEL,
        "input_peak_dbfs": INPUT_PEAK_DBFS,
        "devices": {
            k: {"circuit": v[0] or "fairchild_670", "set": v[1]} for k, v in DEVICES.items()
        },
        "rooms": {
            k: {
                "dims_m": r.dims_m,
                "rt60_s": dict(
                    zip(map(int, room.BANDS_HZ), np.round(r.rt60_s(), 3).tolist(), strict=True)
                ),
                "source": r.source,
            }
            for k, r in room.ROOMS.items()
        },
        "positions_m": {"near": NEAR, "far": FAR},
        "flutter": {"total_rms": flutter.TOTAL_RMS, "source": flutter.TOTAL_RMS_SOURCE},
        "measure": (
            "glimpse proportion at the target -6 dB under the masker (each at -23 LUFS); "
            "energetic separation: dB the target can drop and keep the dry pair's "
            "proportion at -6 dB. 'all': every cell the processed target fills; 'notes': "
            "only the cells where the dry target was (new harmonics, reverb tails between "
            "notes don't count)"
        ),
        "conditions": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=1))
    print(f"-> {OUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()

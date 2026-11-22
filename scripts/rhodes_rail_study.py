"""The tone bar rail as a coupling between the keys, studied offline (varimu/rhodes/rail.py;
docs/RHODES_IMPERFECTION_PLAN.md, "Notes depending on each other").

    uv run --extra fast --extra listen python scripts/rhodes_rail_study.py [--stiffness 1 4 16]

For each rail stiffness (a factor on `rail.Rail`'s plank EI; the plank's values are all
provisional), the harp's EMF (circuitsim isn't involved: varimu/rhodes/harp.py's voices) on a
rigid rail and on the moving rail, in two scenes:

- **thump**: F1, E2 and A2 struck alone at velocity 120, pedal up, 2.5 s apart (jRhodes3d's
  loudest layer's centre): SC4's measure (scripts on the branch rhodes-realism,
  reports/rhodes/attack/ there), the band under 0.7 f0 over the first 50 ms re the whole
  signal in that window, against the real piano's (SC4: F1 -16.3, E2 -20.0, A2 -23.7 dB at L1;
  ours rigid -26 to -27);
- **pedal**: rhodes_render.py's demo progression with the pedal: the keys never struck (the
  sympathetic ring) alone, re the whole, and how much the struck keys' own sound moves.

Writes reports/rhodes/imperfection/rail/: summary.json and WAVs (each scene rigid and on the
rail, matched to -23 LUFS together, i.e. one gain for the pair, and the sympathetic keys alone at
the pair's gain), 48 kHz.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
from pathlib import Path

import numpy as np
from scipy import signal

from varimu.rhodes import midi
from varimu.rhodes import rail as rl
from varimu.separation.metrics import loudness_lufs
from varimu.sim.io import write_audio

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "rhodes" / "imperfection" / "rail"
FS = 48000.0
REAL_THUMP_DB = {29: -16.3, 40: -20.0, 45: -23.7}  # SC4, jRhodes3d L1


def thump_db(y: np.ndarray, t_on: float, f0: float) -> float:
    sos = signal.butter(4, 0.7 * f0, "lowpass", fs=FS, output="sos")
    lo = signal.sosfiltfilt(sos, y)
    a, b = int((t_on - 0.005) * FS), int((t_on + 0.05) * FS)
    r = np.sqrt(np.mean(lo[a:b] ** 2)) / np.sqrt(np.mean(y[a:b] ** 2))
    return float(20 * np.log10(r))


def thump_events() -> list[midi.Event]:
    ev = []
    for i, n in enumerate(REAL_THUMP_DB):
        t = 0.1 + 2.5 * i
        ev += [midi.Event(t, "on", n, 120), midi.Event(t + 2.0, "off", n, 0)]
    return ev


def pedal_events() -> list[midi.Event]:
    spec_ = importlib.util.spec_from_file_location("rr", ROOT / "scripts" / "rhodes_render.py")
    rr = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(rr)
    ev = [e for e in rr.demo_events() if e.t_s < 10.7]  # the four pedalled bars
    return ev


def db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-30))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stiffness", type=float, nargs="*", default=[1.0, 4.0, 16.0])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict = {}
    for kf in args.stiffness:
        base = rl.Rail()
        r_ = dataclasses.replace(base, youngs_pa=base.youngs_pa * kf)
        tag = f"ei_x{kf:g}"
        res: dict = {"rail_modes_hz": None}
        for scene, events, dur in (
            ("thump", thump_events(), 7.6),
            ("pedal", pedal_events(), 13.0),
        ):
            print(f"{tag} {scene} ...", flush=True)
            r = rl.render(events, dur, rail=r_, fs_hz=FS)
            res["rail_modes_hz"] = r.rail_modes_hz[:8].round(1).tolist()
            gain = 10 ** ((-23 - loudness_lufs(r.rigid_v, FS)) / 20)
            write_audio(
                OUT / f"{scene}_{tag}_rigid.wav", (gain * r.rigid_v).astype(np.float32), int(FS)
            )
            write_audio(
                OUT / f"{scene}_{tag}_rail.wav", (gain * r.rail_v).astype(np.float32), int(FS)
            )
            write_audio(
                OUT / f"{scene}_{tag}_sympathetic.wav",
                (gain * r.sympathetic_v).astype(np.float32),
                int(FS),
            )
            own = r.rail_v - r.sympathetic_v
            out = {
                "sympathetic_re_whole_db": db(r.sympathetic_v) - db(r.rail_v),
                "struck_keys_moved_db": db(own - r.rigid_v) - db(r.rigid_v),
                "rail_peak_um": 1e6 * max(float(np.max(np.abs(u))) for u in r.u_m.values()),
                "force_peak_n": max(float(np.max(np.abs(f))) for f in r.forces_n.values()),
            }
            if scene == "thump":
                out["thump_db"] = {}
                for i, n in enumerate(REAL_THUMP_DB):
                    t = 0.1 + 2.5 * i
                    f0 = 440 * 2 ** ((n - 69) / 12)
                    out["thump_db"][n] = {
                        "rigid": round(thump_db(r.rigid_v, t, f0), 1),
                        "rail": round(thump_db(r.rail_v, t, f0), 1),
                        "real": REAL_THUMP_DB[n],
                    }
            res[scene] = out
            print(json.dumps(out), flush=True)
        summary[tag] = res
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

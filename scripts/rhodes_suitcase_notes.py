"""A jRhodes-style listening set through the whole Suitcase (docs/RHODES_PLAN.md "The
Suitcase"): single notes across the keyboard at three velocities, each through the harp, the
preamp (the vibrato on, at its fitted rate), the power amp and the speakers, the stereo
pressure 1 m in front of the front speakers.

    uv run --extra fast --with soundfile python scripts/rhodes_suitcase_notes.py
        [--quality production|draft] [--circuit rhodes_suitcase_100w] [--vibrato 0|1]

One MIDI file of 7 notes x 3 velocities (a note held 2.5 s, one every 4 s) is rendered once by
scripts/rhodes_render.py, then cut into one stereo WAV per note,
reports/rhodes/suitcase_notes/<note>_v<velocity>.wav (0 dBFS = the circuit's 25 Pa), with an
index in the same folder. The notes are jRhodes3d's: F1, E2, D3, C4, B4, A5, G6 (every fifth
of its 15, F1-C7: `real instrument samples/jrhodes3d_download/`, untracked), so a note of
this set sits beside the real sample of the same key (`rhodes_vs_jrhodes.py`).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varimu.rhodes import midi  # noqa: E402

OUT = ROOT / "reports" / "rhodes" / "suitcase_notes"
RENDERS = ROOT / "reports" / "rhodes" / "renders"
NOTES = [("F1", 29), ("E2", 40), ("D3", 50), ("C4", 60), ("B4", 71), ("A5", 81), ("G6", 91)]
VELOCITIES = (30, 75, 120)
HOLD_S = 2.5
SLOT_S = 4.0
LEAD_S = 0.3


def events() -> list[midi.Event]:
    ev: list[midi.Event] = []
    t = LEAD_S
    for _, n in NOTES:
        for v in VELOCITIES:
            ev.append(midi.Event(t, "on", n, v))
            ev.append(midi.Event(t + HOLD_S, "off", n, 0))
            t += SLOT_S
    return ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", default="production")
    ap.add_argument("--circuit", default="rhodes_suitcase_100w")
    ap.add_argument("--vibrato", type=int, default=1)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    RENDERS.mkdir(parents=True, exist_ok=True)
    name = f"suitcase_notes_{a.quality}"
    mid = RENDERS / f"{name}.mid"
    midi.write(mid, events())
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "rhodes_render.py"),
        "--midi",
        str(mid),
        "--circuit",
        a.circuit,
        "--quality",
        a.quality,
        "--tail",
        "1.5",
        "--out",
        name,
        "--set",
        f"vibrato={a.vibrato}",
    ]
    subprocess.run(cmd, check=True)
    y, fs = sf.read(RENDERS / f"{name}.wav", dtype="float32")
    index = []
    t = LEAD_S
    for label, n in NOTES:
        for v in VELOCITIES:
            i0, i1 = int((t - 0.05) * fs), int((t + SLOT_S - 0.05) * fs)
            seg = y[i0:i1]
            path = OUT / f"{label}_v{v:03d}.wav"
            sf.write(path, seg, fs, subtype="FLOAT")
            index.append(f"{path.name}: MIDI {n}, velocity {v}, peak {np.max(np.abs(seg)):.3f} FS")
            t += SLOT_S
    (OUT / "index.txt").write_text(
        f"quality {a.quality}, circuit {a.circuit}, vibrato {a.vibrato}\n" + "\n".join(index) + "\n"
    )
    print("\n".join(index))
    return 0


if __name__ == "__main__":
    sys.exit(main())

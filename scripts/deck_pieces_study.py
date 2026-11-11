"""The Ampex 300-4's print in pieces against one run (docs/PERIOD_GEAR_BACKLOG.md, PG1, MT5;
TAPE_SPEED_PLAN.md P3's measurement, scripts/chunk_351.py's, on the deck's four tracks).

Reads what `cargo run --release -p varimu-app --example tape_print -- --session DIR --measure
CHUNK_S --out DIR` wrote (each tape track printed in pieces of CHUNK_S and as one run, the
app's own print path, timed) and reports per tape track: the largest third-octave band
difference 50 Hz-15 kHz over the whole excerpt, the same in 200 ms windows around every seam,
each seam's waveform difference re the track's rms, and the floor between the two runs away
from the seams (the master oscillator's free phase and the grain's cells: two runs never agree
sample for sample, TAPE_PLAN.md "Speed").

    uv run python scripts/deck_pieces_study.py DIR   -> reports/multitrack/deck/pieces.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.config import REPO_ROOT

sys.path.insert(0, str(Path(__file__).parent))
from chunk_351 import bands_db  # noqa: E402

OUT = REPO_ROOT / "reports" / "multitrack" / "deck"
NAMES = ("bass", "guitar", "lead vocal", "harmonies")  # the session's assignment (MT6)


def db(x: float) -> float:
    return 20 * math.log10(x + 1e-30)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", type=Path)
    a = ap.parse_args()
    meta = json.loads((a.dir / "meta.json").read_text(encoding="utf-8"))
    fs = int(meta["rate"])
    chunk = round(meta["pieces"]["chunk_s"] * fs)
    late = round(meta["latency_s"] * fs)
    res: dict = {
        "source": str(a.dir),
        "audio_s": meta["audio_s"],
        "pieces": meta["pieces"],
        "tape_gpu": meta["tape_gpu"],
        "runs": meta["runs"],
    }
    tracks = {}
    for k in range(4):
        pc, wh = a.dir / f"pieces_tape{k + 1}.wav", a.dir / f"whole_tape{k + 1}.wav"
        if not (pc.exists() and wh.exists()):
            continue
        yc, _ = sf.read(pc)
        yw, _ = sf.read(wh)
        n = min(len(yc), len(yw))
        yc, yw = yc[:n], yw[:n]
        rms = float(np.sqrt(np.mean(yw**2)))
        r: dict = {
            "bands_whole_db": float(np.abs(bands_db(yc, fs) - bands_db(yw, fs)).max()),
            "level_dbfs_rms": db(rms),
        }
        seams = []
        # The pieces cut the circuit's input, which runs `late` ahead of the playback.
        for s0 in range(chunk, n + late, chunk):
            s_out = s0 - late
            lo, hi = s_out - int(0.1 * fs), s_out + int(0.1 * fs)
            if lo < 0 or hi > n:
                continue
            d = yc[lo:hi] - yw[lo:hi]
            bands = np.abs(bands_db(yc[lo:hi], fs) - bands_db(yw[lo:hi], fs))
            seams.append(
                {
                    "at_s": s_out / fs,
                    "bands_db": float(bands.max()),
                    "diff_db_re_rms": db(float(np.sqrt(np.mean(d**2))) / rms),
                    "peak_diff_db_re_rms": db(float(np.abs(d).max()) / rms),
                }
            )
        r["seams"] = seams
        w = int(0.2 * fs)
        floor = []
        for i in range(n // w):
            t = i * w + w // 2 + late
            if t < chunk or min(t % chunk, chunk - t % chunk) < 0.4 * fs:
                continue
            d = yc[i * w : (i + 1) * w] - yw[i * w : (i + 1) * w]
            floor.append(db(float(np.sqrt(np.mean(d**2))) / rms))
        if floor:
            r["mid_piece_diff_db_re_rms"] = {
                "median": float(np.median(floor)),
                "p90": float(np.percentile(floor, 90)),
                "max": float(np.max(floor)),
            }
        tracks[f"{k + 1} {NAMES[k]}"] = r
    res["tracks"] = tracks
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pieces.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

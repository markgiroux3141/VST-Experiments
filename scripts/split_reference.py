"""Split a reference record (one long file of a whole album) into its tracks at the silences
between them, and label each track's era (ANALOG_MAGIC_FABLE.md AM1 / AM3's corpora).

  uv run --extra listen python scripts/split_reference.py FILE --tracks 20 --name NAME
      [--eras 1-6:1960s 7-14:1970s 15-20:later]

-> cache/magic/reference/<NAME>/NN.wav (stereo float32 at 48 kHz) and tracks.json (start,
end, era per track). The gaps are the longest stretches of short-term level more than 45 dB
under the program's median, so `--tracks` must be the album's count (it picks that many - 1
gaps)."""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import soundfile as sf

from varimu.config import REPO_ROOT
from varimu.magic import fingerprints as fp

OUT = REPO_ROOT / "cache" / "magic" / "reference"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("--tracks", type=int, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--eras", nargs="*", default=[])
    a = ap.parse_args()
    info = sf.info(a.file)
    fs = info.samplerate
    hop = int(0.05 * fs)
    # Level per 50 ms, read in blocks (an album doesn't fit in memory as float64).
    lv = []
    with sf.SoundFile(a.file) as f:
        while True:
            b = f.read(hop * 1200, dtype="float32", always_2d=True)
            if not len(b):
                break
            m = b.mean(axis=1).astype(float)
            n = len(m) // hop
            ms = (m[: n * hop].reshape(n, hop) ** 2).mean(axis=1)
            lv.append(10 * np.log10(ms + 1e-20))
    lv = np.concatenate(lv)
    quiet = lv < np.median(lv) - 45
    # Runs of quiet blocks.
    runs = []
    i = 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if i > 0 and j < len(quiet):
                runs.append((j - i, i, j))
            i = j
        else:
            i += 1
    runs.sort(reverse=True)
    gaps = sorted(runs[: a.tracks - 1], key=lambda r: r[1])
    if len(gaps) < a.tracks - 1:
        print(f"only {len(gaps)} gaps found", file=sys.stderr)
        return 1
    cuts = [0] + [(g[1] + g[2]) // 2 for g in gaps] + [len(lv)]
    eras = {}
    for e in a.eras:
        rng, label = e.split(":")
        lo, hi = (int(v) for v in rng.split("-"))
        for k in range(lo, hi + 1):
            eras[k] = label
    out = OUT / a.name
    out.mkdir(parents=True, exist_ok=True)
    meta = {"source": str(a.file), "fs": fs, "tracks": []}
    with sf.SoundFile(a.file) as f:
        for k in range(a.tracks):
            s, e = cuts[k] * hop, cuts[k + 1] * hop
            f.seek(s)
            x = f.read(e - s, dtype="float64", always_2d=True)
            # Trim the silence at both ends.
            m = np.abs(x).max(axis=1)
            nz = np.flatnonzero(m > 10 ** (-60 / 20))
            if len(nz):
                x = x[nz[0] : nz[-1] + 1]
            y = fp.to_fs(x, fs)
            sf.write(
                out / f"{k + 1:02d}.wav", y.astype(np.float32), fp.ANALYSIS_FS, subtype="FLOAT"
            )
            meta["tracks"].append(
                {
                    "n": k + 1,
                    "start_s": s / fs,
                    "end_s": e / fs,
                    "seconds": len(y) / fp.ANALYSIS_FS,
                    "era": eras.get(k + 1),
                }
            )
            print(
                f"  {k + 1:02d}: {s / fs / 60:6.2f}-{e / fs / 60:6.2f} min, "
                f"{len(y) / fp.ANALYSIS_FS:5.0f} s, {eras.get(k + 1)}",
                flush=True,
            )
    (out / "tracks.json").write_text(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

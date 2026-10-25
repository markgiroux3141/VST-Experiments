"""Build program clips from multitrack stems (config/listening.yaml `mixes`).

    uv run --extra listen python scripts/build_clips.py --root DIR [--only NAME ...]

Each mix is a plain sum of its stems (static gain and polarity per stem, no other
processing), summed to mono at the stems' rate, then one gain so that its loudest
window of the pool's excerpt length reads MIX_LUFS integrated, lowered if a peak of
the whole clip would pass MIX_PEAK_DBFS. MIX_LUFS is the level of the two clips the
pool was first matched on (the arpeggio -13.5, the guitar's loudest 8 s -14.5 LUFS),
where the 3 and 6 dB targets solved within AC THRESHOLD's range.

Writes data/clips/<name>.wav (mono float32), the mix's category into
data/clips/clips.yaml, and data/clips/mixes.json: per mix its recipe, the stems'
SHA-256, the normalization gain and the levels, so a clip can be rebuilt and checked.
The stems are the user's (never committed); so are the clips.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

from varimu.config import DATA_DIR
from varimu.listen import matching
from varimu.listen.candidates import POOL_FILE, load_pool

MIX_LUFS = -14.0
MIX_PEAK_DBFS = -0.5
CLIP_DIR = DATA_DIR / "clips"


def find_stem(song_dir: Path, stem: str) -> Path:
    hits = sorted(song_dir.rglob(f"{stem}.wav"))
    if len(hits) != 1:
        raise FileNotFoundError(f"{stem}.wav under {song_dir}: {len(hits)} matches")
    return hits[0]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def loudest_window(x: np.ndarray, fs: int, seconds: float) -> slice:
    """The loudest window of `seconds` (rms, on a 0.1 s grid), as varimu.listen.stimuli
    picks a long clip's excerpt."""
    hop = int(0.1 * fs)
    w = int(round(seconds / 0.1))
    e = np.square(x[: len(x) // hop * hop]).reshape(-1, hop).sum(1)
    if len(e) <= w:
        return slice(0, len(x))
    best = int(np.argmax(np.convolve(e, np.ones(w), "valid")))
    return slice(best * hop, best * hop + w * hop)


def build(name: str, mix: dict, root: Path, excerpt_s: float) -> dict:
    song_dir = root / mix["song"]
    invert = set(mix.get("invert", []))
    unknown = invert - set(mix["stems"])
    if unknown:
        raise KeyError(f"{name}: invert lists stems not in the mix: {sorted(unknown)}")
    total, fs, stems = None, None, []
    for stem, gain_db in mix["stems"].items():
        path = find_stem(song_dir, stem)
        x, rate = sf.read(path, dtype="float64", always_2d=True)
        if fs is None:
            fs = rate
        elif rate != fs:
            raise ValueError(f"{name}: {stem} is at {rate} Hz, the others at {fs}")
        y = x.mean(axis=1) * 10 ** (float(gain_db) / 20) * (-1 if stem in invert else 1)
        if total is None:
            total = y
        else:
            n = max(len(total), len(y))
            total = np.pad(total, (0, n - len(total))) + np.pad(y, (0, n - len(y)))
        stems.append({"stem": stem, "file": path.relative_to(root).as_posix(),
                      "sha256": sha256(path), "gain_db": float(gain_db),
                      "inverted": stem in invert})  # fmt: skip
    win = loudest_window(total, fs, excerpt_s)
    lufs = matching.integrated_lufs(total[win], fs)
    gain_db = MIX_LUFS - lufs
    peak_db = 20 * np.log10(np.max(np.abs(total))) + gain_db
    if peak_db > MIX_PEAK_DBFS:
        gain_db -= peak_db - MIX_PEAK_DBFS
    out = total * 10 ** (gain_db / 20)
    path = CLIP_DIR / f"{name}.wav"
    sf.write(path, out.astype("<f4"), fs, subtype="FLOAT")
    return {
        "clip": path.name, "category": mix["category"], "song": mix["song"],
        "sample_rate": fs, "seconds": round(len(out) / fs, 3), "stems": stems,
        "normalization_gain_db": round(gain_db, 3),
        "loudest_window_s": [round(win.start / fs, 2), round(win.stop / fs, 2)],
        "loudest_window_lufs": round(matching.integrated_lufs(out[win], fs), 2),
        "peak_dbfs": round(float(20 * np.log10(np.max(np.abs(out)))), 2),
        "peak_limited": bool(peak_db > MIX_PEAK_DBFS),
        "clip_sha256": sha256(path), "note": mix.get("note", ""),
    }  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, required=True, help="folder holding the songs' folders")
    ap.add_argument("--only", nargs="*", help="mix names (default: every mix)")
    args = ap.parse_args()
    mixes = yaml.safe_load(POOL_FILE.read_text(encoding="utf-8")).get("mixes") or {}
    names = args.only or list(mixes)
    excerpt_s = load_pool().excerpt_s
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = CLIP_DIR / "mixes.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    local_path = CLIP_DIR / "clips.yaml"
    local = yaml.safe_load(local_path.read_text("utf-8")) or {} if local_path.exists() else {}
    for name in names:
        rec = build(name, mixes[name], args.root, excerpt_s)
        manifest[name] = rec
        local[rec["clip"]] = {**local.get(rec["clip"], {}), "category": rec["category"]}
        print(
            f"{rec['clip']}: {rec['category']}, {len(rec['stems'])} stems, {rec['seconds']} s, "
            f"gain {rec['normalization_gain_db']:+.1f} dB -> loudest {excerpt_s:g} s "
            f"{rec['loudest_window_lufs']} LUFS at {rec['loudest_window_s']} s, peak "
            f"{rec['peak_dbfs']} dBFS{' (peak limited)' if rec['peak_limited'] else ''}"
        )
    manifest_path.write_text(json.dumps(manifest, indent=1), "utf-8")
    local_path.write_text(yaml.safe_dump(local, sort_keys=True), "utf-8")


if __name__ == "__main__":
    main()

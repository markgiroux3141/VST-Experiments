"""AM3, distance to an era (docs/ANALOG_MAGIC_FABLE.md), step 1 (varimu.magic.era).

The corpus: the 1960s tracks of the user's Lightfoot compilation (Rhino's Complete Greatest
Hits, tracks 1-6: the United Artists recordings of 1965-69; split by split_reference.py into
cache/magic/reference/lightfoot_complete/). 20 minutes: under the doc's 30, so the distance
uses the diagonal covariance (the shrunk full one is reported beside it).

Checks:
  A. the floor: the corpus's odd tracks against its even ones;
  B. held-out 1960s tracks (leave one out) against the corpus, and every later track
     (1970s, later) against it: if the held-out aren't closer, the features don't carry the
     era;
  C. a known change on the cover: its plain mix low-passed at 10 kHz, and with a +6 dB low
     shelf at 150 Hz: the deltas' signs recorded.
Then the cover's versions, each through the reference's codec (opus 160 kbit/s), as deltas
against the plain mix: the 1968-style mix without and with the 4-track, and any files given
with --variants (each against --baseline).

-> reports/magic/era/summary.json

  uv run --extra listen python scripts/era_distance.py [--variants F ... --baseline F]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from varimu.config import REPO_ROOT
from varimu.magic import codec, era

OUT = REPO_ROOT / "reports" / "magic" / "era"
REF = REPO_ROOT / "cache" / "magic" / "reference" / "lightfoot_complete"
COVER = REPO_ROOT / "cache" / "magic" / "forensics" / "cover"
FEAT_CACHE = REPO_ROOT / "cache" / "magic" / "era"


def load(path: Path, codec_name: str | None = None) -> tuple[np.ndarray, int]:
    x, fs = sf.read(path, dtype="float64", always_2d=True)
    if codec_name:
        x = codec.round_trip(x, fs, codec_name)
    return x.mean(axis=1), fs


def feats(path: Path, codec_name: str | None = None, tag: str = "") -> np.ndarray:
    import hashlib

    st = path.stat()
    key = hashlib.sha256(f"{path}|{st.st_size}|{st.st_mtime}|{codec_name}|{tag}|v1".encode()).hexdigest()[:24]
    p = FEAT_CACHE / f"{key}.npy"
    if p.exists():
        return np.load(p)
    x, fs = load(path, codec_name)
    f = era.features(x, fs)
    FEAT_CACHE.mkdir(parents=True, exist_ok=True)
    np.save(p, f)
    return f


def feats_of(x: np.ndarray, fs: int) -> np.ndarray:
    return era.features(x, fs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--variants", nargs="*", default=[])
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--codec", default="opus160")
    a = ap.parse_args()
    meta = json.loads((REF / "tracks.json").read_text())
    by_era: dict[str, list[tuple[int, np.ndarray]]] = {}
    for t in meta["tracks"]:
        f = feats(REF / f"{t['n']:02d}.wav")
        by_era.setdefault(t["era"], []).append((t["n"], f))
        print(f"  track {t['n']:02d} ({t['era']}): {len(f)} windows", flush=True)
    sixties = by_era["1960s"]
    corpus = era.Corpus([f for _, f in sixties])
    summ: dict = {"corpus_windows": len(corpus.f), "dims": corpus.f.shape[1]}

    # A: the floor.
    odd = era.Corpus([f for n, f in sixties if n % 2])
    even = np.vstack([f for n, f in sixties if not n % 2])
    summ["A_floor"] = {"diag": odd.distance(even, True), "full": odd.distance(even, False)}

    # B: held-out vs later.
    rows = []
    for n, f in sixties:
        c = era.Corpus([g for m, g in sixties if m != n])
        rows.append({"track": n, "era": "1960s (held out)", "diag": c.distance(f, True),
                     "full": c.distance(f, False)})
    for e in ("1970s", "later"):
        for n, f in by_era.get(e, []):
            rows.append({"track": n, "era": e, "diag": corpus.distance(f, True),
                         "full": corpus.distance(f, False)})
    summ["B_tracks"] = rows
    for e in ("1960s (held out)", "1970s", "later"):
        v = [r["diag"] for r in rows if r["era"] == e]
        vf = [r["full"] for r in rows if r["era"] == e]
        summ.setdefault("B_median", {})[e] = {"diag": float(np.median(v)), "full": float(np.median(vf))}
    print(f"A floor: {summ['A_floor']}", flush=True)
    print(f"B medians: {summ['B_median']}", flush=True)

    # C and the cover's versions (codec-matched).
    plain = COVER / "cover_plain.wav"
    f_plain = feats(plain, a.codec)
    x, fs = load(plain)
    lp = signal.sosfiltfilt(signal.butter(6, 10000, fs=fs, output="sos"), x)
    # A +6 dB low shelf at 150 Hz: x plus a low-passed copy scaled to reach +6 dB.
    shelf = x + (10 ** (6 / 20) - 1) * signal.sosfiltfilt(signal.butter(2, 150, fs=fs, output="sos"), x)
    summ["cover_distance_plain"] = {"diag": corpus.distance(f_plain, True), "full": corpus.distance(f_plain, False)}
    summ["C_known_changes"] = {
        "lowpass_10k": era.era_delta(era.features(codec.round_trip(lp, fs, a.codec), fs), f_plain, corpus),
        "low_shelf_+6dB": era.era_delta(era.features(codec.round_trip(shelf, fs, a.codec), fs), f_plain, corpus),
    }
    summ["cover_versions"] = {}
    for nm in ("cover_mix_no_tape", "cover_mix_through_4track"):
        f = feats(COVER / f"{nm}.wav", a.codec)
        summ["cover_versions"][nm] = era.era_delta(f, f_plain, corpus)
    if a.variants:
        fb = feats(Path(a.baseline), a.codec)
        for v in a.variants:
            summ["cover_versions"][Path(v).stem] = era.era_delta(feats(Path(v), a.codec), fb, corpus)
    print(json.dumps({k: summ[k] for k in ("C_known_changes", "cover_versions")}, indent=1), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    prior = OUT / "summary.json"
    if prior.exists() and a.variants:
        old = json.loads(prior.read_text())
        old.setdefault("cover_versions", {}).update(summ["cover_versions"])
        summ = {**old, **{k: v for k, v in summ.items() if k != "cover_versions"}, "cover_versions": old["cover_versions"]}
    prior.write_text(json.dumps(summ, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())

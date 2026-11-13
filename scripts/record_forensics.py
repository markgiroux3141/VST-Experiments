"""AM1, record forensics (docs/ANALOG_MAGIC_FABLE.md): every fingerprint
(varimu.magic.fingerprints) of each file under a label, then medians and quartiles over the
label's files; with several labels, a comparison table and overlay plots.

  uv run --extra listen python scripts/record_forensics.py analyse --label NAME FILE_OR_DIR ...
      [--codec opus160]
  uv run --extra listen python scripts/record_forensics.py reference --name lightfoot_complete
      (cache/magic/reference/<name>/ from split_reference.py: one label per era)
  uv run --extra listen python scripts/record_forensics.py cover [--codec opus160]
      (the user's cover of Did She Mention My Name: a plain sum of the session's lanes, the
      1968-style mix without and with the 4-track; reports/lightfoot_mix/)
  uv run --extra listen python scripts/record_forensics.py compare LABEL ...

-> reports/magic/forensics/<label>.json, compare.json, compare.png.

`--codec opus160`: each file through libopus at 160 kbit/s and back (ffmpeg) before the
analysis, as YouTube delivers audio: so a cover compared with a YouTube-sourced reference has
the same codec on both sides.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.config import REPO_ROOT
from varimu.magic import fingerprints as fp

OUT = REPO_ROOT / "reports" / "magic" / "forensics"
REF = REPO_ROOT / "cache" / "magic" / "reference"
COVER = REPO_ROOT / "cache" / "magic" / "forensics" / "cover"
LANES = REPO_ROOT / "cache" / "lightfoot_mix" / "dry"
MIXES = REPO_ROOT / "reports" / "lightfoot_mix"
AUDIO_EXT = (".wav", ".flac", ".mp3", ".ogg", ".opus", ".aiff", ".aif")


def codec_round_trip(path: Path, codec: str) -> np.ndarray:
    """The file through the named codec and back, at 48 kHz stereo (float)."""
    kbps = int(codec.removeprefix("opus"))
    with tempfile.TemporaryDirectory() as d:
        enc = Path(d) / "x.opus"
        dec = Path(d) / "x.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(path),
                "-c:a",
                "libopus",
                "-b:a",
                f"{kbps}k",
                str(enc),
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(enc),
                "-ar",
                "48000",
                "-c:a",
                "pcm_f32le",
                str(dec),
            ],
            check=True,
        )
        x, fs = sf.read(dec, dtype="float64", always_2d=True)
    return x, fs


def read(path: Path, codec: str | None) -> tuple[np.ndarray, int]:
    if codec:
        return codec_round_trip(path, codec)
    x, fs = sf.read(path, dtype="float64", always_2d=True)
    return x, fs


def files_of(items: list[str]) -> list[Path]:
    out = []
    for it in items:
        p = Path(it)
        if p.is_dir():
            out += sorted(q for q in p.iterdir() if q.suffix.lower() in AUDIO_EXT)
        else:
            out.append(p)
    return out


def flatten(d: dict, prefix: str = "") -> dict[str, float]:
    """Scalar leaves of a fingerprint dict as 'a.b.c' keys."""
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        elif isinstance(v, int | float) and not isinstance(v, bool):
            out[key] = float(v)
    return out


def analyse(label: str, files: list[Path], codec: str | None) -> dict:
    per_file = {}
    for p in files:
        x, fs = read(p, codec)
        x = x[:, :2] if x.shape[1] > 2 else x
        if x.shape[1] == 1:
            x = x[:, 0]
        per_file[p.name] = fp.all_fingerprints(x, fs)
        print(f"  {label}: {p.name} ({len(x) / fs:.0f} s)", flush=True)
    flat = {k: flatten(v) for k, v in per_file.items()}
    keys = sorted(set().union(*[set(f) for f in flat.values()])) if flat else []
    agg = {}
    for k in keys:
        v = np.array([f[k] for f in flat.values() if k in f and np.isfinite(f[k])])
        if len(v):
            q1, med, q3 = np.percentile(v, [25, 50, 75])
            agg[k] = {"median": float(med), "q1": float(q1), "q3": float(q3), "n": len(v)}
    res = {"label": label, "codec": codec, "files": per_file, "summary": agg}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{label}.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def make_cover() -> list[Path]:
    """The cover's three versions as files in cache/magic/forensics/cover/: plain (the four
    lanes at the mix's faders and pans, nothing else: modern and clean), mix_no_tape and
    mix_through_4track (reports/lightfoot_mix/)."""
    COVER.mkdir(parents=True, exist_ok=True)
    mix = json.loads((LANES / "mix.json").read_text())
    names = ["bass", "guitar", "lead vocal", "harmonies"]  # src_1..4 (the tape's order)
    lanes = [sf.read(LANES / f"src_{k + 1}.wav", dtype="float64")[0] for k in range(4)]
    n = min(len(v) for v in lanes)
    out = np.zeros((n, 2))
    for name, x in zip(names, lanes, strict=True):
        g = 10 ** (mix["faders_db"][name] / 20)
        pan = mix["moves"][name]["pan"]
        th = (pan + 1) * np.pi / 4  # constant power
        out[:, 0] += g * np.cos(th) * x[:n]
        out[:, 1] += g * np.sin(th) * x[:n]
    from varimu.listen.matching import integrated_lufs

    out *= 10 ** ((mix["mix_lufs"] - integrated_lufs(out, 48000)) / 20)
    paths = [COVER / "cover_plain.wav"]
    sf.write(paths[0], out.astype(np.float32), 48000, subtype="FLOAT")
    for nm in ("mix_no_tape", "mix_through_4track"):
        p = COVER / f"cover_{nm}.wav"
        x, fs = sf.read(MIXES / f"{nm}.wav", dtype="float32")
        sf.write(p, x, fs, subtype="FLOAT")
        paths.append(p)
    return paths


def compare(labels: list[str]) -> dict:
    data = {lb: json.loads((OUT / f"{lb}.json").read_text())["summary"] for lb in labels}
    keys = sorted(set().union(*[set(d) for d in data.values()]))
    table = {k: {lb: data[lb].get(k) for lb in labels} for k in keys}
    # Separation of the first label from each other: the medians' difference over the
    # pooled interquartile range (|d| > 1: the middle halves don't overlap).
    base = labels[0]
    sep = {}
    for k in keys:
        a = data[base].get(k)
        if not a:
            continue
        row = {}
        for lb in labels[1:]:
            b = data[lb].get(k)
            if not b:
                continue
            iqr = max(((a["q3"] - a["q1"]) + (b["q3"] - b["q1"])) / 2, 1e-9)
            row[lb] = (b["median"] - a["median"]) / iqr
        sep[k] = row
    res = {"labels": labels, "table": table, "separation_vs_first": sep}
    (OUT / "compare.json").write_text(json.dumps(res, indent=1, default=float))
    plot(labels, OUT)
    return res


def plot(labels: list[str], out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    for lb in labels:
        d = json.loads((out / f"{lb}.json").read_text())
        files = d["files"].values()
        # LTAS, each file re its 1 kHz band, median over files.
        bands = None
        curves = []
        for f in files:
            b = f["ltas"]["bands_db"]
            bands = [float(k) for k in b]
            v = np.array(list(b.values()))
            curves.append(v - v[np.argmin(np.abs(np.array(bands) - 1000))])
        axes[0, 0].semilogx(bands, np.median(curves, axis=0), label=lb)
        oct_keys = [k for k in next(iter(files))["crest_by_band"] if k != "broadband"]
        cr = np.median([[f["crest_by_band"][k] for k in oct_keys] for f in files], axis=0)
        axes[0, 1].semilogx([float(k) for k in oct_keys], cr, "o-", label=lb)
        st = [f.get("stereo") for f in files if f.get("stereo")]
        if st:
            ck = list(st[0]["coherence"])
            axes[1, 0].semilogx(
                [float(k) for k in ck],
                np.median([[s["coherence"][k] for k in ck] for s in st], axis=0),
                "o-",
                label=lb,
            )
        lv = [f["level_distribution"] for f in files]
        axes[1, 1].plot(
            [np.median([v[p] - v["p50"] for v in lv]) for p in ("p10", "p50", "p95")],
            [10, 50, 95],
            "o-",
            label=lb,
        )
    axes[0, 0].set(title="LTAS re 1 kHz (median over files)", xlabel="Hz", ylabel="dB")
    axes[0, 1].set(title="crest factor per octave", xlabel="Hz", ylabel="dB")
    axes[1, 0].set(title="L/R coherence per octave", xlabel="Hz")
    axes[1, 1].set(title="short-term level percentiles re median", xlabel="dB", ylabel="percentile")
    for ax in axes.flat:
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "compare.png", dpi=110)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("analyse")
    a1.add_argument("--label", required=True)
    a1.add_argument("--codec", default=None)
    a1.add_argument("items", nargs="+")
    a2 = sub.add_parser("reference")
    a2.add_argument("--name", required=True)
    a3 = sub.add_parser("cover")
    a3.add_argument("--codec", default=None)
    a4 = sub.add_parser("compare")
    a4.add_argument("labels", nargs="+")
    a = ap.parse_args()
    if a.cmd == "analyse":
        analyse(a.label, files_of(a.items), a.codec)
    elif a.cmd == "reference":
        meta = json.loads((REF / a.name / "tracks.json").read_text())
        eras: dict[str, list[Path]] = {}
        for t in meta["tracks"]:
            eras.setdefault(t["era"] or "unlabelled", []).append(REF / a.name / f"{t['n']:02d}.wav")
        for era, files in eras.items():
            analyse(f"{a.name}_{era}", files, None)
    elif a.cmd == "cover":
        paths = make_cover()
        tag = f"_{a.codec}" if a.codec else ""
        for p in paths:
            analyse(p.stem + tag, [p], a.codec)
    elif a.cmd == "compare":
        r = compare(a.labels)
        for k, row in r["separation_vs_first"].items():
            if any(abs(v) >= 1 for v in row.values()):
                print(f"  {k}: " + ", ".join(f"{lb} {v:+.2f}" for lb, v in row.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

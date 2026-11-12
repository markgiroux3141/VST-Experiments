"""Mix Did She Mention My Name like a 1968 Gordon Lightfoot record, from the dry lanes or
from the Ampex 300-4's print (docs/HEADLESS_MIX_PLAN.md, an early H3 without H0's
session render; the notes are reports/lightfoot_mix/NOTES.md).

Usage:
  uv run python scripts/lightfoot_mix.py --version dry|tape [--stage inserts|mix|all]
      [--quality production]

  dry:  the session's four lanes (the mid of each, as the deck records it)
  tape: reports/lightfoot_mix/tape/tape1..4.wav (examples/tape_print.rs --out)

The console moves, the same for both versions (MOVES below): each insert chain printed by
varimu-app's examples/print.rs (the app's own print), faders set by loudness, pans, the
lead vocal ridden against the accompaniment, a post-fader send into the stereo EMT 140
plate. Each insert's trim is its base trim (measured on the dry lane) plus the dry lane's
sounding level minus this version's, so both versions drive the inserts alike. The mix is
written un-normalized (mix_<version>.wav, float) with a JSON of every number; the
loudness-matched pair for listening is made by --stage match.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf
from lightfoot_mix_analyze import lufs
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "sessions" / "did she mention my name (tape)"
OUT = ROOT / "reports" / "lightfoot_mix"
WORK = ROOT / "cache" / "lightfoot_mix"
PRINT = ROOT / "target" / "release" / "examples" / "print.exe"
FS = 48_000
NAMES = ["bass", "guitar", "lead vocal", "harmonies"]

# The console's moves. Each insert: (device, {knob: value}, base trim dB). Measured on a
# 10 s chorus excerpt of the dry lanes (NOTES.md has the numbers).
MOVES = {
    "bass": {"inserts": [], "lu": -7.0, "pan": 0.0, "send": 0.0},
    "guitar": {
        "inserts": [
            (
                "pultec_eqp1a",
                {
                    "lf_freq_hz": 100,
                    "lf_atten": 1.0,
                    "hf_boost_freq_khz": 4,
                    "hf_boost": 0.8,
                    "bandwidth": 0.8,
                },
                0.0,
            )
        ],
        "lu": -3.5,
        "pan": -0.5,
        "send": 0.25,
    },
    "lead vocal": {
        "inserts": [
            (
                "pultec_eqp1a",
                {
                    "lf_freq_hz": 100,
                    "lf_atten": 0.5,
                    "hf_boost_freq_khz": 8,
                    "hf_boost": 0.5,
                    "bandwidth": 0.7,
                },
                0.0,
            ),
            ("fairchild_670", {"time_constant": 2}, 22.0),
        ],
        "lu": 0.0,
        "pan": 0.0,
        "send": 1.0,
    },
    "harmonies": {
        "inserts": [("fairchild_670", {"time_constant": 2}, 6.0)],
        "lu": -5.0,
        "pan": 0.5,
        "send": 1.3,
    },
}
PLATE = ("plate_reverb", {"stereo": 1, "decay_500hz_s": 2.2}, 0.0)
# The plate's return: its loudness re the dry lead vocal's (a moderate, audible tail).
PLATE_LU = -11.0
# Vocal rides: the lead's 3 s loudness held near its median excess over the accompaniment,
# at most +-3 dB, moved over ~1 s (a hand on the fader).
RIDE_MAX_DB = 3.0


def mono(path: Path) -> np.ndarray:
    x, fs = sf.read(path, dtype="float64")
    assert fs == FS, (path, fs)
    return x if x.ndim == 1 else x.mean(axis=1)


def sounding_db(x: np.ndarray) -> float:
    """The rms while the part sounds (400 ms blocks within 30 dB of the loudest)."""
    blk = int(0.4 * FS)
    r = np.array([np.mean(x[i : i + blk] ** 2) for i in range(0, len(x) - blk, blk)])
    rdb = 10 * np.log10(r + 1e-24)
    return float(10 * np.log10(np.mean(r[rdb > rdb.max() - 30])))


def sources(version: str) -> dict[str, Path]:
    d = WORK / version
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    for k, n in enumerate(NAMES):
        if version == "dry":
            p = d / f"src_{k + 1}.wav"
            if not p.exists():
                x = mono(SESSION / "takes" / f"t000{k + 1}" / "draft.wav")
                sf.write(p, x.astype(np.float32), FS, subtype="FLOAT")
        else:
            p = OUT / "tape" / f"tape{k + 1}.wav"
        out[n] = p
    return out


def run_chain(src: Path, chain, offset_db: float, quality: str, dst: Path) -> dict:
    if not chain:
        return {"cmd": None}
    cmd = [str(PRINT), "--file", str(src), "--quality", quality]
    for dev, knobs, trim in chain:
        cmd += ["--device", dev]
        for k, v in knobs.items():
            cmd += ["--set", f"{k}={v}"]
        cmd += ["--trim", f"{trim + offset_db:.2f}"]
        offset_db = 0.0  # the offset applies to the first insert only
    cmd += ["--cache", str(WORK / "prints"), "--out", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        raise RuntimeError(f"{cmd}\n{r.stdout}\n{r.stderr}")
    return {"cmd": cmd[1:], "log": r.stdout.strip().splitlines()}


def stage_inserts(version: str, quality: str) -> None:
    src = sources(version)
    dry = sources("dry")
    meta = {"version": version, "quality": quality, "tracks": {}}
    jobs = {}
    with ThreadPoolExecutor(len(NAMES)) as pool:
        for n in NAMES:
            offset = sounding_db(mono(dry[n])) - sounding_db(mono(src[n]))
            meta["tracks"][n] = {"source": str(src[n].relative_to(ROOT)), "trim_offset_db": offset}
            dst = WORK / version / f"ins_{n}.wav"
            jobs[n] = pool.submit(run_chain, src[n], MOVES[n]["inserts"], offset, quality, dst)
        for n, j in jobs.items():
            meta["tracks"][n]["print"] = j.result()
            print(n, meta["tracks"][n])
    (WORK / version / "inserts.json").write_text(json.dumps(meta, indent=1))


def pan(x: np.ndarray, p: float) -> np.ndarray:
    """A constant-power pan pot (-3 dB at centre), p in [-1, 1]."""
    th = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(th), x * np.sin(th)], axis=1)


def rides(lead: np.ndarray, acc: np.ndarray) -> tuple[np.ndarray, dict]:
    """The lead's fader moves: gain (linear, per sample) and a summary."""
    hop = int(0.1 * FS)
    win = 30  # 3 s
    n = len(lead) // hop

    def st(x):
        e = np.array([np.mean(x[i * hop : (i + 1) * hop] ** 2) for i in range(n)])
        return 10 * np.log10(np.convolve(e, np.ones(win) / win, "same") + 1e-24)

    sl, sa = st(signal.lfilter(*signal.butter(2, 150, "high", fs=FS), lead)), st(acc)
    sounding = sl > np.percentile(sl, 99) - 20
    excess = sl - sa
    target = np.median(excess[sounding])
    g = np.clip(target - excess, -RIDE_MAX_DB, RIDE_MAX_DB)
    g[~sounding] = 0.0
    # a hand: hold between phrases, move over ~1 s
    for i in range(1, n):
        if not sounding[i]:
            g[i] = g[i - 1]
    b, a = signal.butter(1, 0.5, fs=10)
    g = signal.filtfilt(b, a, g)
    t = (np.arange(len(lead)) / hop).clip(0, n - 1)
    gs = np.interp(t, np.arange(n), g)
    return 10 ** (gs / 20), {
        "median_excess_db": float(target),
        "ride_db_p5_p50_p95": [float(np.percentile(g[sounding], q)) for q in (5, 50, 95)],
    }


def stage_mix(version: str, quality: str) -> None:
    src = sources(version)
    tr = {}
    for n in NAMES:
        p = WORK / version / f"ins_{n}.wav"
        tr[n] = mono(p) if MOVES[n]["inserts"] else mono(src[n])
    m = min(len(x) for x in tr.values())
    tr = {n: x[:m] for n, x in tr.items()}
    meta = {"version": version, "quality": quality, "faders_db": {}}
    # Faders: each track's loudness to its target re the lead (LU).
    ref = lufs(tr["lead vocal"], FS)
    for n in NAMES:
        g = ref + MOVES[n]["lu"] - lufs(tr[n], FS)
        meta["faders_db"][n] = float(g)
        tr[n] = tr[n] * 10 ** (g / 20)
    gain, meta["rides"] = rides(tr["lead vocal"], tr["guitar"] + tr["bass"])
    tr["lead vocal"] = tr["lead vocal"] * gain
    # The send (post-fader) and the plate.
    send = sum(MOVES[n]["send"] * tr[n] for n in NAMES)
    send *= 10 ** ((-12.0 - 20 * np.log10(np.abs(send).max())) / 20)  # peaks at -12 dBFS
    sp = WORK / version / "send.wav"
    sf.write(sp, send.astype(np.float32), FS, subtype="FLOAT")
    pp = WORK / version / "plate.wav"
    meta["plate"] = run_chain(sp, [PLATE], 0.0, quality, pp)
    wet, _ = sf.read(pp, dtype="float64")
    if wet.ndim == 1:
        wet = np.stack([wet, wet], axis=1)
    g = ref + PLATE_LU - lufs(wet, FS) + 10 * np.log10(2)  # stereo vs mono loudness
    meta["plate_return_db"] = float(g)
    wet *= 10 ** (g / 20)
    n_out = max(m, len(wet))
    mix = np.zeros((n_out, 2))
    for n in NAMES:
        mix[:m] += pan(tr[n], MOVES[n]["pan"])
    mix[: len(wet)] += wet
    meta["mix_lufs"] = lufs(mix, FS)
    meta["mix_peak_dbfs"] = float(20 * np.log10(np.abs(mix).max()))
    meta["moves"] = {n: {k: v for k, v in MOVES[n].items()} for n in NAMES}
    meta["plate_settings"] = PLATE
    sf.write(WORK / version / "mix.wav", mix.astype(np.float32), FS, subtype="FLOAT")
    (WORK / version / "mix.json").write_text(json.dumps(meta, indent=1, default=str))
    print(
        json.dumps(
            {
                k: meta[k]
                for k in ("faders_db", "rides", "plate_return_db", "mix_lufs", "mix_peak_dbfs")
            },
            indent=1,
        )
    )


def stage_match() -> None:
    """The two mixes at one loudness, the louder-peaked one at -1 dBFS true-ish peak."""
    mixes = {v: sf.read(WORK / v / "mix.wav", dtype="float64")[0] for v in ("dry", "tape")}
    loud = {v: lufs(x, FS) for v, x in mixes.items()}
    # the loudness each can reach with its peak at -1 dBFS (4x oversampled peak)
    reach = {
        v: loud[v] - 1.0 - 20 * np.log10(np.abs(signal.resample_poly(x, 4, 1, axis=0)).max())
        for v, x in mixes.items()
    }
    target = min(reach.values())
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"target_lufs": target, "files": {}}
    for v, x in mixes.items():
        g = target - loud[v]
        y = x * 10 ** (g / 20)
        name = {"tape": "mix_through_4track.wav", "dry": "mix_no_tape.wav"}[v]
        sf.write(OUT / name, y.astype(np.float32), FS, subtype="FLOAT")
        meta["files"][name] = {
            "gain_db": g,
            "lufs": lufs(y, FS),
            "peak_dbfs": float(20 * np.log10(np.abs(y).max())),
        }
    (OUT / "match.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=["dry", "tape"])
    ap.add_argument("--stage", choices=["inserts", "mix", "all", "match"], default="all")
    ap.add_argument("--quality", default="production")
    a = ap.parse_args()
    if a.stage == "match":
        stage_match()
        return
    if a.stage in ("inserts", "all"):
        stage_inserts(a.version, a.quality)
    if a.stage in ("mix", "all"):
        stage_mix(a.version, a.quality)


if __name__ == "__main__":
    main()

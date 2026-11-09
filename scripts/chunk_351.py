"""TAPE_SPEED_PLAN.md P3: the literal Ampex 351's print in pieces run at once
(`fast.run_transient_chunked`) against the same print run continuously.

The aligned machine at production (with its noise unless `--no-noise`), `--seconds` of the
clip at `--drive-db`, printed whole (or reused from cache/tape/chunks/) and in pieces of
`--chunk-s` with `--warmup-s` of warm-up on `--workers` threads. Reports the wall times,
the largest third-octave band difference 50 Hz-15 kHz over the whole excerpt, the same in
200 ms windows around every seam (against the same windows of the whole print), and each
seam's waveform difference re the print's rms (the bias oscillator's free phase and the
grain's cells set its floor, -46 to -57 dB between any two runs: TAPE_PLAN.md "Speed").
Writes both prints, their difference and spectrograms around the seams to reports/tape/chunks/
and the numbers to its results.json.

    uv run --extra fast --extra listen python scripts/chunk_351.py --seconds 30 --chunk-s 7.5

`--gpu`: the tape's recording kernel on the GPU (TAPE_SPEED_PLAN.md P5), both prints.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta
from varimu.sim import fast
from varimu.sim.io import TransientSettings, load_audio

CACHE = REPO_ROOT / "cache" / "tape" / "chunks"
OUT = REPO_ROOT / "reports" / "tape" / "chunks"
TAIL_S = 0.3


def bands_db(y: np.ndarray, fs: int) -> np.ndarray:
    """Third-octave band levels 50 Hz-15 kHz (dB)."""
    f = np.fft.rfftfreq(len(y), 1.0 / fs)
    p = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
    out = []
    for fc in 1000.0 * 2.0 ** (np.arange(-13, 12) / 3.0):
        b = (f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6))
        out.append(10 * math.log10(p[b].sum() + 1e-300))
    return np.array(out)


def seams_png(yc: np.ndarray, yw: np.ndarray, fs: int, at_s: list[float], path: Path) -> None:
    """Spectrograms of the pieces and of pieces - whole, 1 s either side of each seam."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.signal import spectrogram

    fig, ax = plt.subplots(len(at_s), 2, figsize=(12, 2.8 * len(at_s)), squeeze=False)
    for i, s in enumerate(at_s):
        lo, hi = max(0, int((s - 1) * fs)), min(len(yc), int((s + 1) * fs))
        for j, (y, name) in enumerate(((yc, "pieces"), (yc - yw, "pieces - whole"))):
            f, t, sxx = spectrogram(y[lo:hi], fs, nperseg=2048, noverlap=1536)
            ax[i, j].pcolormesh(
                t + lo / fs,
                f / 1e3,
                10 * np.log10(sxx + 1e-20),
                vmin=-150,
                vmax=-40,
                shading="auto",
            )
            ax[i, j].set_ylim(0, 20)
            ax[i, j].axvline(s, color="w", lw=0.5, ls=":")
            ax[i, j].set_title(f"{name} around the seam at {s:.2f} s")
            ax[i, j].set_ylabel("kHz")
    fig.tight_layout()
    fig.savefig(path, dpi=80)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clip", default="drums_setmefree.wav")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--drive-db", type=float, default=6.0)
    ap.add_argument("--chunk-s", type=float, default=7.5)
    ap.add_argument("--warmup-s", type=float, default=2.0)
    ap.add_argument("--fade-s", type=float, default=0.01)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--tape-threads",
        type=int,
        help="each piece's tape kernel threads (default: the cores less 4, shared)",
    )
    ap.add_argument("--no-noise", action="store_true")
    ap.add_argument(
        "--gpu", action="store_true", help="the tape kernel on the GPU (TransientSettings.tape_gpu)"
    )
    ap.add_argument("--alignment", type=Path, help="a cached alignment's JSON (its panel)")
    ap.add_argument("--skip-whole", action="store_true", help="only the pieces (timing)")
    a = ap.parse_args()

    cores = os.cpu_count() or 1
    tape_threads = a.tape_threads or max(1, (cores - 4) // max(1, a.workers))
    al = ta.Alignment(**json.loads(a.alignment.read_text())) if a.alignment else ta.aligned()
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    if a.gpu:
        st = dataclasses.replace(st, tape_gpu=True)
    fs = st.sample_rate
    c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
    v_in, v_out = c.full_scale
    p = spec.resolve(c, al.overrides)
    delay = int(round(p["head_distance_m"] / p["speed_m_s"] * fs))
    ir = builder.build(c, al.overrides, cores="ja", noise=not a.no_noise).ir
    x = load_audio(REPO_ROOT / "data" / "clips" / a.clip, fs)
    x = x[int(a.start * fs) :]
    if len(x) < int(a.seconds * fs):
        # A clip shorter than the excerpt plays again from its start (P3's 3 minutes from
        # the ~39 s drums: the seams' comparison doesn't depend on the music).
        x = np.tile(x, math.ceil(a.seconds * fs / len(x)))
        res_note = f"the clip ({Path(a.clip).name} from {a.start:g} s) tiled to {a.seconds:g} s"
    else:
        res_note = None
    x = x[: int(a.seconds * fs)]
    u = np.concatenate([x, np.zeros(delay + int(TAIL_S * fs))]) * v_in * 10 ** (a.drive_db / 20)
    tag = (
        f"{Path(a.clip).stem}_{a.start:g}s_{a.seconds:g}s_{a.drive_db:+g}dB"
        + ("_nonoise" if a.no_noise else "")
        + ("_gpu" if a.gpu else "")
    )
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(ir.to_json().encode() + u.tobytes() + json.dumps(st.as_dict()).encode())
    whole_path = CACHE / f"whole_{tag}_{h.hexdigest()[:16]}.npy"
    res: dict = {"tag": tag, "chunk_s": a.chunk_s, "warmup_s": a.warmup_s, "workers": a.workers}
    res["tape_threads"] = tape_threads
    if res_note:
        res["note"] = res_note
    audio_s = len(u) / fs

    def show(label):
        t0 = time.time()

        def progress(f: float) -> None:
            el = time.time() - t0
            if f > 0:
                print(f"\r{label}: {100 * f:5.1f}%  eta {el / f - el:6.0f} s", end="", flush=True)

        return progress

    if not a.skip_whole:
        if whole_path.exists():
            yw = np.load(whole_path)
            res["whole_x_real_time"] = None
        else:
            r = fast.run_transient(ir, u, settings=st, progress=show("whole"))
            print()
            yw = r.vectors["v(out)"][delay:] / v_out
            np.save(whole_path, yw)
            res["whole_x_real_time"] = r.wall_s / (audio_s + st.settle_s)
    # The whole print takes the tape's default threads; the pieces share the cores.
    os.environ["CIRCUITSIM_TAPE_THREADS"] = str(tape_threads)
    t0 = time.time()
    r = fast.run_transient_chunked(
        ir,
        u,
        settings=st,
        chunk_s=a.chunk_s,
        warmup_s=a.warmup_s,
        fade_s=a.fade_s,
        workers=a.workers,
        progress=show("pieces"),
    )
    print()
    res["pieces_wall_s"] = time.time() - t0
    res["pieces_x_real_time"] = res["pieces_wall_s"] / audio_s
    yc = r.vectors["v(out)"][delay:] / v_out
    import soundfile as sf

    sf.write(OUT / f"{tag}_pieces.wav", yc.astype(np.float32), fs, subtype="FLOAT")
    if not a.skip_whole:
        sf.write(OUT / f"{tag}_whole.wav", yw.astype(np.float32), fs, subtype="FLOAT")
        sf.write(OUT / f"{tag}_diff.wav", (yc - yw).astype(np.float32), fs, subtype="FLOAT")
        n = min(len(yc), len(yw))
        res["bands_whole_db"] = float(np.abs(bands_db(yc[:n], fs) - bands_db(yw[:n], fs)).max())
        rms = float(np.sqrt(np.mean(yw[:n] ** 2)))
        seams = []
        for s0 in np.arange(1, math.ceil(len(u) / (a.chunk_s * fs))) * round(a.chunk_s * fs):
            s_out = int(s0) - delay  # the seam in the output's time (the delay removed)
            lo, hi = s_out - int(0.1 * fs), s_out + int(0.1 * fs)
            if lo < 0 or hi > n:
                continue
            d = yc[lo:hi] - yw[lo:hi]
            seams.append(
                {
                    "at_s": s_out / fs,
                    "bands_db": float(
                        np.abs(bands_db(yc[lo:hi], fs) - bands_db(yw[lo:hi], fs)).max()
                    ),
                    "diff_db_re_rms": 20 * math.log10(np.sqrt(np.mean(d**2)) / rms + 1e-30),
                    "peak_diff_db_re_rms": 20 * math.log10(np.abs(d).max() / rms + 1e-30),
                }
            )
        res["seams"] = seams
        if seams:
            seams_png(yc[:n], yw[:n], fs, [s["at_s"] for s in seams], OUT / f"{tag}_seams.png")
        # Away from the seams, for the floor between any two runs: 200 ms windows in the
        # pieces after the first (the first starts at t = 0 and is the whole print exactly),
        # 0.4 s clear of the seams.
        w = int(0.2 * fs)
        chunk = round(a.chunk_s * fs)
        floor = []
        for k in range(n // w):
            t = k * w + w // 2 + delay  # the window's middle in the input's time
            if t < chunk or min(t % chunk, chunk - t % chunk) < 0.4 * fs:
                continue
            d = yc[k * w : (k + 1) * w] - yw[k * w : (k + 1) * w]
            floor.append(20 * math.log10(np.sqrt(np.mean(d**2)) / rms + 1e-30))
        if floor:
            res["mid_chunk_diff_db_re_rms"] = {
                "median": float(np.median(floor)),
                "p90": float(np.percentile(floor, 90)),
                "max": float(np.max(floor)),
            }
    log = OUT / "results.json"
    allres = json.loads(log.read_text()) if log.exists() else {}
    allres[f"{tag}_c{a.chunk_s:g}_w{a.warmup_s:g}_j{a.workers}"] = res
    log.write_text(json.dumps(allres, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

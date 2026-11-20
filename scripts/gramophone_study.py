"""Shellac 78s from physics, end to end (docs/PHONO_PLAN.md G2; varimu/phono/gramophone.py):
program material played into the recording horn, cut laterally into a wax master (the
pressing taken as its exact copy), played on a Victor gramophone with the Exhibition
sound-box, a steel needle and a flower horn, heard 1 m from the horn's mouth.
-> reports/phono/gramophone/

- response.png / response.csv: the recorder (cutter excursion per incident pascal), the
  reproducer (pressure at 1 m per groove micrometre, the contacts linearized, a new
  needle) and the whole chain, small signals;
- audio/<clip>_dry.wav, audio/<clip>_<variant>.wav at 96 kHz. Variants:
  `smooth`  an ideal cut on ideal machines (no grain, exact 78 rpm, a true disc, no dust,
            the needle's point unworn): the acoustic chain alone, at the outer grooves;
  `played`  a used record on used machines: the shellac's grain, both machines' drives
            (the player's spring motor, governor and worm), an off-centre, dished disc,
            light dust, a new steel needle wearing as it plays;
  `worn`    the same with heavy dust, two scratches and a needle already through a side
            and a half (reused, as people did);
  `inner`   `played` cut near the label (the slower groove: tracing loss and distortion),
            the needle near a side's end, as it would be there.
  All matched to -20 dBFS rms (a level match only, not LUFS): compare character;
- pitch.png: the `played` take's pitch deviation (cents) from both drives;
- summary.json: levels, mistracking, wow, the needle's flat, the damage's counts.

    uv run --extra fast --extra listen python scripts/gramophone_study.py
        [--clips vocal_longwayhome mix_longwayhome] [--seconds 10] [--variants ...]
    ... --file SONG.wav [--start S] [--name NAME] [--seconds S | --whole]
    ... --pairs victor_exhibition:victor_exhibition victor_orthophonic:victor_orthophonic
            victor_exhibition:victor_orthophonic   (RECORDER:PLAYER; outputs
            <clip>_<acoustic78|electric78>_<player>_<variant>.wav)

A whole song is cut as one side from the outer groove inward (a side holds ~3 minutes).
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # threaded small solves ran ~100x slower

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from varimu.phono import gramophone as gr  # noqa: E402

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "phono" / "gramophone"
FS_OUT = 96000
P_REF = 2e-5
USED = {"surface": 1, "motion": 1, "damage": {}}
VARIANTS = {
    "smooth": {"surface": None, "motion": None, "damage": None, "needle_sides": None},
    "played": {**USED, "needle_sides": 0.0},
    "worn": {
        **USED,
        "damage": {"dust_per_m": 25.0, "scratches": 2.0},
        "needle_sides": 1.5,
    },
    "inner": {**USED, "needle_sides": 0.85, "start_radius_m": 0.068},
}


def clip_path(name: str, arg: str | None) -> Path:
    if arg:
        return Path(arg) / f"{name}.wav"
    return ROOT / "data" / "clips" / f"{name}.wav"


def excerpt(path: Path, seconds: float, start: float | None = None) -> tuple[np.ndarray, int]:
    x, fs = sf.read(path, dtype="float64", always_2d=True)
    x = x.mean(axis=1)
    n = int(seconds * fs)
    if len(x) <= n:
        return x, fs
    if start is not None:
        s = min(int(start * fs), len(x) - n)
    else:
        hop = fs // 2
        starts = np.arange(0, len(x) - n, hop)
        energy = [np.sum(x[s : s + n] ** 2) for s in starts]
        s = int(starts[int(np.argmax(energy))])
    seg = x[s : s + n].copy()
    fade = int(0.02 * fs)
    ramp = np.linspace(0, 1, fade)
    seg[:fade] *= ramp
    seg[-fade:] *= ramp[::-1]
    return seg, fs


def level_match(x: np.ndarray, rms_dbfs: float = -20.0) -> np.ndarray:
    rms = np.sqrt(np.mean(x**2)) or 1.0
    y = x * 10 ** (rms_dbfs / 20) / rms
    peak = np.max(np.abs(y))
    return y / peak * 0.99 if peak > 0.99 else y


def db(x):
    return 20 * np.log10(np.maximum(np.abs(x), 1e-30))


def responses(rec_spec: dict, play_spec: dict, tag: str) -> dict:
    f = np.geomspace(30, 12000, 500)
    rec = gr.recorder_response(rec_spec, f)
    rep = gr.reproducer_response(play_spec, f)
    chain = rec * rep
    OUT.mkdir(parents=True, exist_ok=True)
    np.savetxt(
        OUT / f"response_{tag}.csv",
        np.column_stack([f, db(rec * 1e6), db(rep * 1e-6), db(chain)]),
        delimiter=",",
        header="f_hz,recorder_db_um_per_pa,reproducer_db_pa_per_um,chain_db_pa_per_pa",
        comments="",
    )
    fig, axs = plt.subplots(3, 1, figsize=(9, 10), sharex=True)
    kind = "electrical" if gr.is_electrical(rec_spec) else "acoustic"
    for ax, y, title in (
        (axs[0], db(rec * 1e6), f"Recorder ({kind}): lateral cutter excursion (dB re 1 um/Pa)"),
        (axs[1], db(rep * 1e-6), "Gramophone: pressure at 1 m per groove um (dB re 1 Pa/um)"),
        (axs[2], db(chain), f"Chain ({tag}): pascals at 1 m per incident pascal (dB)"),
    ):
        ax.semilogx(f, y)
        ax.set_title(title, fontsize=10)
        ax.grid(True, which="both", alpha=0.3)
    i_pk = int(np.argmax(db(chain)))
    band = f[db(chain) >= db(chain)[i_pk] - 10]
    axs[2].axhspan(db(chain)[i_pk] - 10, db(chain)[i_pk], alpha=0.1)
    axs[2].set_xlabel("Hz")
    fig.tight_layout()
    fig.savefig(OUT / f"response_{tag}.png", dpi=110)
    plt.close(fig)
    nd = gr.needle(play_spec)
    return {
        "chain_peak_hz": float(f[i_pk]),
        "chain_within_10db_hz": [float(band.min()), float(band.max())],
        "needle_f0_hz": float(np.sqrt(nd.stiffness_n_m / nd.mass_kg) / (2 * np.pi)),
    }


def pitch_plot(cents: np.ndarray, fs: float, name: str) -> None:
    t = np.arange(len(cents)) / fs
    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.plot(t[::96], cents[::96], lw=0.8)
    ax.set_xlabel("s")
    ax.set_ylabel("cents")
    ax.set_title(f"{name}: pitch from both drives and the disc's eccentricity", fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / f"pitch_{name}.png", dpi=110)
    plt.close(fig)


def side_m(spec: dict) -> float:
    r = spec["record"]
    w = 2 * np.pi * spec["player"]["rpm"] / 60.0
    return spec["soundbox"]["side_s"] * w * 0.5 * (r["outer_radius_m"] + r["inner_radius_m"])


def pair_tag(rec_spec: dict, play_name: str) -> str:
    rec = "electric78" if gr.is_electrical(rec_spec) else "acoustic78"
    return f"{rec}_{play_name.removeprefix('victor_')}"


def whole(path: Path, start: float | None) -> tuple[np.ndarray, int]:
    """The whole file from `start` seconds (mono), faded in and out over 20 ms."""
    x, fs = sf.read(path, dtype="float64", always_2d=True)
    x = x.mean(axis=1)[int((start or 0.0) * fs) :].copy()
    fade = int(0.02 * fs)
    ramp = np.linspace(0, 1, fade)
    x[:fade] *= ramp
    x[-fade:] *= ramp[::-1]
    return x, fs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clips", nargs="+", default=["vocal_longwayhome", "mix_longwayhome"])
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--clips-dir")
    ap.add_argument("--file", help="an audio file to use instead of --clips")
    ap.add_argument("--start", type=float, help="the excerpt's start in --file (s)")
    ap.add_argument("--whole", action="store_true", help="--file from --start to its end")
    ap.add_argument("--name", help="the clip's name in outputs (default: the file's stem)")
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS))
    ap.add_argument(
        "--pairs",
        nargs="+",
        default=["victor_exhibition:victor_exhibition"],
        help="RECORDING_MACHINE:PLAYER (config/phono names): whose recorder cuts, who plays",
    )
    args = ap.parse_args()

    path_summary = OUT / "summary.json"
    old = json.loads(path_summary.read_text(encoding="utf-8")) if path_summary.exists() else {}
    summary: dict = {"responses": old.get("responses", {}), "takes": old.get("takes", {})}
    audio = OUT / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    if args.file:
        sources = [(args.name or Path(args.file).stem, Path(args.file))]
    else:
        sources = [(c, clip_path(c, args.clips_dir)) for c in args.clips]
    pairs = []
    for pair in args.pairs:
        rec_name, play_name = pair.split(":")
        rec_spec, play_spec = gr.load(rec_name), gr.load(play_name)
        tag = pair_tag(rec_spec, play_name)
        summary["responses"][tag] = responses(rec_spec, play_spec, tag)
        print(tag, "responses:", summary["responses"][tag], flush=True)
        pairs.append((tag, rec_spec, play_spec))
    for clip, path in sources:
        if args.whole:
            x, fs = whole(path, args.start)
        else:
            x, fs = excerpt(path, args.seconds, args.start)
        sf.write(audio / f"{clip}_dry.wav", level_match(x).astype(np.float32), fs)
        for tag, rec_spec, play_spec in pairs:
            for var in args.variants:
                cfg = VARIANTS[var]
                t0 = time.time()
                rec = gr.record(
                    rec_spec,
                    x,
                    fs,
                    start_radius_m=cfg.get("start_radius_m"),
                    motion_seed=cfg["motion"],
                )
                if rec.spiral.radius(rec.length_m) < rec_spec["record"]["inner_radius_m"]:
                    print(f"  {clip} {tag} {var}: runs past the label's radius (over a side)")
                counts = {}
                if cfg["surface"] is not None:
                    gr.surface(rec, rec_spec, cfg["surface"])
                if cfg["damage"] is not None:
                    counts = gr.age(rec, dict(rec_spec["damage"], **cfg["damage"]), 1)
                sides = cfg["needle_sides"]
                played_m = None if sides is None else sides * side_m(play_spec)
                pb = gr.play(play_spec, rec, motion_seed=cfg["motion"], needle_played_m=played_m)
                wall = time.time() - t0
                lead = rec.lead_in_samples
                p = pb.pressure_pa[lead:]
                y = gr.to_output_rate(p, pb.fs_hz, FS_OUT)
                name = f"{clip}_{tag}_{var}"
                sf.write(audio / f"{name}.wav", level_match(y).astype(np.float32), FS_OUT)
                incident = rec.pa_per_unit * np.sqrt(np.mean(x**2))
                cents = gr.pitch_cents(rec, pb)[lead:]
                take = {
                    "incident_spl_db_rms": float(db(incident / P_REF))
                    if not gr.is_electrical(rec_spec)
                    else None,
                    "spl_1m_db_rms": float(db(np.sqrt(np.mean(p**2)) / P_REF)),
                    "spl_1m_db_peak": float(db(np.max(np.abs(p)) / P_REF)),
                    "mistracking_fraction": float(
                        np.mean(np.any(pb.forces_n[:, lead:] <= 0.0, axis=0))
                    ),
                    "radius_m": [float(rec.spiral.r0_m), float(rec.spiral.radius(rec.length_m))],
                    "needle_flat_half_um": [
                        float(pb.flat_m[0] * 1e6),
                        float(pb.flat_m[-1] * 1e6),
                    ],
                    "wow_cents_rms": float(np.std(cents)),
                    "wow_cents_peak_to_peak": float(np.ptp(cents)),
                    "damage": counts,
                    "wall_s_per_audio_s": wall / (len(x) / fs),
                }
                if var == "played":
                    pitch_plot(cents, pb.fs_hz, name)
                summary["takes"][name] = take
                print(f"{name}: {take}", flush=True)
                path_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()

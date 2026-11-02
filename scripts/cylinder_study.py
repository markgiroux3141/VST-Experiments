"""A wax cylinder from physics, end to end (docs/PHONO_PLAN.md; varimu/phono/cylinder.py):
program material sung into the recording horn, cut into wax, played back on the
reproducer and its horn, heard 1 m from the horn's mouth. -> reports/phono/cylinder/

- response.png / response.csv: the recorder (cutter excursion per incident pascal), the
  reproducer (pressure at 1 m per groove displacement, the contact linearized) and the
  whole chain (pascals out per pascal in), small signals;
- audio/<clip>_dry.wav, audio/<clip>_<variant>.wav at 96 kHz. Variants:
  `smooth`  an ideal cut on ideal machines (perfectly smooth wax, exact 160 rpm, no dust):
            the acoustic chain alone;
  `played`  a used cylinder on used machines: the wax's roughness, both machines' drives
            (spring motors, governors, belts, the cylinder's runout: the wow), light dust;
  `worn`    the same, neglected and played 30 times before (wear.py): heavy dust, mould,
            a crack;
  `close`   `played` with the performer twice as loud at the horn (the cutter lifts out of
            the wax, the stylus leaves the groove).
  All matched to -20 dBFS rms (a level match only, not LUFS): compare character;
- pitch.png: the `played` take's pitch deviation (cents) from both machines' drives;
- tracking.png: the tip over the groove where the `close` take mistracks;
- summary.json: levels, mistracking, wow, the damage's counts.

    uv run python scripts/cylinder_study.py [--clips vocal_longwayhome mix_longwayhome]
        [--seconds 10] [--clips-dir DIR] [--variants smooth played worn close]
    uv run python scripts/cylinder_study.py --file SONG.mp3 [--start S] [--name NAME]

Under heavy load from other jobs, pin BLAS to one thread (OPENBLAS_NUM_THREADS=1).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from varimu.phono import cylinder as cy  # noqa: E402
from varimu.phono import damage as dm  # noqa: E402
from varimu.phono import transport as tr  # noqa: E402
from varimu.phono import wear as wr  # noqa: E402

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "phono" / "cylinder"
FS_OUT = 96000
P_REF = 2e-5
USED = {"surface": 1, "motion": 1, "damage": {}}
VARIANTS = {
    "smooth": {"drive": 1.0, "surface": None, "motion": None, "damage": None},
    "played": {"drive": 1.0, **USED},
    "worn": {
        "drive": 1.0,
        **USED,
        "damage": {"dust_per_m": 40.0, "mould_colonies_per_m": 2.0, "cracks": 1.0},
        "plays": 30,
    },
    "close": {"drive": 2.0, **USED},
}


def clip_path(name: str, arg: str | None) -> Path:
    if arg:
        return Path(arg) / f"{name}.wav"
    here = ROOT / "data" / "clips" / f"{name}.wav"
    if here.exists():
        return here
    # A worktree has no clips (git-ignored): use the main checkout's.
    return ROOT.parent / "VST Experiments" / "data" / "clips" / f"{name}.wav"


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


def responses(spec: dict) -> dict:
    f = np.geomspace(30, 12000, 500)
    rec = cy.recorder_response(spec, f)
    rep = cy.reproducer_response(spec, f)
    chain = rec * rep
    OUT.mkdir(parents=True, exist_ok=True)
    np.savetxt(
        OUT / "response.csv",
        np.column_stack([f, db(rec * 1e6), db(rep * 1e-6), db(chain)]),
        delimiter=",",
        header="f_hz,recorder_db_um_per_pa,reproducer_db_pa_per_um,chain_db_pa_per_pa",
        comments="",
    )
    fig, axs = plt.subplots(3, 1, figsize=(9, 10), sharex=True)
    for ax, y, title in (
        (axs[0], db(rec * 1e6), "Recorder: cutter excursion per incident pascal (dB re 1 um/Pa)"),
        (axs[1], db(rep * 1e-6), "Reproducer: pressure at 1 m per groove um (dB re 1 Pa/um)"),
        (axs[2], db(chain), "Chain: pascals at 1 m per incident pascal (dB)"),
    ):
        ax.semilogx(f, y)
        ax.set_title(title, fontsize=10)
        ax.grid(True, which="both", alpha=0.3)
    i_pk = int(np.argmax(db(chain)))
    band = f[db(chain) >= db(chain)[i_pk] - 10]
    axs[2].axhspan(db(chain)[i_pk] - 10, db(chain)[i_pk], alpha=0.1)
    axs[2].set_xlabel("Hz")
    fig.tight_layout()
    fig.savefig(OUT / "response.png", dpi=110)
    plt.close(fig)
    return {
        "chain_peak_hz": float(f[i_pk]),
        "chain_within_10db_hz": [float(band.min()), float(band.max())],
        "recorder_diaphragm_f0_hz": cy._rec_diaphragm(spec).f0_hz,
        "reproducer_diaphragm_f0_hz": cy._rep_diaphragm(spec).f0_hz,
    }


def pitch_plot(cents: np.ndarray, fs: float, name: str) -> None:
    t = np.arange(len(cents)) / fs
    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.plot(t[::48], cents[::48], lw=0.8)
    ax.set_xlabel("s")
    ax.set_ylabel("cents")
    ax.set_title(f"{name}, played: pitch from both machines' drives (wow)", fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "pitch.png", dpi=110)
    plt.close(fig)


def tracking_plot(pb: cy.Playback, lead: int, name: str) -> None:
    flights = np.flatnonzero(pb.force_n[lead:] <= 0.0)
    if not len(flights):
        return
    c = lead + int(flights[len(flights) // 2])
    w = int(0.004 * pb.fs_hz)
    sl = slice(max(c - w, 0), c + w)
    t = (np.arange(sl.start, sl.stop) - lead) / pb.fs_hz * 1e3
    fig, axs = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    axs[0].plot(t, pb.surface_m[sl] * 1e6, label="groove under the tip (dilated)")
    axs[0].plot(t, pb.tip_m[sl] * 1e6, label="tip", lw=0.9)
    axs[0].set_ylabel("um")
    axs[0].legend(fontsize=8)
    axs[1].plot(t, pb.force_n[sl])
    axs[1].set_ylabel("contact force (N)")
    axs[1].set_xlabel("ms")
    axs[0].set_title(f"{name}: the tip leaving the groove", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "tracking.png", dpi=110)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clips", nargs="+", default=["vocal_longwayhome", "mix_longwayhome"])
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--clips-dir")
    ap.add_argument(
        "--file", help="an audio file to use instead of --clips (any format soundfile reads)"
    )
    ap.add_argument(
        "--start", type=float, help="the excerpt's start in --file (s); default its loudest window"
    )
    ap.add_argument("--name", help="the clip's name in outputs (default: the file's stem)")
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS))
    args = ap.parse_args()

    spec = cy.load()
    summary: dict = {"responses": responses(spec), "takes": {}}
    print("responses:", summary["responses"], flush=True)
    audio = OUT / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    if args.file:
        name = args.name or Path(args.file).stem
        sources = [(name, Path(args.file))]
    else:
        sources = [(c, clip_path(c, args.clips_dir)) for c in args.clips]
    for clip, path in sources:
        x, fs = excerpt(path, args.seconds, args.start)
        sf.write(audio / f"{clip}_dry.wav", level_match(x).astype(np.float32), fs)
        for var in args.variants:
            cfg = VARIANTS[var]
            t0 = time.time()
            rec = cy.record(
                spec,
                x,
                fs,
                drive=cfg["drive"],
                surface_seed=cfg["surface"],
                motion_seed=cfg["motion"],
            )
            uncut = float(np.mean(spec["cylinder"]["cut_depth_m"] + rec.z_m < 0.0))
            counts = {}
            if cfg["damage"] is not None:
                d = dict(spec["damage"], **cfg["damage"])
                circ = np.pi * spec["cylinder"]["diameter_m"]
                counts = dm.age(rec.groove, d, 1, circ)
            if cfg.get("plays"):
                counts["plays"] = wr.wear(rec.groove, spec, cfg["plays"])["plays"]
            pb = cy.play(spec, rec.groove, motion_seed=cfg["motion"])
            wall = time.time() - t0
            lead = rec.lead_in_samples
            p = pb.pressure_pa[lead:]
            y = cy.to_output_rate(p, pb.fs_hz, FS_OUT)
            sf.write(audio / f"{clip}_{var}.wav", level_match(y).astype(np.float32), FS_OUT)
            incident = rec.pa_per_unit * np.sqrt(np.mean(x**2))
            cents = tr.pitch_cents(rec.motion, pb.motion, rec.groove.length_m)[lead:]
            take = {
                "incident_spl_db_rms": float(db(incident / P_REF)),
                "spl_1m_db_rms": float(db(np.sqrt(np.mean(p**2)) / P_REF)),
                "spl_1m_db_peak": float(db(np.max(np.abs(p)) / P_REF)),
                "mistracking_fraction": float(np.mean(pb.force_n[lead:] <= 0.0)),
                "uncut_fraction": uncut,
                "wow_cents_rms": float(np.std(cents)),
                "wow_cents_peak_to_peak": float(np.ptp(cents)),
                "damage": counts,
                "wall_s_per_audio_s": wall / (len(x) / fs),
            }
            if var == "played" and clip == args.clips[0]:
                pitch_plot(cents, pb.fs_hz, clip)
            summary["takes"][f"{clip}_{var}"] = take
            print(f"{clip} {var}: {take}", flush=True)
            if var == "close" and clip == args.clips[0]:
                tracking_plot(pb, lead, f"{clip}, close")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()

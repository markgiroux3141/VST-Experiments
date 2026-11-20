"""The 1960s record player end to end (docs/PHONO_PLAN.md, "The 1960s record player"): a song
cut on the Westrex 3D lathe into a stereo LP (varimu/phono/lp.py), pressed, played on the GE
RP1560's changer and Sonotone cartridge (varimu/phono/portable.py) into its amplifier
(config/circuits/ge_rp1560.yaml): the wings' sound pressure, L and R.

Variants: `smooth` (a perfect pressing on a perfect turntable: the machines' sound alone),
`played` (the vinyl's surface, dust and non-fill; the changer's rim drive, the record's warp and
off-centre hole, the motor's rumble). Writes WAVs loudness-matched (-20 dBFS rms) with the dry
source, and summary.json, to reports/phono/record_player/.

    uv run --extra fast --extra listen python scripts/record_player_study.py \\
        --file "assets/songs/Lead Belly - In the pines.mp3" --start 1.0 --name in_the_pines
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.config import CONFIG_DIR  # noqa: E402
from varimu.phono import lp  # noqa: E402
from varimu.phono import portable as po  # noqa: E402
from varimu.sim import fast  # noqa: E402
from varimu.sim.io import TransientSettings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "phono" / "record_player"
FS_OUT = 48000


def load_song(path: Path, start_s: float, seconds: float | None):
    x, fs = sf.read(str(path), always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    x = x[int(start_s * fs) :]
    if seconds:
        x = x[: int(seconds * fs)]
    fade = int(0.01 * fs)
    ramp = 0.5 * (1 - np.cos(np.pi * np.arange(fade) / fade))
    x[:fade] *= ramp[:, None]
    x[-fade:] *= ramp[::-1, None]
    return x[:, :2], fs


def amplifier(emf: np.ndarray, fs_hz: float, quality: str) -> np.ndarray:
    """The GE's amplifier on the elements' EMFs (2, n) at fs_hz: the wings' pressure (2, n')
    at the engine's output rate."""
    c = spec.load_circuit(CONFIG_DIR / "circuits" / "ge_rp1560.yaml")
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    sr = st.sample_rate
    x = np.stack([resample_poly(e, int(sr), int(fs_hz)) for e in emf])  # volts
    ir = builder.build(c, spec.resolve(c, {})).ir
    r = fast.run_transient(ir, x[0], settings=st, controls={"in_r": x[1]})
    return np.stack([r.vectors["v(out)"], r.vectors["v(out_r)"]]), sr


def rms_db(x) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-30))


def write_matched(path: Path, y: np.ndarray, fs: int, target_db: float = -20.0) -> None:
    g = 10 ** ((target_db - rms_db(y)) / 20)
    sf.write(str(path), (y * g).T.astype(np.float32), fs, subtype="FLOAT")


def band_db(y: np.ndarray, fs: float, edges=(63, 125, 250, 500, 1000, 2000, 4000, 8000)):
    m = y.mean(axis=0)
    f = np.fft.rfftfreq(len(m), 1 / fs)
    p = np.abs(np.fft.rfft(m)) ** 2
    tot = p.sum()
    out = {}
    for fc in edges:
        b = (f >= fc / np.sqrt(2)) & (f < fc * np.sqrt(2))
        out[str(fc)] = float(10 * np.log10(p[b].sum() / tot + 1e-30))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--variants", nargs="+", default=["smooth", "played"])
    ap.add_argument("--quality", default="production")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    audio = OUT / "audio"
    audio.mkdir(exist_ok=True)
    rs, ps = lp.load(), po.load()
    x, fs_in = load_song(ROOT / args.file, args.start, args.seconds)
    write_matched(audio / f"{args.name}_dry.wav", resample_poly(x, FS_OUT, fs_in, axis=0).T, FS_OUT)
    t0 = time.time()
    cp = lp.card(rs)
    ps = po.calibrate(ps, rs)
    summary = {}
    for variant in args.variants:
        played = variant == "played"
        t = time.time()
        rec = lp.record(rs, x, fs_in, cp, motion_seed=args.seed if played else None)
        t_cut = time.time() - t
        counts = lp.press(rec, rs, args.seed) if played else {}
        t = time.time()
        pb = po.play(ps, rs, rec, motion_seed=args.seed if played else None)
        t_play = time.time() - t
        lead = int(0.25 * pb.fs_hz)
        emf = pb.emf_v[:, lead:]
        t = time.time()
        y, sr = amplifier(emf, pb.fs_hz, args.quality)
        t_amp = time.time() - t
        settle = int(0.05 * sr)
        y = y[:, settle:]
        yo = resample_poly(y, FS_OUT, int(sr), axis=1)
        write_matched(audio / f"{args.name}_{variant}.wav", yo, FS_OUT)
        seconds = emf.shape[1] / pb.fs_hz
        mid, side = (emf[0] + emf[1]) / 2, (emf[0] - emf[1]) / 2
        summary[variant] = {
            "seconds": seconds,
            "spl_db_left": rms_db(y[0] / 2e-5),
            "spl_db_right": rms_db(y[1] / 2e-5),
            "emf_rms_v": [float(np.std(e)) for e in emf],
            "emf_side_to_mid_db": rms_db(side) - rms_db(mid),
            "peak_cut_velocity_cm_s": rec.peak_velocity_m_s * 100,
            "lift_out": rec.lift_out,
            "radius_m": [float(rec.spiral.r_m[0]), float(rec.spiral.r_m[-1])],
            "mistracking": pb.mistracking_fraction(),
            "wall_force_mean_n": [float(f) for f in pb.forces_n.mean(axis=1)],
            "bands_db": band_db(yo, FS_OUT),
            "pressing": {k: float(v) for k, v in counts.items()},
            "speed_x_realtime": {
                "cut": t_cut / seconds,
                "play": t_play / seconds,
                "amp": t_amp / seconds,
            },
        }
        print(variant, json.dumps(summary[variant], indent=1))
    summary["dry_bands_db"] = band_db(resample_poly(x, FS_OUT, fs_in, axis=0).T, FS_OUT)
    path = OUT / f"summary_{args.name}.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"-> {path} ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()

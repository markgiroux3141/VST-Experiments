"""A source recorded through a microphone chain in free field (MIC_ROOM_PLAN.md A3: the
U47 -> V76 first listen) -> reports/mics/audio/.

    uv run --extra fast python scripts/mic_print.py --circuit u47_v76 --clip FILE \
        [--start S] [--seconds N] [--spl-db 94] [--angle-deg 0] [--set k=v ...] [--draft]

The clip (mono, any rate) is the sound pressure at the capsule's centre, scaled to
`--spl-db` (its rms in dB SPL, re 20 uPa); a plane wave from `--angle-deg` gives the
capsule's front and rear entries (varimu.mics.free_field: on a rigid sphere, its
diffraction, when the capsule component gives one, else a path delay apart), the front on
the circuit's input, the rear on its control input `p_rear` (a pressure capsule has none).
The chain renders at production quality (`--draft` for the draft), and the output (the
circuit's `out`, volts)
is written as float32 WAV normalized to its full scale, with the dry source beside it at
the same loudness for comparison (LUFS-matched: "loudness lies").
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.devices.library import component_data
from varimu.mics.free_field import entry_pressures, sphere_entry_pressures
from varimu.sim import fast
from varimu.sim.io import TransientSettings, full_scale, load_audio, write_audio

P_REF = 20e-6
OUT_DIR = REPO_ROOT / "reports" / "mics" / "audio"


def _entries(q, p: np.ndarray, theta_rad: float, fs: int):
    """The capsule's front and rear entry pressures for a plane wave whose pressure at its
    centre is `p`: on a rigid sphere when the capsule component gives one
    (`sphere_radius_m`: varimu.mics.free_field.sphere_entry_pressures), else `path_m`
    apart in free field (0 for a pressure capsule)."""
    for key in ("capsule_model_u47", "capsule_model"):
        if key in q:
            g = component_data(str(q[key])).get("geometry", {})
            if "sphere_radius_m" in g:
                sph = (g["sphere_radius_m"], g["diaphragm"]["radius_m"])
                return (*sphere_entry_pressures(p, theta_rad, *sph, fs), f"sphere {sph}")
            path = float(g.get("path_m", 0.0) or 0.0)
            return (*entry_pressures(p, theta_rad, path, fs), f"path {path}")
    return p, p, "pressure"


def _lufs(x: np.ndarray, fs: int) -> float:
    try:
        import pyloudnorm

        return float(pyloudnorm.Meter(fs).integrated_loudness(x))
    except ImportError:  # the listen extra: rms in its place
        return float(20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-12))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--circuit", default="u47_v76")
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--spl-db", type=float, default=94.0)
    ap.add_argument("--angle-deg", type=float, default=0.0)
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    ap.add_argument("--draft", action="store_true")
    args = ap.parse_args()

    c = spec.load_circuit(spec.circuit_path(args.circuit))
    over = {}
    for kv in args.set:
        k, v = kv.split("=", 1)
        over[k] = float(v)
    q = spec.resolve(c, over)
    s = TransientSettings.from_sim_settings(
        engine="circuitsim", quality="draft" if args.draft else None
    )
    fs = s.sample_rate
    x = load_audio(args.clip, fs)
    x = x[int(args.start * fs) : int((args.start + args.seconds) * fs)]
    x = x - np.mean(x)
    p = x * (P_REF * 10 ** (args.spl_db / 20) / np.sqrt(np.mean(x**2)))
    front, rear, field = _entries(q, p, np.radians(args.angle_deg), fs)
    ir = builder.build(c, over).ir
    controls = {"p_rear": rear} if any(k.name == "p_rear" for k in ir.controls) else None
    t0 = time.perf_counter()
    v = fast.run_transient(ir, front, settings=s, controls=controls).vectors["v(out)"]
    wall = time.perf_counter() - t0
    out_fs = full_scale(s, c)[1]
    y = v / out_fs
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = "_".join([args.circuit, args.clip.stem, f"{args.spl_db:g}db", f"{args.angle_deg:g}deg"]
                   + [kv.replace("=", "") for kv in args.set])  # fmt: skip
    write_audio(OUT_DIR / f"{tag}.wav", y.astype(np.float32), fs)
    dry = x * 10 ** ((_lufs(y, fs) - _lufs(x, fs)) / 20)
    write_audio(OUT_DIR / f"{args.clip.stem}_dry.wav", dry.astype(np.float32), fs)
    info = {
        "circuit": args.circuit,
        "clip": str(args.clip),
        "spl_db": args.spl_db,
        "angle_deg": args.angle_deg,
        "field": field,
        "overrides": over,
        "out_peak_dbfs": round(float(20 * np.log10(np.max(np.abs(y)) + 1e-12)), 2),
        "out_rms_v": round(float(np.sqrt(np.mean(v**2))), 5),
        "x_real_time": round(wall / (len(p) / fs), 2),
    }
    (OUT_DIR / f"{tag}.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()

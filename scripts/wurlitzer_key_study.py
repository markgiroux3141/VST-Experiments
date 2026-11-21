"""WZ1's study: single Wurlitzer 200A keys struck offline, against the Pie-finger set
(docs/WURLITZER_PLAN.md, WZ1; "Reference: the Pie-finger set").

    uv run python scripts/wurlitzer_key_study.py [--fit] [--keys 4 28 52]

- measures the Pie-finger long notes (pitch, the fundamental's decay, harmonics 2-5 re the
  fundamental 0.15-0.65 s in, the peak level) -> reports/wurlitzer/key/reference.json;
- `--fit`: the voicing and one hammer speed per Pie-finger layer (low / mid / high, hand
  struck) fitted to those harmonics on the fit keys (least squares in dB, only harmonics
  the recording holds above -60 dB re its fundamental), written to
  reports/wurlitzer/key/fit.json; the strikes below then use them;
- strikes each study key at the three speeds: the plate's voltage (WAVs at 48 kHz, 0 dBFS =
  `numerics.full_scale_v`), harmonics and level against the recording, the contact, the
  reed's swing, its second mode -> reports/wurlitzer/key/{summary.json, README.md, audio/}.

The recording went through the 200A's preamp and AUX output, which WZ1 doesn't model: only
ratios at one time (harmonics re the fundamental, levels re the middle layer) are compared.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import optimize, signal

from varimu.config import REPO_ROOT
from varimu.wurlitzer import key as ky
from varimu.wurlitzer import reed as rd
from varimu.wurlitzer import spec as sp

SAMPLES = (
    REPO_ROOT
    / "real instrument samples"
    / "Pie-finger Wurlitzer 200A sample set"
    / "Pie-finger Wurlitzer 200A sample set"
)
OUT = REPO_ROOT / "reports" / "wurlitzer" / "key"
FS = 48000.0
LAYERS = ("low", "mid", "high")
NOTE = {
    "C": 0,
    "C#": 1,
    "D": 2,
    "D#": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "G": 7,
    "G#": 8,
    "A": 9,
    "A#": 10,
    "B": 11,
}
FIT_KEYS = (4, 10, 15, 28, 34, 39, 52, 58, 63)  # C2 F#2 B2, C4 F#4 B4, C6 F#6 B6
FLOOR_DB = -60.0


def harmonics(
    y: np.ndarray, fs: float, f0: float, a_s: float = 0.15, b_s: float = 0.65
) -> tuple[float, list[float]]:
    """The fundamental's frequency (a parabolic peak near f0) and harmonics 2-5 in dB re it."""
    a, b = int(a_s * fs), int(b_s * fs)
    seg = y[a:b] * np.hanning(b - a)
    nfft = 1 << 21
    s = np.abs(np.fft.rfft(seg, nfft))
    fr = np.fft.rfftfreq(nfft, 1 / fs)

    def peak(f: float, w: float) -> tuple[float, float]:
        lo, hi = np.searchsorted(fr, [f * (1 - w), f * (1 + w)])
        k = lo + int(np.argmax(s[lo:hi]))
        y0, y1, y2 = np.log(s[k - 1 : k + 2] + 1e-30)
        d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
        return fr[k] + d * (fr[1] - fr[0]), s[k]

    f1, a1 = peak(f0, 0.05)
    return f1, [float(20 * np.log10(peak(h * f1, 0.01)[1] / a1)) for h in range(2, 6)]


def decay_db_s(y: np.ndarray, fs: float, f0: float) -> float | None:
    sos = signal.butter(4, [f0 * 0.8, f0 * 1.2], "bandpass", fs=fs, output="sos")
    z = signal.sosfiltfilt(sos, y)
    blk = int(0.05 * fs)
    m = z.size // blk
    env = 20 * np.log10(np.sqrt(np.mean(z[: m * blk].reshape(m, blk) ** 2, axis=1)) + 1e-12)
    t = (np.arange(m) + 0.5) * 0.05
    tail = env[-4:].mean()
    sel = (t > 0.2) & (env > env.max() - 40) & (env > tail + 6)
    if sel.sum() < 5:
        return None
    return float(np.polyfit(t[sel], env[sel], 1)[0])


def measure() -> dict:
    """The Pie-finger long notes: per (key, layer) pitch, decay, harmonics, peak."""
    out = {}
    for layer in LAYERS:
        for p in sorted((SAMPLES / "Long notes" / f"{layer.capitalize()} vel").glob("*.wav")):
            m = re.search(r"-([A-G]#?)(\d)\.wav$", p.name)
            midi = 12 * (int(m.group(2)) + 1) + NOTE[m.group(1)]
            n = midi - 32
            y, fs = sf.read(p)
            on = int(np.argmax(np.abs(y) > 0.1 * np.max(np.abs(y))))
            y = y[on:]
            f1, h = harmonics(y, fs, sp.note_hz(n) * 2 ** (5 / 1200))
            out[f"{n}:{layer}"] = {
                "key": n,
                "layer": layer,
                "midi": midi,
                "f0_hz": f1,
                "cents": 1200 * np.log2(f1 / sp.note_hz(n)),
                "harmonics_db": h,
                "decay_db_s": decay_db_s(y, fs, f1),
                "peak_db": float(20 * np.log10(np.max(np.abs(y)))),
            }
    return out


def model_key(n: int, voicing: float | None = None) -> sp.Key:
    k = sp.key(n)
    return k if voicing is None else replace(k, voicing_m=voicing)


def model_harmonics(n: int, speed: float, voicing: float) -> tuple[list[float], float]:
    s = ky.strike(model_key(n, voicing), speed, duration_s=0.7, fs_hz=FS, oversample=8)
    _, h = harmonics(s.plate_v, FS, sp.note_hz(n))
    return h, float(20 * np.log10(np.max(np.abs(s.plate_v))))


def _model_job(job: tuple[int, float, float]) -> list[float]:
    return model_harmonics(*job)[0]


def fit(ref: dict) -> dict:
    """Voicing and three speeds: least squares on the harmonics above FLOOR_DB (the strikes
    of one evaluation on a process pool)."""
    import os
    from concurrent.futures import ProcessPoolExecutor

    sp.plate_f()  # every blank's field map solved here first, not once per worker
    pool = ProcessPoolExecutor(max(1, min(6, (os.cpu_count() or 2) - 2)))

    def resid(p: np.ndarray) -> np.ndarray:
        vo = p[0] * 1e-3
        speeds = np.exp(p[1:])
        jobs = [(n, float(spd), vo) for n in FIT_KEYS for spd in speeds]
        mods = list(pool.map(_model_job, jobs))
        r = []
        for (n, _, _), layer, mod in zip(jobs, LAYERS * len(FIT_KEYS), mods, strict=True):
            real = ref[f"{n}:{layer}"]["harmonics_db"]
            r += [m_ - r_ for m_, r_ in zip(mod, real, strict=True) if r_ > FLOOR_DB]
        e = np.array(r)
        print(
            f"  voicing {vo * 1e3:.3f} mm speeds {np.round(speeds, 3)} -> "
            f"rms {np.sqrt(np.mean(e**2)):.2f} dB",
            flush=True,
        )
        return np.clip(e, -40, 40)

    p0 = np.array([0.6, np.log(0.5), np.log(1.2), np.log(2.5)])
    with pool:
        res = optimize.least_squares(
            resid,
            p0,
            diff_step=0.05,
            max_nfev=20,
            bounds=([0.0] + [np.log(0.05)] * 3, [3.0] + [np.log(10.0)] * 3),
        )
    e = res.fun
    return {
        "voicing_m": float(res.x[0] * 1e-3),
        "speeds_m_s": [float(v) for v in np.exp(res.x[1:])],
        "rms_db": float(np.sqrt(np.mean(e**2))),
        "keys": list(FIT_KEYS),
        "floor_db": FLOOR_DB,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--keys", type=int, nargs="*", default=list(FIT_KEYS))
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "audio").mkdir(exist_ok=True)
    ref = measure()
    (OUT / "reference.json").write_text(json.dumps(ref, indent=1))
    cfg = sp.load()
    fit_path = OUT / "fit.json"
    voicing = None  # each key's own (the config's per register, WZ3)
    speeds = cfg["velocity"]["layer_speeds_m_s"]
    if args.fit:
        print("fitting one voicing and the layers' speeds (WZ1) ...", flush=True)
        f = fit(ref)
        fit_path.write_text(json.dumps(f, indent=1))
        voicing, speeds = f["voicing_m"], f["speeds_m_s"]
    rows = []
    for n in args.keys:
        k = model_key(n, voicing)
        fe = rd.assemble(k.reed)
        md = rd.modes(fe, count=3)
        row = {
            "key": n,
            "f_hz": k.f_hz,
            "length_mm": k.reed.length_m * 1e3,
            "tip_mass_g": k.reed.tip_mass_kg * 1e3,
            "q": 1 / k.reed.loss,
            "mode2_ratio": float(md.f_hz[1] / md.f_hz[0]),
            "electrostatic_cents": ky.electrostatic_shift_cents(k),
            "layers": {},
        }
        for layer, spd in zip(LAYERS, speeds, strict=True):
            s = ky.strike(k, spd, duration_s=2.0, fs_hz=FS, oversample=8)
            _, h = harmonics(s.plate_v, FS, k.f_hz)
            real = ref.get(f"{n}:{layer}")
            row["layers"][layer] = {
                "speed_m_s": spd,
                "contact_ms": s.contact_s * 1e3,
                "max_force_n": s.max_force_n,
                "strikes": s.strikes,
                "tip_swing_mm": float(np.max(np.abs(s.tip_m)) * 1e3),
                "off_map_s": s.off_map_s,
                "peak_dbv": float(20 * np.log10(np.max(np.abs(s.plate_v)))),
                "harmonics_db": h,
                "decay_db_s": decay_db_s(s.plate_v, FS, k.f_hz),
                "real": None
                if real is None
                else {kk: real[kk] for kk in ("harmonics_db", "decay_db_s", "peak_db", "cents")},
            }
            sf.write(
                OUT / "audio" / f"key{n:02d}_{layer}.wav",
                (s.plate_v / k.full_scale_v).astype(np.float32),
                int(FS),
                subtype="FLOAT",
            )
        rows.append(row)
        print(
            f"key {n}: L {row['length_mm']:.1f} mm, mode 2 {row['mode2_ratio']:.2f} x f0",
            flush=True,
        )
    (OUT / "summary.json").write_text(
        json.dumps({"voicing_m": voicing, "speeds_m_s": speeds, "keys": rows}, indent=1)
    )
    write_readme(rows, voicing, speeds, fit_path)


def write_readme(rows: list, voicing: float | None, speeds: list, fit_path: Path) -> None:
    what = (
        f"Voicing {voicing * 1e3:.3f} mm on every key (WZ1's fit: fit.json)"
        if voicing is not None
        else "Each key's voicing and hammer from the config (per register, WZ3)"
    )
    lines = [
        "# WZ1: single keys against the Pie-finger set",
        "",
        "Generated by `scripts/wurlitzer_key_study.py` (docs/WURLITZER_PLAN.md, WZ1). The",
        "model's output is the plate's AC voltage (WZ1's load, no preamp); the recording went",
        "through the 200A's preamp and AUX output, so only ratios are compared (WZ3's",
        "comparison through the circuit: reports/wurlitzer/registers/).",
        "",
        f"{what}; hammer speeds (low / mid / high) {', '.join(f'{v:.3f}' for v in speeds)} m/s.",
        "",
        "| Key | f0 Hz | L mm | lead g | mode 2 / f0 | layer | contact ms | swing mm "
        "| H2-H5 model (dB re f0) | H2-H5 real | level re mid, model / real |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        mid_m = r["layers"]["mid"]["peak_dbv"]
        mid_r = r["layers"]["mid"]["real"]["peak_db"] if r["layers"]["mid"]["real"] else None
        for layer in LAYERS:
            L = r["layers"][layer]
            real = L["real"]
            hr = " / ".join(f"{v:.0f}" for v in real["harmonics_db"]) if real else "-"
            lv = f"{L['peak_dbv'] - mid_m:+.1f} / " + (
                f"{real['peak_db'] - mid_r:+.1f}" if real and mid_r is not None else "-"
            )
            hm = " / ".join(f"{v:.0f}" for v in L["harmonics_db"])
            lines.append(
                f"| {r['key']} | {r['f_hz']:.1f} | {r['length_mm']:.1f} | {r['tip_mass_g']:.3f} "
                f"| {r['mode2_ratio']:.2f} | {layer} | {L['contact_ms']:.2f} "
                f"| {L['tip_swing_mm']:.2f} | {hm} | {hr} | {lv} |"
            )
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

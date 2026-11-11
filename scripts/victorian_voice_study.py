"""The Victorian synth's 1881 voice measured (docs/VICTORIAN_SYNTH_PLAN.md, V1-V3)
-> reports/victorian/voice/ (summary.json, plots, WAVs).

    uv run --extra fast --extra listen python scripts/victorian_voice_study.py [--only NAME ...]

Studies (renders at the draft quality, the circuit as the app plays it, JA cores):
- `demo`: a 4-key chord with a run over it, and the same at CUTOFF 0 / 1 (WAVs, float, peak
  -1 dBFS each; the sound pressure 0.3 m in front of Bell's receiver);
- `velocity`: one key (A3) struck at velocities 10-127: the output's level (dB re the loudest)
  and the line's current (the carbon's law through the key's force);
- `cutoff`: a held C major chord at CUTOFF 0-1: the output's spectral centroid and level (the
  reactor's iron biased toward saturation lowers its inductance);
- `sag`: 1, 4 and 8 keys held for 4 s: the local battery's and the line's volts (the cells'
  ohmic drop and polarization), and the pitch a reed (the reference, varimu/victorian/reed.py)
  runs at on the local battery's sagged volts against the nominal 2.8 V;
- `breaker`: the reeds at the live rate (8 x 96 kHz) against the reference rate (64 x): pitch
  and the line current's harmonics to 20 kHz (V1's "the breaker's exception matches its
  reference within stated bounds").
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from varimu.circuit import builder  # noqa: E402
from varimu.circuit.spec import circuit_path, load_circuit  # noqa: E402
from varimu.sim import fast  # noqa: E402
from varimu.sim.io import TransientSettings  # noqa: E402
from varimu.victorian import compile as vcompile  # noqa: E402
from varimu.victorian import reed  # noqa: E402

OUT = REPO / "reports" / "victorian" / "voice"
FS = 96000
CHORD = [48, 55, 60, 64, 67, 72, 76, 79]
RUN = [72, 74, 76, 79, 81, 79, 76, 72]


def render(
    seconds: float, notes: list, cutoff: float | None = None, probes: bool = False
) -> dict[str, np.ndarray]:
    spec = load_circuit(circuit_path("victorian_voice"))
    overrides = None if cutoff is None else {"cutoff": cutoff}
    ir = builder.build(spec, overrides, cores="ja").ir
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    s = dataclasses.replace(s, cores="ja")
    res = fast.run_transient(ir, np.zeros(int(seconds * FS)), settings=s, notes=sorted(notes))
    return {k: np.asarray(v) for k, v in res.vectors.items()}


def phrase(seconds: float, chord_keys: int = 4) -> list:
    ev = [(0.2, "on", n, 90) for n in CHORD[:chord_keys]]
    t, i = 1.2, 0
    while t < seconds - 1.0:
        n = RUN[i % len(RUN)]
        ev += [(t, "on", n, 100), (t + 0.3, "off", n, 0)]
        t, i = t + 0.35, i + 1
    ev += [(seconds - 1.0, "off", n, 0) for n in CHORD[:chord_keys]]
    return ev


def wav(name: str, x: np.ndarray) -> None:
    import soundfile as sf

    y = x / max(np.max(np.abs(x)), 1e-12) * 10 ** (-1 / 20)
    sf.write(OUT / f"{name}.wav", y.astype(np.float32), FS, subtype="FLOAT")


def db(x: float) -> float:
    return 20 * math.log10(max(x, 1e-30))


def centroid(x: np.ndarray) -> float:
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / FS)
    return float(np.sum(f * X) / np.sum(X))


def study_demo(summary: dict) -> None:
    for name, cutoff in (("demo", None), ("demo_cutoff_0", 0.0), ("demo_cutoff_1", 1.0)):
        r = render(8.0, phrase(8.0), cutoff)
        wav(name, r["v(out)"])
        summary.setdefault("demo", {})[name] = {
            "peak_pa": float(np.max(np.abs(r["v(out)"]))),
            "line_min_v": float(np.min(r["v(line)"])),
            "loc_min_v": float(np.min(r["v(loc)"])),
        }


def study_velocity(summary: dict) -> None:
    rows = []
    for vel in (10, 20, 40, 64, 90, 110, 127):
        r = render(0.8, [(0.05, "on", 57, vel)])
        seg = slice(int(0.4 * FS), int(0.75 * FS))
        rows.append(
            {
                "velocity": vel,
                "out_rms_pa": float(np.std(r["v(out)"][seg])),
                "line_rms_a": float(np.std(r["v(ok)"][seg])),
            }
        )
    top = rows[-1]["out_rms_pa"]
    for row in rows:
        row["out_db"] = db(row["out_rms_pa"] / top)
    summary["velocity"] = rows


def study_cutoff(summary: dict) -> None:
    rows = []
    for c in (0.0, 0.25, 0.5, 0.75, 1.0):
        r = render(1.0, [(0.05, "on", n, 100) for n in (48, 52, 55, 60)], c)
        seg = r["v(out)"][int(0.5 * FS) : int(0.95 * FS)]
        rows.append({"cutoff": c, "centroid_hz": centroid(seg), "rms_pa": float(np.std(seg))})
    summary["cutoff"] = rows


def _pitch_at(args: tuple[int, float]) -> float:
    note, v_loc = args
    cfg = reed.load_cfg()
    data = vcompile.load(vcompile.latest())
    lo = data["keys"][0]["note"]
    p = vcompile.from_data(data["keys"][note - lo])
    o = reed.run(p, 0.9, v_loc, 6.0, [(0.0, "on", 100)], probes=True)
    f = reed.pitch_hz(o["x"])
    return 1200 * math.log2(f / vcompile.note_hz(cfg, note))


def study_sag(summary: dict) -> None:
    rows = []
    for k in (1, 4, 8):
        r = render(4.2, [(0.1, "on", n, 100) for n in CHORD[:k]])
        t = np.arange(len(r["v(loc)"])) / FS
        at = [0.5, 2.0, 4.0]
        loc = [float(np.interp(x, t, r["v(loc)"])) for x in at]
        line = [float(np.mean(r["v(line)"][int((x - 0.1) * FS) : int(x * FS)])) for x in at]
        rows.append({"keys": k, "t_s": at, "loc_v": loc, "line_mean_v": line})
    # A reed's pitch on the sagged local battery (the reference key, A3).
    vs = sorted({round(v, 4) for row in rows for v in row["loc_v"]} | {2.8})
    with ProcessPoolExecutor(min(len(vs), 8)) as ex:
        cents = dict(zip(vs, ex.map(_pitch_at, [(57, v) for v in vs]), strict=True))
    for row in rows:
        row["a3_cents_vs_nominal"] = [cents[round(v, 4)] - cents[2.8] for v in row["loc_v"]]
    summary["sag"] = {"rows": rows, "a3_cents_at_v": {str(k): c for k, c in cents.items()}}


def _breaker(args: tuple[int, int]) -> tuple[int, int, float, list[float]]:
    note, ov = args
    cfg = reed.load_cfg()
    data = vcompile.load(vcompile.latest())
    p = vcompile.from_data(data["keys"][note - data["keys"][0]["note"]])
    secs = max(0.6, 25.0 / p.f_hz + 0.35)
    o = reed.run(p, secs, 2.8, 6.0, [(0.0, "on", 100)], oversample=ov, probes=True)
    f = reed.pitch_hz(o["x"])
    il = np.array(o["i_line"][-19200:])
    t = np.arange(len(il)) / FS
    hs = [abs(np.mean(il * np.exp(-2j * np.pi * h * f * t))) for h in range(1, int(20000 / f) + 1)]
    return note, ov, 1200 * math.log2(f / vcompile.note_hz(cfg, note)), hs


def study_breaker(summary: dict) -> None:
    jobs = [(n, ov) for n in (36, 48, 60, 72, 84) for ov in (8, 64)]
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(_breaker, jobs))
    ref = {n: np.array(h) for n, ov, _, h in res if ov == 64}
    rows = []
    for n, ov, c, h in res:
        if ov != 8:
            continue
        r, h = ref[n], np.array(h)
        m = min(len(r), len(h))
        k = r[:m] > r[:m].max() * 1e-3
        d = 20 * np.log10(h[:m][k] / r[:m][k])
        c64 = next(cc for nn, oo, cc, _ in res if nn == n and oo == 64)
        rows.append(
            {
                "note": n,
                "cents_live_vs_reference": c - c64,
                "harmonics_rms_db": float(np.sqrt(np.mean(d**2))),
                "harmonics_max_db": float(np.max(np.abs(d))),
                "harmonics": int(k.sum()),
            }
        )
    summary["breaker"] = rows


STUDIES = {
    "breaker": study_breaker,
    "velocity": study_velocity,
    "cutoff": study_cutoff,
    "sag": study_sag,
    "demo": study_demo,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", choices=list(STUDIES))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for name in a.only or list(STUDIES):
        print(f"{name} ...", flush=True)
        STUDIES[name](summary)
        path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in (a.only or list(STUDIES))}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

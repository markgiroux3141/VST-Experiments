"""The Novachord's measurements (docs/NOVACHORD_PLAN.md, NV1-NV3) -> reports/novachord/:

  - chord sag (NV3): 1, 5, 10 and 20 keys held at ATTACK 4 (organ-like: the level the keys
    settle at) for 1.5 s: the control tubes' B+ (`bct`: +260 V through the preamplifier's
    100k, SM2 Fig. 21) and the output's level, per chord size;
  - the vibrato (NV2): note A's oscillator over 4 s with NORMAL, SMALL and both: the reed's
    rate and swing, the pitch's mean and its depth (one-note circuit);
  - speed: seconds of computing per second of sound for the full instrument and the note.

    uv run --extra fast python scripts/novachord_study.py [--only sag vibrato] [--quality draft]

Writes reports/novachord/study.json and prints each result.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import time

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.rhodes import midi
from varimu.sim import fast, io

OUT = REPO_ROOT / "reports" / "novachord"
FS = 96000
# chords from the middle of the keyboard (MIDI), built up from A3
CHORD_NOTES = [57, 61, 64, 69, 52, 73, 76, 45, 59, 66, 71, 62, 54, 68, 78, 47, 50, 74, 81, 40]


def _script(name):
    sp = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def sag(quality: str) -> dict:
    nr = _script("novachord_render")
    out = {}
    for n in (1, 5, 10, 20):
        ev = [midi.Event(0.05, "on", k, 100) for k in CHORD_NOTES[:n]]
        t0 = time.perf_counter()
        v, el, _ = nr.render(
            ev, 1.5, quality, {"attack": 4, "amp": 0}, 3, probes=("out", "bct"), progress=None
        )
        late = slice(int(1.0 * FS), int(1.5 * FS))
        out[str(n)] = {
            "bct_v": round(float(np.mean(v["bct"][late])), 2),
            "bct_idle_v": round(float(np.mean(v["bct"][: int(0.04 * FS)])), 2),
            "out_rms_v": round(
                float(np.sqrt(np.mean((v["out"][late] - np.mean(v["out"][late])) ** 2))), 5
            ),
            "x_real_time": round(el / 1.5, 1),
            "wall_s": round(time.perf_counter() - t0, 1),
        }
        print(f"{n} keys: {out[str(n)]}", flush=True)
    return out


def vibrato(quality: str) -> dict:
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "novachord_note.yaml")
    res = {}
    for name, sets in (
        ("off", {}),
        ("normal", {"normal_vibrato": 1}),
        ("small", {"small_vibrato": 1}),
        ("both", {"normal_vibrato": 1, "small_vibrato": 1}),
    ):
        ir = builder.build_ir(s, spec.resolve(s, sets))
        ir = dataclasses.replace(ir, probes=(VoltageProbe("ao_top"), VoltageProbe("reed2_x")))
        st = dataclasses.replace(
            io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
            full_scale_volts_peak=1.0,
        )
        n = int(4.0 * FS)
        ctl = {k: np.zeros(n) for k, _ in s.cv_inputs}
        t0 = time.perf_counter()
        v = fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl).vectors
        el = time.perf_counter() - t0
        y = np.asarray(v["v(ao_top)"])
        y = y - y.mean()
        i = np.flatnonzero((y[:-1] < 0) & (y[1:] >= 0))
        t = (i + (-y[i]) / (y[i + 1] - y[i])) / FS
        f, tc = 1 / np.diff(t), t[1:]
        late = tc > 2.0
        c = 1200 * np.log2(f[late] / 1760.0)
        x = np.asarray(v["v(reed2_x)"])[int(2.0 * FS) :]
        xr = x - x.mean()
        j = np.flatnonzero((xr[:-1] < 0) & (xr[1:] >= 0))
        res[name] = {
            "pitch_c": round(float(np.mean(c)), 2),
            "depth_c_p2p": round(float(np.percentile(c, 97) - np.percentile(c, 3)), 2),
            "reed_hz": round(float((len(j) - 1) / ((j[-1] - j[0]) / FS)), 3)
            if len(j) > 2
            else None,
            "reed_mm": round(float(np.ptp(x) / 2), 3),
            "x_real_time": round(el / 4.0, 1),
        }
        print(f"vibrato {name}: {res[name]}", flush=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=["sag", "vibrato"])
    ap.add_argument("--quality", default="draft")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "study.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    report["quality"] = args.quality
    if "vibrato" in args.only:
        report["vibrato"] = vibrato(args.quality)
    if "sag" in args.only:
        report["chord_sag"] = sag(args.quality)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

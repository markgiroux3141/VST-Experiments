"""The stereo 670 measured (docs/STEREO_PLAN.md, ST3b's done-when): the stereo unit against the
one-channel file, separation in both S301 positions, and LATERAL & VERTICAL on a hard-panned
source.

    uv run --extra fast python scripts/fairchild_670_stereo_study.py [--quality Q] [--only NAME ...]

-> reports/fairchild_670_stereo/<quality>/summary.json (and the numbers printed). Each
measurement renders steady tones (varimu.measure.levels' rise and hold) through
fast.run_transient, in parallel; the right input is the audio control `in_r`.

- `vs_mono`: a -6 dBFS 1 kHz tone (about 10 dB of limiting at the factory adjustment) into
  the left only, and into both. With `r145_r148_ohm=75` (the one-channel file's lumped
  pick-off) the left alone is the one-channel file up to its lumped idle channel 2; both
  driven differ by the supply's coupling (both channels' 6386 cathode current in L302: the
  README's "Supply rails"), the bound written down here. At this file's own pads, the gains
  against the one-channel file's at their factory adjustments.
- `separation`: 1 kHz at -20 dBFS (no limiting) into the left alone: the right output re the
  left, at LEFT & RIGHT and at LATERAL & VERTICAL ([MAN] p.4: 60 dB and 40 dB). Then with
  channel 2's 6386 banks 10 % hotter (an unmatched unit: at LATERAL & VERTICAL the matrix's
  cancellation is the channels' match; the input pads are ahead of the matrix, so they don't
  unmatch it), and its gain re channel 1's at LEFT & RIGHT.
- `panned`: a centred 400 Hz tone at -26 dBFS in both, a 1 kHz tone at -6 dBFS in the left
  from 0.4 s: the centred tone's level in each output before and during it (its image: right
  re left). LEFT & RIGHT ducks the left only (the image drifts right); LATERAL & VERTICAL
  ducks both alike ([MAN] p.3: "retain the spatial distribution ... without producing any
  annoying image drift").
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.signal import butter, sosfiltfilt

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.sim import fast, runner
from varimu.sim.io import TransientSettings, full_scale

OUT = REPO_ROOT / "reports" / "fairchild_670_stereo"
STEREO, MONO = "fairchild_670_stereo", "fairchild_670"
# The one-channel file's pick-off (its two lumped 150 ohm legs) and factory adjustment, on
# both channels: the stereo unit as the one-channel file builds channel 1.
MONO_TRIMS = {"input_atten_db": 11.0, "dc_threshold": 0.253, "ac_threshold": 0.709}
MONO_PICKOFF = {
    "r145_r148_ohm": 75,
    **MONO_TRIMS,
    **{f"{k}_2": v for k, v in MONO_TRIMS.items()},
}
# Channel 2 a little hotter than channel 1 (its 6386 banks' emission +10 %): an unmatched unit.
UNMATCHED = {"v6386_2a.emission_scale": 1.1, "v6386_2b.emission_scale": 1.1}


class Bench:
    def __init__(self, quality: str):
        self.s = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
        self.fs = self.s.sample_rate
        self.vin, self.vout = full_scale(self.s)
        self.specs = {n: spec.load_circuit(spec.circuit_path(n)) for n in (STEREO, MONO)}

    def t(self, seconds: float) -> np.ndarray:
        return np.arange(int(seconds * self.fs)) / self.fs

    def tone(self, f: float, dbfs: float, seconds: float, start_s: float = 0.0) -> np.ndarray:
        t = self.t(seconds)
        env = np.clip((t - start_s) / 0.05, 0.0, 1.0)
        return 10 ** (dbfs / 20) * np.sin(2 * np.pi * f * t) * env

    def one(self, job):
        circuit, left, right, ov = job
        ir = builder.build(self.specs[circuit], ov).ir
        ctl = {"in_r": right * self.vin} if circuit == STEREO else None
        with fast.thread_priority(self.s.priority):
            r = fast.run_transient(ir, left * self.vin, settings=self.s, controls=ctl)
        return {k: v for k, v in r.vectors.items()}

    def run(self, jobs: dict) -> dict:
        with ThreadPoolExecutor(runner.default_jobs()) as ex:
            return dict(zip(jobs, ex.map(self.one, jobs.values()), strict=True))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def db(x: float) -> float:
    return float(20 * np.log10(x + 1e-30))


def vs_mono(b: Bench) -> dict:
    x = b.tone(1000.0, -6.0, 0.6)
    z = 0 * x
    jobs = {
        "mono": (MONO, x, None, {}),
        "left_alone": (STEREO, x, z, MONO_PICKOFF),
        "both": (STEREO, x, x, MONO_PICKOFF),
        "own_both": (STEREO, x, x, {}),
        "own_left": (STEREO, x, z, {}),
    }
    r = b.run(jobs)
    a = int(0.1 * b.fs)
    tail = slice(int(0.4 * b.fs), None)

    def rel(p, q):
        return round(db(rms(p[a:] - q[a:]) / rms(q[a:])), 1)

    def gain(o):
        return round(db(rms(o[tail] / b.vout) / rms(x[tail])), 2)

    m = r["mono"]["v(out)"]
    return {
        "mono_pickoff_left_alone_vs_mono_db": rel(r["left_alone"]["v(out)"], m),
        "mono_pickoff_left_alone_right_out_re_left_db": round(
            db(rms(r["left_alone"]["v(out_r)"][tail]) / rms(r["left_alone"]["v(out)"][tail])), 1
        ),
        "mono_pickoff_both_vs_mono_db": rel(r["both"]["v(out)"], m),
        "mono_pickoff_both_right_vs_left_db": rel(r["both"]["v(out_r)"], r["both"]["v(out)"]),
        "gain_db": {k: gain(o["v(out)"]) for k, o in r.items()},
        "cv_v": {k: round(float(np.median(o["v(cv)"][tail])), 2) for k, o in r.items()},
        "nb2_v": {k: round(float(np.median(o["v(nb2)"][tail])), 2) for k, o in r.items()},
    }


def separation(b: Bench) -> dict:
    x = b.tone(1000.0, -20.0, 0.6)
    z = 0 * x
    jobs = {
        "lr": (STEREO, x, z, {"mode": 1}),
        "lv": (STEREO, x, z, {"mode": 2}),
        "lv_unmatched": (STEREO, x, z, {"mode": 2, **UNMATCHED}),
        "lr_unmatched_both": (STEREO, x, x, {"mode": 1, **UNMATCHED}),
    }
    r = b.run(jobs)
    tail = slice(int(0.4 * b.fs), None)

    def sep(o):
        return round(db(rms(o["v(out)"][tail]) / rms(o["v(out_r)"][tail])), 1)

    return {
        "left_right_db": sep(r["lr"]),
        "lateral_vertical_db": sep(r["lv"]),
        "lateral_vertical_unmatched_db": sep(r["lv_unmatched"]),
        "unmatched_ch2_re_ch1_gain_db": round(
            db(
                rms(r["lr_unmatched_both"]["v(out_r)"][tail])
                / rms(r["lr_unmatched_both"]["v(out)"][tail])
            ),
            2,
        ),
        "spec_db": {"left_right": 60, "lateral_vertical": 40},
        "gain_lv_vs_lr_db": round(
            db(rms(r["lv"]["v(out)"][tail]) / rms(r["lr"]["v(out)"][tail])), 2
        ),
        "cv_lv_v": [round(float(np.median(r["lv"][k][tail])), 2) for k in ("v(cv)", "v(cv_2)")],
    }


def panned(b: Bench) -> dict:
    seconds, start = 1.4, 0.4
    centre = b.tone(400.0, -26.0, seconds)
    loud = b.tone(1000.0, -6.0, seconds, start_s=start)
    jobs = {
        "lr": (STEREO, centre + loud, centre, {"mode": 1}),
        "lv": (STEREO, centre + loud, centre, {"mode": 2}),
    }
    r = b.run(jobs)
    sos = butter(4, [300.0, 520.0], btype="bandpass", fs=b.fs, output="sos")
    before = slice(int(0.25 * b.fs), int(start * b.fs))
    during = slice(int((start + 0.6) * b.fs), None)
    res = {}
    for k, o in r.items():
        lo = sosfiltfilt(sos, o["v(out)"])
        ro = sosfiltfilt(sos, o["v(out_r)"])
        d = {
            "left_ducks_db": round(db(rms(lo[during]) / rms(lo[before])), 2),
            "right_ducks_db": round(db(rms(ro[during]) / rms(ro[before])), 2),
        }
        d["image_shift_db"] = round(d["right_ducks_db"] - d["left_ducks_db"], 2)
        d["cv_v"] = [round(float(np.median(o[c][during])), 2) for c in ("v(cv)", "v(cv_2)")]
        res[k] = d
    return res


MEASUREMENTS = {"vs_mono": vs_mono, "separation": separation, "panned": panned}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", default="production")
    ap.add_argument("--only", nargs="*", choices=list(MEASUREMENTS))
    a = ap.parse_args()
    b = Bench(a.quality)
    out_dir = OUT / a.quality
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for name in a.only or MEASUREMENTS:
        summary[name] = MEASUREMENTS[name](b)
        print(name, json.dumps(summary[name], indent=1))
    path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

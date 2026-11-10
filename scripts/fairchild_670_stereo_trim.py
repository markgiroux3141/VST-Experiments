"""The stereo 670's factory threshold adjustment ([MAN] p.8, to the manual's curve 3), as the
one-channel file's defaults were set (varimu.sim.setup.threshold, 2026-10-23).

    uv run --extra fast python scripts/fairchild_670_stereo_trim.py [--write] [--quality Q]

The stereo file takes the drawing's sidechain pads (four 150 ohm legs; the one-channel file
lumps them into two), so its sidechain is driven less and its thresholds sit elsewhere. The
manual adjusts each channel alone ("6. Repeat the above procedure for the other channel"):
channel 1 here with the right input silent, at LEFT & RIGHT. The channels are the same parts on
one supply, so channel 2 takes channel 1's trims; the check renders channel 2 alone (left
silent) at the two points and reports how far it lands from them.

--write stores the trims in config/fairchild_670_stereo_trims.yaml and regenerates the circuit
file (scripts/make_fairchild_670_stereo.py reads them).
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys

import numpy as np
import yaml

from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.measure import levels
from varimu.sim import setup
from varimu.sim.io import TransientSettings

CIRCUIT = "fairchild_670_stereo"
TRIMS = CONFIG_DIR / "fairchild_670_stereo_trims.yaml"
KEYS = ("input_atten_db", "dc_threshold", "ac_threshold")


def silent_right(x: np.ndarray) -> dict[str, np.ndarray]:
    return {"in_r": np.zeros_like(x)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--quality", default="production")
    a = ap.parse_args()
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality=a.quality)
    target = setup.factory_target()
    print(f"target: +{target.out_3db_dbm:.2f} dBm at 3 dB, +{target.out_10db_dbm:.2f} at 10 dB")
    r = setup.threshold({}, target, settings=s, circuit=CIRCUIT, controls=silent_right)
    trims = {k: r.overrides[k] for k in KEYS}
    print("channel 1:", trims)

    # Channel 2 alone at channel 1's trims (left silent): its output at the two points.
    ov = {**trims, **{f"{k}_2": v for k, v in trims.items()}}
    pts = [
        (target.out_3db_dbm, levels.emf_dbfs_for(target.out_3db_dbm + 3, r.k_db)),
        (target.out_10db_dbm, levels.emf_dbfs_for(target.out_10db_dbm + 10, r.k_db)),
    ]
    fs = s.sample_rate
    from varimu.sim import runner

    jobs = []
    for _, emf in pts:
        x = levels.tone(10 ** (emf / 20), sample_rate=fs)
        jobs.append(
            runner.RenderJob(
                np.zeros_like(x), ov, "trim check ch2", circuit=CIRCUIT, controls={"in_r": x}
            )
        )
    tail = slice(-int(levels.MEASURE_S * fs), None)
    errs = []
    for (want, _), rr in zip(pts, runner.render_many(jobs, settings=s), strict=True):
        got = levels.dbm(levels.rms(rr.vectors["v(out_r)"][tail]))
        errs.append(round(got - want, 3))
    print("channel 2 at channel 1's trims: ", errs, "dB at the 3 / 10 dB points")
    if not a.write:
        return 0
    data = {
        "source": (
            f"scripts/fairchild_670_stereo_trim.py, {datetime.date.today().isoformat()}, "
            f"{a.quality}: [MAN] p.8's threshold procedure to curve 3 on channel 1 (right input "
            f"silent, LEFT & RIGHT), varimu.sim.setup.threshold; channel 2 takes channel 1's "
            f"(alone, it lands {errs[0]:+.3f} / {errs[1]:+.3f} dB from the 3 / 10 dB points)"
        ),
        **{k: float(v) for k, v in trims.items()},
        "log": list(r.log),
    }
    TRIMS.write_text(yaml.safe_dump(data, sort_keys=False, width=100), encoding="utf-8")
    print(f"wrote {TRIMS}")
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "make_fairchild_670_stereo.py")], check=True
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

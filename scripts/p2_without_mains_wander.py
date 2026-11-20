"""AM2 attribution: P2 (noise seed 1 vs 2) with the mains wander's rms set to 0 in this process
only (varimu.devices.noise.MAINS_RMS; uncached renders). If P2 falls to the additive
expectation, the seed-dependent difference is the mains wander's."""

import json
import sys

import numpy as np

sys.path.insert(0, "scripts")
import two_pass_null as t  # noqa: E402

from varimu.devices import noise as noise_mod  # noqa: E402
from varimu.magic import null, render  # noqa: E402

noise_mod.MAINS_RMS = 0.0
fs = render.sample_rate()
out = {}
for dev, clip in [("telefunken_v76", "drums"), ("fender_5e3", "guitar")]:
    x = t.program(clip, 10.0, fs)
    j = t.jobs_for(dev, clip, x)
    y = {}
    for tag in ("n1", "n2", "floor"):
        jj = dict(j[tag])
        jj.pop("fn", None)
        jj["cache"] = False
        y[tag] = render.through(**jj)["out"]
    r = null.null_report(y["n1"], y["n2"], fs, dewarp_stage=False)
    fl = null.rms_db(null.audio_band(y["floor"], fs), null.audio_band(y["n1"], fs))
    out[f"{dev} {clip}"] = {
        "P2_gain": r["gain"],
        "P2_audio": r["audio"],
        "floor_audio": fl,
        "additive_expectation_audio": fl + 10 * np.log10(2),
    }
    print(dev, clip, out[f"{dev} {clip}"], flush=True)
open("reports/magic/null/p2_without_mains_wander.json", "w").write(json.dumps(out, indent=1))

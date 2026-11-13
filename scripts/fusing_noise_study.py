"""AM7, noise that fuses (docs/ANALOG_MAGIC_FABLE.md): the stimuli and the coherence table.

Per carrier (the tube synth's dry line, a bass line, a voice; 4 s each at -18 dBFS rms):
y0 = the tape machine without grain, y1 = with grain seed 1 (flutter off in both); the noises
of varimu.magic.fusing, and how much each follows y0. If n_phys doesn't follow, the model's
tape noise isn't signal-dependent: that is the first finding, before any listening.

-> reports/magic/fusing/ (summary.json); stimuli in cache/magic/fusing/<carrier>/ for
scripts/fusing_noise_listen.py.

  uv run --extra fast --extra listen python scripts/fusing_noise_study.py
"""

from __future__ import annotations

import json
import sys

import numpy as np

from varimu.config import REPO_ROOT
from varimu.magic import fusing, render
from varimu.sim.io import load_audio, write_audio

OUT = REPO_ROOT / "reports" / "magic" / "fusing"
STIM = REPO_ROOT / "cache" / "magic" / "fusing"
CARRIERS = {
    "synth": REPO_ROOT / "cache" / "separation" / "conditions" / "dry" / "target.wav",
    "bass": REPO_ROOT / "data" / "clips" / "bass_areasontoleave.wav",
    "voice": REPO_ROOT / "data" / "clips" / "vocal_longwayhome.wav",
}


def excerpt(path, fs, seconds=4.0):
    x = load_audio(path, fs)
    w = int(seconds * fs)
    if len(x) > w:
        e = [np.mean(x[s : s + w] ** 2) for s in range(0, len(x) - w, fs // 2)]
        s0 = int(np.argmax(e)) * (fs // 2)
        x = x[s0 : s0 + w]
    x = x * 10 ** (-18 / 20) / (np.std(x) + 1e-30)
    f = int(0.02 * fs)
    x[:f] *= np.linspace(0, 1, f)
    x[-f:] *= np.linspace(1, 0, f)
    return x


def main() -> int:
    fs = render.sample_rate()
    xs = {k: excerpt(p, fs) for k, p in CARRIERS.items() if p.exists()}
    jobs = []
    for x in xs.values():
        jobs.append({"fn": render.tape_print, "x": x, "noise_seed": None, "flutter": False})
        jobs.append({"fn": render.tape_print, "x": x, "noise_seed": 1, "flutter": False})
    outs = render.through_many(jobs, workers=6)
    summ = {}
    for i, (k, _) in enumerate(xs.items()):
        y0, y1 = outs[2 * i]["out"], outs[2 * i + 1]["out"]
        ns = fusing.noises(y0, y1, fs)
        summ[k] = {name: fusing.follow_measures(y0, n, fs) for name, n in ns.items()}
        d = STIM / k
        write_audio(d / "y0.wav", y0, fs)
        for name, n in ns.items():
            write_audio(d / f"{name}.wav", n, fs)
        print(
            k,
            json.dumps({n: {m: round(v, 3) for m, v in r.items()} for n, r in summ[k].items()}),
            flush=True,
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

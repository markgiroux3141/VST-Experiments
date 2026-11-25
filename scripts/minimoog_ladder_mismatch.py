"""What the ladder's transistor mismatch does to the Minimoog voice (MINIMOOG_BACKLOG.md
"Authenticity first", item 3): the one mismatch no factory trim takes out.

The voice's ladder transistors (section "ladder": the four stages' pairs and the input pair, model
QL, the TIS97's 2N3904 stand-in) share one model instance, so the ladder is exactly symmetric. Here
each gets its own instance with a drawn SPICE area (saturation current x area: a Vbe offset of
Vt ln(area), ~1 mV for 4 %), uniform within +-AREA_PCT (provisional: unmatched small-signal
transistors from one lot), drawn as the builder draws parts (default_rng([seed, crc32(name)])).
In a temporary copy of config/circuits/minimoog_voice.yaml (cache/minimoog/units/); nothing in
config/ changes. Measured at draft-1x, partitioned as the app plays it, against the nominal voice:

  - thump: no source in the mixer, AMOUNT OF CONTOUR 1, ATTACK 0, DECAY 0.15, SUSTAIN 0: the
    filter contour's sweep feeds through an unbalanced ladder as a low-frequency pulse at the
    MAIN OUTPUT (the VCA open on the loudness contour); peak and rms in mV, 0.2 s from the key;
  - harmonics: a 200 Hz sine at EXTERNAL INPUT (30 mV and 1 mV at the jack, LEVEL 0.5), CUTOFF 0.9,
    EMPHASIS 0, a key held: H2 and H3 re the fundamental at the MAIN OUTPUT.

    uv run --extra fast python scripts/minimoog_ladder_mismatch.py [--seeds 1 2 3] [--area-pct 12]

Writes reports/minimoog/units/ladder_mismatch.json.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import zlib
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import minimoog_gate_check as gc  # noqa: E402
import minimoog_vcf_study as vs  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.circuit.ir import VoltageProbe  # noqa: E402
from varimu.config import CONFIG_DIR  # noqa: E402
from varimu.sim import fast  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = CONFIG_DIR / "circuits" / "minimoog_voice.yaml"
WORK = ROOT / "cache" / "minimoog" / "units"
OUT = ROOT / "reports" / "minimoog" / "units"
NOTE = 45  # A2: low, where a thump is heard
# The rate a draft-1x run takes and returns its samples at (the 96 kHz grid; the host is 48 kHz).
FS = vs.settings("draft-1x").sample_rate


def drawn_voice(seed: int, area_pct: float) -> tuple[Path, dict]:
    d = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    ladder = next(s for s in d["sections"] if s["title"] == "ladder")["parts"]
    areas = {}
    for name, part in ladder.items():
        if "bjt" not in part or part.get("model") != "QL":
            continue
        u = np.random.default_rng([seed, zlib.crc32(name.encode())]).uniform(-1.0, 1.0)
        area = 1.0 + u * area_pct / 100.0
        areas[name] = area
        key = f"QL_{name}"
        d["devices"][key] = {
            "device": d["devices"]["QL"]["device"],
            "area": {"value": float(area), "source": f"minimoog_ladder_mismatch.py seed {seed}"},
        }
        part["model"] = key
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"minimoog_voice_ladder{seed}.yaml"
    path.write_text(yaml.safe_dump(d, sort_keys=False, width=10**9), encoding="utf-8")
    return path, areas


def run(path: Path, over: dict, x: np.ndarray, gate_at_s: float = 0.2) -> tuple[float, np.ndarray]:
    s = spec.load_circuit(path)
    ir = builder.build_ir(s, spec.resolve(s, over), "linear", events=True)
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"),))
    st = dataclasses.replace(
        vs.settings("draft-1x"),
        newton_reltol=gc.VOICE_NEWTON,
        newton_vntol=gc.VOICE_NEWTON,
        partition=gc.VOICE_PARTITION,
        partition_coupling="hold",
        hard_step_iterations=gc.VOICE_HARD_STEP,
    )
    fs = st.sample_rate
    n = len(x)
    off, on = gc.gate_levels(s, "gate")
    gate = np.full(n, off)
    gate[int(gate_at_s * fs) :] = on
    key = np.full(n, gc.key_volts(s, NOTE))
    r = fast.run_transient(ir, x, settings=st, controls={"key": key, "gate": gate})
    return fs, np.asarray(r.vectors["v(out)"])


THUMP = {
    "osc1_on": 0, "ext_on": 0, "amount": 1.0, "attack": 0.0, "decay": 0.15, "sustain": 0.0,
    "lattack": 0.0, "ldecay": 0.6, "lsustain": 1.0, "cutoff": 0.4, "emphasis": 0.0,
}  # fmt: skip
# the sine at the jack: hot (the pre-amp and ladder driven) and low (where a symmetric
# ladder has almost no H2)
AMPS = (0.3, 0.01)
TONE = {"osc1_on": 0, "ext_on": 1, "ext_level": 0.5, "cutoff": 0.9, "emphasis": 0.0}


def thump(path: Path) -> dict:
    fs = FS
    x = np.zeros(int(0.8 * fs))
    fs, y = run(path, THUMP, x)
    seg = y[int(0.2 * fs) : int(0.6 * fs)] - y[int(0.15 * fs) : int(0.2 * fs)].mean()
    return {
        "peak_mv": 1e3 * float(np.abs(seg).max()),
        "rms_mv": 1e3 * float(np.sqrt(np.mean(seg**2))),
    }


def harmonics(path: Path, amp: float) -> dict:
    fs, f0 = FS, 200.0  # amp: of the jack's 0.1 V full scale
    n = int(1.0 * fs)
    t = np.arange(n) / fs
    x = amp * np.sin(2 * np.pi * f0 * t) * np.clip(t / 0.05, 0, 1)
    fs, y = run(path, TONE, x, gate_at_s=0.05)
    seg = y[int(0.5 * fs) : int(0.5 * fs) + int(0.4 * fs)]  # 80 cycles
    tt = np.arange(len(seg)) / fs
    win = np.hanning(len(seg))
    mag = [
        abs(np.sum((seg - seg.mean()) * win * np.exp(-2j * np.pi * k * f0 * tt))) for k in (1, 2, 3)
    ]
    return {
        "h1_v": 2 * mag[0] / win.sum(),
        "h2_db": 20 * np.log10(mag[1] / mag[0]),
        "h3_db": 20 * np.log10(mag[2] / mag[0]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--area-pct", type=float, default=12.0)
    a = ap.parse_args()
    rep: dict = {
        "area_pct": a.area_pct,
        "nominal": {"thump": thump(SRC), **{f"harmonics_{a}": harmonics(SRC, a) for a in AMPS}},
    }
    print("nominal", json.dumps(rep["nominal"]), flush=True)
    rep["units"] = {}
    for seed in a.seeds:
        path, areas = drawn_voice(seed, a.area_pct)
        u = {
            "areas": areas,
            "thump": thump(path),
            **{f"harmonics_{a}": harmonics(path, a) for a in AMPS},
        }
        rep["units"][seed] = u
        print(f"unit {seed}", json.dumps({k: u[k] for k in u if k != "areas"}), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ladder_mismatch.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"wrote {OUT / 'ladder_mismatch.json'}")


if __name__ == "__main__":
    main()

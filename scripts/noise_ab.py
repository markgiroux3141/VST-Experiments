"""Tube synth: does B5's noise matter? A and B of osc_ab.py's phrase, noise off and on.

Both renders are config/circuits/tube_synth.yaml with osc_ab.py's panel, notes, gate and
keyboard tuning, the tube oscillator at WAVE 1 (osc_ab's B), at production:
- A: noise off (build_ir(..., noise=False));
- B: the file's noise (resistors, tubes, the mains wander; seed 1).
Matched for loudness (integrated LUFS to osc_ab's TARGET_LUFS: CLAUDE.md "Loudness lies").
Written to reports/tube_synth/noise_ab/renders/ (not committed): A_noise_off.wav,
B_noise_on.wav, a blind pair 1.wav / 2.wav (seeded) with blind_key.json;
reports/tube_synth/noise_ab/summary.json keeps the levels and each held note's pitch in
cents from equal temperament.

    uv run --extra fast --extra listen python scripts/noise_ab.py
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.listen.matching import integrated_lufs
from varimu.sim import fast, io

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "tube_synth" / "noise_ab"
SEED = 20261031

_spec = importlib.util.spec_from_file_location("osc_ab", Path(__file__).with_name("osc_ab.py"))
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)


def render(noise: bool, gate: np.ndarray, pitch: np.ndarray) -> np.ndarray:
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "tube_synth.yaml")
    ir = builder.build_ir(s, spec.resolve(s, ab.PANEL), cores="ja", noise=None if noise else False)
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production"),
        full_scale_volts_peak=1.0,
    )
    controls = {"gate": gate, "pitch": pitch}
    return fast.run_transient(ir, np.zeros(len(gate)), settings=st, controls=controls).vectors[
        "v(out)"
    ]


def main() -> None:
    fs = io.load_sim_settings().sample_rate
    gate, hz, _ = ab.score(fs)
    table = [(f, v) for f, v in json.loads(ab.TUNING.read_text())["hz_v"] if v >= ab.TUNING_MIN_V]
    pitch = np.array([ab.tuning_volts(f, table) for f in hz])
    print(f"rendering {len(gate) / fs:.1f} s twice at production", flush=True)
    with ThreadPoolExecutor(2) as ex:
        off, on = ex.map(lambda n: render(n, gate, pitch), (False, True))
    renders = OUT_DIR / "renders"
    renders.mkdir(parents=True, exist_ok=True)
    summary: dict = {"panel": ab.PANEL, "target_lufs": ab.TARGET_LUFS}
    tracks = {"A_noise_off": off, "B_noise_on": on}
    matched = {}
    for name, y in tracks.items():
        y = y - np.mean(y)
        lufs = integrated_lufs(y, fs)
        g = 10 ** ((ab.TARGET_LUFS - lufs) / 20)
        matched[name] = (y * g).astype(np.float32)
        sf.write(renders / f"{name}.wav", matched[name], fs, subtype="FLOAT")
        summary[name] = {
            "lufs_before": round(lufs, 3),
            "gain_db": round(float(20 * np.log10(g)), 3),
            "note_cents_from_et": [
                round(ab.note_cents(y, fs, nt, s, d), 2) for nt, s, d in ab.PHRASE if d >= 0.3
            ],
        }
    d = matched["B_noise_on"] - matched["A_noise_off"]
    summary["difference_db_re_signal"] = round(
        float(20 * np.log10(np.std(d) / np.std(matched["A_noise_off"]))), 1
    )
    rng = np.random.default_rng(SEED)
    order = list(tracks)
    rng.shuffle(order)
    for i, name in enumerate(order, 1):
        sf.write(renders / f"{i}.wav", matched[name], fs, subtype="FLOAT")
    (renders / "blind_key.json").write_text(
        json.dumps({f"{i}.wav": n for i, n in enumerate(order, 1)}) + "\n"
    )
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    print(f"wrote {renders}")


if __name__ == "__main__":
    main()

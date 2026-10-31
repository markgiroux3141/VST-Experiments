"""The tube synth played from note lists (the experiment's source tracks).

A note is (MIDI key, start beat, length in beats). The keyboard's feeds are the app's
(`panel::key_feeds`): the gate at the circuit's `gate_on_v` / `gate_off_v`, the pitch
control from the measured tuning (`reports/tube_synth/vco/synth_tuning_high.json`, the
RANGE switch at HIGH), interpolated on log frequency as `panel::Pitch` does.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit import ir as I
from varimu.config import CONFIG_DIR
from varimu.config import REPO_ROOT as ROOT
from varimu.sim import fast, io

TUNING = ROOT / "reports" / "tube_synth" / "vco" / "synth_tuning_high.json"
CACHE = ROOT / "cache" / "separation" / "synth"

Note = tuple[int, float, float]  # (MIDI key, start beat, length in beats)


def key_hz(key: int) -> float:
    return 440.0 * 2 ** ((key - 69) / 12)


def pitch_volts(hz: float) -> float:
    table = json.loads(TUNING.read_text())["hz_v"]
    f = np.array([p[0] for p in table])
    v = np.array([p[1] for p in table])
    return float(np.interp(np.log2(hz), np.log2(f), v))


def controls(
    notes: list[Note], bpm: float, fs: float, seconds: float, gate_on_v: float, gate_off_v: float
):
    """The gate and pitch controls for `notes` (the pitch holds the last key, as a mono
    keyboard does)."""
    n = int(round(seconds * fs))
    gate = np.full(n, gate_off_v)
    first = min(notes, key=lambda x: x[1])
    pitch = np.full(n, pitch_volts(key_hz(first[0])))
    beat_s = 60.0 / bpm
    for key, start, length in sorted(notes, key=lambda x: x[1]):
        a = int(round(start * beat_s * fs))
        b = min(n, int(round((start + length) * beat_s * fs)))
        gate[a:b] = gate_on_v
        pitch[a:] = pitch_volts(key_hz(key))
    return {"gate": gate, "pitch": pitch}


def render(
    notes: list[Note], *, bpm: float, seconds: float, panel: dict, quality: str = "draft"
) -> np.ndarray:
    """The synth's `out` (volts) playing `notes`, at the project's sample rate. Noise off
    (clean sources: two tracks shouldn't share one noise seed). Cached in
    cache/separation/synth/."""
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "tube_synth.yaml")
    p = spec.resolve(s, panel)
    ir = builder.build_ir(s, p, cores="ja", noise=False)
    ir = dataclasses.replace(ir, probes=(I.VoltageProbe("out"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    gate_on = float(p["gate_on_v"])
    gate_off = float(p["gate_off_v"])
    ctl = controls(notes, bpm, st.sample_rate, seconds, gate_on, gate_off)
    h = hashlib.sha256()
    h.update(ir.to_json().encode())
    h.update(json.dumps(st.as_dict(), sort_keys=True).encode())
    h.update(fast.check_build().encode())
    for k in sorted(ctl):
        h.update(k.encode() + ctl[k].astype("<f8").tobytes())
    path = CACHE / f"{h.hexdigest()[:24]}.npy"
    if path.exists():
        return np.load(path)
    with fast.thread_priority(st.priority):
        v = fast.run_transient(ir, np.zeros(len(ctl["gate"])), settings=st, controls=ctl).vectors
    out = np.asarray(v["v(out)"], float)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.save(path, out)
    return out

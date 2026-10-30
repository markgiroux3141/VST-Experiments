"""Tube synth: does the tube oscillator matter? A and B of one phrase through one voice.

Both renders are config/circuits/tube_synth.yaml with the same panel, the same notes and the
same gate, so the filter, the envelope, the VCA, the transformers and the supply are the
same in both; the tube oscillator runs in both (its draw on the supply is the same):
- A: the tube oscillator's mixer resistor is opened (r_mix_osc_ohm 1e12) and varimu-app's
  test oscillator (`midi::TestOsc`: a band-limited polyBLEP square, equal temperament)
  comes in through the external input, at the level that drives the filter's first grid
  (the mixer node) to the same peak as the tube oscillator does in B;
- B: the tube oscillator at WAVE 1 (its square end), its pitch through the keyboard tuning
  (reports/tube_synth/vco/synth_tuning.json from -23 V, as varimu-app's `panel::Pitch`).
Rendered at production, then matched for loudness (integrated LUFS, both to TARGET_LUFS:
CLAUDE.md "Loudness lies"; no gain reduction here). Written to
reports/tube_synth/ab/renders/ (not committed): A_test_osc.wav, B_tube_osc.wav, and a blind
pair 1.wav / 2.wav (seeded) with blind_key.json; reports/tube_synth/ab/summary.json keeps the
levels and each note's pitch in cents from equal temperament.

    uv run --extra fast --extra listen python scripts/osc_ab.py [--quality production|draft]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.listen.matching import integrated_lufs
from varimu.sim import fast, io
from varimu.synth import vco

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "tube_synth" / "ab"
TUNING = ROOT / "reports" / "tube_synth" / "vco" / "synth_tuning.json"
TUNING_MIN_V = -23.0  # where the tuning starts (panel.rs TUBE_SYNTH_TUNING)
KEY_UP_V, KEY_DOWN_V = -110.0, -1.0
PANEL = {"cutoff": 0.7, "resonance": 0.3, "attack": 0.05, "release": 0.3, "wave": 1.0}
TARGET_LUFS = -20.0
SEED = 20261030
# (MIDI note, start s, length s): held notes (drift, glide), legato (overlaps: the gate
# stays down while the pitch moves), staccato, low and high.
PHRASE = (
    (45, 0.2, 1.6),  # A2, held
    (48, 2.0, 0.25),  # C3 staccato
    (52, 2.3, 0.25),  # E3
    (57, 2.6, 0.25),  # A3
    (55, 2.9, 0.45),  # G3, legato into
    (57, 3.3, 1.5),  # A3, held
    (76, 5.1, 0.3),  # E5
    (74, 5.4, 0.3),  # D5
    (72, 5.7, 0.3),  # C5
    (69, 6.0, 1.2),  # A4, held
    (36, 7.5, 2.0),  # C2, held low
)
TAIL_S = 1.2


def note_hz(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def tuning_volts(hz: float, table: list[tuple[float, float]]) -> float:
    """panel::Pitch::volts: log2(Hz) linear between the points, held at the ends."""
    if hz <= table[0][0]:
        return table[0][1]
    if hz >= table[-1][0]:
        return table[-1][1]
    for (f0, v0), (f1, v1) in zip(table, table[1:], strict=False):
        if f0 <= hz <= f1:
            return v0 + (v1 - v0) * np.log2(hz / f0) / np.log2(f1 / f0)
    raise AssertionError


def score(fs: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per sample: the gate (volts), the sounding note's frequency (Hz, the last held),
    the sounding note (0 before the first)."""
    n = int((max(s + d for _, s, d in PHRASE) + TAIL_S) * fs)
    gate = np.full(n, KEY_UP_V)
    note = np.zeros(n, int)
    for nt, s, d in PHRASE:
        a, b = int(s * fs), int((s + d) * fs)
        gate[a:b] = KEY_DOWN_V
        note[a:] = nt  # the last key's pitch holds (a later note overwrites from its start)
    note[note == 0] = PHRASE[0][0]
    hz = np.array([note_hz(k) for k in range(128)])[note]
    return gate, hz, note


def test_square(hz: np.ndarray, fs: int, peak_v: float) -> np.ndarray:
    """midi::TestOsc's square: two polyBLEP saws half a cycle apart."""

    def blep(t, dt):
        out = np.zeros_like(t)
        lo, hi = t < dt, t > 1.0 - dt
        x = t[lo] / dt[lo]
        out[lo] = 2 * x - x * x - 1
        x = (t[hi] - 1.0) / dt[hi]
        out[hi] = x * x + 2 * x + 1
        return out

    dt = np.minimum(hz / fs, 0.5)
    phase = np.concatenate([[0.0], np.cumsum(dt)[:-1]]) % 1.0
    saw = lambda t: 2 * t - 1 - blep(t, dt)  # noqa: E731
    return peak_v * 0.5 * (saw(phase) - saw((phase + 0.5) % 1.0))


def render(quality: str, sets: dict, x: np.ndarray, gate: np.ndarray, pitch: np.ndarray):
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "tube_synth.yaml")
    ir = builder.build_ir(s, spec.resolve(s, {**PANEL, **sets}), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"), VoltageProbe("mix")))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    v = fast.run_transient(ir, x, settings=st, controls={"gate": gate, "pitch": pitch}).vectors
    return v["v(out)"], v["v(mix)"]


def note_cents(y: np.ndarray, fs: int, nt: int, s: float, d: float) -> float:
    """The note's pitch in cents from equal temperament (after its attack, until it ends or
    the next note starts)."""
    end = min([s + d] + [s2 for _, s2, _ in PHRASE if s < s2 < s + d])
    a, b = int((s + 0.1 * d + 0.05) * fs), int(end * fs)
    return float(vco.cents(vco.frequency(y[a:b], fs, lowpass_hz=3 * note_hz(nt)), note_hz(nt)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quality", default="production", choices=("production", "draft"))
    a = ap.parse_args()
    fs = io.load_sim_settings().sample_rate
    gate, hz, _ = score(fs)
    table = [(f, v) for f, v in json.loads(TUNING.read_text())["hz_v"] if v >= TUNING_MIN_V]
    pitch = np.array([tuning_volts(f, table) for f in hz])
    silent = np.zeros(len(gate))

    print(f"B (tube oscillator) at {a.quality}, then A at its drive level", flush=True)
    out_b, mix_b = render(a.quality, {}, silent, gate, pitch)
    on = gate == KEY_DOWN_V
    peak_v = float(np.percentile(np.abs(mix_b[on] - np.median(mix_b[on])), 99.9))
    x_a = test_square(hz, fs, peak_v)
    out_a, mix_a = render(a.quality, {"r_mix_osc_ohm": 1e12}, x_a, gate, pitch)

    renders = OUT_DIR / "renders"
    renders.mkdir(parents=True, exist_ok=True)
    summary = {
        "quality": a.quality,
        "panel": PANEL,
        "target_lufs": TARGET_LUFS,
        "mix_peak_v": peak_v,
    }
    tracks = {"A_test_osc": out_a, "B_tube_osc": out_b}
    matched = {}
    for name, y in tracks.items():
        y = y - np.mean(y)
        lufs = integrated_lufs(y, fs)
        g = 10 ** ((TARGET_LUFS - lufs) / 20)
        matched[name] = (y * g).astype(np.float32)
        sf.write(renders / f"{name}.wav", matched[name], fs, subtype="FLOAT")
        summary[name] = {
            "lufs_before": round(lufs, 2),
            "gain_db": round(float(20 * np.log10(g)), 2),
            "peak_dbfs_after": round(float(20 * np.log10(np.max(np.abs(matched[name])))), 2),
            "note_cents_from_et": [
                round(note_cents(y, fs, nt, s, d), 1) for nt, s, d in PHRASE if d >= 0.3
            ],
        }
    rng = np.random.default_rng(SEED)
    order = list(tracks)
    rng.shuffle(order)
    for i, name in enumerate(order, 1):
        sf.write(renders / f"{i}.wav", matched[name], fs, subtype="FLOAT")
    (renders / "blind_key.json").write_text(
        json.dumps({f"{i}.wav": n for i, n in enumerate(order, 1)}) + "\n"
    )
    summary["held_notes"] = [nt for nt, s, d in PHRASE if d >= 0.3]
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    print(f"wrote {renders}")


if __name__ == "__main__":
    main()

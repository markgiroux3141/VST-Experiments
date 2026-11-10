"""Gated notes through the filter board as the app plays it (docs/MINIMOOG_PLAN.md, MM2).

The app's `minimoog_filter_board` runs at draft-1x with the VCA as a partition coupled "hold"
and Newton at 1e-5 (crates/varimu-app/src/panel.rs). A key's gate steps the contour 0 -> 5 V
in one sample; with the default "extrapolate" coupling that step overshot across the cut and
Newton failed at key-down. This plays a 220 Hz saw with five gated notes (long, short, quick
repeats) through the partitioned draft and through one solve, and reports the difference with
the cut's lag removed.

    uv run --extra fast python scripts/minimoog_gate_check.py [--coupling hold|extrapolate]
        [--emphasis 0.9] [--amp 0.25]

`--voice` plays `minimoog_voice` instead (the contour generators, the keyboard circuit and
oscillator
1 joined, MM4 / MM5): the keys' gate on the keyboard's trigger contact (the circuit file's
gate_off_v / gate_on_v), the key on its pitch bar (key_*: an octave over the low A while held), the
app's partition (VOICE_PARTITION, as crates/varimu-app/src/panel.rs has it), with knobs given by
`--set k=v`, at the app's numerics (Newton 1e-4, hard steps; `--precise`: 1e-5). The oscillator's
island runs in both (a multi-rate part never runs in the one solve):
the reference is the rest as one solve.

Exit 1 if the partitioned run fails."""

import argparse
import dataclasses
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import minimoog_vcf_study as st  # noqa: E402

from varimu.sim import fast  # noqa: E402

FS = 96000
GATES_S = [(0.2, 0.6), (0.7, 0.75), (0.8, 1.4), (1.45, 1.5), (1.55, 1.9)]
KEY_NOTE = 57  # an octave over the procedures' low A


def spec_value(s, key: str) -> float:
    return float(s.values[key]["value"])


def key_volts(s, note: int) -> float:
    """The keyboard string's volts at MIDI `note` (the circuit file's key_*, as the app's)."""
    v = (note - spec_value(s, "key_ref_note")) * spec_value(s, "key_v_per_semitone")
    return float(np.clip(v, spec_value(s, "key_min_v"), spec_value(s, "key_max_v")))


def gate_levels(s, name: str) -> tuple[float, float]:
    """A gate input's (key up, key down) volts: `<name>_off_v`, `<name>_on_v` (the app's)."""
    return spec_value(s, f"{name}_off_v"), spec_value(s, f"{name}_on_v")


# The oscillators' islands (multi-rate parts: they never run in the one solve), each a group.
VOICE_ISLANDS = [
    "|",
    "osc 1: range",
    "osc 1: summer",
    "osc 1: expo",
    "osc 1: core",
    "osc 1: shapers",
    "osc 1: pulse width",
    "|",
    "osc 2: panel",
    "osc 2: range",
    "osc 2: summer",
    "osc 2: expo",
    "osc 2: core",
    "osc 2: shapers",
    "osc 2: pulse width",
    "|",
    "osc 3: panel",
    "osc 3: range",
    "osc 3: summer",
    "osc 3: expo",
    "osc 3: core",
    "osc 3: shapers",
    "osc 3: pulse width",
]
VOICE_PARTITION = [
    "ladder",
    "output amplifier",
    "filter: rails",
    "|",
    "noise: rails",
    "noise: source",
    "noise: white",
    "noise: pink",
    "modulation mix",
    "panel: rails",
    "|",
    "vca",
    "keyboard: rails",
    "keyboard: sample and hold",
    "keyboard: glide",
    "|",
    "contour: rails",
    "contour: flip-flop",
    "contour: envelope",
    "contour: output",
    "contour: trigger switches",
    "contour: loudness flip-flop",
    "contour: loudness envelope",
    "contour: loudness output",
    *VOICE_ISLANDS,
]


# The voice's live numerics as the app plays it (varimu-app panel::LIVE_NUMERICS): Newton 1e-4
# (`--precise`: the device's 1e-5) and hard steps at 12 iterations (a contour flip-flop's flip
# inside a step redone as halves, MINIMOOG_PLAN.md "Real time").
VOICE_NEWTON, VOICE_NEWTON_PRECISE, VOICE_HARD_STEP = 1e-4, 1e-5, 12


def play(ir, x, gate, key, partition, coupling, gate_name="contour", newton=1e-5, hard=0):
    s = dataclasses.replace(
        st.settings("draft-1x"),
        newton_reltol=newton,
        newton_vntol=newton,
        partition=partition,
        partition_coupling=coupling,
        hard_step_iterations=hard,
    )
    r = fast.run_transient(ir, x, settings=s, controls={"key": key, gate_name: gate})
    return np.asarray(r.vectors["v(out)"])


def aligned_diff_db(x, ref):
    """x against ref in dB after removing a fitted delay (the cut's one sample)."""
    X, R = np.fft.rfft(x), np.fft.rfft(ref)
    f = np.fft.rfftfreq(len(x), 1 / FS)
    m = (f > 50) & (f < 3000) & (np.abs(R) > np.abs(R).max() * 1e-3)
    ph = np.unwrap(np.angle(X[m] / R[m]))
    tau = -np.polyfit(2 * np.pi * f[m], ph, 1)[0]
    y = np.fft.irfft(X * np.exp(2j * np.pi * f * tau), len(x))
    return 20 * np.log10(np.std(y - ref) / np.std(ref)), tau * FS


def envelope_db(x, ref, block_s=0.01):
    """The largest difference of 10 ms rms envelopes (dB) where ref is within 40 dB of its peak:
    what a cut's sample of phase leaves of the level."""
    n = int(block_s * FS)
    m = len(ref) // n
    a = np.sqrt(np.mean(x[: m * n].reshape(m, n) ** 2, axis=1)) + 1e-12
    b = np.sqrt(np.mean(ref[: m * n].reshape(m, n) ** 2, axis=1)) + 1e-12
    k = b > b.max() * 1e-2
    return float(np.max(np.abs(20 * np.log10(a[k] / b[k]))))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--coupling", default="hold")
    p.add_argument("--emphasis", type=float, default=0.0)
    p.add_argument("--amp", type=float, default=0.25)
    p.add_argument("--voice", action="store_true")
    p.add_argument("--set", nargs="*", default=[])
    p.add_argument("--precise", action="store_true", help="the voice at its precise 1e-5")
    a = p.parse_args()

    over = {"emphasis": a.emphasis}
    for kv in a.set:
        k, v = kv.split("=")
        over[k] = float(v)
    if a.voice:
        from varimu.circuit import builder, spec
        from varimu.config import CONFIG_DIR

        vs = spec.load_circuit(CONFIG_DIR / "circuits" / "minimoog_voice.yaml")
        ir = builder.build_ir(vs, spec.resolve(vs, over), "ja")
        partition, gate_name = VOICE_PARTITION, "gate"
        one_solve = VOICE_ISLANDS[1:]  # the oscillators' islands, the rest one solve
        (g_off, g_on), key_v = gate_levels(vs, "gate"), key_volts(vs, KEY_NOTE)
    else:
        fs = st.load()
        ir = st.build(fs, over)
        partition, gate_name = ["vca"], "contour"
        one_solve = []
        (g_off, g_on), key_v = gate_levels(fs, "contour"), key_volts(fs, KEY_NOTE)
    n = int(FS * 2.0)
    t = np.arange(n) / FS
    # the voice plays its own oscillator (its audio input a leak)
    x = np.zeros(n) if a.voice else a.amp * (2 * ((t * 220.0) % 1.0) - 1)
    gate = np.full(n, g_off)
    for t0, t1 in GATES_S:
        gate[int(t0 * FS) : int(t1 * FS)] = g_on
    key = np.full(n, key_v)  # the key held from the start: the bar keeps the last key

    num = {}
    if a.voice:
        num = {
            "newton": VOICE_NEWTON_PRECISE if a.precise else VOICE_NEWTON,
            "hard": VOICE_HARD_STEP,
        }
    ref = play(ir, x, gate, key, one_solve, a.coupling, gate_name, **num)
    try:
        out = play(ir, x, gate, key, partition, a.coupling, gate_name, **num)
    except fast.SimulationFailed as e:
        print(f"FAILED ({a.coupling}): {e}")
        return 1
    d, lag = aligned_diff_db(out, ref)
    print(
        f"{a.coupling}, EMPHASIS {a.emphasis}: peak out {np.abs(out).max():.2f} V "
        f"(one solve {np.abs(ref).max():.2f}); vs one solve {d:.1f} dB, lag {lag:.2f} samples; "
        f"10 ms envelopes within {envelope_db(out, ref):.2f} dB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

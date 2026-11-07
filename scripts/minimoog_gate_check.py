"""Gated notes through the filter board as the app plays it (docs/MINIMOOG_PLAN.md, MM2).

The app's `minimoog_filter_board` runs at draft-1x with the VCA as a partition coupled "hold"
and Newton at 1e-5 (crates/varimu-app/src/panel.rs). A key's gate steps the contour 0 -> 5 V
in one sample; with the default "extrapolate" coupling that step overshot across the cut and
Newton failed at key-down. This plays a 220 Hz saw with five gated notes (long, short, quick
repeats) through the partitioned draft and through one solve, and reports the difference with
the cut's lag removed.

    uv run --extra fast python scripts/minimoog_gate_check.py [--coupling hold|extrapolate]
        [--emphasis 0.9] [--amp 0.25]

`--voice` plays `minimoog_voice` instead (the contour generators and the keyboard circuit joined,
MM4): the keys' gate on the keyboard's trigger contact (the circuit file's gate_off_v / gate_on_v),
the key on its pitch bar (key_*: an octave over the low A while held), the app's partition
(VOICE_PARTITION, as crates/varimu-app/src/panel.rs has it), with knobs given by `--set k=v`.

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


VOICE_PARTITION = [
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
]


def play(ir, x, gate, key, partition, coupling, gate_name="contour"):
    s = dataclasses.replace(
        st.settings("draft-1x"),
        newton_reltol=1e-5,
        newton_vntol=1e-5,
        partition=partition,
        partition_coupling=coupling,
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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--coupling", default="hold")
    p.add_argument("--emphasis", type=float, default=0.0)
    p.add_argument("--amp", type=float, default=0.25)
    p.add_argument("--voice", action="store_true")
    p.add_argument("--set", nargs="*", default=[])
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
        (g_off, g_on), key_v = gate_levels(vs, "gate"), key_volts(vs, KEY_NOTE)
    else:
        fs = st.load()
        ir = st.build(fs, over)
        partition, gate_name = ["vca"], "contour"
        (g_off, g_on), key_v = gate_levels(fs, "contour"), key_volts(fs, KEY_NOTE)
    n = int(FS * 2.0)
    t = np.arange(n) / FS
    x = a.amp * (2 * ((t * 220.0) % 1.0) - 1)
    gate = np.full(n, g_off)
    for t0, t1 in GATES_S:
        gate[int(t0 * FS) : int(t1 * FS)] = g_on
    key = np.full(n, key_v)  # the key held from the start: the bar keeps the last key

    ref = play(ir, x, gate, key, [], a.coupling, gate_name)
    try:
        out = play(ir, x, gate, key, partition, a.coupling, gate_name)
    except fast.SimulationFailed as e:
        print(f"FAILED ({a.coupling}): {e}")
        return 1
    d, lag = aligned_diff_db(out, ref)
    print(
        f"{a.coupling}, EMPHASIS {a.emphasis}: peak out {np.abs(out).max():.2f} V "
        f"(one solve {np.abs(ref).max():.2f}); vs one solve {d:.1f} dB, lag {lag:.2f} samples"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

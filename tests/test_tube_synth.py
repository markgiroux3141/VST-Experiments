"""The tube synth (config/circuits/tube_synth.yaml; S4, docs/TUBE_SYNTH_PLAN.md):
tube_voice.yaml's voice with S4's candidate (b), the reactor-tuned LC oscillator, on the
voice's one supply. The keys give both control inputs: `gate` (the keyboard bus) and
`pitch` (the 6V6GT's grid through the keyboard tuning, varimu-app's `panel::Pitch`).

At draft with the native app's partition (four threads: the VCA, the filter, the
oscillator, the supplies), measured 2026-10-30: the pitch ~59 Hz at -23 V, ~479 Hz at
-15 V, ~1739 Hz at 0 V (reports/tube_synth/vco/synth_tuning.json); below -23 V the tank's
swing saturates the cores. The 6V6GT's screen is on two 5651s: on b3 the VCA's opening
sagged it and a held note fell ~780 cents over ~2 s; regulated, ~19 cents. A held key at
-15 V: ~-11 dBFS out at the panel's defaults; key up, the VCA's bleed ~-80 dBFS or less.
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.preflight import check_circuit
from varimu.sim import fast, io
from varimu.synth import vco

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

CIRCUIT = Path(CONFIG_DIR / "circuits" / "tube_synth.yaml")
FS = 96000
FULL_SCALE_V = 3.5
PARTITION = (
    "input",
    "filter",
    "resonance",
    "cutoff",
    "|",
    "oscillator",
    "pitch",
    "|",
    "power supply",
    "bias supply",
)  # the native app's (panel.rs)
KEY_UP_V, KEY_DOWN_V = -110.0, -1.0


def run(pitch_v, dur_s=1.0, on_s=0.2):
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {}), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"), VoltageProbe("o_t")))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(dur_s * FS)
    t = np.arange(n) / FS
    gate = np.where(t >= on_s, KEY_DOWN_V, KEY_UP_V)
    v = fast.run_transient(
        ir, np.zeros(n), settings=st, controls={"gate": gate, "pitch": np.full(n, pitch_v)}
    ).vectors
    return v["v(out)"], v["v(o_t)"]


def rms_dbfs(y):
    return 20 * np.log10(np.sqrt(np.mean((y - y.mean()) ** 2)) / FULL_SCALE_V + 1e-15)


def test_passes_the_preflight_checks_with_its_gate_and_pitch():
    s = spec.load_circuit(CIRCUIT)
    assert s.cv_inputs == (("gate", "bus"), ("pitch", "pv"))
    assert check_circuit(s) == []


def test_a_key_sounds_the_oscillator_at_its_pitch():
    out, tank = run(-15.0)
    held, before = out[int(0.5 * FS) :], out[int(0.02 * FS) : int(0.18 * FS)]
    f = vco.frequency(tank[int(0.5 * FS) :], FS)
    print(f, rms_dbfs(held), rms_dbfs(before))
    assert abs(vco.cents(f, 478.5)) < 30
    assert -20 < rms_dbfs(held) < -3
    assert rms_dbfs(before) < rms_dbfs(held) - 50


def test_a_held_note_droops_by_tens_of_cents_not_semitones():
    """The VCA opening sags the supply; the regulated screen keeps the pitch within ~20
    cents of where it started (unregulated, ~780 cents)."""
    _, tank = run(-15.0, dur_s=2.0, on_s=0.1)
    early = vco.frequency(tank[int(0.15 * FS) : int(0.35 * FS)], FS)
    late = vco.frequency(tank[int(1.7 * FS) :], FS)
    print(early, late)
    assert abs(vco.cents(late, early)) < 50

"""The tube synth's S4 candidate (b) (config/circuits/vco_lc.yaml): an LC oscillator tuned
by the saturable reactor, its pitch on the `pitch` control input.

At draft (the native app plays it at draft-2x, the same 96 kHz internal rate), measured
2026-10-30 (scripts/vco_study.py; reports/tube_synth/vco/): ~431 Hz at -25 V and ~1658 Hz
at 0 V (the keyboard tuning, lc_tuning.json); the WAVE pot moves the output from the
tank to V1A's square: the 3rd harmonic at 431 Hz -14.4 dB at the tank end (the tank's own
~-19 dB, from the cores and the square drive, plus ~-20 dB of the square through the
passive blend) and -9.3 dB at the square end.
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

CIRCUIT = Path(CONFIG_DIR / "circuits" / "vco_lc.yaml")
FS = 96000


def run(pitch_v, dur_s=0.5, **controls):
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, controls), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("t"), VoltageProbe("out")))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
    )
    n = int(dur_s * FS)
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls={"pitch": np.full(n, pitch_v)})
    return v.vectors["v(t)"], v.vectors["v(out)"]


def test_passes_the_preflight_checks_with_its_pitch_input():
    s = spec.load_circuit(CIRCUIT)
    assert s.cv_inputs == (("pitch", "pv"),)
    assert check_circuit(s) == []


@pytest.mark.parametrize(("pitch_v", "hz"), [(-25.0, 431.0), (0.0, 1658.0)])
def test_the_pitch_input_sets_the_pitch(pitch_v, hz):
    t, _ = run(pitch_v)
    f = vco.frequency(t, FS)
    print(pitch_v, f)
    assert abs(vco.cents(f, hz)) < 30


def test_wave_moves_the_output_from_the_tank_to_the_square():
    """The square end's 3rd harmonic is ~-9.3 dB, the tank end's ~5 dB under it."""
    third = {}
    for w in (0.0, 1.0):
        t, out = run(-25.0, wave=w)
        third[w] = vco.harmonics_db(out[-FS // 4 :], FS, vco.frequency(t, FS), 3)[2]
    print(third)
    assert third[1.0] > -12 and third[0.0] < third[1.0] - 3

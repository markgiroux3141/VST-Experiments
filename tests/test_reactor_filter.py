"""The saturable-reactor low-pass (config/circuits/reactor_filter.yaml; tube synth S2's
core, docs/TUBE_SYNTH_PLAN.md): the control voltage moves its cutoff, and the signal's own
level moves it too (the cores' permeability rises with the signal's swing).

A 110 Hz sawtooth, its harmonics' levels at the output against the input's. Measured
2026-10-29 at production (dB re input; the draft-1x the app plays at within 0.4 dB):

    2 V peak,  0 V:   110 Hz -3.1, 1.1 kHz -27.2, 2.2 kHz -41.6
    2 V peak, 20 V:   110 Hz -0.8, 1.1 kHz  -1.4, 2.2 kHz -16.8
    2 V peak, 150 V:  110 Hz -0.8, 1.1 kHz  -0.6, 2.2 kHz  -0.6, 4 kHz -3.5
    10 V peak, 0 V:   110 Hz -8.4 (a loud note pulls the cutoff down)
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.preflight import check_circuit
from varimu.sim import fast, io

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

from engine_compare import FS  # noqa: E402

CIRCUIT = Path(CONFIG_DIR / "circuits" / "reactor_filter.yaml")
F0 = 110.0


def harmonics_db(cutoff_v, amp_v, ks=(1, 10, 20, 36)):
    """Each harmonic k of a 110 Hz saw at the output, dB re its level at the input."""
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {"cutoff_v": cutoff_v}))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim"), full_scale_volts_peak=1.0
    )
    t = np.arange(int(0.6 * FS)) / FS
    x = amp_v * (2 * ((F0 * t) % 1.0) - 1.0)
    y = fast.run_transient(ir, x, settings=st).vectors["v(out)"][int(0.1 * FS) :]
    sp = np.abs(np.fft.rfft(y * np.hanning(len(y)))) / len(y) * 4
    df = FS / len(y)
    return {k: 20 * np.log10(sp[round(k * F0 / df)] / (2 * amp_v / (np.pi * k))) for k in ks}


def test_passes_the_preflight_checks():
    assert check_circuit(spec.load_circuit(CIRCUIT)) == []


def test_the_control_moves_the_cutoff():
    low, mid, high = (harmonics_db(v, 2.0) for v in (0.0, 20.0, 150.0))
    print(low, mid, high, sep="\n")
    assert low[10] < -20 and low[20] < -35  # ~110 Hz unbiased
    assert mid[10] > -4 and mid[20] < -10  # ~1.5 kHz
    assert high[20] > -3 and high[36] > -6  # ~4 kHz
    assert low[1] > -5  # the fundamental passes


def test_a_loud_note_pulls_the_cutoff_down():
    soft, loud = harmonics_db(0.0, 2.0, (1,)), harmonics_db(0.0, 10.0, (1,))
    print(soft, loud)
    assert loud[1] < soft[1] - 3

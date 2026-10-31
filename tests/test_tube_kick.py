"""The tube kick (config/circuits/tube_kick.yaml; docs/TUBE_SYNTH_PLAN.md, S5's status, "A
tube kick"): the tube synth's reactor oscillator running all the time, a key's edge
sweeping its pitch down and opening a VCA that decays. Measured at draft with the native
app's partition, 2026-10-30: at the panel's defaults the pitch rests ~55 Hz, a hit starts
~150 Hz and is back by ~200 ms, -20 dB at ~210 ms; between hits the oscillator is ~-92 dB
under a hit, a key's release ~-54 dB.
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import butter, sosfiltfilt

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.preflight import check_circuit
from varimu.sim import fast, io
from varimu.synth import vco

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

CIRCUIT = Path(CONFIG_DIR / "circuits" / "tube_kick.yaml")
FS = 96000
PARTITION = ("oscillator", "pitch", "|", "power supply", "bias supply")  # panel.rs's
KEY_UP_V, KEY_DOWN_V = -110.0, -1.0
HIT_S = 1.5  # the hit, after the oscillator has run behind the closed VCA


def run(dur_s, key_s, sets=None):
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets or {}), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"), VoltageProbe("o_t")))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(dur_s * FS)
    t = np.arange(n) / FS
    gate = np.where((t >= HIT_S) & (t < HIT_S + key_s), KEY_DOWN_V, KEY_UP_V)
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls={"gate": gate}).vectors
    return v["v(out)"], v["v(o_t)"]


def lockin(y, f):
    t = np.arange(len(y)) / FS
    y = y - np.polyval(np.polyfit(t, y, 3), t)  # the supplies still settling
    return 2 * abs(np.mean(y * np.exp(-2j * np.pi * f * t)))


def test_passes_the_preflight_checks_with_its_gate():
    s = spec.load_circuit(CIRCUIT)
    assert s.cv_inputs == (("gate", "bus"),)
    assert check_circuit(s) == []


def test_a_hit_sweeps_down_and_decays_and_the_closed_vca_passes_nothing():
    out, tank = run(2.3, 0.05)
    i0 = int(HIT_S * FS)
    rest = vco.frequency(tank[int(0.5 * FS) : i0], FS)
    tc, f = vco.cycle_frequencies(tank[i0 : i0 + int(0.4 * FS)], FS)
    start = f[np.searchsorted(tc, 0.02)]
    end = f[np.searchsorted(tc, 0.25)]
    y = sosfiltfilt(butter(2, 20, "hp", fs=FS, output="sos"), out)
    peak = np.abs(y[i0 : i0 + int(0.3 * FS)]).max()
    late = np.abs(y[i0 + int(0.45 * FS) : i0 + int(0.6 * FS)]).max()
    bleed = lockin(out[int(0.4 * FS) : i0 - 100], rest)
    print(rest, start, end, peak, 20 * np.log10(late / peak), 20 * np.log10(bleed / peak))
    assert 45 < rest < 70
    assert start > 2.0 * rest
    assert abs(vco.cents(end, rest)) < 150
    assert 3.0 < peak < 15.0
    assert late < 0.1 * peak  # -20 dB within 450 ms at the default DECAY
    assert bleed < 10 ** (-70 / 20) * peak


def test_depth_zero_holds_the_pitch():
    _, tank = run(1.9, 0.05, {"depth": 0.0})
    i0 = int(HIT_S * FS)
    rest = vco.frequency(tank[int(0.5 * FS) : i0], FS)
    tc, f = vco.cycle_frequencies(tank[i0 : i0 + int(0.3 * FS)], FS)
    print(rest, f[:8])
    assert np.all(np.abs(vco.cents(f, rest)) < 100)

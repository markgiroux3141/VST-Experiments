"""The tube synth's filter and VCA (config/circuits/tube_filter.yaml; S2,
docs/TUBE_SYNTH_PLAN.md): the reactor low-pass between tube stages, a 6V6GT setting its
cutoff through the control windings, a 6386 as the VCA.

A 110 Hz sawtooth at full scale (1 V peak) at draft-1x (what the app plays). Measured
2026-10-29: the 6V6GT's plate current 0.06 / 4.5 / 18 mA at CUTOFF 0 / 0.5 / 1 (1 to
181 A/m of bias); the 20th harmonic -54 / -35 / -24 dB re the fundamental at CUTOFF
0 / 0.5 / 1 (a saw's own is -26); LEVEL 0 / 0.5 / 0.9 / 1: -112 / -21 / -11 / -1 dB re
2.5 V of fundamental (the 6386's remote cutoff: dB nearly linear in bias, steep at the
top); RESONANCE 0.9 lifts the 10th harmonic (1.1 kHz, at CUTOFF 0.5) ~9 dB over 0.3.
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

CIRCUIT = Path(CONFIG_DIR / "circuits" / "tube_filter.yaml")
F0 = 110.0


def run(**controls):
    """v(out) and the 6V6GT's cathode for a 110 Hz saw at full scale, after 0.25 s."""
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, controls))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft-1x"),
        full_scale_volts_peak=1.0,
    )
    t = np.arange(int(0.6 * FS)) / FS
    v = fast.run_transient(ir, 2 * ((F0 * t) % 1.0) - 1.0, settings=st).vectors
    return v["v(out)"][int(0.25 * FS) :], v


def harmonics(y, ks=(1, 10, 20)):
    sp = np.abs(np.fft.rfft(y * np.hanning(len(y)))) / len(y) * 4
    df = FS / len(y)
    return {k: sp[round(k * F0 / df)] for k in ks}


def db(a, b):
    return 20 * np.log10(a / b)


def test_passes_the_preflight_checks():
    assert check_circuit(spec.load_circuit(CIRCUIT)) == []


def test_the_cutoff_knob_sweeps_the_filter():
    h = {c: harmonics(run(cutoff=c, level=1.0)[0]) for c in (0.0, 0.5, 1.0)}
    rel = {c: db(x[20], x[1]) for c, x in h.items()}
    print(rel)
    assert rel[0.0] < -45 and -45 < rel[0.5] < -25 and rel[1.0] > -30
    assert rel[0.0] < rel[0.5] < rel[1.0]


def test_the_level_knob_is_a_vca_from_off_to_full():
    full = harmonics(run(cutoff=0.5, level=1.0)[0])[1]
    half = harmonics(run(cutoff=0.5, level=0.5)[0])[1]
    off = harmonics(run(cutoff=0.5, level=0.0)[0])[1]
    print(db(half, full), db(off, full))
    assert db(off, full) < -80
    assert -30 < db(half, full) < -10


def test_resonance_lifts_the_cutoff_region():
    lo = harmonics(run(cutoff=0.5, resonance=0.3)[0])
    hi = harmonics(run(cutoff=0.5, resonance=0.9)[0])
    lift = db(hi[10], lo[10]) - db(hi[1], lo[1])
    print(f"lift at 1.1 kHz {lift:.1f} dB")
    assert lift > 5

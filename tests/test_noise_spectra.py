"""Noise sources against theory, in both engines (device builder B5's done-when):
varimu.measure.noise_theory's test circuits, their spectra per octave band against the
closed forms, and the two engines on the same streams against each other."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import butter, sosfiltfilt

from varimu.measure import noise_theory as nt
from varimu.sim import ngspice

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

CASES = {
    "johnson": lambda: nt.johnson(),
    "triode": lambda: nt.tube("12AX7@1", vb=250.0, rl=100e3, vg=-1.5),
    "pentode": lambda: nt.tube("6V6GT@1", vb=250.0, rl=5e3, vg=-12.5, vs=250.0),
}


def _ngspice():
    try:
        ngspice.find_ngspice()
    except ngspice.SimulatorNotFound:
        pytest.skip("ngspice not available")


def _check(bands, tol_low_db: float, tol_db: float, split_hz: float = 256.0):
    bad = [
        (round(fc), round(d, 2))
        for fc, d, _ in bands
        if abs(d) > (tol_low_db if fc < split_hz else tol_db)
    ]
    assert not bad, f"bands off theory (centre Hz, dB): {bad}; all: {bands}"


@pytest.mark.parametrize("name", CASES)
def test_circuitsim_spectra_match_theory(name):
    """4 s at production, 16 Hz-16 kHz: within 0.5 dB per octave from 256 Hz up (measured
    within 0.30), 1.0 dB below (few bins: measured within 0.47)."""
    case = CASES[name]()
    v = nt.run(case, 4.0, "circuitsim")
    _check(nt.octaves(case, v, 16.0, 20000.0), 1.0, 0.5)


@pytest.mark.parametrize("name", CASES)
def test_ngspice_spectra_match_theory(name):
    """1 s (ngspice runs these ~3-30x slower than real time), 64 Hz-16 kHz: within 0.6 dB
    per octave from 256 Hz up, 1.0 dB below (measured within 0.45)."""
    _ngspice()
    case = CASES[name]()
    v = nt.run(case, 1.0, "ngspice")
    _check(nt.octaves(case, v, 64.0, 20000.0, nperseg=2**13), 1.0, 0.6)


def test_the_engines_agree_on_the_noise_waveform():
    """The same streams through both engines (ngspice as a reference: a timepoint on every
    sample; at its production settings its interpolation leaves -31 dB): the triode's noise
    (shot and flicker) below 20 kHz. Measured -61 dB here (-51 dB on triode_stage.yaml, a
    ~0.1-0.2% level offset, where circuitsim's 2x and 8x agree to -53 dB): bound -55 dB."""
    _ngspice()
    case = CASES["triode"]()
    a = nt.run(case, 0.25, "circuitsim", settle_s=0.05)
    b = nt.run(case, 0.25, "ngspice", reference=True, settle_s=0.05)
    sos = butter(8, 20000.0, fs=nt.RATE, output="sos")
    a, b = (sosfiltfilt(sos, x - np.mean(x))[480:] for x in (a, b))
    d_db = 20 * np.log10(np.std(a - b) / np.std(a))
    assert d_db < -55.0, f"engines differ by {d_db:.1f} dB re the noise"

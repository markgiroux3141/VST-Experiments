"""The tube synth's filter and VCA (config/circuits/tube_filter.yaml; S2,
docs/TUBE_SYNTH_PLAN.md): the reactor low-pass between tube stages, a 6V6GT setting its
cutoff through the control windings, a 12AX7 Q multiplier for its resonance, a 6386 as the
VCA, all on one supply (6X4 full wave, a selenium bridge for the bias).

A 110 Hz sawtooth at draft-1x (what the app plays); the numbers each test measured are in
its docstring.
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import butter, sosfiltfilt

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.preflight import check_circuit
from varimu.sim import fast, io

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

from engine_compare import FS  # noqa: E402

CIRCUIT = Path(CONFIG_DIR / "circuits" / "tube_filter.yaml")
F0 = 110.0


def settings():
    return dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft-1x"),
        full_scale_volts_peak=1.0,
    )


def build(**controls):
    s = spec.load_circuit(CIRCUIT)
    return builder.build_ir(s, spec.resolve(s, controls))


def run(amp=1.0, f0=F0, **controls):
    """v(out) for a saw of `amp` V peak at f0, after 0.25 s."""
    t = np.arange(int(0.6 * FS)) / FS
    x = amp * (2 * ((f0 * t) % 1.0) - 1.0)
    return fast.run_transient(build(**controls), x, settings=settings()).vectors["v(out)"][
        int(0.25 * FS) :
    ]


def harmonics(y, ks=(1, 10, 20), f0=F0):
    sp = np.abs(np.fft.rfft(y * np.hanning(len(y)))) / len(y) * 4
    df = FS / len(y)
    return {k: sp[round(k * f0 / df)] for k in ks}


def db(a, b):
    return 20 * np.log10(a / b)


def test_passes_the_preflight_checks():
    assert check_circuit(spec.load_circuit(CIRCUIT)) == []


def test_the_cutoff_knob_sweeps_the_filter():
    """The 20th harmonic (2.2 kHz) re the fundamental at CUTOFF 0 / 0.5 / 1 (a saw's own:
    -26 dB). Measured 2026-10-29: -54 / -32 / -24 dB."""
    h = {c: harmonics(run(cutoff=c, resonance=0.0)) for c in (0.0, 0.5, 1.0)}
    rel = {c: db(x[20], x[1]) for c, x in h.items()}
    print(rel)
    assert rel[0.0] < -45 and -45 < rel[0.5] < -25 and rel[1.0] > -30
    assert rel[0.0] < rel[0.5] < rel[1.0]


def test_the_level_knob_is_a_vca_from_off_to_full():
    """The fundamental at LEVEL 0.5 and 0 re LEVEL 1 (the 6386's remote cutoff: dB nearly
    linear in bias, steep at the top). Measured 2026-10-29: -18.5 / -49.8 dB. Off is VCA
    bleed through the tube itself: at -103 V with ~280 V on its plate the 6386's remote
    tail still passes ~4% of its grid signal (the plate supply carries 0.006 mV of it; with
    the VCA on b3, the input stages' rail, the supply leaked -34 dB)."""
    full = harmonics(run(cutoff=0.5, level=1.0))[1]
    half = harmonics(run(cutoff=0.5, level=0.5))[1]
    off = harmonics(run(cutoff=0.5, level=0.0))[1]
    print(db(half, full), db(off, full))
    assert db(off, full) < -45
    assert -30 < db(half, full) < -10


def test_resonance_lifts_the_cutoff_region():
    """A quiet saw (-20 dBFS, 55 Hz) at CUTOFF 0.5: the largest lift of any harmonic with
    RESONANCE 0.6 over 0, near the cutoff. At full scale the 12AX7 pair runs out of headroom
    and lifts far less (louder, less resonant). Measured 2026-10-29: +8.2 dB at ~4.6 kHz."""
    f0, ks = 55.0, tuple(range(1, 120))

    def response(res):
        h = harmonics(run(amp=0.1, f0=f0, cutoff=0.5, resonance=res), ks, f0)
        return np.array([20 * np.log10(h[k] * k) for k in ks])  # x k: flat for a saw

    lift = response(0.6) - response(0.0)
    k = int(np.argmax(lift))
    print(f"lift {lift[k]:.1f} dB at {ks[k] * f0:.0f} Hz")
    assert lift[k] > 5 and 1500 < ks[k] * f0 < 8000


def test_the_filter_oscillates_at_full_resonance():
    """At CUTOFF 0.25 a 2 ms pulse, then silence: with RESONANCE 1 the filter sustains a
    tone near its cutoff; at 0.5 it rings down. Measured 2026-10-29 (0.8-1.2 s, above
    200 Hz): -24 dBFS at ~700 Hz, against -110."""
    x = np.zeros(int(1.2 * FS))
    x[int(0.01 * FS) : int(0.012 * FS)] = 0.5
    hp = butter(4, 200, "highpass", fs=FS, output="sos")
    tail = {}
    for res in (0.5, 1.0):
        v = fast.run_transient(build(cutoff=0.25, resonance=res), x, settings=settings())
        y = sosfiltfilt(hp, v.vectors["v(out)"])[int(0.8 * FS) :]
        tail[res] = 20 * np.log10(np.sqrt(np.mean(y**2)) / 5 + 1e-15)
        if res == 1.0:
            sp = np.abs(np.fft.rfft(y * np.hanning(len(y))))
            f_hz = np.argmax(sp) * FS / len(y)
    print(tail, f_hz)
    assert tail[1.0] > -35 and tail[0.5] < -80
    assert 400 < f_hz < 1500

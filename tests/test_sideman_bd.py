"""The Side Man's bass drum (config/circuits/sideman_bd.yaml; docs/DRUM_PLAN.md, D2a): V100-A
of schematic 501648, a 12AX7 phase-lead oscillator degenerated below oscillation and struck
by its ground-out key line. Measured at production, 2026-11-04 (scripts/sideman_study.py):
at the RING trim's default (calibrated to the drawing's +1.5 V cathode) the plate idles at
176 V (drawing +174), a hit rings at ~70 Hz (the patent: "about 65 c.p.s."), -20 dB at
~117 ms; more degeneration rings shorter and higher; at RING 0.4 and below it oscillates.
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import hilbert

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.preflight import check_circuit
from varimu.sim import fast, io
from varimu.synth import vco

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

CIRCUIT = Path(CONFIG_DIR / "circuits" / "sideman_bd.yaml")
FS = 96000
HIT_S = 0.2
KEY_UP_V, KEY_DOWN_V = -40.0, 0.0


def run(dur_s, hits_s=(HIT_S,), sets=None, key_s=0.02):
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets or {}))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in ("out", "p", "k")))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production"),
        full_scale_volts_peak=1.0,
    )
    n = int(dur_s * FS)
    t = np.arange(n) / FS
    gate = np.full(n, KEY_UP_V)
    for h in hits_s:
        gate[(t >= h) & (t < h + key_s)] = KEY_DOWN_V
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls={"gate": gate}).vectors
    return v["v(out)"], v["v(p)"], v["v(k)"]


def ring_ms(out, i0, level_db=-20.0):
    e = np.abs(hilbert(out[i0:] - out[i0 - 1]))
    e = np.convolve(e, np.ones(960) / 960, mode="same")
    pk = int(np.argmax(e))
    below = np.flatnonzero(20 * np.log10(e[pk:] / e[pk] + 1e-12) < level_db)
    return (pk + below[0]) / FS * 1000 if len(below) else None


def test_passes_the_preflight_checks_with_its_gate():
    s = spec.load_circuit(CIRCUIT)
    assert s.cv_inputs == (("gate", "key"),)
    assert check_circuit(s) == []


def test_idles_at_the_drawings_voltages():
    _, p, k = run(0.15, hits_s=())
    assert abs(p[-1] - 174.0) < 0.05 * 174.0  # dwg 501648: plate +174 V
    assert abs(k[-1] - 1.5) < 0.1  # cathode +1.5 V


def test_a_hit_rings_near_the_patents_pitch_and_dies_away():
    out, p, _ = run(1.2)
    i0 = int(HIT_S * FS)
    tc, f = vco.cycle_frequencies(p[i0:] - p[i0 - 1], FS)
    f50 = f[np.searchsorted(tc, 0.05)]
    t20 = ring_ms(out, i0)
    print(f50, t20, np.abs(out[i0:]).max())
    assert 60 < f50 < 78  # "about 65 c.p.s."
    assert t20 is not None and 70 < t20 < 200
    assert 0.8 < np.abs(out[i0:]).max() < 2.5  # full scale 2.5 V
    assert np.abs(out[i0 - 2000 : i0]).max() < 1e-3  # silent before the key


def test_ring_sets_the_drums_size():
    out_big, _, _ = run(1.2, sets={"ring": 0.5})
    out_small, _, _ = run(1.2, sets={"ring": 1.0})
    i0 = int(HIT_S * FS)
    big, small = ring_ms(out_big, i0), ring_ms(out_small, i0)
    print(big, small)
    assert big > 1.5 * small


def test_sixteenths_hit_softer_while_the_key_line_recovers():
    beat = 0.125  # sixteenths at 120 BPM
    hits = [HIT_S + i * beat for i in range(6)]
    out, _, _ = run(HIT_S + 6 * beat + 0.3, hits_s=hits)
    peaks = [np.abs(out[int(h * FS) : int((h + 0.05) * FS)]).max() for h in hits]
    drop_db = 20 * np.log10(peaks[-1] / peaks[0])
    print(drop_db)
    assert -6.0 < drop_db < -1.0

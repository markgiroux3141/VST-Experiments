"""Sympathetic resonance (docs/RHODES_IMPERFECTION_PLAN.md): the keys coupled through the tone
bar rail. circuitsim's coupled harp medium against the reference (varimu/rhodes/sympathetic.py),
off at amount 0 bit for bit, and the IR's checks.

The medium reads a key only ringing in sympathy through the pickup's small-signal gain while
its swing is small (harp.rs `LINEAR_M`); the reference reads every key through the whole map.
That readout is the agreement's floor here: ~1e-3 of the rail's part (-55 dB re it), far
under the whole (-80 dB re it); without it the two agreed within -118 dB (2026-11-22)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from varimu.circuit import builder, ir, spec
from varimu.rhodes import compile as hc
from varimu.rhodes import imperfection as imp
from varimu.rhodes import midi
from varimu.rhodes import sympathetic as sy

circuitsim = pytest.importorskip("circuitsim")

FS = 48000.0
KEYS = [20, 32, 44, 56, 68]
E = midi.Event
# a pedalled phrase: a key released under the pedal, the pedal up at a chunk's first sample
# (0.8 s: where a lost switch was found), a key struck twice, keys released
EVENTS = [
    E(0.002, "pedal", value=1),
    E(0.01, "on", 40, 110),
    E(0.30, "on", 52, 100),
    E(0.60, "off", 40),
    E(0.80, "pedal", value=0),
    E(0.90, "on", 64, 90),
    E(1.00, "on", 64, 120),
    E(1.20, "off", 64),
    E(1.30, "off", 52),
]
N = int(1.5 * FS)


def _db(err: np.ndarray, ref: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(err**2)) / np.sqrt(np.mean(ref**2)))


@pytest.fixture(scope="module")
def data():
    return hc.compile_harp(keys=KEYS, workers=1)


def _rust(data, sym=None, i=None, events=EVENTS, n=N):
    el = {"name": "VHARP", "out": "h", "rate_hz": 2 * FS, "contact_rate_hz": 4 * FS}
    el["model"] = data
    if sym is not None:
        el["sympathetic"] = sym
    if i is not None:
        el["imperfection"] = {k: float(getattr(i, k)) for k in ("seed", "amount", *imp.PARTS)}
    ordered = sorted(events, key=lambda ev: (ev.t_s, ev.kind != "off"))
    notes = [(round(ev.t_s * FS), ev.kind, ev.note, ev.value) for ev in ordered]
    _, raw, _ = circuitsim.harp_render(json.dumps(el), FS, n, notes)
    return np.asarray(raw)


def _ref(amount, i=None):
    return sy.render(
        EVENTS, (N - 1) / FS, amount=amount, fs_hz=FS, oversample=2, keys=KEYS, imperfection=i
    )


def test_amount_zero_is_off_bit_for_bit(data):
    assert np.array_equal(_rust(data, 0.0), _rust(data))


def test_the_reference_at_amount_zero_is_the_rigid_rail():
    r = _ref(0.0)
    assert np.max(np.abs(r.raw_v - r.rigid_raw_v)) < 1e-15


@pytest.mark.parametrize("amount", [1.0, 10.0])
def test_circuitsim_rings_in_sympathy_as_the_reference(data, amount):
    off = _rust(data)
    raw = _rust(data, amount)
    ref = _ref(amount).raw_v
    assert raw.size == ref.size
    sym = ref - off  # the rail's part (the struck keys' own sound is off's to -136 dB)
    assert _db(raw - ref, sym) < -55
    assert _db(raw - ref, ref) < -80
    # and it is heard: -42 dB re the whole at 1 on these five keys, -22 at 10
    assert _db(raw - off, off) > (-50 if amount == 1.0 else -30)


def test_an_imperfect_harp_rings_in_sympathy_as_the_reference(data):
    unit = imp.Imperfection(seed=5, amount=2.0)
    ref = _ref(3.0, unit).raw_v
    raw = _rust(data, 3.0, unit)
    assert _db(raw - ref, ref) < -80


def test_the_rail_steps_exactly():
    """osc_zoh against the matrix exponential of the mode's state space."""
    from scipy import linalg

    w, zeta, dt = 2 * np.pi * 36.2, 0.02, 1 / 96000
    ad, bd = sy.osc_zoh(w, zeta, dt)
    a = np.array([[0.0, 1.0], [-w * w, -2 * zeta * w], [0.0, 0.0]])
    big = np.zeros((3, 3))
    big[:2, :2] = a[:2]
    big[1, 2] = 1.0
    e = linalg.expm(big * dt)
    assert np.allclose(np.array(ad).reshape(2, 2), e[:2, :2], rtol=1e-12, atol=0)
    assert np.allclose(bd, e[:2, 2], rtol=1e-9, atol=0)


def test_the_ir_checks_the_amount_and_the_rail():
    old = hc.load_data("MK1_HARP@2")
    with pytest.raises(ir.IRError, match="no rail"):
        ir._validate_harp(ir.Harp("V", "h", 96000.0, 384000.0, old, None, 1.0), "in")
    new = hc.load_data("MK1_HARP@3")
    with pytest.raises(ir.IRError, match="in \\[0, 30"):
        ir._validate_harp(ir.Harp("V", "h", 96000.0, 384000.0, new, None, 31.0), "in")
    ir._validate_harp(ir.Harp("V", "h", 96000.0, 384000.0, new, None, 30.0), "in")


def test_the_suitcase_switches_it_on():
    s = spec.load_circuit(spec.circuit_path("rhodes_suitcase_100w"))

    def harp(over):
        c = builder.build(s, over)
        return next(e for sec in c.ir.sections for e in sec.elements if isinstance(e, ir.Harp))

    plain = harp({})
    assert plain.sympathetic is None and plain.imperfection.amount == 0.0
    on = harp({"sympathy": 1, "sympathy_amount": 4.0, "imp_amount": 7.0})
    assert on.sympathetic == 4.0 and on.imperfection.amount == 7.0

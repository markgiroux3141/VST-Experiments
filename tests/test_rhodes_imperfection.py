"""An imperfect Rhodes (docs/RHODES_IMPERFECTION_PLAN.md): the reference
(varimu/rhodes/imperfection.py through harp.py's voices) and circuitsim's harp medium agree,
amount 0 is the compiled harp bit for bit, and the draws are pure functions of what they name."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from varimu.rhodes import compile as hc
from varimu.rhodes import harp, midi
from varimu.rhodes import imperfection as imp

circuitsim = pytest.importorskip("circuitsim")

FS = 48000.0
KEYS = [20, 44, 56, 68]
UNIT = imp.Imperfection(seed=7, amount=2.0)


def _db(err: np.ndarray, ref: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(err**2)) / np.sqrt(np.mean(ref**2)))


@pytest.fixture(scope="module")
def data():
    return hc.compile_harp(keys=KEYS, workers=1)


def _ir(i: imp.Imperfection | None) -> dict | None:
    if i is None:
        return None
    return {k: float(getattr(i, k)) for k in ("seed", "amount", *imp.PARTS)}


def _rust(data, events, n, i=None):
    el = {"name": "VHARP", "out": "h", "rate_hz": 2 * FS, "contact_rate_hz": 4 * FS}
    el["model"] = data
    if i is not None:
        el["imperfection"] = _ir(i)
    ordered = sorted(events, key=lambda ev: (ev.t_s, ev.kind != "off"))
    notes = [(round(ev.t_s * FS), ev.kind, ev.note, ev.value) for ev in ordered]
    _, raw, _ = circuitsim.harp_render(json.dumps(el), FS, n, notes)
    return np.asarray(raw)


E = midi.Event
EVENTS = [
    E(100 / FS, "on", 40, 100),
    E(2000 / FS, "on", 64, 70),
    E(2300 / FS, "pedal", value=1),
    E(5000 / FS, "off", 40),
    E(6000 / FS, "on", 76, 127),
    E(6500 / FS, "on", 76, 90),  # struck again, ringing
    E(9000 / FS, "off", 64),
    E(12000 / FS, "pedal", value=0),
    E(14000 / FS, "on", 88, 60),
    E(16000 / FS, "off", 88),
    E(17000 / FS, "on", 88, 60),  # released and struck again: a second release follows
    E(19000 / FS, "off", 88),
    E(20000 / FS, "on", 40, 100),
    E(22000 / FS, "off", 40),
]
N = 24000


def test_amount_zero_is_the_compiled_harp_bit_for_bit(data):
    plain = _rust(data, EVENTS, N)
    zero = replace(UNIT, amount=0.0)
    assert np.array_equal(_rust(data, EVENTS, N, zero), plain)
    shares_off = imp.Imperfection(7, 1.0, *([0.0] * len(imp.PARTS)))
    assert np.array_equal(_rust(data, EVENTS, N, shares_off), plain)
    ref = harp.render(EVENTS, (N - 1) / FS, fs_hz=FS, oversample=2, step_oversample=4)
    ref0 = harp.render(
        EVENTS, (N - 1) / FS, fs_hz=FS, oversample=2, step_oversample=4, imperfection=zero
    )
    assert np.array_equal(ref.raw_v, ref0.raw_v)


def test_circuitsim_plays_an_imperfect_harp_as_the_reference(data):
    """Every part at amount 2: the medium's internal EMF against harp.render's, within the
    arc's reduction (as test_rhodes_compiled's perfect harp, -128 dB there)."""
    ref = harp.render(
        EVENTS, (N - 1) / FS, fs_hz=FS, oversample=2, step_oversample=4, imperfection=UNIT
    ).raw_v
    raw = _rust(data, EVENTS, N, UNIT)
    assert raw.size == ref.size
    assert _db(raw - ref, ref) < -110
    # and it is another instrument
    assert _db(raw - _rust(data, EVENTS, N), ref) > -30


@pytest.mark.parametrize("part", imp.PARTS)
def test_each_part_alone_agrees_and_moves_the_sound(data, part):
    one = imp.Imperfection(7, 2.0, *[1.0 if p == part else 0.0 for p in imp.PARTS])
    ref = harp.render(
        EVENTS, (N - 1) / FS, fs_hz=FS, oversample=2, step_oversample=4, imperfection=one
    ).raw_v
    raw = _rust(data, EVENTS, N, one)
    assert _db(raw - ref, ref) < -110
    assert not np.array_equal(raw, _rust(data, EVENTS, N))


def test_a_repeated_note_differs_strike_to_strike_only_with_the_hammer(data):
    gap = 1.0  # the tine asleep again before the next strike
    events = [E(0.01 + gap * i, "on", 64, 90) for i in range(3)]
    events += [E(0.01 + gap * i + 0.3, "off", 64) for i in range(3)]
    n = int(3 * gap * FS)
    w = int(0.25 * FS) * 2  # internal samples (2x) per note's first 0.25 s

    def notes(raw):
        return [raw[2 * round((0.01 + gap * i) * FS) :][:w] for i in range(3)]

    per_key = replace(UNIT, dampers=0.0, hammer=0.0, release=0.0)
    still = notes(_rust(data, events, n, per_key))
    assert np.array_equal(still[0], still[1]) and np.array_equal(still[1], still[2])
    moving = notes(_rust(data, events, n, imp.Imperfection(7, 1.0, 0, 0, 0, 0, 0, 1.0, 0)))
    for a, b in ((0, 1), (1, 2)):
        d = _db(moving[a] - moving[b], moving[a])
        assert -60 < d < -5, d


def test_draws_are_pure_functions_of_what_they_name():
    a = imp.key_draws(UNIT, 44, 2e-3)
    assert imp.key_draws(UNIT, 44, 2e-3) == a
    # another share doesn't move a part's draw
    b = imp.key_draws(replace(UNIT, tips=0.0, decay=0.5), 44, 2e-3)
    assert (b.ratio, b.voicing_m, b.damper) == (a.ratio, a.voicing_m, a.damper)
    assert b.stiffness == 1.0
    # another key, another seed: other draws
    assert imp.key_draws(UNIT, 45, 2e-3) != a
    assert imp.key_draws(replace(UNIT, seed=8), 44, 2e-3) != a
    # strikes and releases by count
    s = [imp.strike_draws(UNIT, 44, c) for c in range(4)]
    assert len(set(s)) == 4 and imp.strike_draws(UNIT, 44, 2) == s[2]
    assert imp.release_draw(UNIT, 44, 0) != imp.release_draw(UNIT, 44, 1)
    # amount 0: identity
    z = replace(UNIT, amount=0.0)
    assert imp.key_draws(z, 44, 2e-3) == imp.KeyDraws(1.0, 2e-3, 1.0, 1.0, 1.0)
    assert imp.strike_draws(z, 44, 3) == (1.0, 1.0) and imp.release_draw(z, 44, 3) == 1.0


def test_the_spreads_are_what_the_constants_say():
    """Over the 73 keys at amount 1, the per-key draws' spreads (a sample of 73)."""
    one = imp.Imperfection(seed=3, amount=1.0)
    d = [imp.key_draws(one, n, 2e-3) for n in range(8, 81)]
    cents = 1200 * np.log2([x.ratio for x in d])
    assert np.std(cents) == pytest.approx(imp.TUNING_CENTS, rel=0.3)
    assert np.std(np.log([x.decay for x in d])) == pytest.approx(imp.DECAY_SPREAD, rel=0.3)
    v = np.array([x.voicing_m for x in d])
    assert v.min() >= imp.VOICING_RANGE_M[0] and v.max() <= imp.VOICING_RANGE_M[1]


def test_a_detuned_key_sounds_its_cents(data):
    """The key's fundamental moves by its drawn ratio (the time scaling is exact)."""
    one = imp.Imperfection(5, 2.0, 1.0, 0, 0, 0, 0, 0, 0)
    key, note = 44, 44 + harp.MIDI_KEY_OFFSET
    events = [E(0.01, "on", note, 90)]
    n = int(1.5 * FS)

    def f0(raw):
        s = raw[int(0.3 * 2 * FS) :]
        m = np.abs(np.fft.rfft(s * np.hanning(s.size), 1 << 22))
        fr = np.fft.rfftfreq(1 << 22, 1 / (2 * FS))
        hz = 440 * 2 ** ((note - 69) / 12)
        band = (fr > 0.95 * hz) & (fr < 1.05 * hz)
        return fr[band][np.argmax(m[band])]

    want = imp.key_draws(one, key, 2e-3).ratio
    got = f0(_rust(data, events, n, one)) / f0(_rust(data, events, n))
    assert 1200 * np.log2(got) == pytest.approx(1200 * np.log2(want), abs=0.15)


def test_the_ir_checks_the_imperfection():
    from varimu.circuit import ir

    bad = imp.Imperfection(seed=1, amount=2.5)
    with pytest.raises(ValueError):
        imp.check(bad)
    model = {"format": 1, "keys": [1]}
    el = ir.Harp("VH", "h", 96e3, 192e3, model, ir.HarpImperfection(1, 2.5, 1, 1, 1, 1, 1, 1, 1))
    with pytest.raises(ir.IRError, match="imperfection"):
        ir._validate_harp(el, "in")

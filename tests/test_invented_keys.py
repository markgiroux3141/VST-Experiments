"""The invented keyboards' live tier (docs/INVENTED_LIVE_PLAN.md): circuitsim's invented.rs
against the Python references in varimu/invented/keys/, on performances."""

from __future__ import annotations

import json

import numpy as np
import pytest

from varimu.invented.keys import common
from varimu.invented.keys import compile as kc

circuitsim = pytest.importorskip("circuitsim")

FS = 48_000.0


def element(ref: str, knobs: list[float], max_keys: int = 16) -> dict:
    instrument, data, sha = kc.ir_data(ref)
    return {
        "name": "VKEYS",
        "out": "out",
        "instrument": instrument,
        "data": data,
        "sha256": sha,
        "rate_hz": FS,
        "max_keys": float(max_keys),
        "k0": knobs[0],
        "k1": knobs[1],
        "k2": knobs[2],
        "k3": knobs[3],
    }


def db(err: np.ndarray, ref: np.ndarray) -> float:
    return 20 * np.log10(max(np.sqrt(np.mean(err**2)), 1e-300) / np.sqrt(np.mean(ref**2)))


PERFORMANCE = [
    (0, "on", 57, 90),
    (int(0.15 * FS), "on", 64, 50),
    (int(0.30 * FS), "pressure", 0, 100),
    (int(0.35 * FS), "off", 57, 0),
    (int(0.40 * FS), "pedal", 0, 1),
    (int(0.45 * FS), "off", 64, 0),
    (int(0.50 * FS), "on", 57, 120),  # a re-strike of a ringing bar
    (int(0.60 * FS), "pedal", 0, 0),
    (int(0.70 * FS), "off", 57, 0),
]


def test_the_rosin_wheel_agrees_with_its_reference():
    from varimu.invented.keys import rosin

    ref = kc.latest("ROSIN_WHEEL")
    knobs = [0.375, 0.5, 0.333, 0.0]
    n = int(0.9 * FS)
    kb = rosin.keyboard(kc.load(ref), FS, knobs)
    want = common.play(kb, n, PERFORMANCE, lambda v: v.step())
    got = circuitsim.invented_render(json.dumps(element(ref, knobs)), FS, n, PERFORMANCE, 0)
    assert np.sqrt(np.mean(want**2)) > 1e-3  # it sounds
    assert db(got - want, want) < -120


def test_the_keys_are_the_same_on_any_number_of_threads():
    ref = kc.latest("ROSIN_WHEEL")
    el = json.dumps(element(ref, [0.375, 0.5, 0.333, 0.0]))
    chord = [(0, "on", k, 80) for k in (48, 52, 55, 60, 64, 67)]
    a = circuitsim.invented_render(el, FS, 9600, chord, 0)
    b = circuitsim.invented_render(el, FS, 9600, chord, 3)
    assert np.array_equal(a, b)

"""Varispeed (docs/DELAY_PLAN.md, "The 351 echo"): the capstan's motor on a variable-frequency
supply. circuitsim's stream against the Python reference (varimu.devices.tape_machine.
TapeStream, and the reduced medium's varimu.delay.reduced.ReducedStream) with the supply
moving, and the physics: the delay is the head distance over the speed the supply sets."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from varimu.delay import reduced as rd
from varimu.devices import tape_machine as tm
from varimu.devices.library import load_tape

circuitsim = pytest.importorskip("circuitsim")

FS = 96000.0


def _supply(n: int) -> np.ndarray:
    """60 Hz, a step to 54 Hz at 40 ms, a glide up to 66 Hz from 120 ms to 180 ms."""
    t = np.arange(n) / FS
    f = np.where(t < 0.04, 60.0, 54.0)
    ramp = np.clip((t - 0.12) / 0.06, 0.0, 1.0)
    return np.where(t < 0.12, f, 54.0 + 12.0 * ramp)


def _signal(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng([seed, 60])
    return np.convolve(rng.standard_normal(n), np.ones(6) / 6.0, mode="same") * 25e3


def test_full_medium_agrees_with_reference():
    tape = load_tape("SCOTCH111@3")
    spec = dataclasses.replace(tm.TapeMachineSpec(), varispeed_nominal_hz=60.0)
    al_bias = 60e3
    v = spec.speed_m_s
    d = round(spec.head_distance_m / v * FS) * v / FS
    n = int(0.25 * FS)
    x, sup = _signal(n, 1), _supply(n)
    ref = tm.TapeStream(spec, tape, al_bias, FS, engine="rust", head_distance_m=d)
    chunk = 3000
    e_ref = np.concatenate(
        [ref.push_many(x[c : c + chunk], sup[c : c + chunk]) for c in range(0, n, chunk)]
    )
    params = json.dumps(tm.stream_params(spec, tape, al_bias, head_distance_m=d))
    e_rs = np.asarray(circuitsim.tape_stream_run(params, FS, x, chunk=2345, supply_hz=sup))
    live = np.abs(e_ref).max()
    assert live > 0
    assert np.abs(e_rs - e_ref).max() <= 1e-9 * live


def test_reduced_medium_agrees_with_reference():
    from tests.test_tape_reduced import _params, _reduction  # the synthetic reduction

    tape = load_tape("SCOTCH111@3")
    spec = dataclasses.replace(tm.TapeMachineSpec(), varispeed_nominal_hz=60.0)
    red, demag = _reduction(spec.layers)
    v = spec.speed_m_s
    d = round(spec.head_distance_m / v * FS) * v / FS
    n = int(0.4 * FS)
    x, sup = _signal(n, 2), _supply(n)
    ref = rd.ReducedStream(spec, tape, red, FS, ds_m=2e-6, demag=demag, head_distance_m=d)
    chunk = 2000
    e_ref = np.concatenate(
        [ref.push_many(x[c : c + chunk], sup[c : c + chunk]) for c in range(0, n, chunk)]
    )
    e_rs = np.asarray(
        circuitsim.tape_stream_run(
            _params(spec, tape, red, demag, d), FS, x, chunk=1111, supply_hz=sup
        )
    )
    live = np.abs(e_ref).max()
    assert live > 0
    assert np.abs(e_rs - e_ref).max() <= 1e-10 * live


def _click_delay(supply_hz: float, spec, tape, red, demag) -> float:
    """The time from a click recorded at a steady supply frequency to its playback (the
    EMF's zero crossing between its two lobes: the flux's derivative)."""
    n = int(0.3 * FS)
    x = np.zeros(n)
    t_click = 0.02
    x[int(t_click * FS)] = 30e3
    from tests.test_tape_reduced import _params

    e = np.asarray(
        circuitsim.tape_stream_run(
            _params(spec, tape, red, demag, spec.head_distance_m),
            FS,
            x,
            supply_hz=np.full(n, float(supply_hz)),
        )
    )
    lo, hi = sorted((int(np.argmax(e)), int(np.argmin(e))))
    z = lo + int(np.argmin(np.abs(e[lo : hi + 1])))
    return (z + 1) / FS - t_click  # push n returns the EMF at t_{n+1}


def test_delay_is_head_distance_over_speed():
    """The slap's delay times the speed the supply sets is the same at every frequency: the
    head distance less where the aperture records (a few tens of um behind the gap)."""
    from tests.test_tape_reduced import _reduction

    tape = load_tape("SCOTCH111@3")
    spec = dataclasses.replace(tm.TapeMachineSpec(), varispeed_nominal_hz=60.0, flutter=False)
    red, demag = _reduction(spec.layers)
    v = spec.speed_m_s
    lengths = {f: _click_delay(f, spec, tape, red, demag) * v * f / 60.0 for f in (50, 60, 72)}
    ds = v / FS  # a sample's tape at 15 ips
    assert max(lengths.values()) - min(lengths.values()) < 3 * ds
    for length in lengths.values():
        assert 0 < spec.head_distance_m - length < 60e-6


def test_supply_needed_and_checked():
    tape = load_tape("SCOTCH111@3")
    spec = dataclasses.replace(tm.TapeMachineSpec(), varispeed_nominal_hz=60.0)
    params = json.dumps(tm.stream_params(spec, tape, 60e3))
    with pytest.raises(Exception, match="supply"):
        circuitsim.tape_stream_run(params, FS, np.zeros(100))

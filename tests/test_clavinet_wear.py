"""A worn Clavinet (docs/CLAVINET_PLAN.md, "Variation and wear"; varimu/clavinet/wear.py the
reference, circuitsim's `ClavModel::worn` the port): nothing worn is the compiled
instrument exactly, each amount moves only its part, the draws are a pure function of the
seed, Rust plays a worn instrument as the twin does, and the worst wear still strikes every
key."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from varimu.clavinet import compile as cc
from varimu.clavinet import live, spec, wear
from varimu.devices import versions

FS = 96000.0


def _db(err: np.ndarray, ref: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(err**2)) / np.sqrt(np.mean(ref**2))))


@pytest.fixture(scope="module")
def saved():
    have = versions.versions(cc.COMPONENT)
    ref = f"{cc.COMPONENT}@{have[-1]}"
    header, arrays = cc.load_data(ref)
    return ref, header, arrays


def test_the_nominal_shore_is_the_instruments():
    assert spec.load()["tangent"]["rubber_shore_a"] == wear.NOMINAL_SHORE


def test_nothing_worn_is_the_compiled_instrument(saved):
    _, header, arrays = saved
    for w in (
        None,
        wear.Wear(age=0.0),
        wear.Wear(seed=7, age=1.0, tuning=0, strings=0, tangents=0, yarn=0, pickups=0),
    ):
        h, a = wear.apply(header, arrays, w)
        assert h is header and a is arrays


def test_each_amount_moves_only_its_part(saved):
    _, header, arrays = saved
    n = 36
    zero = {k: 0.0 for k in wear.AMOUNTS}

    def worn(part):
        h, a = wear.apply(header, arrays, wear.Wear(seed=3, age=1.0, **{**zero, part: 1.0}))
        kd = next(k for k in h["keys"] if k["key"] == n)
        return kd, a[n]

    kd0 = next(k for k in header["keys"] if k["key"] == n)
    a0 = arrays[n]
    kd, a = worn("tuning")
    assert np.array_equal(a["released.lam_free"].real, a0["released.lam"].real)
    assert not np.array_equal(a["held.lam"].imag, a0["held.lam"].imag)
    assert kd["contact"] == kd0["contact"] and kd["pickups"] == kd0["pickups"]
    kd, a = worn("yarn")
    assert np.array_equal(a["held.lam"], a0["held.lam"])
    lf, lr = a["released.lam_free"], a0["released.lam"]
    assert np.array_equal(lf.imag, lr.imag) and np.all(lf.real >= lr.real)
    assert np.any(lf.real > lr.real), "the yarn damps less"
    kd, a = worn("tangents")
    assert kd["contact"]["rubber_k"] > kd0["contact"]["rubber_k"]
    assert kd["contact"]["hold_shift_m"] > 0
    assert np.array_equal(a["held.lam"], a0["held.lam"]) and "released.lam_free" in a
    kd, a = worn("pickups")
    assert kd["pickups"]["centre"]["clearance_m"] != kd0["pickups"]["centre"]["clearance_m"]
    assert kd["contact"] == kd0["contact"]
    kd, a = worn("strings")
    assert np.all(a["held.lam"].real <= a0["held.lam"].real)
    # every contact run keeps the compiled released modes (wear.py's docstring)
    assert all(np.array_equal(worn(p)[1]["released.lam"], a0["released.lam"]) for p in wear.AMOUNTS)


def test_the_draws_are_a_pure_function_of_the_seed(saved):
    _, header, arrays = saved
    a = wear.apply(header, arrays, wear.Wear(seed=5))[1]
    b = wear.apply(header, arrays, wear.Wear(seed=5))[1]
    c = wear.apply(header, arrays, wear.Wear(seed=6))[1]
    assert np.array_equal(a[40]["held.lam"], b[40]["held.lam"])
    assert not np.array_equal(a[40]["held.lam"], c[40]["held.lam"])


def test_a_wear_out_of_range_is_refused():
    with pytest.raises(ValueError):
        wear.check(wear.Wear(age=2.5))
    with pytest.raises(ValueError):
        wear.check(wear.Wear(seed=1.5))


circuitsim = pytest.importorskip("circuitsim")

WORN = wear.Wear(seed=11, age=1.0)
EVENTS = [
    (100, ("on", 41, 100)),
    (103, ("on", 48, 64)),
    (106, ("on", 29, 127)),
    (2500, ("pressure", 90)),
    (5000, ("off", 41)),
    (5300, ("on", 41, 30)),
    (9000, ("off", 41)),
    (9000, ("off", 48)),
    (9500, ("off", 29)),
]
N = 14000


def _element(ref: str, w: wear.Wear | None) -> str:
    data, sha = cc.ir_data(ref)
    el = {
        "name": "VSTRINGS",
        "centre": "ec",
        "bridge": "eb",
        "bridge_neg": "ebn",
        "rate_hz": 96000.0,
        "contact_rate_hz": 96000.0 * 16,
        "data": data,
        "sha256": sha,
    }
    if w is not None:
        el["wear"] = {k: float(v) for k, v in dataclasses.asdict(w).items()}
    return json.dumps(el)


def _notes(events):
    out = []
    for at, ev in events:
        if ev[0] == "pressure":
            out.append((at, "pressure", 0, ev[1]))
        else:
            out.append((at, ev[0], ev[1], ev[2] if len(ev) > 2 else 0))
    return out


def test_rust_plays_a_worn_instrument_as_the_twin_does(saved):
    ref, header, arrays = saved
    yc, yb, rc, rb, (k, s) = circuitsim.clav_render(_element(ref, WORN), FS, N, _notes(EVENTS), 0)
    twin = live.Strings(header, arrays, FS, wear=WORN)
    tw = twin.render((N - 1) * k, [(at * k, ev) for at, ev in EVENTS])
    for raw, t in ((rc, tw[0]), (rb, tw[1])):
        assert np.max(np.abs(t)) > 1e-3, "it sounds"
        assert _db(raw[1:] - t, t) < -120
    nominal = circuitsim.clav_render(_element(ref, None), FS, N, _notes(EVENTS), 0)
    assert _db(nominal[2] - rc, rc) > -40, "worn, it sounds different"


@pytest.mark.parametrize("pickups", [0.0, 2.0])
def test_the_most_worn_instrument_strikes_every_key(saved, pickups):
    """Every key struck at the top velocity, everything else at its most worn: nothing runs
    away. Pickup heights change the level legitimately (a string nearer its bar meets the
    map's steep part), so the bound is loose with them."""
    ref, header, _ = saved
    most = wear.Wear(
        seed=2, age=2.0, tuning=1.0, strings=1.0, tangents=1.0, yarn=1.0, pickups=pickups
    )
    notes = [kd["note"] for kd in header["keys"]]
    events = []
    gap = int(0.3 * FS)  # each key alone: a worn yarn's ring is gone before the next
    for i, n in enumerate(notes):
        events.append((50 + gap * i, ("on", n, 127)))
        events.append((50 + gap * i + int(0.1 * FS), ("off", n)))
    m = 50 + gap * len(notes)
    worn = circuitsim.clav_render(_element(ref, most), FS, m, _notes(events), 3)
    new = circuitsim.clav_render(_element(ref, None), FS, m, _notes(events), 3)
    bound = 2.0 if pickups == 0.0 else 8.0
    for w, n in zip(worn[2:4], new[2:4], strict=True):
        assert np.all(np.isfinite(w))
        assert np.max(np.abs(w)) < bound * np.max(np.abs(n)), "no contact ran away"

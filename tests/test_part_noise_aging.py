"""The aging transform and the excess-noise injection (docs/PART_NOISE_PLAN.md, the 5F1 spike)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from varimu.circuit import builder
from varimu.circuit import ir as irm
from varimu.circuit.spec import load_circuit
from varimu.part_noise import aging

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def champ():
    return builder.build(load_circuit(REPO / "config/circuits/fender_5f1.yaml"), noise=1).ir


def _el(ir, name):
    return next(e for e in ir.elements() if e.name == name)


def test_new_changes_only_the_electrolytics_esr(champ):
    ir, noisy = aging.apply(champ, aging.CHAMP_5F1, aging.CONDITIONS["new"], seed=1)
    assert _el(ir, "RPLA").r_ohm == _el(champ, "RPLA").r_ohm
    assert not any(e.name.startswith("RLK_") for e in ir.elements())
    assert _el(ir, "CB1").c_f == _el(champ, "CB1").c_f
    esr = _el(ir, "RESR_CB1").r_ohm
    assert esr == pytest.approx(0.1 / (2 * np.pi * 120 * 16e-6))
    assert {n.name for n in noisy} == set(aging.CHAMP_5F1.carbon + aging.CHAMP_5F1.pots)


def test_a_wreck_drifts_leaks_and_dries(champ):
    cond = aging.CONDITIONS["wreck"]
    ir, noisy = aging.apply(champ, aging.CHAMP_5F1, cond, seed=1)
    for name in aging.CHAMP_5F1.carbon:
        assert _el(ir, name).r_ohm != _el(champ, name).r_ohm
        # Its Johnson source follows the value: psd x R constant.
        new, old = _el(ir, f"IN_{name}"), _el(champ, f"IN_{name}")
        assert new.psd_a2_hz * _el(ir, name).r_ohm == pytest.approx(
            old.psd_a2_hz * _el(champ, name).r_ohm
        )
    for c in aging.CHAMP_5F1.coupling:
        leak = _el(ir, f"RLK_{c}")
        assert (leak.a, leak.b) == (_el(champ, c).a, _el(champ, c).b)
        assert leak.r_ohm == cond.coupling_leak_ohm
    cb1 = _el(ir, "CB1")
    assert cb1.c_f == pytest.approx(0.2 * 16e-6) and cb1.b == "CB1_esr"
    pla = next(n for n in noisy if n.name == "RPLA")
    assert pla.ni_db == pytest.approx(15.0)  # 0 dB at 100k, +15 for the wreck


def test_draws_are_per_unit_and_reproducible(champ):
    cond = aging.CONDITIONS["cap_job"]
    a, _ = aging.apply(champ, aging.CHAMP_5F1, cond, seed=1)
    b, _ = aging.apply(champ, aging.CHAMP_5F1, cond, seed=1)
    c, _ = aging.apply(champ, aging.CHAMP_5F1, cond, seed=2)
    assert _el(a, "RPLA").r_ohm == _el(b, "RPLA").r_ohm != _el(c, "RPLA").r_ohm


def test_sources_and_controls(champ):
    ir, noisy = aging.apply(champ, aging.CHAMP_5F1, aging.CONDITIONS["new"], seed=1)
    ir = aging.with_sources(ir, noisy)
    assert {c.name for c in ir.controls} >= {aging.control_name(n.name) for n in noisy}
    g = _el(ir, "GXN_RPLA")
    assert isinstance(g, irm.Vccs) and (g.pos, g.neg) == ("b3", "p1a")
    n = 4800
    v = {"v(b3)": np.full(n, 250.0), "v(p1a)": np.full(n, 150.0)}
    one = [x for x in noisy if x.name == "RPLA"]
    c1 = aging.excess_controls(v, one, 96000.0, 1)[aging.control_name("RPLA")]
    c10 = aging.excess_controls(v, one, 96000.0, 1, exaggerate=10.0)[aging.control_name("RPLA")]
    assert np.allclose(c10, 10 * c1)
    assert np.any(c1)
    still = {"v(b3)": np.full(n, 150.0), "v(p1a)": np.full(n, 150.0)}  # no current, no noise
    assert not np.any(aging.excess_controls(still, one, 96000.0, 1)[aging.control_name("RPLA")])

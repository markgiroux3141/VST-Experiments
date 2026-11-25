"""Barkhausen avalanches in a core (varimu.part_noise.iron, docs/PART_NOISE_PLAN.md)."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.devices.core import MU0, core_model
from varimu.part_noise import iron, rng_for

FS = 96000.0


@pytest.fixture(scope="module")
def core():
    return core_model("T", "mumetall", 0.1)


def test_landscape_jumps_add_up_to_the_travel():
    pos, sizes = iron.landscape(0.1, 0.2, 1e-5, rng_for(1, "l"))
    assert np.all(np.diff(pos) >= 0) and pos.min() >= 0.1 and pos.max() <= 0.2
    assert sizes.sum() == pytest.approx(0.1)
    assert sizes.max() <= 1.5e-5  # s_max, after the rescale to the travel (a factor ~1)


def test_stress_makes_jumps_fewer_and_bigger():
    few, big = iron.landscape(0.0, 0.01, 1e-4, rng_for(1, "a"))
    many, small = iron.landscape(0.0, 0.01, 1e-6, rng_for(1, "a"))
    assert few.size < many.size / 5
    assert big.max() > 10 * small.max()


def test_replay_irreversible_magnetization(core):
    """Mirr follows B up a monotonic sweep, and the rate is zero where B stands still."""
    b = np.concatenate([np.linspace(0.3, 0.5, 2000), np.full(500, 0.5)])
    r = iron.replay(core, b, FS)
    assert np.all(np.diff(r.m_irr[:2000]) >= -1e-12)
    assert np.all(r.theta[2001:] == 0.0)
    assert np.all(r.dh_db > 0)


def test_return_point_memory(core):
    """The landscape's deviation is a function of position: a repeated minor loop repeats it."""
    t = np.arange(int(0.2 * FS)) / FS
    b = 0.5 + 0.02 * np.sin(2 * np.pi * 100 * t)
    r = iron.replay(core, b, FS)
    dm = iron.avalanches(r, FS, 100.0, rng_for(2, "m"))
    period = int(FS / 100)
    late = dm[-4 * period :].reshape(4, period)  # after the filters have settled
    assert np.max(np.abs(late[3] - late[2])) < 0.05 * np.max(np.abs(late))
    other = iron.avalanches(r, FS, 100.0, rng_for(3, "m"))  # another core: another barcode
    assert not np.allclose(dm, other)


def test_injection_is_a_jump_at_fixed_field(core):
    dm = np.full(10, 1e-6)
    dh_db = np.full(10, 50.0)
    i = iron.injection_current(core, dm, dh_db)
    assert i[0] == pytest.approx(core.path_m * 50.0 * MU0 * 1e-6 * core.ms_a_per_m)

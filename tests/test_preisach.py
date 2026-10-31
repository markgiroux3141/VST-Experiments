"""The tape's particles (docs/TAPE_PLAN.md, TM1): varimu.devices.preisach and the Scotch 111
fit (varimu.devices.tape_fit, config/components/scotch111/)."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.devices import library, tape_fit
from varimu.devices.fit import load_csv
from varimu.devices.preisach import OE_A_PER_M, Preisach, PreisachParams

OE = OE_A_PER_M


@pytest.fixture(scope="module")
def coarse() -> Preisach:
    return Preisach(PreisachParams(330 * OE, 0.25, 100 * OE, 1500 * OE, n=40, n_table=1024))


def _histories(seed: int, cells: int, length: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 400 * OE, (cells, length)) * np.linspace(1.5, 0.1, length)


def test_the_corner_formula_is_every_hysteron_stepped(coarse):
    h = _histories(1, 40, 30)
    np.testing.assert_allclose(coarse.state_after(h, grid=True), coarse.brute_force(h), atol=1e-14)


def test_only_extrema_matter():
    """Rate independence: a dense history and its turning points leave the same state."""
    pre = Preisach(PreisachParams(330 * OE, 0.25, 100 * OE, 1500 * OE))
    rng = np.random.default_rng(2)
    for _ in range(5):
        x = np.cumsum(rng.normal(0, 50 * OE, 400))
        d = np.diff(x)
        keep = [0, *np.flatnonzero(d[:-1] * d[1:] < 0) + 1, len(x) - 1]
        assert pre.state_after(x[None])[0] == pre.state_after(x[keep][None])[0]


def test_the_continuous_tables_converge():
    h = _histories(3, 30, 40)
    a = Preisach(PreisachParams(330 * OE, 0.25, 100 * OE, 1500 * OE, n_table=1024)).state_after(h)
    b = Preisach(PreisachParams(330 * OE, 0.25, 100 * OE, 1500 * OE, n_table=2048)).state_after(h)
    assert np.abs(a - b).max() < 3e-5
    # ... towards the discrete grid's limit (its own quadrature error ~1/n).
    fine = Preisach(PreisachParams(330 * OE, 0.25, 100 * OE, 1500 * OE, n=512))
    assert np.abs(fine.state_after(h) - fine.state_after(h, grid=True)).max() < 0.03


def test_erased_is_zero_and_the_model_is_odd():
    """No even-order distortion of its own: M(-history) = -M(history), from erased, up to
    the tables' interpolation (a mirrored history reads other table points: ~1e-7 of Ms,
    -140 dB)."""
    pre = Preisach(PreisachParams(330 * OE, 0.25, 100 * OE, 1500 * OE))
    assert abs(pre.state_after(np.zeros((1, 1)))[0]) < 1e-12
    h = _histories(4, 50, 30)
    np.testing.assert_allclose(pre.state_after(-h), -pre.state_after(h), atol=3e-7)


def test_the_anhysteretic_curve_is_smooth():
    """The recording's transfer curve: odd, rising and without a discrete grid's staircase
    (its second differences stay small at 1 Oe steps)."""
    pre = Preisach(PreisachParams(330 * OE, 0.25, 100 * OE, 1500 * OE))
    h = np.arange(-40.0, 40.5, 1.0) * OE
    m = pre.anhysteretic_remanence(h, cycles=2048)
    assert np.all(np.diff(m) > 0)
    np.testing.assert_allclose(m, -m[::-1], atol=1e-6)
    slope = np.diff(m)
    assert np.abs(np.diff(slope)).max() < 0.02 * slope.max()


def test_scotch111_fits_bulletin_20_and_its_coercivity():
    tape = library.load_tape("SCOTCH111@1")
    pre = tape.ensemble()
    rows = load_csv("scotch_111_remanence.csv")
    phi = (
        tape_fit.symmetric_remanence(pre, rows[:, 0]) * tape_fit.MU0 * tape.ms_a_m * tape.coating_m
    )
    # Within the curve's reading error (0.01 lines per 1/4") at nearly every point, and
    # within 2 reading errors everywhere.
    err = np.abs(phi - rows[:, 1]) / tape_fit.SIGMA_PHI_WB_PER_M
    assert err.max() < 2.0 and np.sqrt(np.mean(err**2)) < 1.0
    # Eilers' 270 Oe within the bulletins' +-10%.
    hc = tape_fit.loop_coercivity(pre)
    assert abs(hc / (270 * OE) - 1.0) < 0.10
    # The saturated remanent flux: 0.636 lines per 1/4" (Eilers: 0.64).
    sat = tape_fit.saturation_remanence(pre) * tape_fit.MU0 * tape.ms_a_m * tape.coating_m
    assert sat == pytest.approx(0.636e-8 / 6.35e-3, rel=0.005)

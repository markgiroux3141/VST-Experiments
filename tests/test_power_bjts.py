"""The Rhodes 100 W power amp's transistors (varimu.devices.library.build_2n5784 ...): each
model sits inside its datasheet's limits at the sheet's test points (RCA Power Devices 1981,
data/datasheets/transistors/; the RCA29B / RCA30B from reseller limits only)."""

import pytest
from scipy.optimize import brentq

from varimu.devices.library import load_device


def _hfe_vbe(q, ic_a: float, vce_v: float) -> tuple[float, float]:
    """(hFE, VBE) at the terminals (NPN-signed magnitudes) for a collector current."""
    s = q.sign

    vce_i = vce_v - ic_a * (q.rc_ohm + q.re_ohm)  # the drops at the target current

    def internal(vbe_i):
        ic, ib = q.currents(s * vce_i, s * vbe_i)
        return s * ic, s * ib

    vbe_i = brentq(lambda v: internal(v)[0] - ic_a, 0.3, 0.92, xtol=1e-14)
    ic, ib = internal(vbe_i)
    return ic / ib, vbe_i + ib * q.rb_ohm + (ic + ib) * q.re_ohm


@pytest.mark.parametrize("name", ["2N5784@1", "2N5781@1"])
def test_to39_pair_inside_the_rca_limits(name):
    q = load_device(name)
    hfe_1a, vbe_1a = _hfe_vbe(q, 1.0, 2.0)
    assert 20 <= hfe_1a <= 100, hfe_1a
    assert vbe_1a <= 1.5, vbe_1a
    assert _hfe_vbe(q, 3.2, 2.0)[0] >= 4.0
    if name.startswith("2N5784"):
        # Fig. 9's typical curve at 25 C: ~61 at 10 mA, ~85 at 0.1 A, ~21 at 1 A.
        assert _hfe_vbe(q, 0.01, 2.0)[0] == pytest.approx(61, rel=0.25)
        assert _hfe_vbe(q, 0.1, 2.0)[0] == pytest.approx(85, rel=0.35)  # model 59: a flatter peak
        assert hfe_1a == pytest.approx(21, rel=0.3)


def test_2n6254_inside_the_rca_limits():
    q = load_device("2N6254@1")
    hfe5, vbe5 = _hfe_vbe(q, 5.0, 2.0)
    assert 20 <= hfe5 <= 70, hfe5
    assert vbe5 <= 1.5, vbe5
    assert _hfe_vbe(q, 15.0, 4.0)[0] >= 5.0
    assert 0.55 <= _hfe_vbe(q, 0.1, 4.0)[1] <= 0.8  # provisional: a power die at 100 mA


@pytest.mark.parametrize("name", ["RCA29B@1", "RCA30B@1"])
def test_drivers_inside_the_reseller_limits(name):
    q = load_device(name)
    assert 15 <= _hfe_vbe(q, 1.0, 4.0)[0] <= 150

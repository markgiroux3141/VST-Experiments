"""The uA726 component (docs/MINIMOOG_PLAN.md MM3's first prerequisite): one transistor of the
temperature-controlled pair, fitted to Fairchild's current gain curve at the Minimoog's 78.4 C."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.optimize import brentq

from varimu.devices import library
from varimu.devices.bjt import K_OVER_Q


def card(temp_c: float | None = library.UA726_TEMP_C):
    m = library.load_device("UA726@1")
    if temp_c is None:
        return m
    import dataclasses

    return dataclasses.replace(m, temp_k=temp_c + 273.15)


def vbe_at(m, ic: float, vce: float = 5.0) -> float:
    return brentq(lambda v: float(m.junction(v, v - vce)[0]) - ic, 0.0, 1.2, xtol=1e-14)


def test_gain_follows_the_sheet_at_the_die_temperature():
    """hfe within 10 % of the sheet's curve from 10 uA to 2 mA (VCE 5 V, at 78.4 C); at 10 uA and
    100 uA within 10 % of the bias currents' 200 and 400 (p. 7-34)."""
    m = card()
    ic, _, hfe = library.load_csv("fairchild_ua726_hfe.csv").T
    for i, h in zip(ic, hfe, strict=True):
        if i > library.UA726_FIT_MAX_A:
            continue
        v = vbe_at(m, i)
        out = m.junction(v, v - 5.0)
        assert out[0] / out[1] == pytest.approx(h, rel=0.10), i


def test_matched_pair_is_exponential_at_kt_over_q():
    """Two instances of the one card (the matched pair): an octave of collector current is
    (kT / q) ln 2 of Vbe at the die's temperature, 21.0 mV at 78.4 C, from 0.1 to 20 uA (the
    Minimoog's range), within 1 % (the fitted IKF's high-injection term already adds ~0.2 % at a
    few uA: a scale error the oscillator's Scale trim takes out); at 27 C it is 17.9 mV."""
    for temp_c in (library.UA726_TEMP_C, 26.85):
        m = card(temp_c)
        expect = (temp_c + 273.15) * K_OVER_Q * math.log(2.0)
        for i in np.geomspace(0.1e-6, 10e-6, 5):
            d = vbe_at(m, 2 * i) - vbe_at(m, i)
            assert d == pytest.approx(expect, rel=1e-2), (temp_c, i)
    assert library.UA726_TEMP_C == 78.4

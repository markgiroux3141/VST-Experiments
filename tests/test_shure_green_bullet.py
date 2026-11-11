"""The Shure 520D "Green Bullet" (docs/CHAINS_PLAN.md WP30): the controlled-magnetic element
R_520@1 against Shure's 1980 data sheet (data/datasheets/shure_520d_response.csv; 15.85 mV/Pa
high impedance through the case's 39k), the circuit file, and the chain into the 5E3.
The construction is unpublished, so the element is fitted (scripts/fit_520d.py); its misses are
asserted at their measured size."""

from __future__ import annotations

import csv

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, DATA_DIR
from varimu.devices import versions
from varimu.devices.library import component_data, load_moving_coil
from varimu.measure import ac
from varimu.mics.free_field import body_entry_factors

VERSION = "R_520@1"
ANGLES = [0.0, 90.0, 180.0]
_ENT: dict = {}


def _front(f, theta_deg):
    """The front entry's pressure per pascal of a plane wave from theta, on the case."""
    g = component_data(VERSION)["geometry"]
    f = np.atleast_1d(np.asarray(f, float))
    missing = [x for x in f if float(x) not in _ENT]
    if missing:
        fr, _ = body_entry_factors(
            np.array(missing), np.radians(ANGLES), g["body"], g["diaphragm"]["radius_m"]
        )
        for i, x in enumerate(missing):
            _ENT[float(x)] = fr[i]
    j = ANGLES.index(theta_deg)
    return np.array([_ENT[float(x)][j] for x in f])


def _ir(settings=None):
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "shure_green_bullet.yaml")
    return builder.build_ir(s, spec.resolve(s, settings or {}), "ja")


def _response(f, theta_deg=0.0):
    """Volts at the cord's end (open circuit but the case's 39k) per pascal from theta."""
    f = np.atleast_1d(np.asarray(f, float))
    return ac.transfer(_ir(), f, "out") * _front(f, theta_deg)


def _figure1():
    with open(DATA_DIR / "datasheets" / "shure_520d_response.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    f = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    return f, db - float(np.interp(np.log(1000.0), np.log(f), db))


def test_pinned_and_locked():
    assert versions.versions("R_520")
    c = load_moving_coil(VERSION)
    assert c.re_ohm == pytest.approx(700.0)  # provisional, not fitted
    assert 0.2 < c.le_h < 5.0


def test_sensitivity():
    """Shure: -56.0 dB re 1 V/ubar (15.85 mV/Pa) high impedance, open circuit, 1 kHz."""
    assert abs(_response([1000.0])[0]) == pytest.approx(15.85e-3, rel=0.03)


def test_on_axis_follows_figure_1():
    """Within 2.3 dB over the digitized trace (85 Hz-6.5 kHz), 0.9 dB rms; the bump and
    the fall that make the Green Bullet's voice: the 2.9 kHz peak over the 2.2 kHz dip, and
    the cutoff (6.5 kHz at least 8 dB under 1 kHz)."""
    f, db = _figure1()
    h = _response(np.concatenate([[1000.0], f]))
    on = 20 * np.log10(abs(h[1:]) / abs(h[0]))
    err = on - db
    assert np.max(abs(err)) < 2.5
    assert np.sqrt(np.mean(err**2)) < 0.9
    at = dict(zip(f, on, strict=True))
    near = lambda x: at[min(at, key=lambda k: abs(k - x))]  # noqa: E731
    assert near(2900.0) - near(2170.0) > 2.5
    assert near(6500.0) < -8.0


def test_winding_impedance():
    """The high winding's 1 kHz impedance (Thevenin, open over short) within 5% of 8.0 kOhm:
    the low tap's 160 ohm x the turns ratio squared (the sheet's -73.0 / -56.0 dB)."""
    f = np.array([1000.0])
    bare = {"r_case_ohm": 1e15, "cord_c_f": 1e-21}  # the winding alone: the case's parts away

    def v(load_ohm):
        return ac.transfer(_ir({**bare, "load_ohm": load_ohm}), f, "out")[0]

    z = abs(v(1e12) / (v(1e-2) / 1e-2))
    assert z == pytest.approx(8020.0, rel=0.05)


def test_omnidirectional_at_1k():
    """Shure: omnidirectional. On its 63 mm case the side is within 2.5 dB at 1 kHz (narrowing
    above: -9 dB at 4 kHz, the case's diffraction)."""
    h0 = abs(_response([1000.0], 0.0)[0])
    for th in (90.0, 180.0):
        assert abs(20 * np.log10(abs(_response([1000.0], th)[0]) / h0)) < 2.5


def test_chain_into_the_5e3_builds():
    """bullet_f5e3: the mic on the 5E3's bright input 1, its own cord (no chain cable), the
    output the speaker's pressure."""
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "bullet_f5e3.yaml")
    ir = builder.build(s, {}).ir
    names = {e.name for e in ir.elements()}
    assert {"CCORD_bullet", "R39K_bullet"} <= names
    assert "CCABLE" not in names and "RLOAD_bullet" not in names
    assert s.full_scale is not None

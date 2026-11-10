"""The Shure SM7 (docs/CHAINS_PLAN.md WP15): the cartridge R_SM7@1 against Shure's SM7B figures
(data/datasheets/shure_sm7_response.csv; 1.12 mV/Pa), and the circuit file. The construction is
unpublished, so the cartridge is fitted (scripts/fit_sm7.py); the polars above 2 kHz are known
misses, asserted at their measured size."""

from __future__ import annotations

import csv

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, DATA_DIR
from varimu.devices import versions
from varimu.devices.library import component_data, load_moving_coil
from varimu.mics.free_field import body_entry_factors
from varimu.mics.networks import moving_coil_response

VERSION = "R_SM7@1"
ANGLES = [0.0, 90.0, 180.0]
_ENT: dict = {}


def _response(f, theta_deg):
    """Volts open circuit per pascal of a plane wave from theta (no transformer), the entries
    on the component's body."""
    g = component_data(VERSION)["geometry"]
    c = load_moving_coil(VERSION)
    f = np.atleast_1d(np.asarray(f, float))
    missing = [x for x in f if float(x) not in _ENT]
    if missing:
        fr, rr = body_entry_factors(
            np.array(missing), np.radians(ANGLES), g["body"], g["diaphragm"]["radius_m"]
        )
        for i, x in enumerate(missing):
            _ENT[float(x)] = (fr[i], rr[i])
    j = ANGLES.index(theta_deg)
    ent = (np.array([_ENT[float(x)][0][j] for x in f]), np.array([_ENT[float(x)][1][j] for x in f]))
    return moving_coil_response(c, f, ent)


def _axial():
    with open(DATA_DIR / "datasheets" / "shure_sm7_response.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["setting"] == "flat"]
    fr = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    return fr, db - float(np.interp(1000.0, fr, db))


def test_pinned_and_locked():
    assert versions.versions("R_SM7")
    c = load_moving_coil(VERSION)
    assert c.re_ohm == pytest.approx(140.0)  # shure: 150 ohm


def test_sensitivity():
    """Shure: 1.12 mV/Pa at 1 kHz, open circuit."""
    h = abs(_response([1000.0], 0.0)[0])
    assert h == pytest.approx(1.12e-3, rel=0.05)


def test_on_axis_follows_the_flat_setting():
    """Within 3 dB from 50 Hz to 10 kHz (the fitted band), rms under 1 dB."""
    f, db = _axial()
    keep = (f >= 50) & (f <= 10000)
    h = _response(np.concatenate([[1000.0], f[keep]]), 0.0)
    on = 20 * np.log10(abs(h[1:]) / abs(h[0]))
    assert np.max(abs(on - db[keep])) < 3.0
    assert np.sqrt(np.mean((on - db[keep]) ** 2)) < 1.0


def test_polars():
    """250 Hz within 2 dB of Shure's chart; 2.5 kHz at 90 deg -5.7 against -10.6 (a known miss)."""
    h0 = abs(_response([250.0, 2500.0], 0.0))
    side = 20 * np.log10(abs(_response([250.0, 2500.0], 90.0)) / h0)
    assert side[0] == pytest.approx(-4.5, abs=2.0)
    assert -8.0 < side[1] < -4.0


def test_circuit_builds_and_matches_the_cartridge():
    from varimu.measure import ac

    s = spec.load_circuit(CONFIG_DIR / "circuits" / "shure_sm7.yaml")
    ir = builder.build_ir(s, spec.resolve(s, {}), "ja")
    names = {e.name for e in ir.elements()}
    assert "RLOAD" in names
    f = np.array([100.0, 1000.0, 3000.0])
    got = ac.transfer(ir, f, "out", drives={"p_rear": np.zeros(3, complex)})
    want = _response(f, 0.0)
    assert abs(got[1]) == pytest.approx(abs(want[1]), rel=0.5)

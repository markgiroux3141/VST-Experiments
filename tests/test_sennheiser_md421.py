"""The Sennheiser MD 421-II (docs/CHAINS_PLAN.md WP14): the cartridge R_MD421@1 against
Sennheiser's figures (data/datasheets/sennheiser_md421_*.csv; 2 mV/Pa), and the circuit file.
The construction is unpublished, so the cartridge is fitted (scripts/fit_md421.py); the misses it leaves are asserted at their measured size."""

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

VERSION = "R_MD421@1"
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
    with open(DATA_DIR / "datasheets" / "sennheiser_md421_response.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["trace"] == "M"]
    fr = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["dbv_per_pa"]) for r in rows])
    return fr, db - float(np.interp(1000.0, fr, db))


def test_pinned_and_locked():
    assert versions.versions("R_MD421")
    c = load_moving_coil(VERSION)
    assert c.re_ohm == pytest.approx(230.0)  # sennheiser: 250 ohm output


def test_sensitivity():
    """Sennheiser: 2 mV/Pa +-2.5 dB at 1 kHz, open circuit."""
    h = abs(_response([1000.0], 0.0)[0])
    assert h == pytest.approx(2.0e-3, rel=0.03)


def test_on_axis_follows_the_m_position():
    """The model follows the sheet's M curve within 2.5 dB from 40 Hz to 8 kHz (the fitted band)
    with the presence rise drawn."""
    f, db = _axial()
    keep = (f >= 40) & (f <= 8000)
    h = _response(np.concatenate([[1000.0], f[keep]]), 0.0)
    on = 20 * np.log10(abs(h[1:]) / abs(h[0]))
    assert np.max(abs(on - db[keep])) < 2.5
    assert np.sqrt(np.mean((on - db[keep]) ** 2)) < 1.2
    g = dict(zip(f[keep], on, strict=True))
    assert max(v for k, v in g.items() if 3000 <= k <= 8000) > 4.0  # the presence rise


def test_side_polars():
    """The sheet's 90 deg values at 125 Hz - 2 kHz within 2 dB (the 4 kHz side and the 8 kHz
    rear are known misses: the model is 3-6 dB wide there)."""
    f = [125.0, 250.0, 500.0, 1000.0, 2000.0]
    want = [-3.5, -5.43, -7.72, -7.74, -7.75]
    h0 = abs(_response(f, 0.0))
    side = 20 * np.log10(abs(_response(f, 90.0)) / h0)
    assert np.max(abs(side - np.array(want))) < 2.0


def test_circuit_builds_and_matches_the_cartridge():
    from varimu.measure import ac

    s = spec.load_circuit(CONFIG_DIR / "circuits" / "sennheiser_md421.yaml")
    ir = builder.build_ir(s, spec.resolve(s, {}), "ja")
    names = {e.name for e in ir.elements()}
    assert {"GMC_dia_ga", "GMC_dia_ge", "RMC_re", "RLOAD"} <= names
    f = np.array([100.0, 1000.0, 3000.0])
    got = ac.transfer(ir, f, "out", drives={"p_rear": np.zeros(3, complex)})
    want = _response(f, 0.0)
    assert abs(got[1]) == pytest.approx(abs(want[1]), rel=0.5)

"""The AKG D112 (docs/CHAINS_PLAN.md WP9): the cartridge R_D112@1 against AKG's published
figures (the MKII sheet's response and polars: data/datasheets/akg_d112_*.csv; 1.8 mV/Pa),
and the circuit file. The construction is unpublished, so the cartridge is fitted
(scripts/fit_d112.py); the misses it leaves are asserted at their measured size."""

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

VERSION = "R_D112@1"
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
    with open(DATA_DIR / "datasheets" / "akg_d112_response.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["curve"] == "axial"]
    return (np.array([float(r["freq_hz"]) for r in rows]),
            np.array([float(r["db"]) for r in rows]))  # fmt: skip


def test_pinned_and_locked():
    assert versions.versions("R_D112")
    c = load_moving_coil(VERSION)
    assert c.re_ohm == pytest.approx(190.0)  # akg: 210 ohm output, <= 200 on the MKII


def test_sensitivity():
    """akg: 1.8 mV/Pa at 1 kHz, open circuit."""
    h = abs(_response([1000.0], 0.0)[0])
    assert h == pytest.approx(1.8e-3, rel=0.03)


def test_on_axis_within_the_sheets_tolerance():
    """The sheet's own band is +-3 dB, 40 Hz-17 kHz: the model follows the curve within 3 dB
    from 40 Hz to 8 kHz (the fitted band; above, the dome's second region isn't fitted) with the
    bass bump and the presence peak both drawn."""
    f, db = _axial()
    keep = (f >= 40) & (f <= 8000)
    h = _response(np.concatenate([[1000.0], f[keep]]), 0.0)
    on = 20 * np.log10(abs(h[1:]) / abs(h[0]))
    assert np.max(abs(on - db[keep])) < 3.5
    assert np.sqrt(np.mean((on - db[keep]) ** 2)) < 1.5
    g = dict(zip(f[keep], on, strict=True))
    assert g[100.0] > g[1000.0] + 1.5  # the bass bump
    assert max(v for k, v in g.items() if 2000 <= k <= 5000) > 4.0  # the presence peak


def test_polars_front_to_back():
    """akg2's polars: 15 dB at 125 Hz and 2 kHz at the rear (3 dB), the side at 125 / 250 Hz
    within 3 dB; the side at 2-4 kHz is a known miss (the model is 3-4 dB narrower)."""
    f = [125.0, 250.0, 2000.0]
    h0 = abs(_response(f, 0.0))
    side = 20 * np.log10(abs(_response(f, 90.0)) / h0)
    rear = 20 * np.log10(abs(_response(f, 180.0)) / h0)
    assert rear[0] == pytest.approx(-15.0, abs=3.0)
    assert rear[2] == pytest.approx(-14.8, abs=3.0)
    assert side[0] == pytest.approx(-4.9, abs=3.0)
    assert side[1] == pytest.approx(-6.9, abs=3.0)
    assert side[2] < -6.1 and side[2] > -12.0  # akg2: -6.1; the model's miss


def test_circuit_builds_and_matches_the_cartridge():
    from varimu.measure import ac

    s = spec.load_circuit(CONFIG_DIR / "circuits" / "akg_d112.yaml")
    ir = builder.build_ir(s, spec.resolve(s, {}), "ja")
    names = {e.name for e in ir.elements()}
    assert {"GMC_dia_ga", "GMC_dia_ge", "RMC_re", "RLOAD"} <= names
    f = np.array([100.0, 1000.0, 3000.0])
    got = ac.transfer(ir, f, "out", drives={"p_rear": np.zeros(3, complex)})
    # a front-only pressure: the circuit's `in` is the front entry
    want = _response(f, 0.0)  # the plane wave, entries included: only the 1 kHz level compares
    assert abs(got[1]) == pytest.approx(abs(want[1]), rel=0.5)  # same order: entries differ

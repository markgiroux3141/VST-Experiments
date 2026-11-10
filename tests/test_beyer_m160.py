"""The beyerdynamic M 160 (docs/CHAINS_PLAN.md WP17): config/circuits/beyer_m160.yaml, the
double ribbon RIBBON_M160@1 (fitted by scripts/fit_m160.py) into M160_OT@1.

The whole microphone in the horizontal plane (the ribbons upright) through the linear-core AC
analysis: beyer's 1.0 mV/Pa open circuit and ~200 ohm, the hypercardioid (> 25 dB at 110 deg at
1 kHz; 90 / 180 deg near the ideal's -12 / -6 dB), the 1 m curve within its fitted error.
"""

from __future__ import annotations

import csv

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.config import DATA_DIR
from varimu.devices.library import component_data
from varimu.measure import ac
from varimu.mics import bor
from varimu.preflight import check_circuit

_ENT: dict = {}


def _spec():
    return spec.load_circuit(spec.circuit_path("beyer_m160"))


def _response(f, theta_deg: float = 0.0, **over) -> np.ndarray:
    f = np.atleast_1d(np.asarray(f, float))
    s = _spec()
    q = spec.resolve(s, over)
    g = component_data(str(q["ribbon_model"]))["geometry"]
    key = (tuple(f), theta_deg)
    if key not in _ENT:
        op = bor.operator(bor.body_mesh(g["body"], bor.entry_size(g)))
        fr, rr = bor.entry_factors(op, f, np.radians([theta_deg]))
        _ENT[key] = (fr[:, 0], rr[:, 0])
    front, rear = _ENT[key]
    ir = builder.build_ir(s, q, "linear")
    return front * ac.transfer(ir, f, "out", drives={"p_rear": rear / front})


def test_builds_and_passes_preflight():
    s = _spec()
    assert check_circuit(s) == []
    builder.build_ir(s, spec.resolve(s, {}), "linear")


def test_sensitivity_and_impedance():
    on = abs(_response([1000.0])[0])
    assert 20 * np.log10(on / 1.0e-3) == pytest.approx(0.0, abs=0.5)
    loaded = abs(_response([1000.0], load_ohm=200.0)[0])
    assert 20 * np.log10(on / loaded) == pytest.approx(6.0, abs=1.5)  # ~200 ohm


def test_hypercardioid():
    f = np.array([1000.0])
    on = abs(_response(f, 0.0)[0])
    rel = {a: 20 * np.log10(abs(_response(f, a)[0]) / on) for a in (90.0, 110.0, 180.0)}
    assert rel[110.0] < -25.0
    assert rel[90.0] == pytest.approx(-12.0, abs=1.5)
    assert rel[180.0] == pytest.approx(-6.0, abs=1.5)


def test_axial_response_against_the_sheet():
    """re 1 kHz within 2.5 dB (the sheet's tolerance) from 40 Hz to 18 kHz."""
    with open(DATA_DIR / "datasheets" / "beyer_m160_response.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    f = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    h = _response(np.r_[f, 1000.0])
    e = 20 * np.log10(np.abs(h[:-1] / h[-1])) - db
    assert np.max(np.abs(e)) < 2.5
    assert np.sqrt(np.mean(e**2)) < 1.6

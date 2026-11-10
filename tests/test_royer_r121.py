"""The Royer R-121 (docs/CHAINS_PLAN.md WP16): config/circuits/royer_r121.yaml, the offset
ribbon RIBBON_R121@1 (fitted by scripts/fit_r121.py) into R121_OT@1.

The whole microphone in the horizontal plane (the ribbon upright) through the linear-core AC
analysis: Royer's -49 dB re 1 V/Pa and ~300 ohm, a figure-8 (the side null, the rear lobe in
antiphase), the chart within the manual's +-3 dB.
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
    return spec.load_circuit(spec.circuit_path("royer_r121"))


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
    assert 20 * np.log10(on) == pytest.approx(-49.0, abs=0.5)
    loaded = abs(_response([1000.0], load_ohm=300.0)[0])
    assert 20 * np.log10(on / loaded) == pytest.approx(6.0, abs=1.5)  # ~300 ohm


def test_figure_of_eight():
    f = np.array([500.0])
    on = _response(f, 0.0)[0]
    assert 20 * np.log10(abs(_response(f, 90.0)[0]) / abs(on)) < -30.0
    back = _response(f, 180.0)[0]
    assert abs(back / on) == pytest.approx(1.0, abs=0.15)
    assert np.real(back / on) < 0


def test_axial_response_against_the_chart():
    """re 1 kHz within the manual's +-3 dB from 30 Hz to 16 kHz."""
    with open(DATA_DIR / "datasheets" / "royer_r121_response.csv", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if 30 <= float(r["freq_hz"]) <= 16000]
    f = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    h = _response(np.r_[f, 1000.0])
    e = 20 * np.log10(np.abs(h[:-1] / h[-1])) - db
    assert np.max(np.abs(e)) < 3.0
    assert np.sqrt(np.mean(e**2)) < 1.6

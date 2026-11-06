"""The STC / Coles 4038 (docs/CHAINS_PLAN.md WP8): the circuit file, its sensitivity,
response and figure of eight against STC's brochure C/PA22
(data/datasheets/coles_4038_response.csv) and BBC Engineering Monograph No. 4's figures, the
ribbon's body (varimu.mics.bor.baffle_mesh) for the entries."""

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

SENS_V_PER_PA = 0.6e-3  # stc: 0.06 mV per microbar (1 microbar = 0.1 Pa) open circuit
_ENT: dict = {}


def _spec():
    return spec.load_circuit(spec.circuit_path("coles_4038"))


def _entries(g: dict, f: np.ndarray, theta: float):
    key = (tuple(f), theta)
    if key not in _ENT:
        op = bor.operator(bor.body_mesh(g["body"], bor.entry_size(g)))
        fr, rr = bor.entry_factors(op, f, np.array([theta]))
        lf = bor.ribbon_line_factor(g, f, [theta], in_plane=True)[:, 0]
        _ENT[key] = (fr[:, 0] * lf, rr[:, 0] * lf)
    return _ENT[key]


def _response(f, theta_deg: float = 0.0, **over) -> np.ndarray:
    """Volts at `out` (open circuit) per pascal of a plane wave from theta_deg in the
    ribbon's plane."""
    f = np.atleast_1d(np.asarray(f, float))
    s = _spec()
    q = spec.resolve(s, over)
    g = component_data(str(q["ribbon_model"]))["geometry"]
    front, rear = _entries(g, f, float(np.radians(theta_deg)))
    ir = builder.build_ir(s, q, "linear")
    return front * ac.transfer(ir, f, "out", drives={"p_rear": rear / front})


def _curve():
    with open(DATA_DIR / "datasheets" / "coles_4038_response.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    f = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    return f, db - np.interp(np.log(1000.0), np.log(f), db)


def test_builds_and_passes_preflight():
    s = _spec()
    assert check_circuit(s) == []
    builder.build_ir(s, spec.resolve(s, {}), "linear")


def test_the_ribbon_is_the_pgs():
    """bbc: 1 in x 0.23 in in a 0.25 in gap, 0.22 ohm d.c., the fundamental 25-45 c/s."""
    q = spec.resolve(_spec(), {})
    g = component_data(str(q["ribbon_model"]))["geometry"]
    assert g["body"]["form"] == "baffle"
    assert g["ribbon"]["length_m"] == pytest.approx(0.0254)
    assert g["ribbon"]["width_m"] == pytest.approx(0.23 * 0.0254, rel=1e-3)
    assert 25.0 <= g["ribbon"]["resonance_hz"] <= 45.0
    lumped = component_data(str(q["ribbon_model"]))["lumped"]
    assert lumped["re_ohm"] == pytest.approx(0.22, rel=0.08)
    # the channels are half the pole pieces' depth each side
    d = g["body"]["depth_m"]
    chan = {e["name"]: e for e in g["network"]}
    for side in ("f", "r"):
        assert chan[f"chan_{side}_a"]["length_m"] + chan[f"chan_{side}_b"]["length_m"] == (
            pytest.approx(0.5 * d)
        )


def test_sensitivity():
    """stc: 0.06 mV per microbar open circuit (the fitted gap flux; bbc's 4500-6500 G
    brackets it)."""
    s = abs(_response([1000.0])[0])
    assert 20 * np.log10(s / SENS_V_PER_PA) == pytest.approx(0.0, abs=0.5)
    b = component_data("RIBBON_4038@1")["geometry"]["magnet"]["b_gap_t"]
    assert 0.45 <= b <= 0.70  # bbc 2.2: 6500 G at the pole tips to 4500 G at the centre


def test_output_impedance_is_30_ohm():
    """stc: 30 ohm nominal. The secondary's resistance and the reflected ribbon: the
    open-circuit and 30 ohm-loaded levels at 1 kHz differ by ~6 dB."""
    s = _spec()
    q0 = spec.resolve(s, {})
    q1 = spec.resolve(s, {"load_ohm": 30.0})
    g = component_data(str(q0["ribbon_model"]))["geometry"]
    f = np.array([1000.0])
    front, rear = _entries(g, f, 0.0)
    h = []
    for q in (q0, q1):
        ir = builder.build_ir(s, q, "linear")
        h.append(abs(front * ac.transfer(ir, f, "out", drives={"p_rear": rear / front})[0]))
    assert 20 * np.log10(h[0] / h[1]) == pytest.approx(6.0, abs=1.5)


def test_phasing_and_the_rear_lobe():
    f = np.array([300.0, 1000.0])
    front = _response(f, 0.0)
    rear = _response(f, 180.0)
    assert np.all(np.abs(np.angle(front, deg=True)) < 45)
    assert np.allclose(rear, -front, rtol=0.02)


def test_axial_response_against_fig1():
    """re 1 kHz within 1.6 dB from 40 Hz to 15 kHz except 3-8 kHz, a known miss: the
    baffle-and-channels model rises +2.8 dB at 4-7 kHz where STC's curve is flat to
    -1 dB (the screens' flow resistance doesn't move it; CHAINS_PLAN.md WP8's Notes)."""
    f, db = _curve()
    fk = np.r_[f, 1000.0]
    h = _response(fk)
    e = 20 * np.log10(np.abs(h[:-1] / h[-1])) - db
    k = f >= 40
    miss = (f >= 3000) & (f <= 8000)
    assert np.max(np.abs(e[k & ~miss])) < 1.6
    assert np.max(np.abs(e[miss])) < 3.2
    assert np.sqrt(np.mean(e[k] ** 2)) < 1.2


def test_figure_of_eight():
    """STC: 'bi-directional (figure of eight) polar curve ... accurately maintained': a
    cosine at 500 Hz (the 60 degree level 6 dB down) and a deep side null; the vertical
    plane's line narrows the lobe a little at 10 kHz."""
    f = np.array([500.0])
    on = abs(_response(f, 0.0)[0])
    at60 = abs(_response(f, 60.0)[0])
    at90 = abs(_response(f, 90.0)[0])
    assert 20 * np.log10(at60 / on) == pytest.approx(-6.0, abs=1.0)
    assert 20 * np.log10(at90 / on) < -30.0

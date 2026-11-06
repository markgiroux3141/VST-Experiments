"""The RCA 44-BX (docs/CHAINS_PLAN.md WP6): the circuit file at every strap and jumper, its
sensitivity, response and pattern against RCA's instruction book (IB-24267-5:
data/datasheets/rca_44bx_response.csv, rca_44bx_polar.csv), the ribbon's body
(varimu.mics.bor.baffle_mesh) for the entries."""

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

SENS_V_PER_PA = 1.78e-3  # ib: -55 dBm at 10 dyn/cm^2 into 250 ohm (RTMA: matched power)
_ENT: dict = {}


def _spec():
    return spec.load_circuit(spec.circuit_path("rca_44bx"))


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


def _curve(name: str):
    with open(DATA_DIR / "datasheets" / "rca_44bx_response.csv", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["curve"] == name]
    f = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    return f, db - np.interp(np.log(1000.0), np.log(f), db)


def test_builds_at_every_setting_and_passes_preflight():
    s = _spec()
    assert check_circuit(s) == []
    for imp in (0, 1, 2):
        for resp in (0, 1, 2):
            builder.build_ir(s, spec.resolve(s, {"impedance": imp, "response": resp}), "linear")


def test_the_ribbon_has_its_body():
    q = spec.resolve(_spec(), {})
    g = component_data(str(q["ribbon_model"]))["geometry"]
    assert g["body"]["form"] == "baffle"
    # the channels are half the pole pieces' depth each side, their volume the slot's
    d = g["body"]["depth_m"]
    chan = {e["name"]: e for e in g["network"]}
    for side in ("f", "r"):
        assert chan[f"chan_{side}_a"]["length_m"] + chan[f"chan_{side}_b"]["length_m"] == (
            pytest.approx(0.5 * d)
        )
        w, length = chan[f"chan_{side}_a"]["width_m"], chan[f"chan_{side}_a"]["breadth_m"]
        assert chan[f"cav_{side}"]["volume_m3"] == pytest.approx(w * length * 0.5 * d, rel=1e-5)


def test_sensitivity_at_250_ohm():
    """ib: -55 dBm at 10 dyn/cm^2 (1 Pa) into a matched 250 ohm, 1.78 mV/Pa open circuit
    (fitted: the gap's flux density)."""
    s = abs(_response([1000.0])[0])
    assert 20 * np.log10(s / SENS_V_PER_PA) == pytest.approx(0.0, abs=0.5)


def test_straps_step_down_by_the_turns():
    """150 and 30 ohm: the tap's share of the turns (B-C 209, A-B 101 of 310), near the
    labels' square roots (ib's nominal classes)."""
    h = [abs(_response([1000.0], impedance=k)[0]) for k in (0, 1, 2)]
    assert 20 * np.log10(h[1] / h[0]) == pytest.approx(20 * np.log10(209 / 310), abs=0.1)
    assert 20 * np.log10(h[2] / h[0]) == pytest.approx(20 * np.log10(101 / 310), abs=0.1)
    assert 20 * np.log10(h[1] / h[0]) == pytest.approx(10 * np.log10(150 / 250), abs=1.5)
    assert 20 * np.log10(h[2] / h[0]) == pytest.approx(10 * np.log10(30 / 250), abs=1.5)


def test_phasing_and_the_rear_lobe():
    """The red lead positive for positive pressure on the front (ib, 'Phasing'); from the
    rear the same level, inverted ('Rotating a velocity microphone 180 degrees reverses the
    phase')."""
    f = np.array([300.0, 1000.0])
    front = _response(f, 0.0)
    rear = _response(f, 180.0)
    assert np.all(np.abs(np.angle(front, deg=True)) < 45)
    assert np.allclose(rear, -front, rtol=0.02)


def _against(name: str, pos: int):
    f, db = _curve(name)
    fk = np.r_[f, 1000.0]
    h = _response(fk, response=pos)
    return f, 20 * np.log10(np.abs(h[:-1] / h[-1])) - db


def test_m_on_axis_against_fig4():
    """M re 1 kHz within the SM57's bar (+-2 dB) from 50 Hz to 15 kHz except 2-4.5 kHz,
    a known miss: RCA's -2.3 dB dip at ~2.7 kHz isn't in the baffle-and-channels model (it
    peaks +1.5 near 4 kHz; measured max 3.1 dB at 3 kHz: CHAINS_PLAN.md WP6's Notes)."""
    f, e = _against("M", 0)
    miss = (f > 2000) & (f < 4500)
    assert np.max(np.abs(e[~miss])) < 2.0
    assert np.max(np.abs(e[miss])) < 3.5
    assert np.sqrt(np.mean(e**2)) < 1.3


@pytest.mark.parametrize("name, pos", [("V1", 1), ("V2", 2)])
def test_voice_positions_against_fig4(name, pos):
    """The reactor (fitted: its inductance to V2, its resistance to V1) across B-C (V1) or
    A-C (V2): RCA's low cut within 1.2 dB from 50 Hz to 1 kHz."""
    f, e = _against(name, pos)
    k = f <= 1000
    assert np.max(np.abs(e[k])) < 1.2


def test_vertical_pattern_against_fig3():
    """ib Fig. 3 (the vertical plane: the slot's length counts) at 100-1000 cps and 3000
    within 2.5 dB to 60 degrees. At 6 and 10 kHz the uniform line's sinc narrows the lobe
    and nulls 10 kHz at ~33 degrees, where RCA's lobe has none: a known miss, reported
    (CHAINS_PLAN.md WP6's Notes; a room's table uses the line's azimuthal mean, far
    milder)."""
    with open(DATA_DIR / "datasheets" / "rca_44bx_polar.csv", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["quality"] in ("read", "merged")]
    for fz in (500.0, 3000.0):
        pts = [(float(r["angle_deg"]), float(r["db"])) for r in rows
               if float(r["freq_hz"]) == fz and float(r["angle_deg"]) <= 60]  # fmt: skip
        h0 = abs(_response([fz])[0])
        for ang, db in pts[1:]:
            got = 20 * np.log10(abs(_response([fz], ang)[0]) / h0)
            assert got == pytest.approx(db, abs=2.5), (fz, ang)

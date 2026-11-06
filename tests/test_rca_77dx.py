"""The RCA 77-DX (docs/CHAINS_PLAN.md WP7): the circuit file at every pattern, strap and
voice position, the shutter's stops in the builder, the sensitivities, the on-axis responses
and the patterns against RCA's IB-24884-2 (data/datasheets/rca_77dx_response.csv,
rca_77dx_polar.csv), the reactor's voice positions. The fit and its misses:
scripts/fit_77dx.py, reports/mics/rca77dx_fit.json, CHAINS_PLAN.md WP7's Notes."""

from __future__ import annotations

import copy
import csv

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.config import DATA_DIR
from varimu.devices.library import component_data
from varimu.measure import ac
from varimu.mics import bor
from varimu.preflight import check_circuit

STOPS = ("N", "L3", "U", "L2", "L1", "B")
SENS = {"B": 3.16e-3, "U": 2.24e-3, "N": 1.58e-3}  # ib2: -50 / -53 / -56 dBm, sqrt(4 R P)
_ENT: dict = {}


def _spec():
    return spec.load_circuit(spec.circuit_path("rca_77dx"))


def _entries(g: dict, f: np.ndarray, theta_deg: float):
    key = (tuple(f), theta_deg)
    if key not in _ENT:
        op = bor.operator(bor.body_mesh(g["body"], bor.entry_size(g)))
        fr, rr = bor.entry_factors(op, f, np.radians([theta_deg]))
        _ENT[key] = (fr[:, 0], rr[:, 0])  # the horizontal plane: the ribbon upright
    return _ENT[key]


def _response(f, theta_deg: float = 0.0, **over) -> np.ndarray:
    """Volts at `out` (open circuit) per pascal of a plane wave from theta_deg."""
    f = np.atleast_1d(np.asarray(f, float))
    s = _spec()
    q = spec.resolve(s, over)
    g = component_data(str(q["ribbon_model"]))["geometry"]
    front, rear = _entries(g, f, float(theta_deg))
    ir = builder.build_ir(s, q, "linear")
    return front * ac.transfer(ir, f, "out", drives={"p_rear": rear / front})


def _curve(pattern: str, curve: str):
    with open(DATA_DIR / "datasheets" / "rca_77dx_response.csv", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["pattern"] == pattern and r["curve"] == curve]
    f = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    return f, db - np.interp(np.log(1000.0), np.log(f), db)


def _against(pattern: str, curve: str = "M", pos: int = 0):
    f, db = _curve(pattern, curve)
    fk = np.r_[f, 1000.0]
    h = _response(fk, pattern=STOPS.index(pattern), response=pos)
    return f, 20 * np.log10(np.abs(h[:-1] / h[-1])) - db


def test_builds_at_every_setting_and_passes_preflight():
    s = _spec()
    assert check_circuit(s) == []
    for pat in range(6):
        for imp in (0, 1, 2):
            for resp in (0, 1, 2):
                over = {"pattern": pat, "impedance": imp, "response": resp}
                builder.build_ir(s, spec.resolve(s, over), "linear")


def test_the_shutter_is_the_motors_stop():
    """N has no slot (the rear entry holds only the numerical hold); every other stop one
    opening; the builder refuses a motor with stops and no `stop`, a stop out of range and a
    stop on a motor without stops."""
    s = _spec()
    names = {}
    for k in range(6):
        ir = builder.build_ir(s, spec.resolve(s, {"pattern": k}), "linear")
        names[k] = {e.name for sec in ir.sections for e in sec.elements}
    assert not any("_slot_s" in n for n in names[0])
    for k in range(1, 6):
        assert any(f"_slot_s{k}" in n for n in names[k])
        assert not any(f"_slot_s{j}" in n for j in range(1, 6) if j != k for n in names[k])
    bare = copy.deepcopy(s)
    del next(x for x in bare.sections if x["title"] == "ribbon")["parts"]["RB"]["stop"]
    with pytest.raises(Exception, match="needs one picked"):
        builder.build_ir(bare, spec.resolve(bare, {}), "linear")
    with pytest.raises(Exception, match="not a stop"):
        bad = copy.deepcopy(s)
        next(x for x in bad.sections if x["title"] == "ribbon")["parts"]["RB"]["stop"] = 1.5
        builder.build_ir(bad, spec.resolve(bad, {}), "linear")
    s44 = spec.load_circuit(spec.circuit_path("rca_44bx"))
    sec = next(x for x in s44.sections if x["title"] == "ribbon")
    sec["parts"]["RB"]["stop"] = 0
    with pytest.raises(Exception, match="has no stops"):
        builder.build_ir(s44, spec.resolve(s44, {}), "linear")


@pytest.mark.parametrize("pattern, tol_db", [("B", 0.2), ("N", 0.2), ("U", 1.5)])
def test_sensitivity_at_250_ohm(pattern, tol_db):
    """ib2: B -50, U -53, N -56 dBm at 10 dyn/cm^2 into a matched 250 ohm (B and N fitted:
    the gap's flux, the labyrinth's radius; U a check, measured -0.9 dB)."""
    h = abs(_response([1000.0], pattern=STOPS.index(pattern))[0])
    assert 20 * np.log10(h / SENS[pattern]) == pytest.approx(0.0, abs=tol_db)


def test_straps_step_down_by_the_turns():
    """150 and 30 ohm: the tap's share of the turns (B-C 222, A-B 107 of 329)."""
    h = [abs(_response([1000.0], impedance=k)[0]) for k in (0, 1, 2)]
    assert 20 * np.log10(h[1] / h[0]) == pytest.approx(20 * np.log10(222 / 329), abs=0.1)
    assert 20 * np.log10(h[2] / h[0]) == pytest.approx(20 * np.log10(107 / 329), abs=0.1)


def test_phasing_and_the_figure_eight():
    """The red lead positive for positive pressure on the front (ib); at B the rear the
    same level, inverted, within ib2 Fig. 4's -1.5 dB."""
    f = np.array([300.0, 1000.0])
    front = _response(f, 0.0, pattern=5)
    rear = _response(f, 180.0, pattern=5)
    assert np.all(np.abs(np.angle(front, deg=True)) < 45)
    assert np.all(np.abs(np.angle(rear / front, deg=True)) > 150)
    assert np.all(np.abs(20 * np.log10(np.abs(rear / front)) + 1.5) < 1.0)


@pytest.mark.parametrize(
    "pattern, band, max_db, rms_db",
    [
        # N: the pressure ribbon on the labyrinth, its hump the connector and the head
        ("N", (50, 15000), 2.3, 1.0),
        ("U", (50, 15000), 4.0, 2.0),
        # B: 4-5 kHz +3 dB where RCA dips -2.7 (the equivalent disc's path; WP7's Notes)
        ("B", (50, 15000), 6.5, 2.4),
    ],
)
def test_m_on_axis_against_fig5(pattern, band, max_db, rms_db):
    f, e = _against(pattern)
    k = (f >= band[0]) & (f <= band[1])
    assert np.max(np.abs(e[k])) < max_db
    assert np.sqrt(np.mean(e[k] ** 2)) < rms_db


def _polar_rows():
    with open(DATA_DIR / "datasheets" / "rca_77dx_polar.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.parametrize(
    "pattern, tol_db",
    [("U", 0.5), ("L2", 0.5), ("B", 0.5), ("L3", 1.6), ("L1", 4.0)],
)
def test_patterns_at_400_to_1000_cps(pattern, tol_db):
    """Each stop's opening is fitted to its 400-1000 cps rows of ib2 Fig. 4: U, L-2, B on
    them, L-3 within 1.6 dB, L-1's rear lobe 3.5 dB short (its opening at the slot's whole
    length: WP7's Notes). Bound rows (inside -15 dB) only below their ring."""
    rows = [r for r in _polar_rows() if r["pattern"] == pattern and float(r["freq_hz"]) <= 1000]
    assert rows
    for r in rows:
        fz, ang = float(r["freq_hz"]), float(r["angle_deg"])
        h0 = abs(_response([fz], 0.0, pattern=STOPS.index(pattern))[0])
        got = 20 * np.log10(abs(_response([fz], ang, pattern=STOPS.index(pattern))[0]) / h0)
        if r["quality"] == "bound":
            assert got < float(r["db"]) + 0.5, (pattern, fz, ang)
        else:
            assert got == pytest.approx(float(r["db"]), abs=tol_db), (pattern, fz, ang)


def test_pattern_order_follows_the_shutter():
    """From closed to wide open the 90-degree level at 630 Hz falls (N omni, then the
    directional stops, B's null), and L-3 to B the rear lobe grows from U's null."""
    side = []
    for k in range(6):
        h0 = abs(_response([630.0], 0.0, pattern=k)[0])
        side.append(20 * np.log10(abs(_response([630.0], 90.0, pattern=k)[0]) / h0))
    assert side[0] > -1.0 and side[5] < -15.0
    assert side[0] > side[1] > side[3] > side[4] > side[5]


@pytest.mark.parametrize("curve, pos", [("V1", 1), ("V2", 2)])
def test_voice_positions_against_fig5(curve, pos):
    """The reactor (its inductance fitted at mic level to U's V2, the printed 28 ohm) across
    C-B (V1) or C-A (V2): U's low cut within 2.8 dB from 50 to 600 Hz (measured 2.5)."""
    f, e = _against("U", curve, pos)
    k = (f >= 50) & (f <= 600)
    assert np.max(np.abs(e[k])) < 2.8

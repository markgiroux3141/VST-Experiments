"""The RCA 77-DX's acoustic labyrinth in a ribbon motor's network (docs/CHAINS_PLAN.md WP7
step 4): the `line` element kind against a lossy line's input impedance, its matched end,
the shutter's stops, and Olson's polydirectional circuit (Proc. IRE 32, 1944, eqs. 6-8;
data/schematics/rca_77dx/README.md "olson1944") in its three limits: the aperture closed a
pressure ribbon, resistance controlled by the damped pipe; wide open the velocity
microphone; its inertance M2 = r3 d / c a cardioid."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from varimu.circuit import parts
from varimu.devices import moving_coil as mc
from varimu.devices import ribbon
from varimu.devices.capsule import C_AIR, P0, RHO_AIR
from varimu.mics import networks


def _impedance(els: list[dict], a: str, f: np.ndarray) -> np.ndarray:
    """The impedance from node `a` to the ambient of compiled R / L / C elements (a small
    nodal solve, independent of the circuit code)."""
    nodes = sorted({x for e in els for x in (e["a"], e["b"])} - {"0"})
    idx = {n: k for k, n in enumerate(nodes)}
    out = np.zeros(len(f), complex)
    for i, fk in enumerate(f):
        s = 2j * math.pi * fk
        y = np.zeros((len(nodes), len(nodes)), complex)
        for e in els:
            v = e["value"]
            g = {"R": 1 / v, "L": 1 / (s * v), "C": s * v}[e["kind"]]
            for p, q in ((e["a"], e["b"]), (e["b"], e["a"])):
                if p != "0":
                    y[idx[p], idx[p]] += g
                    if q != "0":
                        y[idx[p], idx[q]] -= g
        rhs = np.zeros(len(nodes), complex)
        rhs[idx[a]] = 1.0
        out[i] = np.linalg.solve(y, rhs)[idx[a]]
    return out


def _zk(area, sigma, phi, alpha, gamma_p, f):
    """Zwikker & Kosten's line constants per length: series Z', shunt Y'."""
    w = 2 * math.pi * f
    z = sigma / area + 1j * w * RHO_AIR * alpha / (phi * area)
    y = 1j * w * phi * area / (gamma_p * P0)
    return z, y


LINE = {"name": "lab", "kind": "line", "a": "m", "radius_m": 3.75e-3, "length_m": 0.5,
        "sections": 400, "flow_resistivity_pa_s_m2": 3000.0, "porosity": 0.98,
        "tortuosity": 1.05, "polytropic": 1.0}  # fmt: skip


def test_line_is_a_lossy_line():
    """A closed stuffed pipe as 400 uniform sections: Z0 coth(gamma L) within 0.1% to 2 kHz
    (a section is 1.25 mm: second order in it)."""
    e = dict(LINE)
    area = math.pi * e["radius_m"] ** 2
    f = np.geomspace(20, 2000, 25)
    z, y = _zk(area, e["flow_resistivity_pa_s_m2"], e["porosity"], e["tortuosity"], 1.0, f)
    z0, gam = np.sqrt(z / y), np.sqrt(z * y)
    exact = z0 / np.tanh(gam * e["length_m"])
    got = _impedance(mc.compile_element(e), "m", f)
    assert np.max(np.abs(got / exact - 1)) < 1e-3


def test_matched_line_and_grading():
    """A matched end: the high-frequency characteristic resistance. Graded sections sum to
    the length, the last `grading` times the first. 12 uniform sections follow 400 on 5 cm
    of light stuffing within 0.35 dB to 6 kHz and 3 dB to 15 kHz (a section near a tenth of
    the wavelength there); graded ones, whose last sections are longer, don't."""
    e = {**LINE, "end": "matched", "length_m": 0.05, "sections": 400}
    els = mc.compile_element(e)
    area = math.pi * e["radius_m"] ** 2
    z0_hf = math.sqrt(RHO_AIR * e["tortuosity"] * 1.0 * P0) / (e["porosity"] * area)
    assert els[-1]["name"] == "lab_end"
    assert els[-1]["value"] == pytest.approx(z0_hf, rel=1e-12)
    # adiabatic, no stuffing: rho c / S
    plain = mc.compile_element({"name": "p", "kind": "line", "a": "m", "radius_m": 3.75e-3,
                                "length_m": 0.05, "sections": 4, "end": "matched"})  # fmt: skip
    assert plain[-1]["value"] == pytest.approx(RHO_AIR * C_AIR / area, rel=2e-3)
    assert all(x["kind"] != "R" for x in plain[:-1])
    dx = mc.line_sections(0.05, 12, 4.0)
    assert sum(dx) == pytest.approx(0.05, rel=1e-14)
    assert dx[-1] / dx[0] == pytest.approx(4.0, rel=1e-12)
    f = np.geomspace(50, 15000, 30)
    fine = _impedance(els, "m", f)
    d = 20 * np.log10(np.abs(_impedance(mc.compile_element({**e, "sections": 12}), "m", f) / fine))
    assert np.max(np.abs(d[f <= 6000])) < 0.35
    assert np.max(np.abs(d)) < 3.0
    graded = _impedance(mc.compile_element({**e, "sections": 12, "grading": 4.0}), "m", f)
    assert np.max(np.abs(20 * np.log10(np.abs(graded / fine)))) > 2.0
    with pytest.raises(ValueError, match="far node"):
        mc.compile_element({**e, "b": "x"})
    with pytest.raises(ValueError, match="end"):
        mc.compile_element({**e, "end": "shut"})


def test_open_line_into_a_node():
    """An open far end ends on `b` half a section past the last compliance; a short open
    empty pipe into the ambient is its air mass rho l / S."""
    e = {"name": "o", "kind": "line", "a": "m", "b": "0", "radius_m": 3e-3, "length_m": 0.01,
         "sections": 4, "end": "open"}  # fmt: skip
    els = mc.compile_element(e)
    assert sum(x["kind"] == "C" for x in els) == 4
    f = np.array([100.0])
    area = math.pi * 9e-6
    z = _impedance(els, "m", f)[0]
    assert z.imag / (2 * math.pi * 100) == pytest.approx(RHO_AIR * 0.01 / area, rel=1e-3)
    to_x = mc.compile_element({**e, "b": "x"})
    assert to_x[-1]["b"] == "x" and to_x[-1]["kind"] == "L"


# --- Olson's circuit -------------------------------------------------------------------------

D_M = 0.025  # the path between the entries (plane-wave entries, no body)
R3 = RHO_AIR * C_AIR / (math.pi * 3.75e-3**2)  # the damped pipe: a 7.5 mm pipe's rho c / S


def _olson(apertures) -> dict:
    """A 77-DX-sized ribbon (ib2: 2 in x 0.054 in) on Olson's circuit: the ribbon from the
    front pressure to the node behind it, the damped pipe a pure resistance r3 to the
    ambient, the aperture (stops: `apertures`, acoustic masses or None) to the rear."""
    return {
        "ribbon": {"length_m": 50.8e-3, "width_m": 1.37e-3, "thickness_m": 1.8e-6,
                   "density_kg_m3": 2700.0, "resistivity_ohm_m": 2.65e-8, "corrugation": 1.1,
                   "resonance_hz": 10.0, "q": 2.0, "modes": 1},
        "magnet": {"b_gap_t": 0.7},
        "leads": {"r_ohm": 0.0, "l_h": 5e-8},
        "network": [
            {"name": "load_f", "kind": "acoustic", "a": "front", "b": "f", "m_kg_m4": 30.0},
            {"name": "rib", "kind": "ribbon", "a": "f", "b": "r"},
            {"name": "pipe", "kind": "acoustic", "a": "r", "r_pa_s_m3": R3},
            {"name": "ap", "kind": "acoustic", "a": "r", "b": "rear",
             "stops": [None if m is None else {"m_kg_m4": m} for m in apertures]},
        ],
    }  # fmt: skip


def _motor(g: dict) -> mc.MovingCoil:
    return mc.moving_coil_from_data(
        {"name": "T", "kind": "ribbon_motor", "lumped": ribbon.compile_network(g)},
        kind="ribbon_motor",
    )


def _plane(c: mc.MovingCoil, f: np.ndarray, theta_deg: float) -> np.ndarray:
    k = 2 * np.pi * f / C_AIR
    ct = math.cos(math.radians(theta_deg))
    entries = (np.exp(0.5j * k * D_M * ct), np.exp(-0.5j * k * D_M * ct))
    return networks.moving_coil_response(c, f, entries)


def _db(x) -> np.ndarray:
    return 20 * np.log10(np.abs(x))


M_CARDIOID = R3 * D_M / C_AIR  # Olson: X ~ p1 Z2 + Z3 (p1 - p2), the rear's null


def test_stops_compile_and_pick():
    c = _motor(_olson([None, M_CARDIOID, 1.0]))
    assert ribbon.stops(c) == [1, 2]
    assert [e.name for e in c.elements if e.stop == 1] == ["ap_s1"]
    for k, n in ((0, 0), (1, 1), (2, 1)):
        at = ribbon.at_stop(c, k)
        assert sum(e.name.startswith("ap_") for e in at.elements) == n
        assert all(e.stop is None for e in at.elements)
    with pytest.raises(ValueError, match="pick a stop"):
        ribbon.at_stop(c, None)
    with pytest.raises(ValueError, match="needs one picked"):
        parts.moving_coil("RB", "f", "r", "p", "0", c)
    plain = copy.deepcopy(_olson([None]))
    plain["network"][-1] = {"name": "ap", "kind": "acoustic", "a": "r", "b": "rear",
                            "m_kg_m4": 1.0}  # fmt: skip
    pc = _motor(plain)
    assert ribbon.at_stop(pc, None) is pc
    with pytest.raises(ValueError, match="no stops"):
        ribbon.at_stop(pc, 0)


def test_olsons_limits():
    """Closed: a pressure ribbon, the same from every direction and flat where the pipe's
    resistance dominates the ribbon's mass (X = p1 / (Z1 + Z3)). Wide open: the velocity
    microphone, its 90-degree null and the rear equal to the front. The aperture's
    inertance r3 d / c: the cardioid, its rear null 25 dB down to 400 Hz (the condition
    is first order in k d: at 1 kHz, k d 0.46, 15 dB), its 90 degrees -6 dB, flat on
    axis; between the two a rear lobe."""
    c = _motor(_olson([None, M_CARDIOID, 3 * M_CARDIOID, 1e-3]))
    f = np.geomspace(50, 1000, 12)
    closed = ribbon.at_stop(c, 0)
    h0 = _plane(closed, f, 0)
    for th in (90, 180):
        assert np.max(np.abs(_db(_plane(closed, f, th) / h0))) < 1e-9
    assert np.ptp(_db(h0)) < 1.0
    # its level: p1 / (Z1 + r3) against Olson's resistance alone
    fo = ribbon.foil(_olson([None]))
    pressure = fo["bl_tm"] / fo["area_m2"] / R3
    assert abs(h0[0]) == pytest.approx(pressure, rel=0.02)
    wide = ribbon.at_stop(c, 3)
    w0 = _plane(wide, f, 0)
    assert np.max(_db(_plane(wide, f, 90) / w0)) < -40
    assert np.max(np.abs(_db(_plane(wide, f, 180) / w0))) < 0.01
    card = ribbon.at_stop(c, 1)
    k0 = _plane(card, f, 0)
    null = _db(_plane(card, f, 180) / k0)  # Olson's condition is first order in k d
    assert np.max(null[f <= 400]) < -25 and np.max(null) < -15
    assert np.max(np.abs(_db(_plane(card, f, 90) / k0) + 6.02)) < 0.3
    assert np.ptp(_db(k0)) < 1.0
    lobe = ribbon.at_stop(c, 2)
    rear = _db(_plane(lobe, f, 180) / _plane(lobe, f, 0))
    assert np.all((rear > -12) & (rear < -3))

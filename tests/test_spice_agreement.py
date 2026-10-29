"""Python reference models vs. their generated SPICE subcircuits (ngspice).

Skipped when ngspice isn't installed (see CLAUDE.md for the portable install).
"""

import numpy as np
import pytest

from varimu.devices.library import load_device
from varimu.sim import ngspice

try:
    ngspice.find_ngspice()
except ngspice.SimulatorNotFound:
    pytest.skip("ngspice not available", allow_module_level=True)

# Everything is solved as one `.op` with an independent instance per bias point.
# A DC *sweep* would not test the equations. ngspice reports a behavioral source's
# value linearized from the previous sweep point and accepts it after one
# iteration (the error scales with step^2; see CLAUDE.md, known issues). The
# initialization modes of a fresh operating point evaluate the expressions exactly.
# SPICE also adds GMIN (1e-12 S) across junctions, hence the small absolute tolerance.
# RTOL is set by wrdata's output precision (10 significant digits).
ATOL, RTOL = 1e-11, 2e-8
TIGHT = "reltol=1e-12 abstol=1e-16 vntol=1e-13"


def _op(netlist_lines, vectors):
    r = ngspice.run("\n".join(netlist_lines), "op", vectors, options=TIGHT)
    return {v: float(r[v][0]) for v in vectors}


@pytest.mark.parametrize("name", ["6386", "12AX7", "12BH7", "12AY7"])
def test_triode_plate_and_grid_current_agree(name):
    t = load_device(name)
    pts = [(vg, vp) for vg in (-70, -40, -20, -10, -4, -1, 0, 0.5) for vp in range(0, 401, 25)]
    lines = [t.subckt()]
    for k, (vg, vp) in enumerate(pts):
        lines += [
            f"vp{k} p{k} 0 dc {vp}",
            f"vg{k} g{k} 0 dc {vg}",
            f"x{k} p{k} g{k} 0 {t.subckt_name}",
        ]
    r = _op(lines, [f"i(vp{k})" for k in range(len(pts))] + [f"i(vg{k})" for k in range(len(pts))])
    vg, vp = np.array(pts, float).T
    ip = -np.array([r[f"i(vp{k})"] for k in range(len(pts))])
    ig = -np.array([r[f"i(vg{k})"] for k in range(len(pts))])
    np.testing.assert_allclose(ip, t.ip(vg, vp), rtol=RTOL, atol=ATOL, err_msg=f"{name} Ip")
    np.testing.assert_allclose(ig, t.ig(vg), rtol=RTOL, atol=ATOL, err_msg=f"{name} Ig")


@pytest.mark.parametrize("name", ["6973", "6V6GT"])
def test_pentode_agrees(name):
    p = load_device(name)
    pts = [
        (vg, vs, vp)
        for vg in (-60, -40, -25, -15, -5)
        for vs in (150, 250)
        for vp in range(0, 401, 25)
    ]
    lines = [p.subckt()]
    for k, (vg, vs, vp) in enumerate(pts):
        lines += [
            f"vp{k} p{k} 0 dc {vp}",
            f"vs{k} s{k} 0 dc {vs}",
            f"vg{k} g{k} 0 dc {vg}",
            f"x{k} p{k} s{k} g{k} 0 {p.subckt_name}",
        ]
    r = _op(lines, [f"i(vp{k})" for k in range(len(pts))] + [f"i(vs{k})" for k in range(len(pts))])
    vg, vs, vp = np.array(pts, float).T
    ip = -np.array([r[f"i(vp{k})"] for k in range(len(pts))])
    is2 = -np.array([r[f"i(vs{k})"] for k in range(len(pts))])
    np.testing.assert_allclose(ip, p.ip(vg, vs, vp), rtol=RTOL, atol=ATOL)
    np.testing.assert_allclose(is2, p.ig2(vg, vs), rtol=RTOL, atol=ATOL)


@pytest.mark.parametrize("name,vmax", [("GZ34", 60.0), ("5Y3GT", 150.0), ("SI_RECTIFIER", 1.2)])
def test_diodes_agree(name, vmax):
    d = load_device(name)
    v = np.linspace(-5, vmax, 41)
    behavioral = hasattr(d, "subckt")
    lines = [d.subckt() if behavioral else d.model_card()]
    for k, vk in enumerate(v):
        dev = f"x{k} a{k} 0 {d.subckt_name}" if behavioral else f"d{k} a{k} 0 {d.model_name}"
        lines += [f"va{k} a{k} 0 dc {vk}", dev]
    r = _op(lines, [f"i(va{k})" for k in range(len(v))])
    i = -np.array([r[f"i(va{k})"] for k in range(len(v))])
    # Below -3*n*Vt, SPICE's D model replaces the exponential with a cubic
    # approximation (SPICE3 diode reverse region). That differs from pure Shockley
    # by ~2e-11 A, which is physically irrelevant, hence the looser absolute tolerance.
    np.testing.assert_allclose(i, d.i(v), rtol=1e-7, atol=5e-11)


def test_6386_capacitances_in_ac():
    """Grid-driven AC current with the plate at AC ground: jw(Cgk + Cgp), well into cutoff."""
    t = load_device("6386")
    net = t.subckt() + (f"vg g 0 dc -100 ac 1\nvp p 0 dc 0\nx1 p g 0 {t.subckt_name}")
    r = ngspice.run(net, "ac dec 3 1e5 1e7", ["i(vg)"])
    c = -r["i(vg)"].imag / (2 * np.pi * r["scale"])
    np.testing.assert_allclose(c, t.c_gk + t.c_gp, rtol=1e-6)
